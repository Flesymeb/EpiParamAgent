#!/usr/bin/env python3
"""Run the AgentSLR-style ScreenPrompt Lite screening baseline."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools" / "scripts" / "leads_mistral_screening_eval.py"


def _has_option(args: list[str], name: str) -> bool:
    return any(arg == name or arg.startswith(f"{name}=") for arg in args)


def main() -> int:
    args = sys.argv[1:]
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--project-root",
        str(ROOT),
        "--prompt-style",
        "screenprompt_lite",
    ]
    if not _has_option(args, "--experiment"):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cmd += ["--experiment", f"baseline_screenprompt_lite_{stamp}"]
    cmd += args
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
