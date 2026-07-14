#!/usr/bin/env python3
"""Run reproducible screening baselines and refresh the summary table."""

from __future__ import annotations

import argparse
import os
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = ROOT / "baselines" / "screening"
DEFAULT_DISEASES = ("covid19", "mpox")
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/v1"
ENDPOINT_ENV_VARS = ("LEADS_ENDPOINT", "LLM_API_BASE", "OPENAI_API_BASE")


def first_nonempty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def load_project_llm_config() -> Any | None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from metaagent.config import load_llm_config
    except Exception:
        return None
    try:
        return load_llm_config(module_hint="screening")
    except Exception as exc:
        print(f"Warning: could not load project LLM config: {exc}", file=sys.stderr)
        return None


def endpoint_settings() -> tuple[str, bool]:
    endpoint_env = first_env(ENDPOINT_ENV_VARS)
    cfg = load_project_llm_config()
    base_url = first_nonempty(endpoint_env, getattr(cfg, "api_base", None), DEFAULT_API_BASE_URL)
    verify_ssl = bool(getattr(cfg, "verify_ssl", True))
    return (base_url or DEFAULT_API_BASE_URL).rstrip("/"), verify_ssl


def endpoint_available(base_url: str, *, verify_ssl: bool, timeout_s: float = 3.0) -> bool:
    url = base_url.rstrip("/") + "/models"
    context = None if verify_ssl else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(url, timeout=timeout_s, context=context) as response:
            return 200 <= int(response.status) < 300
    except Exception:
        return False


def run(cmd: list[str], *, dry_print: bool = False) -> int:
    print("+ " + " ".join(cmd), flush=True)
    if dry_print:
        return 0
    return subprocess.call(cmd, cwd=str(ROOT))


def run_llm_baseline(
    script: Path,
    *,
    diseases: tuple[str, ...],
    dry_run: bool,
    skip_server_check: bool,
    experiment_prefix: str,
) -> int:
    for disease in diseases:
        cmd = [
            sys.executable,
            str(script),
            "--disease",
            disease,
            "--profiles",
            "all",
            "--experiment",
            f"{experiment_prefix}_{disease}",
        ]
        if dry_run:
            cmd.append("--dry-run")
        if skip_server_check:
            cmd.append("--no-check-server")
        code = run(cmd)
        if code:
            return code
    return 0


def validate_outputs() -> None:
    required = [
        BASELINE_DIR / "keyword_rules" / "results" / "rule_based_baselines.csv",
        BASELINE_DIR / "keyword_rules" / "results" / "rule_based_baselines.md",
        BASELINE_DIR / "bm25" / "results" / "bm25_baselines.csv",
        BASELINE_DIR / "bm25" / "results" / "bm25_baselines.md",
        BASELINE_DIR / "results" / "screening_baseline_summary.csv",
        BASELINE_DIR / "results" / "screening_baseline_summary.md",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        joined = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Missing expected baseline outputs:\n{joined}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-keyword",
        action="store_true",
        help="Do not rerun deterministic keyword baselines.",
    )
    parser.add_argument(
        "--skip-bm25",
        action="store_true",
        help="Do not rerun the deterministic BM25 baseline.",
    )
    parser.add_argument(
        "--run-neural-retrieval",
        action="store_true",
        help="Run optional no-training PubMedBERT/BioBERT/SPECTER retrieval baselines.",
    )
    parser.add_argument(
        "--llm-dry-run",
        action="store_true",
        help="Resolve LEADS-Minimal and ScreenPrompt Lite profile paths without model calls.",
    )
    parser.add_argument(
        "--run-llm",
        action="store_true",
        help="Run full LLM baselines. Requires an OpenAI-compatible endpoint.",
    )
    parser.add_argument(
        "--disease",
        action="append",
        choices=DEFAULT_DISEASES,
        help="Disease namespace for LLM baselines. Repeatable; defaults to both.",
    )
    parser.add_argument(
        "--allow-missing-endpoint",
        action="store_true",
        help="Continue even if /models is unavailable. Useful when a custom endpoint blocks model listing.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    diseases = tuple(args.disease or DEFAULT_DISEASES)

    if not args.skip_keyword:
        code = run([sys.executable, str(BASELINE_DIR / "keyword_rules" / "run.py")])
        if code:
            return code

    if not args.skip_bm25:
        code = run([sys.executable, str(BASELINE_DIR / "bm25" / "run.py")])
        if code:
            return code

    if args.run_neural_retrieval:
        code = run([sys.executable, str(BASELINE_DIR / "neural_retrieval" / "run.py")])
        if code:
            return code

    if args.llm_dry_run or args.run_llm:
        base_url, verify_ssl = endpoint_settings()
        available = endpoint_available(base_url, verify_ssl=verify_ssl)
        if args.run_llm and not available and not args.allow_missing_endpoint:
            print(
                "LLM endpoint is not available at "
                f"{base_url}/models. Set LEADS_ENDPOINT/LLM_API_BASE/OPENAI_API_BASE "
                "or use --allow-missing-endpoint if your endpoint blocks /models.",
                file=sys.stderr,
            )
            return 2
        skip_server_check = False
        if not available:
            if args.run_llm and args.allow_missing_endpoint:
                skip_server_check = True
                print(
                    f"Warning: endpoint check failed for {base_url}/models; "
                    "continuing with --no-check-server because --allow-missing-endpoint was set."
                )
            else:
                print(f"Warning: endpoint check failed for {base_url}/models; running dry path checks only.")

        dry_run = args.llm_dry_run and not args.run_llm
        code = run_llm_baseline(
            BASELINE_DIR / "leads_minimal" / "run.py",
            diseases=diseases,
            dry_run=dry_run,
            skip_server_check=skip_server_check,
            experiment_prefix="baseline_leads_minimal",
        )
        if code:
            return code
        code = run_llm_baseline(
            BASELINE_DIR / "agent_slr_screenprompt_lite" / "run.py",
            diseases=diseases,
            dry_run=dry_run,
            skip_server_check=skip_server_check,
            experiment_prefix="baseline_screenprompt_lite",
        )
        if code:
            return code
        code = run_llm_baseline(
            BASELINE_DIR / "reviewcopilot_style" / "run.py",
            diseases=diseases,
            dry_run=dry_run,
            skip_server_check=skip_server_check,
            experiment_prefix="baseline_reviewcopilot_style",
        )
        if code:
            return code

    code = run([sys.executable, str(BASELINE_DIR / "summarize.py")])
    if code:
        return code
    validate_outputs()
    print("Screening baseline outputs are up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
