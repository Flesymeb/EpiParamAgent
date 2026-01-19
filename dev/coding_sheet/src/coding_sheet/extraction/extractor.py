from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Type, Union

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from .config import LLMConfig, load_llm_config
from .parsing import parse_json_records
from .prompting import SYSTEM_PROMPT, USER_PROMPT, FIELD_DESCRIPTIONS, examples_as_json
from .chunking import chunk_text
from .evidence_pack import (
    select_evidence_chunk_ids,
    format_chunks_as_sources_xml,
)
from .fulltext_processor import process_fulltext, ProcessedDocument
from ..schema import CodingSheetRecord, ExtractionBatch, ExtractionResult, Paper
from ..config_schema import ProjectConfig, load_config, get_model
from ..prompt_factory import (
    build_system_prompt,
    build_user_prompt,
    build_full_context_system_prompt,
    build_full_context_user_prompt,
)

logger = logging.getLogger(__name__)


def extract_batch(
    papers: list[dict[str, Any]] | list[Paper],
    *,
    params: Optional[dict[str, Any]] = None,
    llm: Any = None,
    max_fulltext_chars: int = 8000,
    config: Optional[Union[str, Path, ProjectConfig]] = None,
) -> ExtractionBatch:
    """Extract coding-sheet records from a batch of papers.

    Args:
        papers: List of paper dicts or Paper objects
        params: Optional LLM config overrides
        llm: Optional pre-configured LLM instance
        max_fulltext_chars: Max chars of fulltext to pass
        config: Schema configuration - can be:
            - None: uses legacy CodingSheetRecord (default, backward compatible)
            - str: template name ("correlation") or path to YAML config
            - Path: path to YAML config file
            - ProjectConfig: loaded configuration object

    Returns:
        ExtractionBatch with results for each paper
    """
    model_cfg = load_llm_config(params)
    chat = llm or _init_llm(model_cfg)

    # Load schema configuration if provided
    if config is not None:
        if isinstance(config, ProjectConfig):
            project_config = config
        else:
            project_config = load_config(config)
        record_model = get_model(project_config)
        use_config_mode = True
    else:
        # Legacy mode: use hardcoded CodingSheetRecord
        project_config = None
        record_model = CodingSheetRecord
        use_config_mode = False

    paper_objs: list[Paper] = [
        p if isinstance(p, Paper) else Paper.from_dict(p) for p in papers
    ]

    results: list[ExtractionResult] = []
    needs_review = 0
    total_records = 0

    for i, paper in enumerate(paper_objs, 1):
        if not paper.id or not paper.title:
            results.append(
                ExtractionResult(
                    paper_id=paper.id or f"paper_{i}",
                    paper_title=paper.title or "(missing title)",
                    status="failed",
                    errors=["Paper is missing id/title"],
                )
            )
            continue

        res = _extract_one(
            paper,
            chat=chat,
            model_name=model_cfg.model,
            provider=model_cfg.provider,
            max_fulltext_chars=max_fulltext_chars,
            project_config=project_config,
            record_model=record_model,
        )
        results.append(res)

        for r in res.records:
            total_records += 1
            if r.needs_review:
                needs_review += 1

    successful = sum(1 for r in results if r.status == "success")
    failed = len(results) - successful

    return ExtractionBatch(
        model=model_cfg.model,
        provider=model_cfg.provider,
        total_papers=len(results),
        successful_papers=successful,
        failed_papers=failed,
        total_records=total_records,
        needs_review=needs_review,
        results=results,
    )


def _init_llm(cfg: LLMConfig):
    if not cfg.provider or not cfg.model:
        raise RuntimeError(
            "Missing LLM config. Set LLM_PROVIDER and LLM_MODEL (and API key)."
        )

    provider = (cfg.provider or "").lower()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=cfg.model,
            api_key=cfg.api_key,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.api_base,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
    )


