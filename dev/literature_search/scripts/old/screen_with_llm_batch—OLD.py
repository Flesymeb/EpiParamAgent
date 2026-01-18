#!/usr/bin/env python3
"""
使用LLM批量并行筛选文献，根据标题和摘要判断是否符合研究问题
"""

import argparse
import csv
import os
import sys
from datetime import datetime

# Set CSV field size limit to maximum possible value
try:
    csv.field_size_limit(sys.maxsize)
except (AttributeError, ValueError, OverflowError):
    try:
        csv.field_size_limit(2**31 - 1)  # 2GB fallback
    except (AttributeError, ValueError, OverflowError):
        pass
import json
import time
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加src到path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate


class DimensionAssessment(BaseModel):
    """单个维度的相关性评估"""

    score: int = Field(
        description="相关性评分 0-4 (0=不相关, 1=基本不相关, 2=不确定/可能相关, 3=比较相关, 4=高度相关)"
    )
    justification: str = Field(description="简要理由，1-2句话")


class ScreeningDecision(BaseModel):
    """LLM多维度相关性评估的结构化输出"""

    # 各维度评估
    disease_relevance: DimensionAssessment = Field(
        description="疾病相关性: 是否研究目标疾病(COVID-19/SARS-CoV-2)"
    )
    population_relevance: DimensionAssessment = Field(
        description="人群相关性: 是否关注人类（非纯动物或体外研究）"
    )
    location_relevance: DimensionAssessment = Field(
        description="地理相关性: 是否在真实地理环境中进行"
    )
    original_evidence: DimensionAssessment = Field(
        description="原始数据: 是否报告原始经验数据（非综述等）"
    )
    transmission_metric: DimensionAssessment = Field(
        description="传播指标: 是否报告传播强度或再生数相关指标"
    )

    # 整体评估
    llm_suggest: str = Field(
        description="strong_candidate / possible_candidate / unlikely_candidate"
    )
    overall_score: int = Field(
        description="整体相关性评分 0-4 (0=不相关, 1=基本不相关, 2=不确定, 3=比较相关, 4=高度相关)"
    )
    overall_justification: str = Field(description="整体评估理由，2-3句话")


