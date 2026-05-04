from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parents[1]  # MetaAgent-Epi/
SCREENING_SRC = REPO_ROOT

sys.path.insert(0, str(MODULE_ROOT))
sys.path.insert(0, str(SCREENING_SRC))

from metaagent.coding.pipeline.extraction import FETCH_STRATEGIES, run_pipeline


def _resolve_output_from_profile(profile_name: str) -> Path:
    """Look up profile in the screening registry to derive the evaluation output path.

    Returns: evaluation/coding/{disease}/{topic}/{project}/coding_runs/{timestamp}/
    """
    try:
        from metaagent.screening.profile_registry import get_profile
        p = get_profile(profile_name.upper())
        if p is not None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
            return (
                REPO_ROOT / "evaluation" / "coding"
                / p.disease_key / p.topic_key
                / p.project_dir_name
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
    parser.add_argument("--stage", choices=["fetch", "index", "extract", "both"], default="both",
                        help="fetch=download+MinerU only; index=Stage A; extract=Stage B; both=A+B")
    parser.add_argument(
        "--fetch-mode",
        dest="fetch_mode",
        choices=FETCH_STRATEGIES,
        default="pmc_only",
        help=(
            "PDF fetch strategy: "
            "pmc_only = PMC OA only (default, safe); "
            "pmc_scihub = PMC first then Sci-Hub fallback; "
            "pmc_scihub_manual = as above plus interactive prompt"
        ),
    )
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
    run_pipeline(Path(args.input), out_dir, args.stage, Path(args.codebook), fetch_strategy=args.fetch_mode)


if __name__ == "__main__":
    main()
