# Pi analysis agent and deterministic synthesis

The third workflow stage can use Pi to plan an analysis, write code, execute it,
validate the actual outputs and repair failures within explicit budgets. Its inputs
are the research question, the coding table and explicitly supplied original method
documents. A missing prefilled `AnalysisProtocol` does not stop this path: missing
method details must become visible exploratory assumptions. Reproducing an original
method and exploratory reanalysis remain distinguishable, and a source review's
reported pooled number is never an optimization target.

```bash
metaagent synthesis agent --input coding.xlsx \
  --research-question 'What incubation-period estimates are supported by these studies?' \
  --method-source original_methods.pdf --primary-source primary_study.pdf \
  --output runs/synthesis_agent --json
```

Use repeatable `--method-source` for original review methods and `--primary-source` for primary study evidence. The roles are explicit in dry-run fingerprints and staged source metadata; one file cannot claim both roles.

XLSX, CSV, JSONL and JSON coding tables are supported. Method documents may be PDF,
Markdown, TXT, HTML or DOCX; pass the original methods explicitly, rather than a
benchmark reference/gold file. Documents are staged by the analysis backend, with
source hashes and locators; the CLI does not paste whole papers into the prompt.
`--protocol analysis.yaml` is optional context. `--dry-run --json` inspects local
inputs and pinned Pi resources without launching a model, running analysis code,
converting source documents or writing an output directory.

The agent uses the independent `SYNTHESIS_LLM_*` provider/model/endpoint/key profile.
Optional `--model`, `--api-base` and `--api-key-env ENVIRONMENT_VARIABLE_NAME` override
that profile. Credentials are private provider headers, not task fields, model
prompts, generated-code environment or result artifacts. `SYNTHESIS_PI_COMMAND` or
`--pi-command` selects a pinned local Pi executable. Runtime installation/version
must be available; planning reads local metadata rather than invoking the service.

Task example (see `configs/templates/review_task.yaml`):

```yaml
synthesis:
  backend: pi
  # research_question: optional override; otherwise inherit the task question
  method_sources: [methods.pdf, supplement.docx]  # relative to this task file
  max_executions: 6
  max_turns: 16
  max_tokens: 256000
  total_timeout_s: 1200
  exec_timeout_s: 120
```

The CLI defaults remain bounded at 12 turns, 64000 total tokens and 3 generated-code executions; `--max-executions` accepts 1–8. The main Pi templates reserve 16 turns, 256000 total tokens and 6 executions because validation and repair consume additional calls. These are runtime budgets, not choices of statistical methods.

These agent budgets are separate from per-request `SYNTHESIS_LLM_MAX_TOKENS` and
`SYNTHESIS_LLM_TIMEOUT_S` (for example, 8000 output tokens per provider call versus 256000 aggregate session tokens). CLI method paths are relative to the working directory;
repeated `--method-source` values add to task-provided sources.

```bash
metaagent workflow run --task-config task.yaml --output-dir runs/review --json
metaagent workflow run --profile MP5 --dataset-root path/to/diagnostic \
  --start-at pooling --estimates-input coding.jsonl --synthesis-backend pi \
  --research-question 'Analyze the incubation-period evidence and state assumptions.' \
  --method-source original_methods.pdf --output-dir runs/mp5_analysis --json
```

The workflow acquires identity-only PMID/DOI primary and declared supplemental documents through the same verified PDF/MinerU resolver as independent Coding. Missing sources remain visible and user-provided Markdown is labelled as text without a PDF. Pi automatically receives the acquired primary PDFs/text matching the coding report identities, separately from explicit original-method documents. A profile with `source_review_pmid` can supply the original review PDF automatically when no methods were specified; failures are recorded as source gaps and do not invent a method. Pooling-only table input can resolve bibliographic identifiers to primary PDFs, but never opens arbitrary `evidence_file` paths from table cells. The workflow source manifest binds identity, role and byte hashes; acquisition happens only during an actual run.

Use `workflow plan` or `workflow run --dry-run` with the same arguments to inspect
the path without side effects. Workflow analysis flags include
`--synthesis-max-executions`, `--synthesis-max-turns`, `--synthesis-max-tokens`, `--synthesis-total-timeout-s`,
`--synthesis-exec-timeout-s` and `--pi-command`. Method-source bytes, agent settings,
Pi resources/version and synthesis implementation are part of the pooling
fingerprint, so changed methods or budgets invalidate that stage's resume. They do
not change the screening/coding scientific inputs. Input tables and execution
artifacts also retain their normal content hashes.

