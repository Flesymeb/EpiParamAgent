"""Tier-2 enriched metadata retrieval for cascade screening.

For papers with low-confidence LLM decisions, this module fetches
additional metadata and full-text snippets to fill the information
gaps that cause 5D/PECO frameworks to struggle with abstracts alone.

Strategy (simple, no ReAct loop):
  1. PubMed EFetch XML → MeSH terms, Publication Types, structured abstract
  2. PMC OA → HTML full-text → extract Methods section
  3. Pass enriched content back to LLM for re-screening

This directly addresses the root cause of 5D/PECO underperformance:
missing dimension-level evidence (location, evidence type, population)
that abstracts often omit but full text and MeSH terms provide.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class EnrichedMetadata:
    """Structured metadata extracted from PubMed + PMC for re-screening."""

    pmid: str
    success: bool = False

    # From PubMed EFetch
    mesh_terms: list[str] = field(default_factory=list)
    publication_types: list[str] = field(default_factory=list)
    structured_abstract: str = ""  # Labeled abstract (BACKGROUND/METHODS/RESULTS/CONCLUSIONS)
    journal: str = ""
    year: str = ""

    # From PMC OA
    pmc_full_text_snippet: str = ""  # Methods section or beginning of full text
    pmc_url: str = ""

    # Aggregated
    enriched_text: str = ""  # Combined enriched content for LLM prompt
    source: str = ""  # Which source provided the enrichment
    elapsed_ms: float = 0.0
    error: str = ""


# ── PubMed EFetch: MeSH + PubType + structured abstract ──────

async def _fetch_pubmed_xml(
    client: httpx.AsyncClient, pmid: str
) -> Optional[ET.Element]:
    """Fetch PubMed XML for a single PMID via EFetch."""
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"}
    try:
        resp = await client.get(url, params=params, timeout=15.0)
        if resp.status_code == 200:
            return ET.fromstring(resp.text)
    except Exception as e:
        logger.debug(f"PubMed EFetch error for {pmid}: {e}")
    return None


def _extract_mesh_terms(article: ET.Element) -> list[str]:
    """Extract MeSH descriptor names from PubMed XML."""
    terms = []
    for mesh in article.findall(".//MeshHeading"):
        desc = mesh.find("DescriptorName")
        if desc is not None and desc.text:
            qualifiers = mesh.findall("QualifierName")
            if qualifiers:
                for q in qualifiers:
                    if q.text:
                        terms.append(f"{desc.text}/{q.text}")
            else:
                terms.append(desc.text)
    return terms


def _extract_publication_types(article: ET.Element) -> list[str]:
    """Extract PublicationType values from PubMed XML."""
    types = []
    for pt in article.findall(".//PublicationTypeList/PublicationType"):
        if pt.text:
            types.append(pt.text)
    return types


def _extract_structured_abstract(article: ET.Element) -> str:
    """Extract abstract with section labels preserved (BACKGROUND, METHODS, etc.)."""
    parts = []
    for node in article.findall(".//Abstract/AbstractText"):
        label = node.get("Label", "")
        text = "".join(node.itertext()).strip()
        if text:
            parts.append(f"{label}: {text}" if label else text)
    return " ".join(parts) if parts else ""


def _parse_pubmed_metadata(xml_root: ET.Element) -> dict[str, Any]:
    """Parse PubMed XML into structured metadata dict."""
    article = xml_root.find(".//PubmedArticle")
    if article is None:
        article = xml_root

    mesh = _extract_mesh_terms(article)
    pub_types = _extract_publication_types(article)
    abstract = _extract_structured_abstract(article)

    journal = ""
    journal_elem = article.find(".//Journal/Title")
    if journal_elem is not None:
        journal = (journal_elem.text or "").strip()

    year = ""
    pub_date = article.find(".//Journal/JournalIssue/PubDate")
    if pub_date is not None:
        y = pub_date.find("Year")
        if y is not None and y.text:
            year = y.text

    return {
        "mesh_terms": mesh,
        "publication_types": pub_types,
        "structured_abstract": abstract,
        "journal": journal,
        "year": year,
    }


# ── PMC OA: full-text HTML → Methods section ─────────────────

async def _fetch_pmc_html(
    client: httpx.AsyncClient, pmid: str
) -> Optional[str]:
    """Try to fetch PMC OA HTML for a PMID."""
    # PMC often uses PMCID, try direct PMID-based URL first
    urls = [
        f"https://www.ncbi.nlm.nih.gov/pmc/articles/pmid/{pmid}/",
        f"https://www.ncbi.nlm.nih.gov/pmc/?term={pmid}[pmid]&report=fulltext",
    ]
    for url in urls:
        try:
            resp = await client.get(url, timeout=15.0, follow_redirects=True)
            if resp.status_code == 200 and "text/html" in (resp.headers.get("content-type", "")):
                # Check it's actually full text, not a search result page
                if "<div class=\"article\"" in resp.text or "<div id=\"mc" in resp.text or "PMC" in resp.text:
                    return resp.text
        except Exception:
            continue
    return None


def _extract_methods_section(html: str, max_chars: int = 3000) -> str:
    """Extract Methods section from PMC HTML."""
    # Try to find methods heading and extract until next major heading
    methods_patterns = [
        r"<(?:h[234]|div|p)\b[^>]*?(?:id|class)=[^>]*?(?:methods?|materials)[^>]*?>(.*?)(?:</(?:h[234]|div|p)>|$)",
        r"(?:Methods?|METHODS?|Materials and methods|MATERIALS AND METHODS)\s*</[^>]+>\s*(.*?)(?:(?:Results?|RESULTS?|Discussion|DISCUSSION)\s*</[^>]+>|$)",
    ]

    for pattern in methods_patterns:
        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1) if match.lastindex else match.group(0)
            # Clean HTML
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 200:
                return text[:max_chars]

    # Fallback: extract all visible text from article body
    article_match = re.search(
        r"<(?:div|article)\b[^>]*?(?:id|class)=[^>]*?(?:article|main|content)[^>]*?>(.*?)(?:</(?:div|article)>|\Z)",
        html, re.DOTALL | re.IGNORECASE
    )
    if article_match:
        text = re.sub(r"<[^>]+>", " ", article_match.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]

    return ""



# ── PMC JATS XML: structured full-text sections ──────────────

async def _fetch_pmc_jats_xml(
    client: httpx.AsyncClient, pmid: str
) -> Optional[str]:
    """Fetch PMC JATS XML for a PMID. Returns full structured XML text."""
    # First try to get PMCID from PMID
    conv_url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
    params = {"ids": pmid, "format": "json", "tool": "metaagent-epi", "email": "dev@example.com"}
    try:
        r = await client.get(conv_url, params=params, timeout=10.0)
        if r.status_code == 200:
            data = r.json()
            records = data.get("records", [])
            if records and records[0].get("pmcid"):
                pmcid = records[0]["pmcid"]
                # Fetch JATS XML
                jats_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/?report=xml"
                r2 = await client.get(jats_url, timeout=15.0, follow_redirects=True)
                if r2.status_code == 200 and "<article" in r2.text[:500]:
                    return r2.text
    except Exception:
        pass
    return None


def _extract_sections_from_jats(xml_text: str, max_chars: int = 3000) -> str:
    """Extract Methods and Results sections from PMC JATS XML."""
    import re
    
    # Remove XML tags to get plain text
    text = re.sub(r"<[^>]+>", " ", xml_text)
    text = re.sub(r"\s+", " ", text).strip()
    
    # Try to find Methods section
    methods_pat = r"(?:Methods?|METHODS?|Materials and methods|MATERIALS AND METHODS)\s*[:\.\-]?\s*(.*?)(?=(?:Results?|RESULTS?|Discussion|DISCUSSION)\s*[:\.\-]?\s*|$)"
    m = re.search(methods_pat, text, re.DOTALL | re.IGNORECASE)
    if m:
        methods = m.group(1).strip()[:max_chars]
        if len(methods) > 200:
            return f"[Methods section from PMC full-text]\n{methods}"
    
    return text[:max_chars]


# ── Europe PMC: full-text XML ────────────────────────────────

async def _fetch_europe_pmc_fulltext(
    client: httpx.AsyncClient, pmid: str
) -> Optional[str]:
    """Fetch full-text XML from Europe PMC for a PMID."""
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmid}/fullTextXML"
    try:
        r = await client.get(url, timeout=15.0)
        if r.status_code == 200 and "<article" in r.text[:500]:
            return r.text
    except Exception:
        pass
    return None


def _extract_sections_from_europe_pmc(xml_text: str, max_chars: int = 3000) -> str:
    """Extract Methods/Results from Europe PMC XML."""
    import re
    text = re.sub(r"<[^>]+>", " ", xml_text)
    text = re.sub(r"\s+", " ", text).strip()
    
    # Europe PMC XML often has <sec sec-type="methods"> or similar
    methods_pat = r"(?:Methods?|METHODS?|Materials and methods)\b.*?(?=\b(?:Results?|RESULTS?|Discussion)\b|$)"
    m = re.search(methods_pat, text, re.DOTALL | re.IGNORECASE)
    if m:
        methods = m.group(0).strip()[:max_chars]
        if len(methods) > 100:
            return f"[Methods from Europe PMC full-text]\n{methods}"
    
    return text[:max_chars]



# ── Publisher HTML: DOI → journal page → Methods section ─────

async def _fetch_publisher_html(
    client: httpx.AsyncClient, doi: str
) -> Optional[str]:
    """Try to extract Methods section from publisher HTML page via DOI.

    Only used as a last resort when PMC/Europe PMC are unavailable.
    Opens the journal's HTML abstract/full-text page and extracts
    any visible Methods or study design information.
    """
    if not doi:
        return None

    # Resolve DOI to publisher URL
    try:
        resolve_url = f"https://doi.org/{doi}"
        r = await client.get(resolve_url, timeout=10.0, follow_redirects=True)
        if r.status_code != 200:
            return None
        html = r.text
        url = str(r.url)
    except Exception:
        return None

    # Try to find and extract methods-like content
    import re
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Try to extract methods section
    for pat in [
        r"(?:Methods?|METHODS?|Materials and methods|Study design|Experimental procedures?)\b.*?(?=\b(?:Results?|RESULTS?|Discussion|DISCUSSION|Conclusion|References|Acknowledgments?)\b|$)",
        r"(?:Abstract|ABSTRACT)\b.*?(?=\b(?:Introduction|INTRODUCTION)\b|$)",
    ]:
        m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if m:
            methods = m.group(0).strip()
            if len(methods) > 200:
                return f"[Publisher HTML via DOI {doi} — {url}]\n{methods[:3000]}"

    # Fallback: return beginning of article text (often contains study design info)
    if len(text) > 500:
        return f"[Publisher HTML via DOI {doi}]\n{text[:2000]}"

    return None

async def _fetch_html_snippet(
    client: httpx.AsyncClient, url: str, max_chars: int = 3000
) -> str:
    """Fetch HTML from any URL and extract text snippet."""
    try:
        resp = await client.get(url, timeout=15.0, follow_redirects=True)
        if resp.status_code == 200:
            text = re.sub(r"<[^>]+>", " ", resp.text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
    except Exception:
        pass
    return ""


# ── Main orchestrator ────────────────────────────────────────

async def enrich_paper_metadata(
    pmid: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    try_pmc: bool = True,
    doi: str = "",
) -> EnrichedMetadata:
    """Fetch enriched metadata for a single paper.

    Priority: PubMed EFetch → PMC JATS XML → Europe PMC → PMC HTML → Publisher HTML

    Args:
        pmid: PubMed ID of the paper.
        client: Optional shared httpx.AsyncClient.
        try_pmc: Whether to attempt full-text retrieval.
        doi: Optional DOI for publisher HTML fallback.

    Returns:
        EnrichedMetadata with all gathered information.
    """
    result = EnrichedMetadata(pmid=pmid)
    start = time.perf_counter()

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    try:
        # Step 1: PubMed XML (always try, fast and reliable)
        xml_root = await _fetch_pubmed_xml(client, pmid)
        if xml_root is not None:
            meta = _parse_pubmed_metadata(xml_root)
            result.mesh_terms = meta["mesh_terms"]
            result.publication_types = meta["publication_types"]
            result.structured_abstract = meta["structured_abstract"]
            result.journal = meta["journal"]
            result.year = meta["year"]
            result.source = "pubmed"
            result.success = True

        # Step 2: PMC JATS XML — structured full-text (best quality)
        if try_pmc:
            jats_xml = await _fetch_pmc_jats_xml(client, pmid)
            if jats_xml:
                methods = _extract_sections_from_jats(jats_xml)
                if methods:
                    result.pmc_full_text_snippet = methods
                    result.source = "pmc_jats"
                    result.success = True

        # Step 3: Europe PMC — full-text XML (broader OA coverage)
        if try_pmc and not result.pmc_full_text_snippet:
            epmc_xml = await _fetch_europe_pmc_fulltext(client, pmid)
            if epmc_xml:
                methods = _extract_sections_from_europe_pmc(epmc_xml)
                if methods:
                    result.pmc_full_text_snippet = methods
                    result.source = "europe_pmc"
                    result.success = True

        # Step 4: PMC OA HTML (fallback)
        if try_pmc and not result.pmc_full_text_snippet:
            pmc_html = await _fetch_pmc_html(client, pmid)
            if pmc_html:
                methods = _extract_methods_section(pmc_html)
                if methods:
                    result.pmc_full_text_snippet = methods
                    result.source = "pmc"
                    result.success = True

        # Step 5: Publisher HTML via DOI (last resort)
        if try_pmc and not result.pmc_full_text_snippet:
            if doi:
                pub_html = await _fetch_publisher_html(client, doi)
                if pub_html:
                    result.pmc_full_text_snippet = pub_html
                    result.source = "publisher_html"
                    result.success = True

        # Build enriched text for LLM prompt
        parts = []
        if result.publication_types:
            parts.append(f"Publication Types: {', '.join(result.publication_types)}")
        if result.mesh_terms:
            parts.append(f"MeSH Terms: {'; '.join(result.mesh_terms[:20])}")
        if result.structured_abstract:
            parts.append(f"Structured Abstract: {result.structured_abstract[:2000]}")
        if result.pmc_full_text_snippet:
            parts.append(f"[PMC Full-text Methods section]\n{result.pmc_full_text_snippet}")
        result.enriched_text = "\n\n".join(parts)

    except Exception as e:
        result.error = str(e)[:500]
        logger.warning(f"Enrichment failed for PMID={pmid}: {e}")

    finally:
        if own_client and client is not None:
            await client.aclose()

    result.elapsed_ms = (time.perf_counter() - start) * 1000
    return result


async def batch_enrich(
    papers: list[dict[str, Any]],
    *,
    concurrency: int = 5,
    try_pmc: bool = True,
) -> list[tuple[dict[str, Any], EnrichedMetadata]]:
    """Enrich metadata for multiple papers concurrently.

    Args:
        papers: List of paper dicts with 'PMID' key.
        concurrency: Max concurrent enrichment requests.
        try_pmc: Whether to attempt PMC full-text retrieval.

    Returns:
        List of (paper, EnrichedMetadata) tuples.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: list[tuple[dict[str, Any], EnrichedMetadata]] = []

    async def _enrich_one(paper: dict[str, Any]) -> None:
        async with semaphore:
            pmid = (paper.get("PMID") or "").strip()
            doi = (paper.get("DOI") or "").strip()
            enriched = await enrich_paper_metadata(pmid, try_pmc=try_pmc, doi=doi)
            results.append((paper, enriched))

    await asyncio.gather(*(_enrich_one(p) for p in papers))
    return results


