from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parent  # MetaAgent-Epi/
SCREENING_SRC = REPO_ROOT

sys.path.insert(0, str(MODULE_ROOT))
sys.path.insert(0, str(SCREENING_SRC))

from metaagent.coding.pipeline.extraction import EXTRACTION_BACKENDS, FETCH_STRATEGIES, run_pipeline


DISEASE_DIRS = {
    "covid19": "covid19",
    "mpox": "mpox",
}


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
                / DISEASE_DIRS.get(p.disease_key, p.disease_key) / p.topic_key
                / p.project_dir_name
                / "coding_runs" / timestamp
            )
    except Exception:
        pass
    # Fallback: no registry match — use local runs/ dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    return MODULE_ROOT / "runs" / f"{profile_name}_{timestamp}"


def main():
    parser = argparse.ArgumentParser(description="Epi coding sheet extraction (Stage A/B)", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    inputs=parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", help="Numeric PMID list (.txt), PDF, Markdown file, or full-text directory")
    inputs.add_argument("--document-manifest", help="JSON/JSONL source bundles with record_id, path and optional supplements")
    parser.add_argument(
        "--profile",
        default=None,
        help=(
            "Screening profile ID (e.g. P13). Looks up topic/project from the profile "
            "registry and writes to evaluation/coding/{disease}/{topic}/{project}/coding_runs/{timestamp}/."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Explicit output directory. Overrides --profile auto-path when given.",
    )
    parser.add_argument("--stage", choices=["fetch", "index", "extract", "both"], default="both",
                        help="fetch=download+MinerU; index=legacy index; extract/both=selected A/B variant")
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
        required=True,
    )
    parser.add_argument(
        "--skip-stage-a",
        action="store_true",
        help="Skip Stage A evidence localization and run Stage B directly on the full text.",
    )
    parser.add_argument(
        "--extraction-backend", choices=EXTRACTION_BACKENDS, default="langextract",
        help="Internal Stage A backend; B performs semantic finalization.",
    )
    parser.add_argument("--ablation", choices=["full", "without_a", "without_b"], default="full")
    parser.add_argument("--chunk-chars", type=int, default=None)
    parser.add_argument("--stage-a-empty-retries", type=int, choices=range(3), default=1)
    parser.add_argument("--extraction-scope", default=None)
    parser.add_argument("--research-question",default=None)
    parser.add_argument("--task-context",default=None,help="JSON/YAML research_question and review_protocol")
    args = parser.parse_args()
    from metaagent.coding.prompt_context import load_review_context
    try:review_context=load_review_context(args.task_context,args.research_question)
    except (OSError,ValueError) as exc:parser.error(str(exc))
    source=Path(args.document_manifest or args.input).expanduser().resolve()
    if not source.exists():
        parser.error(f"Coding input not found: {source}")
    if args.chunk_chars is not None and args.chunk_chars < 256:
        parser.error("--chunk-chars must be at least 256")
    if args.skip_stage_a and args.ablation == "without_b":
        parser.error("--skip-stage-a conflicts with --ablation without_b")
    if not Path(args.codebook).expanduser().is_file():
        parser.error(f"Codebook not found: {args.codebook}")

    if args.out is not None:
        out_dir = Path(args.out)
    elif args.profile is not None:
        out_dir = _resolve_output_from_profile(args.profile)
    else:
        parser.error("Either --out or --profile must be provided.")

    print(f"Output: {out_dir}")
    try:
        run_pipeline(
            source,
            out_dir,
            args.stage,
            Path(args.codebook),
            fetch_strategy=args.fetch_mode,
            skip_stage_a=args.skip_stage_a,
            extraction_backend=args.extraction_backend,
            document_manifest=source if args.document_manifest else None,
            extraction_scope=args.extraction_scope, review_context=review_context,
            ablation=args.ablation, chunk_chars=args.chunk_chars, stage_a_empty_retries=args.stage_a_empty_retries,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
