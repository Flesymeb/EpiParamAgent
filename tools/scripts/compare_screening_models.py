#!/usr/bin/env python3
"""Run and evaluate screening model comparisons.

Default scope is the 13 COVID-19 evaluation profiles that have registry entries:
P4-P8 and P10-P17.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
COVID13_PROFILES = [
    "P4",
    "P5",
    "P6",
    "P7",
    "P8",
    "P10",
    "P11",
    "P12",
    "P13",
    "P14",
    "P15",
    "P16",
    "P17",
]


def _slugify_model(model: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", model.strip())
    slug = slug.replace("/", "_").replace(":", "_").strip("._-")
    return slug.lower() or "model"


def _build_experiment_name(
    *,
    prefix: str,
    model: str,
    model_slug: str,
    strategy: str,
    template: str,
) -> str:
    if template:
        return template.format(
            prefix=prefix,
            model=model,
            model_slug=model_slug,
            strategy=strategy,
        )
    return f"{prefix}_{model_slug}_{strategy}"


def _run_command(cmd: list[str], *, cwd: Path, dry_run: bool) -> int:
    print("$ " + " ".join(cmd))
    if dry_run:
        return 0
    return subprocess.run(cmd, cwd=str(cwd)).returncode


def _evaluate_screening(
    *,
    profile_name: str,
    gt_file: Path,
    screened_file: Path,
    output_dir: Path,
) -> dict[str, Any]:
    from metaagent.screening.profile_registry import get_profile
    from tools.scripts.screening_evaluation import (
        evaluate_screening_performance,
        load_ground_truth_pmids,
        load_screened_results,
        write_paper_summary_tsv,
    )

    profile = get_profile(profile_name)
    ground_truth = load_ground_truth_pmids(gt_file)
    screened = load_screened_results(screened_file)
    summary = evaluate_screening_performance(
        ground_truth,
        screened,
        topic=profile.topic_key if profile else "unknown",
        project_label=profile.profile_key if profile else profile_name,
    )
    paper_summary_path = write_paper_summary_tsv(output_dir, summary)
    summary["paper_summary_tsv"] = str(paper_summary_path)
    return summary


def _evaluate_screening_maybe_quiet(
    *,
    profile_name: str,
    gt_file: Path,
    screened_file: Path,
    output_dir: Path,
    verbose: bool,
) -> dict[str, Any]:
    if verbose:
        return _evaluate_screening(
            profile_name=profile_name,
            gt_file=gt_file,
            screened_file=screened_file,
            output_dir=output_dir,
        )

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return _evaluate_screening(
            profile_name=profile_name,
            gt_file=gt_file,
            screened_file=screened_file,
            output_dir=output_dir,
        )


def _result_row(
    *,
    model: str,
    model_slug: str,
    experiment: str,
    profile: str,
    gt_file: Path,
    screened_file: Path,
    summary: dict[str, Any] | None,
    status: str,
    note: str = "",
) -> dict[str, str]:
    row = {
        "model": model,
        "model_slug": model_slug,
        "experiment": experiment,
        "profile": profile,
        "topic": str(summary.get("topic", "")) if summary else "",
        "gt": str(summary.get("ground_truth_count", "")) if summary else "",
        "pool": str(summary.get("screened_count", "")) if summary else "",
        "tp": str(summary.get("tp", "")) if summary else "",
        "fp": str(summary.get("fp", "")) if summary else "",
        "fn": str(summary.get("fn", "")) if summary else "",
        "tn": str(summary.get("tn", "")) if summary else "",
        "recall": str(summary.get("recall_ci_display", "")) if summary else "",
        "precision": str(summary.get("precision_ci_display", "")) if summary else "",
        "workload_reduction": str(summary.get("workload_reduction_ci_display", "")) if summary else "",
        "nns": str(summary.get("nns_ci_display", "")) if summary else "",
        "f1": str(summary.get("f1_display", "")) if summary else "",
        "mcc": str(summary.get("mcc_display", "")) if summary else "",
        "wss95": str(summary.get("wss95_display", "")) if summary else "",
        "recall_value": str(summary.get("sensitivity", "")) if summary else "",
        "precision_value": str(summary.get("precision", "")) if summary else "",
        "workload_reduction_value": str(summary.get("workload_reduction", "")) if summary else "",
        "nns_value": str(summary.get("nns", "")) if summary else "",
        "f1_value": str(summary.get("f1", "")) if summary else "",
        "mcc_value": str(summary.get("mcc", "")) if summary else "",
        "wss95_value": str(summary.get("wss95", "")) if summary else "",
        "status": status,
        "note": note,
        "gt_file": str(gt_file),
        "screened_file": str(screened_file),
    }
    return row


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare screening models on evaluation profiles."
    )
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=COVID13_PROFILES,
        help="Profiles to run/evaluate. Default: COVID-19 13 profiles P4-P8 P10-P17.",
    )
    parser.add_argument("--models", nargs="+", required=True, help="Model IDs to compare.")
    parser.add_argument(
        "--include-root-baseline",
        default="",
        help=(
            "Also evaluate project_*_screened.csv files directly under each project "
            "directory, using this value as the model label (e.g. gpt-5.4_current)."
        ),
    )
    parser.add_argument(
        "--experiment-prefix",
        default="cmp_covid13",
        help="Experiment folder prefix. Model slug and strategy are appended.",
    )
    parser.add_argument(
        "--experiment-template",
        default="",
        help=(
            "Optional experiment folder template with placeholders: "
            "{prefix}, {model}, {model_slug}, {strategy}. "
            "Useful for only-eval on existing folders, e.g. '{strategy}_{model_slug}'."
        ),
    )
    parser.add_argument(
        "--strategy",
        default="5d",
        choices=["5d", "binary", "binary_noguidance", "binary_baseline", "peco"],
    )
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--batch-concurrency", type=int, default=2)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--out", default="", help="Output TSV path for combined metrics.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands only.")
    parser.add_argument("--only-eval", action="store_true", help="Skip screening runs; evaluate existing outputs.")
    parser.add_argument("--rerun", action="store_true", help="Run screening even if project_*.csv exists.")
    parser.add_argument(
        "--verbose-eval",
        action="store_true",
        help="Print per-profile evaluation tables instead of only the combined TSV path.",
    )
    parser.add_argument(
        "--no-skip-no-abstract",
        action="store_true",
        help="Do not pass --skip-no-abstract to screening.",
    )
    parser.add_argument(
        "--no-fulltext-rescue",
        action="store_true",
        help="Disable profile full-text rescue policy during screening runs.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(REPO_ROOT))

    from metaagent.screening.profile_registry import get_profile, resolve_profile_paths

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = (
        Path(args.out).resolve()
        if args.out
        else project_root
        / "evaluation"
        / "covid19"
        / "results"
        / f"model_comparison_{timestamp}.tsv"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []

    if args.include_root_baseline:
        baseline_model = args.include_root_baseline
        baseline_slug = _slugify_model(baseline_model)
        for profile_name in args.profiles:
            profile = get_profile(profile_name)
            if profile is None:
                rows.append(
                    _result_row(
                        model=baseline_model,
                        model_slug=baseline_slug,
                        experiment="root",
                        profile=profile_name,
                        gt_file=Path(""),
                        screened_file=Path(""),
                        summary=None,
                        status="error",
                        note="unknown profile",
                    )
                )
                continue
            if profile.disease_key != "covid19":
                rows.append(
                    _result_row(
                        model=baseline_model,
                        model_slug=baseline_slug,
                        experiment="root",
                        profile=profile.profile_key,
                        gt_file=Path(""),
                        screened_file=Path(""),
                        summary=None,
                        status="skipped",
                        note=f"non-COVID profile ({profile.disease_key})",
                    )
                )
                continue

            _, paths = resolve_profile_paths(
                project_root=project_root,
                profile_name=profile_name,
                experiment=None,
            )
            if not paths.screened_file.exists():
                rows.append(
                    _result_row(
                        model=baseline_model,
                        model_slug=baseline_slug,
                        experiment="root",
                        profile=profile.profile_key,
                        gt_file=paths.ground_truth_file,
                        screened_file=paths.screened_file,
                        summary=None,
                        status="missing_output",
                    )
                )
                continue

            try:
                summary = _evaluate_screening_maybe_quiet(
                    profile_name=profile.profile_key,
                    gt_file=paths.ground_truth_file,
                    screened_file=paths.screened_file,
                    output_dir=paths.screened_file.parent,
                    verbose=args.verbose_eval,
                )
            except Exception as exc:
                rows.append(
                    _result_row(
                        model=baseline_model,
                        model_slug=baseline_slug,
                        experiment="root",
                        profile=profile.profile_key,
                        gt_file=paths.ground_truth_file,
                        screened_file=paths.screened_file,
                        summary=None,
                        status="eval_failed",
                        note=str(exc),
                    )
                )
                continue
            rows.append(
                _result_row(
                    model=baseline_model,
                    model_slug=baseline_slug,
                    experiment="root",
                    profile=profile.profile_key,
                    gt_file=paths.ground_truth_file,
                    screened_file=paths.screened_file,
                    summary=summary,
                    status="ok",
                )
            )

    for model in args.models:
        model_slug = _slugify_model(model)
        experiment = _build_experiment_name(
            prefix=args.experiment_prefix,
            model=model,
            model_slug=model_slug,
            strategy=args.strategy,
            template=args.experiment_template,
        )
        for profile_name in args.profiles:
            profile = get_profile(profile_name)
            if profile is None:
                rows.append(
                    _result_row(
                        model=model,
                        model_slug=model_slug,
                        experiment=experiment,
                        profile=profile_name,
                        gt_file=Path(""),
                        screened_file=Path(""),
                        summary=None,
                        status="error",
                        note="unknown profile",
                    )
                )
                continue
            if profile.disease_key != "covid19":
                rows.append(
                    _result_row(
                        model=model,
                        model_slug=model_slug,
                        experiment=experiment,
                        profile=profile.profile_key,
                        gt_file=Path(""),
                        screened_file=Path(""),
                        summary=None,
                        status="skipped",
                        note=f"non-COVID profile ({profile.disease_key})",
                    )
                )
                continue

            _, paths = resolve_profile_paths(
                project_root=project_root,
                profile_name=profile_name,
                experiment=experiment,
            )
            run_needed = args.rerun or not paths.screened_file.exists()
            if not args.only_eval and run_needed:
                cmd = [
                    sys.executable,
                    "-m",
                    "metaagent.cli",
                    "screening",
                    "run",
                    "--project-root",
                    str(project_root),
                    "--profile",
                    profile.profile_key,
                    "--model",
                    model,
                    "--strategy",
                    args.strategy,
                    "--experiment",
                    experiment,
                    "--batch-size",
                    str(args.batch_size),
                    "--batch-concurrency",
                    str(args.batch_concurrency),
                ]
                if not args.no_skip_no_abstract:
                    cmd.append("--skip-no-abstract")
                if args.no_fulltext_rescue:
                    cmd.append("--no-fulltext-rescue")
                code = _run_command(cmd, cwd=REPO_ROOT, dry_run=args.dry_run)
                if code != 0:
                    rows.append(
                        _result_row(
                            model=model,
                            model_slug=model_slug,
                            experiment=experiment,
                            profile=profile.profile_key,
                            gt_file=paths.ground_truth_file,
                            screened_file=paths.screened_file,
                            summary=None,
                            status="run_failed",
                            note=f"exit={code}",
                        )
                    )
                    continue
            elif not args.only_eval:
                print(f"[SKIP] existing screened output: {paths.screened_file}")

            if args.dry_run:
                rows.append(
                    _result_row(
                        model=model,
                        model_slug=model_slug,
                        experiment=experiment,
                        profile=profile.profile_key,
                        gt_file=paths.ground_truth_file,
                        screened_file=paths.screened_file,
                        summary=None,
                        status="dry_run",
                    )
                )
                continue

            if not paths.screened_file.exists():
                rows.append(
                    _result_row(
                        model=model,
                        model_slug=model_slug,
                        experiment=experiment,
                        profile=profile.profile_key,
                        gt_file=paths.ground_truth_file,
                        screened_file=paths.screened_file,
                        summary=None,
                        status="missing_output",
                    )
                )
                continue

            try:
                summary = _evaluate_screening_maybe_quiet(
                    profile_name=profile.profile_key,
                    gt_file=paths.ground_truth_file,
                    screened_file=paths.screened_file,
                    output_dir=paths.screened_file.parent,
                    verbose=args.verbose_eval,
                )
            except Exception as exc:
                rows.append(
                    _result_row(
                        model=model,
                        model_slug=model_slug,
                        experiment=experiment,
                        profile=profile.profile_key,
                        gt_file=paths.ground_truth_file,
                        screened_file=paths.screened_file,
                        summary=None,
                        status="eval_failed",
                        note=str(exc),
                    )
                )
                continue
            rows.append(
                _result_row(
                    model=model,
                    model_slug=model_slug,
                    experiment=experiment,
                    profile=profile.profile_key,
                    gt_file=paths.ground_truth_file,
                    screened_file=paths.screened_file,
                    summary=summary,
                    status="ok",
                )
            )

    fieldnames = [
        "model",
        "model_slug",
        "experiment",
        "profile",
        "topic",
        "gt",
        "pool",
        "tp",
        "fp",
        "fn",
        "tn",
        "recall",
        "precision",
        "workload_reduction",
        "nns",
        "f1",
        "mcc",
        "wss95",
        "recall_value",
        "precision_value",
        "workload_reduction_value",
        "nns_value",
        "f1_value",
        "mcc_value",
        "wss95_value",
        "status",
        "note",
        "gt_file",
        "screened_file",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nComparison summary: {out_path}")


if __name__ == "__main__":
    main()
