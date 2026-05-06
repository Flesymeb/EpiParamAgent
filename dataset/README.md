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
│   │   └── raw.csv          # local large search pool, gitignored
│   └── coding/{parameter}/pN/
│       ├── pmids.txt
│       ├── project.json     # when available
│       └── ground_truth.csv # when available
└── mpox/
    ├── screening/{parameter}/pN/
    └── coding/{parameter}/pN/
```

`raw.csv` files are intentionally ignored because they are large. The small
metadata and label files can be versioned when needed.
