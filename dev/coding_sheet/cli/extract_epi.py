from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))

from lib.pipeline.extraction import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Epi coding sheet extraction (Stage A/B)")
    parser.add_argument("--input", required=True, help="PMID list (.txt), PDF file, or directory")
    parser.add_argument(
        "--profile",
        default=None,
        help="Run profile name (e.g. p13_si). Auto-generates --out as runs/{profile}_{timestamp}/",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory. Required unless --profile is given.",
    )
    parser.add_argument("--stage", choices=["index", "extract", "both"], default="both")
    parser.add_argument(
        "--codebook",
        default=str(MODULE_ROOT / "configs" / "codebook_epi.yaml"),
    )
    args = parser.parse_args()

    if args.out is None:
        if args.profile is None:
            parser.error("Either --out or --profile must be provided.")
        safe_profile = re.sub(r"[^\w\-]", "_", args.profile)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        out_dir = MODULE_ROOT / "runs" / f"{safe_profile}_{timestamp}"
    else:
        out_dir = Path(args.out)

    run_pipeline(Path(args.input), out_dir, args.stage, Path(args.codebook))


if __name__ == "__main__":
    main()
