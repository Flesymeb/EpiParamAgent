# Dataset Workspace

This directory stores local inputs for screening and coding runs. Only this
README is versioned; review data must not be committed.

Recommended layout:

```text
dataset/<disease>/screening/<parameter>/p<id>/
├── query.json
├── query.txt
├── raw.csv
└── ground_truth.csv

dataset/<disease>/coding/<parameter>/p<id>/
└── pmids.txt
```

Use `metaagent pubmed query` to create `query.json`, `query.txt`, and optionally
`raw.csv`. The raw file should contain `PMID`, `Title`, and `Abstract` columns.
`ground_truth.csv` is optional and should contain a `PMID` column. Keep the
ground-truth labels for evaluation rather than adding them to model prompts.
