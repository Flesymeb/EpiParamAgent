#!/usr/bin/env python3
"""
使用LLM批量并行筛选文献，根据标题和摘要判断是否符合研究问题

Usage:
  python .\scripts\screening_llm_batch.py --input ../langgraph_runs/ground_truth/search_v2/search_v2_raw.csv --output ../langgraph_runs/ground_truth/search_v2/test_screen/search_v2_screened.csv --ground-truth ../langgraph_runs/ground_truth/search_v2/search_v2_gt.csv --config V2 --auto-fulltext --batch-size 3
"""

import argparse
import csv
import os
import sys
import shutil
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
import re
import time
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, model_validator
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加src到path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "coding_sheet" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from mineru.config import load_mineru_config
from mineru.pdf_reader_mineru import extract_pdf_markdown_mineru

PROMPT_DIR = Path(__file__).resolve().parents[1] / "src" / "epidemiology" / "prompts"
SCREENING_SYSTEM_PROMPT = PROMPT_DIR / "screening_system.md"
SCREENING_USER_PROMPT = PROMPT_DIR / "screening_user.md"

FULLTEXT_CACHE_ROOT = Path(__file__).resolve().parents[2] / "paper_pool"
PDF_CACHE_DIR = FULLTEXT_CACHE_ROOT / "pdfs"
MD_CACHE_DIR = FULLTEXT_CACHE_ROOT / "markdown"


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
    overall_score: Optional[int] = Field(
        default=None,
        description="整体相关性评分 0-4，由系统自动计算加权平均（Disease 30% + Transmission 30% + Evidence 25% + Population 10% + Location 5%）",
    )
    overall_justification: str = Field(description="整体评估理由，2-3句话")

    @model_validator(mode="after")
    def calculate_overall_score(self):
        """自动计算加权平均overall_score"""
        weighted_score = (
            0.30 * self.disease_relevance.score
            + 0.30 * self.transmission_metric.score
            + 0.25 * self.original_evidence.score
            + 0.10 * self.population_relevance.score
            + 0.05 * self.location_relevance.score
        )
        self.overall_score = round(weighted_score)
        return self


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


def load_prompt_templates() -> tuple[str, str]:
    """Load system and user prompt templates from files."""
    system_text = SCREENING_SYSTEM_PROMPT.read_text(encoding="utf-8")
    user_text = SCREENING_USER_PROMPT.read_text(encoding="utf-8")
    return system_text, user_text


def ensure_fulltext_cache_dirs() -> None:
    """Create fixed full-text cache directories."""
    PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MD_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_pdf_fetcher_module():
    """Load pdf_fetcher module from tools/paper_fetch."""
    paper_fetch_dir = Path(__file__).resolve().parents[2] / "tools" / "paper_fetch"
    if str(paper_fetch_dir) not in sys.path:
        sys.path.insert(0, str(paper_fetch_dir))
    import pdf_fetcher as pdf_fetcher

    return pdf_fetcher


