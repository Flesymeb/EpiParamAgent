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

from metaagent.config import load_llm_config

from metaagent.screening.models import (
    BinaryDecision,
    ScreeningDecision,
    PECODecision,
    classify_binary_decision,
    classify_screening_decision,
    classify_peco_decision,
    resolve_stage2_evidence_floor,
    resolve_stage_mode,
)
from metaagent.screening.prompt_loader import PROMPT_FILES, load_prompt_templates


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
    cfg = load_llm_config(module_hint="screening")
    if not cfg.api_key:
        raise ValueError(
            "API key not found. Please set LLM_API_KEY in .env.local file"
        )

    llm_model = model_override or cfg.model or "openai/gpt-4o-mini"
    api_base = cfg.api_base or "https://api.openai.com/v1"

    print(f"Model: {llm_model} @ {api_base}")

    kwargs: dict[str, Any] = {
        "model": llm_model,
        "temperature": cfg.temperature,
        "api_key": cfg.api_key,
        "base_url": api_base,
        "max_retries": 3,
        "request_timeout": cfg.timeout_s,
        "streaming": cfg.force_streaming,
        "max_tokens": cfg.max_tokens,
    }
    if "openrouter.ai" in api_base and "minimax/" not in llm_model.lower():
        # Keep reasoning models from returning reasoning-only messages with
        # empty content/tool payloads through the OpenAI-compatible API.
        # MiniMax endpoints reject even exclude-only reasoning controls.
        kwargs["reasoning"] = {"exclude": True}

    return ChatOpenAI(**kwargs)




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
                print("      ⚠ Context length exceeded, skipping retry.")
                raise e

            if attempt < max_retries - 1:
                err_short = error_str.split('\n')[0][:80]
                print(f"      Retry {attempt+1}/{max_retries} ({delay}s): {err_short}")
                await asyncio.sleep(delay)
                delay *= 2
            else:
                print(f"      ❌ Failed after {max_retries} attempts.")

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
        "disease_focus": research_question or "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus)",
        "disease_exclude": "studies that focus solely on other diseases",
        "parameter_focus": "target epidemiological parameter (e.g., case fatality rate, mortality, death rate, infection fatality rate). Include papers that report or estimate death/survival outcomes from original patient data.",
        "parameter_exclude": "studies that only mention the parameter in passing without quantitative data",
        "parameter_scoring_note": (
            "- Score 4 if the paper directly reports or estimates the target parameter (CFR, mortality rate, "
            "death rate, survival) from its own patient-level or population-level data.\n"
            "- Score 3 if the paper reports clinical outcomes including deaths/survival among a defined cohort, "
            "enabling CFR calculation, even if CFR is not the primary endpoint.\n"
            "- Score 2 if the paper reports related outcomes (ICU admission, severity, hospitalization) "
            "without explicit mortality data, or uses the parameter from another study as input.\n"
            "- Score 0–1 if the paper only mentions the parameter in background/introduction without any quantitative death/survival data."
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
    if "json" not in f"{system_text}\n{user_text}".lower():
        system_text += "\n\nRespond in JSON format only."
    template = ChatPromptTemplate.from_messages(
        [("system", system_text), ("human", user_text)]
    )
    if is_peco:
        output_schema = PECODecision
    elif is_binary:
        output_schema = BinaryDecision
    else:
        output_schema = ScreeningDecision

    # Use with_structured_output (function calling) for reliable structured output
    structured_llm = llm_model.with_structured_output(output_schema)

    all_prompts: list[tuple[dict[str, Any], Any]] = []
    for paper in papers:
        title = paper.get("Title", "").strip()
        abstract = (paper.get(content_key) or "").strip()
        content = abstract or content_fallback

        # Auto-detect empty abstract → use title_only/lenient mode
        effective_stage = screening_stage
        if not abstract and screening_stage == "title_abstract":
            effective_stage = "title_only"
            stage_mode = "lenient"
        keywords = (paper.get("Keywords") or "").strip() or "(No keywords available)"
        prompt_kwargs: dict[str, str] = {
            "research_question": research_question,
            "title": title,
            "content_label": content_label,
            "content": content,
            "keywords": keywords,
        }
        if is_peco or strategy == "5d":
            prompt_kwargs["pub_types"] = (paper.get("pub_types") or "").strip() or "(Not available)"
            prompt_kwargs["mesh_terms"] = (paper.get("mesh_terms") or "").strip() or "(Not available)"
        prompt = template.format_messages(**prompt_kwargs)
        all_prompts.append((paper, prompt))

    total = len(all_prompts)
    total_batches = (total - 1) // batch_size + 1
    log_every_batches = max(1, total_batches // 20)
    print(
        f"\nScreening {total} papers (batch={batch_size}, concurrency={batch_concurrency})...\n"
    )

    # Limit actual in-flight LLM requests. Previously this semaphore wrapped
    # whole batches, so real API concurrency was batch_size * batch_concurrency.
    request_semaphore = asyncio.Semaphore(max(1, batch_concurrency))
    print_lock = asyncio.Lock()
    completed = 0
    started_at = time.perf_counter()

    async def invoke_one(prompt):
        async with request_semaphore:
            return await invoke_with_retry_async(structured_llm, prompt)

    async def process_batch(batch_idx: int, batch: list[tuple[dict[str, Any], Any]]):
        nonlocal completed
        batch_prompts = [prompt for _, prompt in batch]
        batch_papers = [paper for paper, _ in batch]

        should_log = (
            batch_idx == 1
            or batch_idx == total_batches
            or batch_idx % log_every_batches == 0
        )

        try:
            tasks = [invoke_one(prompt) for prompt in batch_prompts]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            single_errors: list[str] = []
            for paper, result in zip(batch_papers, results):
                completed += 1
                if isinstance(result, Exception):
                    single_errors.append(
                        f"  ⚠️ Paper failed PMID={paper.get('PMID', 'N/A')}: {str(result)[:100]}"
                    )
                    _mark_paper_error(paper, result)
                    continue
                decision, cost = result
                _write_cost(paper, cost)
                parsed = _coerce_structured_result(decision, output_schema)
                _write_parsed_result(
                    paper,
                    parsed,
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
                unlikely_count = len(batch) - strong_count - possible_count - error_count
                async with print_lock:
                    print(f"  [{completed}/{total}] {rate:.1f}/s "
                          f"S={strong_count} P={possible_count} U={unlikely_count} E={error_count}")
                    for msg in single_errors:
                        print(msg)

        except Exception as e:
            async with print_lock:
                print(f"  [Batch {batch_idx}] Batch failed: {str(e)[:200]}")
                print(f"  [Batch {batch_idx}] Retrying individual papers...")
            for paper, prompt in batch:
                try:
                    async with request_semaphore:
                        raw = await invoke_with_retry_async(structured_llm, prompt)
                    if isinstance(raw, tuple):
                        llm_result, cost = raw
                        _write_cost(paper, cost)
                    else:
                        llm_result = raw
                    parsed = _coerce_structured_result(llm_result, output_schema)
                    _write_parsed_result(
                        paper,
                        parsed,
                        thresholds=config.get("thresholds"),
                        stage_mode=stage_mode,
                        evidence_floor=evidence_floor,
                    )
                except Exception as e2:
                    async with print_lock:
                        print(
                            f"    Paper failed PMID={paper.get('PMID', 'N/A')}: {str(e2)[:100]}"
                        )
                    _mark_paper_error(paper, e2)

    batches = [all_prompts[i : i + batch_size] for i in range(0, total, batch_size)]
    for idx, batch in enumerate(batches):
        # Keep the number of scheduled coroutines bounded. Running every batch
        # at once can queue hundreds/thousands of pending structured-output
        # calls against a shared client; some OpenRouter providers then surface
        # this as connection storms even when request_semaphore is low.
        await process_batch(idx + 1, batch)

    elapsed_total = time.perf_counter() - started_at
    rate_total = total / elapsed_total if elapsed_total > 0 else 0.0
    print(
        f"Done: {total} papers in {elapsed_total/60:.1f}min ({rate_total:.1f}/s)"
    )
    return papers


def _coerce_structured_result(result: Any, output_schema: type) -> Any:
    """Normalize LangChain structured output across provider response styles."""
    if isinstance(result, (BinaryDecision, ScreeningDecision, PECODecision)):
        return result

    content_str = getattr(result, "content", "") or ""
    if not content_str.strip():
        raise ValueError("Empty response from LLM")
    return _parse_json_result(content_str, output_schema)


def _write_parsed_result(
    paper: dict[str, Any],
    parsed: Any,
    *,
    thresholds: dict[str, Any] | None,
    stage_mode: str,
    evidence_floor: int,
) -> None:
    if isinstance(parsed, BinaryDecision):
        _write_binary_result(paper, parsed)
    elif isinstance(parsed, PECODecision):
        _write_peco_result(paper, parsed)
    else:
        _write_structured_result(
            paper,
            parsed,
            thresholds=thresholds,
            stage_mode=stage_mode,
            evidence_floor=evidence_floor,
        )


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
    paper["confidence"] = result.confidence


def _write_binary_result(paper: dict[str, Any], result: BinaryDecision) -> None:
    """Write binary include/exclude decision fields onto the paper dict.

    Dimension score fields are left empty to keep the output schema consistent
    with 5D runs while clearly signalling that per-dimension scores are absent.
    """
    paper["llm_suggest"] = classify_binary_decision(result)
    paper["overall_score"] = 4 if result.include else 0
    paper["overall_justification"] = result.justification
    paper["confidence"] = result.confidence
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
    paper["confidence"] = result.confidence
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


def _build_json_schema_hint(model_class: type) -> str:
    """Build a compact JSON schema description for the LLM prompt."""
    schema = model_class.model_json_schema()
    props = schema.get("properties", {})
    required = schema.get("required", [])
    lines = ["{"]
    for name, prop in props.items():
        ptype = prop.get("type", "any")
        desc = (prop.get("description", "") or "")[:80]
        req = "required" if name in required else "optional"
        if ptype == "object":
            subprops = prop.get("properties", {})
            sub = ", ".join(f'"{k}"' for k in subprops)
            lines.append(f'  "{name}": {{ {sub} }},  // {req}, {desc}')
        elif ptype == "array":
            items = prop.get("items", {})
            lines.append(f'  "{name}": [...],  // {req}, {desc}')
        elif ptype == "boolean":
            lines.append(f'  "{name}": true|false,  // {req}, {desc}')
        elif ptype == "number":
            lines.append(f'  "{name}": 0.0,  // {req}, {desc}')
        elif ptype == "integer":
            lines.append(f'  "{name}": 0,  // {req}, {desc}')
        else:
            lines.append(f'  "{name}": "...",  // {req}, {desc}')
    lines.append("}")
    return "\n".join(lines)


def _parse_json_result(content: str, model_class: type) -> Any:
    """Parse LLM JSON output into a Pydantic model, with fallbacks and field name mapping."""
    import json as _json
    import re

    # Extract JSON from content
    data = None
    for pattern in [
        r'```(?:json)?\s*(\{.*?\})\s*```',
        r'\{.*\}',
    ]:
        m = re.search(pattern, content, re.DOTALL)
        if m:
            try:
                data = _json.loads(m.group(1) if m.lastindex else m.group(0))
                break
            except Exception:
                pass
    if data is None:
        try:
            data = _json.loads(content)
        except Exception:
            raise ValueError(f"Could not parse JSON from response: {content[:200]}")

    # Map abbreviated/alternative field names to Pydantic model fields
    field_map = {
        # PECO mappings
        "P": "population", "E": "exposure", "C": "comparison", "O": "outcome",
        "P_present": None, "E_present": None, "C_present": None, "O_present": None,
        "P_justification": None, "E_justification": None,
        # 5D mappings
        "disease": "disease_relevance", "population": "population_relevance",
        "location": "location_relevance", "evidence": "original_evidence",
        "parameter": "parameter_relevance",
        "disease_relevance_score": None, "population_relevance_score": None,
        # Score fields
        "score_disease": None, "score_population": None, "score_location": None,
        "score_evidence": None, "score_parameter": None,
    }

    # Normalize flattened PECO fields
    if any(k.startswith(("P_", "E_", "C_", "O_")) for k in data):
        normalized = {}
        for prefix, field in [("P", "population"), ("E", "exposure"),
                               ("C", "comparison"), ("O", "outcome")]:
            present_key = f"{prefix}_present"
            just_key = f"{prefix}_justification"
            if present_key in data:
                normalized[field] = {
                    "present": data[present_key],
                    "justification": data.get(just_key, ""),
                }
        if normalized:
            data.update(normalized)

    # Remap abbreviated field names
    remapped = {}
    for k, v in data.items():
        if k in field_map and field_map[k] is not None:
            remapped[field_map[k]] = v
        elif k in field_map:
            pass  # Skip mapped-to-None fields
        elif isinstance(v, dict) and "present" in v:
            remapped[k] = v
        elif isinstance(v, bool):
            remapped[k] = v
        else:
            remapped[k] = v
    data = remapped

    # Aggressive key normalization: lowercase + replace spaces/hyphens with underscores
    normalized = {}
    for k, v in list(data.items()):
        nk = k.strip().lower().replace(" ", "_").replace("-", "_")
        # Merge duplicate normalized keys
        if nk in normalized:
            if isinstance(v, dict) and isinstance(normalized[nk], dict):
                normalized[nk].update(v)
        else:
            normalized[nk] = v
    data = normalized

    # Remap "evidence" -> "justification" in nested objects (GLM output format)
    for key in list(data.keys()):
        if isinstance(data[key], dict):
            for sub_key in list(data[key].keys()):
                if sub_key == "evidence" and "justification" not in data[key]:
                    data[key]["justification"] = data[key].pop("evidence")
                elif sub_key == "reason" and "justification" not in data[key]:
                    data[key]["justification"] = data[key].pop("reason")

    # Convert flat booleans (P:true, E:true) to structured objects
    for elem_name in ["population", "exposure", "comparison", "outcome"]:
        if elem_name in data and isinstance(data[elem_name], bool):
            data[elem_name] = {
                "present": data[elem_name],
                "justification": "",
            }

    # Remap 5D alternative field names
    _5d_remap = {
        "disease": "disease_relevance", "disease_relevancy": "disease_relevance",
        "population": "population_relevance", "population_relevancy": "population_relevance",
        "location": "location_relevance", "location_relevancy": "location_relevance",
        "evidence": "original_evidence", "original_evidence_score": "original_evidence",
        "evidence_relevance": "original_evidence", "evidence_quality": "original_evidence",
        "original_empirical_evidence": "original_evidence",
        "parameter": "parameter_relevance", "parameter_relevancy": "parameter_relevance",
        "target_parameter_relevance": "parameter_relevance",
        "overall": "overall_score", "overall_justify": "overall_justification",
    }
    for old_k, new_k in _5d_remap.items():
        if old_k in data and new_k not in data:
            data[new_k] = data.pop(old_k)

    # Convert flat scores (disease:4) to structured objects for 5D
    for dim_name in ["disease_relevance", "population_relevance",
                      "location_relevance", "original_evidence", "parameter_relevance"]:
        if dim_name in data and isinstance(data[dim_name], (int, float)):
            data[dim_name] = {
                "score": int(data[dim_name]),
                "justification": data.get("overall_justification", ""),
            }

    # Convert flat dimension=integer to nested object (deepseek outputs flat format)
    _5d_dims = ["disease_relevance", "population_relevance", "location_relevance",
                "original_evidence", "parameter_relevance"]
    _word_to_score = {"high": 4, "medium": 3, "low": 1, "none": 0,
                     "excellent": 4, "good": 3, "fair": 2, "poor": 1,
                     "yes": 4, "no": 0, "true": 4, "false": 0}
    for dim in _5d_dims:
        if dim in data:
            val = data[dim]
            if isinstance(val, (int, float)):
                data[dim] = {"score": int(val), "justification": data.get("overall_justification", "")}
            elif isinstance(val, str):
                score = _word_to_score.get(val.lower().strip(), 2)
                try: score = int(float(val))
                except (ValueError, TypeError): pass
                data[dim] = {"score": score, "justification": data.get("overall_justification", "")}

    # Convert flat 5D format to nested objects (LLMs output flat format more reliably)
    _5d_flat_map = {
        "disease_score": "disease_relevance", "disease_justification": "disease_relevance",
        "population_score": "population_relevance", "population_justification": "population_relevance",
        "location_score": "location_relevance", "location_justification": "location_relevance",
        "evidence_score": "original_evidence", "evidence_justification": "original_evidence",
        "parameter_score": "parameter_relevance", "parameter_justification": "parameter_relevance",
    }
    flat_dims = {}
    for k, v in list(data.items()):
        if k in _5d_flat_map:
            dim = _5d_flat_map[k]
            if dim not in flat_dims:
                flat_dims[dim] = {}
            if k.endswith("_score"):
                flat_dims[dim]["score"] = int(float(v)) if isinstance(v, (int, float, str)) else 2
            else:
                flat_dims[dim]["justification"] = str(v)
    for dim, obj in flat_dims.items():
        if "score" in obj:
            obj.setdefault("justification", "")
            data[dim] = obj

    # Convert string values to appropriate types (GLM outputs everything as strings)
    for key in list(data.keys()):
        if isinstance(data[key], str):
            # Try integer
            try:
                data[key] = int(data[key])
            except (ValueError, TypeError):
                # Try float
                try:
                    data[key] = float(data[key])
                except (ValueError, TypeError):
                    pass

    # Convert flat string/integer scores to structured dimension objects for 5D
    dim_names = ["disease_relevance", "population_relevance", "location_relevance",
                 "original_evidence", "parameter_relevance"]
    for dim in dim_names:
        if dim in data and isinstance(data[dim], (int, float, str)):
            data[dim] = {
                "score": int(float(data[dim])),
                "justification": data.get("overall_justification", ""),
            }

    # Ensure confidence is float
    if "confidence" in data and isinstance(data["confidence"], str):
        data["confidence"] = float(data["confidence"])

    # Fill truly missing required Pydantic fields with neutral defaults
    # GLM output is inconsistent — sometimes skips original_evidence or parameter_relevance
    for dim, default_score in [
        ("disease_relevance", 2), ("population_relevance", 2),
        ("location_relevance", 2), ("original_evidence", 2),
        ("parameter_relevance", 2),
    ]:
        if dim not in data:
            data[dim] = {"score": default_score, "justification": "Model did not explicitly assess this dimension"}
    if "overall_justification" not in data:
        data["overall_justification"] = data.get("justification", "No overall justification provided")

    return model_class(**data)


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