`--json` emits one JSON document on stdout; operational output goes to stderr.
Missing input/method files and invalid flags/budgets also return one JSON error
document with a nonzero usage exit code. Without `--json`, normal CLI usage errors
remain on stderr.
`complete` exits zero. Partial, failed or scientifically pending results retain
their real artifacts and exit nonzero; they are not converted into a successful
deterministic fallback. Plans return `planned` with exit zero. Inspect the declared
analysis plan, selection/transformation ledger, generated code, execution receipt,
validated result and report rather than treating a prose answer as computation.

The standalone agent's `--resume` continues a matching incomplete analysis.
A matching verified completion is reusable without another model request; changed
input/source/question/settings cannot overwrite a prior result. Use a new output
directory for a deliberately different analysis. Workflow's existing `--resume`
option passes through to Pi and continues the same managed incomplete pooling
attempt, retaining the original log and writing a separate resume log. Completed
workflow stages still reuse only verified content/config/output hashes.

Existing tasks that omit `synthesis` still select `deterministic`; the explicit
legacy example is `configs/templates/review_task.deterministic.yaml`. The existing
`synthesis run --protocol ...` contract below remains available.

## Generated-code sandbox

Generated analysis code runs under bubblewrap, never on the host. The sandbox
unshares the network and every other namespace it can, drops all capabilities,
and starts the interpreter with a cleared environment.

Threads are available. Child processes are not.

- `fork` and `vfork` are refused with `EPERM`.
- `clone` is refused with `EPERM` unless its flags carry `CLONE_THREAD`, so a
  thread can start but a new process cannot.
- `clone3` answers `ENOSYS` on purpose. glibc tries `clone3` first and falls
  back to `clone` only when it sees `ENOSYS`; refusing `clone3` outright would
  leave no way to start a thread at all.

A thread shares the sandbox address space and inherits every limit below, so
allowing threads opens no way out of the sandbox. Libraries that start a
thread at import time therefore work — matplotlib builds its font cache that
way.

Process creation stays closed, so generated code cannot shell out, cannot use
`subprocess` or `multiprocessing`, and cannot reach the host filesystem through
a child process.

Each execution is bounded:

| Limit | Value |
| --- | --- |
| Wall time | `exec_timeout_s`, default 60 s, at most 120 s |
| Address space | `memory_bytes`, default 2 GiB, at most 4 GiB |
| CPU time | the wall-time budget plus one second |
| One output file | `max_output_bytes`, default 16 MiB, at most 32 MiB |
| Output directory | `max_output_bytes` and `max_output_files`, default 64 files, at most 256 |
| Open files | 128 |
| Processes and threads | the host user's thread count plus 128 |
| Captured stdout and stderr | `max_log_bytes`, default 64 KiB, at most 256 KiB |

Inside the sandbox, `/inputs`, `/sources`, `/helpers`, `/analysis_plan.json` and
the staged code file are read-only. Only `/work` is writable, and `/tmp` is a
temporary filesystem. The environment is cleared apart from a fixed list:
`PATH`, `LANG`, `LC_ALL`, `PYTHONPATH`, `PYTHONNOUSERSITE`,
`PYTHONDONTWRITEBYTECODE`, `MPLCONFIGDIR` and four thread-count variables
pinned to one thread each.

Python and R are supported. R needs `Rscript` on the host; without it the
execution returns a recoverable error and the agent switches to Python. The
code must be a regular staged file under the workspace `code` directory, not a
symbolic link.

## Analysis manuals

The agent pulls domain manuals through the `read_skill` action. The manuals
are staged into the workspace with the run and are hashed into the synthesis
fingerprint, so a changed manual invalidates an earlier resume.

| Manual | Covers |
| --- | --- |
| `estimands` | turning the question and the coding rows into one estimand, and choosing the pooling route |
| `epidemiology_parameters` | pooling each coded parameter, with the traps that change the estimand |
| `python_meta_analysis` | statsmodels and scipy recipes, checked against the installed versions |
| `r_meta_analysis` | metafor and meta recipes, for a host that has an R runtime |
| `sandbox_environment` | what the sandbox holds and what it permits |

`profile` lists the manuals with their descriptions, and the tool schema
carries the `read_skill` contract.

The Python recipes were executed in this sandbox. The R recipes were not:
the host has no R runtime, and the manual says so where it matters.

A complete run against the real provider is recorded in
[`docs/validation/synthesis_skills_e2e_20261105/`](../../docs/validation/synthesis_skills_e2e_20261105/VERIFICATION.md):
the tool calls the agent made, the manuals it chose to pull, the plan, the
code, both sandbox receipts and the published result with its independent
verification. That run also found and fixed six defects in the manuals and
one in the relay's budget accounting; the report lists them.

## Deterministic protocol API

