# Full-Text Cache

This directory is the local cache for downloaded PDFs and parsed Markdown used
by full-text screening and coding. Only this README is versioned; papers and
derived full text must not be committed.

The runtime creates cache subdirectories as needed. Access to an article must
comply with its licence and the policies of the configured retrieval source.

Runtime layout:

```text
paper_pool/
├── pdfs/                         # Shared PMID-keyed PDF cache
├── markdown/                     # Shared parsed full-text cache
└── projects/<disease>/<parameter>/<project>/
    ├── pmids.txt                 # Records selected for coding
    ├── fetch_plan.json           # Reproducible source/tier selection
    └── fetch_results.csv         # Per-PMID retrieval status
```

Use `metaagent pdf fetch` to create these files. The default retrieval strategy
uses PubMed Central open-access full text only.
