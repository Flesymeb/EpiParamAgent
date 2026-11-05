"""LLM-powered screening helpers for title/abstract/full-text stages."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import csv
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from metaagent.config import is_usable_secret, load_llm_config, merge_thinking_policy

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
from metaagent.screening.prompt_loader import PROMPT_FILES, load_prompt_templates, load_parameter_guides


def _matches_no_proxy(url: str, no_proxy: str) -> bool:
    """Return True when the URL host matches a NO_PROXY entry."""
    if not url or not no_proxy:
        return False
    host = url.split("//")[-1].split("/")[0].split(":")[0]
    return any(host.endswith(entry.strip()) for entry in no_proxy.split(",") if entry.strip())


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


def init_llm_model(
    model_override: str | None = None,
    provider_override: str | None = None,
    temperature_override: float | None = None,
    config_overrides: dict[str, Any] | None = None,
    module_hint: str = "screening",
) -> Any:
    """Initialize screening model from shared runtime config.

    Args:
        model_override: If provided, overrides the model name from env/config.
            Useful for running baseline comparisons across multiple models.
        provider_override: Optional provider profile override, e.g. openrouter,
            lab, or lab2.
    """
    params: dict[str, Any] = dict(config_overrides or {})
    if model_override:
        params["llm_model"] = model_override
    if provider_override:
        params["llm_provider"] = provider_override
    if temperature_override is not None:
        params["llm_temperature"] = temperature_override
    cfg = load_llm_config(params, module_hint=module_hint)
    if not is_usable_secret(cfg.api_key):
        raise ValueError(
            "API key not found. Please set LLM_API_KEY or the selected "
            "provider key in .env.local"
        )

    llm_model = cfg.model or "openai/gpt-4o-mini"
    api_base = cfg.api_base or "https://api.openai.com/v1"

    print(f"Provider: {cfg.provider or 'default'}")
    print(f"Model: {llm_model} @ {api_base}")

    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    trust_env = cfg.provider not in {"lab", "lab2"} and not _matches_no_proxy(api_base, no_proxy)
    from metaagent.llm_rate_limit import async_httpx_event_hooks, httpx_event_hooks

    http_client = httpx.Client(
        verify=cfg.verify_ssl,
        timeout=cfg.timeout_s,
        trust_env=trust_env,
        event_hooks=httpx_event_hooks(),
    )
    http_async_client = httpx.AsyncClient(
        verify=cfg.verify_ssl,
        timeout=cfg.timeout_s,
        trust_env=trust_env,
        event_hooks=async_httpx_event_hooks(),
    )

    kwargs: dict[str, Any] = {
        "model": llm_model,
        "temperature": cfg.temperature,
        "api_key": cfg.api_key,
        "base_url": api_base,
        # Retries are explicit in invoke_with_retry_async. Both transports use
        # the shared request gate, so each actual attempt consumes its slot.
        "max_retries": 0,
        "request_timeout": cfg.timeout_s,
        "streaming": cfg.force_streaming,
        "max_tokens": cfg.max_tokens,
        "http_client": http_client,
        "http_async_client": http_async_client,
    }
    if cfg.reasoning_effort:
        kwargs["reasoning_effort"] = cfg.reasoning_effort
    if cfg.provider == "bailian" and "qwen" in llm_model.lower() and cfg.thinking is None:
        # Screening requires concise structured classifications, not reasoning
        # traces. Bailian Qwen models otherwise default to thinking mode.
        kwargs["extra_body"] = {"enable_thinking": False}
    if "openrouter.ai" in api_base and "minimax/" not in llm_model.lower():
        # Some OpenRouter reasoning models otherwise return reasoning-only
        # payloads through the OpenAI-compatible API.
        kwargs["reasoning"] = {"exclude": True}

    policy_body = merge_thinking_policy(kwargs.get("extra_body"), cfg.thinking)
    if policy_body is not None:
        kwargs["extra_body"] = policy_body
    from metaagent.config import resolve_extra_body
    extra_body = resolve_extra_body(params, module_hint=module_hint)
    if extra_body:
        body = dict(kwargs.get("extra_body", {}))
        if "thinking" in extra_body or "enable_thinking" in extra_body:
            body.pop("thinking", None)
            body.pop("enable_thinking", None)
        kwargs["extra_body"] = merge_thinking_policy({**body, **extra_body}, None)
    return ChatOpenAI(**kwargs)




class _TokenCounter(BaseCallbackHandler):
    """Per-invocation callback that captures token usage from the LLM response."""

    def __init__(self) -> None:
        super().__init__()
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.observed = False

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
                            if not u:
                                continue
                            self.observed = True
                            self.prompt_tokens += u.get("input_tokens", 0)
                            self.completion_tokens += u.get("output_tokens", 0)
                            self.total_tokens += u.get("total_tokens", 0)
                            return
            if usage:
                self.observed = True
                self.prompt_tokens = usage.get("prompt_tokens", 0)
                self.completion_tokens = usage.get("completion_tokens", 0)
                self.total_tokens = usage.get("total_tokens", 0)
        except Exception:
            pass  # Token counting is best-effort


_CALL_AUDIT = contextvars.ContextVar("screening_call_audit", default=None)
_CALL_PURPOSE = contextvars.ContextVar("screening_call_purpose", default="initial")


async def invoke_with_retry_async(llm, prompt, max_retries=3, delay=1.0):
    """Bounded retries with raw response/usage retained per actual attempt."""
    last_exception = None
    for attempt in range(max_retries):
        started = time.perf_counter()
        event = {"attempt": attempt + 1, "purpose": _CALL_PURPOSE.get(), "stage": "screening", "request_sha256": hashlib.sha256(str(prompt).encode()).hexdigest()}
        try:
            counter = _TokenCounter()
            result = await llm.ainvoke(prompt, config={"callbacks": [counter]})
            cost = {"prompt_tokens": counter.prompt_tokens, "completion_tokens": counter.completion_tokens,
                    "total_tokens": counter.total_tokens, "wall_time_ms": round((time.perf_counter()-started)*1000, 1)}
            event.update(status="ok", raw_response=_result_content_to_string(result), usage=getattr(result,"usage_metadata",None) or (cost if counter.observed else None), response_metadata=getattr(result,"response_metadata",None))
            return result, cost
        except Exception as exc:
            last_exception = exc
            event.update(status="error", error_type=type(exc).__name__)
            if "context_length_exceeded" in str(exc):
                raise
            if attempt < max_retries - 1:
                headers = getattr(getattr(exc,"response",None),"headers",{})
                try:
                    wait = max(delay, float(headers.get("Retry-After",0)))
                except (TypeError, ValueError):
                    wait = delay
                await asyncio.sleep(wait)
                delay *= 2
        finally:
            event['wall_time_ms'] = round((time.perf_counter()-started)*1000, 1)
            audit = _CALL_AUDIT.get()
            if audit:
                path, identities = audit
                path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('a') as handle:
                    handle.write(json.dumps({**event,"record_ids":identities},ensure_ascii=False,default=str)+'\n')
    raise last_exception if last_exception else RuntimeError("No model attempt was scheduled")


async def _screen_individual_prompts(
    *,
    structured_llm: Any,
    batch_papers: list[dict[str, Any]],
    batch_prompts: list[Any],
    output_schema: type,
    thresholds: dict[str, Any] | None,
    stage_mode: str,
    evidence_floor: int,
    prefer_llm_tier: bool,
) -> list[str]:
    """Screen a batch by issuing one model request per paper."""
    tasks = [invoke_with_retry_async(structured_llm, prompt) for prompt in batch_prompts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    single_errors: list[str] = []
    for paper, prompt, result in zip(batch_papers, batch_prompts, results):
        if isinstance(result, Exception):
            single_errors.append(
                f"  ⚠️ Paper failed PMID={paper.get('PMID', 'N/A')}: {str(result)[:100]}"
            )
            _mark_paper_error(paper, result)
            continue
        try:
            decision, cost = result
            _write_cost(paper, cost)
            parsed = _coerce_structured_result(decision, output_schema, strict_5d=prefer_llm_tier)
            _write_parsed_result(
                paper,
                parsed,
                thresholds=thresholds,
                stage_mode=stage_mode,
                evidence_floor=evidence_floor,
                prefer_llm_tier=prefer_llm_tier,
            )
        except Exception as parse_error:
            try:
                retry_result, retry_cost = await invoke_with_retry_async(
                    structured_llm,
                    _contract_correction_prompt(prompt, parse_error, output_schema, require_tier=prefer_llm_tier),
                    max_retries=1,
                )
                _write_cost(paper, retry_cost)
                parsed = _coerce_structured_result(retry_result, output_schema, strict_5d=prefer_llm_tier)
                _write_parsed_result(
                    paper,
                    parsed,
                    thresholds=thresholds,
                    stage_mode=stage_mode,
                    evidence_floor=evidence_floor,
                    prefer_llm_tier=prefer_llm_tier,
                )
            except Exception as retry_error:
                single_errors.append(
                    f"  ⚠️ Paper failed PMID={paper.get('PMID', 'N/A')}: {str(retry_error or parse_error)[:100]}"
                )
                _mark_paper_error(paper, retry_error)
    return single_errors


def _protocol_source(paper: dict[str, Any], content_key: str) -> str:
    """Whitelist source fields; task labels and reference answers never enter evidence."""
    from metaagent.screening.context import bibliographic_context, metadata_text
    context = bibliographic_context(paper)
    fields = {"Title": context["title"], "Official title": metadata_text(paper.get("official_title")), content_key: metadata_text(paper.get(content_key)) or context["abstract"] if content_key != "fulltext" else metadata_text(paper.get("fulltext")),
              "Keywords": context["keywords"], "pub_types": context["pub_types"],
              "mesh_terms": context["mesh_terms"], "language": context["language"],
              "publication_date": context["publication_date"], "Publication Year": context["year"],
              "Authors": context["authors"], "Journal/Book": context["journal"],
              "Create Date": metadata_text(paper.get("Create Date")), "Citation": metadata_text(paper.get("Citation"))}
    text = "\n".join(f"{key}: {value}" for key, value in fields.items() if value)
    if content_key == "fulltext":
        blocks = paper.get("source_blocks") or []
        if isinstance(blocks, list):
            text += "\n" + "\n".join(f"Block {b.get('block_id', i)}: {b.get('text', '')}"
                                            for i, b in enumerate(blocks) if isinstance(b, dict))
    return text


async def _screen_protocol_records(
    papers, llm_model, protocol, *, screening_stage, content_key,
    batch_size, batch_concurrency, batch_mode, audit_path=None, research_question="",
):
    """Execute protocol screening without legacy scores or target-parameter gates."""
    from metaagent.screening.protocol import (
        ProtocolDecision, evidence_source_context, reduce_assessments, render_protocol_messages, validate_protocol,
    )
    validate_protocol(protocol)
    if batch_size < 1 or batch_concurrency < 1:
        raise ValueError("Screening batch size and concurrency must be positive")
    ids = [str(p.get("record_id") or p.get("PMID") or f"row_{i}")
           for i, p in enumerate(papers)]
    if len(ids) != len(set(ids)):
        raise ValueError("Protocol screening requires unique record identities")
    # Source-roster identifiers are transport keys, not study evidence. Blind only
    # these identifiers and map responses back strictly; ordinary IDs stay compatible.
    wire_ids = {identity: ("record_" + hashlib.sha256((str(index) + ":" + identity).encode()).hexdigest()[:20]
                           if identity.startswith("sr:") else identity)
                for index, identity in enumerate(ids)}
    if len(set(wire_ids.values())) != len(ids):
        raise ValueError("Screening model identity collision")
    entries = [(paper, {"record_id": wire_ids[identity], "source": _protocol_source(paper, content_key),
                        "coverage": {key: value for key, value in (paper.get("fulltext_coverage") or {"supplied_content": content_key}).items()
                                     if key in {"complete", "truncated", "missing_materials", "required_materials", "provided_materials", "supplied_content"}}})
               for paper, identity in zip(papers, ids)]
    model = llm_model.bind(response_format={"type": "json_object"})
    semaphore = asyncio.Semaphore(batch_concurrency)
    width = batch_size if batch_mode == "multi" else 1

    async def run(batch):
        async with semaphore:
            for paper, _ in batch:
                paper.pop("criterion_assessments", None)
                paper.pop("protocol_decision", None)
                paper.pop("protocol_error", None)
                paper.pop("evidence_correction", None)
                paper["screening_protocol_version"] = str(protocol["version"])
                paper["screening_execution_mode"] = batch_mode
            for paper, record in batch:
                if str(paper.get("record_id")) != record["record_id"]:
                    paper["screening_model_record_id"] = record["record_id"]
            audit_token = _CALL_AUDIT.set((audit_path,[r['record_id'] for _,r in batch]) if audit_path else None)
            try:
                messages = render_protocol_messages(protocol, [r for _, r in batch],
                                                    screening_stage, multi=batch_mode == "multi", research_question=research_question)
                result, cost = await invoke_with_retry_async(model, messages)
                initial_cost = dict(cost)
                correction_cost = None
                data = result if isinstance(result, dict) else _load_json_data(_result_content_to_string(result))
                values = data.get("records") if batch_mode == "multi" else [data]
                if not isinstance(values, list):
                    raise ValueError("Protocol batch result requires records array")
                parsed = [ProtocolDecision.model_validate(value) for value in values]
                actual = [value.record_id for value in parsed]
                expected = {r["record_id"] for _, r in batch}
                if len(actual) != len(set(actual)) or set(actual) != expected:
                    raise ValueError("Protocol response identities differ from scheduled records")
                # Validate the whole envelope before publishing any decisions. A
                # malformed batch must never become a partial set of exclusions.
                by_id = {value.record_id: value for value in parsed}
                reduced = {r["record_id"]: reduce_assessments(protocol, by_id[r["record_id"]], r["source"], stage=screening_stage, coverage=r["coverage"])
                           for _, r in batch}
                # Correct quote-format mistakes once using the exact same stage
                # source. Grounded criteria are never overwritten by this pass.
                affected = {identity: [a["criterion_id"] for a in result["assessments"]
                                       if "missing_or_unmatched_evidence" in a["validation_flags"]]
                            for identity, result in reduced.items()}
                affected = {identity: names for identity, names in affected.items() if names}
                correction_metadata = {}
                if affected:
                    target = [r for _, r in batch if r["record_id"] in affected]
                    feedback = [{"record_id": r["record_id"], "criteria": [
                        {"criterion_id": a["criterion_id"], "claimed_status": a["status"],
                         "invalid_evidence": a["evidence"], "validation_error": "missing_or_unmatched_evidence",
                         "same_source_locator": evidence_source_context(r["source"], a["evidence"])}
                        for a in reduced[r["record_id"]]["assessments"] if a["criterion_id"] in affected[r["record_id"]]]}
                        for r in target]
                    repair_messages = render_protocol_messages(protocol, target, screening_stage, multi=batch_mode == "multi", research_question=research_question)
                    request = json.loads(repair_messages[1]["content"])
                    request["validation_feedback"] = feedback
                    request["correction_task"] = (
                        "Repair only the listed criterion evidence failures using the SAME record source above. "
                        "Evidence must be an exact short contiguous source quotation, never a criterion description "
                        "or your reasoning. Prefer a sufficient 5-15 word clause; you do not need to repeat the whole "
                        "numerical estimate or uncertainty interval. Copy raw characters exactly, including LaTeX, "
                        "Markdown, punctuation and whitespace: never clean up math or normalize 95% from source notation. "
                        "The same_source_locator is only a navigation hint with raw offsets/context; it does not prove "
                        "eligibility and is not automatically accepted as evidence. Select a short supporting substring "
                        "from the same source, preferably outside noisy math where the claim remains supported. "
                        "If a claim cannot be grounded, set that criterion unknown with empty "
                        "evidence. Return the full declared schema for every listed record. Do not use an abstract "
                        "in place of full text, external knowledge, or invented quotations. There is no further repair pass.")
                    repair_messages[1]["content"] = json.dumps(request, ensure_ascii=False)
                    phase_token = _CALL_PURPOSE.set("evidence_correction")
                    repair_audit_token = _CALL_AUDIT.set((audit_path, [r["record_id"] for r in target]) if audit_path else None)
                    try:
                        repaired, repair_cost = await invoke_with_retry_async(model, repair_messages, max_retries=1)
                        correction_cost = repair_cost
                        repair_data = repaired if isinstance(repaired, dict) else _load_json_data(_result_content_to_string(repaired))
                        repair_values = repair_data.get("records") if batch_mode == "multi" else [repair_data]
                        if not isinstance(repair_values, list):
                            raise ValueError("Correction response requires records array")
                        repair_parsed = [ProtocolDecision.model_validate(value) for value in repair_values]
                        repair_ids = [value.record_id for value in repair_parsed]
                        if len(repair_ids) != len(set(repair_ids)) or set(repair_ids) != set(affected):
                            raise ValueError("Correction identities differ from scheduled records")
                        repaired_by_id = {value.record_id: value for value in repair_parsed}
                        corrected = {}
                        for record in target:
                            identity = record["record_id"]
                            proposal = repaired_by_id[identity]
                            # Validate full criterion membership before selecting
                            # the repairs, so malformed envelopes cannot pass.
                            reduce_assessments(protocol, proposal, record["source"], stage=screening_stage, coverage=record["coverage"])
                            replacements = {a.criterion_id: a for a in proposal.assessments}
                            merged = by_id[identity].model_copy(update={"assessments": [
                                replacements[a.criterion_id] if a.criterion_id in affected[identity] else a
                                for a in by_id[identity].assessments]})
                            corrected[identity] = reduce_assessments(protocol, merged, record["source"], stage=screening_stage, coverage=record["coverage"])
                        for identity, result in corrected.items():
                            reduced[identity] = result
                            remaining = [a["criterion_id"] for a in result["assessments"]
                                         if a["criterion_id"] in affected[identity] and a["effective_status"] == "unknown"]
                            correction_metadata[identity] = {"attempts": 1, "criterion_ids": affected[identity],
                                "status": "unresolved" if remaining else "corrected", "unresolved_criterion_ids": remaining}
                    except Exception as exc:
                        # Invalid repair, transport failure or identity mismatch:
                        # keep the initial evidence-guarded result, not a pass.
                        for identity in affected:
                            correction_metadata[identity] = {"attempts": 1, "criterion_ids": affected[identity],
                                                             "status": "failed", "error_type": type(exc).__name__}
                    finally:
                        _CALL_AUDIT.reset(repair_audit_token)
                        _CALL_PURPOSE.reset(phase_token)
                for paper, record in batch:
                    decision = reduced[record["record_id"]]
                    if record["record_id"] in correction_metadata:
                        paper["evidence_correction"] = correction_metadata[record["record_id"]]
                    # Restore the original transport key after exact model-ID validation.
                    decision["record_id"] = str(paper.get("record_id") or paper.get("PMID") or record["record_id"])
                    paper["protocol_decision"] = decision
                    paper["criterion_assessments"] = decision["assessments"]
                    paper["llm_suggest"] = {"retain": "strong_candidate", "exclude": "unlikely_candidate",
                                            "review": "possible_candidate"}[decision["route"]]
                    paper["llm_tier"] = {"retain": "S", "exclude": "U", "review": "P"}[decision["route"]]
                    paper["overall_justification"] = "Protocol reduction: " + decision["route"]
                    paper["overall_score"] = ""
                    paper["confidence"] = None
                    for dimension in ("disease", "population", "location", "evidence", "parameter"):
                        paper[f"{dimension}_score"] = ""
                        paper[f"{dimension}_justification"] = "Protocol criterion assessments are authoritative"
                    _write_cost_share(paper, initial_cost, len(batch))
                    if record["record_id"] in affected and correction_cost is not None:
                        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                            paper[key] += round(float(correction_cost.get(key) or 0) / len(affected), 2)
                        paper["wall_time_ms"] += correction_cost.get("wall_time_ms") or 0
            except Exception as exc:
                for paper, _ in batch:
                    _mark_paper_error(paper, exc)
                    paper["protocol_error"] = {"type": type(exc).__name__, "message": type(exc).__name__}
            finally:
                _CALL_AUDIT.reset(audit_token)
    await asyncio.gather(*(run(entries[i:i + width]) for i in range(0, len(entries), width)))
    return papers


async def screen_papers_batch_async(
    papers: list[dict[str, Any]],
    research_question: str,
    llm_model: Any,
    batch_size: int = 20,
    batch_concurrency: int = 1,
    batch_mode: str = "single",
    screening_config: Optional[dict[str, Any]] = None,
    screening_stage: str = "title_abstract",
    content_label: str = "Abstract",
    content_key: str = "Abstract",
    content_fallback: str = "(NO ABSTRACT AVAILABLE. Assess supplied metadata under the review criteria; missing information is not affirmative evidence of ineligibility.)",
    strategy: str = "5d",
    prefer_llm_tier: bool = True,
) -> list[dict[str, Any]]:
    """Screen papers in async batches and write decisions onto each paper dict.

    A supplied ``screening_config.review_protocol`` selects criterion-based
    screening and deterministic reduction instead of legacy relevance scores.

    Args:
        strategy: Screening strategy. "5d" uses the five-dimension scoring model;
            "binary" uses a simpler include/exclude decision model.
        prefer_llm_tier: If True (default), use the LLM's own tier classification
            (S/P/U) without numeric score overrides. Missing/invalid tags require
            a bounded contract correction or an explicit error.
    """
    from metaagent.screening.guards import prepare_screening, apply_screening_guards, guide_text
    batch_mode = (batch_mode or "single").strip().lower()
    if batch_mode not in {"single", "multi"}:
        raise ValueError(f"batch_mode must be 'single' or 'multi', got {batch_mode!r}")
    if batch_size < 1 or batch_concurrency < 1:
        raise ValueError("Screening batch size and concurrency must be positive")
    if screening_config and screening_config.get("review_protocol") is not None:
        from .protocol import validate_protocol
        validate_protocol(screening_config["review_protocol"])
    original_papers = papers
    papers = prepare_screening(papers, screening_config, content_key=content_key, stage=screening_stage)
    if not papers:
        return original_papers

    if screening_config and screening_config.get("review_protocol") is not None:
        await _screen_protocol_records(
            papers, llm_model, screening_config["review_protocol"],
            screening_stage=screening_stage, content_key=content_key,
            batch_size=batch_size, batch_concurrency=batch_concurrency, batch_mode=batch_mode,
            audit_path=screening_config.get("call_log"), research_question=research_question,
        )
        apply_screening_guards(papers, screening_config, protocol=True, content_key=content_key, stage=screening_stage)
        return original_papers

    default_config = {
        "research_question": research_question,
        "disease_focus": "The disease/pathogen scope explicitly stated in the research question.",
        "disease_exclude": "Only settings explicitly outside the declared review criteria.",
        "parameter_focus": "The parameter(s) or outcomes in the complete research question.",
        "parameter_exclude": "Only parameter definitions or roles excluded by the declared review criteria.",
        "parameter_scoring_note": (
            "Distinguish this study's own observations or fitted estimates from borrowed fixed inputs and background mentions. "
            "An original model-based estimate is not automatically weaker than directly observed data; apply the task's accepted study types. "
            "At title/abstract screening, missing detail is uncertainty. At full text, verify the source and any task-authorized data form without inventing a model."
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
    if not (is_noguidance or is_baseline):
        system_text += "\n\n" + guide_text()
    if not (is_binary or is_peco):
        parameter_guides = load_parameter_guides(config, config["research_question"])
        if parameter_guides:
            system_text += "\n\n" + parameter_guides.replace("{", "{{").replace("}", "}}")
    if is_peco:
        output_schema = PECODecision
    elif is_binary:
        output_schema = BinaryDecision
    else:
        output_schema = ScreeningDecision

    # Use JSON mode instead of function calling (works with more proxies/models)
    json_schema = output_schema.model_json_schema()
    schema_hint = _build_json_schema_hint(output_schema, require_tier=prefer_llm_tier)
    escaped_schema_hint = schema_hint.replace("{", "{{").replace("}", "}}")
    tier_contract = ('Include an explicit "tier" of S, P or U based on your holistic assessment. Do not calculate a weighted total or derive the tag from numeric thresholds.' if output_schema is ScreeningDecision else "")
    if batch_mode == "multi":
        system_text += (
            "\n\nYou MUST respond with a single JSON object with exactly this top-level shape:\n"
            '{{"papers":[{{"paper_id":"the exact Paper ID from the input","decision":{{...}}}}]}}\n'
            "Return one entry for every input paper, in the same order if possible. "
            "Output valid JSON only, no markdown or extra text.\n"
            "Each decision object must match this schema. For each five-dimension field, "
            'return an object with exactly two keys: "score" (integer 0-4 only, never decimals) '
            'and "justification" (short text). Do not return bare strings for dimension fields. '
            f"{tier_contract}\n"
            f"{escaped_schema_hint}"
        )
    else:
        system_text += (
            "\n\nYou MUST respond with a single JSON object matching this schema. "
            "Output valid JSON only, no other text.\n"
            "For each five-dimension field, return an object with exactly two keys: "
            '"score" (integer 0-4 only, never decimals) and "justification" (short text). '
            'Do not return bare strings for dimension fields. '
            f"{tier_contract}\n"
            f"{escaped_schema_hint}"
        )

    template = ChatPromptTemplate.from_messages(
        [("system", system_text), ("human", user_text)]
    )
    structured_llm = llm_model.bind(response_format={"type": "json_object"})

    all_prompts: list[tuple[dict[str, Any], Any, dict[str, str]]] = []
    from metaagent.screening.context import bibliographic_context, normalize_bibliographic_aliases, metadata_text
    for paper in papers:
        normalize_bibliographic_aliases(paper)
        bibliography = bibliographic_context(paper)
        title = metadata_text(paper.get("Title"))
        content = metadata_text(paper.get(content_key)) or content_fallback
        keywords = bibliography["keywords"] or "(No keywords available)"
        prompt_kwargs: dict[str, str] = {
            "research_question": research_question,
            "title": title,
            "official_title": metadata_text(paper.get("official_title")) or "(Not available)",
            "publication_date": bibliography["publication_date"] or "(Not available)",
            "language": bibliography["language"] or "(Not available)",
            "publication_year": str(paper.get("Publication Year") or "").strip() or "(Not available)",
            "create_date": str(paper.get("Create Date") or "").strip() or "(Not available)",
            "authors": str(paper.get("Authors") or "").strip() or "(Not available)",
            "citation": str(paper.get("Citation") or "").strip() or "(Not available)",
            "journal": str(paper.get("Journal/Book") or "").strip() or "(Not available)",
            "content_label": content_label,
            "content": content,
            "keywords": keywords,
            "pub_types": bibliography["pub_types"] or "(Not available)",
            "mesh_terms": bibliography["mesh_terms"] or "(Not available)",
        }
        prompt = template.format_messages(**prompt_kwargs)
        all_prompts.append((paper, prompt, prompt_kwargs))

    total = len(all_prompts)
    total_batches = (total - 1) // batch_size + 1
    log_every_batches = max(1, total_batches // 20)
    print(
        f"\nScreening {total} papers (batch={batch_size}, concurrency={batch_concurrency}, mode={batch_mode})...\n"
    )

    semaphore = asyncio.Semaphore(max(1, batch_concurrency))
    print_lock = asyncio.Lock()
    completed = 0
    started_at = time.perf_counter()

    async def process_batch(batch_idx: int, batch: list[tuple[dict[str, Any], Any, dict[str, str]]]):
        nonlocal completed
        async with semaphore:
            batch_prompts = [prompt for _, prompt, _ in batch]
            batch_papers = [paper for paper, _, _ in batch]

            should_log = (
                batch_idx == 1
                or batch_idx == total_batches
                or batch_idx % log_every_batches == 0
            )

            try:
                if batch_mode == "multi":
                    batch_content, paper_ids = _build_multi_paper_user_content(
                        [(paper, kwargs) for paper, _, kwargs in batch]
                    )
                    batch_template = ChatPromptTemplate.from_messages(
                        [("system", system_text), ("human", "{batch_content}")]
                    )
                    batch_prompt = batch_template.format_messages(batch_content=batch_content)
                    raw = await invoke_with_retry_async(structured_llm, batch_prompt)
                    decision, cost = raw
                    try:
                        parsed_by_id = _parse_multi_paper_result(decision, output_schema, strict_5d=prefer_llm_tier)
                        if output_schema is ScreeningDecision and prefer_llm_tier:
                            _check_batch_contract(parsed_by_id, paper_ids)
                    except Exception as contract_error:
                        if output_schema is not ScreeningDecision or not prefer_llm_tier:
                            raise
                        decision, retry_cost = await invoke_with_retry_async(
                            structured_llm, _contract_correction_prompt(batch_prompt, contract_error, output_schema), max_retries=1)
                        cost = {key: cost.get(key, 0) + retry_cost.get(key, 0) for key in ("prompt_tokens", "completion_tokens", "total_tokens", "wall_time_ms")}
                        parsed_by_id = _parse_multi_paper_result(decision, output_schema, strict_5d=True)
                        _check_batch_contract(parsed_by_id, paper_ids)
                    missing_ids: list[str] = []
                    for paper, paper_id in zip(batch_papers, paper_ids):
                        parsed = parsed_by_id.get(paper_id)
                        if parsed is None:
                            missing_ids.append(paper_id)
                            _mark_paper_error(paper, ValueError(f"Missing batch result for paper_id={paper_id}"))
                            continue
                        _write_cost_share(paper, cost, len(batch_papers))
                        _write_parsed_result(
                            paper,
                            parsed,
                            thresholds=config.get("thresholds"),
                            stage_mode=stage_mode,
                            evidence_floor=evidence_floor,
                            prefer_llm_tier=prefer_llm_tier,
                        )
                    single_errors = [
                        f"  ⚠️ Paper failed PMID={paper.get('PMID', 'N/A')}: missing batch result"
                        for paper, paper_id in zip(batch_papers, paper_ids)
                        if paper_id in missing_ids
                    ]
                    completed += len(batch_papers)
                else:
                    single_errors = await _screen_individual_prompts(
                        structured_llm=structured_llm,
                        batch_papers=batch_papers,
                        batch_prompts=batch_prompts,
                        output_schema=output_schema,
                        thresholds=config.get("thresholds"),
                        stage_mode=stage_mode,
                        evidence_floor=evidence_floor,
                        prefer_llm_tier=prefer_llm_tier,
                    )
                    completed += len(batch_papers)

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
                if output_schema is ScreeningDecision and prefer_llm_tier:
                    for paper in batch_papers:
                        _mark_paper_error(paper, e)
                    completed += len(batch_papers)
                    async with print_lock:
                        print(f"  [Batch {batch_idx}] Contract/transport failed; {len(batch_papers)} explicit errors")
                    return
                async with print_lock:
                    print(f"  [Batch {batch_idx}] Batch failed: {str(e)[:200]}")
                    print(f"  [Batch {batch_idx}] Retrying individual papers...")
                for paper, prompt, _ in batch:
                    try:
                        raw = await invoke_with_retry_async(structured_llm, prompt)
                        if isinstance(raw, tuple):
                            llm_result, cost = raw
                            _write_cost(paper, cost)
                        else:
                            llm_result = raw
                        parsed = _coerce_structured_result(llm_result, output_schema, strict_5d=prefer_llm_tier)
                        _write_parsed_result(
                            paper,
                            parsed,
                            thresholds=config.get("thresholds"),
                            stage_mode=stage_mode,
                            evidence_floor=evidence_floor,
                            prefer_llm_tier=prefer_llm_tier,
                        )
                    except Exception as e2:
                        async with print_lock:
                            print(
                                f"    Paper failed PMID={paper.get('PMID', 'N/A')}: {str(e2)[:100]}"
                            )
                        _mark_paper_error(paper, e2)
                    finally:
                        completed += 1

    batches = [all_prompts[i : i + batch_size] for i in range(0, total, batch_size)]
    await asyncio.gather(
        *(process_batch(idx + 1, batch) for idx, batch in enumerate(batches))
    )

    elapsed_total = time.perf_counter() - started_at
    rate_total = total / elapsed_total if elapsed_total > 0 else 0.0
    print(
        f"Done: {total} papers in {elapsed_total/60:.1f}min ({rate_total:.1f}/s)"
    )
    apply_screening_guards(papers, screening_config, content_key=content_key, stage=screening_stage,
                           preserve_model_tier=output_schema is ScreeningDecision and prefer_llm_tier)
    return original_papers


def _coerce_structured_result(result: Any, output_schema: type, *, strict_5d: bool = True) -> Any:
    """Normalize provider responses before writing screening fields."""
    if isinstance(result, (BinaryDecision, ScreeningDecision, PECODecision)):
        if strict_5d and isinstance(result, ScreeningDecision):
            _validate_default_5d(result.model_dump())
        return result
    content_str = _result_content_to_string(result)
    return _parse_json_result(content_str, output_schema, strict_5d=strict_5d)


def _result_content_to_string(result: Any) -> str:
    content = getattr(result, "content", "")
    if isinstance(content, list):
        content_str = ""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                content_str += block.get("text", "")
        if not content_str:
            content_str = str(content)
    else:
        content_str = content or str(result)
    return content_str


def _build_multi_paper_user_content(
    papers: list[tuple[dict[str, Any], dict[str, str]]],
) -> tuple[str, list[str]]:
    """Build the user prompt for one API request that screens multiple papers."""
    research_question = papers[0][1].get("research_question", "") if papers else ""
    lines = [
        "Screen each paper independently using the same rubric.",
        f"Research question: {research_question}",
        "Important: Treat each paper as a new, independent case. Do not use evidence, topic signals, or decisions from one paper when judging another paper.",
        "Use the Paper ID exactly as provided.",
        "Return JSON only in this shape:",
        '{"papers":[{"paper_id":"...","decision":{...}}]}',
        "",
        "Papers:",
    ]
    ids: list[str] = []
    seen: set[str] = set()
    for idx, (paper, kwargs) in enumerate(papers, start=1):
        raw_id = (paper.get("PMID") or "").strip() or f"row_{idx}"
        paper_id = raw_id if raw_id not in seen else f"{raw_id}#{idx}"
        seen.add(paper_id)
        ids.append(paper_id)
        lines.extend(
            [
                "",
                f"--- BEGIN PAPER {paper_id} ---",
                f"Paper ID: {paper_id}",
                "Independent case: judge only this paper against the research question above.",
                f"Title: {kwargs.get('title', '')}",
                f"Official title: {kwargs.get('official_title', '(Not available)')}",
                f"Publication Year: {kwargs.get('publication_year', '(Not available)')}",
                f"Publication Date: {kwargs.get('publication_date', '(Not available)')}",
                f"Create Date: {kwargs.get('create_date', '(Not available)')}",
                f"Authors: {kwargs.get('authors', '(Not available)')}",
                f"Citation: {kwargs.get('citation', '(Not available)')}",
                f"Journal/Book: {kwargs.get('journal', '(Not available)')}",
                f"Language: {kwargs.get('language', '(Not available)')}",
                f"Keywords: {kwargs.get('keywords', '')}",
                f"{kwargs.get('content_label', 'Abstract')}: {kwargs.get('content', '')}",
                f"Publication Types: {kwargs.get('pub_types', '(Not available)')}",
                f"MeSH Terms: {kwargs.get('mesh_terms', '(Not available)')}",
                f"--- END PAPER {paper_id} ---",
            ]
        )
    return "\n".join(lines), ids


def _check_batch_contract(parsed, expected_ids):
    if set(parsed) != set(expected_ids):
        raise ValueError(f"Batch IDs differ: missing={sorted(set(expected_ids)-set(parsed))}, extra={sorted(set(parsed)-set(expected_ids))}")


def _parse_multi_paper_result(result: Any, output_schema: type, *, strict_5d: bool = True) -> dict[str, Any]:
    """Parse a multi-paper JSON response into decisions keyed by paper_id."""
    if isinstance(result, dict):
        data = result
    else:
        data = _load_json_data(_result_content_to_string(result))
    papers = data.get("papers") or data.get("results") or data.get("decisions")
    if not isinstance(papers, list):
        raise ValueError("Batch response must contain a 'papers' array")

    parsed: dict[str, Any] = {}
    import json as _json

    for item in papers:
        if not isinstance(item, dict):
            raise ValueError("Each batch response item must be an object")
        paper_id = item.get("paper_id") or item.get("id") or item.get("PMID") or item.get("pmid")
        if not paper_id:
            raise ValueError("Each batch response item must include paper_id")
        decision_data = item.get("decision") or {
            key: value
            for key, value in item.items()
            if key not in {"paper_id", "id", "PMID", "pmid"}
        }
        if output_schema is ScreeningDecision and strict_5d and str(paper_id) in parsed:
            raise ValueError(f"Duplicate paper_id: {paper_id}")
        parsed[str(paper_id)] = _parse_json_result(_json.dumps(decision_data), output_schema, strict_5d=strict_5d)
    return parsed


def _write_parsed_result(
    paper: dict[str, Any],
    parsed: Any,
    *,
    thresholds: dict[str, Any] | None,
    stage_mode: str,
    evidence_floor: int,
    prefer_llm_tier: bool = True,
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
            prefer_llm_tier=prefer_llm_tier,
        )


def _write_structured_result(
    paper: dict[str, Any],
    result: ScreeningDecision,
    *,
    thresholds: dict[str, Any] | None,
    stage_mode: str,
    evidence_floor: int = 1,
    prefer_llm_tier: bool = True,
) -> None:
    paper["llm_suggest"] = classify_screening_decision(
        result,
        thresholds=thresholds,
        stage_mode=stage_mode,
        evidence_floor=evidence_floor,
        prefer_llm_tier=prefer_llm_tier,
    )
    paper["llm_tier"] = result.tier or ""
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


def _write_cost_share(paper: dict[str, Any], cost: dict[str, Any], n_papers: int) -> None:
    """Write approximate per-paper token share for one multi-paper request."""
    n = max(1, n_papers)
    paper["prompt_tokens"] = round(float(cost.get("prompt_tokens", 0)) / n, 2)
    paper["completion_tokens"] = round(float(cost.get("completion_tokens", 0)) / n, 2)
    paper["total_tokens"] = round(float(cost.get("total_tokens", 0)) / n, 2)
    paper["wall_time_ms"] = cost.get("wall_time_ms", 0)


def _build_json_schema_hint(model_class: type, *, require_tier: bool = True) -> str:
    """Build a compact JSON schema description for the LLM prompt."""
    schema = model_class.model_json_schema()
    props = schema.get("properties", {})
    required = list(schema.get("required", []))
    if model_class is ScreeningDecision and require_tier:
        required.append("tier")
    defs = schema.get("$defs", {})
    lines = ["{"]
    for name, prop in props.items():
        if model_class is ScreeningDecision and name == "overall_score":
            continue  # Legacy storage field, not a requested aggregate.
        resolved = _resolve_schema_prop(prop, defs)
        ptype = _schema_type_name(resolved)
        desc = (prop.get("description", "") or "")[:80]
        req = "required" if name in required else "optional"
        if ptype == "object":
            subprops = resolved.get("properties", {})
            sub = ", ".join(
                _format_schema_leaf(sub_key, _resolve_schema_prop(sub_prop, defs))
                for sub_key, sub_prop in subprops.items()
            )
            lines.append(f'  "{name}": {{ {sub} }},  // {req}, {desc}')
        elif ptype == "array":
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


def _validate_default_5d(data: dict[str, Any]) -> None:
    """Validate actual assessments without filling, rounding or inferring scores."""
    for name in ("disease_relevance", "population_relevance", "location_relevance", "original_evidence", "parameter_relevance"):
        item = data.get(name)
        if not isinstance(item, dict) or type(item.get("score")) is not int or not 0 <= item["score"] <= 4:
            raise ValueError(f"{name} requires an explicitly returned integer score from 0 to 4")
        if not isinstance(item.get("justification"), str) or not item["justification"].strip():
            raise ValueError(f"{name} requires its own nonempty justification")
    if not isinstance(data.get("tier"), str) or data["tier"].strip().upper() not in {"S", "P", "U"}:
        raise ValueError("An explicit tier S, P or U is required; scores do not generate a tier")
    if not isinstance(data.get("overall_justification"), str) or not data["overall_justification"].strip():
        raise ValueError("overall_justification must explain the holistic tier")


def _contract_correction_prompt(prompt, error, output_schema, *, require_tier=True):
    from langchain_core.messages import HumanMessage
    schema = _build_json_schema_hint(output_schema, require_tier=require_tier)
    instruction = "Return the complete requested JSON using the SAME supplied source and criteria. Do not invent missing assessments or transfer evidence between papers. For a batch, return every original Paper ID exactly once."
    if output_schema is ScreeningDecision and require_tier:
        instruction += " Use the five assessments and their evidence for your own holistic S/P/U decision, without a weighted total or numeric tier formula."
    return [*prompt, HumanMessage(content="The previous response violated the output contract: " + str(error)[:900] + "\n" + instruction + "\n" + schema)]


def _parse_json_result(content: str, model_class: type, *, strict_5d: bool = True) -> Any:
    """Parse LLM JSON output into a Pydantic model, with fallbacks and field name mapping."""
    data = _load_json_data(content)
    if model_class is ScreeningDecision and strict_5d:
        _validate_default_5d(data)
        return model_class.model_validate(data)

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

    normalized = {}
    for k, v in list(data.items()):
        nk = k.strip().lower().replace(" ", "_").replace("-", "_")
        if nk in normalized and isinstance(v, dict) and isinstance(normalized[nk], dict):
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

    # Convert flat scores (disease:4) to structured objects for 5D
    for dim_name in ["disease_relevance", "population_relevance",
                      "location_relevance", "original_evidence", "parameter_relevance"]:
        if dim_name in data and isinstance(data[dim_name], (int, float, str)):
            try:
                score = int(float(data[dim_name]))
            except (TypeError, ValueError):
                score = _score_from_word(str(data[dim_name]))
            data[dim_name] = {
                "score": score,
                "justification": data.get("overall_justification", ""),
            }

    _remap_5d_aliases(data)
    _convert_flat_5d_scores(data)
    if model_class is ScreeningDecision:
        data.pop("overall_score", None)
        # Historical normalization is available only in explicit legacy mode.
        from .models import llm_tier_to_label
        alias = llm_tier_to_label(data.get("tier"))
        data["tier"] = {"strong_candidate":"S", "possible_candidate":"P", "unlikely_candidate":"U"}.get(alias)
        _fill_missing_5d_dimensions(data)

    return model_class(**data)


def _load_json_data(content: str) -> dict[str, Any]:
    import re
    import json as _json

    data = None
    candidates: list[str] = []
    for text in [_strip_reasoning_blocks(content), content]:
        candidates.extend(
            match.group(1)
            for match in re.finditer(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        )
        candidates.extend(_iter_balanced_json_objects(text))

    # Prefer the last valid object. Models that emit reasoning often mention
    # JSON examples before the final answer.
    for candidate in reversed(candidates):
        try:
            data = _json.loads(candidate)
            break
        except Exception:
            continue
    if data is None:
        try:
            data = _json.loads(content)
        except Exception:
            raise ValueError(f"Could not parse JSON from response: {content[:200]}")
    if not isinstance(data, dict):
        raise ValueError("JSON response must be an object")
    return data


def _strip_reasoning_blocks(content: str) -> str:
    import re

    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)


def _resolve_schema_prop(prop: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in prop:
        ref = str(prop["$ref"])
        if ref.startswith("#/$defs/"):
            key = ref.split("/")[-1]
            return defs.get(key, prop)
        return prop
    if "anyOf" in prop:
        variants = [item for item in prop.get("anyOf", []) if item.get("type") != "null"]
        if len(variants) == 1:
            return _resolve_schema_prop(variants[0], defs)
    return prop


def _schema_type_name(prop: dict[str, Any]) -> str:
    return str(prop.get("type", "object" if "properties" in prop else "any"))


def _format_schema_leaf(name: str, prop: dict[str, Any]) -> str:
    ptype = _schema_type_name(prop)
    if ptype == "integer":
        return f'"{name}": 0'
    if ptype == "number":
        return f'"{name}": 0.0'
    if ptype == "boolean":
        return f'"{name}": true|false'
    return f'"{name}": "..."'


def _iter_balanced_json_objects(content: str) -> list[str]:
    objects: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escape = False
    for idx, ch in enumerate(content):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(content[start : idx + 1])
                start = None
    return objects


def _remap_5d_aliases(data: dict[str, Any]) -> None:
    aliases = {
        "disease": "disease_relevance",
        "disease_relevancy": "disease_relevance",
        "population": "population_relevance",
        "population_relevancy": "population_relevance",
        "location": "location_relevance",
        "location_relevancy": "location_relevance",
        "evidence": "original_evidence",
        "evidence_relevance": "original_evidence",
        "evidence_quality": "original_evidence",
        "original_empirical_evidence": "original_evidence",
        "original_evidence_score": "original_evidence",
        "parameter": "parameter_relevance",
        "parameter_relevancy": "parameter_relevance",
        "target_parameter_relevance": "parameter_relevance",
        "overall": "overall_score",
        "overall_justify": "overall_justification",
    }
    for old_key, new_key in aliases.items():
        if old_key in data and new_key not in data:
            data[new_key] = data.pop(old_key)


def _convert_flat_5d_scores(data: dict[str, Any]) -> None:
    flat_map = {
        "disease_score": "disease_relevance",
        "disease_justification": "disease_relevance",
        "population_score": "population_relevance",
        "population_justification": "population_relevance",
        "location_score": "location_relevance",
        "location_justification": "location_relevance",
        "evidence_score": "original_evidence",
        "evidence_justification": "original_evidence",
        "parameter_score": "parameter_relevance",
        "parameter_justification": "parameter_relevance",
    }
    grouped: dict[str, dict[str, Any]] = {}
    for key, value in list(data.items()):
        dim = flat_map.get(key)
        if not dim:
            continue
        grouped.setdefault(dim, {})
        if key.endswith("_score"):
            grouped[dim]["score"] = _coerce_score(value)
        else:
            grouped[dim]["justification"] = str(value)
    for dim, value in grouped.items():
        if "score" in value:
            value.setdefault("justification", data.get("overall_justification", ""))
            data[dim] = value

    for dim in [
        "disease_relevance",
        "population_relevance",
        "location_relevance",
        "original_evidence",
        "parameter_relevance",
    ]:
        if dim in data and isinstance(data[dim], dict):
            obj = data[dim]
            if "score" in obj:
                obj["score"] = _coerce_score(obj["score"])
            if "justification" not in obj:
                obj["justification"] = str(
                    obj.get("reason")
                    or obj.get("evidence")
                    or data.get("overall_justification", "")
                )


def _fill_missing_5d_dimensions(data: dict[str, Any]) -> None:
    for dim in [
        "disease_relevance",
        "population_relevance",
        "location_relevance",
        "original_evidence",
        "parameter_relevance",
    ]:
        if dim not in data:
            data[dim] = {
                "score": 2,
                "justification": "The model did not explicitly assess this dimension.",
            }
    data.setdefault("overall_justification", "No overall justification provided.")
    data.setdefault("confidence", 0.5)


def _coerce_score(value: Any) -> int:
    if isinstance(value, bool):
        return 4 if value else 0
    try:
        return max(0, min(4, int(float(value))))
    except (TypeError, ValueError):
        return _score_from_word(str(value))


def _score_from_word(value: str) -> int:
    mapping = {
        "high": 4,
        "yes": 4,
        "true": 4,
        "medium": 3,
        "moderate": 3,
        "uncertain": 2,
        "maybe": 2,
        "low": 1,
        "poor": 1,
        "none": 0,
        "no": 0,
        "false": 0,
    }
    return mapping.get(value.strip().lower(), 2)


def _mark_paper_error(paper: dict[str, Any], error: Exception) -> None:
    paper["llm_suggest"] = "error"
    paper["overall_score"] = None
    paper["llm_tier"] = ""
    paper["confidence"] = None
    paper["overall_justification"] = f"LLM error: {str(error)[:200]}"
    for dimension in [
        "disease",
        "population",
        "location",
        "evidence",
        "parameter",
    ]:
        paper[f"{dimension}_score"] = None
        paper[f"{dimension}_justification"] = ""
