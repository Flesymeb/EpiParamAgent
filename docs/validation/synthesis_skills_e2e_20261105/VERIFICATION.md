# End-to-end validation of the synthesis skill manuals

This bundle records one complete run of the real Pi agent against the real
provider, using the five synthesis manuals through the `read_skill` tool.
The agent chose which manuals to pull, wrote the plan, wrote the code, ran it
in the sandbox and finalized the result. Nothing here is a mock or a replay.

## The run

- Status: `complete`, published result `complete`
- Pi version: 1.3.0, model `qwen3.8-27b-fp8`
- Provider: `pjlab` at `https://token.pjlab.org.cn/v1`, thinking `disabled`, temperature `0.1`
- Budget granted: 20 turns, 600000 tokens, 1200.0 s wall clock, 120.0 s per execution
- Provider attempts: 13 (coverage complete), reported tokens 172643
- Charged against the budget: 172643 tokens
- Coding table: 6 input rows, 4 selected, 2 excluded
- Plan reproduction_status: `exploratory`

## The tool calls the agent actually made

```
  1. profile
  2. query
  3. evidence
  4. read_skill  (rejected)
  5. read_skill
  6. read_skill
  7. read_skill
  8. method_capabilities
  9. save_plan  (rejected)
 10. evidence
 11. save_plan
 12. write_code
 13. run_code
 14. finalize
```

Totals: `evidence` x2, `finalize` x1, `method_capabilities` x1, `profile` x1, `query` x1, `read_skill` x4, `run_code` x1, `save_plan` x2, `write_code` x1.

2 calls were refused by the tool, and the agent recovered from
both:

- `read_skill` — Validation failed for tool "epi_tool": - payload: must be object Received arguments: { "action": "read_skill", "payload": "{\"name\":" }
- `save_plan` — {"ok":false,"error":{"type":"ValueError","message":"Method/source quotations must be exact staged source text","recoverable":true}}

One sent a truncated payload and the other a source quotation that was not
exact staged text. The tool refused both instead of guessing, and the agent
repaired its own call and carried on.

## The manuals the agent pulled

- `read_skill` -> `estimands`
- `read_skill` -> `epidemiology_parameters`
- `read_skill` -> `python_meta_analysis`

3 of the five manuals were requested. The agent decided this itself:
the `profile` tool lists the manuals and their descriptions, and nothing in the
prompt names a manual. `estimands` and `epidemiology_parameters` fixed the estimand
and the pooling route, and `python_meta_analysis` supplied the SE derivation, the
ledger expression and the pooling code. `r_meta_analysis` and
`sandbox_environment` were not pulled: the agent had no R runtime to use and the
sandbox rules were already in the always-on prompt.

The manuals staged into the agent workspace are the exact files that were read;
`read_skill` re-hashes each file before returning it, so the hashes below are the
ones the agent saw.

- `epidemiology_parameters` — How to pool each parameter this project codes, with the traps that change the estimand. (4089 characters, sha256 `daea54af3fd418ef`)
- `estimands` — How to turn the research question and the coding rows into one defensible estimand, and which pooling route it belongs to. (3708 characters, sha256 `23291f07ed1248ad`)
- `python_meta_analysis` — Recipes for pooling the selected coding rows with statsmodels and scipy inside the analysis sandbox, verified against the installed versions. (10683 characters, sha256 `874bce0641973ace`)
- `r_meta_analysis` — metafor and meta recipes for the R route, with the runtime precondition stated up front. (6215 characters, sha256 `9b4810a51bfce2ce`)
- `sandbox_environment` — What the analysis sandbox actually contains and permits, checked against this environment. (3310 characters, sha256 `b4127015c3f6863c`)

## The plan the agent saved

- parameter_type: `incubation_period`, statistic `mean`, unit `days`
- uncertainty: `{"level": 0.95, "type": "CI"}`
- method: `random`, interval `normal` at level `0.95`, tau `DL`, prediction interval `False`
- selected input ids: `['r1', 'r2', 'r3', 'r5']`
- excluded input ids: `None`
- reproduction_status: `exploratory`
- assumptions: 5, sensitivity checks: 3, declared transformations: 4

Assumptions the agent declared:

- Each selected row is an independent cohort (distinct cohort_id and study).
- CI-derived SEs assume a symmetric normal interval at the reported confidence level.
- The 90% CI row (r4) is excluded rather than reinterpreted at 95%.
- The median/IQR row (r6) is excluded as a different statistic.
- Pooling is exploratory on the current data: the original method is followed (DL random effects, 95% normal CI, hours-to-days conversion, one estimate per cohort), but the current table differs from the original review's included set, so this is not a reproduction.