`run_synthesis(records, protocol, *, llm_invoke=None)` selects immutable coding
records, validates independent units, computes registered deterministic estimators,
and returns JSON-safe results, decisions, raw input values, transformations, weights
and requested sensitivity analyses. No full text, gold values or reference members
are read by this module.

`write_synthesis_artifacts(result, directory)` writes the authoritative JSON,
selection JSONL, numeric report, study-weight JSONL, PNG/PDF forest plot and requested
sensitivity JSON. Forest images show at most 80 estimates, explicitly marked when
truncated; the numeric JSONL always contains all selected estimates.

`run_analyses(records, protocols, output_dir=None, *, llm_invoke=None)` returns the
multi-analysis summary, or `(summary, artifact_paths)` when a directory is supplied.
Independent numbered output directories prevent path traversal via analysis IDs.

## Method registry

- `fixed`, `random`, `reml`: inverse-variance estimates, DL random effects or REML.
  Explicit uncertainty rules authorize reported SE, normal CI-width approximation,
  or SD/sqrt(n). Source CI level is required. No missing SE imputation, CrI conversion,
  or median-to-mean conversion occurs. Optional `log_transform` is delta-method
  inverse-variance pooling on log scale, not an inferred choice.
- `median`: descriptive sample median of selected study estimates. No averaging or
  mean conversion. `median_interval_method: none` emits no interval; `order_statistic`
  requests the conservative sign/order-statistic CI. If the requested level has no
  finite order-statistic interval at that sample size, the result explicitly says so.
  This does not reconstruct a source review's undisclosed median algorithm.
- `binomial`: aggregate matched events and denominators under a declared common-risk,
  independent-binomial assumption. Explicit Wilson or equal-tailed Clopper-Pearson
  intervals support zero and all-event counts without correction. This is a common-risk
  aggregate, not random-effects proportion meta-analysis.
- `logit_fixed`, `logit_random`, `logit_reml`: counts-derived logit inverse-variance
  pooling. Zero/all-event observations require explicit positive continuity correction;
  otherwise they remain review inputs. The correction is added to event/non-event
  cells of boundary studies only, with the raw counts preserved and the exact
  transformation recorded. No correction is applied to aggregate-binomial methods.

## Example protocol

```yaml
analysis_id: example_cfr
parameter_type: CFR
estimate_measure: count_only
unit: proportion
method: logit_random
independence:
  unit: cohort_id
  multiple_estimates: review
binomial_rules:
  interval_method: wilson
  zero_event_policy: continuity
  continuity_correction: 0.5
filters:
  stratum: [overall]
  period_start: {gte: '2020-01-01', lte: '2021-12-31'}
leave_one_out: true
sensitivity:
  - name: fixed_effect_check
    method: logit_fixed
    exclude_estimate_ids: []
```

Canonical proportion units are `proportion` or `%`. Count-based methods derive
proportions only when explicitly selected and the matched nonnegative integer counts
are valid. An optional `input_measures` list permits declared input types alongside
`estimate_measure`; extraction scope is never inferred from available values.

The inverse-variance methods require `uncertainty_rules: {allowed_types: [SE, CI, SD]}`.
`allow_unit_conversion: true` authorizes compatible time/proportion unit conversion;
all raw values and conversion factors remain in the output.

`independence.unit` accepts `cohort_id`, `study_family_id`, or explicitly authorized
`record_id` plus `assert_independent_reports: true`. Multiple estimates for one unit
are all held for review unless the protocol selects known estimate IDs using
`multiple_estimates: select_ids` and `selected_estimate_ids`. Exact/list filters and
explicit `eq/in/not_in/gte/lte` comparisons support strata and numeric/ISO-date windows.
Unknown identity and uninterpretable filter fields remain review inputs.

## Optional synthesis-model explanations

`llm_selection` and `llm_report` enable calls through the independent `synthesis`
runtime. Selection explanations must match deterministic decisions, known estimate
IDs and existing protocol fields. They cannot repair missing evidence, infer cohort
links or perform the removed Coding B stage. Reports choose an allowed statement
template and refer to existing numeric JSON pointers; numbers are filled by code.
Unknown citations, invented numeric paths and free-form factual claims are rejected.
Optional failures leave the authoritative deterministic result unchanged, and their
status/usage/raw responses are preserved. The default report is deterministic.

CLI: `metaagent synthesis run --input records.jsonl --protocol analysis.yaml --output run/`
Optional flags: `--llm-report`, `--llm-selection`.

Schema introspection: `AnalysisProtocol.model_json_schema()`; method names are in
`metaagent.synthesis.methods.METHOD_REGISTRY`. Unsupported methods/options produce
`protocol_pending`, not guessed defaults. `partial` means a finite result has inputs
awaiting review; `single_estimate` is distinct from a multi-study pooled result.
