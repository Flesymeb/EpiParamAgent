# Evaluation Directory

## Structure

```
evaluation/
├── ground_truth/               # Ground truth datasets
│   └── {disease}/{parameter}/  # GT.csv with PMIDs and labels
├── experiments/                # Experiment results (new runs go here)
│   └── {experiment_id}/        # e.g., peco_v1_baseline
│       ├── screening/          # Screening outputs
│       │   └── {disease}/{parameter}/{strategy}/{model}/
│       │       ├── screened.csv
│       │       ├── metrics.json
│       │       └── cost.json
│       ├── coding/             # Coding outputs
│       │   └── {disease}/{parameter}/{strategy}/
│       │       ├── coding_sheet.xlsx
│       │       └── metrics.json
│       └── pooled_summary.csv  # Aggregated results
├── coding/                     # Legacy coding runs (pre-restructure)
├── screening/                  # Legacy screening runs (pre-restructure)
├── mpox_import/                # Legacy mpox import data
└── README.md
```

## Experiment naming convention

`{strategy}_{model}_{disease}_{parameter}_{date}`

Examples:
- `5d_gpt4.1_covid19_serial_interval_20260505`
- `peco_deepseek-v4_mpox_fatality_20260505`
- `binary_baseline_all_covid19_all_20260505`

## Metrics format (metrics.json)

```json
{
  "screening": {
    "total_papers": 500,
    "tp": 45, "fp": 12, "fn": 3, "tn": 440,
    "sensitivity": 0.938, "specificity": 0.973,
    "f1": 0.857, "mcc": 0.842,
    "cohens_kappa": null
  },
  "cost": {
    "total_prompt_tokens": 150000,
    "total_completion_tokens": 45000,
    "total_time_seconds": 120.5,
    "avg_time_ms_per_paper": 241
  }
}
```
