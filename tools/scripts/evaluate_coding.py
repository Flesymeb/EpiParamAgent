"""Evaluate coding extraction results: compute pooled mean per project.

Scans evaluation/coding/{disease}/{topic}/{project}/coding_runs/ for the latest run,
applies enrich_ci + summarize, and writes a consolidated summary CSV.

Usage
-----
# All projects (auto-discover):
python tools/scripts/evaluate_coding.py

# Specific disease:
python tools/scripts/evaluate_coding.py --disease covid19

# Specific disease + topic:
python tools/scripts/evaluate_coding.py --disease covid19 --topic serial_interval

# Specific project:
python tools/scripts/evaluate_coding.py --disease mpox --topic fatality --project p4

# Override method / parameter filter:
python tools/scripts/evaluate_coding.py \
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
CODING_ROOT = REPO_ROOT / "evaluation" / "coding"
TOOLS_SRC = REPO_ROOT / "dev" / "tools"
DISEASE_DIR_ALIASES = {
    "covid19": "covid19",
    "covid-19": "covid19",
    "COVID-19": "covid19",
    "mpox": "mpox",
    "avian_influenza": "avian_influenza",
    "avian-influenza": "avian_influenza",
}

for p in (TOOLS_SRC,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools.analysis.pooling import enrich_ci, summarize  # type: ignore

# Topic → default parameter_type filter for pooling
TOPIC_PARAM = {
    "serial_interval":     "serial_interval",
    "reproduction_number": "R0",
    "fatality":            "CFR",
    "positivity_rate":     "positivity_rate",
}


def _coding_xlsx(run_dir: Path) -> Path | None:
    """Return the newest coding sheet inside one run directory."""
    candidates = list(run_dir.glob("coding_sheet*.xlsx"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _latest_xlsx(project_dir: Path, run_name: str | None = None) -> Path | None:
    """Return a coding sheet from an explicit run or the latest completed run."""
    runs_dir = project_dir / "coding_runs"
    if not runs_dir.exists():
        return None

    if run_name:
        if Path(run_name).name != run_name:
            raise ValueError("--run must be a directory name, not a path")
        run_dir = runs_dir / run_name
        if not run_dir.is_dir():
            raise FileNotFoundError(f"Coding run not found: {run_dir}")
        xlsx = _coding_xlsx(run_dir)
        if xlsx is None:
            raise FileNotFoundError(f"No coding_sheet*.xlsx found in run: {run_dir}")
        return xlsx

    candidates = [
        xlsx
        for run_dir in runs_dir.iterdir()
        if run_dir.is_dir()
        if (xlsx := _coding_xlsx(run_dir)) is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.parent.name))


def evaluate_project(
    topic: str,
    project: str,
    project_dir: Path,
    parameter_type: str | None,
    estimate_measure: str,
    include_median: bool,
    impute_se: bool,
    method: str,
    run_name: str | None = None,
) -> dict:
    xlsx = _latest_xlsx(project_dir, run_name=run_name)
    if xlsx is None:
        raise FileNotFoundError(f"No completed coding run found under {project_dir}")

    print(f"  [{topic}/{project}] Using {xlsx.parent.name}/{xlsx.name}")

    try:
        df = pd.read_excel(xlsx)
    except Exception as exc:
        raise RuntimeError(f"Failed to read {xlsx}: {exc}") from exc

    if parameter_type is not None:
        if "parameter_type" not in df.columns:
            raise ValueError(
                f"parameter_type '{parameter_type}' was requested, but {xlsx.name} "
                "has no parameter_type column. Use --all-parameter-types only after "
                "confirming that all rows represent a commensurate estimand."
            )
        available = [str(value).strip() for value in df["parameter_type"].dropna().unique()]
        if parameter_type not in available:
            match = next(
                (value for value in available if value.casefold() == parameter_type.casefold()),
                None,
            )
            if match:
                parameter_type = match
            else:
                raise ValueError(
                    f"parameter_type '{parameter_type}' not found in {xlsx.name}. "
                    f"Available: {available}. Pass the intended --parameter-type, "
                    "or use --all-parameter-types explicitly."
                )

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
        raise ValueError(
            f"Pooling returned no rows for {topic}/{project} from run {xlsx.parent.name}"
        )

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
    parser.add_argument(
        "--all-parameter-types",
        action="store_true",
        help="Intentionally pool all parameter types without a parameter_type filter.",
    )
    parser.add_argument("--estimate-measure", default="mean",
                        help="Estimate measure to pool (default: mean).")
    parser.add_argument("--include-median", action="store_true",
                        help="Include medians as mean approximations (per Ali 2021 Rule i).")
    parser.add_argument("--impute-se", action="store_true", default=True,
                        help="Impute missing SE from pooled within-study SD (default: True).")
    parser.add_argument("--no-impute-se", dest="impute_se", action="store_false")
    parser.add_argument("--method", default="random", choices=["random", "fixed"])
    parser.add_argument(
        "--run",
        default=None,
        help="Exact coding_runs directory name. Default: latest run containing a coding sheet.",
    )
    parser.add_argument("--output", default=None,
                        help="Output CSV path. Default: evaluation/coding/pooled_summary_YYYYMMDD.csv")
    args = parser.parse_args()
    if args.parameter_type and args.all_parameter_types:
        parser.error("Use only one of --parameter-type and --all-parameter-types")

    if not CODING_ROOT.exists():
        print(f"ERROR: {CODING_ROOT} not found.")
        sys.exit(1)

    # Discover projects — two-level iteration: disease → topic → project
    _SKIP_DIRS = {"GT_papers", "figures", "_summary"}
    projects_to_run: list[tuple[str, str, str, Path]] = []
    disease_filter = DISEASE_DIR_ALIASES.get(args.disease, args.disease) if args.disease else None
    for disease_dir in sorted(CODING_ROOT.iterdir()):
        if not disease_dir.is_dir() or disease_dir.name.startswith("_"):
            continue
        if disease_filter and disease_dir.name != disease_filter:
            continue
        for topic_dir in sorted(disease_dir.iterdir()):
            if not topic_dir.is_dir() or topic_dir.name in _SKIP_DIRS:
                continue
            if args.topic and topic_dir.name != args.topic:
                continue
            for project_dir in sorted(topic_dir.iterdir()):
                if not project_dir.is_dir() or project_dir.name.startswith("_"):
                    continue
                if args.project and project_dir.name != args.project:
                    continue
                projects_to_run.append((disease_dir.name, topic_dir.name, project_dir.name, project_dir))

    if not projects_to_run:
        print("ERROR: No projects found matching filters.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(projects_to_run)} project(s) to evaluate.\n")

    rows = []
    errors = []
    for disease, topic, project, project_dir in projects_to_run:
        param_type = (
            None
            if args.all_parameter_types
            else args.parameter_type or TOPIC_PARAM.get(topic, topic)
        )
        if topic == "fatality":
            print(f"  [{disease}/{topic}/{project}] NOTE: CFR/IFR is a proportion — "
                  "pooled_mean here is arithmetic average (may be biased). "
                  "For publication-quality meta-analysis use logit transform.")
        try:
            result = evaluate_project(
                topic=topic,
                project=project,
                project_dir=project_dir,
                parameter_type=param_type,
                estimate_measure=args.estimate_measure,
                include_median=args.include_median,
                impute_se=args.impute_se,
                method=args.method,
                run_name=args.run,
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            errors.append(f"{disease}/{topic}/{project}: {exc}")
            continue
        result["disease"] = disease
        rows.append(result)

    if errors:
        print("\nERROR: Coding evaluation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("ERROR: No pooling results were produced.", file=sys.stderr)
        sys.exit(1)

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

    print("\n=== Summary ===")
    df_out = pd.DataFrame(rows)
    print(df_out[["disease","topic","project","n_studies","n_excluded","n_imputed",
                   "pooled_mean","ci_lower","ci_upper","i2"]].to_string(index=False))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
