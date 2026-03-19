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
sys.path.insert(0, str(BASE_DIR / "scripts" / "tools"))

from common.config import load_runtime_env
from screening.fulltext_pipeline import MD_CACHE_DIR

load_runtime_env(module_hint="literature_search")


def main() -> None:
    args = _build_arg_parser().parse_args()
    from screening.config_resolution import resolve_cli_paths, resolve_screening_config
    from screening.fulltext_pipeline import prepare_fulltext_candidates
    from screening.llm_screening import (
        init_llm_model,
        load_ground_truth_pmids,
        load_prompt_templates,
        screen_papers_batch_async,
    )
    from screening.reporting import save_screening_outputs
    from screening.staging import (
        annotate_ground_truth,
        partition_papers,
        print_ground_truth_warning,
        print_stage_split,
    )

    screening_config, research_question = resolve_screening_config(args.config)
    input_file, output_file, gt_file = resolve_cli_paths(
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
        f"使用模型: {os.getenv('LLM_PROVIDER', 'openai')}/{os.getenv('LLM_MODEL', 'gpt-4o-mini')}\n"
    )

    print(f"从 {input_file} 读取数据...\n")
    with open(input_file, "r", encoding="utf-8-sig") as f:
        papers = list(csv.DictReader(f))
    print(f"读取了 {len(papers)} 条记录\n")

    gt_count = annotate_ground_truth(papers, gt_pmids)
    print("=" * 80)
    print(f"研究问题: {research_question}")
    print("=" * 80)

    system_template, user_template = load_prompt_templates()
    stage_state = partition_papers(
        papers=papers,
        auto_fulltext=args.auto_fulltext,
        fulltext_only=args.fulltext_only,
    )

    print_stage_split(
        papers_with_abstract=stage_state["papers_with_abstract"],
        papers_without_abstract=stage_state["papers_without_abstract"],
        auto_fulltext=args.auto_fulltext,
        fulltext_only=args.fulltext_only,
    )

    if args.fulltext_only:
        print("⚠️  fulltext-only 模式：跳过 Title/Abstract 阶段")
        stage_state["papers_with_abstract"] = []

    if stage_state["papers_with_abstract"]:
        fallback_text = "(No abstract available. Please assess based on title only.)"
        if not args.auto_fulltext and not args.fulltext_only:
            fallback_text = (
                "(No abstract available. Be more lenient; assess based on title and keywords.)"
            )

        print("\n" + "=" * 80)
        print("阶段: Title + Abstract screening")
        print("=" * 80 + "\n")
        asyncio.run(
            screen_papers_batch_async(
                stage_state["papers_with_abstract"],
                research_question,
                llm_model,
                batch_size,
                batch_concurrency,
                screening_config,
                content_label="Abstract",
                content_key="Abstract",
                content_fallback=fallback_text,
                system_template=system_template,
                user_template=user_template,
            )
        )

    if args.fulltext_only:
        args.auto_fulltext = True

    fulltext_ready: list[dict[str, Any]] = []
    if args.auto_fulltext and (
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
            print(f"开始全文筛选 (full-text): {len(fulltext_ready)} 篇...")
            asyncio.run(
                screen_papers_batch_async(
                    fulltext_ready,
                    research_question,
                    llm_model,
                    batch_size,
                    batch_concurrency,
                    screening_config,
                    content_label="Full-text content (Markdown)",
                    content_key="fulltext_markdown",
                    content_fallback="(Full-text content unavailable.)",
                    system_template=system_template,
                    user_template=user_template,
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
        config_name=args.config,
        auto_fulltext=bool(args.auto_fulltext),
        fulltext_only=bool(args.fulltext_only),
        use_multidim=bool(args.use_multidim),
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
    parser.add_argument(
        "--input",
        type=str,
        default="../langgraph_runs/ground_truth/search_v2_with_abstracts.csv",
        help="输入CSV文件路径",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="../langgraph_runs/ground_truth/search_v2_screened_v3.csv",
        help="输出CSV文件路径",
    )
    parser.add_argument(
        "--ground-truth",
        type=str,
        default="../langgraph_runs/ground_truth/search_v2_gt.csv",
        help="Ground truth CSV文件路径",
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
        "--config",
        type=str,
        default=None,
        help="筛选配置名称 (如 'CONFIG_INFLUENZA_TRANSMISSION'，见screening_configs.py)",
    )
    parser.add_argument(
        "--use-multidim",
        action="store_true",
        help="使用多维度评分（此参数保留但不影响功能）",
    )
    parser.add_argument(
        "--auto-fulltext",
        action="store_true",
        help="无摘要文献自动下载全文并进行筛选",
    )
    return parser


if __name__ == "__main__":
    main()
