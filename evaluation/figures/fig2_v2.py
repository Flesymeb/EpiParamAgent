"""
Figure 2 (v2): Two-panel layout
  Left  — NNS vs. prevalence scatter (linear), highlighting P7 vs. P15
  Right — NNS distribution per parameter topic (dot + median bar)

Style: Nature Methods single-column figure (88 mm wide per panel → 180 mm total)
Palette: Wong 2011 colorblind-safe
"""

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines
from scipy.stats import spearmanr

# ── 0. Global style ───────────────────────────────────────────────────────────
matplotlib.rcParams.update({
    "font.family":      "Arial",
    "font.size":        7,
    "axes.linewidth":   0.8,
    "axes.labelsize":   8,
    "axes.titlesize":   8,
    "xtick.major.width":0.8,
    "ytick.major.width":0.8,
    "xtick.major.size": 3,
    "ytick.major.size": 3,
    "xtick.direction":  "out",
    "ytick.direction":  "out",
    "pdf.fonttype":     42,
    "ps.fonttype":      42,
})

# ── 1. Data ───────────────────────────────────────────────────────────────────
configs = [
    # label  topic               gt   pool  nns    lo     hi
    ("P10", "Serial Interval",   28,  599,  1.86,  1.45,  2.62),
    ("P11", "Serial Interval",   76,  841,  1.97,  1.70,  2.36),
    ("P12", "Serial Interval",   20,  145,  2.07,  1.52,  3.29),
    ("P13", "Serial Interval",   51,  111,  1.64,  1.38,  2.03),
    ("P14", "Serial Interval",   9,   94,   5.88,  3.54, 14.33),
    ("P7",  "Reproduction Number",122, 574,  1.58,  1.42,  1.79),
    ("P8",  "Reproduction Number",44,  575,  5.98,  4.67,  8.23),
    ("P15", "Reproduction Number",25,  709, 16.36, 11.74, 25.62),
    ("P16", "Reproduction Number",32,  575,  8.86,  6.55, 13.47),
    ("P17", "Reproduction Number",15,  209,  8.25,  5.30, 16.50),
    ("P4",  "Fatality",           56,  345,  3.96,  3.23,  5.07),
    ("P5",  "Fatality",           48, 1882,  3.43,  2.76,  4.56),
    ("P6",  "Fatality",           32, 2253, 22.83, 16.59, 34.84),
]

TOPICS   = ["Serial Interval", "Reproduction Number", "Fatality"]
COLORS   = {"Serial Interval": "#0072B2",
            "Reproduction Number": "#D55E00",
            "Fatality": "#009E73"}
MARKERS  = {"Serial Interval": "o",
            "Reproduction Number": "s",
            "Fatality": "^"}

# Derived fields
rows = []
for label, topic, gt, pool, nns, lo, hi in configs:
    rows.append(dict(label=label, topic=topic, gt=gt, pool=pool,
                     prev=gt/pool*100, nns=nns, lo=lo, hi=hi))

# ── 2. Figure layout ──────────────────────────────────────────────────────────
fig, axes = plt.subplots(
    1, 2,
    figsize=(7.0, 3.2),          # ~178 mm wide (double-column)
    gridspec_kw={"width_ratios": [1.55, 1], "wspace": 0.38},
)
ax_scatter, ax_dot = axes

# ═══════════════════════════════════════════════════════════════════════════════
# PANEL A — NNS vs. prevalence (linear axes)
# ═══════════════════════════════════════════════════════════════════════════════
ax = ax_scatter

ax.set_axisbelow(True)
ax.grid(axis="both", color="#e8e8e8", linewidth=0.5, linestyle="--")

# — "No screening" reference line —
x_ref = np.linspace(0.5, 52, 300)
ax.plot(x_ref, 100 / x_ref,
        linestyle=":", linewidth=1.1, color="#aaaaaa", zorder=1,
        label="No screening  (NNS = 1/prevalence)")

# — Scatter + 95 % CI error bars —
for r in rows:
    c  = COLORS[r["topic"]]
    mk = MARKERS[r["topic"]]
    ax.errorbar(
        r["prev"], r["nns"],
        yerr=[[r["nns"] - r["lo"]], [r["hi"] - r["nns"]]],
        fmt=mk, color=c,
        markersize=6, markeredgewidth=0.5, markeredgecolor="white",
        elinewidth=0.8, capsize=3, capthick=0.8,
        linewidth=0, zorder=3,
    )

# — Point labels (selected) —
ANNOT = {
    "P7":  {"xy": ( 1.5, -0.6), "ha": "left"},
    "P15": {"xy": ( 1.5,  0.5), "ha": "left"},
    "P6":  {"xy": ( 1.2,  0.5), "ha": "left"},
    "P13": {"xy": (-1.5, -0.8), "ha": "right"},
    "P14": {"xy": ( 1.2,  0.3), "ha": "left"},
    "P5":  {"xy": ( 1.2, -0.8), "ha": "left"},
}
for r in rows:
    if r["label"] in ANNOT:
        a = ANNOT[r["label"]]
        ax.annotate(
            r["label"],
            xy=(r["prev"], r["nns"]),
            xytext=a["xy"], textcoords="offset points",
            fontsize=5.5, color=COLORS[r["topic"]], ha=a["ha"],
        )

