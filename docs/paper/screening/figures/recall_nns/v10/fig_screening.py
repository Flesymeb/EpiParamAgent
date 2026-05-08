#!/usr/bin/env python3
"""Screening figures for COVID-19 and Mpox (v10).

Generates four single panels, two disease-level composites, and one overall
COVID-19 + Mpox composite. The output directory is the directory containing
this script, so each copied version writes into its own vx folder.
"""

import csv
import argparse
import json
import math
import re
from pathlib import Path

import matplotlib as mpl
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle


# Paths
OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)


def find_repo_root(start):
    for path in (start, *start.parents):
        if (path / "dataset").exists() and (path / "evaluation").exists():
            return path
    raise RuntimeError(f"Could not locate repo root from {start}")


REPO = find_repo_root(OUT)
VERSION = OUT.name
EXPORT_FORMATS = ("svg", "pdf", "png")

MODEL_SOURCES = {
    "gemini_2_5_flash": {
        "display": "Gemini 2.5 Flash",
        "provider": "openrouter",
        "model": "google/gemini-2.5-flash",
        "exp": "model_5d_screening_multi_adaptive_highc_llmtier_20260507_openrouter_google-gemini-2-5-flash",
    },
    "gpt_4_1": {
        "display": "GPT-4.1",
        "provider": "openrouter",
        "model": "openai/gpt-4.1",
        "exp": "model_5d_screening_multi_adaptive_highc_llmtier_20260507_openrouter_openai-gpt-4-1",
    },
    "lab_deepseek_3_2": {
        "display": "Lab DeepSeek 3.2",
        "provider": "lab",
        "model": "deepseek-3.2",
        "exp": "model_5d_screening_multi_adaptive_highc_llmtier_20260507_lab_deepseek-3-2",
    },
    "lab2_deepseek_v3_huawei_910b": {
        "display": "Lab2 DeepSeek V3 Huawei",
        "provider": "lab2",
        "model": "deepseek-v3-huawei-910b",
        "exp": "model_5d_screening_multi_adaptive_highc_llmtier_20260507_lab2_deepseek-v3-huawei-910b",
    },
    "boyue_deepseek_v4_pro": {
        "display": "Boyue DeepSeek V4 Pro",
        "provider": "boyue",
        "model": "deepseek-v4-pro",
        "exp": "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_deepseek-v4-pro",
    },
    "boyue_qwen3_6_plus": {
        "display": "Boyue Qwen3.6 Plus",
        "provider": "boyue",
        "model": "qwen3.6-plus",
        "exp": "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus",
    },
}
DEFAULT_MODEL_SOURCE = "boyue_qwen3_6_plus"
MODEL_CACHE_JSON = REPO / "evaluation/results/recall_nns_model_sources.json"
MODEL_CACHE_CSV = REPO / "evaluation/results/recall_nns_model_sources.csv"


# Publication palette
FILL_SI = "#6689AD"   # muted steel blue
EDGE_SI = "#3D668C"
FILL_RN = "#B9828A"   # dusty rose
EDGE_RN = "#7C4F58"
FILL_FAT = "#8E78B0"  # muted lavender
EDGE_FAT = "#5F4D84"
GREY = "#8A8A8A"
ORANGE = "#B87522"
DARK = "#2F2F2F"
BG = "#FFFFFF"
BAND_COLORS = ["#F3F7FB", "#FAF3F5", "#F7F4FA"]
SHOW_GROUP_BANDS = False
NNS_BASE_X = 1.0
NNS_LOG_THRESHOLD = 90.0
NNS_REFERENCE_FILL = "#D3D3D3"
NNS_REFERENCE_TEXT = "#6F6F6F"
NNS_SUBPLOT_HSPACE = 0.56
CI_Z = 1.96
CI_LEGEND_LABEL = "95% CI"

# Shared typography scale. Keep these synchronized across all panels.
TOPIC_FS = 12.5
NNS_TOPIC_FS = 10.6
TOPIC_LEGEND_FS = 12.8
AXIS_LABEL_FS = 12.5
RECALL_AXIS_LABEL_FS = 15.0
TICK_FS = 9.6
RECALL_TICK_FS = 11.0
AUTHOR_TICK_FS = 8.6
VALUE_FS = 10.4
SUBTOTAL_VALUE_FS = 10.4
REFERENCE_FS = 11.0
REFERENCE_TITLE_FS = 10.8
RATIO_FS = 8.5
PANEL_LABEL_FS = 12.5
DISEASE_TITLE_FS = 13.5
PANEL_TITLE_FS = 12.5
TEXT_WEIGHT = "semibold"

RECALL_PANEL_TITLE = "Recall of review-included papers"
NNS_PANEL_TITLE = "NNS after LLM screening"

TOPIC_SPECS = {
    "Serial Interval": {"fill": FILL_SI, "edge": EDGE_SI},
    "Reproduction Number": {"fill": FILL_RN, "edge": EDGE_RN},
    "Fatality": {"fill": FILL_FAT, "edge": EDGE_FAT},
}
NNS_TOPIC_LABELS = {
    "Serial Interval": "Serial\nInterval",
    "Reproduction Number": "Reproduction\nNumber",
    "Fatality": "Fatality",
}
NNS_GROUP_LABEL_X = -0.325
RECALL_SINGLETON_GROUP_EXTRA = 1.45
SHOW_NNS_GROUP_LABELS = False

