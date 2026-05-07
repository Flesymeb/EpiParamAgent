#!/usr/bin/env python3
"""Run matched 5D screening comparisons across provider/model pairs."""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

COVID13_PROFILES = ["P4", "P5", "P6", "P7", "P8", "P10", "P11", "P12", "P13", "P14", "P15", "P16", "P17"]
MPOX_PROFILES = ["MP4", "MP5", "MP6", "MP7", "MP8", "MP9", "MP10", "MP11", "MP12"]

MODEL_PRESETS = {
    "priority": [
        ("lab", "deepseek-3.2"),
        ("lab", "minimax2.5"),
        ("lab2", "deepseek-v3-huawei-910b"),
        ("boyue", "deepseek-v4-pro"),
        ("boyue", "kimi-k2.6"),
        ("boyue", "qwen3.6-plus"),
    ],
    "lab-all": [
        ("lab", "qwen3.5-397b"),
        ("lab", "kimi-k2.5"),
        ("lab", "minimax2.5"),
        ("lab", "glm-5"),
        ("lab", "intern-s1"),
        ("lab", "intern-s1-pro"),
        ("lab", "deepseek-3.2"),
        ("lab2", "deepseek-v3-huawei-910b"),
        ("boyue", "deepseek-v4-pro"),
        ("boyue", "kimi-k2.6"),
        ("boyue", "qwen3.6-plus"),
    ],
}
MODEL_TEMPERATURE_OVERRIDES = {
    ("lab", "kimi-k2.5"): 1.0,
    ("boyue", "kimi-k2.5"): 1.0,
    ("boyue", "kimi-k2.6"): 1.0,
}
MODEL_DISPLAY_NAMES = {
    ("lab", "minimax2.5"): "MiniMax 2.7",
}


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    temperature: float | None = None
    batch_size: int | None = None
    batch_concurrency: int | None = None
    batch_mode: str | None = None

    @property
    def slug(self) -> str:
        return f"{_slug(self.provider)}_{_slug(self.model)}"

    @property
    def display_name(self) -> str:
        return MODEL_DISPLAY_NAMES.get((self.provider, self.model), self.model)


@dataclass(frozen=True)
class ProfileJob:
    disease: str
    profile: str
    provider: str
    model: str
    temperature: float | None
    batch_size: int
    batch_concurrency: int
    batch_mode: str
    experiment: str


def main() -> None:
    args = build_parser().parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    run_id = args.run_id or f"model_5d_screening_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    models = resolve_models(args)
    profiles = resolve_profiles(args)

    summary_root = project_root / "evaluation" / "experiments" / run_id
    summary_root.mkdir(parents=True, exist_ok=True)
    write_run_config(summary_root, args, run_id, models, profiles)

    jobs = build_jobs(models, profiles, run_id, args)

    if args.dry_run:
        for job in jobs:
            print(" ".join(build_run_command(project_root, job, args)))
            print(" ".join(build_eval_command(project_root, job)))
        print(f"Dry run: {len(jobs)} profile jobs across {len(models)} models")
        return

    failures = run_jobs(project_root, jobs, args, summary_root)
    summary_path = collect_summaries(project_root, summary_root, run_id, models, profiles)
    print(f"Summary written: {summary_path}")

    if failures:
        failed_path = summary_root / "failures.json"
        failed_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Failures written: {failed_path}")
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--preset", choices=sorted(MODEL_PRESETS), default="priority")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Provider/model pair, e.g. lab:deepseek-3.2. Can be repeated.",
    )
    parser.add_argument("--diseases", default="covid19,mpox")
    parser.add_argument("--covid-profiles", default=",".join(COVID13_PROFILES))
    parser.add_argument("--mpox-profiles", default=",".join(MPOX_PROFILES))
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--batch-concurrency", type=int, default=1, help="Concurrent batch groups inside one profile run.")
    parser.add_argument("--batch-mode", choices=["single", "multi"], default="single", help="single=one API call per paper; multi=one API call per batch")
    parser.add_argument(
        "--model-runtime",
        action="append",
        default=[],
        metavar="PROVIDER:MODEL:MODE:BATCH_SIZE:BATCH_CONCURRENCY",
        help=(
            "Per-model runtime override, e.g. lab:minimax2.5:single:20:3. "
            "Unspecified models use --batch-mode/--batch-size/--batch-concurrency."
        ),
    )
    parser.add_argument("--jobs", type=int, default=2, help="Concurrent profile processes.")
    parser.add_argument("--job-timeout-s", type=int, default=7200, help="Timeout per profile run/eval command.")
    parser.add_argument("--strategy", default="5d", choices=["5d", "binary", "binary_noguidance", "binary_baseline", "peco"])
    parser.add_argument("--skip-existing", dest="skip_existing", action="store_true", help="Skip screening when the screened CSV already exists; still rerun evaluation.")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false", help="Always rerun screening even if prior outputs exist.")
    parser.add_argument("--force", action="store_true", help="Rerun existing screened CSVs.")
    parser.add_argument("--auto-fulltext", action="store_true", help="Enable automatic full-text routing during the primary run.")
    parser.add_argument("--fulltext-only", action="store_true", help="Run only the full-text stage.")
    parser.add_argument("--resume-fulltext", action="store_true", help="Resume legacy full-text eligible rows.")
    parser.add_argument("--resume-possible-fulltext", action="store_true", help="Run stage-2 full-text only for possible candidates.")
    parser.add_argument("--resume-sp-fulltext", action="store_true", help="Run stage-2 full-text for strong and possible candidates.")
    parser.add_argument("--fulltext-cache-only", action="store_true", help="Use cached PDFs/markdown only during second-stage full-text runs.")
    parser.add_argument(
        "--prefer-llm-tier",
        dest="prefer_llm_tier",
        action="store_true",
        default=True,
        help="Use the model's own S/P/U tier output instead of code-side thresholds (default).",
    )
    parser.add_argument(
        "--no-prefer-llm-tier",
        dest="prefer_llm_tier",
        action="store_false",
        help="Use code-side score thresholds instead of the model's S/P/U tier.",
    )
    parser.add_argument("--no-fulltext-rescue", action="store_true", help="Disable profile-level full-text rescue policy.")
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(skip_existing=True)
    return parser


