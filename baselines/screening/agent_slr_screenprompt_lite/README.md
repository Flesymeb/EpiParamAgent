# AgentSLR-Style ScreenPrompt Lite Baseline

AgentSLR is strong related work for epidemiological systematic-literature-review
automation. Its official abstract-screening prompt follows a ScreenPrompt-like
structure with study objectives, inclusion/exclusion criteria, reasoning
instructions, article metadata, and structured output.

This baseline is a lightweight adaptation for our frozen COVID-19/mpox screening
profiles. It is **not** an official AgentSLR reproduction and should be reported
as `AgentSLR-style ScreenPrompt Lite`.

The prompt is intentionally short and weaker than MetaAgent 5D:

```text
You are screening title/abstract records for an epidemiology systematic review.
Review question: {research_question}

Include if the paper appears to study {disease} and may report data, estimates,
or analysis relevant to {parameter}. Exclude if it is clearly unrelated, a
review/editorial/protocol, or only mentions the topic without usable evidence.
If uncertain from the title/abstract, include.

Title: {title}
Abstract: {abstract}

Return JSON only: {"include": true/false, "reason": "short"}
```

Run with any OpenAI-compatible endpoint:

```bash
python baselines/screening/agent_slr_screenprompt_lite/run.py --disease covid19 --profiles all
python baselines/screening/agent_slr_screenprompt_lite/run.py --disease mpox --profiles all
```

Smoke check without model calls:

```bash
python baselines/screening/agent_slr_screenprompt_lite/run.py --disease covid19 --profiles P13 --dry-run
```

The runner reuses `tools/scripts/leads_mistral_screening_eval.py` with
`--prompt-style screenprompt_lite`, so outputs follow the existing screening
experiment layout under `evaluation/experiments/<experiment>/screening/`.
