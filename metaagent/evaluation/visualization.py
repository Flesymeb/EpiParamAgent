"""Publication-oriented visualization helpers for evaluation outputs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import pandas as pd


BLUE = "#2166d1"
TEAL = "#088c8c"
DARK = "#083b8a"
GRAY = "#6b7280"
LIGHT_GRID = "#e5e7eb"


def apply_publication_style() -> None:
    """Use a compact, paper-friendly matplotlib style."""
    plt.rcParams.update(
        {
            "font.size": 9,
            "font.family": "DejaVu Sans",
            "axes.labelsize": 9,
            "axes.titlesize": 10,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.08,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": False,
        }
    )


@dataclass(frozen=True)
class ScreeningFigureRow:
    label: str
    recall: float
    recall_low: float | None
    recall_high: float | None
    nns: float
    nns_low: float | None
    nns_high: float | None


@dataclass(frozen=True)
class CodingFigureRow:
    label: str
    group_label: str
    unit: str
    sr: float
    sr_low: float | None
    sr_high: float | None
    llm: float
    llm_low: float | None
    llm_high: float | None


def read_screening_rows(path: Path) -> list[ScreeningFigureRow]:
    """Read screening rows from TSV/CSV summaries.

    Supported sources include this repo's ``paper_summary.tsv`` files and
    combined summary CSVs with similarly named metric columns.
    """
    df = _read_markdown_table(path) if path.suffix.lower() in {".md", ".markdown"} else _read_table(path)
    rows: list[ScreeningFigureRow] = []
    for _, row in df.iterrows():
        label = _first_text(
            row,
            [
                "Review",
                "Study",
                "Paper",
                "Literature",
                "Project",
                "#Project",
                "profile",
                "project",
                "Profile",
            ],
        )
        if not label:
            continue
        if label.strip("* ").lower() in {"all", "subtotal", "total"}:
            continue
        label = _compact_literature_label(label)
        recall, recall_low, recall_high = _metric_with_ci(
            row,
            ["recall", "Recall", "Recall (95% CI)", "recall_ci"],
        )
        nns, nns_low, nns_high = _metric_with_ci(
            row,
            ["nns", "NNS", "NNS (95% CI)", "nns_ci"],
            ratio=True,
        )
        if math.isnan(recall) or math.isnan(nns):
            continue
        rows.append(
            ScreeningFigureRow(
                label=label or f"row {len(rows) + 1}",
                recall=recall,
                recall_low=recall_low,
                recall_high=recall_high,
                nns=nns,
                nns_low=nns_low,
                nns_high=nns_high,
            )
        )
    return rows


def plot_screening_recall_nns(
    rows: list[ScreeningFigureRow],
    output: Path,
    *,
    title: str = "Screening Performance by Literature",
) -> None:
    """Plot per-literature recall and NNS as a two-panel figure."""
    if not rows:
        raise ValueError("No plottable screening rows found.")

    apply_publication_style()
    labels = [r.label for r in rows]
    x = list(range(len(rows)))
    recall = [r.recall for r in rows]
    recall_yerr = _as_yerr([(r.recall_low, r.recall_high, r.recall) for r in rows])

    y = list(range(len(rows)))
    nns = [r.nns for r in rows]
    nns_xerr = _as_yerr(
        [(r.nns_low, r.nns_high, r.nns) for r in rows],
        horizontal=True,
    )

    width = max(9.0, 0.38 * len(rows) + 5.0)
    height = max(4.2, 0.22 * len(rows) + 3.0)
    fig, axes = plt.subplots(
        1,
        2,
        figsize=(width, height),
        gridspec_kw={"width_ratios": [max(2.2, len(rows) / 5), 1.35]},
    )
    ax_recall, ax_nns = axes

    bars = ax_recall.bar(x, recall, color=BLUE, width=0.72)
    if recall_yerr is not None:
        ax_recall.errorbar(
            x,
            recall,
            yerr=recall_yerr,
            fmt="none",
            ecolor="#111827",
            elinewidth=0.8,
            capsize=2,
        )
    for bar, value in zip(bars, recall):
        ax_recall.text(
            bar.get_x() + bar.get_width() / 2,
            min(1.02, value + 0.025),
            f"{value:.2f}",
            ha="center",
            va="bottom",
            fontsize=7,
        )
    ax_recall.set_ylim(0, 1.08)
    ax_recall.set_ylabel("Recall")
    ax_recall.set_xticks(x)
    ax_recall.set_xticklabels(labels, rotation=45, ha="right")
    ax_recall.yaxis.grid(True, color=LIGHT_GRID, linewidth=0.7)
    ax_recall.set_title(title)

    ax_nns.barh(y, nns, color=TEAL, alpha=0.82, height=0.34)
    ax_nns.scatter(nns, y, color=TEAL, s=32, zorder=3)
    if nns_xerr is not None:
        ax_nns.errorbar(
            nns,
            y,
            xerr=nns_xerr,
            fmt="none",
            ecolor="#111827",
            elinewidth=0.8,
            capsize=2,
            zorder=4,
        )
    for value, ypos in zip(nns, y):
        ax_nns.text(value + max(nns) * 0.025, ypos, f"{value:.2f}", va="center")
    ax_nns.set_yticks(y)
    ax_nns.set_yticklabels(labels)
    ax_nns.invert_yaxis()
    ax_nns.set_xlabel("NNS")
    ax_nns.set_title("Number Needed to Screen")
    ax_nns.xaxis.grid(True, color=LIGHT_GRID, linewidth=0.7)
    ax_nns.set_xlim(0, max(nns) * 1.22 if nns else 1)

    fig.tight_layout(w_pad=2.0)
    _save_figure_variants(fig, output)
    plt.close(fig)


def read_coding_rows(path: Path) -> list[CodingFigureRow]:
    """Read coding interval rows from markdown, CSV, TSV, or XLSX tables."""
    if path.suffix.lower() in {".md", ".markdown"}:
        df = _read_markdown_table(path)
    else:
        df = _read_table(path)
    rows: list[CodingFigureRow] = []
    last_project = ""
    for _, row in df.iterrows():
        project = _first_text(row, ["Project", "profile", "project", "Literature"])
        if project:
            last_project = project
        label = project or last_project
        parameter = _first_text(row, ["Parameter", "parameter", "topic"])
        if parameter and parameter.lower() not in label.lower():
            label = f"{label} {parameter}".strip()

        sr_text = _first_text(row, ["SR Reference (95% CI)", "sr_reference", "sr"])
        llm_text = _first_text(row, ["LLM Extraction (95% CI)", "llm_extraction", "llm"])
        sr, sr_low, sr_high, unit = _parse_estimate_ci(sr_text)
        llm, llm_low, llm_high, llm_unit = _parse_estimate_ci(llm_text)

        if math.isnan(sr):
            sr, sr_low, sr_high = _metric_with_ci(row, ["sr", "sr_estimate", "reference"])
        if math.isnan(llm):
            llm, llm_low, llm_high = _metric_with_ci(row, ["llm", "llm_estimate", "estimate"])
        unit = unit or llm_unit or _first_text(row, ["unit", "Unit"])
        if math.isnan(sr) or math.isnan(llm):
            continue
        rows.append(
            CodingFigureRow(
                label=label or f"row {len(rows) + 1}",
                group_label=_derive_coding_group(parameter or label),
                unit=unit,
                sr=sr,
                sr_low=sr_low,
                sr_high=sr_high,
                llm=llm,
                llm_low=llm_low,
                llm_high=llm_high,
            )
        )
    return rows


def plot_coding_intervals(
    rows: list[CodingFigureRow],
    output: Path,
    *,
    title: str = "Coding Estimates vs Source Review",
    x_label: str | None = None,
) -> None:
    """Plot horizontal SR and LLM estimate intervals for each literature."""
    if not rows:
        raise ValueError("No plottable coding rows found.")

    apply_publication_style()
    grouped = _group_coding_rows(rows)
    height = max(3.5, 0.36 * len(rows) + 1.4 * len(grouped))
    fig, axes = plt.subplots(
        len(grouped),
        1,
        figsize=(8.2, height),
        squeeze=False,
        gridspec_kw={"hspace": 0.55},
    )
    fig.suptitle(title, y=0.995)

    for ax_idx, (group_label, group_rows) in enumerate(grouped):
        ax = axes[ax_idx][0]
        y = list(range(len(group_rows)))
        for idx, row in enumerate(group_rows):
            if row.sr_low is not None and row.sr_high is not None:
                ax.hlines(idx + 0.12, row.sr_low, row.sr_high, color=GRAY, linewidth=2.0)
            ax.scatter(row.sr, idx + 0.12, color=GRAY, marker="s", s=24, label="SR reference" if ax_idx == 0 and idx == 0 else "")

            if row.llm_low is not None and row.llm_high is not None:
                ax.hlines(idx - 0.12, row.llm_low, row.llm_high, color=TEAL, linewidth=2.2)
            ax.scatter(row.llm, idx - 0.12, color=TEAL, marker="o", s=28, label="LLM estimate" if ax_idx == 0 and idx == 0 else "")

        ax.set_yticks(y)
        ax.set_yticklabels([r.label for r in group_rows])
        ax.invert_yaxis()
        ax.set_xlabel(x_label or group_label)
        ax.xaxis.grid(True, color=LIGHT_GRID, linewidth=0.7)
        if len(grouped) > 1:
            ax.set_title(group_label, loc="left", fontsize=9)
        if ax_idx == 0:
            ax.legend(frameon=False, loc="lower right")

    fig.subplots_adjust(top=0.92, left=0.22, right=0.98, hspace=0.72)
    _save_figure_variants(fig, output)
    plt.close(fig)


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".tsv", ".txt"}:
        return pd.read_csv(path, sep="\t")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def _read_markdown_table(path: Path) -> pd.DataFrame:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            if re.fullmatch(r"\|[\s:\-|\u2014]+\|", stripped):
                continue
            current.append(stripped)
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    if not blocks:
        return pd.DataFrame()
    lines = blocks[0]
    if not lines:
        return pd.DataFrame()
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    data = []
    for line in lines[1:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == len(headers):
            data.append(cells)
    return pd.DataFrame(data, columns=headers)


def _first_text(row: pd.Series, candidates: Iterable[str]) -> str:
    for key in candidates:
        if key in row and not pd.isna(row[key]):
            text = str(row[key]).strip()
            if text:
                return _strip_markdown(text)
    return ""


def _metric_with_ci(
    row: pd.Series,
    candidates: Iterable[str],
    *,
    ratio: bool = False,
) -> tuple[float, float | None, float | None]:
    for key in candidates:
        if key in row and not pd.isna(row[key]):
            return _parse_metric_ci(str(row[key]), ratio=ratio)
    return math.nan, None, None


def _parse_metric_ci(text: str, *, ratio: bool = False) -> tuple[float, float | None, float | None]:
    text = _strip_markdown(str(text))
    if not text or text.lower() == "inf":
        return math.nan, None, None
    nums = _extract_numbers(text)
    if not nums:
        return math.nan, None, None
    scale = 0.01 if "%" in text and not ratio else 1.0
    value = nums[0] * scale
    if ratio and "%" in text and len(nums) > 1:
        # Some legacy NNS tables printed CI endpoints as percentages
        # (e.g. 402% for 4.02) while the point estimate stayed unscaled.
        low = nums[1] / 100
        high = nums[2] / 100 if len(nums) > 2 else None
    else:
        low = nums[1] * scale if len(nums) > 1 else None
        high = nums[2] * scale if len(nums) > 2 else None
    return value, low, high


def _parse_estimate_ci(text: str) -> tuple[float, float | None, float | None, str]:
    clean = _strip_markdown(str(text))
    if not clean or clean in {"-", "—"}:
        return math.nan, None, None, ""
    nums = _extract_numbers(clean)
    if not nums:
        return math.nan, None, None, ""
    value = nums[0]
    interval = _extract_interval(clean)
    low = interval[0] if interval else None
    high = interval[1] if interval else None
    return value, low, high, _detect_unit(clean)


def _strip_markdown(text: str) -> str:
    return (
        text.replace("**", "")
        .replace("✓", "")
        .replace("≈", "")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .strip()
    )


def _extract_numbers(text: str) -> list[float]:
    normalized = (
        text.replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    return [float(x) for x in re.findall(r"(?<![\d.])-?\d+(?:\.\d+)?", normalized)]


def _compact_literature_label(label: str) -> str:
    clean = _strip_markdown(label)
    match = re.match(r"^([A-Za-z'`-]+)\s+et\s+al\.\s+(\d{4})", clean)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    return clean


def _group_coding_rows(rows: list[CodingFigureRow]) -> list[tuple[str, list[CodingFigureRow]]]:
    groups: dict[str, list[CodingFigureRow]] = {}
    order: list[str] = []
    for row in rows:
        label = row.group_label
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(row)
    return [(label, groups[label]) for label in order]


def _as_yerr(
    triples: list[tuple[float | None, float | None, float]],
    *,
    horizontal: bool = False,
):
    lows: list[float] = []
    highs: list[float] = []
    any_ci = False
    for low, high, value in triples:
        if low is None or high is None or math.isnan(value):
            lows.append(0.0)
            highs.append(0.0)
            continue
        any_ci = True
        lows.append(max(0.0, value - low))
        highs.append(max(0.0, high - value))
    if not any_ci:
        return None
    return [lows, highs] if horizontal else [lows, highs]


def _infer_axis_label(rows: list[CodingFigureRow]) -> str:
    units = {r.unit for r in rows if r.unit}
    if len(units) == 1:
        unit = next(iter(units))
        return f"Estimate ({unit})" if unit else "Estimate"
    return "Estimate"


def _save_figure_variants(fig: plt.Figure, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    alternate = output.with_suffix(".pdf") if output.suffix.lower() != ".pdf" else output.with_suffix(".png")
    if alternate != output:
        fig.savefig(alternate)


def _derive_coding_group(parameter: str) -> str:
    clean = _strip_markdown(parameter)
    if not clean:
        return "Estimate"
    family = clean.split("(", 1)[0].strip()
    return family or clean


def _detect_unit(text: str) -> str:
    clean_lower = text.lower()
    if re.search(r"\d(?:\.\d+)?\s*d\b|\bday(?:s)?\b", clean_lower):
        return "days"
    if "%" in text:
        return "%"
    return ""


def _extract_interval(text: str) -> tuple[float, float] | None:
    normalized = _strip_markdown(text)
    for match in re.finditer(r"\(([^()]*)\)", normalized):
        body = match.group(1).strip()
        if "/" in body or "," in body:
            continue
        compact = body.lower().replace(" to ", "-")
        compact = compact.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
        interval_match = re.fullmatch(
            r"\s*(-?\d+(?:\.\d+)?)\s*(?:%|d|days?)?\s*-\s*(-?\d+(?:\.\d+)?)\s*(?:%|d|days?)?\s*",
            compact,
        )
        if interval_match:
            return float(interval_match.group(1)), float(interval_match.group(2))
    return None
