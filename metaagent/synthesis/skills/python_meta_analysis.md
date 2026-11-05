---
name: python_meta_analysis
description: Recipes for pooling the selected coding rows with statsmodels and scipy inside the analysis sandbox, verified against the installed versions.
---

# Pooling the selected rows in Python

These recipes were run inside this sandbox with the installed libraries. They
cover the inverse-variance path, which is the one the independent numeric
oracle can verify.

## What the sandbox provides

`numpy`, `pandas`, `scipy`, `matplotlib`, `statsmodels` and `patsy` are
importable. `statsmodels` is 0.14.4 and `scipy` is 1.15.3. `lifelines` is not
installed. `metafor` and `meta` are R packages, so they are unreachable from
Python; see the R manual for that route.

`epi_synthesis_helpers.run_synthesis` and the `metaagent.synthesis` modules
are staged under `/helpers`, so `PYTHONPATH=/helpers` already works. The
deterministic engine is the faster route when the estimand matches one of
its registered methods; use these recipes when the engine does not cover the
case, and always say in the plan which route you took.

## Read the table and the plan

```python
import json
from pathlib import Path

rows = [json.loads(line) for line in Path('/inputs/table.jsonl').read_text().splitlines() if line.strip()]
plan = json.loads(Path('/analysis_plan.json').read_text())
chosen = set(plan['selection']['selected_input_ids'])
selected = [row for row in rows if row['input_id'] in chosen]
```

`/inputs/records.sqlite` holds the same rows in an `estimates` table with the
original columns plus `input_id` and `raw_json`. Use `query` for exploration
and `table.jsonl` inside the generated code.

## Turn reported uncertainty into an SE

The oracle compares standard errors, so every contribution needs `se_used`.
Derive it from what the source reported and record the derivation in the plan
transformation ledger before writing the code.

The derivation must agree with the deterministic engine, otherwise the
independent comparison fails for a reason that has nothing to do with the
science. The engine reads `uncertainty_type` and then uses these fields:

- `SE` — the value of `se`.
- `SD` — the value of `sd` and a numeric `sample_size`.
- `CI` — `uncertainty_low`, `uncertainty_high` and `uncertainty_level`.

A level of `95%` or `95` is read as 0.95. The point estimate must lie inside
the reported interval, and a row whose level, bounds or sample size are
missing is not usable.

```python
import math
from scipy.stats import norm


def se_from_row(row):
    """Mirror the engine's derivation so both routes agree on every row."""
    kind = str(row.get('uncertainty_type') or '').strip().upper()
    if not kind and row.get('se') is not None:
        kind = 'SE'
    if kind == 'SE':
        value = float(row['se'])
        return value, {'method': 'reported_se', 'input': value}
    if kind == 'SD':
        value = float(row['sd'])
        n = float(row['sample_size'])
        if n <= 0:
            raise ValueError('SD needs a numeric sample size')
        return value / math.sqrt(n), {'method': 'sd_div_sqrt_n', 'sd': value, 'n': n}
    if kind == 'CI':
        raw = row.get('uncertainty_level')
        level = float(str(raw).strip().removesuffix('%').strip())
        if str(raw).strip().endswith('%') or 1 < level < 100:
            level /= 100
        low = float(row['uncertainty_low'])
        high = float(row['uncertainty_high'])
        point = float(row['point_estimate'])
        if not 0 < level < 1 or low >= high:
            raise ValueError('Invalid CI bounds or level')
        if not low <= point <= high:
            raise ValueError('Point estimate lies outside the reported CI')
        z = float(norm.ppf((1 + level) / 2))
        return (high - low) / (2 * z), {'method': 'ci_to_se', 'low': low, 'high': high, 'level': level}
    raise ValueError(f"Unsupported uncertainty type: {kind!r}")
```

A confidence level must be explicit. A source interval whose level is not
recorded is not a CI you may reinterpret; keep it as unknown and exclude the
row rather than assume 0.95.