COVID_AUTHOR_MAP = {
    4: "Lim et al., 2021",
    5: "Ioannidis et al., 2021",
    6: "Alimohamadi et al., 2021",
    7: "Dhungel et al., 2022",
    8: "Ahammed et al., 2021",
    10: "Madewell et al., 2023",
    11: "Xu et al., 2023",
    12: "Alene et al., 2021",
    13: "Ali et al., 2022",
    14: "Rai et al., 2021",
    15: "Billah et al., 2020",
    16: "Yu et al., 2021",
    17: "Alimohamadi et al., 2020",
}

MPOX_AUTHOR_MAP = {
    10: "Wu et al., 2025",
    11: "Diaz Brochero et al., 2025",
    5: "Wang et al., 2022",
    6: "Ponce et al., 2024",
    9: "Okoli et al., 2024",
    12: "Sanchez Clemente et al., 2024",
    4: "Cadmus et al., 2024",
    7: "Vasudevan et al., 2025",
    8: "Sharif et al., 2023",
}

DISEASES = {
    "covid19": {
        "title": "COVID-19",
        "dataset": REPO / "dataset/covid19/screening",
        "eval": REPO / "evaluation/screening/covid19",
        "gt_source": "ground_truth",
        "pool_source": "raw_csv",
        "author_map": COVID_AUTHOR_MAP,
        "topic_groups": [
            ("Serial Interval", [10, 11, 12, 13, 14]),
            ("Reproduction Number", [7, 8, 15, 16, 17]),
            ("Fatality", [4, 5, 6]),
        ],
    },
    "mpox": {
        "title": "Mpox",
        "dataset": REPO / "dataset/mpox/screening",
        "eval": REPO / "evaluation/screening/mpox",
        "gt_source": "ground_truth",
        "pool_source": "raw_csv",
        "author_map": MPOX_AUTHOR_MAP,
        "topic_groups": [
            ("Serial Interval", [10, 11, 5, 6]),
            ("Reproduction Number", [9]),
            ("Fatality", [12, 4, 7, 8]),
        ],
        "hide_subtotal_topics": ["Reproduction Number"],
    },
}


# Style
mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
    "font.size": 8.5,
    "axes.labelsize": 9,
    "axes.linewidth": 0.6,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
    "legend.frameon": False,
    "figure.facecolor": "white",
    "axes.facecolor": BG,
})

fonts = [f.name for f in fm.fontManager.ttflist if "Arial" in f.name]
print(f"  Arial fonts: {sorted(set(fonts))}")


# Data helpers
def topic_dir(topic_name):
    return topic_name.lower().replace(" ", "_")


def read_csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def count_csv_rows(path):
    if not path.exists():
        return 0
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def date_tuple(value):
    value = str(value or "").strip().replace("-", "/")
    if not value:
        return None
    try:
        parts = [int(part) for part in value.split("/")[:3]]
    except ValueError:
        return None
    if len(parts) == 1:
        return parts[0], 1, 1
    if len(parts) == 2:
        return parts[0], parts[1], 1
    return parts[0], parts[1], parts[2]


def load_project_date_bounds(project_dir):
    project = load_project_metadata(project_dir)
    return date_tuple(project.get("query_date_from")), date_tuple(project.get("query_date_to"))


def load_project_metadata(project_dir):
    project_file = project_dir / "project.json"
    if not project_file.exists():
        return {}
    with open(project_file, "r", encoding="utf-8") as f:
        return json.load(f)


def int_or_none(value):
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def load_raw_pool_count(project_dir, date_filter=False):
    raw_file = project_dir / "raw.csv"
    if not raw_file.exists():
        return 0
    raw_rows = read_csv_rows(raw_file)
    if date_filter:
        raw_rows = filter_rows_by_project_date(raw_rows, project_dir)
    return len(raw_rows)


def filter_rows_by_project_date(rows, project_dir):
    start, end = load_project_date_bounds(project_dir)
    if start is None and end is None:
        return rows
    filtered = []
    for row in rows:
        row_date = date_tuple(row.get("Create Date"))
        if row_date is None:
            filtered.append(row)
            continue
        if start is not None and row_date < start:
            continue
        if end is not None and row_date > end:
            continue
        filtered.append(row)
    return filtered


def wilson_ci(p, n, z=1.96):
    if n == 0:
        return 0, 0
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - m), min(1, c + m)


def load_gt_pmids(path):
    pmids = set()
    if not path.exists():
        return pmids
    for row in read_csv_rows(path):
        for col in ("PMID", "gt_pmid"):
            value = (row.get(col) or "").strip()
            if value.isdigit():
                excl = (row.get("exclude_flag") or "").strip().lower()
                if excl not in ("review_low_evidence", "review", "low_evidence"):
                    pmids.add(value)
                    break
    return pmids


def has_gt_marker(row):
    value = (row.get("is_ground_truth") or "").strip().lower()
    return bool(value) and value not in ("0", "false", "no", "n")


def is_included(row):
    return row.get("llm_suggest") in ("strong_candidate", "possible_candidate")


def is_valid(row):
    return row.get("llm_suggest") != "error"


def nns_ci_from_precision(tp, inc_n, z=CI_Z):
    if tp <= 0 or inc_n <= 0:
        return float("inf"), float("inf")
    precision = tp / inc_n
    plo, phi = wilson_ci(precision, inc_n, z=z)
    lo = 1 / phi if phi > 0 else float("inf")
    hi = 1 / plo if plo > 0 else float("inf")
    return lo, hi


