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
