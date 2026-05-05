"""Evaluate coding extraction results: compute pooled mean per project.

Scans evaluation/coding/{disease}/{topic}/{project}/coding_runs/ for the latest run,
applies enrich_ci + summarize, and writes a consolidated summary CSV.

Usage
-----
# All projects (auto-discover):
uv run --directory dev python dev/literature_search/scripts/cli/evaluate_coding.py

# Specific disease:
uv run --directory dev python dev/literature_search/scripts/cli/evaluate_coding.py --disease covid19

# Specific disease + topic:
uv run --directory dev python dev/literature_search/scripts/cli/evaluate_coding.py --disease covid19 --topic serial_interval

# Specific project:
uv run --directory dev python dev/literature_search/scripts/cli/evaluate_coding.py --disease mpox --topic fatality --project p4

# Override method / parameter filter:
uv run --directory dev python dev/literature_search/scripts/cli/evaluate_coding.py \
    --disease covid19 --parameter-type serial_interval --estimate-measure mean --include-median --impute-se

Output
------
evaluation/coding/pooled_summary_{YYYYMMDD}.csv
  disease, topic, project, parameter_type, n_studies, n_excluded, n_imputed,
  pooled_mean, se_pooled, ci_lower, ci_upper, i2, tau2, p_het, run_used
"""

from __future__ import annotations

import argparse
import csv
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
CODING_ROOT = REPO_ROOT / "evaluation"  # {disease}/{topic}/coding/{project}/
TOOLS_SRC = REPO_ROOT / "tools"

for p in (TOOLS_SRC,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools.analysis.pooling import enrich_ci, summarize  # type: ignore

# Topic → default parameter_type filter for pooling
TOPIC_PARAM = {
    "serial_interval":     "serial_interval",
    "reproduction_number": "R0",
    "fatality":            "CFR",
}


def _latest_xlsx(project_dir: Path) -> Path | None:
    """Return the xlsx with the most data rows from timestamp-style coding_runs dirs.

    Prefers timestamp directories (YYYYMMDD_*) over ad-hoc names.
    Among those, picks the xlsx with the highest row count (most complete run),
    breaking ties by most recent timestamp.
    """
    import re
    runs_dir = project_dir / "coding_runs"
    if not runs_dir.exists():
        return None

    ts_pattern = re.compile(r"^\d{8}_")
    all_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
    ts_dirs = sorted([d for d in all_dirs if ts_pattern.match(d.name)], reverse=True)
    other_dirs = sorted([d for d in all_dirs if not ts_pattern.match(d.name)], reverse=True)

    candidates: list[tuple[int, str, Path]] = []
    for run_dir in ts_dirs + other_dirs:
        for xlsx in run_dir.glob("*.xlsx"):
            try:
                import pandas as pd
                n_rows = len(pd.read_excel(xlsx, usecols=[0]))  # fast: only first col
            except Exception:
                n_rows = 0
            # Sort key: (-n_rows, -timestamp_str) → most rows first, then most recent
            candidates.append((n_rows, run_dir.name, xlsx))

    if not candidates:
        return None
    # Pick highest row count; break ties by latest timestamp (lexicographic desc)
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][2]