def summary_topic_name(value):
    text = str(value or "").strip()
    lookup = {
        "serial_interval": "Serial Interval",
        "reproduction_number": "Reproduction Number",
        "fatality": "Fatality",
    }
    return lookup.get(text, text)


def parse_summary_project(value):
    text = str(value or "").strip()
    for prefix in ("MP", "P"):
        if text.upper().startswith(prefix):
            text = text[len(prefix):]
            break
    return int(text)


def normalize_source_key(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


MODEL_SOURCE_ALIASES = {
    normalize_source_key(key): key for key in MODEL_SOURCES
}
for key, spec in MODEL_SOURCES.items():
    MODEL_SOURCE_ALIASES[normalize_source_key(spec["display"])] = key
    MODEL_SOURCE_ALIASES[normalize_source_key(spec["model"])] = key


def resolve_model_source(source):
    key = MODEL_SOURCE_ALIASES.get(normalize_source_key(source))
    if key is None:
        raise KeyError(
            f"Unknown model source {source!r}. Available: {', '.join(sorted(MODEL_SOURCES))}"
        )
    return key


def load_disease_data(disease_key, model_source_key):
    cfg = DISEASES[disease_key]
    model = MODEL_SOURCES[model_source_key]
    rows = []

    for topic_name, project_nums in cfg["topic_groups"]:
        td = topic_dir(topic_name)
        projects = []

        for pn in project_nums:
            screened = (
                cfg["eval"]
                / td
                / f"p{pn}"
                / "experiments"
                / model["exp"]
                / f"project_{pn}_screened.csv"
            )
            if not screened.exists():
                print(f"  warning: missing {screened}")
                continue

            project_dir = cfg["dataset"] / td / f"p{pn}"
            papers = read_csv_rows(screened)
            if (td, pn) in cfg.get("date_filter_projects", set()):
                papers = filter_rows_by_project_date(papers, project_dir)
            valid = [row for row in papers if is_valid(row)]
            included = [row for row in valid if is_included(row)]

            if cfg["gt_source"] == "screened_marker":
                gt_n = sum(1 for row in papers if has_gt_marker(row))
                tp = sum(1 for row in included if has_gt_marker(row))
            else:
                gt_pmids = load_gt_pmids(cfg["dataset"] / td / f"p{pn}" / "ground_truth.csv")
                gt_n = len(gt_pmids)
                tp = sum(1 for row in included if (row.get("PMID") or "").strip() in gt_pmids)

            override = cfg.get("gt_count_overrides", {}).get((td, pn))
            if override is not None:
                gt_n = override
                tp = min(tp, gt_n)

            fp = len(included) - tp
            recall = tp / gt_n if gt_n else 0
            rlo, rhi = wilson_ci(recall, gt_n, z=CI_Z)
            nns = len(included) / tp if tp else float("inf")
            nns_lo, nns_hi = nns_ci_from_precision(tp, len(included), z=CI_Z)

            if cfg["pool_source"] == "screened_csv":
                pool_n = len(papers)
            elif cfg["pool_source"] == "search_count":
                project = load_project_metadata(project_dir)
                pool_n = int_or_none(project.get("search_count"))
                if pool_n is None:
                    pool_n = load_raw_pool_count(
                        project_dir,
                        date_filter=(td, pn) in cfg.get("date_filter_projects", set()),
                    )
            else:
                pool_n = load_raw_pool_count(
                    project_dir,
                    date_filter=(td, pn) in cfg.get("date_filter_projects", set()),
                )

            projects.append({
                "label": cfg["author_map"].get(pn, f"P{pn}"),
                "topic": topic_name,
                "project": pn,
                "gt": gt_n,
                "tp": tp,
                "fp": fp,
                "recall": recall,
                "r_lo": rlo,
                "r_hi": rhi,
                "nns": nns,
                "nns_lo": nns_lo,
                "nns_hi": nns_hi,
                "raw": pool_n,
                "source_experiment": model["exp"],
                "is_sub": False,
            })

        rows.extend(projects)

        gt_total = sum(row["gt"] for row in projects)
        tp_total = sum(row["tp"] for row in projects)
        fp_total = sum(row["fp"] for row in projects)
        inc_total = tp_total + fp_total
        pool_total = sum(row["raw"] for row in projects)

        recall = tp_total / gt_total if gt_total else 0
        rlo, rhi = wilson_ci(recall, gt_total, z=CI_Z)
        nns = inc_total / tp_total if tp_total else float("inf")
        nns_lo, nns_hi = nns_ci_from_precision(tp_total, inc_total, z=CI_Z)

        rows.append({
            "label": topic_name,
            "topic": topic_name,
            "project": None,
            "gt": gt_total,
            "tp": tp_total,
            "fp": fp_total,
            "recall": recall,
            "r_lo": rlo,
            "r_hi": rhi,
            "nns": nns,
            "nns_lo": nns_lo,
            "nns_hi": nns_hi,
            "raw": pool_total,
            "is_sub": True,
        })

    total_gt = sum(row["gt"] for row in rows if not row["is_sub"])
    total_pool = sum(row["raw"] for row in rows if not row["is_sub"])
    baseline_nns = total_pool / total_gt if total_gt else float("inf")

    return {
        "key": disease_key,
        "title": cfg["title"],
        "config": cfg,
        "model_source_key": model_source_key,
        "model_source": model,
        "rows": rows,
        "baseline_nns": baseline_nns,
    }


def jsonable_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (int, float, str)) or value is None or isinstance(value, bool):
        return value
    return str(value)


