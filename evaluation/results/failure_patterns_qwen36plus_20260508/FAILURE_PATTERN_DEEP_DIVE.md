# Screening Failure Pattern Deep Dive - Qwen3.6 Plus

Updated: 2026-05-08 05:00:17 CST

Model slug: `model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus`

## Core Finding

The main failure pattern is not disease confusion. The model recognizes the target disease well, but its inclusion boundary is broader than the SR ground truth. False positives are mainly nearby epidemiology papers with plausible disease and evidence signals, while false negatives are mostly papers where the target parameter evidence is weak or hidden in the title/abstract.

## Metrics By Disease And Topic

| Scope | TP/FP/FN/TN | Recall | Precision | F1 | FDR | NNS | WR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| covid19 | 542/2474/19/5878 | 96.6% | 18.0% | 30.3% | 82.0% | 5.56 | 70.4% |
| covid19 / Fatality | 133/1017/3/3327 | 97.8% | 11.6% | 20.7% | 88.4% | 8.65 | 76.6% |
| covid19 / Reproduction number | 238/1206/4/1194 | 98.3% | 16.5% | 28.2% | 83.5% | 6.07 | 49.8% |
| covid19 / Serial interval | 171/251/12/1357 | 93.4% | 40.5% | 56.5% | 59.5% | 2.47 | 84.4% |
| mpox | 92/472/15/3266 | 86.0% | 16.3% | 27.4% | 83.7% | 6.13 | 87.4% |
| mpox / Fatality | 58/325/13/1374 | 81.7% | 15.1% | 25.6% | 84.9% | 6.60 | 80.9% |
| mpox / Reproduction number | 3/17/0/799 | 100.0% | 15.0% | 26.1% | 85.0% | 6.67 | 97.9% |
| mpox / Serial interval | 31/130/2/1093 | 93.9% | 19.3% | 32.0% | 80.7% | 5.19 | 89.4% |
| Overall | 634/2946/34/9144 | 94.9% | 17.7% | 29.8% | 82.3% | 5.65 | 75.6% |

## Dominant Error Types

| Scope | FP dominant types | FN dominant types |
| --- | --- | --- |
| covid19 | `plausibly_relevant_not_in_sr_gt` 39.7%, `weak_or_indirect_target_parameter` 22.2%, `broad_topic_over_inclusion` 15.4% | `target_parameter_not_detected` 84.2%, `possible_gt_non_original_or_review` 15.8% |
| covid19 / Fatality | `plausibly_relevant_not_in_sr_gt` 38.0%, `sparse_metadata_over_inclusion` 18.6%, `broad_topic_over_inclusion` 16.9% | `target_parameter_not_detected` 66.7%, `possible_gt_non_original_or_review` 33.3% |
| covid19 / Reproduction number | `plausibly_relevant_not_in_sr_gt` 39.1%, `weak_or_indirect_target_parameter` 25.9%, `broad_topic_over_inclusion` 16.3% | `target_parameter_not_detected` 100.0% |
| covid19 / Serial interval | `plausibly_relevant_not_in_sr_gt` 49.4%, `weak_or_indirect_target_parameter` 40.2%, `broad_topic_over_inclusion` 4.4% | `target_parameter_not_detected` 83.3%, `possible_gt_non_original_or_review` 16.7% |
| mpox | `weak_or_indirect_target_parameter` 40.3%, `sparse_metadata_over_inclusion` 28.6%, `plausibly_relevant_not_in_sr_gt` 12.1% | `target_parameter_not_detected` 86.7%, `insufficient_title_abstract_evidence` 6.7%, `possible_gt_non_original_or_review` 6.7% |
| mpox / Fatality | `weak_or_indirect_target_parameter` 39.7%, `sparse_metadata_over_inclusion` 32.3%, `plausibly_relevant_not_in_sr_gt` 11.1% | `target_parameter_not_detected` 92.3%, `insufficient_title_abstract_evidence` 7.7% |
| mpox / Reproduction number | `sparse_metadata_over_inclusion` 47.1%, `weak_or_indirect_target_parameter` 23.5%, `borderline_possible_over_inclusion` 17.6% | None |
| mpox / Serial interval | `weak_or_indirect_target_parameter` 43.8%, `sparse_metadata_over_inclusion` 16.9%, `plausibly_relevant_not_in_sr_gt` 16.2% | `target_parameter_not_detected` 50.0%, `possible_gt_non_original_or_review` 50.0% |

