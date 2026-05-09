# LEADS Coding Topicwise Hybrid Results

This directory is the handoff package for adding the LEADS coding comparison result.

## Selected Result

Use `LEADS-Hybrid Topicwise` as the LEADS coding baseline:

- Fatality profiles use `leads_mistral_coding_official_trial_result_final_20260509` (LEADS task `official_trial_result`).
- Continuous profiles (`reproduction_number`, `serial_interval`) use `leads_mistral_coding_official_trial_result_lite_20260509` (LEADS task `official_trial_result_lite`).
- 5D and SR reference values are copied from the existing coding comparison tables.
- LEADS intervals are simple across-extraction intervals, not random-effects meta-analysis intervals.

## Key Numbers

| Scope | Profiles | LEADS MAE | 5D MAE | LEADS closer | 5D closer | Tie | LEADS n | lite profiles | final profiles |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overall | 22 | 2.571 | 0.255 | 5 | 17 | 0 | 552 | 15 | 7 |
| continuous | 15 | 0.607 | 0.180 | 5 | 10 | 0 | 353 | 15 | 0 |
| fatality | 7 | 6.781 | 0.416 | 0 | 7 | 0 | 199 | 0 | 7 |
| r0 | 6 | 0.432 | 0.165 | 1 | 5 | 0 | 175 | 6 | 0 |
| serial_interval | 9 | 0.723 | 0.190 | 4 | 5 | 0 | 178 | 9 | 0 |
| covid19 | 13 | 2.569 | 0.142 | 4 | 9 | 0 | 460 | 10 | 3 |
| mpox | 9 | 2.574 | 0.418 | 1 | 8 | 0 | 92 | 5 | 4 |

## Files

- `sr_5d_leads_hybrid_topicwise_report.md`: human-readable report with summary and per-profile estimates.
- `sr_5d_leads_hybrid_topicwise_summary.csv`: MAE and closer-count summary by scope.
- `sr_5d_leads_hybrid_topicwise_estimates.csv`: per-profile table for SR, 5D, LEADS-Hybrid, deltas, and source run.
- `leads_hybrid_topicwise_best_effort_pooling.csv`: selected LEADS pooled estimates and pooling notes.
- `sr_5d_leads_hybrid_topicwise_delta.png` / `.pdf`: delta-vs-SR plot.
- `sr_5d_leads_hybrid_topicwise_forest.png` / `.pdf`: estimate comparison plot.
- `source_manifest.json`: machine-readable source and selection metadata.

## Recommended Citation In Text

`LEADS-Hybrid` uses the Lite official-style LEADS trial-result extraction for continuous epidemiologic outcomes and the full official LEADS trial-result extraction for fatality outcomes. This topic-wise selection was used because Lite gave better continuous estimates, while the full official prompt gave more reliable fatality estimates.