def export_model_cache():
    payload = {
        "generated_from": VERSION,
        "model_sources": {},
    }
    csv_rows = []

    for model_key, model in MODEL_SOURCES.items():
        source_entry = {
            "display": model["display"],
            "provider": model["provider"],
            "model": model["model"],
            "exp": model["exp"],
            "diseases": {},
        }
        for disease_key in DISEASES:
            bundle = load_disease_data(disease_key, model_key)
            source_entry["diseases"][disease_key] = {
                "title": bundle["title"],
                "baseline_nns": bundle["baseline_nns"],
                "rows": [
                    {k: jsonable_value(v) for k, v in row.items()}
                    for row in bundle["rows"]
                ],
            }
            for row in bundle["rows"]:
                csv_rows.append({
                    "model_source": model_key,
                    "model_display": model["display"],
                    "disease": disease_key,
                    "title": bundle["title"],
                    "row_type": "subtotal" if row["is_sub"] else "project",
                    "topic": row["topic"],
                    "project": row["project"] if row["project"] is not None else "",
                    "label": row["label"],
                    "gt": row["gt"],
                    "tp": row["tp"],
                    "fp": row["fp"],
                    "raw": row["raw"],
                    "recall": row["recall"],
                    "nns": jsonable_value(row["nns"]),
                    "nns_lo": jsonable_value(row["nns_lo"]),
                    "nns_hi": jsonable_value(row["nns_hi"]),
                    "source_experiment": row.get("source_experiment", ""),
                })

        payload["model_sources"][model_key] = source_entry

    MODEL_CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
    MODEL_CACHE_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    with MODEL_CACHE_CSV.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = [
            "model_source",
            "model_display",
            "disease",
            "title",
            "row_type",
            "topic",
            "project",
            "label",
            "gt",
            "tp",
            "fp",
            "raw",
            "recall",
            "nns",
            "nns_lo",
            "nns_hi",
            "source_experiment",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in csv_rows:
            writer.writerow(row)

    print(f"  model cache -> {MODEL_CACHE_JSON}")
    print(f"  model cache -> {MODEL_CACHE_CSV}")


# Layout helpers
def build_recall_layout(bundle):
    rows = bundle["rows"]
    x_labels = []
    x_pos = []
    bar_items = []
    group_bounds = []

    bar_gap = 0.28
    group_pad = 0.58
    between_gap = 0.55
    x = 0.0

    for topic_name, _ in bundle["config"]["topic_groups"]:
        projects = [row for row in rows if not row["is_sub"] and row["topic"] == topic_name]
        if not projects:
            continue
        show_subtotal = topic_name not in set(bundle["config"].get("hide_subtotal_topics", ()))
        singleton_without_average = (not show_subtotal and len(projects) == 1)
        singleton_extra = RECALL_SINGLETON_GROUP_EXTRA if singleton_without_average else 0.0

        group_start = x
        x += group_pad
        x += singleton_extra / 2

        if show_subtotal:
            subtotal = next(row for row in rows if row["is_sub"] and row["topic"] == topic_name)
            x_pos.append(x)
            x_labels.append("Average")
            bar_items.append((x, subtotal))
            x += 1.0 + bar_gap

        for project in projects:
            x_pos.append(x)
            x_labels.append(project["label"])
            bar_items.append((x, project))
            x += 1.0

        x -= 1.0
        x += group_pad
        x += singleton_extra / 2
        group_bounds.append((group_start, x, topic_name))
        x += between_gap

    return x_pos, x_labels, bar_items, group_bounds


def build_nns_layout(bundle):
    rows = bundle["rows"]
    y_labels = []
    y_pos = []
    bar_items = []
    group_bounds = []

    group_pad = 0.52
    bar_gap = 0.26
    between_gap = 0.48
    y = 0.0

    for topic_name, _ in bundle["config"]["topic_groups"]:
        projects = [row for row in rows if not row["is_sub"] and row["topic"] == topic_name]
        if not projects:
            continue
        show_subtotal = topic_name not in set(bundle["config"].get("hide_subtotal_topics", ()))

        group_top = y
        title_pad = 0.90 if (not show_subtotal and len(projects) == 1) else group_pad
        y += title_pad

        if show_subtotal:
            subtotal = next(row for row in rows if row["is_sub"] and row["topic"] == topic_name)
            y_pos.append(y)
            y_labels.append("Average")
            bar_items.append((y, subtotal))
            y += 1.0 + bar_gap

        for project in projects:
            y_pos.append(y)
            y_labels.append(project["label"])
            bar_items.append((y, project))
            y += 1.0

        y -= 1.0
        y += group_pad
        group_bounds.append((group_top, y, topic_name))
        y += between_gap

    return y_pos, y_labels, bar_items, group_bounds


# Drawing helpers
def export_figure(fig, fname):
    for fmt in EXPORT_FORMATS:
        fmt_dir = OUT / fmt
        fmt_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(fmt_dir / f"{fname}.{fmt}", dpi=600, bbox_inches="tight")
    print(f"  {fname} -> {OUT}/{{svg,pdf,png}}/")


def add_vertical_bar(ax, x_center, width, height, **kwargs):
    patch = Rectangle((x_center - width / 2, 0), width, height, **kwargs)
    ax.add_patch(patch)
    return patch


def add_horizontal_bar(ax, y_center, height, width, **kwargs):
    patch = Rectangle((0, y_center - height / 2), width, height, **kwargs)
    ax.add_patch(patch)
    return patch


def add_horizontal_range_bar(ax, y_center, height, x0, x1, **kwargs):
    patch = Rectangle((x0, y_center - height / 2), x1 - x0, height, **kwargs)
    ax.add_patch(patch)
    return patch


def add_wavy_vline(ax, x, y0, y1, amplitude, wavelength, **kwargs):
    y = np.linspace(y0, y1, 420)
    x_wave = x + amplitude * np.sin(2 * np.pi * (y - y0) / wavelength)
    ax.plot(x_wave, y, **kwargs)


def recall_label_y(value, ci_hi, ymax):
    if value >= 0.95:
        offset = ymax * 0.026
    elif value >= 0.90:
        offset = ymax * 0.038
    else:
        offset = ymax * 0.052
    return min(max(value, ci_hi) + offset, ymax * 1.075)


def log_label_x(value, xlim_right, factor=1.06):
    return min(max(value * factor, NNS_BASE_X * 1.08), xlim_right / 1.04)


def log_inside_label_x(value):
    return max(value / 1.08, NNS_BASE_X * 1.10)


def linear_label_x(value, xlim_right):
    return min(value + xlim_right * 0.012, xlim_right * 0.975)


def linear_inside_label_x(value, xlim_right):
    return max(value - xlim_right * 0.012, xlim_right * 0.012)


# Plotting
def set_panel_title(ax, title):
    ax.set_title(
        title,
        fontsize=PANEL_TITLE_FS,
        fontweight=TEXT_WEIGHT,
        color=DARK,
        pad=11,
    )


def topic_legend_handles():
    return [
        Patch(
            facecolor=TOPIC_SPECS[topic]["fill"],
            edgecolor=TOPIC_SPECS[topic]["edge"],
            linewidth=0.5,
            alpha=0.85,
            label=topic,
        )
        for topic in ("Serial Interval", "Reproduction Number", "Fatality")
    ]


def nns_legend_handles():
    return [
        Patch(
            facecolor=NNS_REFERENCE_FILL,
            edgecolor="none",
            linewidth=0,
            label="Original NNS",
        ),
        Line2D(
            [0, 1],
            [0, 0],
            color=DARK,
            linewidth=0.8,
            marker="|",
            markersize=8.5,
            markeredgewidth=1.0,
            label=CI_LEGEND_LABEL,
        ),
    ]


def screening_legend_handles():
    return topic_legend_handles() + nns_legend_handles()


def add_topic_legend(ax):
    handles = topic_legend_handles()
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.58),
        ncol=3,
        prop={"size": TOPIC_LEGEND_FS, "weight": TEXT_WEIGHT},
        handlelength=1.55,
        handletextpad=0.62,
        columnspacing=2.05,
        borderaxespad=0.0,
    )


