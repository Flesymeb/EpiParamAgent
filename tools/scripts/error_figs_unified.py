#!/usr/bin/env python3
"""Clean, non-overlapping error-analysis figures.
Fixes: rotated short labels (no multi-line xticks), larger canvas for donut,
muted journal palette, generous padding.
Numbers aligned to landed audit CSVs (match Appendix J text).
"""
import csv
from collections import Counter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10,
    "axes.titlesize": 12.5, "axes.labelsize": 10.5,
    "axes.spines.top": False, "axes.spines.right": False,
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "figure.dpi": 150,
})
OUT = "docs/paper/latex/figures/pdf"

# muted, journal-style palette (no neon)
C_FN = {"FULLTEXT_ONLY": "#4C72B0", "SPARSE_OR_BORDERLINE": "#DD8452", "NON_PRIMARY_OR_TANGENTIAL": "#8C8C8C"}
C_FP = {
    "MODELING_ASSUMED_INPUT": "#C44E52",
    "DIFFERENT_QUANTITY":     "#DD8452",
    "NON_PRIMARY_STUDY":      "#8C8C8C",
    "ELIGIBILITY_SCOPE":      "#4C72B0",
    "ABSTRACT_LIMITATION":    "#8172B3",
    "PARAMETER_ABSENT":       "#937860",
    "OTHER":                  "#444444",
}
FN_LBL = {
    "FULLTEXT_ONLY":             "Recoverable in full text",
    "SPARSE_OR_BORDERLINE":      "Sparse / borderline",
    "NON_PRIMARY_OR_TANGENTIAL": "Non-primary / tangential",
}
FP_SHORT = {
    "MODELING_ASSUMED_INPUT": "Modeling / assumed input",
    "DIFFERENT_QUANTITY":     "Different quantity",
    "NON_PRIMARY_STUDY":      "Non-primary study",
    "ELIGIBILITY_SCOPE":      "Eligibility scope",
    "ABSTRACT_LIMITATION":    "Not in abstract",
    "PARAMETER_ABSENT":       "Parameter absent",
    "OTHER":                  "Other",
}
DOM_ORDER = ["Reproduction\nnumber", "Serial\ninterval", "Fatality"]

fp = list(csv.DictReader(open("docs/paper/source_data/error_fp_record_taxonomy.csv")))
fn = list(csv.DictReader(open("docs/paper/source_data/error_fn_record_taxonomy.csv")))
N_FP = len(fp); N_FN = len(fn)

FN_CAT = ["FULLTEXT_ONLY", "SPARSE_OR_BORDERLINE", "NON_PRIMARY_OR_TANGENTIAL"]
FP_CAT = ["MODELING_ASSUMED_INPUT", "DIFFERENT_QUANTITY", "NON_PRIMARY_STUDY",
          "ELIGIBILITY_SCOPE", "ABSTRACT_LIMITATION", "PARAMETER_ABSENT", "OTHER"]

# ---------- Fig 1: FN stacked ----------
M_fn = np.zeros((3, 3), dtype=int)
dom_key = ["Reproduction number", "Serial interval", "Fatality"]
for r in fn:
    if r["parameter"] in dom_key and r["category"] in FN_CAT:
        M_fn[dom_key.index(r["parameter"]), FN_CAT.index(r["category"])] += 1
fig, ax = plt.subplots(figsize=(5.6, 4.4))
bottom = np.zeros(3)
for j, c in enumerate(FN_CAT):
    vals = M_fn[:, j]
    ax.bar(range(3), vals, bottom=bottom, color=C_FN[c], label=FN_LBL[c],
           edgecolor="white", linewidth=1.0, width=0.56)
    for i, v in enumerate(vals):
        if v > 0:
            ax.text(i, bottom[i] + v/2, str(v), ha="center", va="center",
                    color="white", fontsize=10, fontweight="bold")
    bottom += vals
for i in range(3):
    ax.text(i, bottom[i] + 0.3, f"n={int(bottom[i])}", ha="center", va="bottom", fontsize=9, color="#333")
ax.set_xticks(range(3)); ax.set_xticklabels(DOM_ORDER, fontsize=9.5)
ax.set_ylabel(f"False negatives (n = {N_FN})")
ax.set_title("False-negative causes by parameter domain", fontweight="bold", pad=12)
ax.set_ylim(0, max(bottom) + 2.6)
ax.legend(loc="upper right", fontsize=8.2, frameon=False, handlelength=1.1)
fig.tight_layout()
fig.savefig(f"{OUT}/error_fn_stacked_by_domain.pdf", bbox_inches="tight")
fig.savefig(f"{OUT}/error_fn_stacked_by_domain.png", bbox_inches="tight", dpi=200)
plt.close(fig)

