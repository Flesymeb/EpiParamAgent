"""Bounded anonymous PMC cloud discovery; no PDF downloading or version guessing.

Rules: https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/ and the bucket README.txt.
PMC deposit numbers are not recency rankings or preprint-version mappings.
"""

from __future__ import annotations
import hashlib
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, unquote, urlsplit
import requests

BUCKET = "pmc-oa-opendata"
HOST = BUCKET + ".s3.amazonaws.com"
BASE_URL = "https://" + HOST + "/"
IDCONV_URL = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
_THROTTLE_LOCK = threading.Lock()
_THROTTLE_STATE = SimpleNamespace(_min_interval=0.34, _last_request_ts=None)


class _Anonymous(requests.auth.AuthBase):
    def __call__(self, request):
        request.headers.pop("Authorization", None)
        request.headers.pop("Cookie", None)
        return request


class _DiscoveryError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _Budget:
    def __init__(self, result, session, timeout_s, total_timeout_s, max_response_bytes):
        if (
            not isinstance(timeout_s, (int, float))
            or isinstance(timeout_s, bool)
            or not 0 < timeout_s <= 30
            or not isinstance(total_timeout_s, (int, float))
            or isinstance(total_timeout_s, bool)
            or not 0 < total_timeout_s <= 120
            or type(max_response_bytes) is not int
            or not 1 <= max_response_bytes <= 2_097_152
        ):
            raise ValueError("PMC request budgets exceed supported finite bounds")
        self.result, self.client = result, session or requests
        self.timeout_s, self.deadline, self.cap = (
            timeout_s,
            time.monotonic() + total_timeout_s,
            max_response_bytes,
        )

    def fetch(self, url, params=None):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {HOST, "pmc.ncbi.nlm.nih.gov"}
            or parsed.username
            or parsed.password
        ):
            raise _DiscoveryError("unsafe_request_host")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _DiscoveryError("total_timeout")
        event = {
            "url": url,
            "parameters": params or {},
            "http_status": None,
            "response_sha256": None,
            "bytes": 0,
            "status": "pending",
        }
        self.result["attempts"].append(event)
        response = None
        chunks = []
        try:
            response = self.client.get(
                url,
                params=params,
                timeout=min(self.timeout_s, remaining),
                allow_redirects=False,
                stream=True,
                auth=_Anonymous(),
                headers={
                    "Authorization": None,
                    "Cookie": "",
                    "User-Agent": "MetaAgent-Epi PMC metadata discovery",
                },
            )
            event["http_status"] = response.status_code
            if 300 <= response.status_code < 400:
                raise _DiscoveryError("redirect_not_allowed")
            if response.status_code != 200:
                raise _DiscoveryError("http_" + str(response.status_code))
            length = response.headers.get("Content-Length")
            if length and int(length) > self.cap:
                raise _DiscoveryError("response_too_large")
            for chunk in response.iter_content(chunk_size=4096):
                if time.monotonic() >= self.deadline:
                    raise _DiscoveryError("total_timeout")
                if not chunk:
                    continue
                event["bytes"] += len(chunk)
                if event["bytes"] > self.cap:
                    raise _DiscoveryError("response_too_large")
                chunks.append(chunk)
            data = b"".join(chunks)
            event.update(
                response_sha256=hashlib.sha256(data).hexdigest(), status="complete"
            )
            return data, event
        except _DiscoveryError as exc:
            event.update(status="failed", reason=exc.code)
            raise
        except (requests.RequestException, ValueError, TypeError, OSError) as exc:
            event.update(
                status="failed",
                reason="transport_or_response_error",
                error_type=type(exc).__name__,
            )
            raise _DiscoveryError("transport_or_response_error") from exc
        finally:
            if response is not None:
                response.close()


def _child(node, name):
    return next((n.text or "" for n in node if n.tag.rsplit("}", 1)[-1] == name), "")


