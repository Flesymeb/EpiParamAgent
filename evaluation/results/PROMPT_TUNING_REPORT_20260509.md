# Screening Prompt Tuning Report - 2026-05-09

## Objective

Improve title/abstract screening precision while preserving high recall across
the frozen COVID-19 13-profile and mpox 9-profile dataset.

## Current Full-Dataset Baseline

Formal LEADS-Minimal frozen rerun:

| Scope | Profiles | TP/FP/FN | Recall | Precision | F1 | NNS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 22 | 587/6239/81 | 87.9% | 8.6% | 0.157 | 11.63 |
| covid19 | 13 | 501/4840/60 | 89.3% | 9.4% | 0.170 | 10.66 |
| mpox | 9 | 86/1399/21 | 80.4% | 5.8% | 0.108 | 17.27 |

Best complete 5D run already exceeds LEADS-Minimal on both recall and
precision:

| Experiment | Profiles | TP/FP/FN | Recall | Precision | F1 | NNS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| boyue/qwen3.6-plus 5D | 22 | 634/2946/34 | 94.9% | 17.7% | 0.298 | 5.65 |
| boyue/deepseek-v4-pro 5D | 22 | 604/2775/64 | 90.4% | 17.9% | 0.298 | 5.59 |
| LEADS strict_simple historical | 22 | 580/5599/88 | 86.8% | 9.4% | 0.169 | 10.65 |

The formal comparison should use
`evaluation/leads_mistral_freeze_leads_minimal_summary.csv`, not older
pre-freeze LEADS snapshots.

## Weak Profiles

The largest Qwen3.6 Plus issues are concentrated in:

| Profile | Recall | Precision | TP/FP/FN | Main problem |
| --- | ---: | ---: | ---: | --- |
| mpox/fatality/p4 | 35.7% | 26.3% | 5/14/9 | FN-heavy, old case/outbreak reports under-included |
| mpox/fatality/p8 | 85.7% | 9.4% | 12/116/2 | FP-heavy sparse/broad mpox records |
| mpox/fatality/p12 | 87.5% | 9.3% | 14/136/2 | FP-heavy sparse/broad mpox records |
| covid19/reproduction_number/p16 | 94.4% | 10.6% | 34/288/2 | broad R0/transmission over-inclusion |
| covid19/fatality/p6 | 100.0% | 4.3% | 32/711/0 | very broad mortality search pool |
| covid19/reproduction_number/p15 | 100.0% | 5.4% | 25/438/0 | very broad R0 search pool |
| mpox/serial_interval/p6 | 100.0% | 8.2% | 5/56/0 | sparse mpox interval false positives |

## Prompt Change

Updated file:
`metaagent/prompts/5d/screening_system_title_abstract.md`

The key changes are:

1. Require concrete original evidence rather than disease relevance alone.
2. Require a concrete target-parameter cue for `P`; broad disease, clinical,
   diagnostic, vaccine, serology, forecasting, or policy papers should be `U`
   unless there is a plausible target-parameter path.
3. For fatality/severity, keep papers as possible candidates only when sparse
   metadata or abstracts contain an explicit outcome cue such as death,
   mortality, hospitalization, ICU, survival, or clinical outcome.
4. For serial/generation/incubation, keep papers as possible candidates only
   when metadata or abstracts contain explicit interval/timing/contact-tracing
   cues rather than broad transmission context alone.
5. For sparse/no-abstract records, use `P` only when title or indexed terms
   contain the exact target parameter or a close synonym; otherwise use `U`.

## Enriched Smoke-Test Result

Combined from the per-project CSVs under
`evaluation/screening_prompt_eval/qwen36_precision_20260509/`.
This is an enriched sample, not a full-pool estimate.

| Sample | TP/FP/FN | Recall | Precision | F1 |
| --- | ---: | ---: | ---: | ---: |
| previous Qwen decisions on same sample | 87/84/16 | 84.5% | 50.9% | 0.635 |
| tuned prompt rerun | 98/40/5 | 95.1% | 71.0% | 0.813 |

FP/FN movement:

- Previous FP demoted: 46/84.
- Previous FN rescued: 13/16.

Per-profile smoke results:

| Profile | Baseline R/P/F1 | Tuned R/P/F1 | FP demoted | FN rescued |
| --- | ---: | ---: | ---: | ---: |
| covid19/reproduction_number/p16 | 94.4/73.9/82.9 | 97.2/89.7/93.3 | 8/12 | 1/2 |
| mpox/fatality/p4 | 35.7/29.4/32.3 | 92.9/54.2/68.4 | 2/12 | 8/9 |
| mpox/fatality/p8 | 85.7/50.0/63.2 | 92.9/65.0/76.5 | 5/12 | 1/2 |
| mpox/fatality/p12 | 87.5/53.8/66.7 | 87.5/82.4/84.8 | 9/12 | 2/2 |
| mpox/reproduction_number/p9 | 100.0/20.0/33.3 | 100.0/75.0/85.7 | 11/12 | 0/0 |
| mpox/serial_interval/p6 | 100.0/29.4/45.5 | 100.0/55.6/71.4 | 8/12 | 0/0 |
| mpox/serial_interval/p10 | 93.3/53.8/68.3 | 100.0/60.0/75.0 | 3/12 | 1/1 |