def nns_items_for_topic(bundle, topic_name):
    rows = bundle["rows"]
    items = []
    show_subtotal = topic_name not in set(bundle["config"].get("hide_subtotal_topics", ()))
    if show_subtotal:
        subtotal = next(row for row in rows if row["is_sub"] and row["topic"] == topic_name)
        items.append(subtotal)
    items.extend(row for row in rows if not row["is_sub"] and row["topic"] == topic_name)
    return items


def nns_original_values(items):
    return [
        row["raw"] / row["gt"]
        for row in items
        if row["gt"] and not math.isinf(row["raw"] / row["gt"])
    ]


def nice_linear_nns_upper(value):
    if value <= 12:
        step = 2
    elif value <= 40:
        step = 5
    elif value <= 100:
        step = 10
    else:
        step = 20
    return max(step, math.ceil(value / step) * step)


def choose_nns_axis(items):
    original_vals = nns_original_values(items)
    xmax = max(original_vals) if original_vals else NNS_BASE_X
    use_log = xmax > NNS_LOG_THRESHOLD
    x_start = NNS_BASE_X if use_log else 0.0
    xlim_right = max(1, int(math.ceil(xmax)))
    return use_log, x_start, xlim_right


def set_nns_xaxis(ax, use_log, xlim_right, show_xlabel):
    if use_log:
        ax.set_xscale("log", base=2)
        ax.set_xlim(NNS_BASE_X, xlim_right)
        max_power = int(math.floor(math.log2(xlim_right)))
        ticks = [2 ** i for i in range(0, max_power + 1)]
        if abs(ticks[-1] - xlim_right) > 1e-6:
            ticks.append(xlim_right)
        ax.xaxis.set_minor_locator(mpl.ticker.NullLocator())
        xlabel = "Number of papers needed to screen (NNS, log2 scale)"
    else:
        ax.set_xscale("linear")
        ax.set_xlim(0, xlim_right)
        ticks = np.linspace(0, xlim_right, 6)
        xlabel = "Number of papers needed to screen (NNS)"

    ax.set_xticks(ticks)
    ax.set_xticklabels([
        str(int(round(tick)))
        for tick in ticks
    ])
    if show_xlabel:
        ax.set_xlabel(
            xlabel,
            fontsize=AXIS_LABEL_FS,
            fontweight=TEXT_WEIGHT,
            color=DARK,
        )
    else:
        ax.set_xlabel("")