def _pdf_location(value, prefix):
    if not isinstance(value, str):
        raise _DiscoveryError("invalid_pdf_mapping")
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.port or parsed.fragment:
        raise _DiscoveryError("unsafe_pdf_mapping")
    if not (
        (parsed.scheme == "s3" and parsed.netloc == BUCKET)
        or (parsed.scheme == "https" and parsed.netloc == HOST)
    ):
        raise _DiscoveryError("unsafe_pdf_mapping")
    key = unquote(parsed.path.lstrip("/"))
    if not key.startswith(prefix + "/"):
        raise _DiscoveryError("pdf_version_mapping_conflict")
    filename = key[len(prefix) + 1 :]
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.pdf", filename)
        or ".." in filename
        or "%" in key
    ):
        raise _DiscoveryError("unsafe_pdf_key")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) - {"md5"} or any(len(v) != 1 for v in query.values()):
        raise _DiscoveryError("unsafe_pdf_query")
    md5 = query.get("md5", [None])[0]
    if md5 is not None and not re.fullmatch(r"[a-fA-F0-9]{32}", md5):
        raise _DiscoveryError("invalid_pdf_md5")
    return key, BASE_URL + quote(key, safe="/"), md5.lower() if md5 else None


def discover_pmc_pdf(
    pmcid,
    *,
    session=None,
    timeout_s=12,
    total_timeout_s=45,
    max_pages=2,
    max_keys=100,
    max_versions=8,
    max_response_bytes=2_097_152,
):
    """Discover exact PMCID deposits; only one clear non-manuscript yields ready.

    No PDFs are downloaded. License null is retained when official metadata says
    open access. Callers must still validate title/DOI and any requested source
    version; ``pmc_deposit_version`` cannot prove a medRxiv or publisher version.
    """
    result = {
        "route": "pmc_cloud_pdf",
        "pmcid": None,
        "status": "pending",
        "reason": None,
        "candidates": [],
        "versions": [],
        "attempts": [],
        "listing_complete": False,
        "version_semantics": "PMC processing identifier, not recency or preprint version",
    }
    if not isinstance(pmcid, str) or not re.fullmatch(
        r"PMC[1-9][0-9]{0,11}", pmcid.strip(), re.I
    ):
        result["reason"] = "invalid_pmcid"
        return result
    pmcid = pmcid.strip().upper()
    result["pmcid"] = pmcid
    if (
        type(max_pages) is not int
        or not 1 <= max_pages <= 5
        or type(max_keys) is not int
        or not 1 <= max_keys <= 100
        or type(max_versions) is not int
        or not 1 <= max_versions <= 16
    ):
        raise ValueError("PMC listing budgets exceed supported finite bounds")
    budget = _Budget(result, session, timeout_s, total_timeout_s, max_response_bytes)
    try:
        objects = {}
        prefixes = set()
        tokens = set()
        token = None
        for _ in range(max_pages):
            params = {
                "list-type": "2",
                "prefix": pmcid + ".",
                "delimiter": "/",
                "max-keys": max_keys,
            }
            if token:
                params["continuation-token"] = token
            data, _event = budget.fetch(BASE_URL, params)
            if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise _DiscoveryError("unsafe_listing_xml")
            try:
                tree = ET.fromstring(data)
            except ET.ParseError as exc:
                raise _DiscoveryError("invalid_listing_xml") from exc
            if tree.tag.rsplit("}", 1)[-1] != "ListBucketResult":
                raise _DiscoveryError("invalid_listing_schema")
            if _child(tree, "Prefix") not in {"", pmcid + "."} or _child(
                tree, "Name"
            ) not in {"", BUCKET}:
                raise _DiscoveryError("listing_scope_conflict")
            for entry in tree:
                kind = entry.tag.rsplit("}", 1)[-1]
                if kind not in {"Contents", "CommonPrefixes"}:
                    continue
                key = _child(entry, "Key" if kind == "Contents" else "Prefix")
                match = re.fullmatch(
                    re.escape(pmcid) + r"\.([1-9][0-9]{0,8})/(.*)", key
                )
                if not match or ".." in key or "%" in key or "\\" in key:
                    raise _DiscoveryError("listing_key_scope_conflict")
                prefix = key.split("/", 1)[0]
                prefixes.add(prefix)
                if kind == "Contents":
                    value = {
                        "key": key,
                        "size": _child(entry, "Size"),
                        "etag": _child(entry, "ETag").strip('"'),
                    }
                    if key in objects and objects[key] != value:
                        raise _DiscoveryError("listing_object_conflict")
                    objects[key] = value
            if len(prefixes) > max_versions:
                raise _DiscoveryError("version_limit")
            truncated = _child(tree, "IsTruncated").strip().lower()
            if truncated == "false":
                result["listing_complete"] = True
                break
            if truncated != "true":
                raise _DiscoveryError("listing_completeness_unknown")
            token = _child(tree, "NextContinuationToken")
            if (
                not token
                or len(token) > 4096
                or any(c in token for c in "\r\n")
                or token in tokens
            ):
                raise _DiscoveryError("invalid_continuation_token")
            tokens.add(token)
        if not result["listing_complete"]:
            raise _DiscoveryError("listing_page_limit")
        if not prefixes:
            result.update(status="unavailable", reason="no_article_deposit")
            return result
        formal = []
        for prefix in sorted(prefixes):
            deposit_version = int(prefix.rsplit(".", 1)[1])
            metadata_url = BASE_URL + prefix + "/" + prefix + ".json"
            data, event = budget.fetch(metadata_url)
            try:
                metadata = json.loads(data)
            except (ValueError, UnicodeDecodeError) as exc:
                raise _DiscoveryError("invalid_metadata_json") from exc
            if not isinstance(metadata, dict):
                raise _DiscoveryError("invalid_metadata_schema")
            if (
                metadata.get("pmcid") != pmcid
                or type(metadata.get("version")) is not int
                or metadata["version"] != deposit_version
            ):
                raise _DiscoveryError("metadata_identity_or_version_conflict")
            item = {
                "pmc_deposit_version": deposit_version,
                "metadata": metadata,
                "metadata_url": metadata_url,
                "metadata_response_sha256": event["response_sha256"],
                "license_code": metadata.get("license_code"),
                "is_manuscript": metadata.get("is_manuscript"),
            }
            result["versions"].append(item)
            if type(metadata.get("is_manuscript")) is not bool:
                raise _DiscoveryError("manuscript_classification_unknown")
            if metadata["is_manuscript"]:
                continue
            if metadata.get("is_pmc_openaccess") is not True:
                raise _DiscoveryError("openaccess_status_unknown_or_false")
            if metadata.get("is_retracted") is not False:
                raise _DiscoveryError("retraction_status_pending")
            formal.append(item)
            if metadata.get("pdf_url") in (None, ""):
                continue
            try:
                key, url, md5 = _pdf_location(metadata["pdf_url"], prefix)
            except ValueError as exc:
                raise _DiscoveryError("unsafe_pdf_mapping") from exc
            listed = objects.get(key)
            if (
                listed
                and re.fullmatch(r"[a-fA-F0-9]{32}", listed["etag"])
                and md5
                and listed["etag"].lower() != md5
            ):
                raise _DiscoveryError("pdf_checksum_metadata_conflict")
            result["candidates"].append(
                {
                    **item,
                    "key": key,
                    "url": url,
                    "pdf_url": url,
                    "pdf_md5": md5,
                    "listing_object": listed,
                    "selection_basis": "non_manuscript_openaccess_deposit",
                }
            )
        if len(formal) > 1:
            raise _DiscoveryError("multiple_non_manuscript_versions")
        if not formal:
            raise _DiscoveryError("manuscript_only_no_automatic_mapping")
        if not result["candidates"]:
            result.update(status="unavailable", reason="no_pdf_in_metadata")
            return result
        result.update(
            status="ready",
            reason="unique_non_manuscript_deposit",
            pdf_url=result["candidates"][0]["url"],
        )
    except _DiscoveryError as exc:
        result.update(status="pending", reason=exc.code)
        result.pop("pdf_url", None)
    return result