# — Highlight P7 vs P15 contrast (label only, no arrow) —
p7  = next(r for r in rows if r["label"] == "P7")
p15 = next(r for r in rows if r["label"] == "P15")

# — Spearman ρ (computed here, injected into legend below) —
prevs = [r["prev"] for r in rows]
nnss  = [r["nns"]  for r in rows]
rho, pval = spearmanr(prevs, nnss)
p_str = "< 0.001" if pval < 0.001 else f"= {pval:.3f}"

# — Axes —
ax.set_xlim(-1, 52)
ax.set_ylim(-0.5, 28)
ax.set_xlabel("Candidate Pool Prevalence (%)", labelpad=4)
ax.set_ylabel("Number Needed to Screen (NNS)", labelpad=4)
ax.set_title("(a)", fontweight="bold", loc="left", pad=4)

# — Legend (topics + reference line) —
topic_handles = [
    mlines.Line2D([], [], marker=MARKERS[t], color=COLORS[t],
                  linestyle="none", markersize=5.5,
                  markeredgecolor="white", markeredgewidth=0.5, label=t)
    for t in TOPICS
]
ref_handle = mlines.Line2D([], [], linestyle=":", color="#aaaaaa",
                            linewidth=1.1, label="No screening")
# Spearman stat as a text-only legend entry (blank handle)
spearman_handle = mpatches.Patch(
    facecolor="none", edgecolor="none",
    label=f"Spearman $\\rho$ = {rho:.2f},  $p$ {p_str}",
)
ax.legend(handles=topic_handles + [ref_handle, spearman_handle],
          loc="upper right", framealpha=0.9, edgecolor="#cccccc",
          fontsize=6, handlelength=1.3, borderpad=0.6, labelspacing=0.4,
          handletextpad=0.4)

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

# ═══════════════════════════════════════════════════════════════════════════════
# PANEL B — NNS per topic (dot plot + median bar + 95 % CI)
# ═══════════════════════════════════════════════════════════════════════════════
ax = ax_dot

ax.set_axisbelow(True)
ax.grid(axis="y", color="#e8e8e8", linewidth=0.5, linestyle="--")

NNS_THRESHOLD = round(8912 / 558, 1)   # = 15.97 ≈ 16.0
                            # overall no-screening NNS: 8,912 pool / 558 GT

x_positions = {t: i+1 for i, t in enumerate(TOPICS)}
JITTER       = 0.13
np.random.seed(42)

for r in rows:
    t  = r["topic"]
    xp = x_positions[t]
    jx = xp + np.random.uniform(-JITTER, JITTER)
    c  = COLORS[t]
    mk = MARKERS[t]

    # Vertical CI line
    ax.plot([jx, jx], [r["lo"], r["hi"]],
            color=c, linewidth=0.7, alpha=0.55, zorder=2)

    # Point
    ax.scatter(jx, r["nns"], marker=mk, s=28,
               color=c, edgecolors="white", linewidths=0.5, zorder=3)

    # Config label for outliers
    if r["label"] in ("P6", "P15", "P14"):
        ax.annotate(
            r["label"],
            xy=(jx, r["nns"]),
            xytext=(4, 1), textcoords="offset points",
            fontsize=5.5, color=c, ha="left",
        )

# — Median bar per topic —
for t in TOPICS:
    xp  = x_positions[t]
    vals = [r["nns"] for r in rows if r["topic"] == t]
    med  = np.median(vals)
    ax.plot([xp - 0.22, xp + 0.22], [med, med],
            color=COLORS[t], linewidth=2.0, solid_capstyle="round", zorder=4)
    ax.text(xp + 0.27, med, f"  median\n  = {med:.1f}",
            fontsize=5.5, color=COLORS[t], va="center")

# — Practical threshold line —
ax.axhline(NNS_THRESHOLD, linestyle="--", linewidth=0.9,
           color="#888888", zorder=1)
ax.text(3.55, NNS_THRESHOLD + 0.4, f"NNS = {NNS_THRESHOLD}\n(no screening\nbaseline)",
        fontsize=5, color="#666666", ha="right", va="bottom")

# — Axes —
ax.set_xlim(0.5, 3.85)
ax.set_ylim(-0.5, 30)
ax.set_xticks([1, 2, 3])
ax.set_xticklabels(
    ["Serial\nInterval", "Reproduction\nNumber", "Fatality"],
    fontsize=7,
)
ax.set_ylabel("Number Needed to Screen (NNS)", labelpad=4)
ax.set_title("(b)", fontweight="bold", loc="left", pad=4)

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

# ── 3. Save ───────────────────────────────────────────────────────────────────
import os
out_dir = os.path.dirname(os.path.abspath(__file__))

fig.tight_layout(pad=0.6)
fig.savefig(os.path.join(out_dir, "fig2_v2.pdf"), dpi=300, bbox_inches="tight")
fig.savefig(os.path.join(out_dir, "fig2_v2.png"), dpi=300, bbox_inches="tight")
print(f"Saved → {out_dir}")
plt.show()
