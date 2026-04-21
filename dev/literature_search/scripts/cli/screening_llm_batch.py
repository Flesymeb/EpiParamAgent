#!/usr/bin/env python3
"""LLM screening entrypoint for title/abstract and optional full-text rescue."""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from typing import Any
from copy import deepcopy

# Set CSV field size limit to maximum possible value.
try:
    csv.field_size_limit(sys.maxsize)
except (AttributeError, ValueError, OverflowError):
    try:
        csv.field_size_limit(2**31 - 1)
    except (AttributeError, ValueError, OverflowError):
        pass

# Add project paths for shared tools and screening package imports.
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR / "src"))
sys.path.insert(0, str(BASE_DIR.parent / "tools"))

from common.config import load_runtime_env
from screening.fulltext_pipeline import MD_CACHE_DIR

load_runtime_env(module_hint="literature_search")


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _merge_stage2_possible_results(
    base_rows: list[dict[str, Any]],
    stage2_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    replacements = {
        (row.get("PMID") or "").strip(): row
        for row in stage2_rows
        if (row.get("PMID") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    for row in base_rows:
        pmid = (row.get("PMID") or "").strip()
        if pmid in replacements:
            merged.append(replacements[pmid])
        else:
            merged.append(row)
    return merged


def _compute_binary_metrics(rows: list[dict[str, Any]], gt_pmids: set[str]) -> dict[str, float | int]:
    tp = fp = fn = tn = 0
    for row in rows:
        pmid = (row.get("PMID") or "").strip()
        suggest = row.get("llm_suggest") or ""
        relevant = suggest in {"strong_candidate", "possible_candidate"}
        is_gt = pmid in gt_pmids
        if is_gt and relevant:
            tp += 1
        elif is_gt and not relevant:
            fn += 1
        elif (not is_gt) and relevant:
            fp += 1
        else:
            tn += 1

    total = tp + fp + fn + tn
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    npv = tn / (tn + fn) if (tn + fn) else 0.0
    accuracy = (tp + tn) / total if total else 0.0
    wr = (tn + fn) / total if total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    nns = (tp + fp) / tp if tp else float("inf")
    denom = ((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) ** 0.5
    mcc = ((tp * tn - fp * fn) / denom) if denom else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "recall": recall,
        "precision": precision,
        "specificity": specificity,
        "npv": npv,
        "accuracy": accuracy,
        "wr": wr,
        "f1": f1,
        "nns": nns,
        "mcc": mcc,
    }


def _format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_ratio(value: float) -> str:
    return "inf" if value == float("inf") else f"{value:.2f}"


def _collect_label_changes(
    base_rows: list[dict[str, Any]],
    merged_rows: list[dict[str, Any]],
    gt_pmids: set[str],
) -> list[dict[str, str]]:
    merged_by_pmid = {
        (row.get("PMID") or "").strip(): row
        for row in merged_rows
        if (row.get("PMID") or "").strip()
    }
    changes: list[dict[str, str]] = []
    for row in base_rows:
        pmid = (row.get("PMID") or "").strip()
        new_row = merged_by_pmid.get(pmid)
        if not new_row:
            continue
        old_label = row.get("llm_suggest") or ""
        new_label = new_row.get("llm_suggest") or ""
        if old_label == new_label:
            continue
        changes.append(
            {
                "pmid": pmid,
                "title": row.get("Title", ""),
                "old": old_label,
                "new": new_label,
                "is_gt": "yes" if pmid in gt_pmids else "no",
            }
        )
    return changes


def _print_second_stage_summary(
    *,
    base_rows: list[dict[str, Any]],
    merged_rows: list[dict[str, Any]],
    possible_rows: list[dict[str, Any]],
    fulltext_ready: list[dict[str, Any]],
    gt_pmids: set[str],
) -> None:
    if not gt_pmids:
        return

    before = _compute_binary_metrics(base_rows, gt_pmids)
    after = _compute_binary_metrics(merged_rows, gt_pmids)
    changes = _collect_label_changes(base_rows, merged_rows, gt_pmids)
    pmc_unavailable = sum(1 for row in possible_rows if row.get("fulltext_status") == "pmc_unavailable")
    screened = sum(1 for row in possible_rows if row.get("fulltext_status") == "screened")

    print("\n" + "=" * 80)
    print("Second-stage summary")
    print("=" * 80)
    print(f"Possible candidates input: {len(possible_rows)}")
    print(f"PMC full-text screened: {screened}")
    print(f"PMC unavailable (kept original label): {pmc_unavailable}")
    print(f"Label changes after merge: {len(changes)}")
    if changes:
        for item in changes[:10]:
            print(
                f"  PMID={item['pmid']} | GT={item['is_gt']} | {item['old']} -> {item['new']} | {item['title'][:120]}"
            )
        if len(changes) > 10:
            print(f"  ... {len(changes) - 10} more changes")

    print("\nStage1 metrics:")
    print(
        f"  TP/FP/FN/TN = {before['tp']} / {before['fp']} / {before['fn']} / {before['tn']} | "
        f"Recall={_format_pct(before['recall'])} | Precision={_format_pct(before['precision'])} | "
        f"F1={_format_pct(before['f1'])} | MCC={before['mcc']:.3f}"
    )
    print("Final merged metrics:")
    print(
        f"  TP/FP/FN/TN = {after['tp']} / {after['fp']} / {after['fn']} / {after['tn']} | "
        f"Recall={_format_pct(after['recall'])} | Precision={_format_pct(after['precision'])} | "
        f"F1={_format_pct(after['f1'])} | MCC={after['mcc']:.3f}"
    )
    print("Delta:")
    print(
        f"  TP {before['tp']} -> {after['tp']} ({after['tp'] - before['tp']:+d}) | "
        f"FP {before['fp']} -> {after['fp']} ({after['fp'] - before['fp']:+d}) | "
        f"FN {before['fn']} -> {after['fn']} ({after['fn'] - before['fn']:+d}) | "
        f"TN {before['tn']} -> {after['tn']} ({after['tn'] - before['tn']:+d})"
    )
    print(
        f"  Recall {_format_pct(before['recall'])} -> {_format_pct(after['recall'])} | "
        f"Precision {_format_pct(before['precision'])} -> {_format_pct(after['precision'])} | "
        f"F1 {_format_pct(before['f1'])} -> {_format_pct(after['f1'])} | "
        f"MCC {before['mcc']:.3f} -> {after['mcc']:.3f}"
    )


def _print_second_stage_screened_examples(
    possible_rows: list[dict[str, Any]],
) -> None:
    screened_rows = [
        row for row in possible_rows if row.get("fulltext_status") == "screened"
    ]
    if not screened_rows:
        return

    print("\nScreened full-text decisions:")
    for row in screened_rows[:10]:
        justification = (row.get("overall_justification") or "").replace("\n", " ").strip()
        if len(justification) > 220:
            justification = justification[:217] + "..."
        print(
            "  "
            f"PMID={row.get('PMID', 'N/A')} | "
            f"label={row.get('llm_suggest', '')} | "
            f"D/P/L/E/Param={row.get('disease_score', '')}/{row.get('population_score', '')}/"
            f"{row.get('location_score', '')}/{row.get('evidence_score', '')}/{row.get('parameter_score', '')}"
        )
        if justification:
            print(f"    {justification}")


def main() -> None:
    args = _build_arg_parser().parse_args()
    from screening.profile_resolution import (
        resolve_explicit_cli_paths,
        resolve_profile_config,
        resolve_profile_io_paths,
    )
    from screening.fulltext_pipeline import prepare_fulltext_candidates
    from screening.llm_screening import (
        init_llm_model,
        load_ground_truth_pmids,
        screen_papers_batch_async,
    )
    from screening.reporting import save_screening_outputs
    from screening.staging import (
        annotate_ground_truth,
        partition_papers,
        print_ground_truth_warning,
        print_stage_split,
    )

    screening_config, research_question = resolve_profile_config(
        args.profile, args.topic
    )
    if args.project_root and args.profile:
        _, input_file, output_file, gt_file = resolve_profile_io_paths(
            project_root=args.project_root,
            profile_name=args.profile,
            topic=args.topic,
            experiment=args.experiment or None,
        )
    else:
        if not (args.input and args.output and args.ground_truth):
            raise ValueError(
                "Use either --project-root/--profile or explicit --input/--output/--ground-truth."
            )
        input_file, output_file, gt_file = resolve_explicit_cli_paths(
            base_dir=BASE_DIR,
            input_raw=args.input,
            output_raw=args.output,
            ground_truth_raw=args.ground_truth,
        )
    batch_size = args.batch_size
    batch_concurrency = args.batch_concurrency
    strategy = args.strategy

    if args.experiment:
        print(f"实验模式: [{args.experiment}] 输出至 {output_file}\n")

    if not input_file.exists():
        print(f"错误: 找不到输入文件 {input_file}")
        print("请先运行 fetch_pubmed_abstracts.py 获取摘要")
        return

    gt_pmids = load_ground_truth_pmids(gt_file)
    if gt_pmids:
        print(f"✓ 加载了 {len(gt_pmids)} 篇Ground Truth论文\n")
    else:
        print_ground_truth_warning(gt_file)

    print("初始化LLM模型...")
    llm_model = init_llm_model(model_override=args.model or None)
    print(
        f"使用模型: {args.model or os.getenv('LLM_MODEL', 'gpt-4o-mini')} | 策略: {strategy}\n"
    )

    # ── helper shared by --resume-possible-fulltext and --resume-sp-fulltext ──
    def _run_second_stage(
        *,
        stage1_file: Path,
        candidate_labels: list[str],
        strong_stage: str,
        possible_stage: str,
        stage2_suffix: str,
        mode_label: str,
    ) -> None:
        if not stage1_file.exists():
            print(f"错误: 找不到第一阶段筛选文件 {stage1_file}")
            return

        print(f"⏩ 第二阶段 {mode_label} 模式: 从 {stage1_file} 读取第一阶段结果\n")
        papers = _load_csv_rows(stage1_file)
        print(f"读取了 {len(papers)} 条记录 (stage1)\n")
        gt_count = annotate_ground_truth(papers, gt_pmids)

        candidate_rows = [
            deepcopy(p)
            for p in papers
            if p.get("llm_suggest") in candidate_labels
        ]
        label_counts = {lbl: sum(1 for r in candidate_rows if r.get("llm_suggest") == lbl)
                        for lbl in candidate_labels}
        count_str = "  ".join(f"{lbl}={n}" for lbl, n in label_counts.items())
        print(f"找到 {len(candidate_rows)} 篇候选 ({count_str})，开始 PMC-only 全文补筛...\n")
        if not candidate_rows:
            print("ℹ️  没有候选文献，退出。")
            return

        fulltext_errors: list[dict[str, str]] = []
        fulltext_ready, _, _ = prepare_fulltext_candidates(
            papers_without_abstract=candidate_rows,
            fulltext_cached=[],
            fulltext_errors=fulltext_errors,
            source_strategy="pmc_only",
        )

        if fulltext_ready:
            # Split by original label and screen with matching stage
            strong_batch = [p for p in fulltext_ready if p.get("llm_suggest") == "strong_candidate"]
            possible_batch = [p for p in fulltext_ready if p.get("llm_suggest") != "strong_candidate"]

            for paper in fulltext_ready:
                paper["screening_stage"] = "full_text"

            if strong_batch:
                print(f"开始全文筛选 - Strong candidates ({strong_stage}): {len(strong_batch)} 篇...")
                asyncio.run(
                    screen_papers_batch_async(
                        strong_batch,
                        research_question,
                        llm_model,
                        batch_size,
                        batch_concurrency,
                        screening_config,
                        screening_stage=strong_stage,
                        content_label="Full-text content (Markdown)",
                        content_key="fulltext_markdown",
                        content_fallback="(Full-text content unavailable.)",
                    )
                )

            if possible_batch:
                print(f"开始全文筛选 - Possible candidates ({possible_stage}): {len(possible_batch)} 篇...")
                asyncio.run(
                    screen_papers_batch_async(
                        possible_batch,
                        research_question,
                        llm_model,
                        batch_size,
                        batch_concurrency,
                        screening_config,
                        screening_stage=possible_stage,
                        content_label="Full-text content (Markdown)",
                        content_key="fulltext_markdown",
                        content_fallback="(Full-text content unavailable.)",
                    )
                )

            for paper in fulltext_ready:
                paper["fulltext_status"] = "screened"

        for paper in candidate_rows:
            if paper.get("fulltext_status") == "pmc_unavailable":
                paper.setdefault("screening_stage", "title_abstract")
                paper["fulltext_eligible"] = "pmc_unavailable"

        stage2_output = output_file.with_name(f"{output_file.stem}_{stage2_suffix}.csv")
        final_output = output_file.with_name(f"{output_file.stem}_final.csv")

        stage2_saved, stage2_log, stage2_manifest, stage2_run_dir = save_screening_outputs(
            papers=candidate_rows,
            output_file=stage2_output,
            research_question=research_question,
            input_file=stage1_file,
            gt_file=gt_file,
            gt_pmids=gt_pmids,
            gt_count=gt_count,
            batch_size=batch_size,
            batch_concurrency=batch_concurrency,
            profile_name=args.profile,
            auto_fulltext=True,
            fulltext_only=True,
            fulltext_needed_count=len(candidate_rows),
            fulltext_ready_count=len(fulltext_ready),
            fulltext_errors=fulltext_errors,
        )

        merged_rows = _merge_stage2_possible_results(papers, candidate_rows)
        final_saved, final_log, final_manifest, final_run_dir = save_screening_outputs(
            papers=merged_rows,
            output_file=final_output,
            research_question=research_question,
            input_file=stage1_file,
            gt_file=gt_file,
            gt_pmids=gt_pmids,
            gt_count=gt_count,
            batch_size=batch_size,
            batch_concurrency=batch_concurrency,
            profile_name=args.profile,
            auto_fulltext=True,
            fulltext_only=False,
            fulltext_needed_count=len(candidate_rows),
            fulltext_ready_count=len(fulltext_ready),
            fulltext_errors=fulltext_errors,
        )

        print(f"\n{'='*80}")
        print(f"{mode_label} second-stage screening completed.")
        print(f"{'='*80}")
        print(f"Stage2 output: {stage2_saved}")
        print(f"Stage2 run snapshot: {stage2_run_dir}")
        print(f"Stage2 report: {stage2_log}")
        print(f"Stage2 manifest: {stage2_manifest}")
        print(f"Final merged output: {final_saved}")
        print(f"Final run snapshot: {final_run_dir}")
        print(f"Final report: {final_log}")
        print(f"Final manifest: {final_manifest}\n")
        _print_second_stage_screened_examples(candidate_rows)
        _print_second_stage_summary(
            base_rows=papers,
            merged_rows=merged_rows,
            possible_rows=candidate_rows,
            fulltext_ready=fulltext_ready,
            gt_pmids=gt_pmids,
        )

    if args.resume_possible_fulltext:
        _run_second_stage(
            stage1_file=output_file if output_file.exists() else input_file,
            candidate_labels=["possible_candidate"],
            strong_stage="possible_full_text",
            possible_stage="possible_full_text",
            stage2_suffix="stage2_possible_fulltext",
            mode_label="Possible-only",
        )
        return

    if args.resume_sp_fulltext:
        _run_second_stage(
            stage1_file=output_file if output_file.exists() else input_file,
            candidate_labels=["strong_candidate", "possible_candidate"],
            strong_stage="strong_full_text",    # confirmation pass: only demote on score ≤1
            possible_stage="possible_full_text",  # confirm_parameter: P只在参数缺失时才降
            stage2_suffix="stage2_sp_fulltext",
            mode_label="Strong+Possible",
        )
        return

    # --resume-fulltext: read from the milestone output file (previous --skip-no-abstract run)
    # and only process papers marked fulltext_eligible=yes.
    if args.resume_fulltext:
        if not output_file.exists():
            print(f"错误: 找不到里程碑文件 {output_file}")
            print("请先使用 --skip-no-abstract 完成第一阶段筛选，生成里程碑文件")
            return
        print(f"⏩  恢复模式 (--resume-fulltext): 从里程碑文件读取 {output_file}\n")
        with open(output_file, "r", encoding="utf-8-sig") as f:
            papers = list(csv.DictReader(f))
        print(f"读取了 {len(papers)} 条记录 (来自里程碑)\n")
        gt_count = annotate_ground_truth(papers, gt_pmids)
        eligible = [p for p in papers if p.get("fulltext_eligible") == "yes"]
        print(f"找到 {len(eligible)} 篇标记为 fulltext_eligible 的文献，执行全文筛选...\n")
        if not eligible:
            print("ℹ️  没有需要全文筛选的文献，退出。")
            return
        print("\n" + "=" * 80)
        print("阶段: Full-text screening (resume)")
        print("=" * 80 + "\n")
        fulltext_ready, _, _ = prepare_fulltext_candidates(
            papers_without_abstract=eligible,
            fulltext_cached=[],
            fulltext_errors=[],
        )
        if fulltext_ready:
            for paper in fulltext_ready:
                paper["screening_stage"] = "full_text"
            print(f"开始全文筛选 (full-text): {len(fulltext_ready)} 篇...")
            asyncio.run(
                screen_papers_batch_async(
                    fulltext_ready,
                    research_question,
                    llm_model,
                    batch_size,
                    batch_concurrency,
                    screening_config,
                    screening_stage="full_text",
                    content_label="Full-text content (Markdown)",
                    content_key="fulltext_markdown",
                    content_fallback="(Full-text content unavailable.)",
                    strategy=strategy,
                )
            )
            for paper in fulltext_ready:
                paper["fulltext_status"] = "screened"
                paper["fulltext_eligible"] = "done"
        saved_output, log_file, manifest_path, run_dir = save_screening_outputs(
            papers=papers,
            output_file=output_file,
            research_question=research_question,
            input_file=output_file,
            gt_file=gt_file,
            gt_pmids=gt_pmids,
            gt_count=gt_count,
            batch_size=batch_size,
            batch_concurrency=batch_concurrency,
            profile_name=args.profile,
            auto_fulltext=True,
            fulltext_only=False,
            fulltext_needed_count=len(eligible),
            fulltext_ready_count=len(fulltext_ready) if fulltext_ready else 0,
            fulltext_errors=[],
        )
        strong = sum(1 for p in papers if p.get("llm_suggest") == "strong_candidate")
        possible = sum(1 for p in papers if p.get("llm_suggest") == "possible_candidate")
        unlikely = sum(1 for p in papers if p.get("llm_suggest") == "unlikely_candidate")
        errors = sum(1 for p in papers if p.get("llm_suggest") == "error")
        print(f"\n{'='*80}")
        print("Full-text screening resumed successfully.")
        print(f"{'='*80}")
        print(
            f"\nResults: Strong {strong} | Possible {possible} | Unlikely {unlikely} | Errors {errors}"
        )
        print(f"Latest output: {saved_output}")
        print(f"Run snapshot: {run_dir}")
        print(f"Detailed report: {log_file}")
        print(f"Manifest: {manifest_path}\n")
        return

    print(f"从 {input_file} 读取数据...\n")
    with open(input_file, "r", encoding="utf-8-sig") as f:
        papers = list(csv.DictReader(f))
    print(f"读取了 {len(papers)} 条记录\n")

    gt_count = annotate_ground_truth(papers, gt_pmids)
    print("=" * 80)
    print(f"研究问题: {research_question}")
    print("=" * 80)

    stage_state = partition_papers(
        papers=papers,
        screening_config=screening_config,
        auto_fulltext=args.auto_fulltext,
        fulltext_only=args.fulltext_only,
    )
    effective_auto_fulltext = bool(stage_state["effective_auto_fulltext"])
    effective_fulltext_only = bool(stage_state["effective_fulltext_only"])

    # --skip-no-abstract: route no-abstract papers to title-only screening now,
    # mark them fulltext_eligible=yes for a future --resume-fulltext run.
    # This ensures all papers get a valid llm_suggest label so metrics are complete.
    if args.skip_no_abstract:
        effective_auto_fulltext = False
        policies = (screening_config or {}).get("policies", {}) or {}
        title_only_mode = str(policies.get("title_only_mode", "lenient")).strip().lower()
        for paper in stage_state["papers_without_abstract"]:
            paper["screening_stage"] = "title_only"
            paper["screening_mode"] = title_only_mode
            paper["fulltext_eligible"] = "yes"
            paper["llm_suggest"] = ""  # clear the needs_full_text placeholder
            paper["fulltext_status"] = ""
        stage_state["papers_title_only"].extend(stage_state["papers_without_abstract"])
        stage_state["papers_without_abstract"] = []
        print(
            f"ℹ️  --skip-no-abstract: {len(stage_state['papers_title_only'])} 篇无摘要文献转入 title-only 筛选，"
            f"标记 fulltext_eligible=yes 供后续 --resume-fulltext 使用\n"
        )

    print_stage_split(
        papers_title_abstract=stage_state["papers_title_abstract"],
        papers_title_only=stage_state["papers_title_only"],
        papers_without_abstract=stage_state["papers_without_abstract"],
        auto_fulltext=effective_auto_fulltext,
        fulltext_only=effective_fulltext_only,
    )

    if effective_fulltext_only:
        print("⚠️  fulltext-only 模式：跳过 Title/Abstract 阶段")
        stage_state["papers_title_abstract"] = []
        stage_state["papers_title_only"] = []

    if stage_state["papers_title_abstract"]:
        print("\n" + "=" * 80)
        print("阶段: Title + Abstract screening")
        print("=" * 80 + "\n")
        asyncio.run(
            screen_papers_batch_async(
                stage_state["papers_title_abstract"],
                research_question,
                llm_model,
                batch_size,
                batch_concurrency,
                screening_config,
                screening_stage="title_abstract",
                content_label="Abstract",
                content_key="Abstract",
                content_fallback="(Abstract unavailable.)",
                strategy=strategy,
            )
        )

    if stage_state["papers_title_only"]:
        print("\n" + "=" * 80)
        print("阶段: Title-only screening")
        print("=" * 80 + "\n")
        asyncio.run(
            screen_papers_batch_async(
                stage_state["papers_title_only"],
                research_question,
                llm_model,
                batch_size,
                batch_concurrency,
                screening_config,
                screening_stage="title_only",
                content_label="Available metadata",
                content_key="Abstract",
                content_fallback="(No abstract available. Assess based on title and keywords only.)",
                strategy=strategy,
            )
        )

    fulltext_ready: list[dict[str, Any]] = []
    if effective_auto_fulltext and (
        stage_state["papers_without_abstract"] or stage_state["fulltext_cached"]
    ):
        print("\n" + "=" * 80)
        print("阶段: Full-text screening (prepare + screen)")
        print("=" * 80 + "\n")
        fulltext_ready, _, _ = prepare_fulltext_candidates(
            papers_without_abstract=stage_state["papers_without_abstract"],
            fulltext_cached=stage_state["fulltext_cached"],
            fulltext_errors=stage_state["fulltext_errors"],
        )

        if fulltext_ready:
            for paper in fulltext_ready:
                paper["screening_stage"] = "full_text"
            print(f"开始全文筛选 (full-text): {len(fulltext_ready)} 篇...")
            asyncio.run(
                screen_papers_batch_async(
                    fulltext_ready,
                    research_question,
                    llm_model,
                    batch_size,
                    batch_concurrency,
                    screening_config,
                    screening_stage="full_text",
                    content_label="Full-text content (Markdown)",
                    content_key="fulltext_markdown",
                    content_fallback="(Full-text content unavailable.)",
                    strategy=strategy,
                )
            )
            for paper in fulltext_ready:
                paper["fulltext_status"] = "screened"

    saved_output, log_file, manifest_path, run_dir = save_screening_outputs(
        papers=papers,
        output_file=output_file,
        research_question=research_question,
        input_file=input_file,
        gt_file=gt_file,
        gt_pmids=gt_pmids,
        gt_count=gt_count,
        batch_size=batch_size,
        batch_concurrency=batch_concurrency,
        profile_name=args.profile,
        auto_fulltext=effective_auto_fulltext,
        fulltext_only=effective_fulltext_only,
        fulltext_needed_count=len(stage_state["papers_without_abstract"]),
        fulltext_ready_count=len(fulltext_ready),
        fulltext_errors=stage_state["fulltext_errors"],
        strategy=strategy,
        experiment=args.experiment or None,
    )

    strong = sum(1 for p in papers if p.get("llm_suggest") == "strong_candidate")
    possible = sum(1 for p in papers if p.get("llm_suggest") == "possible_candidate")
    unlikely = sum(1 for p in papers if p.get("llm_suggest") == "unlikely_candidate")
    errors = sum(1 for p in papers if p.get("llm_suggest") == "error")

    print(f"\n{'='*80}")
    print("Screening completed.")
    print(f"{'='*80}")
    print(
        f"\nResults: Strong {strong} | Possible {possible} | Unlikely {unlikely} | Errors {errors}"
    )
    print(f"Latest output: {saved_output}")
    print(f"Run snapshot: {run_dir}")
    print(f"Detailed report: {log_file}")
    print(f"Manifest: {manifest_path}\n")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用LLM批量筛选文献")
    parser.add_argument("--project-root", type=str, default="", help="仓库根目录；与 --profile 配合使用时自动解析 evaluation 路径")
    parser.add_argument("--profile", type=str, default=None, help="实验 profile 名称，例如 P13")
    parser.add_argument("--topic", type=str, default="", help="可选 topic 覆盖；默认使用 profile 自带 topic")
    parser.add_argument(
        "--input",
        type=str,
        default="",
        help="输入CSV文件路径（显式文件模式）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="输出CSV文件路径（显式文件模式）",
    )
    parser.add_argument(
        "--ground-truth",
        type=str,
        default="",
        help="Ground truth CSV文件路径（显式文件模式）",
    )
    parser.add_argument("--batch-size", type=int, default=20, help="每批处理的文献数量")
    parser.add_argument(
        "--batch-concurrency",
        type=int,
        default=1,
        help="同时并行的批次数",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="",
        help="覆盖配置文件中的模型名称，例如 openai/gpt-4o 或 deepseek/deepseek-chat",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["5d", "binary"],
        default="5d",
        help="筛选策略：5d=五维评分（默认），binary=简单包含/排除",
    )
    parser.add_argument(
        "--experiment",
        type=str,
        default="",
        help="实验名称；若指定，输出保存至 {project_root}/evaluation/experiments/{experiment}/",
    )
    parser.add_argument(
        "--fulltext-only",
        action="store_true",
        help="仅运行全文筛选（跳过标题/摘要筛选）",
    )
    parser.add_argument(
        "--auto-fulltext",
        action="store_true",
        help="无摘要文献自动下载全文并进行筛选",
    )
    parser.add_argument(
        "--skip-no-abstract",
        action="store_true",
        help="跳过全文检索：无摘要文献改走 title-only 筛选并标记 fulltext_eligible=yes，供后续 --resume-fulltext 单独处理",
    )
    parser.add_argument(
        "--resume-fulltext",
        action="store_true",
        help="从里程碑文件恢复：读取上次 --skip-no-abstract 输出，只对 fulltext_eligible=yes 的文献执行全文筛选",
    )
    parser.add_argument(
        "--resume-possible-fulltext",
        action="store_true",
        help="第二阶段：从现有 screened.csv 中只抽 possible_candidate，使用 PMC-only 全文筛选，并输出 stage2 与 final 合并文件",
    )
    parser.add_argument(
        "--resume-sp-fulltext",
        action="store_true",
        help="第二阶段：从现有 screened.csv 中抽 strong+possible 候选，Strong 用 confirmation 模式（只在参数/证据得分≤1 时降级），Possible 用 confirm_parameter 宽松模式，以减少 FP",
    )
    return parser


if __name__ == "__main__":
    main()
