"""Inspect PubMed CSV metadata before screening."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MetadataCompleteness:
    """Counts of fields used by title-and-abstract screening."""

    total_rows: int
    missing_pmid: int
    missing_title: int
    missing_abstract: int
    missing_keywords: int

    @property
    def needs_screening_enrichment(self) -> bool:
        """Return whether required screening text is incomplete."""
        return bool(self.missing_title or self.missing_abstract)

    @property
    def has_optional_gaps(self) -> bool:
        """Return whether optional keyword metadata is incomplete."""
        return bool(self.missing_keywords)


def inspect_csv_metadata(path: Path) -> MetadataCompleteness:
    """Count missing PMID, title, abstract, and keyword values in a CSV."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    def missing_count(field: str) -> int:
        return sum(not str(row.get(field, "") or "").strip() for row in rows)

    return MetadataCompleteness(
        total_rows=len(rows),
        missing_pmid=missing_count("PMID"),
        missing_title=missing_count("Title"),
        missing_abstract=missing_count("Abstract"),
        missing_keywords=missing_count("Keywords"),
    )


__all__ = ["MetadataCompleteness", "inspect_csv_metadata"]
