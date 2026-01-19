"""Resolve publication metadata from DOI using CrossRef API."""

from __future__ import annotations

import logging
import re
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


def extract_doi_from_text(text: str) -> Optional[str]:
    """Extract DOI from text.

    Looks for common DOI patterns:
    - doi: 10.xxxx/yyyy
    - https://doi.org/10.xxxx/yyyy
    - DOI: 10.xxxx/yyyy
    """
    # Pattern: doi prefix followed by publisher/resource identifier
    patterns = [
        r"doi[:\s]+([0-9]{2}\.[0-9]{4,}(?:\.[0-9]+)?/[^\s]+)",
        r"https?://(?:dx\.)?doi\.org/([0-9]{2}\.[0-9]{4,}(?:\.[0-9]+)?/[^\s]+)",
        r"\b(10\.[0-9]{4,}(?:\.[0-9]+)?/[^\s]+)",
    ]

    text_lower = text.lower()
    for pattern in patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            doi = match.group(1)
            # Clean up trailing punctuation
            doi = re.sub(r"[.,;)\]]+$", "", doi)
            return doi

    return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def resolve_doi_metadata(doi: str, timeout: int = 10) -> Optional[dict]:
    """Resolve publication metadata from DOI via CrossRef API.

    Args:
        doi: The DOI identifier (e.g., "10.1177/0022219418775115")
        timeout: Request timeout in seconds

    Returns:
        Dictionary with metadata:
        - title: Article title
        - year: Publication year (int)
        - authors: List of author names
        - journal: Journal name
        - doi: Original DOI

        Returns None if resolution fails.
    """
    if not doi:
        return None

    # Clean DOI
    doi = doi.strip()
    if doi.startswith("http"):
        doi = extract_doi_from_text(doi) or doi

    url = f"https://api.crossref.org/works/{doi}"
    headers = {
        "User-Agent": "MetaAgent/1.0 (mailto:research@example.com)"  # Be a good API citizen
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        data = response.json()
        message = data.get("message", {})

        # Extract year from published date
        # Priority: published-print (正式纸质版) > issued > published > published-online
        year = None

        # Priority 1: published-print (纸质版正式出版年份，最常用于引用)
        date_parts = message.get("published-print", {}).get("date-parts", [[]])[0]
        if date_parts:
            year = date_parts[0] if len(date_parts) > 0 else None

        # Priority 2: issued (发行年份)
        if not year:
            date_parts = message.get("issued", {}).get("date-parts", [[]])[0]
            if date_parts:
                year = date_parts[0]

        # Priority 3: published (通用发表日期)
        if not year:
            date_parts = message.get("published", {}).get("date-parts", [[]])[0]
            if date_parts:
                year = date_parts[0]

        # Priority 4: published-online (在线先发，通常比纸质版早)
        if not year:
            date_parts = message.get("published-online", {}).get("date-parts", [[]])[0]
            if date_parts:
                year = date_parts[0]

        # Extract authors
        authors = []
        for author in message.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            if family:
                authors.append(f"{given} {family}".strip())

        # Extract title
        titles = message.get("title", [])
        title = titles[0] if titles else None

        # Extract journal
        journal = message.get("container-title", [None])[0]

        metadata = {
            "title": title,
            "year": int(year) if year else None,
            "authors": authors,
            "journal": journal,
            "doi": doi,
        }

        logger.info(f"Resolved DOI {doi}: {title} ({year})")
        return metadata

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"DOI not found: {doi}")
        else:
            logger.error(f"HTTP error resolving DOI {doi}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error resolving DOI {doi}: {e}")
        return None


def extract_year_from_pdf_text(text: str) -> Optional[int]:
    """Extract publication year from PDF text.

    Looks for common patterns:
    - Copyright © 2018
    - Published: January 2018
    - (2018)
    - Year patterns near common publication metadata areas
    """
    # Look in first 2000 chars (header area)
    header = text[:2000]

    # Pattern 1: Copyright year
    match = re.search(r"copyright\s*©?\s*(\d{4})", header, re.IGNORECASE)
    if match:
        year = int(match.group(1))
        if 1990 <= year <= 2030:
            return year

    # Pattern 2: Published/Received year
    match = re.search(
        r"(?:published|received)[:\s]+\w+\s+(\d{4})", header, re.IGNORECASE
    )
    if match:
        year = int(match.group(1))
        if 1990 <= year <= 2030:
            return year

    # Pattern 3: Just a year in parentheses near start
    years = re.findall(r"\((\d{4})\)", header)
    for year_str in years:
        year = int(year_str)
        if 1990 <= year <= 2030:
            return year

    return None
