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
    "openrouter_qwen3_6_plus_b1c8_j2_repeat_mean_range": {
        "display": "OpenRouter Qwen3.6 Plus, three-run mean",
        "provider": "openrouter",
        "model": "qwen/qwen3.6-plus",
        "exp": "qwen36_plus_openrouter_direct_single_b1c8_j2_20260510_repeat_mean_range",
        "profile_metrics": "evaluation/results/qwen36_plus_openrouter_direct_single_b1c8_j2_20260510_repeat_metrics.csv",
        "repeat_range": True,
    },
    "openrouter_qwen3_6_plus_mpox_prompt_recall_v5_hybrid": {
        "display": "OpenRouter Qwen3.6 Plus, mpox recall-tuned hybrid",
        "provider": "openrouter",
        "model": "qwen/qwen3.6-plus",
        "exp": "qwen36_plus_openrouter_mpox_prompt_recall_v5_hybrid_20260510",
        "profile_metrics": "evaluation/results/qwen36_plus_openrouter_mpox_prompt_recall_v5_hybrid_repeat_metrics_20260510.csv",
        "repeat_range": True,
    },
    "calibrated_qwen3_6_plus_v1": {
        "display": "Calibrated Qwen3.6 Plus v1",
        "provider": "boyue",
        "model": "qwen3.6-plus",
        "exp": "model_5d_screening_calibrated_boyue_qwen3-6-plus_v1_20260509",
        "profile_metrics": "evaluation/results/model_5d_screening_calibrated_boyue_qwen3-6-plus_v1_20260509_profile_metrics.csv",
    },
    "calibrated_qwen3_6_plus_v1_recall": {
        "display": "Calibrated Qwen3.6 Plus v1-R",
        "provider": "boyue",
        "model": "qwen3.6-plus",
        "exp": "model_5d_screening_calibrated_boyue_qwen3-6-plus_v1_recall_20260509",
        "profile_metrics": "evaluation/results/model_5d_screening_calibrated_boyue_qwen3-6-plus_v1_recall_20260509_profile_metrics.csv",
    },
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
DEFAULT_MODEL_SOURCE = "openrouter_qwen3_6_plus_mpox_prompt_recall_v5_hybrid"
MODEL_CACHE_JSON = REPO / "evaluation/results/recall_nns_model_sources.json"
MODEL_CACHE_CSV = REPO / "evaluation/results/recall_nns_model_sources.csv"


# Publication palette. Keep the three parameter colours close in value so the
# figure reads as a paired screening result rather than a categorical dashboard.
FILL_SI = "#8FA7B8"   # low-saturation blue grey
EDGE_SI = "#5F788A"
FILL_RN = "#BCA3A4"   # low-saturation rose grey
EDGE_RN = "#866B70"
FILL_FAT = "#ADA3BD"  # low-saturation lavender grey
EDGE_FAT = "#786E8A"
GREY = "#8A8A8A"
ORANGE = "#B87522"
DARK = "#2F2F2F"
BG = "#FFFFFF"
BAND_COLORS = ["#F3F7FB", "#FAF3F5", "#F7F4FA"]
SHOW_GROUP_BANDS = False
NNS_BASE_X = 1.0
NNS_LOG_THRESHOLD = 90.0
NNS_REFERENCE_FILL = "#E2E2E2"
NNS_REFERENCE_TEXT = "#777777"
NNS_SUBPLOT_HSPACE = 0.46
NNS_ROW_STEP = 1.18
CI_Z = 1.96
CI_LEGEND_LABEL = "95% CI"

# Shared typography scale. Keep these synchronized across all panels.
TOPIC_FS = 13.6
NNS_TOPIC_FS = 13.1
TOPIC_LEGEND_FS = 14.4
AXIS_LABEL_FS = 13.8
RECALL_AXIS_LABEL_FS = 17.0
TICK_FS = 11.0
RECALL_TICK_FS = 12.4
AUTHOR_TICK_FS = 11.8
VALUE_FS = 11.8
SUBTOTAL_VALUE_FS = 11.8
RECALL_VALUE_FS = 10.2
RECALL_SUBTOTAL_VALUE_FS = 10.4
REFERENCE_FS = 12.2
REFERENCE_TITLE_FS = 12.4
RATIO_FS = 8.5
PANEL_LABEL_FS = 13.5
DISEASE_TITLE_FS = 13.5
PANEL_TITLE_FS = 17.0
TEXT_WEIGHT = "semibold"
NNS_TITLE_PAD = 9
RECALL_TITLE_PAD = 14

