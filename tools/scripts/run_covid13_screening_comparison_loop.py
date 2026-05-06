#!/usr/bin/env python3
"""Overnight supervisor for COVID-19 screening model comparison.

The loop is intentionally conservative: it runs one profile at a time, validates
that the output exists and has the same row count as the raw pool, retries failed
profiles with lower concurrency, and writes a combined TSV/Markdown summary.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ModelSpec:
    label: str
    model_id: str
    experiment: str
    batch_size: int
    batch_concurrency: int
    timeout_s: int = 14400
    max_retries: int = 2


MODEL_SPECS: list[ModelSpec] = [
    ModelSpec(
        label="openai/gpt-4.1",
        model_id="openai/gpt-4.1",
        experiment="cmp_covid13_openai_gpt-4.1_5d_nofulltext",
        batch_size=500,
        batch_concurrency=64,
        timeout_s=7200,
    ),
    ModelSpec(
        label="openai/gpt-4.1-mini",
        model_id="openai/gpt-4.1-mini",
        experiment="cmp_covid13_openai_gpt-4.1-mini_5d_nofulltext",
        batch_size=20,
        batch_concurrency=8,
        timeout_s=7200,
    ),
    ModelSpec(
        label="qwen/qwen-turbo",
        model_id="qwen/qwen-turbo",
        experiment="cmp_covid13_qwen_qwen-turbo_5d_nofulltext_c16",
        batch_size=20,
        batch_concurrency=4,
        timeout_s=10800,
    ),
    ModelSpec(
        label="mistralai/mistral-small-3.2-24b-instruct",
        model_id="mistralai/mistral-small-3.2-24b-instruct",
        experiment="cmp_covid13_mistral_small_3.2_24b_5d_nofulltext_c8",
        batch_size=20,
        batch_concurrency=8,
        timeout_s=18000,
    ),
    ModelSpec(
        label="minimax/minimax-m2.5",
        model_id="minimax/minimax-m2.5",
        experiment="cmp_covid13_minimax_minimax-m2.5_5d_nofulltext_c8",
        batch_size=20,
        batch_concurrency=8,
        timeout_s=18000,
    ),
    ModelSpec(
        label="deepseek/deepseek-v4-flash",
        model_id="deepseek/deepseek-v4-flash",
        experiment="cmp_covid13_deepseek_deepseek-v4-flash_5d_nofulltext_c8",
        batch_size=20,
        batch_concurrency=4,
        timeout_s=18000,
    ),
]


def _slugify_model(model: str) -> str:
    return (
        model.strip()
        .replace("/", "_")
        .replace(":", "_")
        .replace(" ", "_")
        .strip("._-")
        .lower()
        or "model"
    )


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _validate_output(raw_file: Path, screened_file: Path) -> tuple[bool, str]:
    if not screened_file.exists():
        return False, "missing_output"
    try:
        raw_count = len(_read_rows(raw_file))
        rows = _read_rows(screened_file)
    except Exception as exc:
        return False, f"read_failed: {exc}"
    if len(rows) != raw_count:
        return False, f"row_count_mismatch: raw={raw_count} screened={len(rows)}"
    error_count = sum(1 for row in rows if (row.get("llm_suggest") or "") == "error")
    max_errors = max(3, math.ceil(raw_count * 0.005))
    if error_count > max_errors:
        return False, f"too_many_errors: {error_count}>{max_errors}"
    return True, f"ok rows={len(rows)} errors={error_count}"


def _run_profile(
    *,
    spec: ModelSpec,
    profile_name: str,
    paths: Any,
    project_root: Path,
    log_dir: Path,
    attempt: int,
) -> int:
    concurrency = max(1, spec.batch_concurrency // (2**attempt))
    cmd = [
        sys.executable,
        "-m",
        "metaagent.cli",
        "screening",
        "run",
        "--project-root",
        str(project_root),
        "--profile",
        profile_name,
        "--model",
        spec.model_id,
        "--strategy",
        "5d",
        "--experiment",
        spec.experiment,
        "--batch-size",
        str(spec.batch_size),
        "--batch-concurrency",
        str(concurrency),
        "--skip-no-abstract",
        "--no-fulltext-rescue",
    ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = (
        str(project_root)
        if not env.get("PYTHONPATH")
        else f"{project_root}{os.pathsep}{env['PYTHONPATH']}"
    )
    log_file = (
        log_dir
        / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify_model(spec.label)}_{profile_name}_attempt{attempt + 1}.log"
    )
    print(
        f"[LOG] {spec.label} {profile_name} attempt={attempt + 1} "
        f"concurrency={concurrency} log={log_file}",
        flush=True,
    )
    with log_file.open("w", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n")
        f.flush()
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                env=env,
                stdout=f,
                stderr=subprocess.STDOUT,
                timeout=spec.timeout_s,
            )
            return result.returncode
        except subprocess.TimeoutExpired:
            f.write(f"\nTIMEOUT after {spec.timeout_s}s\n")
            return 124


def _write_combined_outputs(
    *,
    project_root: Path,
    specs: list[ModelSpec],
    profiles: list[str],
    output_dir: Path,
) -> tuple[Path, Path]:
    sys.path.insert(0, str(project_root))
    from metaagent.screening.profile_registry import resolve_profile_paths
    from tools.scripts.compare_screening_models import (
        _evaluate_screening_maybe_quiet,
        _result_row,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tsv_path = output_dir / f"model_comparison_overnight_covid13_{timestamp}.tsv"
    md_path = output_dir / f"model_comparison_overnight_covid13_{timestamp}.md"
    rows: list[dict[str, str]] = []

    def add_row(model: str, experiment: str, profile_name: str, experiment_arg: str | None) -> None:
        _, paths = resolve_profile_paths(
            project_root=project_root,
            profile_name=profile_name,
            experiment=experiment_arg,
        )
        if not paths.screened_file.exists():
            rows.append(
                _result_row(
                    model=model,
                    model_slug=_slugify_model(model),
                    experiment=experiment,
                    profile=profile_name,
                    gt_file=paths.ground_truth_file,
                    screened_file=paths.screened_file,
                    summary=None,
                    status="missing_output",
                )
            )
            return
        try:
            summary = _evaluate_screening_maybe_quiet(
                profile_name=profile_name,
                gt_file=paths.ground_truth_file,
                screened_file=paths.screened_file,
                output_dir=paths.screened_file.parent,
                verbose=False,
            )
            rows.append(
                _result_row(
                    model=model,
                    model_slug=_slugify_model(model),
                    experiment=experiment,
                    profile=profile_name,
                    gt_file=paths.ground_truth_file,
                    screened_file=paths.screened_file,
                    summary=summary,
                    status="ok",
                )
            )
        except Exception as exc:
            rows.append(
                _result_row(
                    model=model,
                    model_slug=_slugify_model(model),
                    experiment=experiment,
                    profile=profile_name,
                    gt_file=paths.ground_truth_file,
                    screened_file=paths.screened_file,
                    summary=None,
                    status="eval_failed",
                    note=str(exc),
                )
            )

    for profile in profiles:
        add_row("gpt-5.4_current", "root", profile, None)
    for spec in specs:
        for profile in profiles:
            add_row(spec.label, spec.experiment, profile, spec.experiment)

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
    with tsv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    ok_rows = [r for r in rows if r["status"] == "ok"]
    by_model: dict[str, list[dict[str, str]]] = {}
    for row in ok_rows:
        by_model.setdefault(row["model"], []).append(row)

    lines = [
        "# COVID13 Overnight Screening Model Comparison",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- TSV: `{tsv_path.name}`",
        "- Scope: COVID19 P4-P8 and P10-P17.",
        "- Run mode: strategy `5d`, `--skip-no-abstract`, `--no-fulltext-rescue`.",
        "",
        "| model | projects | TP | FP | FN | TN | micro recall | micro precision | workload reduction | micro F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, model_rows in sorted(by_model.items()):
        tp = sum(int(r["tp"]) for r in model_rows)
        fp = sum(int(r["fp"]) for r in model_rows)
        fn = sum(int(r["fn"]) for r in model_rows)
        tn = sum(int(r["tn"]) for r in model_rows)
        recall = tp / (tp + fn) if tp + fn else 0.0
        precision = tp / (tp + fp) if tp + fp else 0.0
        wr = (tn + fn) / (tp + fp + fn + tn) if tp + fp + fn + tn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        lines.append(
            f"| {model} | {len(model_rows)} | {tp} | {fp} | {fn} | {tn} | "
            f"{recall:.3f} | {precision:.3f} | {wr:.3f} | {f1:.3f} |"
        )
    lines.append("")
    missing = [r for r in rows if r["status"] != "ok"]
    if missing:
        lines.extend(["## Non-ok Rows", ""])
        for row in missing:
            lines.append(
                f"- {row['model']} {row['profile']}: {row['status']} {row.get('note', '')}".rstrip()
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tsv_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run overnight COVID13 model comparison loop.")
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--sleep-between-rounds", type=int, default=300)
    parser.add_argument("--profiles", nargs="+", default=COVID13_PROFILES)
    parser.add_argument(
        "--models",
        nargs="+",
        default=[spec.label for spec in MODEL_SPECS],
        help="Subset of default model labels to run.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    sys.path.insert(0, str(project_root))
    from metaagent.screening.profile_registry import resolve_profile_paths

    selected = [spec for spec in MODEL_SPECS if spec.label in set(args.models)]
    log_dir = project_root / "tmp" / "logs" / "overnight_covid13"
    output_dir = project_root / "evaluation" / "covid19" / "results"
    log_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    for round_idx in range(args.max_rounds):
        print(f"\n=== Overnight COVID13 loop round {round_idx + 1}/{args.max_rounds} ===", flush=True)
        all_valid = True
        for spec in selected:
            print(f"\n--- Model: {spec.label} ({spec.experiment}) ---", flush=True)
            for profile in args.profiles:
                _, paths = resolve_profile_paths(
                    project_root=project_root,
                    profile_name=profile,
                    experiment=spec.experiment,
                )
                valid, note = _validate_output(paths.raw_file, paths.screened_file)
                if valid:
                    print(f"[SKIP] {spec.label} {profile}: {note}", flush=True)
                    continue

                all_valid = False
                print(f"[RUN] {spec.label} {profile}: {note}", flush=True)
                for attempt in range(spec.max_retries + 1):
                    code = _run_profile(
                        spec=spec,
                        profile_name=profile,
                        paths=paths,
                        project_root=project_root,
                        log_dir=log_dir,
                        attempt=attempt,
                    )
                    valid, note = _validate_output(paths.raw_file, paths.screened_file)
                    print(
                        f"[CHECK] {spec.label} {profile} attempt={attempt + 1} code={code}: {note}",
                        flush=True,
                    )
                    if valid:
                        break
                    time.sleep(30)

        tsv_path, md_path = _write_combined_outputs(
            project_root=project_root,
            specs=selected,
            profiles=args.profiles,
            output_dir=output_dir,
        )
        print(f"\n[SUMMARY] {tsv_path}", flush=True)
        print(f"[SUMMARY] {md_path}", flush=True)
        if all_valid:
            print("[DONE] All selected model/profile outputs are valid.", flush=True)
            return
        if round_idx + 1 < args.max_rounds:
            print(f"[SLEEP] {args.sleep_between_rounds}s before next round.", flush=True)
            time.sleep(args.sleep_between_rounds)

    print("[DONE] Max rounds reached. Check summary for remaining non-ok rows.", flush=True)


if __name__ == "__main__":
    main()
