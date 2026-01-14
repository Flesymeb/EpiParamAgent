"""Node functions for the experimental LangGraph pipeline.

Each node takes and returns `SearchState`. Keep responsibilities narrow so
you can test/replace pieces without touching existing code.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Iterable
from types import SimpleNamespace
import functools

from .state import SearchState
from .config import load_llm_config, LLMConfig

# Reuse existing clients without altering them
from data_sources.pubmed_client import PubMedClient
from data_sources.eric_client import ERICClient
from data_sources.scoping_client import run_scoping_search, build_scoping_context
from epidemiology.utils import export_records

logger = logging.getLogger(__name__)


# ------------------------
# Helper utilities
# ------------------------


def _ensure_dir(path: Optional[Path]) -> None:
    if path is None:
        return
    path.mkdir(parents=True, exist_ok=True)


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _normalize_record(rec: Dict[str, Any], source: str) -> Dict[str, Any]:
    return {
        "source": source,
        "id": rec.get("id") or "",
        "title": rec.get("title") or "",
        "abstract": rec.get("abstract") or "",
        "authors": rec.get("authors") or [],
        "year": (rec.get("published") or rec.get("year") or ""),
        "doi": rec.get("doi") or "",
        "journal": rec.get("primary_category") or rec.get("journal_ref") or "",
        "raw": rec,
    }


def _dedupe(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for rec in records:
        doi = (rec.get("doi") or "").strip().lower()
        rid = (rec.get("id") or "").strip().lower()
        title = (rec.get("title") or "").strip().lower()
        key = (doi, rid, title)
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def _to_keywordset(terms: Dict[str, Any]):
    """Convert stored dict to an object with attributes for BooleanSearchAgent."""
    if terms is None:
        terms = {}
    prim = terms.get("primary_keywords") or terms.get("primary") or []
    syn = terms.get("synonyms") or []
    rel = terms.get("related_terms") or []
    dom = terms.get("domain_terms") or []
    out = terms.get("outcome_terms") or []
    des = terms.get("design_terms") or []
    pop = terms.get("population_terms") or []
    mea = terms.get("measurement_terms") or []
    ctx = terms.get("context_terms") or []
    return SimpleNamespace(
        primary_keywords=prim,
        synonyms=syn,
        related_terms=rel,
        domain_terms=dom,
        outcome_terms=out,
        design_terms=des,
        population_terms=pop,
        measurement_terms=mea,
        context_terms=ctx,
    )


def _try_llm(model_cfg: LLMConfig):
    """Best-effort LLM constructor. Returns (model, provider_name) or (None, None)."""
    if not model_cfg.model:
        return None, None
    provider = (model_cfg.provider or "").lower()
    base_url = model_cfg.api_base
    try:
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            model = ChatAnthropic(
                model=model_cfg.model,
                api_key=model_cfg.api_key,
                max_tokens=model_cfg.max_tokens or 512,
                temperature=model_cfg.temperature,
                base_url=base_url,
            )
            return model, "anthropic"
        # default to openai-compatible
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=model_cfg.model,
            api_key=model_cfg.api_key,
            max_tokens=model_cfg.max_tokens or 512,
            temperature=model_cfg.temperature,
            base_url=base_url,
        )
        return model, "openai"
    except Exception as e:
        logger.warning("LLM init failed (%s); falling back to no-LLM.", e)
        return None, None


def _json_dump(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sanitize_eric_queries(query_list: List[str]) -> List[str]:
    """Strip quotes only; keep boolean structure intact for ERIC."""
    clean: List[str] = []
    seen = set()

    def add(q: str):
        qn = q.strip()
        if not qn:
            return
        key = qn.lower()
        if key in seen:
            return
        seen.add(key)
        clean.append(qn)

    for q in query_list:
        add(q.replace('"', ""))
    return clean


def _load_autoscreen_prompt(use_multidim: bool = False) -> tuple[str, str]:
    """Load autoscreen prompt from file, fallback to defaults.

    Args:
        use_multidim: If True, loads multi-dimensional screening prompt
    """
    default_system = (
        "You are screening academic abstracts for a literature review. "
        "Think privately and do not reveal chain-of-thought. "
        "Decide inclusion based on the research question and related concepts. "
        "You may include closely related concepts, but exclude unrelated topics."
    )
    default_user = (
        "Research question: {research_question}\n"
        "Key terms: {key_terms}\n"
        "Title: {title}\n"
        "Abstract: {abstract}\n"
        "Year: {year}\n"
        "Return JSON with keys 'decision' (include/exclude) and 'reason' (brief)."
    )

    # Choose prompt file based on screening mode
    prompt_file = "multidim_screening.md" if use_multidim else "autoscreen.md"
    path = Path(__file__).parent / "prompts" / prompt_file

    if not path.exists():
        logger.warning(f"Prompt file not found: {path}, using defaults")
        return default_system, default_user

    try:
        text = path.read_text(encoding="utf-8")
        match = re.search(
            r"\[SYSTEM\](.*?)\[/SYSTEM\].*?\[USER\](.*?)\[/USER\]",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if match:
            system_text = match.group(1).strip() or default_system
            user_text = match.group(2).strip() or default_user
            return system_text, user_text
    except Exception as e:
        logger.warning("Failed to load autoscreen prompt: %s", e)
    return default_system, default_user


def _resolve_year_filter(
    params: Dict[str, Any], provider: Optional[str] = None
) -> Optional[str]:
    """Resolve a year/date filter string from params.

    Supports formats:
    - Year range: "2020-2024" or "2020:2024"
    - Date range: "2020/1/1-2020/10/22" or "2020/1/1:2020/10/22"
    - Single year: "2020"
    - Single date: "2020/1/1"
    """

    def _get(key: str):
        return params.get(key) if params else None

    if provider:
        for key in (
            f"{provider}_year_range",
            f"{provider}_date_range",
            f"{provider}_year",
            f"{provider}_min_year",
            f"{provider}_max_year",
        ):
            if _get(key) is not None:
                break
        else:
            key = None
    else:
        key = None

    if key:
        value = _get(key)
        if key.endswith("_min_year"):
            min_year = _safe_int(value)
            max_year = _safe_int(_get(f"{provider}_max_year")) if provider else None
        elif key.endswith("_max_year"):
            max_year = _safe_int(value)
            min_year = _safe_int(_get(f"{provider}_min_year")) if provider else None
        else:
            # Direct pass-through for date ranges or year ranges
            result = str(value).strip() if value is not None else None
            # Normalize separator: convert colon to dash for consistency
            if result and ":" in result:
                result = result.replace(":", "-")
            return result
    else:
        min_year = _safe_int(_get("min_year"))
        max_year = _safe_int(_get("max_year"))
        if _get("year_range"):
            result = str(_get("year_range")).strip()
            return result.replace(":", "-") if ":" in result else result
        if _get("date_range"):
            result = str(_get("date_range")).strip()
            return result.replace(":", "-") if ":" in result else result
        if _get("year"):
            return str(_get("year")).strip()

    if min_year and max_year:
        return f"{min_year}-{max_year}"
    if min_year:
        return f"{min_year}-{datetime.now().year}"
    if max_year:
        return str(max_year)
    return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_limit(value: Any, default: Optional[int]) -> Optional[int]:
    """Resolve a numeric limit. Returns None for unlimited."""
    if value is None:
        return default
    if isinstance(value, str) and value.strip().lower() in {"all", "none", "unlimited"}:
        return None
    intval = _safe_int(value)
    if intval is None:
        return default
    if intval <= 0:
        return None
    return intval


# ------------------------
# Nodes
# ------------------------


def scoping_search(state: SearchState, **_: Any) -> SearchState:
    """Optional scoping search (web) to enrich term discovery."""
    if not state.params.get("use_scoping"):
        return state

    providers = state.params.get("scoping_providers") or ["tavily", "serper"]
    if isinstance(providers, str):
        providers = [p.strip() for p in providers.split(",") if p.strip()]
    max_results = _safe_int(state.params.get("scoping_max_results")) or 5
    max_items = _safe_int(state.params.get("scoping_max_items")) or 8
    max_chars = _safe_int(state.params.get("scoping_max_chars")) or 1600

    results = run_scoping_search(
        state.research_question,
        providers=providers,
        max_results=max_results,
        tavily_api_key=state.params.get("tavily_api_key"),
        serper_api_key=state.params.get("serper_api_key"),
    )
    state.scoping_results = results
    state.scoping_context = build_scoping_context(
        results,
        max_items=max_items,
        max_chars=max_chars,
    )

    state.metrics.setdefault("scoping", {})
    state.metrics["scoping"].update(
        {
            "enabled": True,
            "providers": providers,
            "results": len(results),
        }
    )

    if state.workdir:
        _ensure_dir(state.workdir / "cache")
        _json_dump(
            state.workdir / "cache" / "scoping.json",
            {
                "providers": providers,
                "results": results,
                "context": state.scoping_context,
            },
        )
    return state


def generate_terms(state: SearchState, **_: Any) -> SearchState:
    """Generate a controlled term set using existing KeywordGeneratorAgent."""
    research_question = state.research_question
    domain = state.domain
    state.metrics.setdefault("llm_calls", {})

    # Initialize a default workdir if not provided so caches/exports are persisted.
    if state.workdir is not None and not isinstance(state.workdir, Path):
        state.workdir = Path(state.workdir)
    if state.workdir is None:
        base = Path(os.getenv("LITERATURE_WORKDIR", Path.cwd() / "langgraph_runs"))
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        state.workdir = base / f"run_{ts}"
        state.workdir.mkdir(parents=True, exist_ok=True)
        state.metrics["workdir"] = str(state.workdir)
        logger.debug("Initialized workdir at %s", state.workdir)

    try:
        from epidemiology.keyword_generator import KeywordGeneratorAgent

        agent = KeywordGeneratorAgent()
        scoping_context = state.scoping_context or state.params.get("scoping_context")
        kw = agent.generate(
            research_query=research_question,
            domain=domain,
            context=scoping_context,
        )
        state.terms = kw.to_dict()
        state.metrics["llm_calls"]["keyword_generator"] = {
            "status": "ok",
            "provider": os.getenv("LLM_PROVIDER") or "unknown",
        }
    except Exception as e:
        logger.warning("KeywordGeneratorAgent failed (%s); falling back.", e)
        state.terms = {
            "primary_keywords": [research_question],
            "synonyms": [],
            "related_terms": [],
            "domain_terms": [],
        }
        state.metrics["llm_calls"]["keyword_generator"] = {
            "status": "fallback",
            "error": str(e),
        }

    # Cache terms if requested
    if state.workdir:
        _ensure_dir(state.workdir / "cache")
        terms_path = state.workdir / "cache" / "terms.json"
        with terms_path.open("w", encoding="utf-8") as f:
            json.dump(state.terms, f, ensure_ascii=False, indent=2)
    return state


def build_queries(state: SearchState, **_: Any) -> SearchState:
    """Build per-source boolean queries using BooleanSearchAgent."""
    state.metrics.setdefault("llm_calls", {})
    try:
        from epidemiology.boolean_search_agent import BooleanSearchAgent
    except Exception as e:
        logger.warning("BooleanSearchAgent import failed (%s); using fallback.", e)
        BooleanSearchAgent = None  # type: ignore

    kw_obj = _to_keywordset(state.terms)
    queries: Dict[str, List[str]] = {}
    llm_cfg = load_llm_config(state.params)
    llm_model, _ = _try_llm(llm_cfg)
    use_llm_queries = bool(state.params.get("use_llm_queries", True))
    include_single_terms = bool(state.params.get("include_single_terms", False))
    apply_wildcards = bool(state.params.get("apply_wildcards", True))
    wildcard_map = state.params.get("wildcard_map")
    use_seed_queries = bool(state.params.get("use_seed_queries", False))
    eric_force_rule = bool(state.params.get("eric_force_rule_queries", False))
    pubmed_field = state.params.get("pubmed_field", "all")
    llm_iterations = _safe_int(state.params.get("llm_query_iterations")) or 3
    llm_min_queries = _safe_int(state.params.get("llm_min_queries")) or 5
    llm_query_mode = (state.params.get("llm_query_mode") or "").strip().lower()
    llm_term_groups = state.params.get("llm_term_groups")
    llm_term_limits = state.params.get("llm_term_limits")
    llm_prompt_hint = state.params.get("llm_query_prompt_hint")

    if isinstance(llm_term_groups, str):
        llm_term_groups = [g.strip() for g in llm_term_groups.split(",") if g.strip()]
    if llm_query_mode in {"epi", "epidemiology", "epi_three_facet"}:
        if not llm_term_groups:
            llm_term_groups = ["primary_keywords", "synonyms"]
        if not llm_term_limits:
            llm_term_limits = {
                "primary_keywords": 6,
                "synonyms": 8,
            }
        if not llm_prompt_hint:
            llm_prompt_hint = (
                "CRITICAL: Use STRUCTURED multi-facet AND logic, not flat OR lists.\n"
                "REQUIRED STRUCTURE (for operational delays like isolation delay):\n"
                "  (Disease OR Pathogen) AND (Time/Interval OR Delay) AND (Action/Event OR Setting)\n"
                "EXAMPLE:\n"
                "  (COVID-19 OR SARS-CoV-2) AND (interval OR delay OR latency) AND (isolation OR quarantine OR containment)\n"
                "BANNED STRUCTURE:\n"
                "  (COVID-19 OR SARS-CoV-2 OR isolation OR delay OR interval OR ...) [TOO BROAD]\n"
                "Each facet must be required via AND. Use OR only within facets for synonyms.\n"
                "Generate 3-5 queries with different facet combinations, NOT 10+ with same flat structure."
            )

    class _LLMAdapter:
        def __init__(self, model):
            self._model = model

        def _call_llm(self, messages):
            return self._model.invoke(messages)

    for provider in state.providers:
        if BooleanSearchAgent:
            agent = BooleanSearchAgent(
                provider=provider,
                max_queries=state.params.get("max_queries", 12),
                include_single_terms=include_single_terms,
                apply_wildcards=apply_wildcards,
                wildcard_map=wildcard_map,
                pubmed_field=pubmed_field,
            )
            try:
                use_llm = use_llm_queries and llm_model
                if provider == "eric" and eric_force_rule:
                    use_llm = False
                if use_llm:
                    qlist = agent.generate_queries_using_llm(
                        kw_obj,
                        agent=_LLMAdapter(llm_model),
                        research_query=state.research_question,
                        prompt_hint=llm_prompt_hint,
                        iterations=llm_iterations,
                        min_queries=llm_min_queries,
                        term_groups=llm_term_groups,
                        term_limits=llm_term_limits,
                    )
                    state.metrics["llm_calls"][f"queries_{provider}"] = {
                        "status": "ok_llm"
                    }
                else:
                    qlist = agent.generate_queries(kw_obj)
                    state.metrics["llm_calls"][f"queries_{provider}"] = {
                        "status": "ok_rule"
                    }
            except Exception as e:
                logger.warning("Query generation failed for %s: %s", provider, e)
                qlist = []
        else:
            qlist = []

        # Merge search queries from KeywordGeneratorAgent (if any)
        seed_queries = state.terms.get("search_queries", []) if state.terms else []
        if BooleanSearchAgent and seed_queries and use_seed_queries:
            formatted = []
            for q in seed_queries:
                if q and isinstance(q, str):
                    formatted.append(agent._format(q))  # type: ignore[attr-defined]
            qlist.extend(formatted)

        # Dedupe while preserving order
        seen = set()
        deduped = []
        for q in qlist:
            key = str(q).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(q)
        qlist = deduped

        # Fallback to a simple query if none produced
        if not qlist:
            core = (
                kw_obj.primary_keywords[0]
                if kw_obj.primary_keywords
                else state.research_question
            )
            qlist = [core]
            state.metrics["llm_calls"][f"queries_{provider}"] = {"status": "fallback"}
        queries[provider] = qlist

    state.queries = queries

    # Post-process ERIC queries to avoid phrase/position errors
    if "eric" in state.queries:
        state.queries["eric"] = _sanitize_eric_queries(state.queries["eric"])

    if state.workdir:
        _ensure_dir(state.workdir / "cache")
        with (state.workdir / "cache" / "queries.json").open(
            "w", encoding="utf-8"
        ) as f:
            json.dump(queries, f, ensure_ascii=False, indent=2)
    return state


def retrieve_pubmed(state: SearchState, *, retmax: int = 500, **_: Any) -> SearchState:
    """Call PubMed and store raw records.

    By default (no params specified), retrieves ALL results.
    To limit results, explicitly set pubmed_retmax in params.
    """
    if "pubmed" not in state.providers:
        return state
    query_list = state.queries.get("pubmed") or []
    if not query_list:
        logger.warning("PubMed query missing; skip.")
        return state

    no_limits = bool(state.params.get("no_limits"))

    # Default behavior: no limit unless explicitly specified
    # If user provides pubmed_retmax, use it; otherwise None (unlimited)
    if no_limits:
        total_limit = None
    elif "pubmed_retmax" in state.params:
        # User explicitly specified a limit
        total_limit = _resolve_limit(state.params.get("pubmed_retmax"), None)
    else:
        # No explicit limit → unlimited
        total_limit = None

    per_query_limit = (
        None
        if no_limits
        else _resolve_limit(state.params.get("pubmed_per_query_limit"), None)
    )
    if per_query_limit is None and total_limit is not None:
        per_query_limit = max(1, total_limit // max(1, len(query_list)))

    # Get medline_only setting from params (default False to include all PubMed records)
    # Note: PubMed-not-MEDLINE articles can be high quality (e.g., Frontiers journals)
    # and often contain epidemiological studies. Use False to maximize recall.
    medline_only = state.params.get("include_medline_only", False)
    client = PubMedClient(medline_only=medline_only)
    year_filter = _resolve_year_filter(state.params, "pubmed")
    totals = state.metrics.setdefault("provider_totals", {}).setdefault("pubmed", {})
    collected: List[Any] = []
    for query in query_list:
        papers = client.search(query=query, retmax=per_query_limit, year=year_filter)
        total_hits = client.last_total
        if total_hits is not None:
            totals[str(query)] = {"total": total_hits}
        for p in papers:
            if total_limit is None or len(collected) < total_limit:
                collected.append(p)
        # keep running all queries even if total cap reached

    recs = [p.to_dict() for p in collected]

    if state.workdir:
        _ensure_dir(state.workdir / "cache")
        _write_jsonl(state.workdir / "cache" / "raw_pubmed.jsonl", recs)
    return {"pubmed_records": recs}


def retrieve_eric(
    state: SearchState, *, limit: int = 50, enrich_doi: bool = True, **_: Any
) -> SearchState:
    """Call ERIC and store raw records."""
    if "eric" not in state.providers:
        return state
    base_queries = state.queries.get("eric") or []
    if not base_queries:
        logger.warning("ERIC query missing; skip.")
        return state

    no_limits = bool(state.params.get("no_limits"))
    max_results = (
        None
        if no_limits
        else _resolve_limit(state.params.get("eric_limit", limit), limit)
    )
    enrich = state.params.get("eric_enrich_doi", enrich_doi)
    client = ERICClient()
    year_filter = _resolve_year_filter(state.params, "eric")
    totals = state.metrics.setdefault("provider_totals", {}).setdefault("eric", {})
    collected: List[Any] = []

    # Use queries as generated (after quote stripping); no extra token splitting.
    candidate_queries = list(base_queries)
    use_variants = bool(state.params.get("eric_use_variants", False))

    def _search_query(q: str, remaining: int):
        # Search ERIC for a query; optionally try safer variants.
        if not use_variants:
            try:
                papers = client.search(
                    query=q,
                    limit=remaining,
                    year=year_filter,
                    enrich_doi=enrich,
                )
                return papers, q, client.last_total
            except Exception as e:
                logger.warning("ERIC search failed for %s: %s", q, e)
                return [], q, client.last_total

        variants = [q]
        if '"' in q:
            variants.append(q.replace('"', ""))
        if " " in q and '"' not in q:
            variants.append(" AND ".join(part for part in q.split() if part.strip()))
        variants.append(f'title:"{q}"')
        # last resort: primary keyword
        core = state.terms.get("primary_keywords", []) if state.terms else []
        if core:
            variants.append(core[0])

        for v in variants:
            try:
                papers = client.search(
                    query=v,
                    limit=remaining,
                    year=year_filter,
                    enrich_doi=enrich,
                )
                total_hits = client.last_total
                if papers:
                    logger.debug(
                        "ERIC hit with query variant: %s (n=%s, total=%s)",
                        v,
                        len(papers),
                        total_hits,
                    )
                    return papers, v, total_hits
            except Exception as e:
                logger.warning("ERIC search failed for %s: %s", v, e)
        return [], q, client.last_total

    per_query_limit = (
        None
        if no_limits
        else _resolve_limit(state.params.get("eric_per_query_limit"), None)
    )
    if per_query_limit is None and max_results is not None:
        per_query_limit = max(1, max_results // max(1, len(candidate_queries)))

    for q in candidate_queries:
        papers, used_query, total_hits = _search_query(q, per_query_limit)
        if total_hits is not None:
            totals[str(q)] = {"total": total_hits, "used_query": used_query}
        for p in papers:
            if max_results is None or len(collected) < max_results:
                collected.append(p)

    recs = [p.to_dict() for p in collected]

    if state.workdir:
        _ensure_dir(state.workdir / "cache")
        _write_jsonl(state.workdir / "cache" / "raw_eric.jsonl", recs)
    return {"eric_records": recs}


def _process_screening_batch(
    prompts_and_records: List[Tuple[Dict[str, Any], Any]],
    llm_model: Any,
    use_multidim: bool,
    dimension_weights: Optional[Dict] = None,
    aggregation_config: Optional[Dict] = None,
    batch_size: int = 10,
    included: List[Dict] = None,
    excluded: List[Dict] = None,
) -> None:
    """批量处理LLM筛选，使用并行API调用提升速度

    Args:
        prompts_and_records: List of (record, prompt) tuples
        llm_model: LLM model instance
        use_multidim: Whether to use multi-dimensional scoring
        dimension_weights: Weights for dimensions
        aggregation_config: Aggregation configuration
        batch_size: Number of records per batch
        included: List to append included records
        excluded: List to append excluded records
    """
    import asyncio
    from typing import List as TypingList

    if included is None:
        included = []
    if excluded is None:
        excluded = []

    # 分批处理
    for i in range(0, len(prompts_and_records), batch_size):
        batch = prompts_and_records[i : i + batch_size]
        batch_prompts = [prompt for _, prompt in batch]
        batch_records = [rec for rec, _ in batch]

        try:
            if use_multidim:
                # 多维度评分批处理
                from screening.dimension_scoring import EpiDimensionScores

                structured_llm = llm_model.with_structured_output(EpiDimensionScores)

                # 使用batch调用
                results = structured_llm.batch(batch_prompts)

                for rec, result in zip(batch_records, results):
                    try:
                        # 计算分数
                        result.calculate_overall_score(weights=dimension_weights)
                        if result.recommendation is None:
                            thresholds = aggregation_config.get("thresholds", {})
                            result.calculate_recommendation(
                                high_threshold=thresholds.get("include", 0.70),
                                maybe_threshold=thresholds.get("maybe", 0.40),
                            )

                        # 存储结果
                        rec["dimension_scores"] = result.get_dimension_summary()
                        rec["dimension_rationales"] = result.rationales or {}
                        rec["overall_score"] = result.overall_score
                        rec["screen_decision"] = (
                            result.recommendation.lower()
                            if result.recommendation
                            else "maybe"
                        )
                        rec["screen_reason"] = (
                            f"multidim_score={result.overall_score:.2f}"
                        )
                        rec["confidence"] = result.confidence

                        # 分类
                        if result.recommendation in ["INCLUDE", "MAYBE"]:
                            included.append(rec)
                        else:
                            excluded.append(rec)
                    except Exception as e:
                        logger.warning(
                            f"Processing failed for record {rec.get('id')}: {e}"
                        )
                        rec["screen_reason"] = f"llm_error:{e}"
                        rec["screen_decision"] = "include"
                        rec["overall_score"] = None
                        included.append(rec)
            else:
                # 二分类批处理
                import json as _json

                results = llm_model.batch(batch_prompts)

                for rec, resp in zip(batch_records, results):
                    try:
                        content = str(resp.content).strip()
                        decision = "include"
                        reason = "llm_pass"

                        match = re.search(r"\{.*\}", content, re.DOTALL)
                        payload = _json.loads(match.group(0) if match else content)
                        decision = str(payload.get("decision", decision)).lower()
                        reason = str(payload.get("reason", reason))
                        study_design = payload.get("study_design", "unknown")

                        rec["screen_reason"] = reason
                        rec["screen_decision"] = decision
                        rec["study_design"] = study_design

                        if decision == "include":
                            included.append(rec)
                        else:
                            excluded.append(rec)
                    except Exception as e:
                        logger.warning(
                            f"Parsing failed for record {rec.get('id')}: {e}"
                        )
                        if "exclude" in content.lower():
                            decision = "exclude"
                            excluded.append(rec)
                        else:
                            rec["screen_reason"] = f"llm_error:{e}"
                            rec["screen_decision"] = "include"
                            included.append(rec)

        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            # Fallback: 标记所有记录为失败并纳入
            for rec in batch_records:
                rec["screen_reason"] = f"batch_error:{e}"
                rec["screen_decision"] = "include"
                included.append(rec)

        logger.info(
            f"Processed batch {i//batch_size + 1}/{(len(prompts_and_records)-1)//batch_size + 1}"
        )


def normalize_and_dedupe(state: SearchState, **_: Any) -> SearchState:
    """Normalize schema and dedupe across all sources."""
    # Merge per-source records into raw_records for downstream use
    raw_records = dict(state.raw_records)
    if state.pubmed_records:
        raw_records["pubmed"] = state.pubmed_records
    if state.eric_records:
        raw_records["eric"] = state.eric_records
    state.raw_records = raw_records

    normalized: List[Dict[str, Any]] = []
    for source, recs in state.raw_records.items():
        for r in recs:
            normalized.append(_normalize_record(r, source))
    state.normalized_records = normalized
    state.deduped_records = _dedupe(normalized)
    # Metrics
    state.metrics["raw_counts"] = {s: len(v) for s, v in state.raw_records.items()}
    state.metrics["raw_total"] = len(normalized)
    state.metrics["deduped"] = len(state.deduped_records)
    if state.workdir:
        _json_dump(
            state.workdir / "cache" / "metrics_normalize.json",
            {
                "raw_counts": state.metrics["raw_counts"],
                "raw_total": state.metrics["raw_total"],
                "deduped": state.metrics["deduped"],
            },
        )
    return state


def autoscreen_and_export(
    state: SearchState,
    *,
    min_year: Optional[int] = None,
    export_dir: Optional[Path] = None,
    use_multidim_screening: Optional[bool] = None,
) -> SearchState:
    """Screen records using rule-based filtering and optional LLM screening.

    Args:
        state: Current search state
        min_year: Minimum publication year (excludes older papers)
        export_dir: Directory for export files
        use_multidim_screening: If True, uses multi-dimensional relevance scoring
            instead of binary include/exclude. If None, reads from params.
    """
    if min_year is None:
        min_year = state.params.get("min_year")
    if export_dir is None:
        export_dir = state.workdir / "outputs" if state.workdir else None
    if use_multidim_screening is None:
        use_multidim_screening = state.params.get("use_multidim_screening", False)

    included: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    llm_cfg = load_llm_config(state.params)
    llm_model, llm_provider = _try_llm(llm_cfg)

    def _passes_rules(rec: Dict[str, Any]) -> bool:
        year = None
        yval = rec.get("year")
        try:
            if isinstance(yval, str):
                if len(yval) >= 4 and yval[:4].isdigit():
                    year = int(yval[:4])
            elif isinstance(yval, int):
                year = yval
        except Exception:
            year = None
        if min_year and year and year < min_year:
            rec["screen_reason"] = "year_lt_min"
            rec["screen_decision"] = "exclude"
            return False
        return True

    # Rule-based first pass
    rule_passed: List[Dict[str, Any]] = []
    for rec in state.deduped_records:
        if _passes_rules(rec):
            rule_passed.append(rec)
        else:
            excluded.append(rec)

    # Optional LLM screening
    if llm_model and state.params.get("llm_screen"):
        try:
            from langchain_core.prompts import ChatPromptTemplate
        except Exception as e:
            logger.warning("LLM screening skipped (langchain_core missing: %s)", e)
            llm_model = None

    if llm_model and state.params.get("llm_screen"):
        # Load dimension criteria if using multi-dimensional screening
        dimensions_text = ""
        dimension_weights = None
        aggregation_config = None

        if use_multidim_screening:
            try:
                from screening.dimension_loader import load_and_format_dimensions
                from screening.dimension_scoring import EpiDimensionScores

                dimensions_text, dimension_weights, aggregation_config = (
                    load_and_format_dimensions(include_weights=False)
                )
                logger.info(
                    "Multi-dimensional screening enabled with 7 evaluation dimensions"
                )
            except Exception as e:
                logger.error(f"Failed to load dimension config: {e}")
                logger.info("Falling back to binary screening")
                use_multidim_screening = False

        system_text, user_text = _load_autoscreen_prompt(
            use_multidim=use_multidim_screening
        )

        # Inject dimensions into prompt if multi-dimensional
        if use_multidim_screening and dimensions_text:
            user_text = user_text.replace("{dimensions_with_criteria}", dimensions_text)

        template = ChatPromptTemplate.from_messages(
            [
                ("system", system_text),
                ("human", user_text),
            ]
        )

        # 批处理配置
        batch_size = state.params.get("autoscreen_batch_size", 10)
        use_batch = state.params.get("use_batch_screening", True)

        # 准备所有prompts和对应的records
        key_terms = []
        if state.terms:
            key_terms = (
                state.terms.get("primary_keywords", [])
                + state.terms.get("synonyms", [])
                + state.terms.get("related_terms", [])
            )
        key_terms = [str(t) for t in key_terms if t]
        key_terms = key_terms[:20]
        key_terms_str = ", ".join(key_terms)

        all_prompts = []
        for rec in rule_passed:
            prompt = template.format_messages(
                research_question=state.research_question,
                key_terms=key_terms_str,
                title=rec.get("title", ""),
                abstract=rec.get("abstract", ""),
                year=str(rec.get("year") or ""),
            )
            all_prompts.append((rec, prompt))

        # 批量处理或串行处理
        if use_batch and len(all_prompts) > 5:
            logger.info(f"Using batch screening with batch_size={batch_size}")
            _process_screening_batch(
                all_prompts,
                llm_model,
                use_multidim_screening,
                dimension_weights,
                aggregation_config,
                batch_size,
                included,
                excluded,
            )
        else:
            logger.info("Using serial screening")
            for rec, prompt in all_prompts:
                try:
                    if use_multidim_screening:
                        # Use structured output with Pydantic model
                        try:
                            structured_llm = llm_model.with_structured_output(
                                EpiDimensionScores
                            )
                            result = structured_llm.invoke(prompt)

                            # Calculate scores
                            result.calculate_overall_score(weights=dimension_weights)

                            # Calculate recommendation if not already set
                            if result.recommendation is None:
                                thresholds = aggregation_config.get("thresholds", {})
                                result.calculate_recommendation(
                                    high_threshold=thresholds.get("include", 0.70),
                                    maybe_threshold=thresholds.get("maybe", 0.40),
                                )

                            # Store dimension scores in record
                            rec["dimension_scores"] = result.get_dimension_summary()
                            rec["dimension_rationales"] = result.rationales or {}
                            rec["overall_score"] = result.overall_score
                            rec["screen_decision"] = (
                                result.recommendation.lower()
                                if result.recommendation
                                else "maybe"
                            )
                            rec["screen_reason"] = (
                                f"multidim_score={result.overall_score:.2f}"
                            )
                            rec["confidence"] = result.confidence

                            # Classify into included/excluded based on recommendation
                            if result.recommendation in ["INCLUDE", "MAYBE"]:
                                included.append(rec)
                            else:
                                excluded.append(rec)

                        except Exception as e:
                            logger.warning(
                                f"Structured output failed for record {rec.get('id')}: {e}"
                            )
                            # Fail-open: include with error marker
                            rec["screen_reason"] = f"llm_error:{e}"
                            rec["screen_decision"] = "include"
                            rec["overall_score"] = None
                            included.append(rec)

                    else:
                        # Binary screening (original logic)
                        resp = llm_model.invoke(prompt)
                        content = str(resp.content).strip()
                        decision = "include"
                        reason = "llm_pass"
                        try:
                            import json as _json

                            match = re.search(r"\{.*\}", content, re.DOTALL)
                            payload = _json.loads(match.group(0) if match else content)
                            decision = str(payload.get("decision", decision)).lower()
                            reason = str(payload.get("reason", reason))
                        except Exception:
                            if "exclude" in content.lower():
                                decision = "exclude"
                        rec["screen_reason"] = reason
                        rec["screen_decision"] = decision
                        if decision == "include":
                            included.append(rec)
                        else:
                            excluded.append(rec)

                except Exception as e:
                    logger.error(
                        f"LLM screening failed for record {rec.get('id')}: {e}"
                    )
                    rec["screen_reason"] = f"llm_error:{e}"
                    rec["screen_decision"] = "include"
                    included.append(rec)  # fail-open

        state.metrics.setdefault("llm_calls", {})["screening"] = {
            "status": "ok",
            "provider": llm_provider,
            "mode": "multidimensional" if use_multidim_screening else "binary",
        }
    else:
        for rec in rule_passed:
            rec["screen_reason"] = rec.get("screen_reason") or "rule_pass"
            rec["screen_decision"] = rec.get("screen_decision") or "include"
        included.extend(rule_passed)

    state.included = included
    state.excluded = excluded
    state.metrics["included"] = len(included)
    state.metrics["excluded"] = len(excluded)
    state.metrics["excluded_reasons"] = {
        "year_lt_min": len(
            [r for r in excluded if r.get("screen_reason") == "year_lt_min"]
        )
    }
    # Persist timing fields into metrics for export/debugging
    timings = {}
    for key, val in vars(state).items():
        if key.startswith("timing_") and val is not None:
            timings[key] = val
    if timings:
        state.metrics["timings"] = timings

    if export_dir:
        _ensure_dir(export_dir)
        _write_jsonl(export_dir / "included.jsonl", included)
        _write_jsonl(export_dir / "excluded.jsonl", excluded)
        # Also export a compact CSV/JSON via existing util
        try:
            export_records(
                included,
                export_dir,
                "included_records",
                metadata={"metrics": state.metrics},
            )
        except Exception as e:
            logger.warning("export_records failed: %s", e)
    if state.workdir:
        _json_dump(state.workdir / "cache" / "metrics_screen.json", state.metrics)
    return state
