"""
Figure 2: NNS vs. Candidate Pool Prevalence
Demonstrates that parameter specificity sets the efficiency ceiling for LLM-based screening.

Data source: evaluation/screening/GT_1/结果20260401.txt
Output:     figures/fig2_nns_vs_prevalence.pdf  (vector, for submission)
            figures/fig2_nns_vs_prevalence.png  (300 DPI, for preview)

Style reference: Nature Methods / PLOS Medicine single-column figure
  - Width: 88 mm (~3.46 in)
  - Font: Arial, 7 pt axis labels / 6 pt annotations
  - Colorblind-safe palette (Wong 2011, Nature Methods 8:441)
"""

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from scipy.optimize import curve_fit
from scipy.stats import spearmanr

# ── 0. Global style ──────────────────────────────────────────────────────────
matplotlib.rcParams.update({
    "font.family":        "Arial",
    "font.size":          7,
    "axes.linewidth":     0.8,
    "axes.labelsize":     8,
    "axes.titlesize":     8,
    "xtick.major.width":  0.8,
    "ytick.major.width":  0.8,
    "xtick.major.size":   3,
    "ytick.major.size":   3,
    "xtick.direction":    "out",
    "ytick.direction":    "out",
    "legend.fontsize":    6.5,
    "legend.framealpha":  0.9,
    "legend.edgecolor":   "#cccccc",
    "legend.handlelength":1.4,
    "pdf.fonttype":       42,   # embed fonts in PDF
    "ps.fonttype":        42,
})

# ── 1. Data ───────────────────────────────────────────────────────────────────
# (GT, Pool, NNS_point, NNS_lo_95CI, NNS_hi_95CI)
configs = {
    # ── Serial Interval (n=5) ──────────────────────────────
    "P10": dict(topic="Serial Interval",      gt=28,  pool=599,  nns=1.86,  lo=1.45,  hi=2.62),
    "P11": dict(topic="Serial Interval",      gt=76,  pool=841,  nns=1.97,  lo=1.70,  hi=2.36),
    "P12": dict(topic="Serial Interval",      gt=20,  pool=145,  nns=2.07,  lo=1.52,  hi=3.29),
    "P13": dict(topic="Serial Interval",      gt=51,  pool=111,  nns=1.64,  lo=1.38,  hi=2.03),
    "P14": dict(topic="Serial Interval",      gt=9,   pool=94,   nns=5.88,  lo=3.54,  hi=14.33),
    # ── Reproduction Number (n=5) ──────────────────────────
    "P7":  dict(topic="Reproduction Number",  gt=122, pool=574,  nns=1.58,  lo=1.42,  hi=1.79),
    "P8":  dict(topic="Reproduction Number",  gt=44,  pool=575,  nns=5.98,  lo=4.67,  hi=8.23),
    "P15": dict(topic="Reproduction Number",  gt=25,  pool=709,  nns=16.36, lo=11.74, hi=25.62),
    "P16": dict(topic="Reproduction Number",  gt=32,  pool=575,  nns=8.86,  lo=6.55,  hi=13.47),
    "P17": dict(topic="Reproduction Number",  gt=15,  pool=209,  nns=8.25,  lo=5.30,  hi=16.50),
    # ── Fatality (n=3) ────────────────────────────────────
    "P4":  dict(topic="Fatality",             gt=56,  pool=345,  nns=3.96,  lo=3.23,  hi=5.07),
    "P5":  dict(topic="Fatality",             gt=48,  pool=1882, nns=3.43,  lo=2.76,  hi=4.56),
    "P6":  dict(topic="Fatality",             gt=32,  pool=2253, nns=22.83, lo=16.59, hi=34.84),
}

# Colorblind-safe palette (Wong 2011)
TOPIC_STYLE = {
    "Serial Interval":     dict(color="#0072B2", marker="o", zorder=5),  # blue
    "Reproduction Number": dict(color="#D55E00", marker="s", zorder=5),  # vermillion
    "Fatality":            dict(color="#009E73", marker="^", zorder=5),  # green
}

# Compute prevalence (%) for each config
for cfg in configs.values():
    cfg["prev"] = cfg["gt"] / cfg["pool"] * 100

# ── 2. Aggregate arrays for fitting ──────────────────────────────────────────
all_prev = np.array([v["prev"] for v in configs.values()])
all_nns  = np.array([v["nns"]  for v in configs.values()])

# ── 3. Curve fitting ──────────────────────────────────────────────────────────
# Theoretical "no-screening" baseline: NNS_null = 100 / prevalence(%)
# Empirical fit: power law  NNS = a · prev^b
def power_law(x, a, b):
    return a * np.power(x, b)

popt, _ = curve_fit(power_law, all_prev, all_nns, p0=[20.0, -0.9], maxfev=10_000)
a_fit, b_fit = popt

