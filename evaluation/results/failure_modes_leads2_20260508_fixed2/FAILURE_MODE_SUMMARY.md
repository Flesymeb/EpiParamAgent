# LEADS-Minimal Frozen-Dataset Result

Updated: 2026-05-08

This file supersedes the previous LEADS-2 failure-mode report for paper-facing
results. The old LEADS-2 snapshot was generated before the 2026-05-08 dataset
freeze and should remain internal/historical only.

## Official Inputs

- Method name for paper tables: `LEADS` or `LEADS-Minimal`
- Dataset freeze: 2026-05-08
- Profiles: 22 screening profiles
- Raw rows: 12,758
- GT rows: 668
- Summary file: `evaluation/leads_mistral_freeze_leads_minimal_summary.csv`
- Prediction file: `evaluation/leads_mistral_freeze_leads_minimal_predictions.csv`
- Prompt sweep: `evaluation/leads_mistral_freeze_prompt_sweep_micro_summary.csv`

The formal result uses `disease_parameter_minimal`, a minimal title/abstract
prompt that provides only the disease and parameter.

## Prompt

```text
I am screening papers for a systematic review about {disease} and {parameter}.
Based on the title and abstract, decide include or exclude.

Title: {title}
Abstract: {abstract}

Return JSON only: {"include": true/false, "reason": "short"}
```

## Main Table Metrics

| Scope | GT/N | Predicted include | TP | FP | FN | TN | Recall | Precision | F1 | Workload reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| COVID-19 | 561/8913 | 5341 | 501 | 4840 | 60 | 3512 | 0.893 | 0.094 | 0.170 | 0.401 |
| mpox | 107/3845 | 1485 | 86 | 1399 | 21 | 2339 | 0.804 | 0.058 | 0.108 | 0.614 |
| Overall | 668/12758 | 6826 | 587 | 6239 | 81 | 5851 | 0.879 | 0.086 | 0.157 | 0.465 |

## Derived Screening Burden

| Scope | NNS | False discovery rate |
| --- | ---: | ---: |
| COVID-19 | 10.66 | 0.906 |
| mpox | 17.27 | 0.942 |
| Overall | 11.63 | 0.914 |

## Analysis Status

The old failure-type tables and examples were generated from the pre-freeze
LEADS-2 snapshot and are not valid as paper-facing LEADS-Minimal error
analysis. If a new failure-mode report is needed, recompute labels from
`ground_truth_include` and `predicted_include` in
`evaluation/leads_mistral_freeze_leads_minimal_predictions.csv`.
