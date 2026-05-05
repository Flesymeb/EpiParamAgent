"""Tier-2 retrieval agent for cascade screening.

When an LLM screening decision has low confidence, this module attempts to
retrieve additional information (full-text HTML, OA PDF text, enriched metadata)
from multiple sources to enable a more informed re-evaluation.

Priority order (fastest + most legal first):
  1. Semantic Scholar API — openAccessPdf URL
  2. Unpaywall — best OA location by DOI
  3. Europe PMC — full-text links
  4. PubMed EFetch — enriched metadata fallback
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RetrievalResult:
    """Result of attempting to retrieve additional content for a paper."""

    pmid: str
    doi: str = ""
    success: bool = False
    source: str = ""  # "semantic_scholar", "unpaywall", "europe_pmc", "pubmed"
    full_text_snippet: str = ""  # up to ~2000 chars of retrieved text
    enriched_abstract: str = ""  # structured/labeled abstract if available
    pdf_url: str = ""
    html_url: str = ""
    error: str = ""
    elapsed_ms: float = 0.0


# ---------------------------------------------------------------------------
# Source-specific retrievers
# ---------------------------------------------------------------------------


async def _try_semantic_scholar(
    client: httpx.AsyncClient, doi: str, pmid: str
) -> Optional[dict[str, Any]]:
    """Query Semantic Scholar API for open access PDF links."""
    if doi:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
    elif pmid:
        url = f"https://api.semanticscholar.org/graph/v1/paper/PMID:{pmid}"
    else:
        return None

    params = {"fields": "title,abstract,openAccessPdf,isOpenAccess,publicationTypes"}
    try:
        resp = await client.get(f"{url}?{urlencode(params)}", timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            return data
        elif resp.status_code == 429:
            logger.warning("Semantic Scholar rate limited, waiting 1s")
            await _sleep(1.0)
            return None
    except Exception as e:
        logger.debug(f"Semantic Scholar error: {e}")
    return None


async def _try_unpaywall(
    client: httpx.AsyncClient, doi: str, email: str = ""
) -> Optional[dict[str, Any]]:
    """Query Unpaywall API for best OA location by DOI."""
    if not doi:
        return None
    url = f"https://api.unpaywall.org/v2/{doi}"
    params = {}
    if email:
        params["email"] = email
    try:
        resp = await client.get(url, params=params, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            return data
        elif resp.status_code == 404:
            return None  # DOI not found, expected
    except Exception as e:
        logger.debug(f"Unpaywall error: {e}")
    return None


async def _try_europe_pmc(
    client: httpx.AsyncClient, doi: str, pmid: str
) -> Optional[dict[str, Any]]:
    """Query Europe PMC API for full-text links and enriched metadata."""
    if pmid:
        query = f"ext_id:{pmid} src:med"
    elif doi:
        query = f"doi:{doi}"
    else:
        return None

    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = {
        "query": query,
        "format": "json",
        "resultType": "core",
        "pageSize": 1,
    }
    try:
        resp = await client.get(url, params=params, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("resultList", {}).get("result", [])
            if results:
                return results[0]
    except Exception as e:
        logger.debug(f"Europe PMC error: {e}")
    return None


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------


def _extract_snippet_from_html(html_content: str, max_chars: int = 2000) -> str:
    """Extract a meaningful text snippet from HTML, prioritizing methods section."""
    import re

    # Remove scripts, styles, and navigation
    cleaned = re.sub(
        r"<(script|style|nav|header|footer)[^>]*>.*?</\1>",
        "",
        html_content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", cleaned)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Try to find methods section
    methods_patterns = [
        r"(?:Methods|Method|METHODS)\b(.*?)(?:\b(?:Results|RESULTS|Discussion|DISCUSSION)\b|$)",
        r"(?:Materials and methods|MATERIALS AND METHODS)\b(.*?)(?:\b(?:Results|RESULTS)\b|$)",
    ]
    for pattern in methods_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            methods_text = match.group(1).strip()
            if len(methods_text) > 200:
                return methods_text[:max_chars]

    # Fall back to beginning of body text (skip abstract-like first paragraphs)
    return text[:max_chars]


def _extract_structured_abstract_from_ss(data: dict[str, Any]) -> str:
    """Extract abstract from Semantic Scholar result."""
    abstract = (data.get("abstract") or "").strip()
    if abstract and len(abstract) > 50:
        return abstract
    return ""


async def _fetch_html_text(
    client: httpx.AsyncClient, url: str, max_chars: int = 2000
) -> str:
    """Fetch HTML content from a URL and extract text snippet."""
    try:
        resp = await client.get(url, timeout=15.0, follow_redirects=True)
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type:
                return _extract_snippet_from_html(resp.text, max_chars)
    except Exception as e:
        logger.debug(f"HTML fetch error for {url}: {e}")
    return ""


# ---------------------------------------------------------------------------
# Main retrieval orchestrator
# ---------------------------------------------------------------------------


async def _sleep(seconds: float) -> None:
    """Awaitable sleep."""
    await _get_async_sleep()(seconds)


def _get_async_sleep():
    import asyncio
    return asyncio.sleep


async def retrieve_enriched_content(
    pmid: str = "",
    doi: str = "",
    *,
    client: Optional[httpx.AsyncClient] = None,
    unpaywall_email: str = "",
    sources: Optional[list[str]] = None,
) -> RetrievalResult:
    """Attempt to retrieve enriched content for a paper from multiple sources.

    Args:
        pmid: PubMed ID.
        doi: Digital Object Identifier.
        client: Optional shared httpx.AsyncClient.
        unpaywall_email: Email for Unpaywall API (politeness).
        sources: Which sources to try, in order. Default: all.

    Returns:
        RetrievalResult with the best available content.
    """
    if sources is None:
        sources = ["semantic_scholar", "unpaywall", "europe_pmc"]

    result = RetrievalResult(pmid=pmid, doi=doi)
    start = time.perf_counter()

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    try:
        pdf_url = ""
        enriched_abstract = ""

        # 1. Semantic Scholar — fastest, direct OA PDF links
        if "semantic_scholar" in sources:
            ss_data = await _try_semantic_scholar(client, doi, pmid)
            if ss_data:
                oa = ss_data.get("openAccessPdf") or {}
                pdf_url = (oa.get("url") or "").strip()
                enriched_abstract = _extract_structured_abstract_from_ss(ss_data)
                if pdf_url or enriched_abstract:
                    result.source = "semantic_scholar"
                    result.success = True
                    result.enriched_abstract = enriched_abstract
                    result.pdf_url = pdf_url if pdf_url else ""
                    logger.debug(f"SS hit for PMID={pmid}: pdf={bool(pdf_url)}, abstract_len={len(enriched_abstract)}")

        # 2. Unpaywall — best OA location by DOI
        if not result.success and "unpaywall" in sources and doi:
            uw_data = await _try_unpaywall(client, doi, email=unpaywall_email)
            if uw_data:
                best = uw_data.get("best_oa_location") or {}
                if best:
                    result.pdf_url = (best.get("url_for_pdf") or best.get("url") or "").strip()
                    result.html_url = (best.get("url_for_landing_page") or "").strip()
                    result.source = "unpaywall"
                    result.success = bool(result.pdf_url or result.html_url)

        # 3. Europe PMC — enriched metadata + full-text links
        if not result.success and "europe_pmc" in sources:
            epmc_data = await _try_europe_pmc(client, doi, pmid)
            if epmc_data:
                epmc_abstract = (epmc_data.get("abstractText") or "").strip()
                if epmc_abstract and len(epmc_abstract) > 100:
                    result.enriched_abstract = epmc_abstract
                result.pdf_url = (epmc_data.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url", "") if epmc_data.get("fullTextUrlList") else "")
                has_ft = bool(epmc_data.get("hasFullText"))
                result.source = "europe_pmc"
                result.success = has_ft or bool(epmc_abstract)

        # 4. If we have a PDF or HTML URL, try to fetch text snippet
        if result.success and not result.full_text_snippet:
            target_url = result.pdf_url or result.html_url
            if target_url:
                snippet = await _fetch_html_text(client, target_url)
                if snippet:
                    result.full_text_snippet = snippet

        # 5. If we have enriched_abstract from any source, mark success
        if not result.success and result.enriched_abstract:
            result.success = True

    except Exception as e:
        result.error = str(e)[:500]
        logger.warning(f"Retrieval failed for PMID={pmid}: {e}")

    finally:
        if own_client and client is not None:
            await client.aclose()

    result.elapsed_ms = (time.perf_counter() - start) * 1000
    return result


async def batch_retrieve(
    papers: list[dict[str, Any]],
    *,
    concurrency: int = 5,
    unpaywall_email: str = "",
) -> list[tuple[dict[str, Any], RetrievalResult]]:
    """Retrieve enriched content for multiple uncertain papers concurrently.

    Args:
        papers: List of paper dicts with at least 'PMID' and optionally 'DOI' keys.
        concurrency: Max concurrent retrievals.
        unpaywall_email: Email for Unpaywall API.

    Returns:
        List of (paper, RetrievalResult) tuples in the same order as input.
    """
    import asyncio

    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: list[tuple[dict[str, Any], RetrievalResult]] = []

    async def _retrieve_one(paper: dict[str, Any]) -> None:
        async with semaphore:
            pmid = (paper.get("PMID") or "").strip()
            doi = (paper.get("DOI") or "").strip()
            retrieval = await retrieve_enriched_content(
                pmid=pmid, doi=doi, unpaywall_email=unpaywall_email
            )
            results.append((paper, retrieval))

    await asyncio.gather(*(_retrieve_one(p) for p in papers))
    return results


def summarize_retrieval_stats(results: list[tuple[dict[str, Any], RetrievalResult]]) -> dict[str, Any]:
    """Summarize retrieval batch statistics."""
    total = len(results)
    successes = sum(1 for _, r in results if r.success)
    by_source: dict[str, int] = {}
    for _, r in results:
        if r.success and r.source:
            by_source[r.source] = by_source.get(r.source, 0) + 1

    return {
        "total": total,
        "successful": successes,
        "success_rate": successes / total if total else 0,
        "by_source": by_source,
        "avg_elapsed_ms": sum(r.elapsed_ms for _, r in results) / total if total else 0,
    }
