"""Bounded PMC cloud and current ID converter discovery, with no external calls."""

import copy
import hashlib
import json
import pytest
import requests
from metaagent import pmc_cloud as cloud

MD5 = "1" * 32


def listing(
    versions=(1,), *, truncated=False, token=None, contents=False, pmcid="PMC123"
):
    nodes = ""
    for version in versions:
        prefix = f"{pmcid}.{version}"
        if contents:
            nodes += f'<Contents><Key>{prefix}/{prefix}.pdf</Key><Size>100</Size><ETag>"{MD5}"</ETag></Contents>'
        else:
            nodes += f"<CommonPrefixes><Prefix>{prefix}/</Prefix></CommonPrefixes>"
    return (
        f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>{cloud.BUCKET}</Name><Prefix>{pmcid}.</Prefix>{nodes}<IsTruncated>{str(truncated).lower()}</IsTruncated>'
        + (f"<NextContinuationToken>{token}</NextContinuationToken>" if token else "")
        + "</ListBucketResult>"
    ).encode()


def metadata(version=1, **changes):
    return {
        "pmcid": "PMC123",
        "version": version,
        "pmid": 321,
        "doi": "10.1234/source",
        "title": "Exact source title",
        "is_pmc_openaccess": True,
        "is_manuscript": False,
        "is_retracted": False,
        "license_code": "CC BY-NC-ND",
        "pdf_url": f"s3://{cloud.BUCKET}/PMC123.{version}/PMC123.{version}.pdf?md5={MD5}",
        **changes,
    }


class Response:
    def __init__(self, data, status=200, headers=None):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.data

    def close(self):
        self.closed = True


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert len(self.calls) <= len(self.responses), (
            "unexpected unbounded extra request"
        )
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


def test_unique_formal_deposit_ready_exact_prefix_anonymous_no_pdf_download():
    responses = [Response(listing(contents=True)), Response(metadata())]
    transport = Transport(*responses)
    result = cloud.discover_pmc_pdf("pmc123", session=transport)
    assert (
        result["status"] == "ready"
        and result["pdf_url"] == cloud.BASE_URL + "PMC123.1/PMC123.1.pdf"
    )
    assert (
        len(transport.calls) == 2
        and transport.calls[0][1]["params"]["prefix"] == "PMC123."
    )
    assert all(not url.endswith(".pdf") for url, _ in transport.calls)
    candidate = result["candidates"][0]
    assert (
        candidate["license_code"] == "CC BY-NC-ND"
        and candidate["is_manuscript"] is False
    )
    assert candidate["pmc_deposit_version"] == 1 and candidate["pdf_md5"] == MD5
    assert "source_version" not in candidate
    for response, attempt in zip(responses, result["attempts"]):
        assert (
            response.closed
            and attempt["response_sha256"] == hashlib.sha256(response.data).hexdigest()
        )
    for _, options in transport.calls:
        assert options["allow_redirects"] is False and options["stream"] is True
        prepared = requests.Request(
            "GET",
            cloud.BASE_URL,
            headers={
                "Authorization": "Bearer must-not-leak",
                "Cookie": "private=must-not-leak",
            },
        ).prepare()
        options["auth"](prepared)
        assert (
            "Authorization" not in prepared.headers and "Cookie" not in prepared.headers
        )


def test_null_license_kept_when_official_openaccess_true():
    result = cloud.discover_pmc_pdf(
        "PMC123",
        session=Transport(Response(listing()), Response(metadata(license_code=None))),
    )
    assert (
        result["status"] == "ready" and result["candidates"][0]["license_code"] is None
    )


def test_manuscript_plus_one_formal_selects_formal_not_highest_number():
    result = cloud.discover_pmc_pdf(
        "PMC123",
        session=Transport(
            Response(listing((1, 9))),
            Response(metadata(1)),
            Response(metadata(9, is_manuscript=True)),
        ),
    )
    assert (
        result["status"] == "ready"
        and result["candidates"][0]["pmc_deposit_version"] == 1
    )


def test_multiple_formal_deposits_pending_even_if_only_one_pdf():
    result = cloud.discover_pmc_pdf(
        "PMC123",
        session=Transport(
            Response(listing((1, 2))),
            Response(metadata(1)),
            Response(metadata(2, pdf_url=None)),
        ),
    )
    assert (
        result["status"] == "pending"
        and result["reason"] == "multiple_non_manuscript_versions"
    )
    assert "pdf_url" not in result


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"pmcid": "PMC999"}, "metadata_identity_or_version_conflict"),
        ({"version": 2}, "metadata_identity_or_version_conflict"),
        ({"version": True}, "metadata_identity_or_version_conflict"),
        ({"is_manuscript": None}, "manuscript_classification_unknown"),
        ({"is_manuscript": True}, "manuscript_only_no_automatic_mapping"),
        ({"is_pmc_openaccess": False}, "openaccess_status_unknown_or_false"),
        ({"is_retracted": True}, "retraction_status_pending"),
        ({"pdf_url": "https://evil.invalid/key.pdf"}, "unsafe_pdf_mapping"),
        (
            {"pdf_url": f"s3://{cloud.BUCKET}/PMC123.2/PMC123.2.pdf"},
            "pdf_version_mapping_conflict",
        ),
        ({"pdf_url": f"s3://{cloud.BUCKET}/PMC123.1/../file.pdf"}, "unsafe_pdf_key"),
        (
            {"pdf_url": f"s3://{cloud.BUCKET}/PMC123.1/file.pdf?api_key=private"},
            "unsafe_pdf_query",
        ),
    ],
)
def test_unknown_conflicting_or_unsafe_metadata_never_auto_selects(changes, reason):
    result = cloud.discover_pmc_pdf(
        "PMC123", session=Transport(Response(listing()), Response(metadata(**changes)))
    )
    assert (
        result["status"] == "pending"
        and result["reason"] == reason
        and "pdf_url" not in result
    )