def _doi(value):
    return re.sub(
        r"^https?://(?:dx\.)?doi\.org/", "", str(value or "").strip(), flags=re.I
    ).lower()


def _throttle_ncbi():
    # Reuse the existing anonymous PubMed interval implementation without loading
    # an API key/session or involving the LLM request gate.
    from tools.pubmed.client import PubMedClient

    with _THROTTLE_LOCK:
        PubMedClient._throttle(_THROTTLE_STATE)


def resolve_pmcid(
    pmid=None,
    doi=None,
    *,
    session=None,
    timeout_s=12,
    total_timeout_s=45,
    max_response_bytes=1_048_576,
):
    """Resolve an exact PMID/DOI through the current official ID converter.

    Both supplied identifiers must be present and agree in the returned record.
    No numeric PMID is reinterpreted as a PMCID. Version/live metadata is retained
    as a witness, not selected or translated into a preprint version.
    """
    result = {
        "route": "pmc_id_converter",
        "status": "pending",
        "reason": None,
        "attempts": [],
        "records": [],
    }
    pmid = str(pmid or "").strip()
    doi = _doi(doi)
    if (
        pmid
        and not re.fullmatch(r"[1-9][0-9]*", pmid)
        or doi
        and not re.fullmatch(r"10\.\d{4,9}/[^\s,?#]+", doi)
    ):
        result["reason"] = "invalid_bibliographic_identifier"
        return result
    if not pmid and not doi:
        result["reason"] = "missing_bibliographic_identifier"
        return result
    query = pmid or doi
    kind = "pmid" if pmid else "doi"
    params = {
        "ids": query,
        "idtype": kind,
        "format": "json",
        "versions": "yes",
        "tool": "MetaAgent-Epi",
    }
    budget = _Budget(result, session, timeout_s, total_timeout_s, max_response_bytes)
    try:
        _throttle_ncbi()
        data, event = budget.fetch(IDCONV_URL, params)
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise _DiscoveryError("invalid_converter_json") from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("records"), list
        ):
            raise _DiscoveryError("invalid_converter_schema")
        if payload.get("status") is not None and payload.get("status") != "ok":
            raise _DiscoveryError("converter_service_error")
        records = payload["records"]
        result["records"] = records
        if not records:
            result.update(status="unavailable", reason="no_pmc_mapping")
            return result
        if len(records) != 1:
            raise _DiscoveryError("ambiguous_pmc_mapping")
        row = records[0]
        if not isinstance(row, dict):
            raise _DiscoveryError("invalid_converter_record")
        requested = str(row.get("requested-id") or "")
        if requested != query if pmid else _doi(requested) != doi:
            raise _DiscoveryError("requested_identifier_mapping_conflict")
        if (
            pmid
            and str(row.get("pmid") or "") != pmid
            or doi
            and _doi(row.get("doi")) != doi
        ):
            raise _DiscoveryError("bibliographic_identifier_mapping_conflict")
        pmcid = row.get("pmcid")
        if not isinstance(pmcid, str) or not re.fullmatch(
            r"PMC[1-9][0-9]{0,11}", pmcid
        ):
            result.update(status="unavailable", reason="no_exact_pmcid")
            return result
        live = row.get("live")
        if live is False or isinstance(live, str) and live in {"false", "no"}:
            raise _DiscoveryError("embargo_or_not_live")
        if (
            live is not None
            and live is not True
            and not (isinstance(live, str) and live in {"true", "yes"})
        ):
            raise _DiscoveryError("live_status_unknown")
        result.update(
            status="ready",
            reason="exact_identifier_mapping",
            pmcid=pmcid,
            metadata=row,
            metadata_response_sha256=event["response_sha256"],
        )
    except _DiscoveryError as exc:
        result.update(status="pending", reason=exc.code)
        result.pop("pmcid", None)
    return result
