"""Inspect and complete PubMed CSV metadata used by screening."""

from __future__ import annotations

import csv
import json
import shutil
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import StringIO
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

    @property
    def has_any_gaps(self) -> bool:
        """Return whether any inspected metadata field is incomplete."""
        return bool(
            self.missing_pmid
            or self.missing_title
            or self.missing_abstract
            or self.missing_keywords
        )

    def as_dict(self) -> dict[str, int]:
        """Return a stable JSON-serializable representation."""
        return asdict(self)


@dataclass(frozen=True)
class MetadataCompletionResult:
    """Outcome of one explicit PubMed metadata-completion attempt."""

    input_path: Path
    output_path: Path
    backup_path: Path | None
    marker_path: Path
    before: MetadataCompleteness
    after: MetadataCompleteness
    log: str = ""

    def as_dict(self) -> dict[str, object]:
        """Return paths and before/after counts for CLI JSON output."""
        return {
            "attempted": True,
            "input": str(self.input_path),
            "output": str(self.output_path),
            "backup": str(self.backup_path) if self.backup_path else None,
            "marker": str(self.marker_path),
            "before": self.before.as_dict(),
            "after": self.after.as_dict(),
        }


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


def metadata_marker_path(path: Path) -> Path:
    """Return the marker written after a completion attempt."""
    path = Path(path)
    return path.with_name(f"{path.stem}.metadata_enrichment.json")


def complete_csv_metadata(
    input_path: Path,
    output_path: Path | None = None,
    *,
    create_backup: bool = True,
    quiet: bool = True,
) -> MetadataCompletionResult:
    """Retrieve available missing title, abstract, and keyword metadata.

    The operation is safe for in-place updates: the original CSV is copied to
    ``<stem>.before_enrichment.csv`` once, and a JSON marker records both the
    pre- and post-completion counts. Missing fields that PubMed itself does not
    provide remain empty.
    """
    from tools.scripts.pubmed_manager import fix_missing_fields

    source = Path(input_path).expanduser().resolve()
    target = Path(output_path or source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"PubMed CSV not found: {source}")

    before = inspect_csv_metadata(source)
    backup_path: Path | None = None
    if source == target and create_backup:
        backup_path = source.with_name(f"{source.stem}.before_enrichment{source.suffix}")
        if not backup_path.exists():
            shutil.copy2(source, backup_path)

    target.parent.mkdir(parents=True, exist_ok=True)
    captured = StringIO()
    if quiet:
        with redirect_stdout(captured):
            fix_missing_fields(source, target)
    else:
        fix_missing_fields(source, target)

    if not target.exists():
        # Empty retrievals have only a header and require no network repair.
        shutil.copy2(source, target)
    after = inspect_csv_metadata(target)
    marker = metadata_marker_path(target)
    marker.write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "input_csv": str(source),
                "output_csv": str(target),
                "before": before.as_dict(),
                "after": after.as_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return MetadataCompletionResult(
        input_path=source,
        output_path=target,
        backup_path=backup_path,
        marker_path=marker,
        before=before,
        after=after,
        log=captured.getvalue(),
    )


__all__ = [
    "MetadataCompleteness",
    "MetadataCompletionResult",
    "complete_csv_metadata",
    "inspect_csv_metadata",
    "metadata_marker_path",
]