# Spearman correlation
rho, pval = spearmanr(all_prev, all_nns)

# ── 4. Plot ───────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(3.46, 3.20))   # 88 mm wide

# — Background grid —
ax.set_axisbelow(True)
ax.grid(axis="both", color="#e0e0e0", linewidth=0.5, linestyle="--", zorder=0)

# — Reference line: "no screening" NNS = 100/prev —
x_ref = np.logspace(np.log10(1.0), np.log10(60), 300)
ax.plot(x_ref, 100 / x_ref,
        linestyle=":", linewidth=1.0, color="#888888",
        label="No screening  (NNS = 1/prevalence)", zorder=1)

# — Empirical power-law fit —
x_fit = np.logspace(np.log10(1.0), np.log10(55), 300)
ax.plot(x_fit, power_law(x_fit, a_fit, b_fit),
        linestyle="-", linewidth=1.2, color="#333333", alpha=0.75,
        label=fr"Power-law fit  ($\beta$ = {b_fit:.2f})", zorder=2)

# — Data points with 95 % CI error bars —
for label, d in configs.items():
    style = TOPIC_STYLE[d["topic"]]
    yerr_lo = d["nns"] - d["lo"]
    yerr_hi = d["hi"]  - d["nns"]
    ax.errorbar(
        d["prev"], d["nns"],
        yerr=[[yerr_lo], [yerr_hi]],
        fmt=style["marker"],
        color=style["color"],
        markersize=5.5,
        markeredgewidth=0.5,
        markeredgecolor="white",
        elinewidth=0.7,
        capsize=2.5,
        capthick=0.7,
        linewidth=0,
        zorder=style["zorder"],
        label=None,
    )

# — Config labels for noteworthy points —
LABEL_OFFSETS = {
    "P6":  ( 4,  3),
    "P15": ( 4,  2),
    "P14": ( 4,  2),
    "P13": (-16, -9),
    "P7":  ( 4, -8),
    "P5":  ( 4,  3),
    "P8":  ( 4,  2),
}
for label, d in configs.items():
    if label in LABEL_OFFSETS:
        dx, dy = LABEL_OFFSETS[label]
        style = TOPIC_STYLE[d["topic"]]
        ax.annotate(
            label,
            xy=(d["prev"], d["nns"]),
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=5.5,
            color=style["color"],
            ha="left", va="center",
        )

# — Custom legend (topics only, not fit lines) —
topic_handles = [
    matplotlib.lines.Line2D(
        [0], [0],
        marker=TOPIC_STYLE[t]["marker"],
        color="w",
        markerfacecolor=TOPIC_STYLE[t]["color"],
        markeredgecolor="white",
        markersize=5.5,
        label=t,
    )
    for t in TOPIC_STYLE
]
fit_handles = [
    matplotlib.lines.Line2D([0], [0], linestyle=":", linewidth=1.0,
                             color="#888888", label="No screening"),
    matplotlib.lines.Line2D([0], [0], linestyle="-", linewidth=1.2,
                             color="#333333", alpha=0.75,
                             label=fr"Power-law fit ($\beta$={b_fit:.2f})"),
]
ax.legend(
    handles=topic_handles + fit_handles,
    loc="upper right",
    framealpha=0.9,
    edgecolor="#cccccc",
    fontsize=6,
    handlelength=1.2,
    borderpad=0.6,
    labelspacing=0.35,
)

# — Spearman ρ annotation —
sig_str = "< 0.001" if pval < 0.001 else f"= {pval:.3f}"
ax.text(
    0.97, 0.70,
    f"Spearman $\\rho$ = {rho:.2f}\n$p$ {sig_str}",
    transform=ax.transAxes,
    ha="right", va="top",
    fontsize=6,
    color="#333333",
    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
              edgecolor="#cccccc", linewidth=0.6),
)

# — Axes —
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlim(1.0, 60)
ax.set_ylim(1.0, 40)

ax.set_xlabel("Candidate Pool Prevalence (%)", labelpad=4)
ax.set_ylabel("Number Needed to Screen (NNS)", labelpad=4)

# Clean log-scale tick labels
from matplotlib.ticker import LogFormatter, NullFormatter
ax.xaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
ax.yaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
ax.set_xticks([1, 2, 5, 10, 20, 50])
ax.set_yticks([1, 2, 5, 10, 20])

# Remove top/right spines
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

# ── 5. Save ───────────────────────────────────────────────────────────────────
import os
out_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(out_dir, exist_ok=True)

fig.tight_layout(pad=0.5)
fig.savefig(os.path.join(out_dir, "fig2_nns_vs_prevalence.pdf"),
            dpi=300, bbox_inches="tight")
fig.savefig(os.path.join(out_dir, "fig2_nns_vs_prevalence.png"),
            dpi=300, bbox_inches="tight")
print(f"Saved to {out_dir}")
plt.show()
