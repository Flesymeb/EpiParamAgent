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
            "API key not found. Please set LLM_API_KEY/OPENAI_API_KEY in .env file"
        )

    llm_model = model_override or cfg.model or "openai/gpt-4o-mini"
    api_base = cfg.api_base or "https://api.openai.com/v1"

    print(f"API Base: {api_base}")
    print(f"Model: {llm_model}\n")
    print(f"SSL Verify: {cfg.verify_ssl}\n")
    print(f"Force streaming: {cfg.force_streaming}\n")

    return ChatOpenAI(
        model=llm_model,
        temperature=cfg.temperature,
        api_key=cfg.api_key,
        base_url=api_base,
        max_retries=3,
        request_timeout=cfg.timeout_s,
        streaming=cfg.force_streaming,
        max_tokens=cfg.max_tokens,
    )




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

    # Use JSON mode instead of function calling (works with more proxies/models)
    json_schema = output_schema.model_json_schema()
    schema_hint = _build_json_schema_hint(output_schema)
    system_text += f"\n\nYou MUST respond with a single JSON object matching this schema. Output valid JSON only, no other text.\n{schema_hint}"

    structured_llm = llm_model.bind(response_format={"type": "json_object"})

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
        f"\nPreparing to screen {total} papers (batch_size={batch_size} | batch_concurrency={batch_concurrency})...\n"
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
                            f"  ⚠️ Paper failed PMID={paper.get('PMID', 'N/A')}: {str(result)[:100]}"
                        )
                        _mark_paper_error(paper, result)
                        continue
                    decision, cost = result
                    _write_cost(paper, cost)
                    # Parse JSON response from AIMessage into Pydantic model
                    content_str = decision.content if hasattr(decision, 'content') else str(decision)
                    parsed = _parse_json_result(content_str, output_schema)
                    if isinstance(parsed, BinaryDecision):
                        _write_binary_result(paper, parsed)
                    elif isinstance(parsed, PECODecision):
                        _write_peco_result(paper, parsed)
                    else:
                        _write_structured_result(
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
                    eta = (total - completed) / rate if rate > 0 else 0.0
                    unlikely_count = len(batch) - strong_count - possible_count - error_count
                    async with print_lock:
                        print(f"[{batch_idx:>3}/{total_batches}] "
                              f"Progress {completed}/{total} | "
                              f"{rate:.1f} papers/s | ETA {eta/60:.1f}min | "
                              f"S={strong_count} P={possible_count} U={unlikely_count} E={error_count}")
                        for msg in single_errors:
                            print(msg)

            except Exception as e:
                async with print_lock:
                    print(f"  [Batch {batch_idx}] Batch failed: {str(e)[:200]}")
                    print(f"  [Batch {batch_idx}] Retrying individual papers...")
                for paper, prompt in batch:
                    try:
                        raw = await invoke_with_retry_async(structured_llm, prompt)
                        if isinstance(raw, tuple):
                            llm_result, cost = raw
                            _write_cost(paper, cost)
                        else:
                            llm_result = raw
                        # Parse JSON response from AIMessage
                        content_str = llm_result.content if hasattr(llm_result, 'content') else str(llm_result)
                        parsed = _parse_json_result(content_str, output_schema)
                        if isinstance(parsed, BinaryDecision):
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
                                f"    Paper failed PMID={paper.get('PMID', 'N/A')}: {str(e2)[:100]}"
                            )
                        _mark_paper_error(paper, e2)

    batches = [all_prompts[i : i + batch_size] for i in range(0, total, batch_size)]
    await asyncio.gather(
        *(process_batch(idx + 1, batch) for idx, batch in enumerate(batches))
    )

    elapsed_total = time.perf_counter() - started_at
    rate_total = total / elapsed_total if elapsed_total > 0 else 0.0
    print(
        f"Completed {total} papers in {elapsed_total/60:.1f}min, avg {rate_total:.2f} papers/s"
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

    # Convert flat booleans (P:true, E:true) to structured objects
    for elem_name in ["population", "exposure", "comparison", "outcome"]:
        if elem_name in data and isinstance(data[elem_name], bool):
            data[elem_name] = {
                "present": data[elem_name],
                "justification": "",
            }

    # Convert flat scores (disease:4) to structured objects for 5D
    for dim_name in ["disease_relevance", "population_relevance",
                      "location_relevance", "original_evidence", "parameter_relevance"]:
        if dim_name in data and isinstance(data[dim_name], (int, float)):
            data[dim_name] = {
                "score": int(data[dim_name]),
                "justification": data.get("overall_justification", ""),
            }

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