def draw_nns_group(ax, topic_name, items, show_xlabel):
    use_log, x_start, xlim_right = choose_nns_axis(items)
    y_pos = np.arange(len(items), dtype=float)
    y_labels = ["Average" if row["is_sub"] else row["label"] for row in items]
    bar_h = 0.52

    ax.set_facecolor(BG)
    ax.set_ylim(-0.55, len(items) - 0.45)
    ax.invert_yaxis()
    set_nns_xaxis(ax, use_log, xlim_right, show_xlabel=show_xlabel)
    ax.text(
        0.0,
        1.025,
        topic_name,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=NNS_TOPIC_FS,
        fontweight=TEXT_WEIGHT,
        color=TOPIC_SPECS[topic_name]["edge"],
        clip_on=False,
    )

    for yi, row in zip(y_pos, items):
        spec = TOPIC_SPECS[row["topic"]]
        fill = spec["fill"]
        edge = spec["edge"]
        height = bar_h + 0.14 if row["is_sub"] else bar_h
        value = row["nns"] if not math.isinf(row["nns"]) else xlim_right / 1.05
        original_nns = row["raw"] / row["gt"] if row["gt"] else None

        if original_nns:
            add_horizontal_range_bar(
                ax,
                yi,
                height,
                x_start,
                max(original_nns, x_start + 0.02),
                facecolor=NNS_REFERENCE_FILL,
                edgecolor="none",
                linewidth=0,
                alpha=0.98,
                zorder=2,
            )

        add_horizontal_range_bar(
            ax,
            yi,
            height,
            x_start,
            max(value, x_start + 0.02),
            facecolor=edge if row["is_sub"] else fill,
            edgecolor=DARK if row["is_sub"] else edge,
            linewidth=0.65 if row["is_sub"] else 0.35,
            alpha=0.94 if row["is_sub"] else 0.82,
            zorder=3,
        )

        lo = row.get("nns_lo")
        hi = row.get("nns_hi")
        if lo is not None and hi is not None and not math.isinf(value):
            display_lo = max(lo, x_start if use_log else 0.0)
            display_hi = min(hi, xlim_right)
            err_lo = max(0, value - display_lo)
            err_hi = max(0, display_hi - value)
            if err_lo + err_hi > 0:
                ax.errorbar(
                    value,
                    yi,
                    xerr=[[err_lo], [err_hi]],
                    fmt="none",
                    ecolor=DARK,
                    elinewidth=0.7,
                    capsize=2.5,
                    uplims=hi > xlim_right,
                    lolims=lo < (x_start if use_log else 0.0),
                    zorder=4,
                )

        label_x = (
            log_label_x(value, xlim_right, factor=1.08)
            if use_log
            else linear_label_x(value, xlim_right)
        )
        label = f"{value:.1f}  (N={row['raw']})" if row["is_sub"] else f"{value:.1f}"
        ax.text(
            label_x,
            yi + height * 0.50,
            label,
            va="center",
            fontsize=SUBTOTAL_VALUE_FS if row["is_sub"] else VALUE_FS,
            fontweight=TEXT_WEIGHT,
            color=edge,
            zorder=5,
        )

        if original_nns:
            reference_x = (
                log_inside_label_x(original_nns)
                if use_log
                else linear_inside_label_x(original_nns, xlim_right)
            )
            ax.text(
                reference_x,
                yi - height * 0.41,
                f"{original_nns:.0f}",
                va="center",
                ha="right",
                fontsize=REFERENCE_FS - 0.5 if row["is_sub"] else REFERENCE_FS - 1.3,
                fontweight=TEXT_WEIGHT,
                color=NNS_REFERENCE_TEXT,
                clip_on=False,
                zorder=5,
            )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(y_labels, fontsize=TICK_FS, color=DARK)
    ax.tick_params(colors=DARK, width=0.6)
    for label in ax.get_yticklabels():
        label.set_fontweight(TEXT_WEIGHT)
        label.set_fontsize(TICK_FS)
        label.set_color("#242424")
    for label in ax.get_xticklabels():
        label.set_fontweight("normal")
        label.set_fontsize(TICK_FS)

    ax.xaxis.grid(
        True,
        color="#DCDCDC",
        linewidth=0.3,
        linestyle="--",
        alpha=0.42,
        zorder=0,
    )
    ax.axhline(-0.55, color="#D8D8D8", linewidth=0.35, zorder=1)
    ax.axhline(len(items) - 0.45, color="#D8D8D8", linewidth=0.35, zorder=1)


