"""
Figure 3: Five-dimension relevance radar charts (2 × 3 layout)

  Row 1 — GT vs. Non-GT per parameter topic
  Row 2 — Strong / Possible / Unlikely per parameter topic

Demonstrates that (1) GT papers score higher than non-GT papers on all five
dimensions, especially Parameter Relevance; and (2) the label hierarchy
(Strong > Possible > Unlikely) is consistent with the dimension scores.

Style: Nature Methods double-column figure (180 mm)
Palette: Wong 2011 colorblind-safe
"""

import math
import os
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import pandas as pd
from pathlib import Path

# ── 0. Global style ──────────────────────────────────────────────────────────
matplotlib.rcParams.update({
    "font.family":       "Arial",
    "font.size":         7,
    "axes.linewidth":    0.8,
    "axes.labelsize":    8,
    "axes.titlesize":    8,
    "xtick.major.width": 0.8,
    "ytick.major.width": 0.8,
    "pdf.fonttype":      42,
    "ps.fonttype":       42,
})

# ── 1. Data paths ─────────────────────────────────────────────────────────────
EVAL_ROOT = Path(__file__).parent.parent / "GT_1" / "GT_export"

CONFIGS = {
    "Serial Interval": [
        EVAL_ROOT / "serial_interval/p10/project_10_screened.csv",
        EVAL_ROOT / "serial_interval/p11/project_11_screened.csv",
        EVAL_ROOT / "serial_interval/p12/project_12_screened.csv",
        EVAL_ROOT / "serial_interval/p13/project_13_screened.csv",
        EVAL_ROOT / "serial_interval/p14/project_14_screened.csv",
    ],
    "Reproduction Number": [
        EVAL_ROOT / "reproduction_number/p7/project_7_screened.csv",
        EVAL_ROOT / "reproduction_number/p8/project_8_screened.csv",
        EVAL_ROOT / "reproduction_number/p15/project_15_screened.csv",
        EVAL_ROOT / "reproduction_number/p16/project_16_screened.csv",
        EVAL_ROOT / "reproduction_number/p17/project_17_screened.csv",
    ],
    "Fatality": [
        EVAL_ROOT / "fatality/p4/project_4_screened.csv",
        EVAL_ROOT / "fatality/p5/project_5_screened.csv",
        EVAL_ROOT / "fatality/p6/project_6_screened.csv",
    ],
}

DIMENSIONS = [
    ("disease_score",    "Disease"),
    ("population_score", "Population"),
    ("location_score",   "Location"),
    ("evidence_score",   "Evidence"),
    ("parameter_score",  "Parameter"),
]

TOPICS = ["Serial Interval", "Reproduction Number", "Fatality"]

# ── 2. Load data ──────────────────────────────────────────────────────────────
def load_topic(paths):
    frames = []
    for p in paths:
        df = pd.read_csv(p, dtype=str, low_memory=False)
        df["is_gt"] = df["is_ground_truth"].str.strip() == "✓"
        for col, _ in DIMENSIONS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)

topic_data = {t: load_topic(CONFIGS[t]) for t in TOPICS}

# ── 3. Radar helpers ──────────────────────────────────────────────────────────
N = len(DIMENSIONS)
ANGLES = np.linspace(0, 2 * math.pi, N, endpoint=False)
ANGLES_CLOSED = np.concatenate([ANGLES, ANGLES[:1]])

def close_radar(vals):
    return np.concatenate([vals, vals[:1]])

def dim_means(df, mask):
    sub = df.loc[mask]
    return np.array([sub[col].mean() for col, _ in DIMENSIONS])

# ── 4. Palette ────────────────────────────────────────────────────────────────
# Row 1: GT vs Non-GT
C_GT  = "#0072B2"   # blue
C_NGT = "#E69F00"   # orange

# Row 2: Strong / Possible / Unlikely  (Wong 2011)
SPU_COLORS = {
    "strong_candidate":   "#009E73",   # green
    "possible_candidate": "#56B4E9",   # sky blue
    "unlikely_candidate": "#CC79A7",   # pink/purple
}
SPU_LABELS = {
    "strong_candidate":   "Strong",
    "possible_candidate": "Possible",
    "unlikely_candidate": "Unlikely",
}
SPU_ORDER = ["strong_candidate", "possible_candidate", "unlikely_candidate"]

# ── 5. Helper: configure one polar axis ──────────────────────────────────────
def style_polar(ax, dim_labels):
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 4.5)
    ax.set_yticks([1, 2, 3, 4])
    ax.set_yticklabels(["1", "2", "3", "4"], fontsize=5, color="#999999")
    ax.tick_params(axis="y", pad=1.5)
    ax.set_thetagrids(np.degrees(ANGLES), dim_labels, fontsize=6.5)
    for lbl, adeg in zip(ax.get_xticklabels(), np.degrees(ANGLES)):
        lbl.set_fontsize(6.5)
        lbl.set_color("#333333")
        if abs(adeg - 180) < 20:
            lbl.set_ha("center")
        elif adeg > 180:
            lbl.set_ha("right")
        else:
            lbl.set_ha("left")
    ax.grid(color="#cccccc", linewidth=0.5, linestyle="--")
    ax.spines["polar"].set_color("#cccccc")
    ax.spines["polar"].set_linewidth(0.6)

