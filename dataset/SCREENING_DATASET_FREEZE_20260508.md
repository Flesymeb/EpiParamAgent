# Screening Dataset Freeze 2026-05-08

This file defines the fixed screening dataset for the paper-facing 5D,
keyword-rule, and LEADS comparisons.

Use this dataset version for all reruns that should be merged with the current
5D model comparison:

- Input root: `dataset/`
- Screening raw pool: `dataset/{disease}/screening/{topic}/{project}/raw.csv`
- Ground truth: `dataset/{disease}/screening/{topic}/{project}/ground_truth.csv`
- Project metadata: `dataset/{disease}/screening/{topic}/{project}/project.json`
- Prediction-positive convention: `strong_candidate` + `possible_candidate`
- Current reference run:
  `evaluation/experiments/model_5d_screening_multi_adaptive_highc_llmtier_20260507`

Do not use older `evaluation/.../ground_truth/...` copies for paper baseline
reruns. Those paths may correspond to earlier LEADS or pre-cleaning snapshots.

## Frozen Screening Profiles

| Disease | Topic | Project | Raw rows | GT rows |
| --- | --- | --- | ---: | ---: |
| covid19 | fatality | P4 | 345 | 56 |
| covid19 | fatality | P5 | 1882 | 48 |
| covid19 | fatality | P6 | 2253 | 32 |
| covid19 | reproduction_number | P7 | 574 | 122 |
| covid19 | reproduction_number | P8 | 575 | 44 |
| covid19 | reproduction_number | P15 | 709 | 25 |
| covid19 | reproduction_number | P16 | 575 | 36 |
| covid19 | reproduction_number | P17 | 209 | 15 |
| covid19 | serial_interval | P10 | 599 | 28 |
| covid19 | serial_interval | P11 | 841 | 76 |
| covid19 | serial_interval | P12 | 146 | 19 |
| covid19 | serial_interval | P13 | 111 | 51 |
| covid19 | serial_interval | P14 | 94 | 9 |
| mpox | fatality | MP4 | 92 | 14 |
| mpox | fatality | MP7 | 352 | 27 |
| mpox | fatality | MP8 | 683 | 14 |
| mpox | fatality | MP12 | 643 | 16 |
| mpox | reproduction_number | MP9 | 819 | 3 |
| mpox | serial_interval | MP5 | 59 | 8 |
| mpox | serial_interval | MP6 | 522 | 5 |
| mpox | serial_interval | MP10 | 612 | 15 |
| mpox | serial_interval | MP11 | 63 | 5 |

Totals:

- Profiles: 22
- Raw pool rows: 12,758
- Ground-truth rows: 668

## Baseline Rerun Policy

For a baseline to be merged into the paper main table, it must satisfy all of
the following:

1. Run on exactly the 22 profiles listed above.
2. Use the `raw.csv` and `ground_truth.csv` files under `dataset/`, not older
   `evaluation/` copies.
3. Export per-PMID predictions for paired error analysis.
4. Report profile-level TP, FP, FN, TN, recall, precision, F1, workload
   reduction, NNS, and false discovery rate.
5. Record the prompt, model/provider, batch mode, and decision rule in the run
   config.

The previous historical LEADS snapshot has been replaced by the frozen-dataset
LEADS rerun. Use `evaluation/leads_mistral_freeze_leads_minimal_summary.csv`
and `evaluation/leads_mistral_freeze_leads_minimal_predictions.csv` for formal
LEADS results.
