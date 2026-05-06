#!/usr/bin/env python3
"""
Prepare screening raw CSV from PubMed query and optionally merge ground truth.

Workflow:
1) Query PubMed (ESearch + EFetch) -> raw CSV
2) Merge missing PMIDs from Ground Truth CSV
3) Fix missing Abstract/Keywords (optional)

Usage:
  python tools/scripts/screening_prepare.py --query "..." --date-range "2020/1/1-2021/9/10" --output raw.csv --ground-truth gt.csv --fix-missing
  python tools/scripts/screening_prepare.py --project-root /path/to/MetaAgent-Epi --profile P13
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List, Dict, Iterable

import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.pubmed.client import PubMedClient
from tools.provenance import write_run_manifest
from tools.scripts.pubmed_manager import fetch_paper_details, fix_missing_fields
from metaagent.screening.profile_registry import resolve_profile_paths


def _load_pmids_from_csv(path: Path) -> List[str]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        pmids = []
        for row in reader:
            pmid = None
            for key in row.keys():
                if key is None:
                    continue
                key_norm = key.lower()
                if key_norm in ("pmid", "gt_pmid") or key == "\ufeffPMID":
                    val = (row.get(key) or "").strip()
                    if val:
                        pmid = val
                        break
            if pmid and pmid.isdigit():
                pmids.append(pmid)
        return pmids


def _write_csv(rows: List[Dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    for row in rows[1:]:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with open(output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _dedupe_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    deduped = []
    for row in rows:
        pmid = (row.get("PMID") or "").strip()
        if pmid and pmid in seen:
            continue
        if pmid:
            seen.add(pmid)
        deduped.append(row)
    return deduped


def _chunk(items: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare raw screening CSV from PubMed")
    parser.add_argument("--project-root", default="", help="Repository root; used with --profile to resolve evaluation paths")
    parser.add_argument("--profile", default="", help="Screening profile name, e.g. P13")
    parser.add_argument("--disease", default="", help="Optional disease override, e.g. covid19 or mpox")
    parser.add_argument("--topic", default="", help="Optional topic override; defaults to the profile topic")
    parser.add_argument("--query", help="PubMed search term/query")
    parser.add_argument(
        "--date-range",
        default="",
        help="Publication date filter (e.g., 2020/1/1-2021/9/10)",
    )
    parser.add_argument("--retmax", default="all", help="Max records (int or 'all')")
    parser.add_argument(
        "--raw-input",
        default="",
        help="Existing raw CSV to merge GT into (skip PubMed search)",
    )
    parser.add_argument("--output", default="", help="Output raw CSV path")
    parser.add_argument("--ground-truth", default="", help="Ground truth CSV path")
    parser.add_argument(
        "--include-gt",
        action="store_true",
        help="Append GT PMIDs missing from raw",
    )
    parser.add_argument(
        "--fix-missing",
        action="store_true",
        help="Fix missing Abstract/Keywords in output",
    )
    parser.add_argument(
        "--medline-only",
        action="store_true",
        help="Restrict to MEDLINE indexed articles",
    )
    args = parser.parse_args()

    if args.project_root and args.profile:
        _, paths = resolve_profile_paths(
            project_root=args.project_root,
            profile_name=args.profile,
            topic=args.topic or None,
            disease=args.disease or None,
        )
        output_path = paths.raw_file
        gt_path = paths.ground_truth_file
        if not args.raw_input and paths.raw_file.exists():
            args.raw_input = str(paths.raw_file)
    else:
        if not args.output:
            raise ValueError("Either --output or --project-root/--profile must be provided.")
        output_path = Path(args.output)
        gt_path = Path(args.ground_truth) if args.ground_truth else None

    retmax = None
    if args.retmax and str(args.retmax).lower() != "all":
        try:
            retmax = int(args.retmax)
        except ValueError:
            retmax = None

    client = PubMedClient(medline_only=args.medline_only)
    rows: List[Dict[str, str]] = []
    if args.raw_input:
        raw_path = Path(args.raw_input)
        if not raw_path.exists():
            raise FileNotFoundError(f"Raw input not found: {raw_path}")
        with open(raw_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        print(f"[INFO] Loaded raw rows: {len(rows)}")
    else:
        if not args.query:
            raise ValueError("Either --query or --raw-input must be provided.")
        papers = client.search(args.query, retmax=retmax, year=args.date_range or None)
        pmids = [p.id.replace("pubmed:", "") for p in papers if p.id]
        print(f"[INFO] PubMed search hits: {len(pmids)}")
        if pmids:
            for chunk in _chunk(pmids, 50):
                rows.extend(fetch_paper_details(chunk, client))

    if args.include_gt and gt_path and gt_path.exists():
        gt_pmids = _load_pmids_from_csv(gt_path)
        raw_pmids = {r.get("PMID", "") for r in rows}
        missing = [p for p in gt_pmids if p and p not in raw_pmids]
        if missing:
            print(f"[INFO] Adding missing GT PMIDs: {len(missing)}")
            for chunk in _chunk(missing, 50):
                rows.extend(fetch_paper_details(chunk, client))
        else:
            print("[INFO] All GT PMIDs already in raw.")

    rows = _dedupe_rows(rows)
    _write_csv(rows, output_path)
    print(f"[OK] Raw CSV written: {output_path}")

    if args.fix_missing:
        fix_missing_fields(output_path, output_path)
        print(f"[OK] Missing fields fixed: {output_path}")

    manifest_path = write_run_manifest(
        output_dir=output_path.parent,
        workflow="prepare_raw",
        module="literature_search",
        params={
            "profile": args.profile or "",
            "topic": args.topic or "",
            "query": args.query or "",
            "date_range": args.date_range or "",
            "retmax": args.retmax,
            "include_gt": bool(args.include_gt),
            "fix_missing": bool(args.fix_missing),
            "medline_only": bool(args.medline_only),
        },
        inputs=[p for p in [args.raw_input, args.ground_truth] if p],
        outputs=[output_path],
        extra={
            "row_count": len(rows),
            "ground_truth_path": str(gt_path) if gt_path else None,
        },
    )
    print(f"[OK] Manifest written: {manifest_path}")


if __name__ == "__main__":
    main()
