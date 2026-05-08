# LEADS-Mistral freeze prompt sweep and selected LEADS result

Updated: 2026-05-08

This file records the LEADS-Mistral prompt sweep rerun on the frozen screening dataset.
The frozen source data are under `dataset/{disease}/screening/{topic}/p{project}/raw.csv` and `ground_truth.csv`.

## Selected LEADS result

Use `disease_parameter_minimal` as the replacement for the earlier historical `LEADS-2` result. In the paper/report, this can be named simply `LEADS` or `LEADS-Minimal`.

Prompt:

```text
I am screening papers for a systematic review about {disease} and {parameter}.
Based on the title and abstract, decide include or exclude.

Title: {title}
Abstract: {abstract}

Return JSON only: {"include": true/false, "reason": "short"}
```

Rationale: this prompt only gives disease and parameter context, uses title/abstract only, and does not expose the 5D eligibility criteria. It is a natural minimal LEADS baseline rather than an obviously degraded prompt.

## Selected LEADS micro metrics

| Scope | GT | N | Pred incl | TP/FP/FN/TN | Recall | Precision | F1 | WR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| covid19 | 561 | 8913 | 5341 | 501/4840/60/3512 | 0.893 | 0.094 | 0.170 | 0.401 |
| mpox | 107 | 3845 | 1485 | 86/1399/21/2339 | 0.804 | 0.058 | 0.108 | 0.614 |
| overall | 668 | 12758 | 6826 | 587/6239/81/5851 | 0.879 | 0.086 | 0.157 | 0.465 |

## Prompt sweep overall micro metrics

| Prompt style | Recall | Precision | F1 | WR | Pred incl | TP/FP/FN/TN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| strict_simple | 0.870 | 0.091 | 0.165 | 0.502 | 6355 | 581/5774/87/6316 |
| disease_parameter_minimal | 0.879 | 0.086 | 0.157 | 0.465 | 6826 | 587/6239/81/5851 |
| disease_parameter_direct_estimate | 0.401 | 0.242 | 0.302 | 0.913 | 1106 | 268/838/400/11252 |
| disease_parameter_numerical_value | 0.367 | 0.240 | 0.290 | 0.920 | 1022 | 245/777/423/11313 |
| disease_parameter_primary_study | 0.313 | 0.302 | 0.307 | 0.946 | 692 | 209/483/459/11607 |
| disease_parameter_all_conditions | 0.412 | 0.258 | 0.318 | 0.917 | 1064 | 275/789/393/11301 |

## Files

- `evaluation/leads_mistral_freeze_leads_minimal_summary.csv`: per-profile summary rows for the selected LEADS result.
- `evaluation/leads_mistral_freeze_leads_minimal_predictions.csv`: compact per-PMID predictions for the selected LEADS result.
- `evaluation/leads_mistral_freeze_prompt_sweep_micro_summary.csv`: COVID-19, mpox, and overall micro metrics for the tested prompt styles.

Notes:

- The earlier `LEADS-2` result should be treated as a historical snapshot because it was generated before the dataset freeze.
- Strict prompts such as `disease_parameter_numerical_value` and `disease_parameter_primary_study` lower recall but raise precision/F1, so they are better interpreted as strict high-specificity sensitivity analyses rather than the main weak LEADS baseline.
