"""LLM-powered screening helpers for title/abstract/full-text stages."""

from __future__ import annotations

import asyncio
import csv
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from common.config import load_llm_config

from .decision_models import (
    ScreeningDecision,
    classify_screening_decision,
    resolve_stage_mode,
)

BASE_DIR = Path(__file__).resolve().parents[2]
PROMPT_DIR = BASE_DIR / "src" / "epidemiology" / "prompts"
PROMPT_FILES = {
    "title_abstract": (
        PROMPT_DIR / "screening_system_title_abstract.md",
        PROMPT_DIR / "screening_user_title_abstract.md",
    ),
    "title_only": (
        PROMPT_DIR / "screening_system_title_only.md",
        PROMPT_DIR / "screening_user_title_only.md",
    ),
    "full_text": (
        PROMPT_DIR / "screening_system_full_text.md",
        PROMPT_DIR / "screening_user_full_text.md",
    ),
}


def load_ground_truth_pmids(gt_file: Path) -> set[str]:
    """Load PMID values from a ground-truth CSV file."""
    if not gt_file.exists():
        return set()

    gt_pmids: set[str] = set()
    with open(gt_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pmid = None
            for key in row.keys():
                if key is None:
                    continue
                key_norm = key.lower()
                if key_norm in ("pmid", "gt_pmid") or key == "\ufeffPMID":
                    pmid_val = (row.get(key) or "").strip()
                    if pmid_val and pmid_val.isdigit():
                        pmid = pmid_val
                        break
            if pmid:
                gt_pmids.add(pmid)
    return gt_pmids


def init_llm_model() -> Any:
    """Initialize screening model from shared runtime config."""
    cfg = load_llm_config(module_hint="literature_search")
    if not cfg.api_key:
        raise ValueError(
            "API key not found. Please set LLM_API_KEY/OPENAI_API_KEY in .env file"
        )

    llm_model = cfg.model or "openai/gpt-4o-mini"
    api_base = cfg.api_base or "https://api.openai.com/v1"

    print(f"API Base: {api_base}")
    print(f"Model: {llm_model}\n")
    print(f"SSL Verify: {cfg.verify_ssl}\n")

    http_client = httpx.Client(verify=cfg.verify_ssl)
    http_async_client = httpx.AsyncClient(verify=cfg.verify_ssl)
    return ChatOpenAI(
        model=llm_model,
        temperature=cfg.temperature,
        api_key=cfg.api_key,
        base_url=api_base,
        http_client=http_client,
        http_async_client=http_async_client,
        max_retries=3,
        request_timeout=cfg.timeout_s or 60,
    )


def load_prompt_templates(screening_stage: str) -> tuple[str, str]:
    """Load stage-aware screening system/user prompts from prompt files."""
    prompt_pair = PROMPT_FILES.get(screening_stage)
    if prompt_pair is None:
        raise KeyError(f"Unknown screening prompt stage: {screening_stage}")
    system_path, user_path = prompt_pair
    system_text = system_path.read_text(encoding="utf-8")
    user_text = user_path.read_text(encoding="utf-8")
    return system_text, user_text


async def invoke_with_retry_async(llm, prompt, max_retries=3, delay=1.0):
    """Invoke structured output with bounded retries and exponential backoff."""
    last_exception = None
    for attempt in range(max_retries):
        try:
            return await llm.ainvoke(prompt)
        except Exception as e:
            last_exception = e
            error_str = str(e)

            if "context_length_exceeded" in error_str:
                print("      ⚠️ Context length exceeded. Skipping retry.")
                raise e

            if attempt < max_retries - 1:
                print(
                    f"      ⚠️ API glitch (attempt {attempt+1}/{max_retries}): {error_str[:100]}... Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                print(f"      ❌ API failed after {max_retries} attempts.")

    raise last_exception if last_exception else Exception("Unknown error in retry loop")


async def screen_papers_batch_async(
    papers: list[dict[str, Any]],
    research_question: str,
    llm_model: Any,
    batch_size: int = 20,
    batch_concurrency: int = 1,
    screening_config: Optional[dict[str, Any]] = None,
    screening_stage: str = "title_abstract",
    content_label: str = "Abstract",
    content_key: str = "Abstract",
    content_fallback: str = "(No abstract available. Please assess based on title only.)",
) -> list[dict[str, Any]]:
    """Screen papers in async batches and write scores back onto each paper dict."""
    default_config = {
        "research_question": research_question,
        "disease_focus": "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus) AND its (variant OR mutation OR lineage OR amino acid substitution)",
        "disease_exclude": "studies that focus solely on other diseases or wild-type only without variant comparison",
        "parameter_focus": "target epidemiological parameters related to the research question (e.g., reproduction number, serial interval, fatality rate)",
        "parameter_exclude": "studies that discuss adjacent outcomes without actually reporting or estimating the target parameter",
    }
    config = {**default_config, **(screening_config or {})}

    system_text, user_text = load_prompt_templates(screening_stage)
    stage_mode = resolve_stage_mode(screening_stage, config.get("policies", {}))

    system_text = system_text.format(
        screening_stage=screening_stage.replace("_", " "),
        research_question=config["research_question"],
        disease_focus=config["disease_focus"],
        disease_exclude=config["disease_exclude"],
        parameter_focus=config["parameter_focus"],
        parameter_exclude=config["parameter_exclude"],
    )
    template = ChatPromptTemplate.from_messages(
        [("system", system_text), ("human", user_text)]
    )
    structured_llm = llm_model.with_structured_output(ScreeningDecision)

    all_prompts: list[tuple[dict[str, Any], Any]] = []
    for paper in papers:
        title = paper.get("Title", "").strip()
        content = (paper.get(content_key) or "").strip() or content_fallback
        keywords = (paper.get("Keywords") or "").strip() or "(No keywords available)"
        prompt = template.format_messages(
            research_question=research_question,
            title=title,
            content_label=content_label,
            content=content,
            keywords=keywords,
        )
        all_prompts.append((paper, prompt))

    total = len(all_prompts)
    total_batches = (total - 1) // batch_size + 1
    log_every_batches = max(1, total_batches // 20)
    print(
        f"\n准备筛选 {total} 篇文献（batch_size={batch_size} | batch_concurrency={batch_concurrency}）...\n"
    )

    semaphore = asyncio.Semaphore(max(1, batch_concurrency))
    print_lock = asyncio.Lock()
    completed = 0
    started_at = time.perf_counter()

    async def process_batch(batch_idx: int, batch: list[tuple[dict[str, Any], Any]]):
        nonlocal completed
        async with semaphore:
            batch_prompts = [prompt for _, prompt in batch]
            batch_papers = [paper for paper, _ in batch]

            should_log = (
                batch_idx == 1
                or batch_idx == total_batches
                or batch_idx % log_every_batches == 0
            )

            try:
                tasks = [
                    invoke_with_retry_async(structured_llm, prompt)
                    for prompt in batch_prompts
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                single_errors: list[str] = []
                for paper, result in zip(batch_papers, results):
                    completed += 1
                    if isinstance(result, Exception):
                        single_errors.append(
                            f"  ⚠️ 单篇失败 PMID={paper.get('PMID', 'N/A')}: {str(result)[:100]}"
                        )
                        _mark_paper_error(paper, result)
                        continue
                    _write_structured_result(
                        paper,
                        result,
                        thresholds=config.get("thresholds"),
                        stage_mode=stage_mode,
                    )

                strong_count = sum(
                    1 for p in batch_papers if p.get("llm_suggest") == "strong_candidate"
                )
                possible_count = sum(
                    1 for p in batch_papers if p.get("llm_suggest") == "possible_candidate"
                )
                error_count = sum(
                    1 for p in batch_papers if p.get("llm_suggest") == "error"
                )

                if should_log or error_count > 0:
                    elapsed = time.perf_counter() - started_at
                    rate = completed / elapsed if elapsed > 0 else 0.0
                    eta = (total - completed) / rate if rate > 0 else 0.0
                    unlikely_count = len(batch) - strong_count - possible_count - error_count
                    async with print_lock:
                        print(f"[{batch_idx:>3}/{total_batches}] "
                              f"进度 {completed}/{total} | "
                              f"{rate:.1f} 篇/秒 | ETA {eta/60:.1f}min | "
                              f"S={strong_count} P={possible_count} U={unlikely_count} E={error_count}")
                        for msg in single_errors:
                            print(msg)

            except Exception as e:
                async with print_lock:
                    print(f"  [Batch {batch_idx}] 批次失败: {str(e)[:200]}")
                    print(f"  [Batch {batch_idx}] 尝试单篇重处理...")
                for paper, prompt in batch:
                    try:
                        result = await invoke_with_retry_async(structured_llm, prompt)
                        _write_structured_result(
                            paper,
                            result,
                            thresholds=config.get("thresholds"),
                            stage_mode=stage_mode,
                        )
                    except Exception as e2:
                        async with print_lock:
                            print(
                                f"    单篇失败 PMID={paper.get('PMID', 'N/A')}: {str(e2)[:100]}"
                            )
                        _mark_paper_error(paper, e2)

    batches = [all_prompts[i : i + batch_size] for i in range(0, total, batch_size)]
    await asyncio.gather(
        *(process_batch(idx + 1, batch) for idx, batch in enumerate(batches))
    )

    elapsed_total = time.perf_counter() - started_at
    rate_total = total / elapsed_total if elapsed_total > 0 else 0.0
    print(
        f"完成 {total} 篇，总耗时 {elapsed_total/60:.1f} 分钟，平均 {rate_total:.2f} 篇/秒"
    )
    return papers


def _write_structured_result(
    paper: dict[str, Any],
    result: ScreeningDecision,
    *,
    thresholds: dict[str, Any] | None,
    stage_mode: str,
) -> None:
    paper["llm_suggest"] = classify_screening_decision(
        result,
        thresholds=thresholds,
        stage_mode=stage_mode,
    )
    paper["overall_score"] = result.overall_score
    paper["overall_justification"] = result.overall_justification
    paper["disease_score"] = result.disease_relevance.score
    paper["disease_justification"] = result.disease_relevance.justification
    paper["population_score"] = result.population_relevance.score
    paper["population_justification"] = result.population_relevance.justification
    paper["location_score"] = result.location_relevance.score
    paper["location_justification"] = result.location_relevance.justification
    paper["evidence_score"] = result.original_evidence.score
    paper["evidence_justification"] = result.original_evidence.justification
    paper["parameter_score"] = result.parameter_relevance.score
    paper["parameter_justification"] = result.parameter_relevance.justification


def _mark_paper_error(paper: dict[str, Any], error: Exception) -> None:
    paper["llm_suggest"] = "error"
    paper["overall_score"] = 0
    paper["overall_justification"] = f"LLM error: {str(error)[:200]}"
    for dimension in [
        "disease",
        "population",
        "location",
        "evidence",
        "parameter",
    ]:
        paper[f"{dimension}_score"] = 0
        paper[f"{dimension}_justification"] = "Error"
