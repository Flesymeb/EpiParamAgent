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


def _load_autoscreen_prompt() -> tuple[str, str]:
    """Load autoscreen prompt from default file, fallback to defaults."""
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

    path = Path(__file__).parent / "prompts" / "autoscreen.md"

    if not path.exists():
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
    """Resolve a year filter string from params (supports per-provider overrides)."""

    def _get(key: str):
        return params.get(key) if params else None

    if provider:
        for key in (
            f"{provider}_year_range",
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
            return str(value).strip() if value is not None else None
    else:
        min_year = _safe_int(_get("min_year"))
        max_year = _safe_int(_get("max_year"))
        if _get("year_range"):
            return str(_get("year_range")).strip()
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
        logger.info("Initialized workdir at %s", state.workdir)

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
                        prompt_hint=None,
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


def retrieve_pubmed(state: SearchState, *, retmax: int = 50, **_: Any) -> SearchState:
    """Call PubMed and store raw records."""
    if "pubmed" not in state.providers:
        return state
    query_list = state.queries.get("pubmed") or []
    if not query_list:
        logger.warning("PubMed query missing; skip.")
        return state

    no_limits = bool(state.params.get("no_limits"))
    total_limit = (
        None
        if no_limits
        else _resolve_limit(state.params.get("pubmed_retmax", retmax), retmax)
    )
    per_query_limit = (
        None
        if no_limits
        else _resolve_limit(state.params.get("pubmed_per_query_limit"), None)
    )
    if per_query_limit is None and total_limit is not None:
        per_query_limit = max(1, total_limit // max(1, len(query_list)))

    client = PubMedClient()
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
                    logger.info(
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
) -> SearchState:
    """Simple rules-based screening placeholder; swap with your own logic/LLM."""
    if min_year is None:
        min_year = state.params.get("min_year")
    if export_dir is None:
        export_dir = state.workdir / "outputs" if state.workdir else None

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
        system_text, user_text = _load_autoscreen_prompt()
        template = ChatPromptTemplate.from_messages(
            [
                ("system", system_text),
                ("human", user_text),
            ]
        )
        for rec in rule_passed:
            try:
                key_terms = []
                if state.terms:
                    key_terms = (
                        state.terms.get("primary_keywords", [])
                        + state.terms.get("synonyms", [])
                        + state.terms.get("related_terms", [])
                    )
                key_terms = [str(t) for t in key_terms if t]
                key_terms = key_terms[:20]
                prompt = template.format_messages(
                    research_question=state.research_question,
                    key_terms=", ".join(key_terms),
                    title=rec.get("title", ""),
                    abstract=rec.get("abstract", ""),
                    year=str(rec.get("year") or ""),
                )
                resp = llm_model.invoke(prompt)
                content = str(resp.content).strip()
                decision = "include"
                reason = "llm_pass"
                try:
                    import re
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
                rec["screen_reason"] = f"llm_error:{e}"
                rec["screen_decision"] = "include"
                included.append(rec)  # fail-open
        state.metrics.setdefault("llm_calls", {})["screening"] = {
            "status": "ok",
            "provider": llm_provider,
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
