# LEADS-Minimal Screening Baseline

This baseline uses the LEADS-Mistral systematic-review model with a deliberately
minimal disease-plus-parameter prompt. It is the paper-facing LEADS screening
baseline on the frozen dataset.

Prompt:

```text
I am screening papers for a systematic review about {disease} and {parameter}.
Based on the title and abstract, decide include or exclude.

Title: {title}
Abstract: {abstract}

Return JSON only: {"include": true/false, "reason": "short"}
```

Run against an OpenAI-compatible endpoint serving `zifeng-ai/leads-mistral-7b-v1`:

```bash
python baselines/screening/leads_minimal/run.py --disease covid19 --profiles all
python baselines/screening/leads_minimal/run.py --disease mpox --profiles all
```

Useful smoke check without calling the model:

```bash
python baselines/screening/leads_minimal/run.py --disease covid19 --profiles P13 --dry-run
```

Existing frozen outputs:

- `evaluation/leads_mistral_freeze_leads_minimal_summary.csv`
- `evaluation/leads_mistral_freeze_leads_minimal_predictions.csv`
- `evaluation/leads_mistral_freeze_prompt_sweep_summary.md`
