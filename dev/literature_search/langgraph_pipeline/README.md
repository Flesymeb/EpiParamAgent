# LangGraph-based experimental pipeline (isolated)

This folder holds an experimental LangGraph pipeline for literature search. It does **not** modify existing code under `src/`. You can wire it up or discard it without touching the current workflow.

## Design (4 blocks, reusing existing agents/clients)
1) **Keywords**: uses `KeywordGeneratorAgent` (falls back to minimal terms on error; cached to `cache/terms.json`).  
2) **Boolean Queries**: uses `BooleanSearchAgent` per source (fallback query if LLM fails; cached to `cache/queries.json`).  
3) **Retrieval (fan-out)**: calls `PubMedClient` / `ERICClient` (reuses your existing implementations) and optionally caches raw JSONL.  
4) **Integration**: normalize schema, dedupe, rules screening (min_year), optional LLM screening (`llm_screen`), export via `export_records`, metrics to `cache/metrics_*.json`.

## Files
- `state.py` — lightweight state dataclass used by nodes.
- `nodes.py` — node functions (generate terms/queries, retrieve PubMed/ERIC, normalize+dedupe, simple screening).
- `graph.py` — LangGraph wiring (guarded import; fails fast with a helpful error if `langgraph` is absent).

## Usage (example)
```bash
cd MetaAgent/dev/literature_search
# ensure langgraph is installed: pip install langgraph
python - <<'PY'
from pathlib import Path
from langgraph_pipeline.graph import build_graph, run_once

g = build_graph()
state = run_once(
    g,
    research_question="theory of mind in preschool children",
    workdir="langgraph_runs/example1",  # optional cache/output
    params={
        "pubmed_retmax": 5,
        "eric_limit": 5,
        "min_year": 2000,
        # Query controls:
        # "include_single_terms": False,
        # "use_seed_queries": False,
        # "apply_wildcards": True,
        # "eric_force_rule_queries": True,
        # "no_limits": True,  # set to True (or *_limit=0) to fetch all results
        # Optional scoping (web) to enrich terms (not formal retrieval):
        # "use_scoping": True,
        # "scoping_providers": ["tavily", "serper"],
        # "scoping_max_results": 5,
        # "tavily_api_key": "...",  # or set TAVILY_API_KEY
        # "serper_api_key": "...",  # or set SERPER_API_KEY
        # Optional LLM screening (requires LLM_MODEL/API key envs):
        # "llm_screen": True,
        # "llm_model": "gpt-3.5-turbo",
        # "llm_provider": "openai",
    },
)
print("raw", {k: len(v) for k, v in state.raw_records.items()})
print("deduped", len(state.deduped_records))
print("included", len(state.included))
print("outputs:", (Path("langgraph_runs/example1") / "outputs").resolve())
PY
```

Environment variables respected (same as existing clients):
- `NCBI_API_KEY`, `NCBI_EMAIL` for PubMed
- `ERIC_API_BASE`, `CROSSREF_MAILTO`, `CROSSREF_DOI_LOOKUP_MAX` for ERIC
- LLM: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_API_BASE` (for OpenRouter use `LLM_PROVIDER=openai`, `LLM_API_BASE=https://openrouter.ai/api/v1`, and your OpenRouter key)

Notes
- Retrieval uses existing `PubMedClient` and `ERICClient` (no changes to your current code).  
- Queries/terms are cached to `workdir/cache` when `workdir` is provided; raw records cached likewise.  
- Screening: rules (min_year) + optional LLM triage (`llm_screen`, `llm_model`, `llm_provider`, `llm_api_key`). Fail-open if LLM fails.  
- Optional scoping (Tavily/Serper) is for terminology discovery only; keep it separate from formal retrieval.  
- Nothing in `src/` is modified; this is an isolated experiment scaffold.  
