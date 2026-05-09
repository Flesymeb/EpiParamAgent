# Dataset Directory

`dataset/` stores fixed input data for reproducible screening and coding tasks.
Experiment outputs belong in `evaluation/`.

## Structure

```text
dataset/
├── covid19/
│   ├── screening/{parameter}/pN/
│   │   ├── project.json
│   │   ├── ground_truth.csv
│   │   └── raw.csv          # fixed screening candidate pool
│   └── coding/{parameter}/pN/
│       ├── pmids.txt
│       ├── project.json
│       └── ground_truth.csv
└── mpox/
    ├── screening/{parameter}/pN/
    └── coding/{parameter}/pN/
```

`pmids.txt` is the canonical coding extraction input. `project.json` and
`ground_truth.csv` are copied from the matching screening profile to keep each
coding task self-describing. In profiles with manual coding corrections,
`pmids.txt` may be a corrected extraction list rather than an exact row-for-row
copy of `ground_truth.csv`; use `pmids.txt` for coding runs.

The paper-facing screening dataset is frozen in
[`SCREENING_DATASET_FREEZE_20260508.md`](SCREENING_DATASET_FREEZE_20260508.md).
Use those 22 `raw.csv` and `ground_truth.csv` files for main-table 5D,
keyword-rule, and LEADS/LEADS-Minimal comparisons. Do not use older
`evaluation/` copies for paper baseline reruns.

`dataset/covid19/coding/reproduction_number/p7/` is intentionally a curated
full-text coding subset of the larger screening GT. Its `pmids.txt` and
`ground_truth.csv` should remain aligned with each other, but they should not be
used to overwrite the larger screening GT without a separate source-level audit.
