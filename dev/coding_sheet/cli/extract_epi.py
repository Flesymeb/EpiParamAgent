from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.pipeline.extraction import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Epi coding sheet extraction (Stage A/B)")
    parser.add_argument("--input", required=True, help="Markdown/PDF file or directory")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--stage", choices=["index", "extract", "both"], default="both")
    parser.add_argument("--codebook", default=str(Path(__file__).resolve().parents[1] / "configs" / "codebook_epi.yaml"))
    args = parser.parse_args()

    run_pipeline(Path(args.input), Path(args.out), args.stage, Path(args.codebook))


if __name__ == "__main__":
    main()
