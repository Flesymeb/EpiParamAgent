"""Real isolated registry checks: cached observations never declare source versions."""

from pathlib import Path
import hashlib
import pytest
from metaagent import acquisition as acq
from test_acquisition import pdf
import requests


@pytest.fixture
def pool(tmp_path, monkeypatch):
    root = tmp_path / "paper_pool"
    monkeypatch.setenv("METAAGENT_PAPER_POOL", str(root))
    monkeypatch.setattr(
        requests, "get", lambda *a, **kw: pytest.fail("Unexpected acquisition network")
    )
    return root


def snapshot(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def cached_v1(tmp_path):
    doi = "10.1101/2020.03.21.20040329"
    generic = "medrxiv:" + doi
    original = pdf(tmp_path / "source.pdf", doi=doi, posted="March 24, 2020")
    row = {
        "record_id": generic,
        "doi": doi,
        "preprint_version": "v1",
        "version_date": "2020-03-24",
    }
    info = acq.register_pdf(row, original)
    return row, info


def test_unversioned_generic_alias_cache_cannot_backfill_preprint_version(
    tmp_path, pool
):
    row, info = cached_v1(tmp_path)
    before = snapshot(pool)
    bare = {"record_id": row["record_id"], "doi": row["doi"]}
    result = acq.resolve_document(
        bare, tmp_path / "bare", parse=False, allow_network=False
    )
    assert result["record_status"] == "fulltext_unavailable"
    assert "version is undeclared" in result["failure_reason"]
    assert result.get("source_version") is None
    assert snapshot(pool) == before
    # A declared v1 still hits the exact registry and verifies the same bytes.
    explicit = acq.resolve_document(
        row, tmp_path / "explicit", parse=False, allow_network=False
    )
    assert (
        explicit["record_status"] == "pdf_ready" and explicit["source_version"] == "v1"
    )
    assert explicit["access_route"] == "identity_registry_cache"
    assert explicit["pdf_path"] == info["pdf_path"] and snapshot(pool) == before


def test_cache_gate_itself_rejects_before_reading_generic_alias(
    tmp_path, pool, monkeypatch
):
    row, _ = cached_v1(tmp_path)
    original_read = Path.read_text

    def no_registry_read(path, *args, **kwargs):
        if path.is_relative_to(pool):
            pytest.fail("Undeclared version must fail before observing the cache")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", no_registry_read)
    with pytest.raises(ValueError, match="version is undeclared"):
        acq._cached({"record_id": row["record_id"], "doi": row["doi"]})


@pytest.mark.parametrize(
    "declaration",
    [
        {"preprint_version": "v1"},
        {"source_version": "v1"},
        {"version": "1"},
        {"doi": "10.1101/2020.03.21.20040329v1"},
        {
            "fulltext_url": "https://www.medrxiv.org/content/10.1101/2020.03.21.20040329v1.full.pdf"
        },
    ],
)
def test_explicit_preprint_version_forms_keep_cache_hits(tmp_path, pool, declaration):
    row, info = cached_v1(tmp_path)
    before = snapshot(pool)
    request = {"record_id": row["record_id"], "doi": row["doi"], **declaration}
    result = acq.resolve_document(
        request, tmp_path / "explicit", parse=False, allow_network=False
    )
    assert result["record_status"] == "pdf_ready" and result["source_version"] == "v1"
    assert result["pdf_path"] == info["pdf_path"] and snapshot(pool) == before


def test_official_frozen_date_url_cache_remains_usable(tmp_path, pool):
    doi = "10.1101/2020.04.15.20065946"
    row = {
        "record_id": "medrxiv:" + doi,
        "doi": doi,
        "fulltext_url": "https://www.medrxiv.org/content/early/2020/04/19/2020.04.15.20065946.full.pdf",
    }
    original = pdf(tmp_path / "dated.pdf", doi=doi, posted="April 19, 2020")
    info = acq.register_pdf(row, original)
    before = snapshot(pool)
    result = acq.resolve_document(
        row, tmp_path / "dated", parse=False, allow_network=False
    )
    assert (
        result["record_status"] == "pdf_ready"
        and result["source_version"] == "posted-2020-04-19"
    )
    assert result["pdf_path"] == info["pdf_path"] and snapshot(pool) == before


def test_bare_request_cannot_borrow_cached_posted_date(tmp_path, pool):
    doi = "10.1101/2020.03.21.20040329"
    row = {
        "record_id": "medrxiv:" + doi,
        "doi": doi,
        "fulltext_url": "https://www.medrxiv.org/content/early/2020/03/24/2020.03.21.20040329.full.pdf",
    }
    source = pdf(tmp_path / "posted.pdf", doi=doi, posted="March 24, 2020")
    info = acq.register_pdf(row, source)
    assert info["identity"]["version"] == "posted-2020-03-24"
    before = snapshot(pool)
    for name, extra in (("bare", {}), ("operator", {"path": str(source)})):
        request = {"record_id": row["record_id"], "doi": doi, **extra}
        result = acq.resolve_document(
            request, tmp_path / name, parse=False, allow_network=False
        )
        assert result["record_status"] == "fulltext_unavailable"
        assert "version is undeclared" in result["failure_reason"]
        assert result.get("source_version") is None and snapshot(pool) == before
    explicit = acq.resolve_document(
        row, tmp_path / "declared", parse=False, allow_network=False
    )
    assert (
        explicit["record_status"] == "pdf_ready"
        and explicit["source_version"] == "posted-2020-03-24"
    )
    assert snapshot(pool) == before