# ── 6. Build figure (2 rows × 3 cols) ────────────────────────────────────────
dim_labels = [d[1] for d in DIMENSIONS]

fig, axes = plt.subplots(
    2, 3,
    figsize=(7.0, 5.4),
    subplot_kw={"projection": "polar"},
    gridspec_kw={"wspace": 0.55, "hspace": 0.55},
)

row1_labels = ["(a)", "(b)", "(c)"]
row2_labels = ["(d)", "(e)", "(f)"]

# ── Row 1: GT vs Non-GT ───────────────────────────────────────────────────────
for col_i, (topic, panel_lbl) in enumerate(zip(TOPICS, row1_labels)):
    ax = axes[0, col_i]
    df = topic_data[topic]
    gt = df["is_gt"]

    gt_m  = dim_means(df, gt)
    ngt_m = dim_means(df, ~gt)

    ax.plot(ANGLES_CLOSED, close_radar(gt_m),
            linewidth=1.6, color=C_GT, zorder=3, label="GT-positive")
    ax.fill(ANGLES_CLOSED, close_radar(gt_m),
            alpha=0.18, color=C_GT, zorder=2)

    ax.plot(ANGLES_CLOSED, close_radar(ngt_m),
            linewidth=1.4, color=C_NGT, linestyle="--", zorder=3, label="Non-GT")
    ax.fill(ANGLES_CLOSED, close_radar(ngt_m),
            alpha=0.12, color=C_NGT, zorder=2)

    style_polar(ax, dim_labels)
    ax.set_title(
        f"{panel_lbl}  {topic}\n"
        f"GT n={int(gt.sum())}   Non-GT n={int((~gt).sum())}",
        fontsize=7, fontweight="bold", pad=14,
    )

# ── Row 2: Strong / Possible / Unlikely ──────────────────────────────────────
for col_i, (topic, panel_lbl) in enumerate(zip(TOPICS, row2_labels)):
    ax = axes[1, col_i]
    df = topic_data[topic]

    for cls in SPU_ORDER:
        mask = df["llm_suggest"].str.strip() == cls
        if mask.sum() == 0:
            continue
        m = dim_means(df, mask)
        c = SPU_COLORS[cls]
        lbl = f"{SPU_LABELS[cls]} (n={int(mask.sum())})"
        ls = "-" if cls == "strong_candidate" else (
             "--" if cls == "possible_candidate" else ":")
        ax.plot(ANGLES_CLOSED, close_radar(m),
                linewidth=1.4, color=c, linestyle=ls, zorder=3)
        ax.fill(ANGLES_CLOSED, close_radar(m),
                alpha=0.12, color=c, zorder=2)

    style_polar(ax, dim_labels)
    ax.set_title(
        f"{panel_lbl}  {topic}",
        fontsize=7, fontweight="bold", pad=14,
    )

# ── 7. Row legends ────────────────────────────────────────────────────────────
# Row 1 legend (below row 1, above row 2)
row1_handles = [
    mlines.Line2D([], [], color=C_GT,  linewidth=1.6, label="GT-positive"),
    mlines.Line2D([], [], color=C_NGT, linewidth=1.4, linestyle="--", label="Non-GT"),
]
# Row 2 legend (below entire figure)
row2_handles = [
    mlines.Line2D([], [], color=SPU_COLORS[cls], linewidth=1.4,
                  linestyle="-" if cls == "strong_candidate" else
                            ("--" if cls == "possible_candidate" else ":"),
                  label=SPU_LABELS[cls])
    for cls in SPU_ORDER
]

# Place row 1 legend between the two rows
fig.legend(
    handles=row1_handles,
    loc="upper center",
    ncol=2,
    fontsize=6.5,
    framealpha=0.9,
    edgecolor="#cccccc",
    handlelength=1.4,
    borderpad=0.5,
    columnspacing=1.2,
    bbox_to_anchor=(0.5, 0.52),
)

# Place row 2 legend below the figure
fig.legend(
    handles=row2_handles,
    loc="lower center",
    ncol=3,
    fontsize=6.5,
    framealpha=0.9,
    edgecolor="#cccccc",
    handlelength=1.4,
    borderpad=0.5,
    columnspacing=1.2,
    bbox_to_anchor=(0.5, -0.04),
)

# ── 8. Row labels ─────────────────────────────────────────────────────────────
fig.text(0.01, 0.76, "GT vs. Non-GT",
         fontsize=7.5, fontweight="bold", rotation=90, va="center", color="#333333")
fig.text(0.01, 0.27, "Strong / Possible / Unlikely",
         fontsize=7.5, fontweight="bold", rotation=90, va="center", color="#333333")

# ── 9. Save ───────────────────────────────────────────────────────────────────
out_dir = os.path.dirname(os.path.abspath(__file__))

fig.savefig(os.path.join(out_dir, "fig3_dimension_radar.pdf"),
            dpi=300, bbox_inches="tight")
fig.savefig(os.path.join(out_dir, "fig3_dimension_radar.png"),
            dpi=300, bbox_inches="tight")
print(f"Saved → {out_dir}")
plt.show()