def test_complete_listing_pagination_and_bounded_truncation():
    first = Response(listing((1,), truncated=True, token="next-token"))
    transport = Transport(
        first,
        Response(listing((2,))),
        Response(metadata(1)),
        Response(metadata(2, is_manuscript=True)),
    )
    result = cloud.discover_pmc_pdf("PMC123", session=transport)
    assert result["status"] == "ready" and result["listing_complete"]
    assert transport.calls[1][1]["params"]["continuation-token"] == "next-token"
    transport = Transport(Response(listing((1,), truncated=True, token="next-token")))
    result = cloud.discover_pmc_pdf("PMC123", session=transport, max_pages=1)
    assert result["reason"] == "listing_page_limit" and len(transport.calls) == 1
    assert "pdf_url" not in result


@pytest.mark.parametrize(
    "response,reason",
    [
        (Response(b"", 302), "redirect_not_allowed"),
        (Response(b"", 403), "http_403"),
        (Response(b"not xml"), "invalid_listing_xml"),
        (Response(b"<!DOCTYPE x><ListBucketResult/>"), "unsafe_listing_xml"),
        (Response(b"<ListBucketResult/>"), "listing_completeness_unknown"),
        (Response(listing(pmcid="PMC1234")), "listing_scope_conflict"),
        (
            Response(b"0123456789", headers={"Content-Length": "10"}),
            "response_too_large",
        ),
        (Response(b"0123456789"), "response_too_large"),
        (
            requests.Timeout("sensitive transport message"),
            "transport_or_response_error",
        ),
    ],
)
def test_transport_schema_and_byte_limits_return_typed_pending(response, reason):
    transport = Transport(response)
    result = cloud.discover_pmc_pdf(
        "PMC123",
        session=transport,
        max_response_bytes=5 if reason == "response_too_large" else 2_097_152,
    )
    assert result["status"] == "pending" and result["reason"] == reason
    assert len(
        transport.calls
    ) == 1 and "sensitive transport message" not in json.dumps(result)


def test_response_deadline_prevents_followup_metadata(monkeypatch):
    ticks = iter([0, 0, 46])
    monkeypatch.setattr(cloud.time, "monotonic", lambda: next(ticks))
    transport = Transport(Response(listing()))
    result = cloud.discover_pmc_pdf("PMC123", session=transport, total_timeout_s=45)
    assert result["reason"] == "total_timeout" and len(transport.calls) == 1


def test_empty_deposit_and_absent_pdf_are_unavailable():
    assert (
        cloud.discover_pmc_pdf("PMC123", session=Transport(Response(listing(()))))[
            "status"
        ]
        == "unavailable"
    )
    result = cloud.discover_pmc_pdf(
        "PMC123",
        session=Transport(Response(listing()), Response(metadata(pdf_url=None))),
    )
    assert (
        result["status"] == "unavailable" and result["reason"] == "no_pdf_in_metadata"
    )


def test_invalid_input_and_version_limit_make_no_guessed_requests():
    transport = Transport()
    for value in ("123", "PMC123/../", "PMC123?private=token", "PMC123.1"):
        result = cloud.discover_pmc_pdf(value, session=transport)
        assert result["reason"] == "invalid_pmcid" and result["pmcid"] is None
    assert not transport.calls
    with pytest.raises(ValueError):
        cloud.discover_pmc_pdf("PMC123", session=transport, max_pages=999)
    transport = Transport(Response(listing((1, 2))))
    assert (
        cloud.discover_pmc_pdf("PMC123", session=transport, max_versions=1)["reason"]
        == "version_limit"
    )
    assert len(transport.calls) == 1


def test_pdf_md5_mismatch_pending_multipart_etag_not_used_as_md5():
    transport = Transport(
        Response(listing(contents=True).replace(MD5.encode(), b"2" * 32)),
        Response(metadata()),
    )
    assert (
        cloud.discover_pmc_pdf("PMC123", session=transport)["reason"]
        == "pdf_checksum_metadata_conflict"
    )
    transport = Transport(
        Response(listing(contents=True).replace(MD5.encode(), b"2" * 32 + b"-2")),
        Response(metadata()),
    )
    assert cloud.discover_pmc_pdf("PMC123", session=transport)["status"] == "ready"