def plot_recall(bundle, fname="fig_recall", ax=None, save=True, show_legend=True):
    x_pos, x_labels, bar_items, group_bounds = build_recall_layout(bundle)
    n_bars = len(x_pos)
    fig_w = max(8.0, n_bars * 0.58 + 2.5)
    fig_h = 5.0

    if ax is None:
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    else:
        fig = ax.figure

    ymax = 1.08
    bar_w = 0.48 if bundle["key"] == "mpox" else 0.58
    ax.set_facecolor(BG)
    ax.set_xlim(group_bounds[0][0] - 0.12, group_bounds[-1][1] + 0.12)
    ax.set_ylim(0, ymax * 1.02)

    if SHOW_GROUP_BANDS:
        for (b1, b2, _), color in zip(group_bounds, BAND_COLORS):
            ax.axvspan(b1, b2, facecolor=color, alpha=0.62, zorder=0)

    for xi, row in bar_items:
        spec = TOPIC_SPECS[row["topic"]]
        fill = spec["fill"]
        edge = spec["edge"]
        value = row["recall"]
        lo = row["r_lo"]
        hi = row["r_hi"]

        if row["is_sub"]:
            width = bar_w + 0.16
            add_vertical_bar(
                ax,
                xi,
                width,
                value,
                facecolor=edge,
                edgecolor=DARK,
                linewidth=0.65,
                alpha=0.94,
                zorder=3,
            )
            label = f"{value:.2f}"
            fs = SUBTOTAL_VALUE_FS
        else:
            add_vertical_bar(
                ax,
                xi,
                bar_w,
                value,
                facecolor=fill,
                edgecolor=edge,
                linewidth=0.35,
                alpha=0.80,
                zorder=3,
            )
            label = f"{value:.2f}"
            fs = VALUE_FS

        label_y = recall_label_y(value, hi, ymax)
        ax.text(
            xi,
            label_y,
            label,
            ha="center",
            va="bottom",
            fontsize=fs,
            fontweight=TEXT_WEIGHT,
            color=edge,
            linespacing=1.15,
            zorder=5,
        )

        err_lo = max(0, value - lo)
        err_hi = max(0, hi - value)
        if err_lo + err_hi > 0:
            ax.errorbar(
                xi,
                value,
                yerr=[[err_lo], [err_hi]],
                fmt="none",
                ecolor=DARK,
                elinewidth=0.8,
                capsize=2.5,
                zorder=4,
            )

    for b1, b2, _ in group_bounds:
        ax.axvline(b1, color="#D8D8D8", linewidth=0.35, zorder=1)
        ax.axvline(b2, color="#D8D8D8", linewidth=0.35, zorder=1)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(
        x_labels,
        rotation=32,
        ha="right",
        fontsize=AUTHOR_TICK_FS,
        color=DARK,
        rotation_mode="anchor",
    )
    for label in ax.get_xticklabels():
        label.set_fontweight(TEXT_WEIGHT)
        if label.get_text() == "Average":
            label.set_color("#1F1F1F")
    if show_legend:
        add_topic_legend(ax)
    ax.set_ylabel(
        "Recall",
        fontsize=RECALL_AXIS_LABEL_FS,
        fontweight=TEXT_WEIGHT,
        color=DARK,
        labelpad=4,
    )
    ax.set_yticks([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["0.0", "0.2", "0.4", "0.6", "0.8", "1.0"])
    ax.tick_params(colors=DARK, width=0.6)

    for label in ax.get_yticklabels():
        label.set_fontweight("normal")
        label.set_fontsize(RECALL_TICK_FS)
        label.set_color(DARK)

    ax.yaxis.grid(
        True,
        color="#DCDCDC",
        linewidth=0.3,
        linestyle="--",
        alpha=0.42,
        zorder=0,
    )

    if save:
        set_panel_title(ax, f"{bundle['title']}: {RECALL_PANEL_TITLE}")
        fig.subplots_adjust(left=0.085, right=0.985, top=0.90, bottom=0.42)
        export_figure(fig, fname)
        plt.close(fig)


def plot_nns(bundle, fname="fig_nns", ax=None, save=True, show_legend=True):
    groups = [
        (topic_name, nns_items_for_topic(bundle, topic_name))
        for topic_name, _ in bundle["config"]["topic_groups"]
    ]
    groups = [(topic_name, items) for topic_name, items in groups if items]
    n_bars = sum(len(items) for _, items in groups)
    fig_w = max(7.5, 0.55 * n_bars + 6.0)
    fig_h = max(5.8, n_bars * 0.37 + 2.95)

    if ax is None:
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    else:
        fig = ax.figure

    ax.set_facecolor(BG)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    spacer = 0.42
    subgs = ax.get_subplotspec().subgridspec(
        len(groups) + 1,
        1,
        height_ratios=[spacer] + [max(1.0, len(items)) for _, items in groups],
        hspace=NNS_SUBPLOT_HSPACE,
    )
    for idx, (topic_name, items) in enumerate(groups):
        gax = fig.add_subplot(subgs[idx + 1, 0])
        draw_nns_group(gax, topic_name, items, show_xlabel=(idx == len(groups) - 1))

    if show_legend:
        ax.legend(
            handles=nns_legend_handles(),
            loc="lower right",
            bbox_to_anchor=(0.995, 1.01),
            ncol=2,
            prop={"size": REFERENCE_TITLE_FS, "weight": TEXT_WEIGHT},
            handlelength=1.45,
            handletextpad=0.50,
            columnspacing=1.0,
            borderaxespad=0.0,
        )

    if save:
        set_panel_title(ax, f"{bundle['title']}: {NNS_PANEL_TITLE}")
        fig.subplots_adjust(left=0.19, right=0.985, top=0.92, bottom=0.13)
        export_figure(fig, fname)
        plt.close(fig)


def plot_disease_combined(bundle, fname):
    fig = plt.figure(figsize=(11.6, 10.15))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.0, 1.58], hspace=1.02)
    ax_recall = fig.add_subplot(gs[0])
    ax_nns = fig.add_subplot(gs[1])

    plot_recall(bundle, ax=ax_recall, save=False, show_legend=False)
    plot_nns(bundle, ax=ax_nns, save=False, show_legend=False)
    set_panel_title(ax_recall, f"{bundle['title']}: {RECALL_PANEL_TITLE}")
    set_panel_title(ax_nns, f"{bundle['title']}: {NNS_PANEL_TITLE}")

    ax_recall.text(
        -0.052,
        1.11,
        "A",
        transform=ax_recall.transAxes,
        ha="left",
        va="top",
        fontsize=PANEL_LABEL_FS,
        fontweight=TEXT_WEIGHT,
        color=DARK,
    )
    ax_nns.text(
        -0.052,
        1.10,
        "B",
        transform=ax_nns.transAxes,
        ha="left",
        va="top",
        fontsize=PANEL_LABEL_FS,
        fontweight=TEXT_WEIGHT,
        color=DARK,
    )
    fig.legend(
        handles=screening_legend_handles(),
        loc="upper center",
        bbox_to_anchor=(0.5, 0.56),
        ncol=5,
        prop={"size": TOPIC_LEGEND_FS, "weight": TEXT_WEIGHT},
        handlelength=1.45,
        handletextpad=0.52,
        columnspacing=1.15,
        borderaxespad=0.0,
    )
    fig.subplots_adjust(left=0.18, right=0.94, top=0.94, bottom=0.08)
    export_figure(fig, fname)
    plt.close(fig)


