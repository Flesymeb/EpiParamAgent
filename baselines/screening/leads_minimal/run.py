#!/usr/bin/env python3
"""Run the LEADS-Minimal screening baseline."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools" / "scripts" / "leads_mistral_screening_eval.py"
DEFAULT_MODEL = "zifeng-ai/leads-mistral-7b-v1"
MODEL_ENV_VAR = "LEADS_MODEL"


def _has_option(args: list[str], name: str) -> bool:
    return any(arg == name or arg.startswith(f"{name}=") for arg in args)


def _has_model_override(args: list[str]) -> bool:
    return _has_option(args, "--model") or bool(os.getenv(MODEL_ENV_VAR))


def main() -> int:
    args = sys.argv[1:]
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--project-root",
        str(ROOT),
        "--prompt-style",
        "disease_parameter_minimal",
    ]
    if not _has_model_override(args):
        cmd += ["--model", DEFAULT_MODEL]
    if not _has_option(args, "--experiment"):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cmd += ["--experiment", f"baseline_leads_minimal_{stamp}"]
    cmd += args
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
