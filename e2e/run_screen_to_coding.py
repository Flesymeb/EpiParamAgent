"""Run coding/extraction from existing screening outputs.

This driver does not rerun screening. It reads a previously generated
``project_*_screened.csv``, keeps selected screening tiers, writes the selected
PMIDs as the coding input, and optionally invokes the production coding
pipeline on those PMIDs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metaagent.coding.pipeline.extraction import (  # noqa: E402
    _markdown_cache_path,
    _paper_pool_dirs,
    run_pipeline,
)
from metaagent.config import load_llm_config  # noqa: E402


DEFAULT_SCREENING_EXPERIMENT = (
    "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus"
)
DEFAULT_PROVIDER = None
DEFAULT_MODEL = None


def _slug(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace("/", "_")
        .replace("-", "_")
        .replace(".", "_")
        .replace(" ", "_")
    )


def _find_screening_csv(
    *,
    disease: str,
    topic: str,
    project: str,
    experiment: str,
) -> Path:
    project_num = project.lower().removeprefix("p")
    base = (
        ROOT
        / "evaluation"
        / "screening"
        / disease
        / topic
        / f"p{project_num}"
        / "experiments"
        / experiment
    )
    direct = base / f"project_{project_num}_screened.csv"
    if direct.exists():
        return direct
    matches = sorted(base.glob(f"screening_runs/*/project_{project_num}_screened.csv"))
    if matches:
        return matches[-1]
    raise FileNotFoundError(
        f"No screening CSV found for {disease}/{topic}/p{project_num} in {base}"
    )


def _truthy_gt(series: pd.Series) -> pd.Series:
    values = series.astype(str).str.strip().str.lower()
    return series.notna() & ~values.isin({"", "nan", "none", "false", "0"})


def _read_gt_pmids(disease: str, topic: str, project: str) -> set[str]:
    project_num = project.lower().removeprefix("p")
    path = ROOT / "dataset" / disease / "screening" / topic / f"p{project_num}" / "ground_truth.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path)
    pmid_col = "gt_pmid" if "gt_pmid" in df.columns else "PMID" if "PMID" in df.columns else None
    if not pmid_col:
        return set()
    return {
        str(x).strip()
        for x in df[pmid_col].dropna().tolist()
        if str(x).strip() and str(x).strip().lower() != "nan"
    }


def _normalize_tiers(tiers: Iterable[str]) -> set[str]:
    mapping = {
        "strong": "S",
        "strong_candidate": "S",
        "s": "S",
        "possible": "P",
        "possible_candidate": "P",
        "p": "P",
        "unlikely": "U",
        "unlikely_candidate": "U",
        "u": "U",
    }
    normalized = set()
    for tier in tiers:
        key = str(tier).strip().lower()
        normalized.add(mapping.get(key, str(tier).strip().upper()))
    return normalized


def _selected_mask(df: pd.DataFrame, tiers: set[str]) -> pd.Series:
    if "llm_tier" in df.columns:
        return df["llm_tier"].astype(str).str.strip().str.upper().isin(tiers)
    if "llm_suggest" in df.columns:
        suggest_to_tier = {
            "strong_candidate": "S",
            "possible_candidate": "P",
            "unlikely_candidate": "U",
        }
        mapped = df["llm_suggest"].astype(str).str.strip().str.lower().map(suggest_to_tier)
        return mapped.isin(tiers)
    raise ValueError("Screening CSV must contain llm_tier or llm_suggest")


def _cache_status(pmids: Iterable[str]) -> pd.DataFrame:
    pdf_dir, md_dir = _paper_pool_dirs()
    rows = []
    for pmid in pmids:
        pmid = str(pmid).strip()
        pdf = pdf_dir / f"PMID_{pmid}.pdf"
        md = _markdown_cache_path(md_dir, pmid)
        legacy_md = md_dir / f"PMID_{pmid}" / f"PMID_{pmid}.md"
        rows.append(
            {
                "pmid": pmid,
                "pdf_cached": pdf.exists(),
                "markdown_cached": md.exists() or legacy_md.exists(),
                "has_cached_fulltext": pdf.exists() or md.exists() or legacy_md.exists(),
                "pdf_path": str(pdf) if pdf.exists() else "",
                "markdown_path": str(md if md.exists() else legacy_md if legacy_md.exists() else ""),
            }
        )
    return pd.DataFrame(rows)


def _write_pmids(path: Path, pmids: list[str]) -> None:
    path.write_text("\n".join(pmids) + ("\n" if pmids else ""), encoding="utf-8")


def _read_pmids_file(path: Path) -> set[str]:
    if not path.exists():
        raise FileNotFoundError(path)
    pmids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and value.lower() != "nan":
            pmids.add(value)
    return pmids


def _clear_proxy_env() -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(name, None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disease", required=True, choices=("covid19", "mpox"))
    parser.add_argument("--topic", required=True, choices=("serial_interval", "reproduction_number", "fatality"))
    parser.add_argument("--project", required=True, help="Project id, e.g. p13 or 13")
    parser.add_argument("--screening-csv", type=Path, default=None)
    parser.add_argument("--screening-experiment", default=DEFAULT_SCREENING_EXPERIMENT)
    parser.add_argument("--tiers", default="S,P", help="Comma-separated tiers to send to coding")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--stage", default="both", choices=("fetch", "index", "extract", "both"))
    parser.add_argument("--fetch-strategy", default="pmc_only")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--limit", type=int, default=None, help="Optional small-batch smoke-test limit")
    parser.add_argument(
        "--input-pmids-file",
        type=Path,
        default=None,
        help=(
            "Optional explicit PMID order for the coding input. PMIDs not present "
            "in the selected S/P screening set are ignored. The full selected set "
            "is still written to screened_sp_pmids.txt for later merging."
        ),
    )
    parser.add_argument(
        "--skip-pmids-file",
        type=Path,
        action="append",
        default=[],
        help=(
            "PMID list(s) to exclude from the coding input, e.g. records already "
            "completed or currently running in another E2E job. The full S/P "
            "selection is still written for later merging."
        ),
    )
    parser.add_argument("--fresh", action="store_true", help="Remove output dir before running coding")
    parser.add_argument("--run-coding", action="store_true", help="Invoke coding pipeline after preparing PMIDs")
    parser.add_argument(
        "--disable-proxy",
        action="store_true",
        help=(
            "Clear HTTP(S)/ALL proxy variables after loading .env.local. "
            "Useful when a local proxy is configured but unavailable."
        ),
    )
    args = parser.parse_args()

    project_num = args.project.lower().removeprefix("p")
    screening_csv = (
        args.screening_csv.resolve()
        if args.screening_csv
        else _find_screening_csv(
            disease=args.disease,
            topic=args.topic,
            project=project_num,
            experiment=args.screening_experiment,
        )
    )

    llm_overrides = {
        "provider": args.provider,
        "model": args.model,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
    }
    resolved_llm = load_llm_config(llm_overrides, module_hint="coding")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir
    if out_dir is None:
        out_dir = (
            ROOT
            / "e2e"
            / "runs"
            / "screen_to_coding"
            / f"{args.disease}_{args.topic}_p{project_num}_{_slug(resolved_llm.model or 'env_model')}_{run_id}"
        )
    out_dir = out_dir.resolve()
    if args.fresh and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(screening_csv)
    if "PMID" not in df.columns:
        raise ValueError(f"{screening_csv} does not contain a PMID column")
    df["PMID"] = df["PMID"].astype(str).str.strip()
    df = df[df["PMID"].ne("") & df["PMID"].str.lower().ne("nan")].copy()

    tiers = _normalize_tiers(args.tiers.split(","))
    selected = df[_selected_mask(df, tiers)].copy()
    selected = selected.drop_duplicates(subset=["PMID"], keep="first")
    if args.limit is not None:
        selected = selected.head(args.limit).copy()

    gt_pmids = _read_gt_pmids(args.disease, args.topic, project_num)
    selected_pmids = selected["PMID"].astype(str).tolist()
    skip_pmids: set[str] = set()
    for skip_file in args.skip_pmids_file:
        skip_pmids.update(_read_pmids_file(skip_file.resolve()))
    if args.input_pmids_file:
        requested_pmids = [
            pmid
            for pmid in _read_pmids_file(args.input_pmids_file.resolve())
            if pmid in set(selected_pmids)
        ]
        coding_pmids = [pmid for pmid in requested_pmids if pmid not in skip_pmids]
    else:
        requested_pmids = selected_pmids
        coding_pmids = [pmid for pmid in selected_pmids if pmid not in skip_pmids]
    skipped_pmids = [pmid for pmid in selected_pmids if pmid in skip_pmids]

    gt_in_selected = [pmid for pmid in selected_pmids if pmid in gt_pmids]
    gt_missed = sorted(gt_pmids - set(selected_pmids), key=lambda x: int(x) if x.isdigit() else x)
    non_gt_selected = [pmid for pmid in selected_pmids if pmid not in gt_pmids]

    selected_cache = _cache_status(selected_pmids)
    coding_cache = _cache_status(coding_pmids)
    selected_pmids_path = out_dir / "screened_sp_pmids.txt"
    pmids_path = out_dir / "coding_input_pmids.txt"
    skipped_pmids_path = out_dir / "skipped_reuse_or_inflight_pmids.txt"
    selected_csv = out_dir / "screening_selected_records.csv"
    selected_cache_csv = out_dir / "fulltext_cache_status.csv"
    coding_cache_csv = out_dir / "coding_input_fulltext_cache_status.csv"
    summary_path = out_dir / "screen_to_coding_summary.json"

    _write_pmids(selected_pmids_path, selected_pmids)
    _write_pmids(pmids_path, coding_pmids)
    _write_pmids(skipped_pmids_path, skipped_pmids)
    selected.to_csv(selected_csv, index=False)
    selected_cache.to_csv(selected_cache_csv, index=False)
    coding_cache.to_csv(coding_cache_csv, index=False)

    if args.disable_proxy:
        _clear_proxy_env()

    summary = {
        "disease": args.disease,
        "topic": args.topic,
        "project": f"p{project_num}",
        "screening_csv": str(screening_csv),
        "tiers": sorted(tiers),
        "limit": args.limit,
        "screening_rows": int(len(df)),
        "selected_rows": int(len(selected)),
        "coding_input_count": int(len(coding_pmids)),
        "skipped_reuse_or_inflight_count": int(len(skipped_pmids)),
        "skip_pmids_files": [str(p.resolve()) for p in args.skip_pmids_file],
        "input_pmids_file": str(args.input_pmids_file.resolve()) if args.input_pmids_file else None,
        "requested_coding_input_count": int(len(requested_pmids)),
        "gt_total": int(len(gt_pmids)),
        "screening_tp_in_selected": int(len(gt_in_selected)),
        "screening_fp_in_selected": int(len(non_gt_selected)),
        "screening_fn_not_selected": int(len(gt_missed)),
        "selected_cached_fulltext_count": int(selected_cache["has_cached_fulltext"].sum()) if not selected_cache.empty else 0,
        "selected_missing_fulltext_count": int((~selected_cache["has_cached_fulltext"]).sum()) if not selected_cache.empty else 0,
        "coding_cached_fulltext_count": int(coding_cache["has_cached_fulltext"].sum()) if not coding_cache.empty else 0,
        "coding_missing_fulltext_count": int((~coding_cache["has_cached_fulltext"]).sum()) if not coding_cache.empty else 0,
        "coding_missing_fulltext_pmids": coding_cache.loc[~coding_cache["has_cached_fulltext"], "pmid"].tolist() if not coding_cache.empty else [],
        "pmids_input": str(pmids_path),
        "selected_pmids_input": str(selected_pmids_path),
        "skipped_pmids": str(skipped_pmids_path),
        "selected_csv": str(selected_csv),
        "cache_csv": str(selected_cache_csv),
        "coding_cache_csv": str(coding_cache_csv),
        "out_dir": str(out_dir),
        "llm": {
            "provider": resolved_llm.provider,
            "model": resolved_llm.model,
            "api_base": resolved_llm.api_base,
            "temperature": resolved_llm.temperature,
            "max_tokens": resolved_llm.max_tokens,
            "timeout_s": resolved_llm.timeout_s,
            "disable_proxy": args.disable_proxy,
        },
        "coding_ran": False,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.run_coding:
        if not coding_pmids:
            summary["coding_ran"] = False
            summary["coding_skipped_reason"] = "empty coding input after skip-pmids filtering"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"[OK] wrote {summary_path}")
            return
        codebook = ROOT / "configs" / args.disease / "codebooks" / f"{args.topic}.yaml"
        t0 = time.time()
        run_pipeline(
            input_path=pmids_path,
            out_dir=out_dir,
            stage=args.stage,
            codebook_path=codebook,
            fetch_strategy=args.fetch_strategy,
            llm_overrides=llm_overrides,
        )
        summary["coding_ran"] = True
        summary["coding_elapsed_s"] = round(time.time() - t0, 1)
        xlsx_files = sorted(out_dir.glob("coding_sheet*.xlsx"), key=lambda p: p.stat().st_mtime)
        summary["coding_xlsx"] = str(xlsx_files[-1]) if xlsx_files else None
        summary["coding_record_count"] = int(len(pd.read_excel(xlsx_files[-1]))) if xlsx_files else 0

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] wrote {summary_path}")


if __name__ == "__main__":
    main()
