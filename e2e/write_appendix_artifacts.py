#!/usr/bin/env python3
"""Write supplementary benchmark tables and four-way coding comparison figure."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib as mpl
import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba


ROOT = Path(__file__).resolve().parents[1]
LATEX = ROOT / "docs" / "paper" / "latex"
LATEX_TABLES = LATEX / "tables"
LATEX_FIG = LATEX / "figures"
OUT = ROOT / "docs" / "paper" / "coding" / "compare_leads"
SOURCE_DATA = ROOT / "docs" / "paper" / "source_data" / "coding_estimate_intervals.csv"
RECALL_NNS = ROOT / "docs" / "paper" / "source_data" / "recall_nns_model_sources.csv"
LEADS_ESTIMATES = ROOT / "evaluation" / "leads_coding_official_final_results" / "sr_5d_leads_official_final_estimates.csv"
TRACKING = ROOT / "e2e" / "runs" / "screen_to_coding" / "e2e_pooled_mean_tracking.csv"


PROFILE_ORDER = [
    "P10",
    "P11",
    "P12",
    "P13",
    "P14",
    "P7",
    "P8",
    "P15",
    "P16",
    "P17",
    "P4",
    "P5",
    "P6",
    "MP5",
    "MP6",
    "MP10",
    "MP11",
    "MP9",
    "MP4",
    "MP7",
    "MP8",
    "MP12",
]

PROFILE_SORT = {profile: idx for idx, profile in enumerate(PROFILE_ORDER)}
SOURCE_LABELS = {
    "P10": "Madewell et al., 2023",
    "P11": "Xu et al., 2023",
    "P12": "Alene et al., 2021",
    "P13": "Ali et al., 2022",
    "P14": "Rai et al., 2021",
    "P7": "Dhungel et al., 2022",
    "P8": "Ahammed et al., 2021",
    "P15": "Billah et al., 2020",
    "P16": "Yu et al., 2021",
    "P17": "Alimohamadi et al., 2020",
    "P4": "Lim et al., 2021",
    "P5": "Ioannidis et al., 2021",
    "P6": "Alimohamadi et al., 2021",
    "MP5": "Wang et al., 2022",
    "MP6": "Ponce et al., 2024",
    "MP10": "Wu et al., 2025",
    "MP11": "Diaz Brochero et al., 2025",
    "MP9": "Okoli et al., 2024",
    "MP4": "Cadmus et al., 2024",
    "MP7": "Vasudevan et al., 2025",
    "MP8": "Sharif et al., 2023",
    "MP12": "Sanchez Clemente et al., 2024",
}


@dataclass(frozen=True)
class Estimate:
    point: float | None
    lo: float | None
    hi: float | None
    unit: str


mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
        "font.size": 8.5,
        "axes.labelsize": 8.7,
        "axes.titlesize": 9.5,
        "xtick.labelsize": 8.1,
        "ytick.labelsize": 8.0,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "figure.dpi": 600,
        "savefig.dpi": 600,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.unicode_minus": False,
    }
)

COLORS = {
    "SR": "#4F545C",
    "Module": "#4E82B4",
    "E2E": "#D08A2E",
    "LEADS": "#8A5A9E",
}
CI_ALPHA = 0.56
DARK = "#252525"
GRID = "#E7E7E7"
ROW_GAP = 1.48


def _finite(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _latex_escape(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "_": r"\_",
        "#": r"\#",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _fmt_profile(profile: str) -> str:
    return _latex_escape(profile)


def _fmt_review(profile: str) -> str:
    text = SOURCE_LABELS.get(profile, profile)
    if text == "Alimohamadi et al., 2020":
        return r"\makecell[l]{Alimohamadi\\et al., 2020}"
    if text == "Alimohamadi et al., 2021":
        return r"\makecell[l]{Alimohamadi\\et al., 2021}"
    if text == "Diaz Brochero et al., 2025":
        return r"\makecell[l]{Diaz Brochero\\et al., 2025}"
    if text == "Sanchez Clemente et al., 2024":
        return r"\makecell[l]{Sanchez Clemente\\et al., 2024}"
    return _latex_escape(text)


def _fmt_param(topic: object) -> str:
    text = str(topic)
    mapping = {
        "Serial Interval": "Serial interval",
        "serial_interval": "Serial interval",
        "Reproduction Number": r"\makecell[c]{Reproduction\\number}",
        "reproduction_number": r"\makecell[c]{Reproduction\\number}",
        "Fatality": "Fatality",
        "fatality": "Fatality",
    }
    return mapping.get(text, _latex_escape(text))


def _profile_from_screening(row: pd.Series) -> str:
    project = int(float(row["project"]))
    return f"{'MP' if str(row['disease']).lower() == 'mpox' else 'P'}{project}"


def _unit(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    if text in {"%", "d"}:
        return text
    return ""


def _estimate(point: object, lo: object, hi: object, unit: object) -> Estimate:
    return Estimate(_finite(point), _finite(lo), _finite(hi), _unit(unit))


def _parse_leads_estimate(text: object) -> Estimate:
    raw = str(text)
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", re.sub(r"(?<=\d)\s*-\s*(?=\d)", ",", raw))]
    unit = "%"
    if "day" in raw:
        unit = "d"
    elif "%" not in raw:
        unit = ""
    if not nums:
        return Estimate(None, None, None, unit)
    return Estimate(nums[0], nums[1] if len(nums) > 2 else None, nums[2] if len(nums) > 2 else None, unit)


def _fmt_estimate(est: Estimate) -> str:
    if est.point is None:
        return ""
    unit = r"\%" if est.unit == "%" else f" {est.unit}" if est.unit else ""
    if est.lo is None or est.hi is None:
        return f"{est.point:.2f}{unit}"
    lo = max(0.0, est.lo) if est.unit == "%" else est.lo
    hi = min(100.0, est.hi) if est.unit == "%" else est.hi
    return rf"\shortstack[c]{{{est.point:.2f}{unit}\\({lo:.2f}--{hi:.2f})}}"


def _target_type(row: pd.Series) -> str:
    label = str(row.get("parameter_label", "")).strip()
    note = "" if pd.isna(row.get("sr_note")) else str(row.get("sr_note")).strip()
    if note:
        label = f"{label}; {note}"
    replacements = {
        "Serial interval; mixed": "Serial interval; mixed variant target",
        "Serial interval; post-peak": "Serial interval; post-peak target",
        "Serial interval; fixed": "Serial interval; fixed-effect SR target",
        "CFR; Wilson CI from 13/226": "Aggregate CFR; Wilson CI",
        "Pediatric CFR; <=11": "Pediatric CFR; SR point treated as 11%",
    }
    return replacements.get(label, label)


def _reference_note(row: pd.Series) -> str:
    profile = str(row.get("profile", ""))
    notes = {
        "P10": "Mixed-variant endpoint.",
        "P13": "Post-peak endpoint.",
        "P14": "Fixed-effect endpoint.",
        "P5": "Median IFR; no interval.",
        "MP5": "Incubation-period endpoint.",
        "MP4": "Wilson interval reconstructed from reported numerator/denominator.",
        "MP8": "Wilson CI reconstructed.",
        "MP12": "Pediatric endpoint.",
    }
    return notes.get(profile, "")


def _load_four_way_rows() -> pd.DataFrame:
    leads = pd.read_csv(LEADS_ESTIMATES)
    tracking = pd.read_csv(TRACKING)
    source = pd.read_csv(SOURCE_DATA)
    leads["profile"] = leads["profile"].astype(str).str.upper()
    tracking["profile"] = tracking["profile"].astype(str).str.upper()
    source["profile"] = source["project"].astype(str).str.upper()
    rows = leads.merge(
        tracking[
            [
                "profile",
                "unit",
                "topic",
                "sr_point",
                "sr_ci_lower",
                "sr_ci_upper",
                "previous_module_point",
                "previous_module_ci_lower",
                "previous_module_ci_upper",
                "e2e_pooled_mean",
                "e2e_ci_lower",
                "e2e_ci_upper",
                "pool_method",
            ]
        ],
        on="profile",
        how="left",
        validate="one_to_one",
    ).merge(source[["profile", "parameter_label", "sr_note"]], on="profile", how="left", validate="one_to_one")
    rows["order"] = rows["profile"].map(PROFILE_SORT)
    return rows.sort_values("order", kind="stable").reset_index(drop=True)


def write_benchmark_description_table() -> None:
    df = pd.read_csv(RECALL_NNS)
    df = df[
        df["model_source"].eq("calibrated_qwen3_6_plus_v1_recall")
        & df["row_type"].eq("project")
    ].copy()
    df["profile"] = df.apply(_profile_from_screening, axis=1)
    df["selected"] = df["tp"].astype(int) + df["fp"].astype(int)
    df["order"] = df["profile"].map(PROFILE_SORT)
    df = df.sort_values("order", kind="stable")

    lines = [
        r"% !TEX root = ../main.tex",
        r"\begin{table}[H]",
        r"\centering",
        r"\caption{Benchmark source-review inventory. Raw pool denotes PubMed records in the reconstructed source-review screening pool; GT denotes source-review included studies used as the task-specific ground truth.}",
        r"\label{tab:benchmark-description}",
        r"\small",
        r"\renewcommand{\arraystretch}{1.12}",
        r"\begin{tabular}{>{\centering\arraybackslash}p{0.12\textwidth}>{\centering\arraybackslash}p{0.18\textwidth}p{0.44\textwidth}rr}",
        r"\toprule",
        r"Disease & Parameter & Source review & Raw pool & GT \\",
        r"\midrule",
    ]

    overall_raw = overall_gt = 0
    disease_order = [("covid19", "COVID-19"), ("mpox", "Mpox")]
    topic_order = ["serial_interval", "reproduction_number", "fatality"]
    for disease_index, (disease_key, disease_label) in enumerate(disease_order):
        disease_df = df[df["disease"].eq(disease_key)]
        disease_raw = int(disease_df["raw"].sum())
        disease_gt = int(disease_df["gt"].sum())
        overall_raw += disease_raw
        overall_gt += disease_gt
        disease_span = 0
        topic_frames: list[tuple[str, pd.DataFrame]] = []
        for topic_key in topic_order:
            topic_df = disease_df[disease_df["topic"].eq(topic_key)].copy()
            if topic_df.empty:
                continue
            topic_frames.append((topic_key, topic_df))
            disease_span += len(topic_df) + (1 if len(topic_df) > 1 else 0)

        first_disease_row = True
        for topic_key, topic_df in topic_frames:
            topic_raw = int(topic_df["raw"].sum())
            topic_gt = int(topic_df["gt"].sum())
            topic_cell = (
                rf"\multirow[c]{{{len(topic_df)}}}{{0.18\textwidth}}{{\centering {_fmt_param(topic_key)}}}"
                if len(topic_df) > 1
                else _fmt_param(topic_key)
            )
            for row_index, (_, row) in enumerate(topic_df.iterrows()):
                disease_cell = (
                    rf"\multirow[c]{{{disease_span}}}{{0.12\textwidth}}{{\centering {disease_label}}}"
                    if first_disease_row
                    else ""
                )
                lines.append(
                    " & ".join(
                        [
                            disease_cell,
                            topic_cell if row_index == 0 else "",
                            _fmt_review(str(row["profile"])),
                            f"{int(row['raw']):,}",
                            f"{int(row['gt']):,}",
                        ]
                    )
                    + r" \\"
                )
                first_disease_row = False
            if len(topic_df) > 1:
                lines.append(
                    rf" &  & \textit{{Subtotal}} & \textbf{{{topic_raw:,}}} & \textbf{{{topic_gt:,}}} \\"
                )
            lines.append(r"\cmidrule(lr){2-5}")
        lines.append(rf" &  & \textbf{{Total}} & \textbf{{{disease_raw:,}}} & \textbf{{{disease_gt:,}}} \\")
        lines.append(r"\midrule" if disease_index == 0 else r"\midrule")

    lines.extend(
        [
            rf"\textbf{{Overall}} &  &  & \textbf{{{overall_raw:,}}} & \textbf{{{overall_gt:,}}} \\",
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
        ]
    )
    path = LATEX_TABLES / "benchmark_description.tex"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


def write_coding_selection_table(rows: pd.DataFrame) -> None:
    lines = [
        r"% !TEX root = ../main.tex",
        r"\begin{table}[H]",
        r"\centering",
        r"\caption{Source-review reference endpoints used for coding evaluation. Notes are shown only when the reference endpoint required a subgroup choice, non-primary endpoint choice, or interval reconstruction.}",
        r"\label{tab:coding-estimate-selection}",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{3.0pt}",
        r"\renewcommand{\arraystretch}{1.12}",
        r"\begin{tabular}{@{}>{\centering\arraybackslash}p{0.050\textwidth}>{\raggedright\arraybackslash}p{0.135\textwidth}>{\centering\arraybackslash}p{0.115\textwidth}>{\raggedright\arraybackslash}p{0.240\textwidth}>{\centering\arraybackslash}p{0.130\textwidth}>{\raggedright\arraybackslash}p{0.230\textwidth}@{}}",
        r"\toprule",
        r"Profile & Source review & Domain & Reference endpoint & SR reference & Note \\",
        r"\midrule",
    ]
    for _, row in rows.iterrows():
        unit = row.get("unit")
        sr = _estimate(row.get("sr_point"), row.get("sr_ci_lower"), row.get("sr_ci_upper"), unit)
        lines.append(
            " & ".join(
                [
                    _fmt_profile(str(row["profile"])),
                    _fmt_review(str(row["profile"])),
                    _fmt_param(row.get("topic")),
                    _latex_escape(_target_type(row)),
                    _fmt_estimate(sr),
                    _latex_escape(_reference_note(row)),
                ]
            )
            + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}"])
    path = LATEX_TABLES / "coding_estimate_selection.tex"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


def _row_estimates(row: pd.Series) -> dict[str, Estimate]:
    unit = row.get("unit")
    return {
        "SR": _estimate(row.get("sr_point"), row.get("sr_ci_lower"), row.get("sr_ci_upper"), unit),
        "Module": _estimate(
            row.get("previous_module_point"),
            row.get("previous_module_ci_lower"),
            row.get("previous_module_ci_upper"),
            unit,
        ),
        "E2E": _estimate(row.get("e2e_pooled_mean"), row.get("e2e_ci_lower"), row.get("e2e_ci_upper"), unit),
        "LEADS": _parse_leads_estimate(row.get("leads_official")),
    }


def _row_label(profile: str) -> str:
    label = SOURCE_LABELS.get(profile, profile)
    label = label.replace(" et al., ", ", ")
    return label


def _axis_label(unit: str) -> str:
    if unit == "%":
        return "Estimate (%)"
    if unit == "d":
        return "Estimate (days)"
    return "Estimate"


def _xlim(chunk: pd.DataFrame) -> tuple[float, float]:
    vals: list[float] = []
    for _, row in chunk.iterrows():
        for est in _row_estimates(row).values():
            vals.extend([v for v in (est.point, est.lo, est.hi) if v is not None])
    if not vals:
        return 0.0, 1.0
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, abs(hi) * 0.08, 1.0)
    pad = span * 0.10
    if lo >= 0:
        return 0.0, hi + pad
    return lo - pad, hi + pad


def _draw_estimate(ax: plt.Axes, y: float, est: Estimate, method: str, marker: str, z: int) -> None:
    if est.point is None:
        return
    color = COLORS[method]
    if est.lo is not None and est.hi is not None:
        ax.hlines(y, est.lo, est.hi, color=to_rgba(color, CI_ALPHA), linewidth=0.76, zorder=z)
        ax.plot([est.lo, est.hi], [y, y], "|", color=to_rgba(color, CI_ALPHA), markersize=4.0, zorder=z)
    ax.scatter(
        est.point,
        y,
        marker=marker,
        s=21,
        facecolor=color,
        edgecolor="white",
        linewidth=0.30,
        zorder=z + 1,
    )


def _plot_panel(ax: plt.Axes, chunk: pd.DataFrame, title: str) -> None:
    chunk = chunk.reset_index(drop=True)
    offsets = {"SR": 0.36, "Module": 0.12, "E2E": -0.12, "LEADS": -0.36}
    markers = {"SR": "s", "Module": "o", "E2E": "D", "LEADS": "^"}
    y_base = np.arange(len(chunk))[::-1] * ROW_GAP
    xlim = _xlim(chunk)
    for y, (_, row) in zip(y_base, chunk.iterrows()):
        estimates = _row_estimates(row)
        ax.axhline(y, color="#F4F4F4", linewidth=0.34, zorder=-1)
        if estimates["SR"].point is not None:
            sr_x = estimates["SR"].point
            for method in ("Module", "E2E", "LEADS"):
                if estimates[method].point is not None:
                    ax.plot([sr_x, estimates[method].point], [y, y], color="#D6D6D6", linewidth=0.36, zorder=0)
        for z, method in enumerate(("SR", "Module", "E2E", "LEADS"), start=2):
            _draw_estimate(ax, y + offsets[method], estimates[method], method, markers[method], z)

    ax.set_xlim(*xlim)
    ax.set_ylim(-1.08, (len(chunk) - 1) * ROW_GAP + 0.96)
    ax.set_yticks(y_base)
    ax.set_yticklabels([_row_label(str(p)) for p in chunk["profile"]], color=DARK)
    ax.set_title(title, loc="left", fontsize=9.5, color=DARK, pad=3.5)
    ax.set_xlabel(_axis_label(str(chunk["unit"].iloc[0]) if "unit" in chunk else ""), color=DARK)
    ax.xaxis.grid(True, color=GRID, linewidth=0.35)
    ax.yaxis.grid(False)
    ax.tick_params(axis="y", length=0, pad=3)
    ax.tick_params(axis="x", length=2.8, width=0.55, pad=2.5)
    ax.spines["left"].set_color("#666666")
    ax.spines["bottom"].set_color("#666666")
    ax.spines["left"].set_linewidth(0.55)
    ax.spines["bottom"].set_linewidth(0.55)


def write_four_way_figure(rows: pd.DataFrame) -> None:
    groups = [
        ("COVID-19", "covid19", "serial_interval", "Serial interval"),
        ("COVID-19", "covid19", "reproduction_number", "Reproduction number"),
        ("COVID-19", "covid19", "fatality", "Fatality"),
        ("Mpox", "mpox", "serial_interval", "Serial interval"),
        ("Mpox", "mpox", "reproduction_number", "Reproduction number"),
        ("Mpox", "mpox", "fatality", "Fatality"),
    ]
    fig = plt.figure(figsize=(7.25, 7.25))
    subfigs = fig.subfigures(nrows=1, ncols=2, wspace=0.055)
    for col, (subfig, disease_label, disease) in enumerate(zip(np.atleast_1d(subfigs), ["COVID-19", "Mpox"], ["covid19", "mpox"])):
        disease_groups = [g for g in groups if g[1] == disease]
        ratios = [max(1.35, 0.80 * len(rows[(rows["disease"] == d) & (rows["topic"] == t)])) for _, d, t, _ in disease_groups]
        if disease == "mpox":
            ratios[1] = 1.45
        axes = subfig.subplots(nrows=3, ncols=1, gridspec_kw={"height_ratios": ratios, "hspace": 0.48})
        subfig.text(0.00, 0.972, "ab"[col], fontsize=10.0, fontweight="bold", color=DARK, ha="left", va="top")
        subfig.text(0.065, 0.972, disease_label, fontsize=9.4, color=DARK, ha="left", va="top")
        for ax, (_, d, topic, title) in zip(np.atleast_1d(axes), disease_groups):
            chunk = rows[(rows["disease"] == d) & (rows["topic"] == topic)].copy()
            chunk = chunk.sort_values("order", kind="stable")
            _plot_panel(ax, chunk, title)
        subfig.subplots_adjust(left=0.39 if disease == "covid19" else 0.34, right=0.99, top=0.895, bottom=0.070)

    handles = [
        mlines.Line2D([], [], color=to_rgba(COLORS["SR"], CI_ALPHA), marker="s", markerfacecolor=COLORS["SR"], markeredgecolor="white", linestyle="-", linewidth=0.8, markersize=4.6, label="SR"),
        mlines.Line2D([], [], color=to_rgba(COLORS["Module"], CI_ALPHA), marker="o", markerfacecolor=COLORS["Module"], markeredgecolor="white", linestyle="-", linewidth=0.8, markersize=4.6, label="Module"),
        mlines.Line2D([], [], color=to_rgba(COLORS["E2E"], CI_ALPHA), marker="D", markerfacecolor=COLORS["E2E"], markeredgecolor="white", linestyle="-", linewidth=0.8, markersize=4.6, label="E2E"),
        mlines.Line2D([], [], color=to_rgba(COLORS["LEADS"], CI_ALPHA), marker="^", markerfacecolor=COLORS["LEADS"], markeredgecolor="white", linestyle="-", linewidth=0.8, markersize=4.6, label="LEADS"),
    ]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 1.005), ncol=4, frameon=False, fontsize=8.6, handlelength=1.45, columnspacing=1.35)

    for fmt in ("pdf", "png", "svg"):
        out_dir = OUT / fmt
        latex_dir = LATEX_FIG / fmt
        out_dir.mkdir(parents=True, exist_ok=True)
        latex_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"coding_compare_e2e_module_leads_sr.{fmt}"
        fig.savefig(path, bbox_inches="tight", pad_inches=0.035, dpi=600)
        (latex_dir / path.name).write_bytes(path.read_bytes())
        print(f"Wrote {latex_dir / path.name}")
    plt.close(fig)


def main() -> None:
    LATEX_TABLES.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = _load_four_way_rows()
    write_benchmark_description_table()
    write_coding_selection_table(rows)
    write_four_way_figure(rows)


if __name__ == "__main__":
    main()
