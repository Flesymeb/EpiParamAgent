# EpiParamAgent source-review benchmark, version 1

This public dataset contains the review inputs and reference annotations for
the manuscript *EpiParamAgent: Automating Systematic Reviews of Epidemiological
Parameters*. It covers 22 published source reviews: 13 COVID-19 reviews and
9 mpox reviews, grouped into serial interval, reproduction number, and fatality
benchmark tasks. There are 12,758 candidate record instances and 668 included
record instances. Counts are across tasks; the same article can occur in
multiple source reviews. Screening pool membership follows the local dataset
freeze dated 8 May 2026; this public package was assembled on 22 October 2026.

Only benchmark inputs and reference annotations are included. Model screening
decisions, coding/extraction outputs, experimental results, and tests are kept
outside the published repository. The provided data and reusable code allow
independent runs; this package does not include archived model outputs needed
to recalculate the paper's reported results without rerunning the models.

## Files

`profiles.csv` lists every source review, its PMID and title, benchmark domain,
search dates, task path, and the actual input/reference row counts. Review PMIDs
can be resolved at `https://pubmed.ncbi.nlm.nih.gov/<PMID>/`.

Each task uses this layout:

```text
<disease>/screening/<parameter>/p<id>/
├── raw.csv             # frozen PubMed input metadata, including available abstracts
├── ground_truth.csv    # studies included by the source review
├── project.json        # source review, query dates, and review eligibility fields
├── query.txt           # saved PubMed query
└── pmids.txt           # candidate PMIDs, one per line
```

`reference_estimates.csv` provides 22 manually extracted source-review target
estimates and available confidence intervals, with endpoint definitions and
notes corresponding to the manuscript's source-review reference table.
These are reference annotations, not model-generated coding results.

`manifest.json` records provenance, transformations, counts, file sizes, and
SHA-256 checksums for all 112 data files. Source checksums are also recorded
for the original raw and inclusion-list files. The `raw.csv` files are
byte-identical to the frozen local screening inputs; the public reference
lists and project metadata use selected fields to omit internal notes and
annotator identifiers.

## Data dictionary

| File / field | Meaning |
| --- | --- |
| `profiles.csv`: `profile` | `P<n>` for COVID-19; `MP<n>` for mpox; unique task identifier |
| `profiles.csv`: `project` | Runtime project directory, `p<n>` |
| `profiles.csv`: `path` | Task directory relative to the repository root |
| `raw.csv`: `PMID`, `Title`, `Abstract`, `Keywords` | Retrieved PubMed metadata used as screening input; empty text denotes missing metadata |
| `raw.csv`: `DOI`, `PMCID`, `Publication Year` | Bibliographic identifiers and publication year where available |
| `raw.csv`: other columns | Bibliographic metadata retained unchanged from the input snapshot |
| `ground_truth.csv`: `PMID`, `Title`, `DOI`, `Publication Year` | Bibliographic identifiers for studies included in the source review |
| `ground_truth.csv`: `source_review_pmid` | PMID of the source review from which membership was transcribed |
| `project.json`: `query_text`, `query_date_from`, `query_date_to` | Saved query and source search interval |
| `project.json`: `research_question`, `*_focus`, `*_exclude`, `parameter_relevance` | Saved review-question and eligibility metadata, where present |
| `reference_estimates.csv`: `parameter` | Benchmark grouping; consult `reference_endpoint` for the actual estimand |
| `reference_estimates.csv`: `reference_value`, `reference_ci_lower`, `reference_ci_upper` | Source-review point estimate and 95% interval limits when supplied/reconstructed; empty limits mean unavailable |
| `reference_estimates.csv`: `unit` | `d`: days; `%`: percent, not proportions; empty: dimensionless reproduction number |
| `reference_estimates.csv`: `reference_note`, `reference_endpoint` | Endpoint selection or reconstruction details |

Membership in `ground_truth.csv` means inclusion in the corresponding source
review. Candidate records absent from that list are reference negatives for
this benchmark; they are not independently adjudicated as universally
irrelevant. Ground-truth labels must be kept out of model prompts.

The source project metadata are historical descriptions. Counts in
`profiles.csv` and `project.json` were recomputed from the released CSVs;
the query may not recreate an identical pool against today's PubMed database.
Use the frozen `raw.csv` for comparisons on this version.

The mpox task `MP5` is grouped with serial-interval benchmarks but its
source-review target is an **incubation period**. Fatality endpoints also
differ across reviews (for example, infection fatality versus hospital case
fatality). The reference endpoint and units must be checked before extraction
or pooling; this release preserves these distinctions.

## Use with the CLI

From the repository root, after installation and LLM configuration, an example
run with the public inputs is:

```bash
metaagent screening run \
  --profile P13 \
  --input dataset/benchmark_v1/covid19/screening/serial_interval/p13/raw.csv \
  --output /tmp/epiparamagent_p13_screened.csv \
  --no-interactive --no-fix-missing \
  --strategy 5d --batch-mode multi --batch-size 20 --batch-concurrency 5

metaagent screening evaluate performance \
  --ground-truth dataset/benchmark_v1/covid19/screening/serial_interval/p13/ground_truth.csv \
  --screened-results /tmp/epiparamagent_p13_screened.csv
```

Model calls require the user's configured provider and may incur costs. Pin
the repository commit, dependencies, model/provider, prompts, and decision rule
for each independent run. Provider/model changes and stochastic inference can
produce different results. Full-text extraction additionally requires fetching
the articles using their identifiers; PDFs and parsed full texts are not
included in this release.

## Verify the download

This command requires only Python's standard library and checks every data file
against the committed manifest. Run it from the repository root:

```bash
python - <<'PY'
import hashlib, json
from pathlib import Path
root = Path.cwd()
manifest = json.loads((root / 'dataset/benchmark_v1/manifest.json').read_text())
for item in manifest['files']:
    data = (root / item['path']).read_bytes()
    if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
        raise SystemExit('Checksum mismatch: ' + item['path'])
print('Verified', len(manifest['files']), 'data files')
PY
```

## Access, reuse, and citation

The files are directly accessible in this Git repository without a separate
data request. PubMed bibliographic records and abstracts are reused source
material; their source attribution and applicable reuse terms remain relevant.
Downloaded full-text articles are not redistributed. This release does not
assign a new blanket licence to third-party content or a separate data licence
to the reference annotations.

Cite the manuscript, the relevant source reviews listed in `profiles.csv`,
and this dataset's repository commit. Use a commit-pinned URL when citing the
dataset: `https://github.com/Flesymeb/EpiParamAgent/tree/<commit>/dataset/benchmark_v1`.
No dataset DOI or external archival accession has been assigned in this release.

## Data Availability wording

The benchmark inputs and reference annotations are publicly available in the
EpiParamAgent repository under `dataset/benchmark_v1`. The release includes
candidate PubMed records with available titles and abstracts, source-review
inclusion lists, saved search queries and date ranges, source-review metadata,
and manually extracted review-level reference estimates for 22 review tasks.
File checksums and data definitions accompany the release. Model predictions,
coding outputs, and experimental run artifacts are not distributed. Full-text
articles must be obtained from their original sources using the provided
identifiers.
