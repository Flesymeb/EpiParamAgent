# Evaluation Directory

`evaluation/` is for experiment outputs only. Fixed task inputs belong under
`dataset/`.

## Structure

```text
evaluation/
├── screening/
│   └── {covid19|mpox}/{parameter}/pN/experiments/{experiment_id}/
│       ├── project_N_screened.csv
│       ├── screening_logs/
│       └── screening_runs/
├── coding/
│   └── {covid19|mpox}/{parameter}/pN/coding_runs/{run_id}/
│       ├── coding_sheet_*.xlsx
│       ├── index/
│       └── run_manifest_*.json
└── experiments/       # Curated cross-profile summary experiments
```

Do not store dataset files such as `raw.csv`, `ground_truth.csv`, `pmids.txt`,
or `project.json` in `evaluation/`. Paper-facing figures and tables belong in
`docs/paper/`.