## Post-Processing Rule Simulation

These are post-hoc simulations over the same model outputs, not new model runs.

| Rule | Recall | Precision | F1 | FDR | NNS | FP removed | TP lost | Note |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Baseline: strong + possible | 94.9% | 17.7% | 29.8% | 82.3% | 5.65 | 0 | 0 | Current paper setting. |
| Strong only | 81.7% | 25.1% | 38.4% | 74.9% | 3.99 | 1313 | 88 | Drops all possible-candidate papers. |
| Drop sparse possible | 93.9% | 19.3% | 32.0% | 80.7% | 5.19 | 317 | 7 | Keeps strong sparse records, but drops sparse possible candidates. |
| Parameter score >= 3 | 85.3% | 22.2% | 35.2% | 77.8% | 4.51 | 944 | 64 | Removes direct weak-parameter includes. |
| Evidence score >= 3 | 93.7% | 19.6% | 32.4% | 80.4% | 5.10 | 381 | 8 | Removes weak original-evidence includes. |
| Parameter and evidence >= 3 | 84.7% | 23.7% | 37.0% | 76.3% | 4.23 | 1119 | 68 | Requires both parameter and empirical evidence support. |
| Drop possible with parameter <= 2 | 85.3% | 22.2% | 35.2% | 77.8% | 4.51 | 944 | 64 | Targets the largest mpox FP bucket while preserving strong decisions. |

## Weakest Profiles

Profiles are sorted by recall first, then FDR. These are the profiles to inspect before tuning.

| Disease | Topic | Profile | Recall | Precision | F1 | FDR | NNS | TP/FP/FN/TN |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mpox | Fatality | P4 | 35.7% | 26.3% | 30.3% | 73.7% | 3.80 | 5/14/9/64 |
| mpox | Fatality | P8 | 85.7% | 9.4% | 16.9% | 90.6% | 10.67 | 12/116/2/553 |
| mpox | Fatality | P12 | 87.5% | 9.3% | 16.9% | 90.7% | 10.71 | 14/136/2/491 |
| mpox | Serial interval | P5 | 87.5% | 22.6% | 35.9% | 77.4% | 4.43 | 7/24/1/27 |
| covid19 | Serial interval | P13 | 88.2% | 52.9% | 66.2% | 47.1% | 1.89 | 45/40/6/20 |
| covid19 | Serial interval | P14 | 88.9% | 12.9% | 22.5% | 87.1% | 7.75 | 8/54/1/31 |
| mpox | Serial interval | P10 | 93.3% | 30.4% | 45.9% | 69.6% | 3.29 | 14/32/1/565 |
| covid19 | Reproduction number | P16 | 94.4% | 10.6% | 19.0% | 89.4% | 9.47 | 34/288/2/251 |
| covid19 | Fatality | P4 | 94.6% | 25.0% | 39.6% | 75.0% | 4.00 | 53/159/3/130 |
| covid19 | Serial interval | P12 | 94.7% | 39.1% | 55.4% | 60.9% | 2.56 | 18/28/1/99 |

## Failure Laws

1. High recall is driven by a permissive `possible_candidate` boundary. This protects recall, but it also admits weak parameter-evidence papers.
2. COVID-19 false positives are often plausible epidemiology studies outside the narrower SR GT, so many are boundary errors rather than obviously irrelevant papers.
3. mpox false positives are more often metadata-limited or weakly parameter-specific, reflecting shorter abstracts and less standardized reporting.
4. False negatives cluster where the target parameter is implicit, downstream of another analysis, or only visible in full text.
5. A simple parameter/evidence gate can reduce FP, but the post-hoc table should be used to decide whether the recall loss is acceptable.

## Practical Tuning Direction

For the next 5D iteration, tune the boundary rather than the disease detector. The most defensible changes are:

1. Require explicit target-parameter evidence for `strong_candidate`; keep weaker evidence as `possible_candidate` only.
2. For sparse abstracts, avoid automatic inclusion unless title contains the exact target parameter or full-text rescue confirms it.
3. Add full-text rescue for FN-heavy profiles before tightening too much, especially mpox fatality and COVID serial interval.
4. Report FDR/NNS alongside recall so LEADS and keyword baselines cannot look strong solely because they over-include.