def download_pdfs_batch(
    pmids: List[str],
    pmid_overrides: Optional[dict[str, dict[str, str]]] = None,
) -> dict[str, dict[str, str]]:
    """Download PDFs for PMIDs into the fixed cache dir.

    Returns a mapping of PMID -> {"status": ..., "pdf_path": ...}.
    """
    ensure_fulltext_cache_dirs()
    pdf_fetcher = load_pdf_fetcher_module()
    extractor = pdf_fetcher.SciHubUrlExtractor()
    extractor.get_mirrors()

    results: dict[str, dict[str, str]] = {}
    pmid_overrides = pmid_overrides or {}
    for pmid in pmids:
        pmid = (pmid or "").strip()
        if not pmid:
            continue

        target_pdf = PDF_CACHE_DIR / f"PMID_{pmid}.pdf"
        if target_pdf.exists():
            results[pmid] = {"status": "downloaded", "pdf_path": str(target_pdf)}
            continue

        override = pmid_overrides.get(pmid, {})
        doi = (override.get("doi") or "").strip()
        pmcid_raw = (override.get("pmcid") or "").strip()
        pmcid = pmcid_raw
        if pmcid:
            pmcid = re.sub(r"^.*?(PMC\d+).*$", r"\1", pmcid, flags=re.IGNORECASE)
        resolved_doi = ""
        resolved_pmcid = ""
        if not pmcid or not doi:
            resolved_doi, resolved_pmcid = extractor._resolve_pmid(pmid)
            if not doi:
                doi = resolved_doi
            if not pmcid:
                pmcid = resolved_pmcid
        if pmcid:
            pmcid = re.sub(r"^.*?(PMC\d+).*$", r"\1", pmcid, flags=re.IGNORECASE)
        if pmcid_raw and pmcid_raw != pmcid:
            print(f"  [PMCID] normalized: {pmcid_raw} -> {pmcid}")
        if resolved_pmcid and not pmcid_raw:
            print(f"  [PMCID] resolved from PMID: {resolved_pmcid}")
        if not doi and not pmcid:
            results[pmid] = {"status": "no_id", "pdf_path": ""}
            continue

        if doi or pmcid:
            doi_display = doi or "N/A"
            pmcid_display = pmcid or "N/A"
            print(
                f"Resolving PMID: {pmid} | DOI: {doi_display} | PMCID: {pmcid_display}"
            )

        print("  Sci-Hub:")
        url_results, doi, pmcid = extractor.process_pmid(
            pmid,
            download_dir=PDF_CACHE_DIR,
            doi_override=doi,
            pmcid_override=pmcid,
        )
        pdf_path = None
        for info in url_results:
            local_path = info.get("local_path")
            if local_path and Path(local_path).exists():
                pdf_path = Path(local_path)
                break

        if pdf_path and pdf_path.exists():
            if pdf_path != target_pdf:
                if target_pdf.exists():
                    try:
                        pdf_path.unlink()
                    except Exception:
                        pass
                else:
                    try:
                        pdf_path.replace(target_pdf)
                    except Exception:
                        shutil.copyfile(pdf_path, target_pdf)
            results[pmid] = {"status": "downloaded", "pdf_path": str(target_pdf)}
        else:
            results[pmid] = {"status": "download_failed", "pdf_path": ""}

    return results