## The code the agent wrote

```python
import json
import math
from pathlib import Path
import numpy as np
from scipy.stats import norm
from statsmodels.stats.meta_analysis import combine_effects

# ── Read inputs ──────────────────────────────────────────────────────────────
rows = [json.loads(line) for line in Path('/inputs/table.jsonl').read_text().splitlines() if line.strip()]
plan = json.loads(Path('/analysis_plan.json').read_text())
chosen = set(plan['selection']['selected_input_ids'])
selected = sorted([row for row in rows if row['input_id'] in chosen], key=lambda r: r['input_id'])

# ── SE derivation (mirrors the deterministic engine) ─────────────────────────
DIVISOR_95 = 2 * float(norm.ppf(0.975))  # 3.919927969080108

def se_from_row(row):
    kind = str(row.get('uncertainty_type') or '').strip().upper()
    if not kind and row.get('se') is not None:
        kind = 'SE'
    if kind == 'SE':
        return float(row['se']), {'method': 'reported_se', 'input': float(row['se'])}
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
        return (high - low) / (2 * z), {'method': 'normal_ci_width', 'low': low, 'high': high, 'level': level, 'z': z}
    raise ValueError(f"Unsupported uncertainty type: {kind!r}")

# ── Apply unit conversion and derive SEs ─────────────────────────────────────
contributions = []
transformations = []

for row in selected:
    iid = row['input_id']
    unit = row['unit']
    point = float(row['point_estimate'])
    se_raw, se_info = se_from_row(row)

    if unit == 'hours':
        point_days = point / 24.0
        se_days = se_raw / 24.0
        # point transformation ledger
        transformations.append({
            'input_id': iid,
            'field': 'point_estimate',
            'before': point,
            'after': point_days,
            'expression': 'point_estimate / 24',
            'reason': 'Convert hours to days per the original method (divide by 24).'
        })
        # se transformation ledger (CI-derived, then /24)
        transformations.append({
            'input_id': iid,
            'field': 'se',
            'before': None,
            'after': se_days,
            'expression': '(uncertainty_high - uncertainty_low) / 3.919927969080108 / 24',
            'reason': 'Derive SE from the reported 95% CI in hours, then convert to days by dividing by 24.'
        })
    else:
        point_days = point
        se_days = se_raw
        # se transformation ledger (CI-derived, no unit conversion)
        if se_info['method'] == 'normal_ci_width':
            transformations.append({
                'input_id': iid,
                'field': 'se',
                'before': None,
                'after': se_days,
                'expression': '(uncertainty_high - uncertainty_low) / 3.919927969080108',
                'reason': f"Derive SE from the reported 95% CI ({row['uncertainty_low']}, {row['uncertainty_high']}) assuming a symmetric normal interval."
            })
        # r3 has a direct SE, no transformation needed

    contributions.append({
        'input_id': iid,
        'value_used': point_days,
        'se_used': se_days,
        'weight': None  # filled after pooling
    })

# ── Pool: DL random effects (primary) ────────────────────────────────────────
effect = np.array([c['value_used'] for c in contributions], dtype=float)
variance = np.array([c['se_used'] ** 2 for c in contributions], dtype=float)

random_dl = combine_effects(effect, variance, method_re='chi2', use_t=False)
frame = random_dl.summary_frame()
random_row = frame.loc[frame.index == 'random effect'].iloc[0]
pooled = float(random_row['eff'])
ci_low = float(random_row['ci_low'])
ci_high = float(random_row['ci_upp'])
tau2 = float(random_dl.tau2)
q = float(random_dl.q)
i2 = float(random_dl.i2)

# Normalized RE weights
re_weights = 1.0 / (variance + tau2)
re_weights_norm = re_weights / re_weights.sum()
for c, w in zip(contributions, re_weights_norm):
    c['weight'] = float(w)

# ── Sensitivity 1: fixed effects ─────────────────────────────────────────────
fixed = combine_effects(effect, variance, method_re='chi2', use_t=False)
fixed_row = fixed.summary_frame().loc[fixed.summary_frame().index == 'fixed effect'].iloc[0]
fixed_pooled = float(fixed_row['eff'])
fixed_ci_low = float(fixed_row['ci_low'])
fixed_ci_high = float(fixed_row['ci_upp'])

# ── Sensitivity 2: REML ──────────────────────────────────────────────────────
random_reml = combine_effects(effect, variance, method_re='iterated', use_t=False)
reml_row = random_reml.summary_frame().loc[random_reml.summary_frame().index == 'random effect'].iloc[0]
reml_pooled = float(reml_row['eff'])
reml_ci_low = float(reml_row['ci_low'])
reml_ci_high = float(reml_row['ci_upp'])
reml_tau2 = float(random_reml.tau2)

# ── Sensitivity 3: exclude r5 ────────────────────────────────────────────────
idx_no_r5 = [i for i, c in enumerate(contributions) if c['input_id'] != 'r5']
effect_no_r5 = effect[idx_no_r5]
variance_no_r5 = variance[idx_no_r5]
random_dl_no_r5 = combine_effects(effect_no_r5, variance_no_r5, method_re='chi2', use_t=False)
no_r5_row = random_dl_no_r5.summary_frame().loc[random_dl_no_r5.summary_frame().index == 'random effect'].iloc[0]
no_r5_pooled = float(no_r5_row['eff'])
no_r5_ci_low = float(no_r5_row['ci_low'])
no_r5_ci_high = float(no_r5_row['ci_upp'])
no_r5_tau2 = float(random_dl_no_r5.tau2)

# ── Forest plot ──────────────────────────────────────────────────────────────
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(8, 5))
labels = [f"{c['input_id']} ({c['value_used']:.2f} d, SE {c['se_used']:.3f})" for c in contributions]
y_pos = range(len(contributions))
for i, c in enumerate(contributions):
    lo = c['value_used'] - 1.96 * c['se_used']
    hi = c['value_used'] + 1.96 * c['se_used']
    ax.errorbar(c['value_used'], i, xerr=[[c['value_used']-lo],[hi-c['value_used']]],
                fmt='o', color='steelblue', capsize=4, markersize=6)
ax.axvline(pooled, color='red', linestyle='--', linewidth=1.5, label=f"Pooled: {pooled:.3f} d")
ax.set_yticks(list(y_pos))
ax.set_yticklabels(labels, fontsize=9)
ax.set_xlabel('Mean incubation period (days)')
ax.set_title('Forest plot: pooled mean incubation period (DL random effects)')
ax.legend()
ax.invert_yaxis()
plt.tight_layout()
plt.savefig('/work/forest.png', dpi=150)
plt.savefig('/work/forest.pdf')
plt.close()

# ── Write result ─────────────────────────────────────────────────────────────
result = {
    'status': 'complete',
    'result': {
        'point_estimate': pooled,
        'unit': 'days',
        'method': 'random',
        'ci_lower': ci_low,
        'ci_upper': ci_high,
        'ci_level': 0.95,
        'interval_type': 'CI',
        'tau2': tau2,
        'Q': q,
        'I2': i2
    },
    'contributions': contributions,
    'transformations': transformations,
    'sensitivity': [
        {
            'name': 'fixed_effects',
            'result': {'point_estimate': fixed_pooled, 'ci_lower': fixed_ci_low, 'ci_upper': fixed_ci_high, 'ci_level': 0.95},
            'selected_input_ids': [c['input_id'] for c in contributions],
            'interpretation': 'Fixed-effect pool for comparison; assesses sensitivity to the random-effects assumption.'
        },
        {
            'name': 'reml',
            'result': {'point_estimate': reml_pooled, 'ci_lower': reml_ci_low, 'ci_upper': reml_ci_high, 'ci_level': 0.95, 'tau2': reml_tau2},
            'selected_input_ids': [c['input_id'] for c in contributions],
            'interpretation': 'REML random-effects pool; assesses sensitivity to the DL tau2 estimator.'
        },
        {
            'name': 'exclude_r5',
            'result': {'point_estimate': no_r5_pooled, 'ci_lower': no_r5_ci_low, 'ci_upper': no_r5_ci_high, 'ci_level': 0.95, 'tau2': no_r5_tau2},
            'selected_input_ids': [c['input_id'] for c in contributions if c['input_id'] != 'r5'],
            'interpretation': 'DL random-effects pool excluding the hours-converted row r5; assesses sensitivity to the unit conversion.'
        }
    ],
    'limitations': [
        'Exploratory analysis on current data; not a reproduction of the original review.',
        'r4 (Dilmore 2021, 90% CI) excluded: CI level not harmonizable to 95% without unsupported assumption.',
        'r6 (Fraser 2022, median/IQR) excluded: different statistic per original method and review exclusions.',
        'CI-derived SEs assume symmetric normal intervals at the reported confidence level.',
        'Only 4 independent cohorts; heterogeneity estimates (tau2, I2) are imprecise.',
        'No publication bias assessment performed (insufficient studies for Egger test).'
    ]
}

Path('/work/result.json').write_text(json.dumps(result, indent=2))
print('Done. Pooled:', pooled, 'CI:', ci_low, '-', ci_high, 'tau2:', tau2, 'I2:', i2)
```

