# LEADS Coding Official Final Results

This directory is the handoff package for adding the LEADS coding comparison result.

## Selected Result

Use `LEADS-Official final` as the LEADS coding baseline.

- Source run: `evaluation/experiments/leads_mistral_coding_official_trial_result_final_20260509`.
- LEADS task: `official_trial_result`.
- Profiles: 22 main coding profiles, excluding COVID fatality `P9`.
- LEADS confidence intervals are simple across-extraction intervals, not random-effects meta-analysis intervals.

## Key Numbers

| Scope | Profiles | LEADS MAE | 5D MAE | LEADS closer | 5D closer | Tie | LEADS n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| overall | 22 | 2.677 | 0.255 | 1 | 21 | 0 | 625 |
| continuous | 15 | 0.762 | 0.180 | 1 | 14 | 0 | 426 |
| fatality | 7 | 6.781 | 0.416 | 0 | 7 | 0 | 199 |
| r0 | 6 | 0.582 | 0.165 | 0 | 6 | 0 | 209 |
| serial_interval | 9 | 0.882 | 0.190 | 1 | 8 | 0 | 217 |
| covid19 | 13 | 2.604 | 0.142 | 0 | 13 | 0 | 525 |
| mpox | 9 | 2.783 | 0.418 | 1 | 8 | 0 | 100 |

Main takeaway: final LEADS is a clean single-prompt official baseline. Overall, LEADS is closer to SR in `1/22` profiles, while 5D is closer in `21/22` profiles.

## Files

- `sr_5d_leads_official_final_report.md`: human-readable report with summary and per-profile estimates.
- `sr_5d_leads_official_final_summary.csv`: MAE and closer-count summary by scope.
- `sr_5d_leads_official_final_estimates.csv`: per-profile table for SR, 5D, LEADS-Official final, deltas, and closer labels.
- `leads_official_best_effort_pooling.csv`: selected LEADS pooled estimates and pooling notes.
- `leads_official_best_effort_pooling.md`: markdown view of the LEADS pooling table.
- `sr_5d_leads_official_final_delta.png` / `.pdf`: delta-vs-SR plot.
- `sr_5d_leads_official_final_forest.png` / `.pdf`: estimate comparison plot.
- `source_manifest.json`: machine-readable source and package metadata.

## Recommended Citation In Text

`LEADS-Official final` uses the official-style LEADS trial-result extraction prompt as an external coding baseline. The output is poolable as a best-effort comparison, but it does not preserve all epidemiology-specific fields needed for 5D-style codebook-guided meta-analysis.