def resolve_models(args: argparse.Namespace) -> list[ModelSpec]:
    runtime_overrides = parse_model_runtime_overrides(args.model_runtime)
    raw = []
    if args.model:
        for item in args.model:
            if ":" not in item:
                raise ValueError(f"--model must be provider:model, got {item!r}")
            provider, model = item.split(":", 1)
            raw.append((provider.strip(), model.strip()))
    else:
        raw = MODEL_PRESETS[args.preset]
    specs = []
    for provider, model in raw:
        runtime = runtime_overrides.pop((provider, model), {})
        specs.append(
            ModelSpec(
                provider=provider,
                model=model,
                temperature=MODEL_TEMPERATURE_OVERRIDES.get((provider, model)),
                batch_size=runtime.get("batch_size"),
                batch_concurrency=runtime.get("batch_concurrency"),
                batch_mode=runtime.get("batch_mode"),
            )
        )
    if runtime_overrides:
        unknown = ", ".join(f"{provider}:{model}" for provider, model in sorted(runtime_overrides))
        raise ValueError(f"--model-runtime specified for models not in this run: {unknown}")
    return specs


def parse_model_runtime_overrides(items: list[str]) -> dict[tuple[str, str], dict[str, int | str]]:
    overrides: dict[tuple[str, str], dict[str, int | str]] = {}
    for item in items:
        parts = item.split(":")
        if len(parts) != 5:
            raise ValueError(
                "--model-runtime must be PROVIDER:MODEL:MODE:BATCH_SIZE:BATCH_CONCURRENCY, "
                f"got {item!r}"
            )
        provider, model, mode, batch_size_raw, batch_concurrency_raw = [part.strip() for part in parts]
        if mode not in {"single", "multi"}:
            raise ValueError(f"--model-runtime mode must be single or multi, got {mode!r}")
        batch_size = int(batch_size_raw)
        batch_concurrency = int(batch_concurrency_raw)
        if batch_size < 1 or batch_concurrency < 1:
            raise ValueError("--model-runtime batch size and concurrency must be positive integers")
        overrides[(provider, model)] = {
            "batch_mode": mode,
            "batch_size": batch_size,
            "batch_concurrency": batch_concurrency,
        }
    return overrides


def resolve_profiles(args: argparse.Namespace) -> dict[str, list[str]]:
    diseases = {item.strip() for item in args.diseases.split(",") if item.strip()}
    profiles: dict[str, list[str]] = {}
    if "covid19" in diseases:
        profiles["covid19"] = _split_csv(args.covid_profiles)
    if "mpox" in diseases:
        profiles["mpox"] = _split_csv(args.mpox_profiles)
    return profiles


def build_jobs(
    models: list[ModelSpec],
    profiles: dict[str, list[str]],
    run_id: str,
    args: argparse.Namespace,
) -> list[ProfileJob]:
    """Round-robin jobs across models so different providers can run in parallel."""
    per_model_jobs: list[list[ProfileJob]] = []
    for spec in models:
        model_jobs = [
            ProfileJob(
                disease=disease,
                profile=profile,
                provider=spec.provider,
                model=spec.model,
                temperature=spec.temperature,
                batch_size=spec.batch_size or args.batch_size,
                batch_concurrency=spec.batch_concurrency or args.batch_concurrency,
                batch_mode=spec.batch_mode or args.batch_mode,
                experiment=f"{run_id}_{spec.slug}",
            )
            for disease, profile_list in profiles.items()
            for profile in profile_list
        ]
        per_model_jobs.append(model_jobs)

    jobs: list[ProfileJob] = []
    max_len = max((len(queue) for queue in per_model_jobs), default=0)
    for idx in range(max_len):
        for queue in per_model_jobs:
            if idx < len(queue):
                jobs.append(queue[idx])
    return jobs