def _should_retry_llm_error(exception):
    """Determine if an LLM API error should be retried.

    Retry on:
    - Network errors (ConnectionError, TimeoutError)
    - Temporary API errors (429 rate limit, 500/502/503/504 server errors)

    Do NOT retry on:
    - Authentication errors (401, 403)
    - Payment errors (402)
    - Invalid request errors (400, 404)
    """
    # Network errors should always retry
    if isinstance(exception, (ConnectionError, TimeoutError)):
        return True

    # Check for OpenAI/OpenRouter APIStatusError
    try:
        from openai import APIStatusError

        if isinstance(exception, APIStatusError):
            status_code = exception.status_code
            # Retry on temporary server errors and rate limits
            if status_code in (429, 500, 502, 503, 504):
                return True
            # Don't retry on client errors
            return False
    except ImportError:
        pass

    # For other exceptions, don't retry
    return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_should_retry_llm_error),
    reraise=True,
)
def _call_llm(chat, messages):
    return chat.invoke(messages)


def _extract_one(
    paper: Paper,
    *,
    chat: Any,
    model_name: Optional[str],
    provider: Optional[str],
    max_fulltext_chars: int,
    project_config: Optional[ProjectConfig] = None,
    record_model: Type[BaseModel] = CodingSheetRecord,
) -> ExtractionResult:
    res = ExtractionResult(paper_id=paper.id, paper_title=paper.title)

    # Determine extraction mode
    extraction_mode = "chunked"  # default
    if project_config is not None:
        extraction_mode = project_config.extraction.mode

    if extraction_mode == "full_context":
        # Full-context mode: use entire document with table markers
        return _extract_full_context(
            paper=paper,
            chat=chat,
            model_name=model_name,
            project_config=project_config,
            record_model=record_model,
            res=res,
        )
    else:
        # Chunked mode: original behavior
        return _extract_chunked(
            paper=paper,
            chat=chat,
            model_name=model_name,
            max_fulltext_chars=max_fulltext_chars,
            project_config=project_config,
            record_model=record_model,
            res=res,
        )


def _extract_chunked(
    paper: Paper,
    *,
    chat: Any,
    model_name: Optional[str],
    max_fulltext_chars: int,
    project_config: Optional[ProjectConfig],
    record_model: Type[BaseModel],
    res: ExtractionResult,
) -> ExtractionResult:
    """Extract using chunked mode (original behavior)."""
    full_text = (paper.full_text or "").strip()
    if len(full_text) > max_fulltext_chars:
        full_text = full_text[:max_fulltext_chars] + "\n\n[... truncated ...]"

    # Build evidence chunks and select a compact evidence pack.
    evidence_text = full_text or (paper.abstract or "")
    # Use larger chunk size for tables, more chunks for better coverage
    chunks = chunk_text(evidence_text, max_chars=2000, overlap_chars=200)
    chosen_ids = select_evidence_chunk_ids(chunks, top_k=15, neighbor_hops=1)
    sources_xml = format_chunks_as_sources_xml(chunks, chosen_ids)

    # Build prompts - use config-driven or legacy mode
    if project_config is not None:
        # Prepare metadata
        metadata = {}
        if paper.doi:
            metadata["doi"] = paper.doi
        if paper.year:
            metadata["year"] = paper.year

        system = build_system_prompt(project_config)
        user = build_user_prompt(
            project_config,
            title=paper.title,
            abstract=(paper.abstract or "")[:2000],
            sources_xml=sources_xml,
            metadata=metadata if metadata else None,
        )
    else:
        # Legacy mode
        system = SYSTEM_PROMPT.format(
            field_descriptions=FIELD_DESCRIPTIONS,
        )
        user = USER_PROMPT.format(
            title=paper.title,
            abstract=(paper.abstract or "")[:2000],
            sources_xml=sources_xml,
            examples=examples_as_json(),
        )

    return _call_and_parse(
        chat=chat,
        system=system,
        user=user,
        model_name=model_name,
        record_model=record_model,
        res=res,
        paper=paper,
        extraction_mode="chunked",
        chunks=chunks,
    )


