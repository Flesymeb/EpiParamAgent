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
    llm_model = init_llm_model()
    print(
        f"使用模型: {os.getenv('LLM_MODEL', 'gpt-4o-mini')}\n"
    )

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
                )
            )
            for paper in fulltext_ready:
                paper["fulltext_status"] = "screened"
                paper["fulltext_eligible"] = "done"
        saved_output, log_file, manifest_path = save_screening_outputs(
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
        print("✅ 全文筛选恢复完成!")
        print(f"{'='*80}")
        print(
            f"\n📊 结果: Strong {strong} | Possible {possible} | Unlikely {unlikely} | Errors {errors}"
        )
        print(f"📁 输出: {saved_output.name}")
        print(f"📋 详细报告: {log_file}\n")
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
                )
            )
            for paper in fulltext_ready:
                paper["fulltext_status"] = "screened"

    saved_output, log_file, manifest_path = save_screening_outputs(
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
    )

    strong = sum(1 for p in papers if p.get("llm_suggest") == "strong_candidate")
    possible = sum(1 for p in papers if p.get("llm_suggest") == "possible_candidate")
    unlikely = sum(1 for p in papers if p.get("llm_suggest") == "unlikely_candidate")
    errors = sum(1 for p in papers if p.get("llm_suggest") == "error")

    print(f"\n{'='*80}")
    print("✅ 筛选完成!")
    print(f"{'='*80}")
    print(
        f"\n📊 结果: Strong {strong} | Possible {possible} | Unlikely {unlikely} | Errors {errors}"
    )
    print(f"📁 输出: {saved_output.name}")
    print(f"📋 详细报告: {log_file}\n")
    print(f"🧾 Manifest: {manifest_path}\n")


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
    return parser


if __name__ == "__main__":
    main()
