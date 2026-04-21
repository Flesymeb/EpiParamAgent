from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]  # MetaAgent-Epi/
SCREENING_SRC = REPO_ROOT / "dev" / "literature_search" / "src"

sys.path.insert(0, str(MODULE_ROOT))
sys.path.insert(0, str(SCREENING_SRC))

from lib.pipeline.extraction import run_pipeline


def _resolve_output_from_profile(profile_name: str) -> Path:
    """Look up profile in the screening registry to derive the evaluation output path.

    Returns: evaluation/coding/{topic}/{project}/coding_runs/{timestamp}/
    """
    try:
        from screening.profile_registry import get_profile
        p = get_profile(profile_name.upper())
        if p is not None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
            return (
                REPO_ROOT / "evaluation" / "coding"
                / p.topic_key / p.project_dir_name
                / "coding_runs" / timestamp
            )
    except Exception:
        pass
    # Fallback: no registry match — use local runs/ dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    return MODULE_ROOT / "runs" / f"{profile_name}_{timestamp}"


def main():
    parser = argparse.ArgumentParser(description="Epi coding sheet extraction (Stage A/B)")
    parser.add_argument("--input", required=True, help="PMID list (.txt), PDF file, or directory")
    parser.add_argument(
        "--profile",
        default=None,
        help=(
            "Screening profile ID (e.g. P13). Looks up topic/project from the profile "
            "registry and writes to evaluation/coding/{topic}/{project}/coding_runs/{timestamp}/."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Explicit output directory. Overrides --profile auto-path when given.",
    )
    parser.add_argument("--stage", choices=["index", "extract", "both"], default="both")
    parser.add_argument(
        "--codebook",
        default=str(MODULE_ROOT / "configs" / "codebook_epi.yaml"),
    )
    args = parser.parse_args()

    if args.out is not None:
        out_dir = Path(args.out)
    elif args.profile is not None:
        out_dir = _resolve_output_from_profile(args.profile)
    else:
        parser.error("Either --out or --profile must be provided.")

    print(f"Output: {out_dir}")
    run_pipeline(Path(args.input), out_dir, args.stage, Path(args.codebook))


if __name__ == "__main__":
    main()
