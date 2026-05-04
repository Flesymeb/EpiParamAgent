"""Shared data models for data source clients."""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class Paper:
    """Represents a research paper."""

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
    source: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
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