RECALL_PANEL_TITLE = "Recall of included papers"
NNS_PANEL_TITLE = "NNS with LLM-assisted screening"

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
SHOW_NNS_TOPIC_LABELS = False

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


def parse_semicolon_floats(value):
    text = str(value or "").strip()
    if not text:
        return []
    return [float(item) for item in text.split(";") if item.strip()]


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
    profile_metrics = {}

    if model.get("profile_metrics"):
        profile_path = REPO / model["profile_metrics"]
        for row in read_csv_rows(profile_path):
            if row.get("experiment") != model["exp"] or row.get("disease") != disease_key:
                continue
            profile_metrics[(summary_topic_name(row.get("topic")), int(row["project"]))] = row

    for topic_name, project_nums in cfg["topic_groups"]:
        td = topic_dir(topic_name)
        projects = []

        for pn in project_nums:
            project_dir = cfg["dataset"] / td / f"p{pn}"
            metric_row = profile_metrics.get((topic_name, pn))
            recall_override = None
            recall_range = None
            nns_override = None
            nns_range = None
            tp_runs = []
            fp_runs = []

            if metric_row is not None:
                gt_n = int(float(metric_row["gt"]))
                pool_n = int(float(metric_row["total"]))
                if metric_row.get("recall_mean"):
                    tp = float(metric_row["tp_mean"])
                    fp = float(metric_row["fp_mean"])
                    recall_override = float(metric_row["recall_mean"])
                    recall_range = (
                        float(metric_row["recall_min"]),
                        float(metric_row["recall_max"]),
                    )
                    nns_override = float(metric_row["nns_mean"])
                    nns_range = (
                        float(metric_row["nns_min"]),
                        float(metric_row["nns_max"]),
                    )
                    tp_runs = parse_semicolon_floats(metric_row.get("tp_runs"))
                    fp_runs = parse_semicolon_floats(metric_row.get("fp_runs"))
                else:
                    tp = int(metric_row["tp"])
                    fp = int(metric_row["fp"])
            else:
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

            recall = recall_override if recall_override is not None else (tp / gt_n if gt_n else 0)
            rlo, rhi = wilson_ci(recall, gt_n, z=CI_Z)
            included_n = tp + fp
            nns = nns_override if nns_override is not None else (included_n / tp if tp else float("inf"))
            nns_lo, nns_hi = nns_ci_from_precision(tp, included_n, z=CI_Z)

            project_row = {
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
            }
            if tp_runs and fp_runs:
                project_row["tp_runs"] = tp_runs
                project_row["fp_runs"] = fp_runs
            projects.append(project_row)

        rows.extend(projects)

        gt_total = sum(row["gt"] for row in projects)
        tp_total = sum(row["tp"] for row in projects)
        fp_total = sum(row["fp"] for row in projects)
        inc_total = tp_total + fp_total
        pool_total = sum(row["raw"] for row in projects)

        run_count = 0
        if projects and all(row.get("tp_runs") and row.get("fp_runs") for row in projects):
            run_count = len(projects[0]["tp_runs"])
        if run_count and all(len(row["tp_runs"]) == run_count and len(row["fp_runs"]) == run_count for row in projects):
            subtotal_tp_runs = [sum(row["tp_runs"][idx] for row in projects) for idx in range(run_count)]
            subtotal_fp_runs = [sum(row["fp_runs"][idx] for row in projects) for idx in range(run_count)]
            recall_runs = [tp_run / gt_total if gt_total else 0 for tp_run in subtotal_tp_runs]
            nns_runs = [
                (tp_run + fp_run) / tp_run if tp_run else float("inf")
                for tp_run, fp_run in zip(subtotal_tp_runs, subtotal_fp_runs)
            ]
            recall = sum(recall_runs) / len(recall_runs) if recall_runs else 0
            rlo, rhi = wilson_ci(recall, gt_total, z=CI_Z)
            nns = sum(nns_runs) / len(nns_runs) if nns_runs else float("inf")
            nns_lo, nns_hi = nns_ci_from_precision(tp_total, inc_total, z=CI_Z)
        else:
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
            "project_count": len(projects),
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
                    "project_count": row.get("project_count", ""),
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
            "project_count",
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


def reference_label_x(original_nns, llm_label_x, xlim_right, use_log):
    """Place the original-NNS label just to the right of the grey bar."""
    if use_log:
        x = original_nns * 1.035
        if x < llm_label_x * 1.45:
            x = llm_label_x * 1.45
    else:
        x = original_nns + xlim_right * 0.012
        if x < llm_label_x + xlim_right * 0.075:
            x = llm_label_x + xlim_right * 0.075
    return x


