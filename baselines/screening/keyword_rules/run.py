#!/usr/bin/env python3
"""Run keyword-rule screening baselines into this baseline folder."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools" / "scripts" / "rule_based_screening_baselines.py"
RESULTS = Path(__file__).resolve().parent / "results"
DEFAULT_OUTPUT = RESULTS / "rule_based_baselines.csv"
DEFAULT_SUMMARY = RESULTS / "rule_based_baselines.md"


def _has_option(args: list[str], name: str) -> bool:
    return any(arg == name or arg.startswith(f"{name}=") for arg in args)


def main() -> int:
    args = sys.argv[1:]
    cmd = [sys.executable, str(SCRIPT)]
    if not _has_option(args, "--output"):
        cmd += ["--output", str(DEFAULT_OUTPUT)]
    if not _has_option(args, "--summary"):
        cmd += ["--summary", str(DEFAULT_SUMMARY)]
    cmd += args
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