def build_enriched_prompt(
    paper: dict[str, Any],
    enriched: EnrichedMetadata,
) -> str:
    """Build enriched content text for LLM re-screening prompt.

    Combines the paper's original abstract with newly retrieved metadata
    and full-text snippets, prioritizing the most dimensionally-informative content.
    """
    parts = []

    # Original title and abstract
    title = (paper.get("Title") or "").strip()
    abstract = (paper.get("Abstract") or "").strip()
    if title:
        parts.append(f"Title: {title}")
    if abstract:
        parts.append(f"Original Abstract: {abstract[:2000]}")

    # Enriched metadata (fills 5D/PECO dimension gaps)
    if enriched.publication_types:
        parts.append(f"Publication Types: {', '.join(enriched.publication_types)}")
    if enriched.mesh_terms:
        parts.append(f"MeSH Terms: {'; '.join(enriched.mesh_terms[:25])}")
    if enriched.structured_abstract:
        structured = enriched.structured_abstract[:2000]
        if structured != abstract[:2000]:  # Only add if it adds new info
            parts.append(f"Structured Abstract: {structured}")
    if enriched.pmc_full_text_snippet:
        parts.append(f"[Retrieved from PMC full-text]\n{enriched.pmc_full_text_snippet}")
    if enriched.journal:
        parts.append(f"Journal: {enriched.journal} ({enriched.year})")

    return "\n\n".join(parts)
