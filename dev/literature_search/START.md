# MetaAgent Literature Search - Run Guide

## 1) Create and activate the environment

(Ubuntu)

```bash
cd ~/ailab/Meta-Analysis/MetaAgent/dev/literature_search
uv venv .venv
source ./.venv/bin/activate
```

(PowerShell)

```powershell
cd D:\AILab\MAS\Meta-Analysis\MetaAgent\dev\literature_search
uv venv .venv
.\.venv\Scripts\Activate.ps1
```

## 2) Install dependencies

Make sure you have `uv` installed, then run:

```bash
uv sync
# Optional: install extra/dev providers
uv sync --extra extra-providers
uv sync --dev
```

This command will:

- Create a local virtual environment (.venv)
- Install all dependencies exactly as locked in uv.lock

something maybe useful on Windows:

```powershell
uv pip install -U pip wheel
uv pip install -e .[extra-providers]
```

## 3) Configure environment variables

Make sure `.env` exists at:

```
MetaAgent/dev/literature_search/.env
```

At minimum for LLM + LangSmith:

```
LLM_PROVIDER=openai
LLM_MODEL=openai/gpt-4.1
LLM_API_KEY=sk-or-...
LLM_API_BASE=https://openrouter.ai/api/v1

LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=metaagent_literature_search
LANGSMITH_TRACING=true
```

For PubMed:

```
NCBI_EMAIL=you@example.com
NCBI_API_KEY=...
```

## 4) Start the LangGraph server

```powershell
langgraph dev --allow-blocking
```

You will get URLs like:

```
API: http://127.0.0.1:2024
Studio: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

## 5) Run a query (Studio -> View Raw)

```json
{
  "research_question": "I want to explore the studies of theory of mind in children",
  "params": {
    "pubmed_retmax": 80,
    "pubmed_per_query_limit": 10,
    "eric_limit": 80,
    "eric_per_query_limit": 10,
    "min_year": 2000
  }
}
```

```json
{
  "research_question": "You're the first user, I need to write an article on Navigating the Promise and Pitfalls of Large Language Models in Philosophical Transactions of the Royal Society A in Agent-Based Modeling, please help me find some articles for my research.",
  "domain": "Large Language Models in Agent-Based Modeling",
  "providers": [
    "pubmed",
    "eric"
  ],
  "params": {
    "pubmed_retmax": 500,
    "pubmed_per_query_limit": 50,
    "eric_limit": 500,
    "eric_per_query_limit": 50,
    "min_year": 2000,
    "use_llm_queries": true,
    "max_queries": 15,
    "llm_screen": true
  }
}
```

```json
{
  "research_question": "Early Numeracy and Mathematics Development: A Longitudinal Meta-Analysis on the Predictive Nature of Early Numeracy",
  "domain": "developmental_psychology",
  "providers": [
    "pubmed",
    "eric"
  ],
  "params": {
    "pubmed_retmax": 200,
    "pubmed_per_query_limit": 40,
    "eric_limit": 200,
    "eric_per_query_limit": 40,
    "min_year": 2000,
    "use_llm_queries": true,
    "max_queries": 12,
    "include_single_terms": false,
    "use_seed_queries": false,
    "apply_wildcards": true,
    "eric_force_rule_queries": true,
    "no_limits": true,
    "use_scoping": true,
    "scoping_providers": [
      "tavily",
      "serper"
    ],
    "scoping_max_results": 5
  }
}
```

## 6) Outputs

Runs are saved under:

```
MetaAgent/dev/literature_search/langgraph_runs/
```

Each run contains:

- `cache/terms.json`, `cache/queries.json`
- `cache/raw_pubmed.jsonl`, `cache/raw_eric.jsonl`
- `outputs/included.jsonl`, `outputs/excluded.jsonl`
- `cache/metrics_screen.json` (includes timings)