# ---------- Fig 2: FP donut (larger canvas, labels spread) ----------
cc = Counter(r["category"] for r in fp)
items = [(c, FP_SHORT[c], cc.get(c, 0)) for c in FP_CAT]
total = sum(x[2] for x in items)
fig, ax = plt.subplots(figsize=(10.5, 6.2))
sizes = [max(x[2], 1e-4) for x in items]
wedges, _ = ax.pie(sizes, colors=[C_FP[x[0]] for x in items], startangle=140,
                   wedgeprops=dict(width=0.38, edgecolor="white", linewidth=1.8),
                   counterclock=False)
ax.set_aspect("equal")
ax.text(0, 0.10, "False positives", ha="center", va="center", fontsize=13.5, fontweight="bold")
ax.text(0, -0.04, f"n = {total}", ha="center", va="center", fontsize=10, color="#555")
ax.text(0, -0.18, "record-level, full population", ha="center", va="center", fontsize=8.5, color="#999", style="italic")
# spread labels vertically to avoid stacking; use elbow leader lines
label_pts = []
for w, lbl, cnt in zip(wedges, [x[1] for x in items], [x[2] for x in items]):
    if cnt == 0:
        continue
    ang = (w.theta2 + w.theta1) / 2.0
    ang_rad = np.deg2rad(ang)
    x = np.cos(ang_rad); y = np.sin(ang_rad)
    horiz = "left" if x >= 0 else "right"; sign = 1 if x >= 0 else -1
    r1 = 1.30
    label_pts.append((ang, x, y, horiz, sign, r1, lbl, cnt))
# sort by angle so we can nudge y to avoid overlap on each side
left = sorted([p for p in label_pts if p[3] == "left"], key=lambda p: -p[1])  # top to bottom by y
right = sorted([p for p in label_pts if p[3] == "right"], key=lambda p: -p[1])
def place(side_list, base_x):
    # assign y positions with min spacing
    placed = []
    min_gap = 0.42
    for (_, x, y, horiz, sign, r1, lbl, cnt) in side_list:
        y0 = r1 * y
        if placed:
            y0 = min(y0, placed[-1][1] - min_gap)
        placed.append((x, y0, horiz, sign, r1, lbl, cnt))
    return placed
for side in [left, right]:
    placed = place(side, None)
    for (x, y_text, horiz, sign, r1, lbl, cnt) in placed:
        x_elbow = r1 * (x / abs(x) if x else 1) if False else r1 * np.cos(np.deg2rad(0))
        # elbow from rim to (r1*cos, y_text) then horizontal to label
        ang = [p[0] for p in side if p[1:3] == (x, y_text) or True]  # fallback
# simpler robust placement: explicit y per side
def draw_side(side_list, sign):
    placed = []
    min_gap = 0.46
    for (_, x, y, horiz, sg, r1, lbl, cnt) in side_list:
        y0 = r1 * y
        if placed and y0 > placed[-1][0] - min_gap:
            y0 = placed[-1][0] - min_gap
        placed.append((y0, x, y, r1, lbl, cnt))
    for (y_text, x, y, r1, lbl, cnt) in placed:
        x_rim = np.cos(np.arctan2(y, x)); y_rim = np.sin(np.arctan2(y, x))
        x_elbow = r1 * x_rim
        ax.plot([x_rim, x_elbow, x_elbow + sign*0.18], [y_rim, r1*y_rim, y_text],
                color="#888", lw=0.8, zorder=1)
        ax.text(x_elbow + sign*0.20, y_text, f"{lbl}\n{cnt} ({cnt/total*100:.1f}%)",
                ha=horiz, va="center", fontsize=8.8, zorder=2)
draw_side(left, 1); draw_side(right, -1)
ax.set_xlim(-2.9, 2.9); ax.set_ylim(-1.85, 1.85)
fig.tight_layout()
fig.savefig(f"{OUT}/error_taxonomy_fp.pdf", bbox_inches="tight")
fig.savefig(f"{OUT}/error_taxonomy_fp.png", bbox_inches="tight", dpi=200)
plt.close(fig)

# ---------- Fig 3: FP heatmap (rotated short labels) ----------
M_fp = np.zeros((3, len(FP_CAT)), dtype=int)
for r in fp:
    if r["parameter"] in dom_key and r["category"] in FP_CAT:
        M_fp[dom_key.index(r["parameter"]), FP_CAT.index(r["category"])] += 1
