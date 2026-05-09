#!/usr/bin/env python3
"""Prepare PMC-only full text for COVID-19 serial-interval P13."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from metaagent.screening.fulltext_pipeline import (
    MD_CACHE_DIR,
    PDF_CACHE_DIR,
    convert_pdfs_to_markdown,
    download_pdfs_batch,
)


EXP = "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus"
DISEASE = "covid19"
TOPIC = "serial_interval"
PROJECT = 13
OUT_DIR = REPO / "evaluation" / "screening_prompt_eval" / "fulltext_prepare"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    raw_path = REPO / "dataset" / DISEASE / "screening" / TOPIC / f"p{PROJECT}" / "raw.csv"
    screened_path = (
        REPO
        / "evaluation"
        / "screening"
        / DISEASE
        / TOPIC
        / f"p{PROJECT}"
        / "experiments"
        / EXP
        / f"project_{PROJECT}_screened.csv"
    )

    raw_rows = {(row.get("PMID") or "").strip(): row for row in read_csv(raw_path)}
    screened_rows = read_csv(screened_path)
    pmids: list[str] = []
    overrides: dict[str, dict[str, str]] = {}

    for row in screened_rows:
        pmid = (row.get("PMID") or "").strip()
        if not pmid:
            continue
        pmids.append(pmid)
        raw = raw_rows.get(pmid, {})
        doi = (row.get("DOI") or raw.get("DOI") or "").strip()
        pmcid = (row.get("PMCID") or raw.get("PMCID") or "").strip()
        if doi or pmcid:
            overrides[pmid] = {"doi": doi, "pmcid": pmcid}

    print(
        f"Preparing PMC full text for {DISEASE}/{TOPIC}/p{PROJECT}: "
        f"{len(pmids)} screened records"
    )
    print(f"PDF cache: {PDF_CACHE_DIR}")
    print(f"Markdown cache: {MD_CACHE_DIR}")

    pdf_results = download_pdfs_batch(pmids, overrides, source_strategy="pmc_only")
    md_results = convert_pdfs_to_markdown(pdf_results)

    rows: list[dict[str, str]] = []
    for pmid in pmids:
        pdf_info = pdf_results.get(pmid, {})
        md_info = md_results.get(pmid, {})
        rows.append(
            {
                "pmid": pmid,
                "pdf_status": pdf_info.get("status", ""),
                "pdf_path": pdf_info.get("pdf_path", ""),
                "md_status": md_info.get("status", ""),
                "md_path": md_info.get("md_path", ""),
                "pmcid": overrides.get(pmid, {}).get("pmcid", ""),
                "doi": overrides.get(pmid, {}).get("doi", ""),
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest = OUT_DIR / f"p13_pmc_fulltext_prepare_{ts}.json"
    csv_path = OUT_DIR / f"p13_pmc_fulltext_prepare_{ts}.csv"
    manifest.write_text(
        json.dumps(
            {
                "disease": DISEASE,
                "topic": TOPIC,
                "project": PROJECT,
                "screened_records": len(pmids),
                "pdf_downloaded": sum(1 for row in rows if row["pdf_status"] == "downloaded"),
                "pdf_missing": sum(1 for row in rows if row["pdf_status"] != "downloaded"),
                "md_converted": sum(1 for row in rows if row["md_status"] == "converted"),
                "md_missing": sum(1 for row in rows if row["md_status"] != "converted"),
                "csv": str(csv_path.relative_to(REPO)),
                "rows": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {manifest.relative_to(REPO)}")
    print(f"Wrote {csv_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