def converter_record(**changes):
    return {
        "requested-id": "321",
        "pmid": 321,
        "doi": "10.1234/source",
        "pmcid": "PMC123",
        "versions": [{"pmcid": "PMC123.1", "current": True}],
        **changes,
    }


def test_converter_exact_dual_binding_current_endpoint_and_witness(monkeypatch):
    monkeypatch.setattr(cloud, "_throttle_ncbi", lambda: None)
    payload = {"status": "ok", "records": [converter_record()]}
    original = copy.deepcopy(payload)
    response = Response(payload)
    transport = Transport(response)
    result = cloud.resolve_pmcid("321", "10.1234/source", session=transport)
    assert result["status"] == "ready" and result["pmcid"] == "PMC123"
    assert (
        transport.calls[0][0]
        == "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
    )
    assert (
        transport.calls[0][1]["params"]["ids"] == "321"
        and transport.calls[0][1]["params"]["idtype"] == "pmid"
    )
    assert transport.calls[0][1]["params"]["versions"] == "yes"
    assert (
        result["metadata_response_sha256"] == hashlib.sha256(response.data).hexdigest()
    )
    assert payload == original
    transport = Transport(
        Response({"records": [converter_record(**{"requested-id": "10.1234/source"})]})
    )
    assert (
        cloud.resolve_pmcid(doi="https://doi.org/10.1234/source", session=transport)[
            "status"
        ]
        == "ready"
    )
    assert transport.calls[0][1]["params"]["idtype"] == "doi"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"requested-id": "999"}, "requested_identifier_mapping_conflict"),
        ({"doi": "10.1234/other"}, "bibliographic_identifier_mapping_conflict"),
        ({"pmid": "999"}, "bibliographic_identifier_mapping_conflict"),
        ({"live": False}, "embargo_or_not_live"),
        ({"live": "false"}, "embargo_or_not_live"),
        ({"live": []}, "live_status_unknown"),
    ],
)
def test_converter_conflict_embargo_never_ready(monkeypatch, changes, reason):
    monkeypatch.setattr(cloud, "_throttle_ncbi", lambda: None)
    result = cloud.resolve_pmcid(
        "321",
        "10.1234/source",
        session=Transport(Response({"records": [converter_record(**changes)]})),
    )
    assert (
        result["status"] == "pending"
        and result["reason"] == reason
        and "pmcid" not in result
    )


def test_converter_ambiguous_and_bad_identifier_do_not_guess(monkeypatch):
    monkeypatch.setattr(cloud, "_throttle_ncbi", lambda: None)
    result = cloud.resolve_pmcid(
        "321",
        session=Transport(
            Response(
                {"records": [converter_record(), converter_record(pmcid="PMC999")]}
            )
        ),
    )
    assert result["reason"] == "ambiguous_pmc_mapping" and "pmcid" not in result
    transport = Transport()
    assert (
        cloud.resolve_pmcid("PMC123", session=transport)["reason"]
        == "invalid_bibliographic_identifier"
    )
    assert not transport.calls


def test_converter_reuses_ncbi_throttle_not_llm_gate(monkeypatch):
    from tools.pubmed.client import PubMedClient

    called = []
    monkeypatch.setattr(
        PubMedClient, "_throttle", lambda state: called.append(state._min_interval)
    )
    transport = Transport(Response({"records": []}))
    assert cloud.resolve_pmcid("321", session=transport)["status"] == "unavailable"
    assert called == [0.34]


def test_pubmed_parse_and_adapter_retain_only_own_pmcid(monkeypatch):
    import xml.etree.ElementTree as ET
    from tools.pubmed.client import PubMedClient
    from tools.literature.sources import search

    article = ET.fromstring(
        '<PubmedArticle><MedlineCitation><PMID>321</PMID><Article><ArticleTitle>Source title</ArticleTitle><Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pmc">PMC123</ArticleId></ArticleIdList><ReferenceList><Reference><ArticleIdList><ArticleId IdType="pmc">PMC999</ArticleId></ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle>'
    )
    paper = PubMedClient()._parse_article(article)
    assert paper.pmcid == "PMC123" and paper.to_dict()["pmcid"] == "PMC123"

    def fake_search(client, *args, **kwargs):
        client.last_total = 1
        return [paper]

    monkeypatch.setattr(PubMedClient, "search", fake_search)
    assert search("pubmed", "unchanged native query", 1)[0][0]["pmcid"] == "PMC123"


def test_converter_malformed_status_is_typed_not_a_raw_error(monkeypatch):
    monkeypatch.setattr(cloud, "_throttle_ncbi", lambda: None)
    result = cloud.resolve_pmcid(
        "321", session=Transport(Response({"status": [], "records": []}))
    )
    assert (
        result["status"] == "pending" and result["reason"] == "converter_service_error"
    )