def write_run_config(
    summary_root: Path,
    args: argparse.Namespace,
    run_id: str,
    models: list[ModelSpec],
    profiles: dict[str, list[str]],
) -> None:
    def effective_batch_size(spec: ModelSpec) -> int:
        return spec.batch_size or args.batch_size

    def effective_batch_concurrency(spec: ModelSpec) -> int:
        return spec.batch_concurrency or args.batch_concurrency

    def effective_batch_mode(spec: ModelSpec) -> str:
        return spec.batch_mode or args.batch_mode

    def request_concurrency(spec: ModelSpec) -> int:
        batch_size = effective_batch_size(spec)
        batch_concurrency = effective_batch_concurrency(spec)
        batch_mode = effective_batch_mode(spec)
        return batch_concurrency if batch_mode == "multi" else batch_size * batch_concurrency

    payload = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "strategy": args.strategy,
        "batch_defaults": {
            "batch_size": args.batch_size,
            "batch_concurrency": args.batch_concurrency,
            "batch_mode": args.batch_mode,
        },
        "jobs": args.jobs,
        "estimated_max_inflight_requests_upper_bound": max((request_concurrency(spec) for spec in models), default=1)
        * max(1, args.jobs),
        "estimated_max_papers_inflight_upper_bound": max(
            (effective_batch_size(spec) * effective_batch_concurrency(spec) for spec in models),
            default=1,
        )
        * max(1, args.jobs),
        "auto_fulltext": bool(args.auto_fulltext),
        "fulltext_only": bool(args.fulltext_only),
        "resume_fulltext": bool(args.resume_fulltext),
        "resume_possible_fulltext": bool(args.resume_possible_fulltext),
        "resume_sp_fulltext": bool(args.resume_sp_fulltext),
        "fulltext_cache_only": bool(args.fulltext_cache_only),
        "prefer_llm_tier": bool(args.prefer_llm_tier),
        "no_fulltext_rescue": bool(args.no_fulltext_rescue),
        "models": [
            {
                "provider": spec.provider,
                "model": spec.model,
                "display_name": spec.display_name,
                "temperature": spec.temperature,
                "slug": spec.slug,
                "batch_size": effective_batch_size(spec),
                "batch_concurrency": effective_batch_concurrency(spec),
                "batch_mode": effective_batch_mode(spec),
                "estimated_request_concurrency_per_profile": request_concurrency(spec),
            }
            for spec in models
        ],
        "profiles": profiles,
    }
    (summary_root / "run_config.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_jobs(
    project_root: Path,
    jobs: list[ProfileJob],
    args: argparse.Namespace,
    summary_root: Path,
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    pending: set[Future[tuple[ProfileJob, int, str]]] = set()
    max_workers = max(1, int(args.jobs))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        job_iter = iter(jobs)
        while True:
            while len(pending) < max_workers:
                try:
                    job = next(job_iter)
                except StopIteration:
                    break
                pending.add(executor.submit(run_one_job, project_root, job, args, summary_root))
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                job, code, log_path = future.result()
                if code != 0:
                    failures.append(
                        {
                            "disease": job.disease,
                            "profile": job.profile,
                            "provider": job.provider,
                            "model": job.model,
                            "experiment": job.experiment,
                            "log": log_path,
                            "returncode": str(code),
                        }
                    )
                    print(f"FAILED {job.experiment} {job.disease}/{job.profile} -> {log_path}")
                else:
                    print(f"OK {job.experiment} {job.disease}/{job.profile}")
    return failures


def run_one_job(
    project_root: Path,
    job: ProfileJob,
    args: argparse.Namespace,
    summary_root: Path,
) -> tuple[ProfileJob, int, str]:
    output_csv = expected_screened_csv(project_root, job)
    log_dir = summary_root / "logs" / job.experiment
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{job.disease}_{job.profile.lower()}.log"

    if output_csv.exists() and args.skip_existing and not args.force:
        eval_code = run_command(build_eval_command(project_root, job), log_path, timeout_s=args.job_timeout_s)
        return job, eval_code, str(log_path)

    code = run_command(build_run_command(project_root, job, args), log_path, timeout_s=args.job_timeout_s)
    if code != 0:
        return job, code, str(log_path)
    eval_code = run_command(build_eval_command(project_root, job), log_path, timeout_s=args.job_timeout_s)
    return job, eval_code, str(log_path)


def run_command(command: list[str], log_path: Path, *, timeout_s: int) -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) if not env.get("PYTHONPATH") else f"{REPO_ROOT}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONUNBUFFERED"] = "1"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n$ {' '.join(command)}\n")
        log.flush()
        proc: subprocess.Popen[bytes] | None = None
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(REPO_ROOT),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            proc.wait(timeout=timeout_s if timeout_s > 0 else None)
            return int(proc.returncode)
        except subprocess.TimeoutExpired:
            if proc is not None:
                _terminate_process_group(proc)
            log.write(f"\nTIMEOUT: command exceeded {timeout_s}s\n")
            return 124