Mpct = M_fp / M_fp.sum(axis=1, keepdims=True) * 100
fig, ax = plt.subplots(figsize=(8.8, 4.0))
im = ax.imshow(Mpct, cmap="Blues", aspect="auto", vmin=0, vmax=75)
ax.set_xticks(range(len(FP_CAT)))
ax.set_xticklabels([FP_SHORT[c] for c in FP_CAT], fontsize=8.6, rotation=28, ha="right")
ax.set_yticks(range(3)); ax.set_yticklabels(["Reproduction number", "Serial interval", "Fatality"], fontsize=9.5)
for i in range(3):
    for j in range(len(FP_CAT)):
        cnt = M_fp[i, j]; pct = Mpct[i, j]
        col = "white" if pct > 45 else "#222"
        ax.text(j, i, f"{cnt}\n({pct:.0f}%)", ha="center", va="center", fontsize=8.0, color=col)
ax.set_title("False-positive cause by parameter domain", fontweight="bold", pad=12)
cbar = fig.colorbar(im, ax=ax, fraction=0.024, pad=0.03)
cbar.set_label("% within parameter domain", fontsize=8.5)
cbar.ax.tick_params(labelsize=7.8)
for i in range(3):
    ax.text(len(FP_CAT) - 0.5 + 0.7, i, f"n={M_fp[i].sum()}", ha="left", va="center", fontsize=8.0, color="#444")
ax.set_xlim(-0.5, len(FP_CAT) + 1.6)
fig.tight_layout()
fig.savefig(f"{OUT}/error_fp_domain_cat_heatmap.pdf", bbox_inches="tight")
fig.savefig(f"{OUT}/error_fp_domain_cat_heatmap.png", bbox_inches="tight", dpi=200)
plt.close(fig)

# ---------- Fig 4: FP mismatch bar (rotated short labels) ----------
def bucket(m):
    m = (m or "").lower()
    if any(k in m for k in ["risk factor","prognost","biomarker","severity","association","odds","predictor","regression coefficient","smr","hazard"]):
        return "Risk factors / prognosis"
    if any(k in m for k in ["death","mortality","lethal","raw count","excess"]):
        return "Deaths / mortality"
    if any(k in m for k in ["rt_vs","re not","effective re","secondary attack"]):
        return "Effective Re / SAR"
    if any(k in m for k in ["incubation","generation"]):
        return "Incubation / generation"
    if any(k in m for k in ["seroprev","prevalence","incidence"]):
        return "Seroprevalence / incidence"
    if any(k in m for k in ["growth","doubling"]):
        return "Growth / doubling rate"
    if any(k in m for k in ["simulat","model_input","assumed","model-derived","model parameter","theoretical","forecast","derived"]):
        return "Model-derived / simulated"
    if any(k in m for k in ["scope","geography","population","denominator","variant","setting"]):
        return "Population / geography"
    if any(k in m for k in ["review","case report","case series","editorial","commentary","surveillance"]):
        return "Non-primary study"
    return None
mis = Counter()
for r in fp:
    b = bucket(r["mismatch_type"])
    if b: mis[b] += 1
MIS_ORDER = ["Risk factors / prognosis", "Deaths / mortality", "Effective Re / SAR",
             "Incubation / generation", "Seroprevalence / incidence", "Growth / doubling rate",
             "Model-derived / simulated", "Population / geography", "Non-primary study"]
MIS_COLOR = ["#C44E52","#DD8452","#4C72B0","#8172B3","#55A868","#937860","#8C8C8C","#8C8C8C","#8C8C8C"]
order = [(m, mis.get(m,0), c) for m, c in zip(MIS_ORDER, MIS_COLOR) if mis.get(m,0) > 0]
fig, ax = plt.subplots(figsize=(8.6, 4.8))
xpos = np.arange(len(order))
ax.bar(xpos, [o[1] for o in order], color=[o[2] for o in order], edgecolor="white", linewidth=1.0, width=0.64)
for i, o in enumerate(order):
    ax.text(i, o[1] + 8, f"{o[1]} ({o[1]/N_FP*100:.1f}%)", ha="center", va="bottom", fontsize=8.4)
ax.set_xticks(xpos)
ax.set_xticklabels([o[0] for o in order], fontsize=8.6, rotation=28, ha="right")
ax.set_ylabel("False-positive records")
ax.set_title("Estimator / quantity mismatches among false positives", fontweight="bold", pad=12)
ax.set_ylim(0, max(o[1] for o in order) * 1.22)
tot = sum(o[1] for o in order)
ax.text(0.99, 0.97, f"{tot} of {N_FP} FPs ({tot/N_FP*100:.0f}%)\nreport a related-but-different quantity",
        transform=ax.transAxes, ha="right", va="top", fontsize=8.4, color="#444",
        bbox=dict(boxstyle="round,pad=0.35", fc="#f7f7f7", ec="#ccc", lw=0.7))
fig.tight_layout()
fig.savefig(f"{OUT}/error_fp_mismatch_bar.pdf", bbox_inches="tight")
fig.savefig(f"{OUT}/error_fp_mismatch_bar.png", bbox_inches="tight", dpi=200)
plt.close(fig)
print("done; mismatch total", tot)