def load_ground_truth_pmids(gt_file: Path) -> set:
    """从ground truth CSV加载PMIDs"""
    if not gt_file.exists():
        return set()

    gt_pmids = set()
    with open(gt_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pmid = None
            for key in ["PMID", "\ufeffPMID"]:
                if key in row:
                    pmid_val = row[key].strip()
                    if pmid_val and pmid_val.isdigit():
                        pmid = pmid_val
                        break
            if pmid:
                gt_pmids.add(pmid)
    return gt_pmids


def init_llm_model() -> Any:
    """初始化LLM模型"""
    llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    api_base = os.getenv("OPENAI_BASE_URL") or os.getenv(
        "OPENAI_API_BASE", "https://api.openai.com/v1"
    )
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")

    if not api_key:
        raise ValueError(
            "API key not found. Please set OPENAI_API_KEY or LLM_API_KEY in .env file"
        )

    print(f"API Base: {api_base}")
    print(f"Model: {llm_model}\n")

    # 返回ChatOpenAI实例（不使用client参数）
    return ChatOpenAI(
        model=llm_model,
        temperature=0,
        api_key=api_key,
        base_url=api_base,
        max_retries=3,  # Built-in retries for connection issues
        request_timeout=60,  # Timeout
    )


async def invoke_with_retry_async(llm, prompt, max_retries=3, delay=1.0):
    """带重试机制的异步单次调用"""
    last_exception = None
    for attempt in range(max_retries):
        try:
            return await llm.ainvoke(prompt)
        except Exception as e:
            last_exception = e
            error_str = str(e)

            # Check for specific "empty response" or parsing errors which are transient
            is_parsing_error = "parsed" in error_str or "OutputParserException" in str(
                type(e)
            )
            is_length_error = "context_length_exceeded" in error_str

            if is_length_error:
                print(f"      ⚠️ Context length exceeded. Skipping retry.")
                raise e  # Don't retry length errors

            if attempt < max_retries - 1:
                print(
                    f"      ⚠️ API glitch (attempt {attempt+1}/{max_retries}): {error_str[:100]}... Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                print(f"      ❌ API failed after {max_retries} attempts.")

    raise last_exception if last_exception else Exception("Unknown error in retry loop")


async def screen_papers_batch_async(
    papers: List[Dict[str, Any]],
    research_question: str,
    llm_model: Any,
    batch_size: int = 20,
) -> List[Dict[str, Any]]:
    """
    批量异步并行筛选文献

    Args:
        papers: 文献列表
        research_question: 研究问题
        llm_model: LLM模型实例
        batch_size: 每批并发处理的文献数量

    Returns:
        添加了筛选结果的文献列表
    """
    # 创建prompt模板
    system_text = """You are assisting in the screening of academic papers for a systematic review in epidemiology.

Your task is NOT to make a final inclusion or exclusion decision.
Instead, you should assess the relevance of each study across multiple predefined dimensions and provide a structured relevance annotation.

Assess each study based ONLY on the title and abstract.

### Core Inclusion Criteria (Relevance Dimensions):

A study is considered potentially relevant if it meets all core criteria below.

1. **Disease relevance (Variant-specific focus)**
The study must explicitly investigate SARS-CoV-2 **variants/lineages** and their transmission differences.

**Score 4**: Named variants (Alpha, Delta, Omicron, B.1.1.7, etc.) with transmission comparison or variant-specific estimates.
**Score 3**: Lineages/clades (e.g., "lineage B.1.1.33") OR early 2020 phylogenetic studies comparing distinct strains with reproduction numbers.
**Score 2**: General COVID-19 with R0/Re but NO variant differentiation (e.g., "R0 of SARS-CoV-2 in population X" from early 2020).
**Score 1**: COVID-19 study without transmission focus (vaccines, clinical outcomes, diagnostics only).
**Score 0**: Not about COVID-19/SARS-CoV-2.

**CRITICAL**: Wild-type/original strain ONLY studies (without variant comparison) should score ≤2.

2. **Population relevance**
The study focuses on humans (general population or predefined subgroups).
Exclude studies that are purely animal or in vitro.

3. **Location relevance**
Studies conducted in any geographic region are eligible.
Note: Some research questions may specify geographic restrictions - assess based on the research question provided.

4. **Original empirical evidence**
The study reports or estimates original empirical data.
Exclude those without original data: reviews, meta-analyses, editorials, commentaries, perspectives, and letters that do not report new data.
Exclude theoretical models/simulations that do not report new data (unless calibrated with real-world data reported in the abstract).
Exclude case reports with less than 2 cases.

5. **Transmission-related content (Variant-specific metrics)**
The study reports transmission metrics **related to variants**:

**Score 4**: Numerical R0/Re/Rt values with CIs, explicitly for variants or comparing variants.
**Score 3**: Quantitative variant-specific transmission metrics (fitness advantage %, growth rate, doubling time, SAR comparison), OR methods state R estimation for variants.
**Score 2**: Transmission metrics mentioned but unclear if variant-specific, OR qualitative comparison ("more transmissible") with some data.
**Score 1**: Only vague statements ("highly transmissible") without quantification.
**Score 0**: No transmission-related content.

**CRITICAL**: If the study only reports R0 for original/wild-type SARS-CoV-2 (without variant context), score should be ≤2, not 3-4.

Exclude studies that only discuss clinical outcomes, severity, or vaccine effectiveness without transmission quantification.

### For EACH dimension:
- Provide a relevance score using a 5-point scale:
  - **0**: Not relevant / clearly does not meet criterion
  - **1**: Mostly not relevant / unlikely to meet criterion
  - **2**: Uncertain / possibly relevant / insufficient information
  - **3**: Moderately relevant / likely meets criterion
  - **4**: Highly relevant / clearly meets criterion
- Provide a brief justification (1–2 sentences)

### Overall assessment rules:
Based on the above dimensions, provide an overall **LLM suggestion** following these strict criteria:

**strong_candidate** (High confidence - all 3 must be met):
  1. Disease (variant focus) ≥ 3  [REQUIRED]
  2. Transmission (variant metrics) ≥ 3  [REQUIRED]
  3. Evidence (original data) ≥ 3  [REQUIRED]
  4. Population ≥ 2 AND Location ≥ 2

**possible_candidate** (Moderate confidence - relaxed thresholds):
  1. Disease ≥ 3 AND Transmission ≥ 3  [BOTH REQUIRED]
  2. Evidence ≥ 2  [At least some original analysis]
  3. Any score on Population/Location
  
**unlikely_candidate** (Low confidence - any one triggers):
  - Disease < 3  [No clear variant focus]
  - Transmission < 3  [No variant-specific transmission data]
  - Evidence = 0  [Pure review/commentary]

**Key principle**: Disease and Transmission are MANDATORY dimensions. A paper without variant-specific transmission data cannot be strong/possible, regardless of other scores.

When information is insufficient, prefer "unclear" (Score 2) over "not relevant" (Score 0).
Prioritize sensitivity over specificity at this stage.
"""

    user_text = """Research question: {research_question}

Title: {title}
Abstract: {abstract}

Assess the relevance of this paper across all dimensions and provide structured annotations."""

    template = ChatPromptTemplate.from_messages(
        [("system", system_text), ("human", user_text)]
    )

    # 使用结构化输出
    structured_llm = llm_model.with_structured_output(ScreeningDecision)

    # 准备所有prompts
    all_prompts = []
    for paper in papers:
        title = paper.get("Title", "").strip()
        abstract = paper.get("Abstract", "").strip()

        # 如果没有摘要，使用特殊说明
        if not abstract:
            abstract = "(No abstract available. Please assess based on title only.)"

        prompt = template.format_messages(
            research_question=research_question, title=title, abstract=abstract
        )
        all_prompts.append((paper, prompt))

    print(f"\n准备筛选 {len(all_prompts)} 篇文献（并发数={batch_size}）...\n")

    # 异步并发处理
    for i in range(0, len(all_prompts), batch_size):
        batch = all_prompts[i : i + batch_size]
        batch_prompts = [prompt for _, prompt in batch]
        batch_papers = [paper for paper, _ in batch]

        batch_num = i // batch_size + 1
        total_batches = (len(all_prompts) - 1) // batch_size + 1

        print(f"处理批次 {batch_num}/{total_batches} ({len(batch)} 篇)...")

        try:
            # 异步并发调用LLM
            tasks = [
                invoke_with_retry_async(structured_llm, prompt)
                for prompt in batch_prompts
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 保存结果 (处理可能的异常)
            for paper, result in zip(batch_papers, results):
                if isinstance(result, Exception):
                    print(
                        f"  ⚠️ 单篇失败 PMID={paper.get('PMID', 'N/A')}: {str(result)[:100]}"
                    )
                    paper["llm_suggest"] = "error"
                    paper["overall_score"] = 0
                    paper["overall_justification"] = f"LLM error: {str(result)[:200]}"
                    for dimension in [
                        "disease",
                        "population",
                        "location",
                        "evidence",
                        "transmission",
                    ]:
                        paper[f"{dimension}_score"] = 0
                        paper[f"{dimension}_justification"] = "Error"
                    continue

                # 整体评估
                paper["llm_suggest"] = result.llm_suggest
                paper["overall_score"] = result.overall_score
                paper["overall_justification"] = result.overall_justification

                # 疾病相关性
                paper["disease_score"] = result.disease_relevance.score
                paper["disease_justification"] = result.disease_relevance.justification

                # 人群相关性
                paper["population_score"] = result.population_relevance.score
                paper["population_justification"] = (
                    result.population_relevance.justification
                )

                # 地理相关性
                paper["location_score"] = result.location_relevance.score
                paper["location_justification"] = (
                    result.location_relevance.justification
                )

                # 原始数据
                paper["evidence_score"] = result.original_evidence.score
                paper["evidence_justification"] = result.original_evidence.justification

                # 传播指标
                paper["transmission_score"] = result.transmission_metric.score
                paper["transmission_justification"] = (
                    result.transmission_metric.justification
                )

            strong_count = sum(
                1
                for _, r in zip(batch_papers, results)
                if not isinstance(r, Exception) and r.llm_suggest == "strong_candidate"
            )
            possible_count = sum(
                1
                for _, r in zip(batch_papers, results)
                if not isinstance(r, Exception)
                and r.llm_suggest == "possible_candidate"
            )
            error_count = sum(1 for r in results if isinstance(r, Exception))
            print(
                f"  批次结果: {strong_count} strong, {possible_count} possible, {len(batch) - strong_count - possible_count - error_count} unlikely, {error_count} errors"
            )

        except Exception as e:
            print(f"  批次处理失败: {str(e)[:200]}...")
            print(f"  尝试单篇重新处理 (with async retries)...")

            # 逐篇异步重试
            for paper, prompt in batch:
                try:
                    # 使用带重试的异步调用
                    result = await invoke_with_retry_async(structured_llm, prompt)

                    # 保存结果
                    paper["llm_suggest"] = result.llm_suggest
                    paper["overall_score"] = result.overall_score
                    paper["overall_justification"] = result.overall_justification
                    paper["disease_score"] = result.disease_relevance.score
                    paper["disease_justification"] = (
                        result.disease_relevance.justification
                    )
                    paper["population_score"] = result.population_relevance.score
                    paper["population_justification"] = (
                        result.population_relevance.justification
                    )
                    paper["location_score"] = result.location_relevance.score
                    paper["location_justification"] = (
                        result.location_relevance.justification
                    )
                    paper["evidence_score"] = result.original_evidence.score
                    paper["evidence_justification"] = (
                        result.original_evidence.justification
                    )
                    paper["transmission_score"] = result.transmission_metric.score
                    paper["transmission_justification"] = (
                        result.transmission_metric.justification
                    )

                except Exception as e2:
                    print(
                        f"    单篇失败 PMID={paper.get('PMID', 'N/A')}: {str(e2)[:100]}"
                    )
                    paper["llm_suggest"] = "error"
                    paper["overall_score"] = 0
                    paper["overall_justification"] = f"LLM error: {str(e2)[:200]}"
                    for dimension in [
                        "disease",
                        "population",
                        "location",
                        "evidence",
                        "transmission",
                    ]:
                        paper[f"{dimension}_score"] = 0
                        paper[f"{dimension}_justification"] = "Error"

            # 统计本批次结果
            strong_count = sum(
                1 for p in batch_papers if p.get("llm_suggest") == "strong_candidate"
            )
            possible_count = sum(
                1 for p in batch_papers if p.get("llm_suggest") == "possible_candidate"
            )
            error_count = sum(
                1 for p in batch_papers if p.get("llm_suggest") == "error"
            )
            print(
                f"  重试后结果: {strong_count} strong, {possible_count} possible, {len(batch) - strong_count - possible_count - error_count} unlikely, {error_count} errors"
            )

        # 短暂延迟避免速率限制
        await asyncio.sleep(0.2)

    return papers


def main():
    """主函数"""
    # 解析命令行参数
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
    parser.add_argument(
        "--batch-size", type=int, default=20, help="每批并发处理的文献数量"
    )
    parser.add_argument(
        "--use-multidim",
        action="store_true",
        help="使用多维度评分（此参数保留但不影响功能）",
    )

    args = parser.parse_args()

    # 研究问题
    research_question = (
        "What are the reproduction numbers of different SARS-CoV-2 variants?"
    )

    # 转换为绝对路径
    script_dir = Path(__file__).parent
    input_file = (script_dir / args.input).resolve()
    output_file = (script_dir / args.output).resolve()
    gt_file = (script_dir / args.ground_truth).resolve()
    batch_size = args.batch_size

    if not input_file.exists():
        print(f"错误: 找不到输入文件 {input_file}")
        print("请先运行 fetch_pubmed_abstracts.py 获取摘要")
        return

    # 加载ground truth PMIDs
    gt_pmids = load_ground_truth_pmids(gt_file)
    if gt_pmids:
        print(f"✓ 加载了 {len(gt_pmids)} 篇Ground Truth论文\n")
    else:
        print(f"⚠️  未找到Ground Truth文件: {gt_file}\n")

    # 初始化LLM
    print("初始化LLM模型...")
    llm_model = init_llm_model()
    print(
        f"使用模型: {os.getenv('LLM_PROVIDER', 'openai')}/{os.getenv('LLM_MODEL', 'gpt-4o-mini')}\n"
    )

    # 读取数据
    print(f"从 {input_file} 读取数据...\n")
    papers = []
    with open(input_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        papers = list(reader)

    print(f"读取了 {len(papers)} 条记录\n")

    # 添加ground truth标记
    if gt_pmids:
        for paper in papers:
            pmid = paper.get("PMID", "").strip()
            paper["is_ground_truth"] = "✓" if pmid in gt_pmids else ""
        gt_count = sum(1 for p in papers if p.get("is_ground_truth") == "✓")
        print(f"其中包含 {gt_count}/{len(gt_pmids)} 篇Ground Truth\n")
    print("=" * 80)
    print(f"研究问题: {research_question}")
    print("=" * 80)

    # 异步并发筛选 - 使用命令行参数的batch_size
    papers = asyncio.run(
        screen_papers_batch_async(papers, research_question, llm_model, batch_size)
    )

    # 保存结果
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # 添加筛选相关的列
    if papers:
        fieldnames = list(papers[0].keys())

        # 确保is_ground_truth列在PMID后面（如果存在）
        if "is_ground_truth" in fieldnames:
            fieldnames.remove("is_ground_truth")
            if "PMID" in fieldnames:
                pmid_idx = fieldnames.index("PMID")
                fieldnames.insert(pmid_idx + 1, "is_ground_truth")
            else:
                fieldnames.insert(0, "is_ground_truth")

        # 整体评估字段
        for field in ["llm_suggest", "overall_score", "overall_justification"]:
            if field not in fieldnames:
                fieldnames.append(field)
        # 各维度评估字段
        for dimension in [
            "disease",
            "population",
            "location",
            "evidence",
            "transmission",
        ]:
            for suffix in ["score", "justification"]:
                field = f"{dimension}_{suffix}"
                if field not in fieldnames:
                    fieldnames.append(field)

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(papers)

    # 统计
    strong = [p for p in papers if p.get("llm_suggest") == "strong_candidate"]
    possible = [p for p in papers if p.get("llm_suggest") == "possible_candidate"]
    unlikely = [p for p in papers if p.get("llm_suggest") == "unlikely_candidate"]
    errors = [p for p in papers if p.get("llm_suggest") == "error"]

    # 生成时间戳和日志目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = output_file.parent / "screening_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"screening_report_{timestamp}.txt"

    # 生成详细统计报告
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("LLM文献筛选详细报告")
    report_lines.append("=" * 80)
    report_lines.append(f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"研究问题: {research_question}")
    report_lines.append(f"输入文件: {input_file}")
    report_lines.append(f"输出文件: {output_file}")
    report_lines.append(
        f"模型配置: {os.getenv('LLM_PROVIDER', 'openai')}/{os.getenv('LLM_MODEL', 'gpt-4o-mini')}"
    )
    report_lines.append(f"批处理大小: {batch_size}")
    report_lines.append("\n" + "=" * 80)
    report_lines.append("📊 筛选结果统计")
    report_lines.append("=" * 80)
    report_lines.append("\n┌─────────────────────────┬──────────┬──────────┐")
    report_lines.append("│ 类别                     │   数量    │   占比    │")
    report_lines.append("├─────────────────────────┼──────────┼──────────┤")
    report_lines.append(
        f"│ 💪 Strong candidates     │   {len(strong):4d}   │  {len(strong)/len(papers)*100:5.1f}%  │"
    )
    report_lines.append(
        f"│ 🤔 Possible candidates   │   {len(possible):4d}   │  {len(possible)/len(papers)*100:5.1f}%  │"
    )
    report_lines.append(
        f"│ 😐 Unlikely candidates   │   {len(unlikely):4d}   │  {len(unlikely)/len(papers)*100:5.1f}%  │"
    )
    report_lines.append(
        f"│ ⚠️  Errors               │   {len(errors):4d}   │  {len(errors)/len(papers)*100:5.1f}%  │"
    )
    report_lines.append("├─────────────────────────┼──────────┼──────────┤")
    report_lines.append(
        f"│ 📝 总记录数              │   {len(papers):4d}   │ 100.0%   │"
    )
    report_lines.append("└─────────────────────────┴──────────┴──────────┘")

    # 统计各维度的评分分布
    report_lines.append("\n" + "=" * 80)
    report_lines.append("📊 各维度相关性评分统计 (0-4分制)")
    report_lines.append("=" * 80)
    dimensions = [
        ("disease", "Disease (Variant)"),
        ("population", "Population"),
        ("location", "Location"),
        ("evidence", "Evidence"),
        ("transmission", "Transmission"),
    ]

    report_lines.append(
        "\n┌─────────────────┬─────────┬──────────┬────────────────────────────────┐"
    )
    report_lines.append(
        "│ 维度             │ 平均分  │ 高相关率  │ 评分分布 (0/1/2/3/4)            │"
    )
    report_lines.append(
        "├─────────────────┼─────────┼──────────┼────────────────────────────────┤"
    )

    for dim, label in dimensions:
        score_field = f"{dim}_score"

        # 统计各分数段
        score_0 = sum(1 for p in papers if str(p.get(score_field, "")).strip() == "0")
        score_1 = sum(1 for p in papers if str(p.get(score_field, "")).strip() == "1")
        score_2 = sum(1 for p in papers if str(p.get(score_field, "")).strip() == "2")
        score_3 = sum(1 for p in papers if str(p.get(score_field, "")).strip() == "3")
        score_4 = sum(1 for p in papers if str(p.get(score_field, "")).strip() == "4")

        # 计算平均分数
        valid_scores = [
            int(p.get(score_field, 0))
            for p in papers
            if p.get(score_field) not in ["", None]
        ]
        avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0

        # 统计高相关（3-4分）的比例
        high_relevance = sum(1 for s in valid_scores if s >= 3)
        high_pct = (high_relevance / len(valid_scores) * 100) if valid_scores else 0

        report_lines.append(
            f"│ {label:15s} │  {avg_score:4.2f}  │  {high_pct:5.1f}%  │ {score_0:2d}/{score_1:2d}/{score_2:2d}/{score_3:2d}/{score_4:2d}                 │"
        )

    report_lines.append(
        "└─────────────────┴─────────┴──────────┴────────────────────────────────┘"
    )

    # Strong candidates 列表
    if strong:
        report_lines.append("\n" + "=" * 80)
        report_lines.append(f"💪 Strong Candidates ({len(strong)} 篇)")
        report_lines.append("=" * 80)
        high_relevance = sorted(
            strong, key=lambda x: int(x.get("overall_score", 0)), reverse=True
        )

        for i, paper in enumerate(high_relevance, 1):
            report_lines.append(
                f"\n{i}. PMID: {paper.get('PMID', 'N/A')} [Score: {paper.get('overall_score')}/4]"
            )
            report_lines.append(f"   Title: {paper.get('Title', 'N/A')}")
            report_lines.append(
                f"   Overall: {paper.get('overall_justification', 'N/A')}"
            )
            report_lines.append(
                f"   维度评分: D={paper.get('disease_score')} P={paper.get('population_score')} L={paper.get('location_score')} E={paper.get('evidence_score')} T={paper.get('transmission_score')}"
            )

    # 保存详细报告到文件
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    # 简洁的控制台输出
    print(f"\n{'='*80}")
    print(f"✅ 筛选完成!")
    print(f"{'='*80}")
    print(
        f"\n📊 结果: Strong {len(strong)} | Possible {len(possible)} | Unlikely {len(unlikely)} | Errors {len(errors)}"
    )
    print(f"📁 输出: {output_file.name}")
    print(f"📋 详细报告: {log_file}\n")


if __name__ == "__main__":
    main()
