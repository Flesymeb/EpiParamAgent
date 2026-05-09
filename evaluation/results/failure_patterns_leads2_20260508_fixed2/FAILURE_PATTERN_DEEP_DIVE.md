# LEADS-Minimal Frozen-Dataset Screening Summary

Updated: 2026-05-08

This report replaces the previous LEADS-2 historical snapshot with the formal
frozen-dataset LEADS-Minimal rerun. The old
`leads_mistral_disease_parameter_minimal_20260506_225001` result should be
treated only as an internal historical snapshot and should not be used in main
paper tables.

## Run Definition

- Method name: `LEADS` or `LEADS-Minimal`
- Dataset freeze: 2026-05-08
- Screening profiles: 22
- Raw rows: 12,758
- Ground-truth rows: 668
- Summary: `evaluation/leads_mistral_freeze_leads_minimal_summary.csv`
- Per-PMID predictions: `evaluation/leads_mistral_freeze_leads_minimal_predictions.csv`
- Prompt style: `disease_parameter_minimal`
- Source data: `dataset/{disease}/screening/{topic}/p{project}/raw.csv` and `ground_truth.csv`

Prompt:

```text
I am screening papers for a systematic review about {disease} and {parameter}.
Based on the title and abstract, decide include or exclude.

Title: {title}
Abstract: {abstract}

Return JSON only: {"include": true/false, "reason": "short"}
```

This is a minimal title/abstract LEADS baseline: it gives only disease and
parameter context, without 5D eligibility criteria or complex screening rules.

## Main Micro Metrics

| Scope | GT/N | Predicted include | TP/FP/FN/TN | Recall | Precision | F1 | Workload reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| COVID-19 | 561/8913 | 5341 | 501/4840/60/3512 | 0.893 | 0.094 | 0.170 | 0.401 |
| mpox | 107/3845 | 1485 | 86/1399/21/2339 | 0.804 | 0.058 | 0.108 | 0.614 |
| Overall | 668/12758 | 6826 | 587/6239/81/5851 | 0.879 | 0.086 | 0.157 | 0.465 |

## Topic-Level Context

These rows are aggregated from the frozen-dataset LEADS-Minimal profile summary.

| Scope | GT/N | Predicted include | TP/FP/FN/TN | Recall | Precision | F1 | NNS | Workload reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| COVID-19 / Serial interval | 183/1791 | 902 | 169/733/14/875 | 0.923 | 0.187 | 0.312 | 5.34 | 0.496 |
| COVID-19 / Reproduction number | 242/2642 | 1725 | 213/1512/29/888 | 0.880 | 0.123 | 0.217 | 8.10 | 0.347 |
| COVID-19 / Fatality | 136/4480 | 2714 | 119/2595/17/1749 | 0.875 | 0.044 | 0.084 | 22.81 | 0.394 |
| mpox / Serial interval | 33/1256 | 449 | 27/422/6/801 | 0.818 | 0.060 | 0.112 | 16.63 | 0.643 |
| mpox / Reproduction number | 3/819 | 200 | 3/197/0/619 | 1.000 | 0.015 | 0.030 | 66.67 | 0.756 |
| mpox / Fatality | 71/1770 | 836 | 56/780/15/919 | 0.789 | 0.067 | 0.123 | 14.93 | 0.528 |

## Interpretation

LEADS-Minimal preserves high recall under a deliberately weak title/abstract
baseline, but precision remains low because many nearby disease- and
parameter-relevant papers are included. In main results, report recall together
with precision, workload reduction, and NNS so the baseline is not interpreted
as strong solely because it over-includes.

The previous LEADS-2 failure-pattern labels were produced before the dataset
freeze and are not reused here. Any future failure-mode analysis should be
regenerated from `evaluation/leads_mistral_freeze_leads_minimal_predictions.csv`
using `ground_truth_include` and `predicted_include`.
