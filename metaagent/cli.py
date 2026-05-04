"""MetaAgent-Epi CLI: epidemiological systematic review screening and coding.

Usage:
    python -m metaagent.cli screening run [OPTIONS]
    python -m metaagent.cli coding extract [OPTIONS]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from typing import Any

try:
    csv.field_size_limit(sys.maxsize)
except Exception:
    try:
        csv.field_size_limit(2**31 - 1)
    except Exception:
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MetaAgent-Epi: LLM-powered epidemiological systematic review automation"
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── screening run ──
    screen = sub.add_parser("screening", help="Run LLM screening")
    screen.add_argument("action", choices=["run"], help="Screening action")
    screen.add_argument("--input", required=True, help="Input CSV file path")
    screen.add_argument("--output", required=True, help="Output CSV file path")
    screen.add_argument("--ground-truth", default="", help="Ground truth CSV for evaluation")
    screen.add_argument(
        "--strategy", choices=["5d", "binary", "binary_baseline", "binary_noguidance", "peco"],
        default="5d", help="Screening prompt strategy"
    )
    screen.add_argument("--model", default="", help="Model name override")
    screen.add_argument("--batch-size", type=int, default=20, help="Papers per batch")
    screen.add_argument("--batch-concurrency", type=int, default=1, help="Concurrent batches")
    screen.add_argument("--cascade", action="store_true", help="Enable cascade retrieval for uncertain papers")
    screen.add_argument("--experiment", default="", help="Experiment name for output organization")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.command == "screening" and args.action == "run":
        _cmd_screening_run(args)
    else:
        _build_parser().print_help()


def _cmd_screening_run(args: argparse.Namespace) -> None:
    """Execute LLM screening with optional cascade retrieval."""
    from metaagent.config import load_runtime_env, load_llm_config
    from metaagent.screening.engine import (
        init_llm_model, load_ground_truth_pmids, screen_papers_batch_async,
    )
    from metaagent.screening.profile import resolve_profile_config
    from metaagent.screening.staging import annotate_ground_truth, partition_papers, print_stage_split
    from metaagent.screening.reporting import save_screening_outputs

    load_runtime_env()

    input_file = Path(args.input)
    output_file = Path(args.output)
    if not input_file.exists():
        print(f"Error: input file not found: {input_file}")
        sys.exit(1)

    # Load ground truth
    gt_file = Path(args.ground_truth) if args.ground_truth else None
    gt_pmids: set[str] = set()
    if gt_file and gt_file.exists():
        gt_pmids = load_ground_truth_pmids(gt_file)
        print(f"Loaded {len(gt_pmids)} ground truth papers")

    # Init LLM
    print("Initializing LLM model...")
    llm_model = init_llm_model(model_override=args.model or None)
    strategy = args.strategy
    cfg = load_llm_config()
    print(f"Model: {args.model or cfg.model} | Strategy: {strategy}")

    # Load papers
    with open(input_file, "r", encoding="utf-8-sig") as f:
        papers = list(csv.DictReader(f))
    print(f"Loaded {len(papers)} papers")

    # Build config
    from metaagent.config import load_runtime_env as _reload
    screening_config: dict[str, Any] = {}

    gt_count = annotate_ground_truth(papers, gt_pmids)

    # Stage papers
    stage_state = partition_papers(
        papers=papers,
        screening_config=screening_config,
        auto_fulltext=False,
        fulltext_only=False,
    )
    print_stage_split(
        papers_title_abstract=stage_state["papers_title_abstract"],
        papers_title_only=stage_state["papers_title_only"],
        papers_without_abstract=stage_state["papers_without_abstract"],
        auto_fulltext=False,
        fulltext_only=False,
    )

    # Run title+abstract screening
    if stage_state["papers_title_abstract"]:
        print(f"\nScreening {len(stage_state['papers_title_abstract'])} papers (title + abstract)...")
        asyncio.run(
            screen_papers_batch_async(
                stage_state["papers_title_abstract"],
                research_question="",
                llm_model=llm_model,
                batch_size=args.batch_size,
                batch_concurrency=args.batch_concurrency,
                screening_config=screening_config,
                screening_stage="title_abstract",
                content_label="Abstract",
                content_key="Abstract",
                content_fallback="(Abstract unavailable.)",
                strategy=strategy,
            )
        )

    # Run title-only screening
    if stage_state["papers_title_only"]:
        print(f"\nScreening {len(stage_state['papers_title_only'])} papers (title only)...")
        asyncio.run(
            screen_papers_batch_async(
                stage_state["papers_title_only"],
                research_question="",
                llm_model=llm_model,
                batch_size=args.batch_size,
                batch_concurrency=args.batch_concurrency,
                screening_config=screening_config,
                screening_stage="title_only",
                content_label="Available metadata",
                content_key="Abstract",
                content_fallback="(No abstract available.)",
                strategy=strategy,
            )
        )

    # Save results
    saved, log_file, manifest_path, run_dir = save_screening_outputs(
        papers=papers,
        output_file=output_file,
        research_question="",
        input_file=input_file,
        gt_file=gt_file or Path(""),
        gt_pmids=gt_pmids,
        gt_count=gt_count,
        batch_size=args.batch_size,
        batch_concurrency=args.batch_concurrency,
        profile_name="",
        auto_fulltext=False,
        fulltext_only=False,
        fulltext_needed_count=0,
        fulltext_ready_count=0,
        fulltext_errors=[],
        strategy=strategy,
        experiment=args.experiment or None,
    )

    # Summary
    strong = sum(1 for p in papers if p.get("llm_suggest") == "strong_candidate")
    possible = sum(1 for p in papers if p.get("llm_suggest") == "possible_candidate")
    unlikely = sum(1 for p in papers if p.get("llm_suggest") == "unlikely_candidate")
    errors = sum(1 for p in papers if p.get("llm_suggest") == "error")

    # Cost summary
    total_prompt = sum(int(p.get("prompt_tokens", 0)) for p in papers)
    total_completion = sum(int(p.get("completion_tokens", 0)) for p in papers)
    total_time = sum(float(p.get("wall_time_ms", 0)) for p in papers)

    print(f"\nScreening complete.")
    print(f"  Results: Strong={strong}, Possible={possible}, Unlikely={unlikely}, Errors={errors}")
    print(f"  Tokens: {total_prompt:,} prompt + {total_completion:,} completion = {total_prompt+total_completion:,} total")
    print(f"  Time: {total_time/1000:.1f}s total, {total_time/len(papers):.0f}ms avg per paper")
    print(f"  Output: {saved}")


if __name__ == "__main__":
    main()
