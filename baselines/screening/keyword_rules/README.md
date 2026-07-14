# Keyword-Rule Screening Baseline

Non-LLM baseline for title/abstract screening. A record is selected when the
configured metadata fields contain at least one disease term and at least one
parameter term. Optional policies exclude review-like publication text.

Run:

```bash
python baselines/screening/keyword_rules/run.py
```

Default outputs:

- `baselines/screening/keyword_rules/results/rule_based_baselines.csv`
- `baselines/screening/keyword_rules/results/rule_based_baselines.md`

The implementation delegates to the canonical rule code in
`tools/scripts/rule_based_screening_baselines.py` so existing paper-facing
outputs can still be regenerated from the old path.