## Full-Run Status

Qwen3.6 Plus via Boyue worked in `single` mode, but `multi` mode stalled on
the 7-profile smoke run. OpenRouter DeepSeek v4 Pro completed MP4
title/abstract multi-batch screening, but the profile then triggered automatic
full-text/PDF rescue and timed out. A rerun with `--no-fulltext-rescue
--skip-no-abstract` also timed out before useful output.

Full affected-profile reruns completed with Boyue Qwen3.6 Plus in stable
`single` mode for:

- mpox/fatality: p4, p8, p12
- mpox/reproduction_number: p9
- mpox/serial_interval: p6, p10
- covid19/reproduction_number: p15, p16
- covid19/fatality: p6

P6 did not improve, so it is not selected for the best hybrid.

Best tuned/full-run replacements:

| Experiment | Profile | TP/FP/FN | Recall | Precision | F1 | NNS |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| prompt_tuned_ta_boyue_qwen36plus_20260509 | mpox/fatality/p4 | 11/15/3 | 78.6% | 42.3% | 0.550 | 2.36 |
| prompt_tuned_sparse_boyue_qwen36plus_20260509 | mpox/fatality/p4 | 11/10/3 | 78.6% | 52.4% | 0.629 | 1.91 |
| prompt_tuned_sparse_boyue_qwen36plus_20260509 | mpox/fatality/p8 | 10/50/4 | 71.4% | 16.7% | 0.270 | 6.00 |
| prompt_tuned_sparse_boyue_qwen36plus_20260509 | mpox/fatality/p12 | 15/79/1 | 93.8% | 16.0% | 0.273 | 6.27 |
| prompt_tuned_sparse_boyue_qwen36plus_20260509 | mpox/reproduction_number/p9 | 3/3/0 | 100.0% | 50.0% | 0.667 | 2.00 |
| prompt_tuned_sparse_boyue_qwen36plus_20260509 | mpox/serial_interval/p6 | 5/15/0 | 100.0% | 25.0% | 0.400 | 4.00 |
| prompt_tuned_sparse_boyue_qwen36plus_20260509 | mpox/serial_interval/p10 | 14/14/1 | 93.3% | 50.0% | 0.651 | 2.00 |
| prompt_tuned_sparse_r0recall_boyue_qwen36plus_20260509 | covid19/reproduction_number/p15 | 25/402/0 | 100.0% | 5.9% | 0.111 | 17.08 |
| prompt_tuned_sparse_r0recall_boyue_qwen36plus_20260509 | covid19/reproduction_number/p16 | 34/248/2 | 94.4% | 12.1% | 0.214 | 8.29 |

Recommended paper-facing hybrid:

| Scope | Profiles | TP/FP/FN | Recall | Precision | F1 | NNS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 22 | 639/2670/29 | 95.7% | 19.3% | 0.321 | 5.18 |
| covid19 | 13 | 542/2398/19 | 96.6% | 18.4% | 0.310 | 5.42 |
| mpox | 9 | 97/272/10 | 90.7% | 26.3% | 0.408 | 3.80 |

This hybrid improves over the previous complete Qwen3.6 Plus run
(634/2946/34, recall 94.9%, precision 17.7%, F1 0.298) and is far above
formal LEADS-Minimal (587/6239/81, recall 87.9%, precision 8.6%, F1 0.157).

Artifacts:

- `evaluation/results/PROMPT_TUNED_HYBRID_SUMMARY_20260509.md`
- `evaluation/results/prompt_tuned_hybrid_summary_20260509.json`
- `evaluation/results/prompt_tuned_hybrid_profile_metrics_20260509.csv`

Recommended full rerun command shape:

```bash
PYTHONPATH=. python tools/scripts/screening_llm_batch.py \
  --project-root /home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi \
  --profile MP4 \
  --batch-size 20 \
  --batch-concurrency 5 \
  --batch-mode multi \
  --strategy 5d \
  --model deepseek/deepseek-v4-pro \
  --provider openrouter \
  --experiment prompt_tuned_ta_openrouter_dsv4pro_20260509 \
  --prefer-llm-tier \
  --no-fulltext-rescue \
  --skip-no-abstract
```

If further improvement is needed, the next target is covid19/fatality/p6. The
current prompt did not improve that profile, so it likely needs full-text
verification, stricter post-processing, or SR-scope rules rather than more
generic title/abstract prompt text.

## Recommendation For Main Figure

For the strongest current main figure/table, use the recommended hybrid above.
It keeps the complete Qwen3.6 Plus baseline where the tuned prompt did not help,
and swaps in tuned full-rerun outputs only where they improved the profile.
Present NNS/FDR with recall and precision because LEADS has very poor screening
efficiency.