## The executions

### Execution 1

- status: `complete`, return code `0`
- validation_status: not set on this receipt; the repeat check runs on the second execution
- sandbox: `"bubblewrap"`, network: `"unshared"`
- wall time: 1.039708461961709 s
- limits: `{"walltime_s": 120, "memory_bytes": 2147483648, "output_bytes": 16777216, "output_files": 64, "log_bytes": 65536, "host_uid_process_thread_cap": 6159, "host_uid_headroom": 128, "generated_process_creation": "seccomp_denied"}`
- code sha256: `10a6deab872811554977226170f73e121899316aa3d102f86a9debb094ea198f`
- plan sha256: `eec4efaeda6d285eb3ecc45c0b6bf84f00af1314cc868dde1a98067cd1f7614f`
- outputs: `forest.pdf` (16295 bytes), `result.json` (4024 bytes), `forest.png` (49469 bytes)

### Execution 2

- status: `complete`, return code `0`
- validation_status: `verified`
- sandbox: `"bubblewrap"`, network: `"unshared"`
- wall time: 1.0607589250430465 s
- limits: `{"walltime_s": 120, "memory_bytes": 2147483648, "output_bytes": 16777216, "output_files": 64, "log_bytes": 65536, "host_uid_process_thread_cap": 6170, "host_uid_headroom": 128, "generated_process_creation": "seccomp_denied"}`
- code sha256: `10a6deab872811554977226170f73e121899316aa3d102f86a9debb094ea198f`
- plan sha256: `eec4efaeda6d285eb3ecc45c0b6bf84f00af1314cc868dde1a98067cd1f7614f`
- outputs: `forest.pdf` (16295 bytes), `result.json` (4024 bytes), `forest.png` (49469 bytes)

