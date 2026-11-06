---
name: sandbox_environment
description: What the analysis sandbox actually contains and permits, checked against this environment.
---

# The sandbox as it is

Everything below was checked on this host, not assumed.

## Installed libraries

Read the version you actually get instead of trusting a table:

```python
from importlib.metadata import version
print(version('statsmodels'))
```

The project runs on two hosts with different builds:

| Library | analysis host | source host |
| --- | --- | --- |
| numpy | 2.5.1 | 2.1.3 |
| pandas | 3.0.5 | 2.2.3 |
| scipy | 1.18.0 | 1.15.3 |
| matplotlib | 3.11.1 | 3.10.0 |
| statsmodels | 0.14.4 | 0.14.4 |
| patsy | 1.0.3 | 1.0.1 |
| scikit-learn | not installed | 1.6.1 |

The analysis host runs pandas 3, a major version above the source host's
pandas 2. Text columns get the new `str` dtype there instead of `object`,
and copy behaviour differs. Write frames with `to_csv` rather than relying
on a repr, and read a column before using it in arithmetic, so the code does
not depend on which host runs it. `numpy.asarray` is the safe way to turn an
array into a matrix; `numpy.matrix` is deprecated and will go.

`lifelines` is not installed on either host. `metafor` and `meta` are R
packages, so they are out of reach from Python; there is no R runtime on
either host either.

## The staged helpers

`PYTHONPATH` is `/helpers`, so these import directly inside the sandbox:

- `epi_synthesis_helpers.run_synthesis` — the deterministic engine.
- `metaagent.synthesis.engine`, `methods`, `statistical_verification`,
  `diagnostics` and `plots`.
- `tools.analysis.pooling`.

The engine registers these methods: `fixed`, `random` (DerSimonian-Laird),
`reml`, `median`, `binomial`, `logit_fixed`, `logit_random`, `logit_reml` and
`ft_dl_miller_harmonic`.

The independent oracle covers the inverse-variance methods only — `fixed`,
`random` and `reml` — and only on the declared analysis scale. It compares
the point estimate, `tau2`, the confidence bounds, the supplied weights and
the supplied heterogeneity metrics, and it recomputes them with a separate
implementation. Any other method returns `not_supported` with the reason
`method_has_no_independent_numeric_oracle`, which is a statement about the
oracle's scope and not about the method's validity.

## What the sandbox permits

- No network. The namespace is unshared and the network is unshared with it.
- Threads are allowed. A library that starts a thread at import, such as
  matplotlib, works.
- Child processes are not. `fork`, `vfork` and a `clone` without
  `CLONE_THREAD` are refused, so no `subprocess`, no `multiprocessing`, no
  `os.fork`. `clone3` answers `ENOSYS`, so glibc falls back to `clone` and
  meets the same rule.

## The filesystem and the environment

`/inputs` holds `table.jsonl`, `records.sqlite`, `profile.json` and
`review_context.json`. `/sources` holds the staged method documents as text.
/helpers holds the helper package. `/analysis_plan.json` is the saved plan.
Only `/work` is writable, and `/tmp` is a temporary filesystem.

The environment is cleared apart from `PATH`, `LANG`, `LC_ALL`, `PYTHONPATH`,
`PYTHONNOUSERSITE`, `PYTHONDONTWRITEBYTECODE`, `MPLCONFIGDIR` and four
thread-count variables pinned to one thread each. There are no credentials
in the environment and no host filesystem beyond the mounted paths.

## The budgets

Wall time is the run's `exec_timeout_s`, 120 seconds by default. Address space
is `memory_bytes`, 2 GiB by default. The output directory is bounded by
`max_output_bytes` and `max_output_files`. The captured stdout and stderr
are bounded by `max_log_bytes`, and the whole session is bounded by the
turn, token and tool-call budgets.

## Reading and writing

`/inputs/table.jsonl` holds one JSON object per row, with the original
columns plus `input_id`. `/inputs/records.sqlite` holds the same rows in an
`estimates` table, with the original columns plus `input_id` and `raw_json`.

Write `/work/result.json` for the numbers, `/work/forest.png` and
`/work/forest.pdf` for the plot. `run_code` executes the code twice and
rejects inconsistent output, so seed anything random and sort the rows by
`input_id` before computing.