## Pool with statsmodels

`combine_effects` takes the effect and its **variance**, not a standard error.

```python
import numpy as np
from statsmodels.stats.meta_analysis import combine_effects

for row in selected:
    row['_se_used'], row['_se_derivation'] = se_from_row(row)

effect = np.array([row['point_estimate'] for row in selected], dtype=float)
variance = np.array([row['_se_used'] ** 2 for row in selected], dtype=float)

fixed = combine_effects(effect, variance, method_re='chi2', use_t=False)
random_dl = combine_effects(effect, variance, method_re='chi2', use_t=True)
random_pm = combine_effects(effect, variance, method_re='iterated', use_t=False)
```

`method_re` selects the between-study variance estimator for the random
effects model: `'chi2'` is DerSimonian-Laird, `'iterated'` is Paule-Mandel.
The fixed effect estimate is always computed as well.

With `use_t=False` the pooled interval is the normal interval, and it
reproduces the deterministic engine exactly — same point estimate, same
bounds, same `tau2` — so a result written this way passes the independent
comparison. This was checked on the same five effects with both routes.

`use_t=True` is **not** the interval the engine calls `hk`. Both routes use
the same Hartung-Knapp scale for the standard error, but the engine takes a
t quantile with `k-1` degrees of freedom while statsmodels keeps the normal
quantile, so the bounds differ. For `hk`, `modified_hk` and prediction
intervals, use the engine rather than statsmodels; the prediction interval is
`t(k-2)` times the square root of `tau2` plus the interval variance, and it
needs a random effects model with at least three independent estimates.

Read the numbers off `summary_frame()`, whose last four rows are the pooled
rows:

```python
frame = random_dl.summary_frame()
fixed_row = frame.loc[frame.index == 'fixed effect'].iloc[0]
random_row = frame.loc[frame.index == 'random effect'].iloc[0]
pooled = float(random_row['eff'])
ci_low = float(random_row['ci_low'])
ci_high = float(random_row['ci_upp'])
tau2 = float(random_dl.tau2)
q = float(random_dl.q)
i2 = float(random_dl.i2)
```

`tau2`, `q` and `i2` live on the analysis scale you pooled on. When the
effects are log ratios, report them on the log scale and exponentiate only in
the narrative, with the interval endpoints exponentiated as well.

The per-study rows of the same frame carry `w_fe` and `w_re`, the normalized
fixed and random effects weights. A contribution weight in the result must be
the normalized share that sums to one, not the raw inverse variance.

## Proportion effect sizes

When the coding table carries event counts rather than a proportion, turn two
groups into an effect size before pooling:

```python
from statsmodels.stats.meta_analysis import effectsize_2proportions

effect, variance = effectsize_2proportions(
    count1=120, nobs1=1000, count2=150, nobs2=1200, statistic='or')
```

The first pair is the first group and the second pair the comparison group;
`count` is the number of events and `nobs` the group size. `statistic` is
`'diff'` for a risk difference, `'rr'` for a risk ratio and `'or'` for an
odds ratio. A risk ratio and an odds ratio are not the same estimand; pool
the one the question asks for. A zero cell needs `zero_correction`, and the
correction is a declared transformation, not a silent adjustment.

## Write the result

`/work/result.json` must match the schema the tool expects, with `status`,
`result`, `contributions`, `transformations`, `sensitivity` and `limitations`.
Every selected row appears in `contributions` with `input_id`, `value_used`,
`se_used` and `weight`. Rows whose SE came from a CI or an SD need their own
`field='se'` entry in `transformations`, with `before` set to null when the
source had no SE column.

Write the forest plot to `/work/forest.png` and `/work/forest.pdf` from the
same contributions, with the units and the cohort labels on the axis.

## Reproducibility

`run_code` executes the code twice and rejects inconsistent output, so set a
seed for anything random and avoid wall-clock or hash-ordered iteration over
the selected rows. Sort by `input_id` before you compute.
