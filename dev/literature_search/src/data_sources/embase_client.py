"""Embase API client for searching biomedical and pharmaceutical literature.

Note: Embase requires an institutional subscription and API key from Elsevier.
For access, contact: https://www.elsevier.com/solutions/embase-biomedical-research

This is a placeholder implementation. Full integration requires:
1. Elsevier API Key
2. Institution Token
3. Embase API subscription

Alternative: Users can export Embase results manually and import them alongside PubMed results.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import List, Optional, Dict, Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from .models import Paper
except Exception:
    from dataclasses import dataclass
    from datetime import datetime

    @dataclass
    class Paper:
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
        source: str = "embase"


logger = logging.getLogger(__name__)


class EmbaseClient:
    """Client for Embase API (Elsevier)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        inst_token: Optional[str] = None,
        api_base: str = "https://api.elsevier.com/content/search/scopus",
    ):
        """Initialize Embase client.

        Args:
            api_key: Elsevier API key (or set EMBASE_API_KEY env var)
            inst_token: Institution token (or set EMBASE_INST_TOKEN env var)
            api_base: API base URL
        """
        self.api_key = api_key or os.getenv("EMBASE_API_KEY")
        self.inst_token = inst_token or os.getenv("EMBASE_INST_TOKEN")
        self.api_base = api_base

        if not self.api_key:
            logger.warning(
                "Embase API key not found. Set EMBASE_API_KEY environment variable or pass api_key parameter. "
                "Embase searches will not work. Visit https://dev.elsevier.com/ for API access."
            )

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def search(
        self,
        query: str,
        max_results: int = 100,
        year_filter: Optional[str] = None,
    ) -> List[Paper]:
        """Search Embase database.

        Args:
            query: Search query string
            max_results: Maximum number of results to return
            year_filter: Year filter (e.g., "2020-2024")

        Returns:
            List of Paper objects

        Raises:
            ValueError: If API key not configured
            requests.RequestException: If API call fails
        """
        if not self.api_key:
            raise ValueError(
                "Embase API key not configured. Set EMBASE_API_KEY environment variable. "
                "For API access, visit: https://dev.elsevier.com/"
            )

        logger.info(f"Searching Embase: query='{query}', max_results={max_results}")

        # TODO: Implement actual Embase API calls
        # This is a placeholder that raises NotImplementedError
        raise NotImplementedError(
            "Embase integration is not yet fully implemented. "
            "This requires institutional access to Embase API. "
            "\n\nOptions:"
            "\n1. Contact your institution's library for Embase API credentials"
            "\n2. Use Embase web interface and export results manually"
            "\n3. Use PubMed/MEDLINE as primary source (already implemented)"
        )

    def _parse_embase_record(self, record: Dict[str, Any]) -> Paper:
        """Parse Embase API response into Paper object.

        Args:
            record: Raw record from Embase API

        Returns:
            Paper object
        """
        # TODO: Implement Embase record parsing
        # Embase uses different field names than PubMed
        raise NotImplementedError("Embase record parsing not yet implemented")


def search_embase(
    query: str,
    max_results: int = 100,
    year_filter: Optional[str] = None,
    api_key: Optional[str] = None,
    inst_token: Optional[str] = None,
) -> List[Paper]:
    """Convenience function to search Embase.

    Args:
        query: Search query
        max_results: Maximum results to return
        year_filter: Year filter (e.g., "2020-2024")
        api_key: Elsevier API key (optional, reads from env)
        inst_token: Institution token (optional, reads from env)

    Returns:
        List of Paper objects
    """
    client = EmbaseClient(api_key=api_key, inst_token=inst_token)
    return client.search(query, max_results=max_results, year_filter=year_filter)


if __name__ == "__main__":
    # Example usage (requires valid API credentials)
    try:
        results = search_embase(
            query="COVID-19 AND vaccine AND effectiveness",
            max_results=10,
        )
        print(f"Found {len(results)} results")
        for paper in results[:3]:
            print(f"\nTitle: {paper.title}")
            print(f"Authors: {', '.join(paper.authors[:3])}")
            print(f"Year: {paper.published.year}")
    except Exception as e:
        print(f"Error: {e}")
        print("\nEmbase integration requires institutional API access.")
        print("For now, use PubMed as the primary data source.")
