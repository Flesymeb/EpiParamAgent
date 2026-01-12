"""Shared utilities for psychology literature search."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Dict, Any, Optional, Sequence


def export_records(
    records: Iterable[Dict[str, Any]],
    output_dir: Path,
    basename: str,
    *,
    write_json: bool = True,
    write_csv: bool = True,
    fieldnames: Optional[Sequence[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
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
        if fieldnames is None and records_list:
            fieldnames = list(records_list[0].keys())
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames or [])
            if fieldnames:
                writer.writeheader()
                for record in records_list:
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