def plot_overall_combined(covid, mpox, fname="fig7_screening_overall_combined"):
    fig = plt.figure(figsize=(19.0, 10.45))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.58], hspace=0.70, wspace=0.34)

    ax_c_recall = fig.add_subplot(gs[0, 0])
    ax_m_recall = fig.add_subplot(gs[0, 1])
    ax_c_nns = fig.add_subplot(gs[1, 0])
    ax_m_nns = fig.add_subplot(gs[1, 1])

    plot_recall(covid, ax=ax_c_recall, save=False, show_legend=False)
    plot_recall(mpox, ax=ax_m_recall, save=False, show_legend=False)
    plot_nns(covid, ax=ax_c_nns, save=False, show_legend=False)
    plot_nns(mpox, ax=ax_m_nns, save=False, show_legend=False)
    set_panel_title(ax_c_recall, f"{covid['title']}: {RECALL_PANEL_TITLE}")
    set_panel_title(ax_m_recall, f"{mpox['title']}: {RECALL_PANEL_TITLE}")
    set_panel_title(ax_c_nns, f"{covid['title']}: {NNS_PANEL_TITLE}")
    set_panel_title(ax_m_nns, f"{mpox['title']}: {NNS_PANEL_TITLE}")

    for ax, label in [
        (ax_c_recall, "A"),
        (ax_m_recall, "B"),
        (ax_c_nns, "C"),
        (ax_m_nns, "D"),
    ]:
        ax.text(
            -0.065,
            1.11 if ax in (ax_c_recall, ax_m_recall) else 1.10,
            label,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=PANEL_LABEL_FS,
            fontweight=TEXT_WEIGHT,
            color=DARK,
        )

    fig.legend(
        handles=screening_legend_handles(),
        loc="upper center",
        bbox_to_anchor=(0.5, 0.57),
        ncol=5,
        prop={"size": TOPIC_LEGEND_FS, "weight": TEXT_WEIGHT},
        handlelength=1.45,
        handletextpad=0.52,
        columnspacing=1.25,
        borderaxespad=0.0,
    )
    fig.subplots_adjust(left=0.11, right=0.985, top=0.925, bottom=0.08)
    export_figure(fig, fname)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-source",
        default=DEFAULT_MODEL_SOURCE,
        help=(
            "Model source key or display name. "
            f"Choices: {', '.join(sorted(MODEL_SOURCES))}"
        ),
    )
    parser.add_argument(
        "--write-model-cache",
        action="store_true",
        help="Write a JSON/CSV cache for all six model sources before plotting.",
    )
    parser.add_argument(
        "--list-model-sources",
        action="store_true",
        help="Print available model sources and exit.",
    )
    args = parser.parse_args()

    if args.list_model_sources:
        for key, spec in MODEL_SOURCES.items():
            print(f"{key}: {spec['display']} -> {spec['exp']}")
        return

    model_source_key = resolve_model_source(args.model_source)
    spec = MODEL_SOURCES[model_source_key]
    print(f"Using model source: {model_source_key} ({spec['display']})")

    if args.write_model_cache:
        export_model_cache()

    covid = load_disease_data("covid19", model_source_key)
    mpox = load_disease_data("mpox", model_source_key)

    outputs = [
        (plot_recall, covid, "fig1_covid19_recall"),
        (plot_nns, covid, "fig2_covid19_nns"),
        (plot_recall, mpox, "fig3_mpox_recall"),
        (plot_nns, mpox, "fig4_mpox_nns"),
    ]
    for func, bundle, fname in outputs:
        func(bundle, fname)

    plot_disease_combined(covid, "fig5_covid19_combined")
    plot_disease_combined(mpox, "fig6_mpox_combined")
    plot_overall_combined(covid, mpox, "fig7_screening_overall_combined")
    print(f"Done - {VERSION}")


if __name__ == "__main__":
    main()
