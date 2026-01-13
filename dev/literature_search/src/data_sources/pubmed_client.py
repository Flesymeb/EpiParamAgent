"""PubMed API client for searching and fetching paper metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any, Iterable
import os
import time
import html
import xml.etree.ElementTree as ET

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

# Paper dataclass from shared models
try:
    from .models import Paper  # type: ignore
except Exception:

    @dataclass
    class Paper:  # type: ignore
        id: str
        title: str
        authors: List[str]
        abstract: str
        published: datetime
        updated: datetime
        pdf_url: str
        categories: List[str]
        primary_category: str
        comment: Optional[str] = None
        journal_ref: Optional[str] = None
        doi: Optional[str] = None
        citation_count: int = 0
        source: str = "pubmed"

        def to_dict(self) -> Dict[str, Any]:
            return {
                "id": self.id,
                "title": self.title,
                "authors": self.authors,
                "abstract": self.abstract,
                "published": self.published.isoformat(),
                "updated": self.updated.isoformat(),
                "pdf_url": self.pdf_url,
                "categories": self.categories,
                "primary_category": self.primary_category,
                "comment": self.comment,
                "journal_ref": self.journal_ref,
                "doi": self.doi,
                "citation_count": self.citation_count,
                "source": self.source,
            }


logger = logging.getLogger(__name__)


class PubMedClient:
    """Client for NCBI PubMed (E-utilities)."""

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(
        self,
        api_key: Optional[str] = None,
        email: Optional[str] = None,
        tool: str = "meta-analysis-literature-search",
        medline_only: bool = True,  # Whether to restrict to MEDLINE indexed articles
    ):
        self.api_key = (
            api_key or os.getenv("NCBI_API_KEY") or os.getenv("PUBMED_API_KEY")
        )
        self.email = email or os.getenv("NCBI_EMAIL")
        self.tool = tool
        self.medline_only = medline_only

        self.session = requests.Session()
        self._min_interval = 0.1 if self.api_key else 0.34
        self._last_request_ts: Optional[float] = None
        # Allow disabling SSL verification via env (NCBI_VERIFY_SSL=false) for environments with custom certs.
        self.verify_ssl = os.getenv("NCBI_VERIFY_SSL", "true").lower() != "false"
        self.last_total: Optional[int] = None

    def _base_params(self) -> Dict[str, str]:
        params: Dict[str, str] = {"tool": self.tool}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["email"] = self.email
        return params

    def _throttle(self) -> None:
        now = time.time()
        if self._last_request_ts is not None:
            elapsed = now - self._last_request_ts
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
        self._last_request_ts = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def search(
        self,
        query: str,
        retmax: Optional[int] = 100,
        year: Optional[str] = None,
        # medline_only: bool = True,  # Whether to restrict to MEDLINE indexed articles
    ) -> List[Paper]:
        """Search PubMed and return Paper objects."""
        self.last_total = None
        term = self._build_term(query, year)
        logger.debug(f"Searching PubMed for: {term}")
        target: Optional[int]
        if retmax is None or retmax <= 0:
            target = None
        else:
            target = max(0, int(retmax))
        per_page = 200
        retstart = 0
        ids: List[str] = []
        total = None

        while True:
            if target is not None and len(ids) >= target:
                break
            page_size = per_page
            if target is not None:
                page_size = min(per_page, max(0, target - len(ids)))
                if page_size <= 0:
                    break
            params = {
                "db": "pubmed",
                "term": term,
                "retmax": str(page_size),
                "retstart": str(retstart),
                "retmode": "json",
                "sort": "relevance",
            }
            params.update(self._base_params())

            self._throttle()
            response = self.session.get(
                f"{self.BASE_URL}/esearch.fcgi",
                params=params,
                timeout=30,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("esearchresult", {})
            if total is None:
                try:
                    total = int(result.get("count", 0))
                except Exception:
                    total = 0
                self.last_total = total
                if target is None:
                    target = total
                logger.debug(
                    "PubMed total matches for query: %s (total=%s)", term, total
                )
                if total > 10000:
                    logger.warning(
                        "PubMed search count=%s exceeds 10000; consider splitting by year or using history-based retrieval.",
                        total,
                    )

            id_list = result.get("idlist", [])
            if not id_list:
                break
            ids.extend(id_list)
            retstart += len(id_list)
            if total is not None and retstart >= total:
                break

        if not ids:
            return []

        papers: List[Paper] = []
        slice_ids = ids if target is None else ids[:target]
        for chunk in self._chunk_ids(slice_ids, chunk_size=200):
            papers.extend(self._fetch_details(chunk))
            self._throttle()
        return papers

    # def _build_term(self, query: str, year: Optional[str], medline_only) -> str:
    #     if not year:
    #         return query
    #     year = year.strip()
    #     if "-" in year:
    #         start, end = [p.strip() for p in year.split("-", 1)]
    #         return f"({query}) AND ({start}:{end}[pdat])"
    #     return f"({query}) AND ({year}[pdat])"
    def _build_term(
        self,
        query: str,
        year: Optional[str],
    ) -> str:
        """Build PubMed search term with date filter.

        Supports:
        - Year range: "2020-2024" -> (query) AND (2020:2024[pdat])
        - Date range: "2020/1/1-2020/10/22" -> (query) AND (2020/1/1:2020/10/22[pdat])
        - Single year: "2020" -> (query) AND (2020[pdat])
        - Single date: "2020/1/1" -> (query) AND (2020/1/1[pdat])
        """
        term = query

        if year:  # Add publication date filter
            year = year.strip()
            if "-" in year:
                # Split on dash, convert back to colon for PubMed
                start, end = [p.strip() for p in year.split("-", 1)]
                term = f"({term}) AND ({start}:{end}[pdat])"
            else:
                # Single year or single date
                term = f"({term}) AND ({year}[pdat])"

        if self.medline_only:  # Restrict to MEDLINE indexed articles
            term = f"({term}) AND medline[sb]"

        return term

    def _chunk_ids(self, ids: Iterable[str], chunk_size: int) -> Iterable[List[str]]:
        chunk: List[str] = []
        for pid in ids:
            chunk.append(pid)
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

    def _fetch_details(self, ids: List[str]) -> List[Paper]:
        params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "xml",
        }
        params.update(self._base_params())
        self._throttle()
        response = self.session.get(
            f"{self.BASE_URL}/efetch.fcgi",
            params=params,
            timeout=30,
            verify=self.verify_ssl,
        )
        response.raise_for_status()

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as e:
            logger.warning(f"Failed to parse PubMed XML: {e}")
            return []

        papers: List[Paper] = []
        for article in root.findall(".//PubmedArticle"):
            if self.medline_only and not self._is_medline(article):
                continue
            paper = self._parse_article(article)
            if paper:
                papers.append(paper)
        return papers

    def _is_medline(self, article: ET.Element) -> bool:
        mc = article.find(".//MedlineCitation")
        if mc is None:
            return False

        status = mc.get("Status", "")
        has_mesh = article.find(".//MeshHeadingList") is not None

        return status == "MEDLINE" and has_mesh

    def _parse_article(self, article: ET.Element) -> Optional[Paper]:
        try:
            pmid = self._text(article.find(".//PMID")) or ""
            title = self._text(article.find(".//ArticleTitle")) or ""
            abstract = self._extract_abstract(article)
            authors = self._extract_authors(article)
            published = self._extract_pub_date(article)
            doi = self._extract_doi(article)
            journal = self._text(article.find(".//Journal/Title")) or ""
            is_medline = self._is_medline(article)

            return Paper(
                id=f"pubmed:{pmid}" if pmid else "",
                title=title,
                authors=authors,
                abstract=abstract,
                published=published,
                updated=published,
                pdf_url="",
                categories=[journal] if journal else [],
                primary_category=journal,
                comment=f"MEDLINE={is_medline}",
                journal_ref=journal or None,
                doi=doi,
                citation_count=0,
                source="pubmed",
            )
        except Exception as e:
            logger.warning(f"Failed to parse PubMed article: {e}")
            return None

    def _extract_abstract(self, article: ET.Element) -> str:
        parts = []
        for node in article.findall(".//Abstract/AbstractText"):
            label = node.get("Label")
            text = self._text(node)
            if not text:
                continue
            parts.append(f"{label}: {text}" if label else text)
        return "\n".join(parts).strip()

    def _extract_authors(self, article: ET.Element) -> List[str]:
        authors = []
        for author in article.findall(".//AuthorList/Author"):
            fore = self._text(author.find("ForeName"))
            last = self._text(author.find("LastName"))
            if fore and last:
                authors.append(f"{fore} {last}")
            elif last:
                authors.append(last)
        return authors

    def _extract_pub_date(self, article: ET.Element) -> datetime:
        date_node = (
            article.find(".//ArticleDate")
            or article.find(".//JournalIssue/PubDate")
            or article.find(".//PubDate")
        )
        if date_node is None:
            return datetime(1900, 1, 1)

        year = self._text(date_node.find("Year"))
        month = self._text(date_node.find("Month"))
        day = self._text(date_node.find("Day"))

        try:
            year_i = int(year) if year else 1900
        except ValueError:
            year_i = 1900
        month_i = self._parse_month(month)
        day_i = int(day) if day and day.isdigit() else 1

        return datetime(year_i, month_i, day_i)

    def _extract_doi(self, article: ET.Element) -> Optional[str]:
        for node in article.findall(".//ArticleId"):
            if node.get("IdType") == "doi":
                text = self._text(node)
                if text:
                    return text
        return None

    def _parse_month(self, month: Optional[str]) -> int:
        if not month:
            return 1
        month = month.strip()
        if month.isdigit():
            return max(1, min(12, int(month)))
        mapping = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        return mapping.get(month[:3].lower(), 1)

    def _text(self, node: Optional[ET.Element]) -> Optional[str]:
        if node is None:
            return None
        if node.text is None:
            return None
        return html.unescape(node.text.strip())