def _terminate_process_group(proc: subprocess.Popen[bytes]) -> None:
    """Terminate a profile run and any child batch worker it spawned."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        proc.wait(timeout=10)


def build_run_command(project_root: Path, job: ProfileJob, args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "metaagent.cli",
        "screening",
        "run",
        "--project-root",
        str(project_root),
        "--profile",
        job.profile,
        "--disease",
        job.disease,
        "--batch-size",
        str(job.batch_size),
        "--batch-concurrency",
        str(job.batch_concurrency),
        "--batch-mode",
        job.batch_mode,
        "--strategy",
        args.strategy,
        "--provider",
        job.provider,
        "--model",
        job.model,
        "--experiment",
        job.experiment,
    ]
    if job.temperature is not None:
        command += ["--temperature", str(job.temperature)]
    if args.auto_fulltext:
        command += ["--auto-fulltext"]
    if args.fulltext_only:
        command += ["--fulltext-only"]
    if args.resume_fulltext:
        command += ["--resume-fulltext"]
    if args.resume_possible_fulltext:
        command += ["--resume-possible-fulltext"]
    if args.resume_sp_fulltext:
        command += ["--resume-sp-fulltext"]
    if args.fulltext_cache_only:
        command += ["--fulltext-cache-only"]
    if args.prefer_llm_tier:
        command += ["--prefer-llm-tier"]
    else:
        command += ["--no-prefer-llm-tier"]
    if args.no_fulltext_rescue:
        command += ["--no-fulltext-rescue"]
    return command


def build_eval_command(project_root: Path, job: ProfileJob) -> list[str]:
    return [
        sys.executable,
        "-m",
        "metaagent.cli",
        "screening",
        "evaluate",
        "performance",
        "--project-root",
        str(project_root),
        "--profile",
        job.profile,
        "--disease",
        job.disease,
        "--experiment",
        job.experiment,
    ]


def expected_screened_csv(project_root: Path, job: ProfileJob) -> Path:
    from metaagent.screening.profile_registry import resolve_profile_paths

    _, paths = resolve_profile_paths(
        project_root=project_root,
        profile_name=job.profile,
        disease=job.disease,
        experiment=job.experiment,
    )
    return paths.screened_file


def collect_summaries(
    project_root: Path,
    summary_root: Path,
    run_id: str,
    models: list[ModelSpec],
    profiles: dict[str, list[str]],
) -> Path:
    from metaagent.screening.profile_registry import get_profile, resolve_profile_paths

    rows: list[dict[str, str]] = []
    for spec in models:
        experiment = f"{run_id}_{spec.slug}"
        for disease, profile_list in profiles.items():
            for profile_name in profile_list:
                profile = get_profile(profile_name)
                if profile is None:
                    continue
                _, paths = resolve_profile_paths(
                    project_root=project_root,
                    profile_name=profile_name,
                    disease=disease,
                    experiment=experiment,
                )
                summary = paths.screened_file.parent / "paper_summary.tsv"
                if not summary.exists():
                    continue
                with summary.open(encoding="utf-8") as f:
                    reader = csv.DictReader(f, delimiter="\t")
                    for row in reader:
                        row.update(
                            {
                                "run_id": run_id,
                                "experiment": experiment,
                                "provider": spec.provider,
                                "model": spec.model,
                                "model_display": spec.display_name,
                                "disease": disease,
                                "profile": profile_name,
                                "topic": profile.topic_key,
                            }
                        )
                        rows.append(row)

    output = summary_root / "screening_model_comparison_summary.csv"
    if not rows:
        output.write_text("", encoding="utf-8")
        return output
    fieldnames = [
        "run_id",
        "experiment",
        "provider",
        "model",
        "model_display",
        "disease",
        "topic",
        "profile",
    ] + [key for key in rows[0].keys() if key not in {"run_id", "experiment", "provider", "model", "disease", "topic", "profile"}]
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output


def _split_csv(text: str) -> list[str]:
    return [item.strip().upper() for item in text.split(",") if item.strip()]


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")


if __name__ == "__main__":
    start = time.perf_counter()
    try:
        main()
    finally:
        elapsed = time.perf_counter() - start
        print(f"Elapsed: {elapsed / 60:.1f} min")
