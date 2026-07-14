#!/usr/bin/env python3
"""Fetch/convert PMC full text for E2E full-text-filter missing candidates."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metaagent.screening.fulltext_pipeline import (  # noqa: E402
    MD_CACHE_DIR,
    PDF_CACHE_DIR,
    prepare_fulltext_candidates,
)


DEFAULT_EXPERIMENT_DIR = (
    ROOT
    / "e2e"
    / "runs"
    / "screen_to_coding"
    / "fulltext_filter_experiments"
    / "glm51_existing_md_20260619"
)


def _has_pdf(pmid: str) -> bool:
    return (PDF_CACHE_DIR / f"PMID_{pmid}.pdf").exists()


def _has_markdown(pmid: str) -> bool:
    return (
        (MD_CACHE_DIR / f"PMID_{pmid}" / "fulltext.md").exists()
        or (MD_CACHE_DIR / f"PMID_{pmid}" / f"PMID_{pmid}.md").exists()
    )


def _truthy_pmcid(value: Any) -> bool:
    return "PMC" in str(value or "").upper()


def _clean_cell(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _load_candidates(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"PMID": str})
    df["PMID"] = df["PMID"].astype(str).str.strip()
    df = df[df["PMID"].ne("") & df["PMID"].str.lower().ne("nan")].copy()
    df["has_pmcid"] = df.get("PMCID", "").map(_truthy_pmcid)
    df["has_pdf_before"] = df["PMID"].map(_has_pdf)
    df["has_markdown_before"] = df["PMID"].map(_has_markdown)
    return df[~df["has_markdown_before"]].copy()


def _to_paper_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in df.to_dict("records"):
        rows.append(
            {
                "PMID": _clean_cell(row.get("PMID")),
                "PMCID": _clean_cell(row.get("PMCID")),
                "DOI": _clean_cell(row.get("DOI")),
                "Title": _clean_cell(row.get("Title") or row.get("Title_src")),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT_DIR)
    parser.add_argument("--profiles", nargs="*", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--known-pmcid-or-pdf-only",
        action="store_true",
        help="Only process rows that already have PMCID metadata or cached PDF.",
    )
    parser.add_argument(
        "--source-strategy",
        choices=["pmc_only", "cache_only"],
        default="pmc_only",
    )
    parser.add_argument("--out-name", default="missing_pmc_fulltext_prepare")
    args = parser.parse_args()

    experiment_dir = args.experiment_dir.resolve()
    candidates_path = experiment_dir / "missing_fulltext_candidates_with_cache.csv"
    if not candidates_path.exists():
        raise FileNotFoundError(
            f"{candidates_path} not found. Build it from fulltext_filter_decisions first."
        )

    df = _load_candidates(candidates_path)
    if args.profiles:
        wanted = {p.upper() for p in args.profiles}
        df = df[df["profile"].astype(str).str.upper().isin(wanted)].copy()
    if args.known_pmcid_or_pdf_only:
        df = df[df["has_pmcid"] | df["has_pdf_before"]].copy()
    if args.limit is not None:
        df = df.head(args.limit).copy()

    out_prefix = experiment_dir / args.out_name
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    selected_path = out_prefix.with_suffix(".selected.csv")
    errors_path = out_prefix.with_suffix(".errors.csv")
    summary_path = out_prefix.with_suffix(".summary.json")
    df.to_csv(selected_path, index=False)

    # Fetch/convert once per PMID; the status table below maps the resulting
    # cache state back to every profile row that referenced that PMID.
    unique_df = df.drop_duplicates(subset=["PMID"], keep="first").copy()
    papers = _to_paper_rows(unique_df)
    errors: list[dict[str, str]] = []
    ready, pdf_results, md_results = prepare_fulltext_candidates(
        papers_without_abstract=papers,
        fulltext_cached=[],
        fulltext_errors=errors,
        source_strategy=args.source_strategy,
    )

    status_rows = []
    ready_pmids = {(row.get("PMID") or "").strip() for row in ready}
    for _, row in df.iterrows():
        pmid = str(row["PMID"]).strip()
        status_rows.append(
            {
                "profile": row.get("profile", ""),
                "topic": row.get("topic", ""),
                "PMID": pmid,
                "is_ground_truth": bool(row.get("is_ground_truth", False)),
                "PMCID": row.get("PMCID", ""),
                "has_pdf_before": bool(row.get("has_pdf_before", False)),
                "has_markdown_before": bool(row.get("has_markdown_before", False)),
                "pdf_status": (pdf_results.get(pmid) or {}).get("status", ""),
                "pdf_path": (pdf_results.get(pmid) or {}).get("pdf_path", ""),
                "md_status": (md_results.get(pmid) or {}).get("status", ""),
                "md_path": (md_results.get(pmid) or {}).get("md_path", ""),
                "has_markdown_after": _has_markdown(pmid),
                "ready_for_screening": pmid in ready_pmids or _has_markdown(pmid),
            }
        )
    status = pd.DataFrame(status_rows)
    status_path = out_prefix.with_suffix(".status.csv")
    status.to_csv(status_path, index=False)
    pd.DataFrame(errors).to_csv(errors_path, index=False)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "experiment_dir": str(experiment_dir),
        "candidate_rows": int(len(df)),
        "unique_pmids": int(len(unique_df)),
        "known_pmcid_or_pdf_only": bool(args.known_pmcid_or_pdf_only),
        "source_strategy": args.source_strategy,
        "ready_count": int(status["ready_for_screening"].sum()) if not status.empty else 0,
        "markdown_after_count": int(status["has_markdown_after"].sum()) if not status.empty else 0,
        "pdf_downloaded_or_cached_count": int(
            status["pdf_status"].eq("downloaded").sum()
        )
        if not status.empty
        else 0,
        "errors_count": len(errors),
        "selected_csv": str(selected_path),
        "status_csv": str(status_path),
        "errors_csv": str(errors_path),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
