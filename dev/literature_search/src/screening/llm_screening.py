"""LLM-powered screening helpers for title/abstract/full-text stages."""

from __future__ import annotations

import asyncio
import csv
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from common.config import load_llm_config

from .decision_models import (
    BinaryDecision,
    ScreeningDecision,
    PECODecision,
    classify_binary_decision,
    classify_screening_decision,
    classify_peco_decision,
    resolve_stage2_evidence_floor,
    resolve_stage_mode,
)

BASE_DIR = Path(__file__).resolve().parents[2]
PROMPT_DIR = BASE_DIR / "src" / "epidemiology" / "prompts"
PROMPT_FILES = {
    "title_abstract": (
        PROMPT_DIR / "5d" / "screening_system_title_abstract.md",
        PROMPT_DIR / "5d" / "screening_user_title_abstract.md",
    ),
    "title_only": (
        PROMPT_DIR / "5d" / "screening_system_title_only.md",
        PROMPT_DIR / "5d" / "screening_user_title_only.md",
    ),
    "full_text": (
        PROMPT_DIR / "5d" / "screening_system_full_text.md",
        PROMPT_DIR / "5d" / "screening_user_full_text.md",
    ),
    "possible_full_text": (
        PROMPT_DIR / "5d" / "screening_system_possible_full_text.md",
        PROMPT_DIR / "5d" / "screening_user_possible_full_text.md",
    ),
    "strong_full_text": (
        PROMPT_DIR / "5d" / "screening_system_strong_full_text.md",
        PROMPT_DIR / "5d" / "screening_user_strong_full_text.md",
    ),
    "binary_title_abstract": (
        PROMPT_DIR / "binary" / "screening_system_title_abstract.md",
        PROMPT_DIR / "binary" / "screening_user_title_abstract.md",
    ),
    "binary_title_only": (
        PROMPT_DIR / "binary" / "screening_system_title_only.md",
        PROMPT_DIR / "binary" / "screening_user_title_only.md",
    ),
    "binary_noguidance_title_abstract": (
        PROMPT_DIR / "binary_noguidance" / "screening_system_title_abstract.md",
        PROMPT_DIR / "binary_noguidance" / "screening_user_title_abstract.md",
    ),
    "binary_noguidance_title_only": (
        PROMPT_DIR / "binary_noguidance" / "screening_system_title_only.md",
        PROMPT_DIR / "binary_noguidance" / "screening_user_title_only.md",
    ),
    "binary_baseline_title_abstract": (
        PROMPT_DIR / "binary_baseline" / "screening_system_title_abstract.md",
        PROMPT_DIR / "binary_baseline" / "screening_user_title_abstract.md",
    ),
    "binary_baseline_title_only": (
        PROMPT_DIR / "binary_baseline" / "screening_system_title_only.md",
        PROMPT_DIR / "binary_baseline" / "screening_user_title_only.md",
    ),
    "peco_title_abstract": (
        PROMPT_DIR / "peco" / "screening_system_title_abstract.md",
        PROMPT_DIR / "peco" / "screening_user_title_abstract.md",
    ),
    "peco_title_only": (
        PROMPT_DIR / "peco" / "screening_system_title_only.md",
        PROMPT_DIR / "peco" / "screening_user_title_only.md",
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


def init_llm_model(model_override: str | None = None) -> Any:
    """Initialize screening model from shared runtime config.

    Args:
        model_override: If provided, overrides the model name from env/config.
            Useful for running baseline comparisons across multiple models.
    """
    cfg = load_llm_config(module_hint="literature_search")
    if not cfg.api_key:
        raise ValueError(
            "API key not found. Please set LLM_API_KEY/OPENAI_API_KEY in .env file"
        )

    llm_model = model_override or cfg.model or "openai/gpt-4o-mini"
    api_base = cfg.api_base or "https://api.openai.com/v1"

    print(f"API Base: {api_base}")
    print(f"Model: {llm_model}\n")
    print(f"SSL Verify: {cfg.verify_ssl}\n")
    print(f"Force streaming: {cfg.force_streaming}\n")

    http_client = httpx.Client(verify=cfg.verify_ssl, timeout=cfg.timeout_s)
    http_async_client = httpx.AsyncClient(verify=cfg.verify_ssl, timeout=cfg.timeout_s)
    return ChatOpenAI(
        model=llm_model,
        temperature=cfg.temperature,
        api_key=cfg.api_key,
        base_url=api_base,
        http_client=http_client,
        http_async_client=http_async_client,
        max_retries=3,
        request_timeout=cfg.timeout_s,
        streaming=cfg.force_streaming,
        max_tokens=cfg.max_tokens,
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


class _TokenCounter(BaseCallbackHandler):
    """Per-invocation callback that captures token usage from the LLM response."""

    def __init__(self) -> None:
        super().__init__()
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        try:
            usage = None
            if hasattr(response, "llm_output") and response.llm_output:
                usage = response.llm_output.get("token_usage")
            if usage is None and hasattr(response, "generations"):
                for gen_list in response.generations:
                    for gen in gen_list:
                        msg = getattr(gen, "message", None)
                        if msg and hasattr(msg, "usage_metadata"):
                            u = msg.usage_metadata
                            self.prompt_tokens += u.get("input_tokens", 0)
                            self.completion_tokens += u.get("output_tokens", 0)
                            self.total_tokens += u.get("total_tokens", 0)
                            return
            if usage:
                self.prompt_tokens = usage.get("prompt_tokens", 0)
                self.completion_tokens = usage.get("completion_tokens", 0)
                self.total_tokens = usage.get("total_tokens", 0)
        except Exception:
            pass  # Token counting is best-effort


async def invoke_with_retry_async(llm, prompt, max_retries=3, delay=1.0):
    """Invoke structured output with bounded retries, exponential backoff, and cost tracking.

    Returns:
        (result, cost_dict) where cost_dict has keys: prompt_tokens, completion_tokens,
        total_tokens, wall_time_ms.
    """
    last_exception = None
    for attempt in range(max_retries):
        try:
            counter = _TokenCounter()
            t0 = time.perf_counter()
            result = await llm.ainvoke(prompt, config={"callbacks": [counter]})
            wall_ms = (time.perf_counter() - t0) * 1000
            cost = {
                "prompt_tokens": counter.prompt_tokens,
                "completion_tokens": counter.completion_tokens,
                "total_tokens": counter.total_tokens,
                "wall_time_ms": round(wall_ms, 1),
            }
            return result, cost
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
    strategy: str = "5d",
) -> list[dict[str, Any]]:
    """Screen papers in async batches and write scores back onto each paper dict.

    Args:
        strategy: Screening strategy. "5d" uses the five-dimension scoring model;
            "binary" uses a simpler include/exclude decision model.
    """
    default_config = {
        "research_question": research_question,
        "disease_focus": "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus) AND its (variant OR mutation OR lineage OR amino acid substitution)",
        "disease_exclude": "studies that focus solely on other diseases or wild-type only without variant comparison",
        "parameter_focus": "target epidemiological parameters related to the research question (e.g., reproduction number, serial interval, fatality rate)",
        "parameter_exclude": "studies that discuss adjacent outcomes without actually reporting or estimating the target parameter",
        "parameter_scoring_note": (
            "- Score 3–4 only if the paper directly reports the parameter from its own observed individual-level data "
            "(contact-tracing pairs, household contacts, clinical surveillance records).\n"
            "- Score 2 if the paper estimates the parameter as a model output (transmission model calibration), "
            "or uses the parameter value from another study as an input assumption.\n"
            "- Score 0–1 if the paper only mentions the parameter in the introduction/background without reporting a new estimate."
        ),
    }
    config = {**default_config, **(screening_config or {})}

    # parameter_scoring_note may come from policies (YAML block scalar) — strip trailing whitespace
    policies = config.get("policies", {}) or {}
    if "parameter_scoring_note" in policies:
        config["parameter_scoring_note"] = str(policies["parameter_scoring_note"]).strip()

    # Binary strategy only applies at title/abstract stages; full-text stages always
    # use 5D scoring because the detailed prompt and ScreeningDecision schema are
    # needed for the stage-2 classification logic.
    # PECO strategy similarly applies only at title/abstract stages.
    BINARY_STAGES = {"title_abstract", "title_only"}
    is_binary = strategy in {"binary", "binary_noguidance", "binary_baseline"} and screening_stage in BINARY_STAGES
    is_peco = strategy == "peco" and screening_stage in BINARY_STAGES
    is_noguidance = strategy == "binary_noguidance" and screening_stage in BINARY_STAGES
    is_baseline = strategy == "binary_baseline" and screening_stage in BINARY_STAGES

    # PECO strategy uses separate prompt files
    effective_stage = screening_stage
    if is_peco:
        peco_stage_map = {
            "title_abstract": "peco_title_abstract",
            "title_only": "peco_title_only",
        }
        effective_stage = peco_stage_map.get(screening_stage, screening_stage)
    elif is_binary:
        if is_noguidance:
            binary_stage_map = {
                "title_abstract": "binary_noguidance_title_abstract",
                "title_only": "binary_noguidance_title_only",
            }
        elif is_baseline:
            binary_stage_map = {
                "title_abstract": "binary_baseline_title_abstract",
                "title_only": "binary_baseline_title_only",
            }
        else:
            binary_stage_map = {
                "title_abstract": "binary_title_abstract",
                "title_only": "binary_title_only",
            }
        effective_stage = binary_stage_map.get(screening_stage, screening_stage)

    system_text, user_text = load_prompt_templates(effective_stage)
    stage_mode = resolve_stage_mode(screening_stage, policies)
    evidence_floor = resolve_stage2_evidence_floor(policies)

    if is_noguidance:
        fmt_kwargs: dict[str, str] = {}
    elif is_baseline:
        fmt_kwargs = {
            "disease_focus": config["disease_focus"],
            "parameter_focus": config["parameter_focus"],
        }
    elif is_binary:
        fmt_kwargs = {
            "research_question": config["research_question"],
        }
    elif is_peco:
        fmt_kwargs = {
            "research_question": config["research_question"],
            "disease_focus": config["disease_focus"],
            "disease_exclude": config["disease_exclude"],
            "parameter_focus": config["parameter_focus"],
            "parameter_exclude": config["parameter_exclude"],
        }
    else:
        fmt_kwargs = {
            "screening_stage": screening_stage.replace("_", " "),
            "research_question": config["research_question"],
            "disease_focus": config["disease_focus"],
            "disease_exclude": config["disease_exclude"],
            "parameter_focus": config["parameter_focus"],
            "parameter_exclude": config["parameter_exclude"],
            "parameter_scoring_note": config["parameter_scoring_note"],
        }

    system_text = system_text.format(**fmt_kwargs)
    template = ChatPromptTemplate.from_messages(
        [("system", system_text), ("human", user_text)]
    )
    if is_peco:
        output_schema = PECODecision
    elif is_binary:
        output_schema = BinaryDecision
    else:
        output_schema = ScreeningDecision
    structured_llm = llm_model.with_structured_output(output_schema)

    all_prompts: list[tuple[dict[str, Any], Any]] = []
    for paper in papers:
        title = paper.get("Title", "").strip()
        content = (paper.get(content_key) or "").strip() or content_fallback
        keywords = (paper.get("Keywords") or "").strip() or "(No keywords available)"
        prompt_kwargs: dict[str, str] = {
            "research_question": research_question,
            "title": title,
            "content_label": content_label,
            "content": content,
            "keywords": keywords,
        }
        if is_peco:
            prompt_kwargs["pub_types"] = (paper.get("pub_types") or "").strip() or "(Not available)"
            prompt_kwargs["mesh_terms"] = (paper.get("mesh_terms") or "").strip() or "(Not available)"
        prompt = template.format_messages(**prompt_kwargs)
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
                    decision, cost = result
                    _write_cost(paper, cost)
                    if isinstance(decision, BinaryDecision):
                        _write_binary_result(paper, decision)
                    elif isinstance(decision, PECODecision):
                        _write_peco_result(paper, decision)
                    else:
                        _write_structured_result(
                            paper,
                            decision,
                            thresholds=config.get("thresholds"),
                            stage_mode=stage_mode,
                            evidence_floor=evidence_floor,
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
                        raw = await invoke_with_retry_async(structured_llm, prompt)
                        if isinstance(raw, tuple):
                            result, cost = raw
                            _write_cost(paper, cost)
                        else:
                            result = raw
                        if isinstance(result, BinaryDecision):
                            _write_binary_result(paper, result)
                        elif isinstance(result, PECODecision):
                            _write_peco_result(paper, result)
                        else:
                            _write_structured_result(
                                paper,
                                result,
                                thresholds=config.get("thresholds"),
                                stage_mode=stage_mode,
                                evidence_floor=evidence_floor,
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
    evidence_floor: int = 1,
) -> None:
    paper["llm_suggest"] = classify_screening_decision(
        result,
        thresholds=thresholds,
        stage_mode=stage_mode,
        evidence_floor=evidence_floor,
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


def _write_binary_result(paper: dict[str, Any], result: BinaryDecision) -> None:
    """Write binary include/exclude decision fields onto the paper dict.

    Dimension score fields are left empty to keep the output schema consistent
    with 5D runs while clearly signalling that per-dimension scores are absent.
    """
    paper["llm_suggest"] = classify_binary_decision(result)
    paper["overall_score"] = 4 if result.include else 0
    paper["overall_justification"] = result.justification
    for dim in ["disease", "population", "location", "evidence", "parameter"]:
        paper[f"{dim}_score"] = ""
        paper[f"{dim}_justification"] = ""


def _write_peco_result(paper: dict[str, Any], result: PECODecision) -> None:
    """Write PECO framework decision fields onto the paper dict.

    Maps PECO elements to dimension score fields for output schema consistency.
    P→population, E→disease, C→(unmapped, stored in overall_justification),
    O→parameter.
    """
    paper["llm_suggest"] = classify_peco_decision(result)
    paper["overall_score"] = 4 if result.include else (2 if result.confidence < 0.7 else 0)
    paper["overall_justification"] = result.justification
    paper["disease_score"] = 4 if result.exposure.present else 0
    paper["disease_justification"] = result.exposure.justification
    paper["population_score"] = 4 if result.population.present else 0
    paper["population_justification"] = result.population.justification
    paper["parameter_score"] = 4 if result.outcome.present else 0
    paper["parameter_justification"] = result.outcome.justification
    paper["location_score"] = ""
    paper["location_justification"] = f"[PECO] C={result.comparison.present} | {result.comparison.justification}"
    paper["evidence_score"] = ""
    paper["evidence_justification"] = ""
    paper["confidence"] = result.confidence


def _write_cost(paper: dict[str, Any], cost: dict[str, Any]) -> None:
    """Write per-paper token usage and timing onto the paper dict."""
    paper["prompt_tokens"] = cost.get("prompt_tokens", 0)
    paper["completion_tokens"] = cost.get("completion_tokens", 0)
    paper["total_tokens"] = cost.get("total_tokens", 0)
    paper["wall_time_ms"] = cost.get("wall_time_ms", 0)


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
