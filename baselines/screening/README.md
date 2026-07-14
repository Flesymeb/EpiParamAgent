# Screening Baselines

This folder keeps reproducible first-pass screening baselines separate from the
main MetaAgent 5D workflow. The baselines are intentionally weaker or simpler
than the proposed method: they use title/abstract metadata, short prompts, and
binary include/exclude outputs rather than 5D S/P/U scoring.

## Implemented Baselines

| Baseline | Folder | Status | Role |
| --- | --- | --- | --- |
| Keyword rules | `keyword_rules/` | runnable without LLM | Non-LLM retrieval-style baseline using disease and parameter terms. |
| BM25 | `bm25/` | runnable without LLM | Traditional sparse-retrieval baseline over title/abstract text. The default query uses short disease-parameter terms, and the cutoff uses matched per-review MetaAgent workload rather than GT-tuned thresholds. |
| Neural retrieval | `neural_retrieval/` | runnable with local `torch`/`transformers` | No-training dense retrieval baselines using PubMedBERT, BioBERT, and SPECTER embeddings with the same matched-workload cutoff as BM25. |
| LEADS-Minimal | `leads_minimal/` | runnable with OpenAI-compatible endpoint | Minimal prompt on `zifeng-ai/leads-mistral-7b-v1`; frozen results already exist under `evaluation/`. |
| AgentSLR-style ScreenPrompt Lite | `agent_slr_screenprompt_lite/` | runnable with OpenAI-compatible endpoint | Short adaptation of AgentSLR/ScreenPrompt abstract-screening style to this benchmark. Not an official AgentSLR reproduction. |
| ReviewCopilot-style GPT screening | `reviewcopilot_style/` | runnable with OpenAI-compatible endpoint | ReviewCopilot-inspired title/abstract screening prompt with `include`/`unclear`/`exclude` decisions; manual keyword exclusions are disabled. |
| ReviewCopilot-minimal binary screening | `reviewcopilot_minimal/` | runnable with OpenAI-compatible endpoint | Weaker prompt-only baseline using only review question, title, and abstract; no profile-specific criteria or unclear class. |

## Related-Work Screening Decision

LEADS is the most direct model baseline already used in the manuscript because
it is a systematic-review literature-mining model with citation screening and
extraction tasks. AgentSLR is important related work for epidemiological SLR
automation, but its official benchmark covers WHO priority pathogens and a
full pipeline from retrieval to report generation. A direct numerical comparison
against official AgentSLR results would mix datasets and endpoints. The safer
screening-only comparison is therefore an AgentSLR-style prompt adaptation run
on our frozen COVID-19/mpox source-review profiles.

ASReview and related active-learning tools are relevant for background but are
not implemented here as a first-pass baseline because their core workflow is
interactive prioritization with reviewer-provided labels and a stopping rule,
not zero-shot title/abstract inclusion on the full raw pool.

## Common Dataset

All baselines target the frozen screening benchmark:

- `dataset/{disease}/screening/{topic}/p{project}/raw.csv`
- `dataset/{disease}/screening/{topic}/p{project}/ground_truth.csv`

The current freeze note is `dataset/SCREENING_DATASET_FREEZE_20260508.md`.

## Summary Table

The normal no-endpoint path runs deterministic keyword and BM25 baselines and
refreshes the unified summary:

```bash
python baselines/screening/run_all.py
```

To only resolve LLM baseline paths without model calls:

```bash
python baselines/screening/run_all.py --llm-dry-run
```

After running the keyword baseline manually, regenerate the unified screening
summary:

```bash
python baselines/screening/summarize.py
```

Optional no-training dense retrieval baselines are explicit because they require
local `torch` and `transformers`:

```bash
python baselines/screening/neural_retrieval/run.py --models pubmedbert biobert specter
python baselines/screening/summarize.py
```

Default outputs:

- `baselines/screening/results/screening_baseline_summary.csv`
- `baselines/screening/results/screening_baseline_summary.md`

ScreenPrompt Lite and ReviewCopilot-style/minimal outputs are auto-discovered
only when they are complete disease-level, non-dry-run runs. Smoke tests,
`--limit` runs, and single-profile runs are intentionally ignored by the
unified summary unless you pass an explicit `--screenprompt-summary`,
`--reviewcopilot-summary`, or `--reviewcopilot-minimal-summary` to
`summarize.py`.

For LLM baselines, the shared runner resolves settings in this order:
explicit CLI arguments, process env (`LEADS_ENDPOINT`/`LLM_API_BASE`/
`OPENAI_API_BASE`, `LEADS_API_KEY`/`LLM_API_KEY`/`OPENAI_API_KEY`,
`LEADS_MODEL`/`LLM_MODEL`/`OPENAI_MODEL`), then the project `.env.local` via
`metaagent.config.load_llm_config(module_hint="screening")`, then local vLLM
fallbacks. The LEADS-Minimal wrapper pins `zifeng-ai/leads-mistral-7b-v1` by
default so the baseline label matches the actual model; pass `--model` or set
`LEADS_MODEL` to use a different served LEADS-compatible model.

Full LLM reruns are explicit:

```bash
python baselines/screening/run_all.py --run-llm
```

If the endpoint supports `/chat/completions` but blocks `/models`, use:

```bash
python baselines/screening/run_all.py --run-llm --allow-missing-endpoint
```

In that mode the orchestrator passes `--no-check-server` to the LLM baseline
runner and lets the chat-completion calls determine whether the endpoint is
usable.