`run_code` runs the code twice and refuses inconsistent output, so the second
receipt carries `validation_status: verified`. The two `result.json` files are
byte-identical; the two `forest.pdf` files differ because a PDF embeds its own
creation timestamp, while `forest.png` is identical.

## The published result

- status: `complete`
- point estimate: 5.238908179149273 days
- interval: [4.788537394208007, 5.689278964090538] at level 0.95 (CI)
- tau2: 0.08370425702542335, Q: 4.988938698503375, I2: 0.3986697008524146
- validation: `{"numeric_provenance": "sandbox_executed_and_repeated", "scientific_correctness": "not_independently_verified"}`
- independent verification: `verified` (synthesis-statistics-v1), checked ['point_estimate', 'tau2', 'ci_lower', 'ci_upper']
- its scope: `numerical_consistency_not_scientific_eligibility_or_independence`

Contributions:

| input_id | study | source unit | value_used | se_used | weight |
| --- | --- | --- | --- | --- | --- |
| `r1` | Alvarez 2020 | days | 5.2 | 0.30612807415479243 | 0.2976082437229644 |
| `r2` | Boot 2020 | days | 6.1 | 0.4591921112321885 | 0.17925366012774316 |
| `r3` | Chen 2021 | days | 4.8 | 0.4 | 0.21666118969980738 |
| `r5` | Ewing 2022 | hours | 5.083333333333333 | 0.2976245165393815 | 0.306476906449485 |

Transformation ledger, re-evaluated by the tool against the original rows:

- `r1` `se`: `(uncertainty_high - uncertainty_low) / 3.919927969080108` -> 0.30612807415479243
- `r2` `se`: `(uncertainty_high - uncertainty_low) / 3.919927969080108` -> 0.4591921112321885
- `r5` `point_estimate`: `point_estimate / 24` -> 5.083333333333333
- `r5` `se`: `(uncertainty_high - uncertainty_low) / 3.919927969080108 / 24` -> 0.2976245165393815

Sensitivity analyses that were actually executed:

- `fixed_effects`: 5.2136929436296935 [4.872260910796545, 5.555124976462842] on `['r1', 'r2', 'r3', 'r5']`
- `reml`: 5.246424196988579 [4.752092523376006, 5.740755870601153] on `['r1', 'r2', 'r3', 'r5']`
- `exclude_r5`: 5.325150532994546 [4.6586002536159095, 5.991700812373183] on `['r1', 'r2', 'r3']`

Limitations the agent recorded:

- Exploratory analysis on current data; not a reproduction of the original review.
- r4 (Dilmore 2021, 90% CI) excluded: CI level not harmonizable to 95% without unsupported assumption.
- r6 (Fraser 2022, median/IQR) excluded: different statistic per original method and review exclusions.
- CI-derived SEs assume symmetric normal intervals at the reported confidence level.
- Only 4 independent cohorts; heterogeneity estimates (tau2, I2) are imprecise.
- No publication bias assessment performed (insufficient studies for Egger test).

