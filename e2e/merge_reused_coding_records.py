"""Merge reused and newly coded records for a screening-to-coding E2E run.

The coding stage is PMID-level reusable within the same disease/parameter
codebook. This utility reconstructs a project-level coding sheet by taking the
project's selected PMID list and collecting matching rows from any completed
coding sheets plus the current run's newly coded sheet.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd


def _read_pmids(path: Path) -> list[str]:
    pmids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and value.lower() != "nan":
            pmids.append(value)
    return pmids


def _pmid(value: object) -> str | None:
    match = re.search(r"\d+", str(value))
    return match.group(0) if match else None


def _expand_paths(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        matches = glob.glob(value)
        if matches:
            paths.extend(Path(m) for m in matches)
        else:
            paths.append(Path(value))
    return sorted({p.resolve() for p in paths if p.exists()})


def _load_records(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        df = pd.read_excel(path)
        if "pmid" not in df.columns:
            continue
        df = df.copy()
        df["pmid"] = df["pmid"].map(_pmid)
        df = df[df["pmid"].notna()].copy()
        df["_source_xlsx"] = str(path)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected-pmids", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--output-prefix", default="coding_sheet_merged_reuse")
    parser.add_argument(
        "--xlsx",
        action="append",
        default=[],
        help="Completed coding sheet path or shell glob. Can be repeated.",
    )
    args = parser.parse_args()

    selected_pmids = _read_pmids(args.selected_pmids.resolve())
    selected_set = set(selected_pmids)
    paths = _expand_paths(args.xlsx)
    records = _load_records(paths)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if records.empty:
        merged = pd.DataFrame()
    else:
        records = records[records["pmid"].isin(selected_set)].copy()
        # Keep exact duplicate rows only once, preferring earlier xlsx arguments.
        sort_cols = ["_source_xlsx"]
        records = records.sort_values(sort_cols, kind="stable")
        value_cols = [c for c in records.columns if c != "_source_xlsx"]
        merged = records.drop_duplicates(subset=value_cols, keep="first").copy()
        merged["_selected_order"] = merged["pmid"].map({pmid: i for i, pmid in enumerate(selected_pmids)})
        merged = merged.sort_values(["_selected_order", "pmid"], kind="stable")
        merged = merged.drop(columns=["_selected_order"])

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    xlsx_path = args.out_dir / f"{args.output_prefix}_{timestamp}.xlsx"
    csv_path = args.out_dir / f"{args.output_prefix}_{timestamp}.csv"
    summary_path = args.out_dir / f"{args.output_prefix}_{timestamp}.json"

    export = merged.drop(columns=["_source_xlsx"], errors="ignore")
    export.to_excel(xlsx_path, index=False)
    export.to_csv(csv_path, index=False)

    covered_pmids = set(export["pmid"].astype(str)) if "pmid" in export.columns else set()
    summary = {
        "selected_pmids": str(args.selected_pmids.resolve()),
        "selected_count": len(selected_pmids),
        "record_sources": [str(p) for p in paths],
        "source_count": len(paths),
        "merged_record_count": int(len(export)),
        "covered_pmid_count": len(covered_pmids),
        "missing_pmid_count": len(selected_set - covered_pmids),
        "missing_pmids": sorted(selected_set - covered_pmids, key=lambda x: int(x) if x.isdigit() else x),
        "xlsx": str(xlsx_path),
        "csv": str(csv_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
