"""Shared utilities for psychology literature search."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Iterable, Dict, Any, Optional, Sequence

# Set CSV field size limit to maximum possible value
# Try sys.maxsize first, fall back to 2GB on Windows where sys.maxsize may overflow
try:
    csv.field_size_limit(sys.maxsize)
except (AttributeError, ValueError, OverflowError):
    try:
        csv.field_size_limit(2**31 - 1)  # 2GB, works on most systems
    except (AttributeError, ValueError, OverflowError):
        pass  # Use default limit if all attempts fail


def export_records(
    records: Iterable[Dict[str, Any]],
    output_dir: Path,
    basename: str,
    *,
    write_json: bool = True,
    write_csv: bool = True,
    fieldnames: Optional[Sequence[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    flatten_dimension_scores: bool = True,
) -> Dict[str, Path]:
    """Export records to JSON/CSV for downstream pipelines.

    Args:
        records: Iterable of dict records.
        output_dir: Directory to write outputs.
        basename: Base filename without extension.
        write_json: Whether to write JSON output.
        write_csv: Whether to write CSV output.
        fieldnames: Optional explicit CSV columns.
        metadata: Optional metadata to include in JSON output.
        flatten_dimension_scores: If True, expands dimension_scores dict into
            separate columns for CSV export (e.g., dim_disease_relevance).

    Returns:
        Mapping of output type to path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    records_list = list(records)
    outputs: Dict[str, Path] = {}

    if write_json:
        json_path = output_dir / f"{basename}.json"
        payload = {"metadata": metadata or {}, "records": records_list}
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        outputs["json"] = json_path

    if write_csv:
        csv_path = output_dir / f"{basename}.csv"

        # Prepare records for CSV - flatten dimension scores if present
        csv_records = []
        for rec in records_list:
            csv_rec = dict(rec)

            # Flatten dimension_scores dict into separate columns
            if flatten_dimension_scores and "dimension_scores" in csv_rec:
                dim_scores = csv_rec.pop("dimension_scores")
                if isinstance(dim_scores, dict):
                    for dim_name, dim_value in dim_scores.items():
                        csv_rec[f"dim_{dim_name}"] = dim_value

            # Remove nested structures that don't work well in CSV
            if "dimension_rationales" in csv_rec:
                # Store as JSON string in CSV
                csv_rec["dimension_rationales_json"] = json.dumps(
                    csv_rec.pop("dimension_rationales")
                )

            # Keep other fields as-is
            csv_records.append(csv_rec)

        if fieldnames is None and csv_records:
            # Auto-detect fieldnames, ensuring dimension columns come after standard fields
            standard_fields = [
                "id",
                "title",
                "authors",
                "year",
                "abstract",
                "journal",
                "doi",
                "source",
                "screen_decision",
                "screen_reason",
                "overall_score",
                "confidence",
            ]
            all_keys = set()
            for rec in csv_records:
                all_keys.update(rec.keys())

            # Order: standard fields first, then dimension fields, then others
            fieldnames = []
            for field in standard_fields:
                if field in all_keys:
                    fieldnames.append(field)
                    all_keys.remove(field)

            # Add dimension score fields
            dim_fields = sorted([k for k in all_keys if k.startswith("dim_")])
            fieldnames.extend(dim_fields)
            for f in dim_fields:
                all_keys.remove(f)

            # Add remaining fields
            fieldnames.extend(sorted(all_keys))

        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames or [])
            if fieldnames:
                writer.writeheader()
                for record in csv_records:
                    writer.writerow(record)
        outputs["csv"] = csv_path

    return outputs


def generate_prisma_mermaid(data: Dict[str, Any], output_path: Path) -> Path:
    """Generate a simple PRISMA flow in Mermaid format.

    Expects keys:
      identified, duplicates, screened, excluded_screening,
      full_text, excluded_full_text, included
    """
    identified = data.get("identified", 0)
    duplicates = data.get("duplicates", 0)
    screened = data.get("screened", 0)
    excluded_screening = data.get("excluded_screening", 0)
    full_text = data.get("full_text", 0)
    excluded_full_text = data.get("excluded_full_text", 0)
    included = data.get("included", 0)

    mermaid = f"""flowchart TB
    id1[Identification\\nRecords identified: {identified}]
    id2[Duplicates removed: {duplicates}]
    sc1[Screening\\nRecords screened: {screened}]
    sc2[Excluded at screening: {excluded_screening}]
    el1[Eligibility\\nFull-text assessed: {full_text}]
    el2[Excluded full-text: {excluded_full_text}]
    in1[Included\\nStudies included: {included}]

    id1 --> id2 --> sc1 --> sc2
    sc1 --> el1 --> el2 --> in1
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(mermaid, encoding="utf-8")
    return output_path


def generate_prisma_png_from_mermaid(mermaid_path: Path, output_path: Path) -> Path:
    """Render Mermaid to PNG via kroki.io. Best-effort: if request fails, raises."""
    import requests

    mermaid = mermaid_path.read_text(encoding="utf-8")
    resp = requests.post(
        "https://kroki.io/mermaid/png",
        data=mermaid.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
        timeout=30,
    )
    resp.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(resp.content)
    return output_path