def evaluate_project(
    topic: str,
    project: str,
    project_dir: Path,
    parameter_type: str,
    estimate_measure: str,
    include_median: bool,
    impute_se: bool,
    method: str,
) -> dict | None:
    xlsx = _latest_xlsx(project_dir)
    if xlsx is None:
        print(f"  [{topic}/{project}] No coding_runs found, skipping.")
        return None

    print(f"  [{topic}/{project}] Using {xlsx.parent.name}/{xlsx.name}")

    try:
        df = pd.read_excel(xlsx)
    except Exception as exc:
        print(f"  [{topic}/{project}] Failed to read xlsx: {exc}")
        return None

    # Check parameter_type column
    if "parameter_type" in df.columns:
        available = df["parameter_type"].dropna().unique().tolist()
        if parameter_type not in available:
            # Try case-insensitive match
            match = next(
                (p for p in available if p.lower().strip() == parameter_type.lower()),
                None,
            )
            if match:
                parameter_type = match
            else:
                print(f"  [{topic}/{project}] parameter_type '{parameter_type}' not found. "
                      f"Available: {available}. Trying without filter.")
                parameter_type = None  # type: ignore
    else:
        # Column doesn't exist — skip parameter_type filter
        parameter_type = None

    df_enriched = enrich_ci(df)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        summary = summarize(
            df_enriched,
            parameter_type=parameter_type,
            estimate_measure=estimate_measure,
            include_median=include_median,
            impute_missing_se=impute_se,
            method=method,
        )
        for w in caught:
            print(f"    [warn] {w.message}")

    if summary.empty:
        print(f"  [{topic}/{project}] summarize returned empty.")
        return None

    r = summary.iloc[0]
    return {
        "topic": topic,
        "project": project,
        "parameter_type": parameter_type or "all",
        "estimate_measure": estimate_measure,
        "include_median": include_median,
        "impute_se": impute_se,
        "method": method,
        "n_studies": int(r.get("n_studies", 0)),
        "n_excluded": int(r.get("n_excluded", 0)),
        "n_imputed": int(r.get("n_imputed", 0)),
        "pooled_mean": round(float(r.get("pooled_mean", float("nan"))), 4),
        "se_pooled": round(float(r.get("se_pooled", float("nan"))), 4),
        "ci_lower": round(float(r.get("ci_lower", float("nan"))), 4),
        "ci_upper": round(float(r.get("ci_upper", float("nan"))), 4),
        "i2": round(float(r.get("i2", float("nan"))), 1),
        "tau2": round(float(r.get("tau2", float("nan"))), 4),
        "p_het": round(float(r.get("p_het", float("nan"))), 4),
        "run_used": str(xlsx.parent.name),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute pooled means from coding extraction results."
    )
    parser.add_argument("--disease", default=None, help="Filter by disease (e.g. covid19, mpox).")
    parser.add_argument("--topic", default=None, help="Filter by topic (e.g. serial_interval).")
    parser.add_argument("--project", default=None, help="Filter by project (e.g. p13).")
    parser.add_argument("--parameter-type", default=None,
                        help="Override parameter_type filter (default: inferred from topic).")
    parser.add_argument("--estimate-measure", default="mean",
                        help="Estimate measure to pool (default: mean).")
    parser.add_argument("--include-median", action="store_true",
                        help="Include medians as mean approximations (per Ali 2021 Rule i).")
    parser.add_argument("--impute-se", action="store_true", default=True,
                        help="Impute missing SE from pooled within-study SD (default: True).")
    parser.add_argument("--no-impute-se", dest="impute_se", action="store_false")
    parser.add_argument("--method", default="random", choices=["random", "fixed"])
    parser.add_argument("--output", default=None,
                        help="Output CSV path. Default: evaluation/coding/pooled_summary_YYYYMMDD.csv")
    args = parser.parse_args()

    if not CODING_ROOT.exists():
        print(f"ERROR: {CODING_ROOT} not found.")
        sys.exit(1)

    # Discover projects — three-level: disease → topic → coding/{project}
    _SKIP_DIRS = {"GT_papers", "figures", "_summary", "screening", "ground_truth"}
    projects_to_run: list[tuple[str, str, str, Path]] = []
    for disease_dir in sorted(CODING_ROOT.iterdir()):
        if not disease_dir.is_dir() or disease_dir.name.startswith("_"):
            continue
        if args.disease and disease_dir.name != args.disease:
            continue
        for topic_dir in sorted(disease_dir.iterdir()):
            if not topic_dir.is_dir() or topic_dir.name in _SKIP_DIRS:
                continue
            if args.topic and topic_dir.name != args.topic:
                continue
            coding_dir = topic_dir / "coding"
            if not coding_dir.is_dir():
                continue
            for project_dir in sorted(coding_dir.iterdir()):
                if not project_dir.is_dir() or project_dir.name.startswith("_"):
                    continue
                if args.project and project_dir.name != args.project:
                    continue
                projects_to_run.append((disease_dir.name, topic_dir.name, project_dir.name, project_dir))

    if not projects_to_run:
        print("No projects found matching filters.")
        sys.exit(0)

    print(f"Found {len(projects_to_run)} project(s) to evaluate.\n")

    rows = []
    for disease, topic, project, project_dir in projects_to_run:
        param_type = args.parameter_type or TOPIC_PARAM.get(topic, "serial_interval")
        if topic == "fatality":
            print(f"  [{disease}/{topic}/{project}] NOTE: CFR/IFR is a proportion — "
                  "pooled_mean here is arithmetic average (may be biased). "
                  "For publication-quality meta-analysis use logit transform.")
        result = evaluate_project(
            topic=topic,
            project=project,
            project_dir=project_dir,
            parameter_type=param_type,
            estimate_measure=args.estimate_measure,
            include_median=args.include_median,
            impute_se=args.impute_se,
            method=args.method,
        )
        if result:
            result["disease"] = disease
            rows.append(result)

    if not rows:
        print("\nNo results produced.")
        return

    out_path = Path(args.output) if args.output else (
        CODING_ROOT / f"pooled_summary_{datetime.now().strftime('%Y%m%d')}.csv"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "disease", "topic", "project", "parameter_type", "estimate_measure",
        "include_median", "impute_se", "method",
        "n_studies", "n_excluded", "n_imputed",
        "pooled_mean", "se_pooled", "ci_lower", "ci_upper",
        "i2", "tau2", "p_het", "run_used",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n=== Summary ===")
    df_out = pd.DataFrame(rows)
    print(df_out[["disease","topic","project","n_studies","n_excluded","n_imputed",
                   "pooled_mean","ci_lower","ci_upper","i2"]].to_string(index=False))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
