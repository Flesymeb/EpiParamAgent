# Datasets

The public [benchmark_v1](benchmark_v1/README.md) contains the frozen inputs for
the paper's 22 COVID-19 and mpox source-review tasks: 12,758 candidate records,
668 source-review inclusion labels, source search queries and date ranges,
and 22 manually extracted review-level reference estimates. These files are
versioned and downloadable with the repository.

All other subdirectories are local review workspaces and remain ignored.
Model predictions, coding outputs, experimental results, tests, credentials,
and downloaded full texts are not part of the public dataset.

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