## Budget accounting

- Calls with reported usage: 13; the log holds 39 records, because each call leaves a start, a forwarded marker and a completion
- First measured prompt: 4257 tokens; last measured prompt: 20555 tokens
- Last input bound the relay charged: 27981 tokens, above the measured 20555 because the three-bytes-per-token floor and the 512-token framing allowance are deliberately conservative

The relay charges the input side of a request against the token budget. It
used to charge the request body in *bytes*, which overstates the token count
roughly fourfold: a session that had used about a sixth of its token budget
was told the budget was exhausted, and the local 429 was reported as an
upstream error. The bound is now estimated in tokens, floored at three bytes
per token and anchored on the last measured prompt, so a provider that
under-reports usage cannot widen the budget. The charged total above equals
the provider-reported total, because every attempt reported its usage.

## What this validation found and fixed

The run itself was the point, and it earned its keep: the first full attempt
failed twice on the same thing, and the manuals were wrong about it.

1. **The relay charged bytes against a token budget.** The input side of a
   request was reserved as its serialized byte count, which overstates the
   token count about fourfold. A session that had used a sixth of its token
   budget was told the budget was exhausted, and the local 429 was dressed up
   as an upstream error. The bound is now estimated in tokens, floored at
   three bytes per token and anchored on the last measured prompt, so a
   provider that under-reports usage cannot widen the budget. The charged
   total in this run equals the provider-reported total exactly.
2. **The manuals never said how a ledger expression is checked.** Every
   `transformations` entry is re-evaluated by the tool against the original
   row, and the grammar has no quantile function in it. An earlier attempt
   wrote `norm.ppf(0.975)` into the expression and was refused with
   `Unsupported transformation expression`, twice, and never reached a
   published result. The Python manual now states the grammar and gives the
   numeric divisor `2 * z_{0.975} = 3.919927969080108`; the agent used
   exactly that expression on its own in this run.
3. **The manuals explained the `hk` difference wrongly.** They said that
   statsmodels keeps the normal quantile while the engine takes `t(k-1)`.
   Both take `t(k-1)`; the engine additionally rescales the pooled standard
   error by `sqrt(sum(w * (x - pooled)**2) / (k - 1))` and statsmodels does
   not. The conclusion held, the reason did not, and the reason is what an
   agent would reason from.
4. **The manuals did not warn that the pooled weight rows are NaN.** In the
   statsmodels frame the pooled `fixed effect` row carries `w_re` = NaN and
   the pooled `random effect` row carries `w_fe` = NaN. An earlier attempt
   read a weight from the wrong row and the result was rejected as
   non-finite. The manual now says to take per-study weights from the study
   rows, or to compute the normalized share from `1 / (variance + tau2)`.
5. **Two smaller manual errors.** The SE derivation was labelled `ci_to_se`
   where the engine emits `normal_ci_width`, and the sandbox manual said the
   address-space cap was 4 GiB when the default is 2 GiB.
6. **The R recipe was not runnable R.** It read JSON Lines with
   `rows$input_id` on a list, and it pooled `keep$se_used`, a field that does
   not exist in the table. It now reads the table with a union of the row
   columns, derives the SE from the reported uncertainty the way the engine
   does, and applies the unit factor to the point estimate and the standard
   error together.

## Caveats

- **The gateway is intermittent.** `token.pjlab.org.cn` returned
  `service_unavailable_error` on and off during this session, twice in a row
  for this run before it succeeded on the third attempt. The failure is
  upstream and has nothing to do with the code under test; the run was
  repeated, not patched around.
- **The budget granted here is larger than the shipped default.** This run
  was given 20 turns and 600000 tokens; `metaagent.cli synthesis agent`
  defaults to 12 turns and 64000 tokens. The default is too small for this
  workflow: the prompt grows to about 20600 tokens by the last of the 13
  calls, and the 13 calls cost 172643 tokens in total. A default of 12 turns
  also has no room for the repair loop the agent used when the tool refused
  a call.
- **The result is an exploratory current-data analysis.** The plan says so,
  and the published result carries `reproduction_status: exploratory`. It is
  not a reproduction of the original review.
- **The independent oracle checks numbers, not science.** It verified the
  point estimate, `tau2` and both bounds against a separate implementation.
  It says nothing about cohort independence or eligibility, and the
  published result says so with `scientific_correctness:
  not_independently_verified`.
- **The fixture is small.** Six rows, four of them selected, is enough to
  exercise the machinery and not enough to exercise the science.