def format_count(value):
    return f"{int(value):,}"


# Plotting
def set_panel_title(ax, title, pad=11):
    ax.set_title(
        title,
        fontsize=PANEL_TITLE_FS,
        fontweight="medium",
        color=DARK,
        pad=pad,
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
    measured_vals = [
        row["nns"]
        for row in items
        if row.get("nns") is not None and not math.isinf(row["nns"])
    ]
    ci_vals = [
        row["nns_hi"]
        for row in items
        if row.get("nns_hi") is not None and not math.isinf(row["nns_hi"])
    ]
    xmax = max(original_vals) if original_vals else max(measured_vals + ci_vals + [NNS_BASE_X])
    use_log = xmax > NNS_LOG_THRESHOLD
    x_start = NNS_BASE_X if use_log else 0.0
    if use_log:
        xlim_right = max(1, int(math.ceil(xmax)))
    else:
        xlim_right = nice_linear_nns_upper(xmax)
    return use_log, x_start, xlim_right


def set_nns_xaxis(ax, use_log, xlim_right, show_xlabel):
    if use_log:
        ax.set_xscale("log", base=2)
        ax.set_xlim(NNS_BASE_X, xlim_right)
        max_power = int(math.floor(math.log2(xlim_right)))
        ticks = [2 ** i for i in range(0, max_power + 1)]
        ax.xaxis.set_minor_locator(mpl.ticker.NullLocator())
        xlabel = "Papers needed to screen per included paper (NNS, log2 scale)"
    else:
        ax.set_xscale("linear")
        ax.set_xlim(0, xlim_right)
        ticks = np.linspace(0, xlim_right, 6)
        xlabel = "Papers needed to screen per included paper (NNS)"

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


def draw_nns_group(ax, topic_name, items, show_xlabel, axis_config=None):
    use_log, x_start, xlim_right = axis_config or choose_nns_axis(items)
    y_pos = np.arange(len(items), dtype=float) * NNS_ROW_STEP
    y_labels = ["Average" if row["is_sub"] else row["label"] for row in items]
    bar_h = 0.52

    ax.set_facecolor(BG)
    ax.set_ylim(-0.58, y_pos[-1] + 0.58)
    ax.invert_yaxis()
    set_nns_xaxis(ax, use_log, xlim_right, show_xlabel=show_xlabel)
    if SHOW_NNS_TOPIC_LABELS:
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
                alpha=0.78,
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
            ci_cap = original_nns if original_nns else xlim_right
            display_hi = min(hi, ci_cap, xlim_right)
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
                    uplims=False,
                    lolims=lo < (x_start if use_log else 0.0),
                    zorder=4,
                )

        label_x = (
            log_label_x(value, xlim_right, factor=1.08)
            if use_log
            else linear_label_x(value, xlim_right)
        )
        label = f"{value:.1f}"
        ax.text(
            label_x,
            yi + height * 0.60,
            label,
            va="center",
            fontsize=SUBTOTAL_VALUE_FS if row["is_sub"] else VALUE_FS,
            fontweight=TEXT_WEIGHT,
            color=edge,
            zorder=5,
        )

        if original_nns:
            reference_x = reference_label_x(original_nns, label_x, xlim_right, use_log)
            reference_label = f"{original_nns:.0f}"
            if row["is_sub"]:
                reference_label = f"{reference_label}  (N={format_count(row['raw'])})"
            ax.text(
                reference_x,
                yi,
                reference_label,
                va="center",
                ha="left",
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
        label.set_fontweight(TEXT_WEIGHT if label.get_text() == "Average" else "normal")
        label.set_fontsize(TICK_FS)
        label.set_color("#242424")
    for label in ax.get_xticklabels():
        label.set_fontweight("normal")
        label.set_fontsize(TICK_FS)

    ax.xaxis.grid(True, color="#E6E6E6", linewidth=0.35, linestyle="-", alpha=0.30, zorder=0)
    ax.axhline(-0.55, color="#D8D8D8", linewidth=0.35, zorder=1)
    ax.axhline(len(items) - 0.45, color="#D8D8D8", linewidth=0.35, zorder=1)


def plot_recall(bundle, fname="fig_recall", ax=None, save=True, show_legend=True):
    x_pos, x_labels, bar_items, group_bounds = build_recall_layout(bundle)
    n_bars = len(x_pos)
    fig_w = max(8.0, n_bars * 0.58 + 2.5)
    fig_h = 2.75

    if ax is None:
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    else:
        fig = ax.figure

    ymin = 0.00
    ymax = 1.02
    bar_w = 0.48 if bundle["key"] == "mpox" else 0.56
    ax.set_facecolor(BG)
    ax.set_xlim(group_bounds[0][0] - 0.12, group_bounds[-1][1] + 0.12)
    ax.set_ylim(ymin, ymax)

    for b1, b2, _topic_name in group_bounds:
        ax.axvline(b1, color="#DCDCDC", linewidth=0.35, zorder=1)
        ax.axvline(b2, color="#DCDCDC", linewidth=0.35, zorder=1)

    for xi, row in bar_items:
        spec = TOPIC_SPECS[row["topic"]]
        fill = spec["fill"]
        edge = spec["edge"]
        value = row["recall"]
        lo = max(row["r_lo"], ymin)
        hi = min(row["r_hi"], ymax)
        err_lo = max(0, value - lo)
        err_hi = max(0, hi - value)
        width = bar_w + 0.12 if row["is_sub"] else bar_w

        ax.bar(
            xi,
            max(value - ymin, 0),
            bottom=ymin,
            width=width,
            color=edge if row["is_sub"] else fill,
            edgecolor=DARK if row["is_sub"] else edge,
            linewidth=0.65 if row["is_sub"] else 0.35,
            alpha=0.94 if row["is_sub"] else 0.80,
            zorder=3,
        )

        if err_lo + err_hi > 0:
            ax.errorbar(
                xi,
                value,
                yerr=[[err_lo], [err_hi]],
                fmt="none",
                ecolor="#333333" if row["is_sub"] else edge,
                elinewidth=0.72 if row["is_sub"] else 0.58,
                capsize=2.2 if row["is_sub"] else 1.8,
                capthick=0.72 if row["is_sub"] else 0.58,
                alpha=0.95 if row["is_sub"] else 0.82,
                zorder=4,
            )
        elif row.get("has_recall_range"):
            cap_half_width = width * (0.22 if row["is_sub"] else 0.18)
            ax.hlines(
                value,
                xi - cap_half_width,
                xi + cap_half_width,
                color="#333333" if row["is_sub"] else edge,
                linewidth=0.72 if row["is_sub"] else 0.58,
                alpha=0.95 if row["is_sub"] else 0.82,
                zorder=4,
            )

        if row["is_sub"]:
            ax.text(
                xi,
                min(value + 0.018, ymax - 0.012),
                f"{value:.2f}",
                ha="center",
                va="bottom",
                fontsize=RECALL_SUBTOTAL_VALUE_FS - 1.4,
                fontweight=TEXT_WEIGHT,
                color=edge,
                zorder=5,
            )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(
        x_labels,
        rotation=22,
        ha="right",
        fontsize=AUTHOR_TICK_FS - 3.0,
        color=DARK,
        rotation_mode="anchor",
    )
    for label in ax.get_xticklabels():
        if label.get_text() == "Average":
            label.set_color("#1F1F1F")
            label.set_fontweight(TEXT_WEIGHT)
        else:
            label.set_fontweight("normal")
    if show_legend:
        add_topic_legend(ax)
    ax.set_ylabel(
        "Recall",
        fontsize=RECALL_AXIS_LABEL_FS,
        fontweight=TEXT_WEIGHT,
        color=DARK,
        labelpad=4,
    )
    ax.set_yticks([0.00, 0.50, 1.00])
    ax.set_yticklabels(["0.00", "0.50", "1.00"])
    ax.tick_params(colors=DARK, width=0.6)

    for label in ax.get_yticklabels():
        label.set_fontweight("normal")
        label.set_fontsize(RECALL_TICK_FS)
        label.set_color(DARK)

    ax.yaxis.grid(True, color="#E4E4E4", linewidth=0.35, linestyle="-", alpha=0.34, zorder=0)

    if save:
        set_panel_title(ax, f"{bundle['title']}: {RECALL_PANEL_TITLE}")
        fig.subplots_adjust(left=0.085, right=0.985, top=0.86, bottom=0.48)
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
    fig_h = max(7.2, n_bars * 0.56 + 3.95)

    if ax is None:
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    else:
        fig = ax.figure

    ax.set_facecolor(BG)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    subgs = ax.get_subplotspec().subgridspec(
        len(groups),
        1,
        height_ratios=[max(1.0, (len(items) - 1) * NNS_ROW_STEP + 1.0) for _, items in groups],
        hspace=NNS_SUBPLOT_HSPACE,
    )
    for idx, (topic_name, items) in enumerate(groups):
        gax = fig.add_subplot(subgs[idx, 0])
        draw_nns_group(
            gax,
            topic_name,
            items,
            show_xlabel=(idx == len(groups) - 1),
        )

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
        set_panel_title(ax, f"{bundle['title']}: {NNS_PANEL_TITLE}", pad=NNS_TITLE_PAD)
        fig.subplots_adjust(left=0.19, right=0.985, top=0.92, bottom=0.13)
        export_figure(fig, fname)
        plt.close(fig)


def plot_disease_combined(bundle, fname):
    fig = plt.figure(figsize=(11.6, 11.55))
    gs = fig.add_gridspec(2, 1, height_ratios=[0.70, 2.16], hspace=1.22)
    ax_recall = fig.add_subplot(gs[0])
    ax_nns = fig.add_subplot(gs[1])

    plot_recall(bundle, ax=ax_recall, save=False, show_legend=False)
    plot_nns(bundle, ax=ax_nns, save=False, show_legend=False)
    set_panel_title(ax_recall, f"{bundle['title']}: {RECALL_PANEL_TITLE}")
    set_panel_title(ax_nns, f"{bundle['title']}: {NNS_PANEL_TITLE}", pad=NNS_TITLE_PAD)

    ax_recall.text(
        -0.052,
        1.11,
        "a",
        transform=ax_recall.transAxes,
        ha="left",
        va="top",
        fontsize=PANEL_LABEL_FS,
        fontweight=TEXT_WEIGHT,
        color=DARK,
    )
    ax_nns.text(
        -0.065,
        1.035,
        "b",
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
        prop={"size": TOPIC_LEGEND_FS - 1.2, "weight": TEXT_WEIGHT},
        handlelength=1.22,
        handletextpad=0.46,
        columnspacing=0.95,
        borderaxespad=0.0,
    )
    fig.subplots_adjust(left=0.18, right=0.94, top=0.94, bottom=0.08)
    export_figure(fig, fname)
    plt.close(fig)


def plot_overall_combined(covid, mpox, fname="fig7_screening_overall_combined"):
    fig = plt.figure(figsize=(16.0, 9.85))
    outer = fig.add_gridspec(
        3,
        1,
        height_ratios=[0.07, 0.92, 2.08],
        hspace=0.62,
    )
    recall_gs = outer[1, 0].subgridspec(1, 2, wspace=0.16)
    nns_gs = outer[2, 0].subgridspec(1, 2, wspace=0.23)

    ax_legend = fig.add_subplot(outer[0, 0])
    ax_c_recall = fig.add_subplot(recall_gs[0, 0])
    ax_m_recall = fig.add_subplot(recall_gs[0, 1])
    ax_c_nns = fig.add_subplot(nns_gs[0, 0])
    ax_m_nns = fig.add_subplot(nns_gs[0, 1])
    ax_legend.axis("off")

    plot_recall(covid, ax=ax_c_recall, save=False, show_legend=False)
    plot_recall(mpox, ax=ax_m_recall, save=False, show_legend=False)
    plot_nns(covid, ax=ax_c_nns, save=False, show_legend=False)
    plot_nns(mpox, ax=ax_m_nns, save=False, show_legend=False)
    set_panel_title(ax_c_recall, f"{covid['title']}: {RECALL_PANEL_TITLE}", pad=RECALL_TITLE_PAD)
    set_panel_title(ax_m_recall, f"{mpox['title']}: {RECALL_PANEL_TITLE}", pad=RECALL_TITLE_PAD)
    set_panel_title(ax_c_nns, f"{covid['title']}: {NNS_PANEL_TITLE}", pad=NNS_TITLE_PAD)
    set_panel_title(ax_m_nns, f"{mpox['title']}: {NNS_PANEL_TITLE}", pad=NNS_TITLE_PAD)

    for ax, label in [
        (ax_c_recall, "a"),
        (ax_m_recall, "b"),
        (ax_c_nns, "c"),
        (ax_m_nns, "d"),
    ]:
        is_recall_panel = ax in (ax_c_recall, ax_m_recall)
        ax.text(
            -0.065 if is_recall_panel else -0.080,
            1.11 if is_recall_panel else 1.035,
            label,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=PANEL_LABEL_FS,
            fontweight=TEXT_WEIGHT,
            color=DARK,
        )

    ax_legend.legend(
        handles=screening_legend_handles(),
        loc="center",
        ncol=5,
        prop={"size": TOPIC_LEGEND_FS - 1.4, "weight": TEXT_WEIGHT},
        handlelength=1.20,
        handletextpad=0.46,
        columnspacing=1.00,
        frameon=False,
        borderaxespad=0.0,
    )
    fig.subplots_adjust(left=0.050, right=0.997, top=0.985, bottom=0.065)
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
