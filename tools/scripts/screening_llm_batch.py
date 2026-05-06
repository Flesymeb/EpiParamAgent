#!/usr/bin/env python3
"""Run LLM screening for one profile or explicit CSV paths."""

from __future__ import annotations

import argparse
import asyncio
import csv
from copy import deepcopy
from pathlib import Path
from typing import Any


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _merge_rows_by_pmid(
    base_rows: list[dict[str, Any]], replacement_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    replacements = {
        (row.get("PMID") or "").strip(): row
        for row in replacement_rows
        if (row.get("PMID") or "").strip()
    }
    return [replacements.get((row.get("PMID") or "").strip(), row) for row in base_rows]


def _resolve_profile_config(profile_name: str | None) -> tuple[dict[str, Any], str]:
    if not profile_name:
        return {}, ""

    from metaagent.screening.profile_registry import get_profile

    profile = get_profile(profile_name.upper())
    if profile is None:
        raise ValueError(f"Unknown profile: {profile_name}")
    config = profile.to_screening_config()
    return config, profile.research_question


def _resolve_io_paths(args: argparse.Namespace) -> tuple[Path, Path, Path | None]:
    if args.project_root and args.profile:
        from metaagent.screening.profile_registry import resolve_profile_paths

        _, paths = resolve_profile_paths(
            project_root=args.project_root,
            profile_name=args.profile,
            topic=args.topic or None,
            experiment=args.experiment or None,
        )
        return paths.raw_file, paths.screened_file, paths.ground_truth_file

    if not (args.input and args.output):
        raise ValueError(
            "Use either --project-root/--profile or explicit --input/--output."
        )
    return (
        Path(args.input).expanduser().resolve(),
        Path(args.output).expanduser().resolve(),
        Path(args.ground_truth).expanduser().resolve() if args.ground_truth else None,
    )


async def _screen(
    papers: list[dict[str, Any]],
    *,
    research_question: str,
    llm_model: Any,
    batch_size: int,
    batch_concurrency: int,
    screening_config: dict[str, Any],
    screening_stage: str,
    content_label: str,
    content_key: str,
    content_fallback: str,
    strategy: str,
) -> None:
    from metaagent.screening.engine import screen_papers_batch_async

    await screen_papers_batch_async(
        papers,
        research_question,
        llm_model,
        batch_size=batch_size,
        batch_concurrency=batch_concurrency,
        screening_config=screening_config,
        screening_stage=screening_stage,
        content_label=content_label,
        content_key=content_key,
        content_fallback=content_fallback,
        strategy=strategy,
    )


def _save(
    *,
    papers: list[dict[str, Any]],
    output_file: Path,
    research_question: str,
    input_file: Path,
    gt_file: Path | None,
    gt_pmids: set[str],
    gt_count: int | None,
    args: argparse.Namespace,
    fulltext_needed_count: int,
    fulltext_ready_count: int,
    fulltext_errors: list[dict[str, str]],
):
    from metaagent.screening.reporting import save_screening_outputs

    return save_screening_outputs(
        papers=papers,
        output_file=output_file,
        research_question=research_question,
        input_file=input_file,
        gt_file=gt_file,
        gt_pmids=gt_pmids,
        gt_count=gt_count,
        batch_size=args.batch_size,
        batch_concurrency=args.batch_concurrency,
        profile_name=args.profile,
        auto_fulltext=bool(args.auto_fulltext or args.fulltext_only),
        fulltext_only=bool(args.fulltext_only),
        fulltext_needed_count=fulltext_needed_count,
        fulltext_ready_count=fulltext_ready_count,
        fulltext_errors=fulltext_errors,
        strategy=args.strategy,
        experiment=args.experiment or None,
    )


def _run_second_stage(
    *,
    stage1_file: Path,
    output_file: Path,
    gt_file: Path | None,
    gt_pmids: set[str],
    gt_count: int | None,
    research_question: str,
    llm_model: Any,
    screening_config: dict[str, Any],
    args: argparse.Namespace,
    candidate_labels: set[str],
    strong_stage: str,
    possible_stage: str,
    suffix: str,
) -> None:
    from metaagent.screening.fulltext_pipeline import prepare_fulltext_candidates

    if not stage1_file.exists():
        raise FileNotFoundError(f"Stage-1 file not found: {stage1_file}")

    base_rows = _load_csv_rows(stage1_file)
    candidates = [
        deepcopy(row)
        for row in base_rows
        if row.get("llm_suggest") in candidate_labels
    ]
    if not candidates:
        print("No second-stage candidates found.")
        return

    fulltext_errors: list[dict[str, str]] = []
    fulltext_ready, _, _ = prepare_fulltext_candidates(
        papers_without_abstract=candidates,
        fulltext_cached=[],
        fulltext_errors=fulltext_errors,
        source_strategy="pmc_only",
    )

    strong_rows = [p for p in fulltext_ready if p.get("llm_suggest") == "strong_candidate"]
    possible_rows = [p for p in fulltext_ready if p.get("llm_suggest") != "strong_candidate"]

    if strong_rows:
        asyncio.run(
            _screen(
                strong_rows,
                research_question=research_question,
                llm_model=llm_model,
                batch_size=args.batch_size,
                batch_concurrency=args.batch_concurrency,
                screening_config=screening_config,
                screening_stage=strong_stage,
                content_label="Full-text content (Markdown)",
                content_key="fulltext_markdown",
                content_fallback="(Full-text content unavailable.)",
                strategy=args.strategy,
            )
        )
    if possible_rows:
        asyncio.run(
            _screen(
                possible_rows,
                research_question=research_question,
                llm_model=llm_model,
                batch_size=args.batch_size,
                batch_concurrency=args.batch_concurrency,
                screening_config=screening_config,
                screening_stage=possible_stage,
                content_label="Full-text content (Markdown)",
                content_key="fulltext_markdown",
                content_fallback="(Full-text content unavailable.)",
                strategy=args.strategy,
            )
        )

    for row in fulltext_ready:
        row["fulltext_status"] = "screened"

    stage2_output = output_file.with_name(f"{output_file.stem}_{suffix}.csv")
    final_output = output_file.with_name(f"{output_file.stem}_final.csv")
    _save(
        papers=candidates,
        output_file=stage2_output,
        research_question=research_question,
        input_file=stage1_file,
        gt_file=gt_file,
        gt_pmids=gt_pmids,
        gt_count=gt_count,
        args=args,
        fulltext_needed_count=len(candidates),
        fulltext_ready_count=len(fulltext_ready),
        fulltext_errors=fulltext_errors,
    )
    merged = _merge_rows_by_pmid(base_rows, candidates)
    saved, report, manifest, run_dir = _save(
        papers=merged,
        output_file=final_output,
        research_question=research_question,
        input_file=stage1_file,
        gt_file=gt_file,
        gt_pmids=gt_pmids,
        gt_count=gt_count,
        args=args,
        fulltext_needed_count=len(candidates),
        fulltext_ready_count=len(fulltext_ready),
        fulltext_errors=fulltext_errors,
    )
    print(f"Final output: {saved}")
    print(f"Run snapshot: {run_dir}")
    print(f"Report: {report}")
    print(f"Manifest: {manifest}")


def main() -> None:
    args = _build_arg_parser().parse_args()

    from metaagent.screening.engine import init_llm_model, load_ground_truth_pmids
    from metaagent.screening.fulltext_pipeline import prepare_fulltext_candidates
    from metaagent.screening.staging import (
        annotate_ground_truth,
        partition_papers,
        print_ground_truth_warning,
        print_stage_split,
    )

    screening_config, research_question = _resolve_profile_config(args.profile)
    if args.no_fulltext_rescue:
        policies = screening_config.setdefault("policies", {})
        rescue_policy = dict(policies.get("fulltext_rescue", {}) or {})
        rescue_policy["enabled"] = False
        policies["fulltext_rescue"] = rescue_policy
    if args.research_question:
        research_question = args.research_question
    input_file, output_file, gt_file = _resolve_io_paths(args)

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    gt_pmids = load_ground_truth_pmids(gt_file) if gt_file else set()
    if gt_pmids:
        print(f"Loaded {len(gt_pmids)} ground-truth PMIDs")
    elif gt_file:
        print_ground_truth_warning(gt_file)

    llm_model = init_llm_model(model_override=args.model or None)

    if args.resume_possible_fulltext or args.resume_sp_fulltext:
        stage1_file = output_file if output_file.exists() else input_file
        if args.resume_possible_fulltext:
            labels = {"possible_candidate"}
            strong_stage = possible_stage = "possible_full_text"
            suffix = "stage2_possible_fulltext"
        else:
            labels = {"strong_candidate", "possible_candidate"}
            strong_stage = "strong_full_text"
            possible_stage = "possible_full_text"
            suffix = "stage2_sp_fulltext"
        _run_second_stage(
            stage1_file=stage1_file,
            output_file=output_file,
            gt_file=gt_file,
            gt_pmids=gt_pmids,
            gt_count=None,
            research_question=research_question,
            llm_model=llm_model,
            screening_config=screening_config,
            args=args,
            candidate_labels=labels,
            strong_stage=strong_stage,
            possible_stage=possible_stage,
            suffix=suffix,
        )
        return

    if args.resume_fulltext:
        if not output_file.exists():
            raise FileNotFoundError(
                f"Milestone file not found for --resume-fulltext: {output_file}"
            )
        papers = _load_csv_rows(output_file)
        gt_count = annotate_ground_truth(papers, gt_pmids)
        eligible = [p for p in papers if p.get("fulltext_eligible") == "yes"]
        if not eligible:
            print("No fulltext_eligible=yes rows found.")
            return
        fulltext_errors: list[dict[str, str]] = []
        fulltext_ready, _, _ = prepare_fulltext_candidates(
            papers_without_abstract=eligible,
            fulltext_cached=[],
            fulltext_errors=fulltext_errors,
        )
        if fulltext_ready:
            asyncio.run(
                _screen(
                    fulltext_ready,
                    research_question=research_question,
                    llm_model=llm_model,
                    batch_size=args.batch_size,
                    batch_concurrency=args.batch_concurrency,
                    screening_config=screening_config,
                    screening_stage="full_text",
                    content_label="Full-text content (Markdown)",
                    content_key="fulltext_markdown",
                    content_fallback="(Full-text content unavailable.)",
                    strategy=args.strategy,
                )
            )
            for paper in fulltext_ready:
                paper["fulltext_status"] = "screened"
                paper["fulltext_eligible"] = "done"
        _save(
            papers=papers,
            output_file=output_file,
            research_question=research_question,
            input_file=output_file,
            gt_file=gt_file,
            gt_pmids=gt_pmids,
            gt_count=gt_count,
            args=args,
            fulltext_needed_count=len(eligible),
            fulltext_ready_count=len(fulltext_ready),
            fulltext_errors=fulltext_errors,
        )
        print("Full-text resume completed.")
        return

    papers = _load_csv_rows(input_file)
    gt_count = annotate_ground_truth(papers, gt_pmids)
    stage_state = partition_papers(
        papers=papers,
        screening_config=screening_config,
        auto_fulltext=args.auto_fulltext,
        fulltext_only=args.fulltext_only,
    )

    if args.skip_no_abstract:
        policies = (screening_config or {}).get("policies", {}) or {}
        title_only_mode = str(policies.get("title_only_mode", "lenient")).strip().lower()
        for paper in stage_state["papers_without_abstract"]:
            paper["screening_stage"] = "title_only"
            paper["screening_mode"] = title_only_mode
            paper["fulltext_eligible"] = "yes"
            paper["llm_suggest"] = ""
            paper["fulltext_status"] = ""
        stage_state["papers_title_only"].extend(stage_state["papers_without_abstract"])
        stage_state["papers_without_abstract"] = []

    print_stage_split(
        papers_title_abstract=stage_state["papers_title_abstract"],
        papers_title_only=stage_state["papers_title_only"],
        papers_without_abstract=stage_state["papers_without_abstract"],
        auto_fulltext=stage_state["effective_auto_fulltext"],
        fulltext_only=stage_state["effective_fulltext_only"],
    )

    if stage_state["papers_title_abstract"]:
        asyncio.run(
            _screen(
                stage_state["papers_title_abstract"],
                research_question=research_question,
                llm_model=llm_model,
                batch_size=args.batch_size,
                batch_concurrency=args.batch_concurrency,
                screening_config=screening_config,
                screening_stage="title_abstract",
                content_label="Abstract",
                content_key="Abstract",
                content_fallback="(Abstract unavailable.)",
                strategy=args.strategy,
            )
        )

    if stage_state["papers_title_only"]:
        asyncio.run(
            _screen(
                stage_state["papers_title_only"],
                research_question=research_question,
                llm_model=llm_model,
                batch_size=args.batch_size,
                batch_concurrency=args.batch_concurrency,
                screening_config=screening_config,
                screening_stage="title_only",
                content_label="Available metadata",
                content_key="Abstract",
                content_fallback="(No abstract available. Assess based on title and keywords only.)",
                strategy=args.strategy,
            )
        )

    fulltext_ready: list[dict[str, Any]] = []
    fulltext_needed = len(stage_state["papers_without_abstract"])
    if stage_state["effective_auto_fulltext"] and (
        stage_state["papers_without_abstract"] or stage_state["fulltext_cached"]
    ):
        fulltext_ready, _, _ = prepare_fulltext_candidates(
            papers_without_abstract=stage_state["papers_without_abstract"],
            fulltext_cached=stage_state["fulltext_cached"],
            fulltext_errors=stage_state["fulltext_errors"],
        )
        if fulltext_ready:
            asyncio.run(
                _screen(
                    fulltext_ready,
                    research_question=research_question,
                    llm_model=llm_model,
                    batch_size=args.batch_size,
                    batch_concurrency=args.batch_concurrency,
                    screening_config=screening_config,
                    screening_stage="full_text",
                    content_label="Full-text content (Markdown)",
                    content_key="fulltext_markdown",
                    content_fallback="(Full-text content unavailable.)",
                    strategy=args.strategy,
                )
            )
            for paper in fulltext_ready:
                paper["fulltext_status"] = "screened"

    saved, report, manifest, run_dir = _save(
        papers=papers,
        output_file=output_file,
        research_question=research_question,
        input_file=input_file,
        gt_file=gt_file,
        gt_pmids=gt_pmids,
        gt_count=gt_count,
        args=args,
        fulltext_needed_count=fulltext_needed,
        fulltext_ready_count=len(fulltext_ready),
        fulltext_errors=stage_state["fulltext_errors"],
    )

    print("Screening completed.")
    print(f"Latest output: {saved}")
    print(f"Run snapshot: {run_dir}")
    print(f"Report: {report}")
    print(f"Manifest: {manifest}")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run LLM-based literature screening")
    parser.add_argument("--project-root", default="", help="Repository root for profile mode")
    parser.add_argument("--profile", default=None, help="Screening profile, e.g. P13 or MP9")
    parser.add_argument("--topic", default="", help="Optional topic override")
    parser.add_argument("--input", default="", help="Explicit input CSV")
    parser.add_argument("--output", default="", help="Explicit output CSV")
    parser.add_argument("--ground-truth", default="", help="Explicit ground-truth CSV")
    parser.add_argument("--research-question", default="", help="Research question for explicit file mode")
    parser.add_argument("--batch-size", type=int, default=20, help="Progress/logging batch size")
    parser.add_argument("--batch-concurrency", type=int, default=1, help="Max in-flight LLM requests")
    parser.add_argument("--model", default="", help="Override model name")
    parser.add_argument(
        "--strategy",
        choices=["5d", "binary", "binary_noguidance", "binary_baseline", "peco"],
        default="5d",
    )
    parser.add_argument("--experiment", default="", help="Experiment output subdirectory")
    parser.add_argument("--fulltext-only", action="store_true", help="Only run full-text screening")
    parser.add_argument("--auto-fulltext", action="store_true", help="Fetch full text for routed papers")
    parser.add_argument("--no-fulltext-rescue", action="store_true", help="Disable profile full-text rescue policy")
    parser.add_argument("--skip-no-abstract", action="store_true", help="Title-only now, full-text later")
    parser.add_argument("--resume-fulltext", action="store_true", help="Deprecated alias; use --resume-sp-fulltext")
    parser.add_argument("--resume-possible-fulltext", action="store_true")
    parser.add_argument("--resume-sp-fulltext", action="store_true")
    return parser


if __name__ == "__main__":
    main()