def convert_pdfs_to_markdown(
    pmid_to_pdf: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Convert cached PDFs to Markdown using MinerU.

    Returns a mapping of PMID -> {"status": ..., "md_path": ...}.
    """
    ensure_fulltext_cache_dirs()
    cfg = load_mineru_config()
    if not cfg.api_key:
        print("⚠️  MinerU API key missing; skipping full-text conversion.")
        return {
            pmid: {"status": "conversion_failed", "md_path": "", "error": "no_api_key"}
            for pmid in pmid_to_pdf.keys()
        }

    total_pdfs = sum(1 for info in pmid_to_pdf.values() if info.get("pdf_path"))
    if total_pdfs:
        print(f"开始全文转换 (MinerU): {total_pdfs} 篇 | 输出目录: {MD_CACHE_DIR}")
    results: dict[str, dict[str, str]] = {}
    converted = 0
    failed = 0
    cached = 0
    for pmid, info in pmid_to_pdf.items():
        pdf_path = info.get("pdf_path") or ""
        if not pdf_path:
            failed += 1
            results[pmid] = {"status": "conversion_failed", "md_path": ""}
            continue

        paper_dir = MD_CACHE_DIR / f"PMID_{pmid}"
        md_path = paper_dir / f"PMID_{pmid}.md"
        if md_path.exists() and md_path.stat().st_size > 0:
            results[pmid] = {"status": "converted", "md_path": str(md_path)}
            converted += 1
            cached += 1
            continue

        try:
            paper_dir.mkdir(parents=True, exist_ok=True)
            print(f"  [MinerU] 转换 PMID {pmid} ...")
            extracted = extract_pdf_markdown_mineru(
                Path(pdf_path),
                output_dir=paper_dir,
            )
            if extracted.markdown:
                md_path.write_text(extracted.markdown, encoding="utf-8")
                results[pmid] = {"status": "converted", "md_path": str(md_path)}
                converted += 1
                print(f"  [MinerU] 完成 PMID {pmid}")
            else:
                failed += 1
                results[pmid] = {
                    "status": "conversion_failed",
                    "md_path": "",
                    "error": "empty_markdown",
                }
                if not any(paper_dir.iterdir()):
                    paper_dir.rmdir()
        except Exception as exc:
            failed += 1
            results[pmid] = {
                "status": "conversion_failed",
                "md_path": "",
                "error": str(exc)[:200],
            }
            print(f"  [MinerU] 失败 PMID {pmid}: {str(exc)[:200]}")
            if paper_dir.exists() and not any(paper_dir.iterdir()):
                paper_dir.rmdir()

    if total_pdfs:
        print(f"全文转换完成: 成功 {converted} (缓存 {cached}) | 失败 {failed}")
    return results


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
    screening_config: Optional[Dict[str, Any]] = None,
    content_label: str = "Abstract",
    content_key: str = "Abstract",
    content_fallback: str = "(No abstract available. Please assess based on title only.)",
    system_template: Optional[str] = None,
    user_template: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    批量异步并行筛选文献

    Args:
        papers: 文献列表
        research_question: 研究问题
        llm_model: LLM模型实例
        batch_size: 每批并发处理的文献数量
        screening_config: 筛选配置字典（见screening_configs.py）

    Returns:
        添加了筛选结果的文献列表
    """
    # 默认配置（COVID-19变异株传播）
    default_config = {
        "research_question": research_question,
        "disease_focus": "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus) AND its (variant OR mutation OR lineage OR amino acid substitution)",
        "disease_exclude": "studies that focus solely on other diseases or wild-type only without variant comparison",
        "transmission_focus": "transmission metrics **related to the specific disease focus** (e.g., reproduction number, serial interval, attack rate, transmission probability)",
        "transmission_exclude": "studies that only discuss clinical outcomes, severity, or vaccine effectiveness without transmission quantification",
    }

    # 合并用户配置
    config = {**default_config, **(screening_config or {})}

    # 创建prompt模板（外置文件）
    if system_template is None or user_template is None:
        system_text, user_text = load_prompt_templates()
    else:
        system_text, user_text = system_template, user_template

    system_text = system_text.format(
        research_question=config["research_question"],
        disease_focus=config["disease_focus"],
        disease_exclude=config["disease_exclude"],
        transmission_focus=config["transmission_focus"],
        transmission_exclude=config["transmission_exclude"],
    )

    template = ChatPromptTemplate.from_messages(
        [("system", system_text), ("human", user_text)]
    )

    # 使用结构化输出
    structured_llm = llm_model.with_structured_output(ScreeningDecision)

    # 准备所有prompts
    all_prompts = []
    for paper in papers:
        title = paper.get("Title", "").strip()
        abstract = paper.get(content_key, "").strip()
        keywords = paper.get("Keywords", "").strip()

        # 如果没有摘要，使用特殊说明
        if not abstract:
            abstract = content_fallback

        # 如果没有keywords
        if not keywords:
            keywords = "(No keywords available)"

        prompt = template.format_messages(
            research_question=research_question,
            title=title,
            content_label=content_label,
            content=abstract,
            keywords=keywords,
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

    args = parser.parse_args()

    # 加载配置
    screening_config = None
    research_question = (
        "What are the reproduction numbers of different SARS-CoV-2 variants?"  # 默认值
    )
    if args.config:
        try:
            from screening_configs import (
                CONFIG_SERIAL_INTERVAL,
                CONFIG_COVID_VARIANTS,
                CONFIG_SUPERSPREADING,
                CONFIG_INFLUENZA_TRANSMISSION,
                CONFIG_MEASLES_TRANSMISSION,
                CONFIG_EBOLA_TRANSMISSION,
                CONFIG_TB_TRANSMISSION,
                CONFIG_GENERIC_INFECTIOUS_DISEASE,
                CONFIG_OUTBREAK_INVESTIGATION,
            )

            config_map = {
                "SERIAL_INTERVAL": CONFIG_SERIAL_INTERVAL,
                "CONFIG_SERIAL_INTERVAL": CONFIG_SERIAL_INTERVAL,
                "V1": CONFIG_SERIAL_INTERVAL,
                "COVID_VARIANTS": CONFIG_COVID_VARIANTS,
                "CONFIG_COVID_VARIANTS": CONFIG_COVID_VARIANTS,
                "V2": CONFIG_COVID_VARIANTS,
                "VARIANTS": CONFIG_COVID_VARIANTS,
                "SUPERSPREADING": CONFIG_SUPERSPREADING,
                "CONFIG_SUPERSPREADING": CONFIG_SUPERSPREADING,
                "V3": CONFIG_SUPERSPREADING,
                "INFLUENZA": CONFIG_INFLUENZA_TRANSMISSION,
                "CONFIG_INFLUENZA_TRANSMISSION": CONFIG_INFLUENZA_TRANSMISSION,
                "MEASLES": CONFIG_MEASLES_TRANSMISSION,
                "CONFIG_MEASLES_TRANSMISSION": CONFIG_MEASLES_TRANSMISSION,
                "EBOLA": CONFIG_EBOLA_TRANSMISSION,
                "CONFIG_EBOLA_TRANSMISSION": CONFIG_EBOLA_TRANSMISSION,
                "TB": CONFIG_TB_TRANSMISSION,
                "CONFIG_TB_TRANSMISSION": CONFIG_TB_TRANSMISSION,
                "GENERIC": CONFIG_GENERIC_INFECTIOUS_DISEASE,
                "CONFIG_GENERIC_INFECTIOUS_DISEASE": CONFIG_GENERIC_INFECTIOUS_DISEASE,
                "OUTBREAK": CONFIG_OUTBREAK_INVESTIGATION,
                "CONFIG_OUTBREAK_INVESTIGATION": CONFIG_OUTBREAK_INVESTIGATION,
            }
            screening_config = config_map.get(args.config.upper())
            if screening_config:
                # 从配置中提取研究问题
                if "research_question" in screening_config:
                    research_question = screening_config["research_question"]
                print(f"✓ 使用配置: {args.config}")
                print(f"  Research question: {research_question}")
                print(f"  Disease focus: {screening_config['disease_focus'][:80]}...")
                print(
                    f"  Transmission focus: {screening_config['transmission_focus'][:80]}...\n"
                )
            else:
                print(
                    f"⚠ 未找到配置 '{args.config}'，使用默认配置（COVID-19 variants）\n"
                )
        except ImportError as e:
            print(f"⚠ 无法加载配置文件: {e}")
            print("使用默认配置（COVID-19 variants）\n")

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

    system_template, user_template = load_prompt_templates()

    papers_with_abstract = []
    papers_without_abstract = []
    fulltext_errors = []
    for paper in papers:
        abstract = (paper.get("Abstract") or "").strip()
        if abstract:
            papers_with_abstract.append(paper)
            paper["screening_stage"] = "title_abstract"
        else:
            papers_without_abstract.append(paper)
            paper["screening_stage"] = "pending_fulltext"
            paper["fulltext_status"] = "pending"
            paper["fulltext_path"] = ""
            paper["llm_suggest"] = "needs_full_text"

    print(
        f"筛选分流: title+abstract={len(papers_with_abstract)} | full-text={len(papers_without_abstract)}\n"
    )

    # 异步并发筛选 - 有摘要
    if papers_with_abstract:
        asyncio.run(
            screen_papers_batch_async(
                papers_with_abstract,
                research_question,
                llm_model,
                batch_size,
                screening_config,
                content_label="Abstract",
                content_key="Abstract",
                content_fallback="(No abstract available. Please assess based on title only.)",
                system_template=system_template,
                user_template=user_template,
            )
        )

    # 自动全文筛选 - 无摘要
    if args.auto_fulltext and papers_without_abstract:
        print(f"\n开始全文筛选流程 ({len(papers_without_abstract)} 篇)...")
        ensure_fulltext_cache_dirs()

        pmids = []
        pmid_overrides = {}
        for paper in papers_without_abstract:
            pmid = (paper.get("PMID") or "").strip()
            if pmid:
                pmids.append(pmid)
                doi = (paper.get("DOI") or paper.get("doi") or "").strip()
                pmcid = (paper.get("PMCID") or paper.get("pmcid") or "").strip()
                if doi or pmcid:
                    pmid_overrides[pmid] = {"doi": doi, "pmcid": pmcid}
            else:
                paper["fulltext_status"] = "no_pmid"
                fulltext_errors.append(
                    {
                        "pmid": "",
                        "title": paper.get("Title", ""),
                        "status": "no_pmid",
                        "detail": "missing PMID",
                    }
                )

        print(f"开始全文下载 (PDF) | 输出目录: {PDF_CACHE_DIR}")
        pdf_results = download_pdfs_batch(pmids, pmid_overrides)
        md_results = convert_pdfs_to_markdown(pdf_results)

        fulltext_ready = []
        for paper in papers_without_abstract:
            pmid = (paper.get("PMID") or "").strip()
            if not pmid:
                continue
            pdf_info = pdf_results.get(pmid, {})
            md_info = md_results.get(pmid, {})

            if pdf_info.get("status") != "downloaded":
                status = pdf_info.get("status", "download_failed")
                paper["fulltext_status"] = status
                fulltext_errors.append(
                    {
                        "pmid": pmid,
                        "title": paper.get("Title", ""),
                        "status": status,
                        "detail": pdf_info.get("error", ""),
                    }
                )
                continue

            if md_info.get("status") != "converted":
                status = md_info.get("status", "conversion_failed")
                paper["fulltext_status"] = status
                fulltext_errors.append(
                    {
                        "pmid": pmid,
                        "title": paper.get("Title", ""),
                        "status": status,
                        "detail": md_info.get("error", ""),
                    }
                )
                continue

            md_path = md_info.get("md_path", "")
            paper["fulltext_path"] = md_path
            paper["fulltext_status"] = "converted"
            paper["screening_stage"] = "full_text"
            try:
                paper["fulltext_markdown"] = Path(md_path).read_text(encoding="utf-8")
                fulltext_ready.append(paper)
            except Exception:
                paper["fulltext_status"] = "read_failed"
                fulltext_errors.append(
                    {
                        "pmid": pmid,
                        "title": paper.get("Title", ""),
                        "status": "read_failed",
                        "detail": "read markdown failed",
                    }
                )

        downloaded = sum(
            1 for v in pdf_results.values() if v.get("status") == "downloaded"
        )
        converted = sum(
            1 for v in md_results.values() if v.get("status") == "converted"
        )
        print(f"全文筛选入选: {len(fulltext_ready)}/{len(papers_without_abstract)}")

        if fulltext_ready:
            print(f"开始全文筛选 (full-text): {len(fulltext_ready)} 篇...")
            asyncio.run(
                screen_papers_batch_async(
                    fulltext_ready,
                    research_question,
                    llm_model,
                    batch_size,
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
        for field in ["screening_stage", "fulltext_status", "fulltext_path"]:
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

    for paper in papers:
        paper.pop("fulltext_markdown", None)

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
    report_lines.append(
        "Full-text: "
        f"need_fulltext={len(papers_without_abstract)} | "
        f"screened={len(fulltext_ready) if 'fulltext_ready' in locals() else 0}"
    )

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
    if fulltext_errors:
        report_lines.append("\n" + "=" * 80)
        report_lines.append("Full-text failures")
        report_lines.append("=" * 80)
        for idx, item in enumerate(fulltext_errors, 1):
            report_lines.append(
                f"[{idx:02d}] PMID={item.get('pmid') or 'N/A'} | {item.get('status')} | {item.get('title')}"
            )
            detail = (item.get("detail") or "").strip()
            if detail:
                report_lines.append(f"     detail: {detail}")

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
