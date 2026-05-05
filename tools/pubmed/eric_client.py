"""ERIC API client for searching education research metadata."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
import os
import html
import re
import time

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from .models import Paper  # type: ignore
except Exception:
    from dataclasses import dataclass
    from typing import List, Optional, Dict, Any
    from datetime import datetime

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
        source: str = "eric"

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
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)


class ERICClient:
    """Client for the ERIC API (https://api.ies.ed.gov/eric/)."""

    BASE_URL = "https://api.ies.ed.gov/eric/"
    CROSSREF_URL = "https://api.crossref.org/works"

    def __init__(
        self, base_url: Optional[str] = None, crossref_mailto: Optional[str] = None
    ):
        self.base_url = base_url or os.getenv("ERIC_API_BASE") or self.BASE_URL
        self.crossref_mailto = crossref_mailto or os.getenv("CROSSREF_MAILTO")
        self.session = requests.Session()
        self._crossref_last_ts: Optional[float] = None
        self._crossref_min_interval = 0.1
        self.last_total: Optional[int] = None
        self.last_total_raw: Optional[int] = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def search(
        self,
        query: str,
        limit: Optional[int] = 100,
        year: Optional[str] = None,
        fields: Optional[List[str]] = None,
        enrich_doi: bool = False,
        doi_lookup_max: Optional[int] = None,
    ) -> List[Paper]:
        """Search ERIC and return Paper objects."""
        self.last_total = None
        self.last_total_raw = None
        logger.info("Searching ERIC for: %s", query)

        target: Optional[int]
        if limit is None or limit <= 0:
            target = None
        else:
            target = max(0, int(limit))
        if target == 0:
            return []
        if doi_lookup_max is None:
            env_limit = os.getenv("CROSSREF_DOI_LOOKUP_MAX")
            try:
                doi_lookup_max = max(0, int(env_limit)) if env_limit else target
            except ValueError:
                doi_lookup_max = target
        else:
            doi_lookup_max = max(0, doi_lookup_max)

        min_year, max_year = self._parse_year_range(year)
        use_query_filter = True
        if min_year or max_year:
            if " AND " in query or " OR " in query or "(" in query or ")" in query:
                # ERIC filter syntax (pubyearmin/max) does not play well with boolean-heavy queries.
                use_query_filter = False

        search_query = self._build_query(query, year) if use_query_filter else query
        if search_query != query:
            logger.info("ERIC query with year filter: %s", search_query)
        if not use_query_filter and (min_year or max_year):
            logger.info(
                "ERIC year filter applied post-search: %s-%s",
                min_year or "",
                max_year or "",
            )
        search_query = self._escape_unfielded_quotes(search_query)
        per_page = 2000
        start = 0
        total = None
        papers: List[Paper] = []
        doi_cache: Dict[str, Optional[str]] = {}
        doi_lookups = 0

        if fields is None:
            fields = [
                "id",
                "title",
                "author",
                "description",
                "publicationdateyear",
                "publicationtype",
                "source",
                "sourceid",
                "url",
                "e_fulltextauth",
                "peerreviewed",
            ]

        if enrich_doi and not self.crossref_mailto:
            logger.info(
                "CROSSREF_MAILTO not set; Crossref recommends providing a contact email."
            )

        while True:
            if target is not None and len(papers) >= target:
                break
            params = {
                "search": search_query,
                "format": "json",
                "start": str(start),
                "rows": str(
                    per_page
                    if target is None
                    else min(per_page, max(0, target - len(papers)))
                ),
                "fields": ",".join(fields),
            }
            response = self.session.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("response", {})

            if total is None:
                total = self._safe_int(data.get("numFound"))
                self.last_total_raw = total if total is not None else 0
                self.last_total = self.last_total_raw
                if total is not None:
                    logger.info(
                        "ERIC total matches for query: %s (total=%s)",
                        search_query,
                        total,
                    )
                if target is None and total is not None:
                    target = total

            docs = data.get("docs", []) or []
            if not docs:
                break

            for doc in docs:
                paper = self._convert_doc(doc)
                if paper and (min_year or max_year) and not use_query_filter:
                    pub_year = self._safe_int(doc.get("publicationdateyear"))
                    if pub_year is None:
                        continue
                    if min_year and pub_year < min_year:
                        continue
                    if max_year and pub_year > max_year:
                        continue
                if (
                    paper
                    and enrich_doi
                    and not paper.doi
                    and doi_lookups < doi_lookup_max
                ):
                    key = self._normalize_title(paper.title)
                    if key in doi_cache:
                        paper.doi = doi_cache[key] or None
                    else:
                        year_hint = self._safe_int(doc.get("publicationdateyear"))
                        doi = self._lookup_doi_crossref(
                            paper.title, paper.authors, year_hint
                        )
                        doi_cache[key] = doi
                        if doi:
                            paper.doi = doi
                        doi_lookups += 1
                if paper:
                    papers.append(paper)

            start += len(docs)
            if total is not None and start >= total:
                break

        if (min_year or max_year) and not use_query_filter:
            # When filtering locally, update last_total to reflect filtered count.
            self.last_total = len(papers)
            logger.info(
                "ERIC total after local year filter: %s",
                self.last_total,
            )
        return papers

    def _build_query(self, query: str, year: Optional[str]) -> str:
        if not year:
            return query

        year = year.strip()
        if not year:
            return query

        if "-" in year:
            start, end = [p.strip() for p in year.split("-", 1)]
            if start.isdigit() and end.isdigit():
                return f"{query} pubyearmin:{start} pubyearmax:{end}".strip()
        if year.isdigit():
            return f"{query} pubyear:{year}".strip()
        return query

    def _parse_year_range(
        self, year: Optional[str]
    ) -> tuple[Optional[int], Optional[int]]:
        if not year:
            return None, None
        year = year.strip()
        if not year:
            return None, None
        if "-" in year:
            start, end = [p.strip() for p in year.split("-", 1)]
            min_year = self._safe_int(start)
            max_year = self._safe_int(end)
            return min_year, max_year
        if year.isdigit():
            y = self._safe_int(year)
            return y, y
        return None, None

    def _escape_unfielded_quotes(self, query: str) -> str:
        """Escape quotes used for unfielded phrases to avoid ERIC Solr errors."""
        if '"' not in query:
            return query

        output: List[str] = []
        last = 0
        for match in re.finditer(r'"[^"]*"', query):
            start, end = match.span()
            prefix = query[:start]
            j = len(prefix) - 1
            while j >= 0 and prefix[j].isspace():
                j -= 1
            fielded = False
            if j >= 0 and prefix[j] == ":":
                k = j - 1
                while k >= 0 and (prefix[k].isalnum() or prefix[k] == "_"):
                    k -= 1
                field = prefix[k + 1 : j]
                if field:
                    fielded = True

            output.append(query[last:start])
            if fielded:
                output.append(query[start:end])
            else:
                output.append(query[start:end].replace('"', '\\"'))
            last = end

        output.append(query[last:])
        return "".join(output)

    def _convert_doc(self, doc: Dict[str, Any]) -> Optional[Paper]:
        try:
            record_id = str(doc.get("id") or "").strip()
            title = self._clean_text(doc.get("title")) or ""
            abstract = self._clean_text(doc.get("description")) or ""
            authors = self._parse_authors(doc.get("author"))
            pub_year = doc.get("publicationdateyear")
            published = self._parse_year(pub_year)
            source = self._clean_text(doc.get("source")) or ""
            doi = self._extract_doi([doc.get("url"), doc.get("sourceid")])
            publication_type = self._ensure_list(doc.get("publicationtype"))
            categories = publication_type
            primary_category = categories[0] if categories else source
            pdf_url = self._fulltext_url(record_id, doc.get("e_fulltextauth"))

            return Paper(
                id=f"eric:{record_id}" if record_id else "",
                title=title,
                authors=authors,
                abstract=abstract,
                published=published,
                updated=published,
                pdf_url=pdf_url,
                categories=categories,
                primary_category=primary_category,
                comment=None,
                journal_ref=source or None,
                doi=doi,
                citation_count=0,
                source="eric",
            )
        except Exception as e:
            logger.warning("Failed to parse ERIC record: %s", e)
            return None

    def _fulltext_url(self, record_id: str, flag: Any) -> str:
        if not record_id or not record_id.startswith("ED"):
            return ""
        if str(flag).strip() not in {"1", "true", "True"}:
            return ""
        return f"https://files.eric.ed.gov/fulltext/{record_id}.pdf"

    def _parse_authors(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [self._clean_text(v) for v in value if self._clean_text(v)]
        if isinstance(value, str):
            return [v.strip() for v in value.split(";") if v.strip()]
        return []

    def _extract_doi(self, values: List[Any]) -> Optional[str]:
        for value in values:
            if value is None:
                continue
            if isinstance(value, list):
                candidates = value
            else:
                candidates = [value]
            for item in candidates:
                text = self._clean_text(item)
                if not text:
                    continue
                match = _DOI_RE.search(text)
                if match:
                    doi = match.group(0).rstrip(").,;")
                    return doi
        return None

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
    )
    def _lookup_doi_crossref(
        self, title: str, authors: List[str], year_hint: Optional[int]
    ) -> Optional[str]:
        if not title:
            return None
        author_query = self._author_query(authors)
        params: Dict[str, str] = {
            "query.title": title,
            "rows": "10",
        }
        if author_query:
            params["query.author"] = author_query
        if year_hint:
            params["filter"] = f"from-pub-date:{year_hint},until-pub-date:{year_hint}"
        if self.crossref_mailto:
            params["mailto"] = self.crossref_mailto

        items = self._fetch_crossref_items(params)
        doi = self._select_crossref_doi(items, title)
        if doi:
            return doi

        fallback = {
            "query.bibliographic": title,
            "rows": "10",
        }
        if author_query:
            fallback["query.author"] = author_query
        if self.crossref_mailto:
            fallback["mailto"] = self.crossref_mailto
        items = self._fetch_crossref_items(fallback)
        return self._select_crossref_doi(items, title)

    def _author_query(self, authors: List[str]) -> Optional[str]:
        if not authors:
            return None
        first = authors[0].strip()
        if not first:
            return None
        if "," in first:
            return first.split(",", 1)[0].strip()
        parts = [p for p in first.split() if p]
        return parts[-1] if parts else first

    def _fetch_crossref_items(self, params: Dict[str, str]) -> List[Dict[str, Any]]:
        self._crossref_throttle()
        response = self.session.get(
            self.CROSSREF_URL,
            params=params,
            timeout=30,
            headers={"User-Agent": "meta-analysis-literature-search"},
        )
        response.raise_for_status()
        data = response.json().get("message", {})
        return data.get("items", []) or []

    def _select_crossref_doi(
        self, items: List[Dict[str, Any]], title: str
    ) -> Optional[str]:
        target = self._normalize_title(title)
        if not target:
            return None
        target_tokens = self._tokenize_title(target)
        for item in items:
            doi = item.get("DOI")
            if not doi:
                continue
            item_titles = item.get("title") or []
            if isinstance(item_titles, str):
                item_titles = [item_titles]
            for candidate in item_titles:
                normalized = self._normalize_title(candidate)
                if not normalized:
                    continue
                if normalized == target or normalized in target or target in normalized:
                    return doi
                if self._title_similarity(target_tokens, normalized) >= 0.82:
                    return doi
        return None

    def _parse_year(self, value: Any) -> datetime:
        year = self._safe_int(value)
        if year:
            return datetime(year, 1, 1)
        return datetime.now()

    def _ensure_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [self._clean_text(v) for v in value if self._clean_text(v)]
        if isinstance(value, str):
            cleaned = self._clean_text(value)
            return [cleaned] if cleaned else []
        return []

    def _clean_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return html.unescape(text)

    def _safe_int(self, value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _normalize_title(self, title: Any) -> str:
        if title is None:
            return ""
        return re.sub(r"[^a-z0-9]+", " ", str(title).lower()).strip()

    def _tokenize_title(self, normalized_title: str) -> List[str]:
        if not normalized_title:
            return []
        return [t for t in normalized_title.split() if t]

    def _title_similarity(self, target_tokens: List[str], candidate: str) -> float:
        if not target_tokens or not candidate:
            return 0.0
        candidate_tokens = set(self._tokenize_title(candidate))
        if not candidate_tokens:
            return 0.0
        target_set = set(target_tokens)
        intersection = target_set & candidate_tokens
        union = target_set | candidate_tokens
        return len(intersection) / max(1, len(union))

    def _crossref_throttle(self) -> None:
        now = time.time()
        if self._crossref_last_ts is not None:
            elapsed = now - self._crossref_last_ts
            if elapsed < self._crossref_min_interval:
                time.sleep(self._crossref_min_interval - elapsed)
        self._crossref_last_ts = time.time()