def _extract_full_context(
    paper: Paper,
    *,
    chat: Any,
    model_name: Optional[str],
    project_config: ProjectConfig,
    record_model: Type[BaseModel],
    res: ExtractionResult,
) -> ExtractionResult:
    """Extract using full-context mode."""
    # Process full text with table marking
    max_chars = project_config.extraction.max_input_chars
    truncation_marker = project_config.extraction.truncation_marker

    processed = process_fulltext(
        markdown=paper.full_text or "",
        max_chars=max_chars,
        truncation_marker=truncation_marker,
    )

    if processed.was_truncated:
        logger.info(
            f"Document truncated: {processed.truncated_chars} chars omitted "
            f"(original: {processed.total_chars})"
        )

    # Build full-context prompts
    # Prepare metadata
    metadata = {}
    if paper.doi:
        metadata["doi"] = paper.doi
    if paper.year:
        metadata["year"] = paper.year

    system = build_full_context_system_prompt(project_config)
    user = build_full_context_user_prompt(
        project_config,
        title=paper.title,
        abstract=paper.abstract or "",
        full_text=processed.content,
        tables_summary=processed.tables_summary,
        was_truncated=processed.was_truncated,
        metadata=metadata if metadata else None,
    )

    return _call_and_parse(
        chat=chat,
        system=system,
        user=user,
        model_name=model_name,
        record_model=record_model,
        res=res,
        paper=paper,
        extraction_mode="full_context",
        chunks=None,
    )


def _call_and_parse(
    *,
    chat: Any,
    system: str,
    user: str,
    model_name: Optional[str],
    record_model: Type[BaseModel],
    res: ExtractionResult,
    paper: Paper,
    extraction_mode: str,
    chunks: Optional[list] = None,
) -> ExtractionResult:
    """Call LLM and parse results (shared by both modes)."""
    try:
        # Prefer LangChain message objects when available
        try:
            from langchain_core.messages import SystemMessage, HumanMessage

            messages: Any = [SystemMessage(content=system), HumanMessage(content=user)]
        except Exception:
            messages = system + "\n\n" + user

        resp = _call_llm(chat, messages)
        text = getattr(resp, "content", None) or str(resp)

        # Log finish reason if available (to debug truncation)
        finish_reason = getattr(resp, "response_metadata", {}).get("finish_reason")
        if finish_reason:
            logger.info(f"LLM finish_reason: {finish_reason}")

        res.raw_llm_output = text

        raw_records = parse_json_records(text)
        if not raw_records:
            res.status = "failed"
            preview = (text or "").strip().replace("\r", "")
            preview = preview[:800] + ("..." if len(preview) > 800 else "")
            res.errors.append("Failed to parse JSON from LLM output")
            if preview:
                res.errors.append(f"LLM output preview: {preview}")
            return res

        for idx, rd in enumerate(raw_records, 1):
            try:
                rd = dict(rd)
                rd.setdefault("source_id", paper.id)
                rd.setdefault("source_doi", paper.doi)
                rd.setdefault("source_database", paper.source)
                rd.setdefault("extractor_model", model_name)
                rd.setdefault("extraction_mode", extraction_mode)

                # Use the appropriate model for validation
                record = record_model.model_validate(rd)

                # Validate evidence_chunk_ids for chunked mode
                if (
                    extraction_mode == "chunked"
                    and chunks
                    and record.evidence_chunk_ids
                ):
                    valid_ids = [
                        cid
                        for cid in record.evidence_chunk_ids
                        if 0 <= cid < len(chunks)
                    ]
                    if len(valid_ids) < len(record.evidence_chunk_ids):
                        invalid_ids = [
                            cid
                            for cid in record.evidence_chunk_ids
                            if cid not in valid_ids
                        ]
                        logger.warning(
                            f"Record {idx}: Invalid chunk IDs {invalid_ids} (max={len(chunks)-1})"
                        )
                        record.evidence_chunk_ids = valid_ids

                res.records.append(record)
            except Exception as e:
                res.errors.append(f"Record {idx} validation failed: {e}")
                continue

        res.status = "success" if res.records else "failed"
        if not res.records:
            res.errors.append("No valid records after validation")

        return res

    except Exception as e:
        res.status = "failed"
        res.errors.append(str(e))
        logger.exception("Extraction failed for %s", paper.id)
        return res
