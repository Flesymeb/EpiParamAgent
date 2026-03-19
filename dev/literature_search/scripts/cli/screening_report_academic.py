"""
Generate an academic-style screening report (tables + figures).

Inputs:
  <root>/<topic>/pXX/
    - project_XX_groundtruth.csv
    - project_XX_screened.csv
    - project.json

Outputs (under --out):
  drafts/tables/screening_summary.csv
  drafts/tables/screening_summary.md
  drafts/tables/screening_summary.tex
  drafts/figs/pareto_recall_workload_<topic>.png
  drafts/figs/recall_workload_bars_<topic>.png
  drafts/figs/dimension_gt_vs_non_gt_<topic>.png
  drafts/figs/dimension_by_class_<topic>.png
  drafts/result.md (optional, updated by default)

Example:
  python scripts/cli/screening_report_academic.py \
    --root evaluation/screening/GT_1/GT_export \
    --topics serial_interval,reproduction_number,fatality \
    --out dev/literature_search/drafts \
    --with-plots \
    --update-md
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd


def _safe_float(value: str | None) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_ground_truth_pmids(csv_file: Path) -> Dict[str, Dict[str, str]]:
    ground_truth: Dict[str, Dict[str, str]] = {}
    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pmid = None
            for key in row.keys():
                if key is None:
                    continue
                key_norm = key.lower()
                if key_norm in ("pmid", "gt_pmid") or key == "\ufeffPMID":
                    pmid_val = (row.get(key) or "").strip()
                    if pmid_val and pmid_val.isdigit():
                        pmid = pmid_val
                        break
            if pmid:
                ground_truth[pmid] = {
                    "id": row.get("id", ""),
                    "title": row.get("title", ""),
                    "first_author": row.get("first_author", ""),
                    "year": row.get("year", ""),
                    "variant_focus": row.get("variant_focus", ""),
                }
    return ground_truth


def load_screened_results(csv_file: Path) -> Dict[str, Dict[str, Optional[float]]]:
    screened: Dict[str, Dict[str, Optional[float]]] = {}
    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pmid = (row.get("PMID") or "").strip()
            if not pmid:
                continue
            suggest = (row.get("llm_suggest") or "").strip() or "unlikely_candidate"
            screened[pmid] = {
                "llm_suggest": suggest,
                "overall_score": _safe_float(row.get("overall_score", "")),
                "disease_score": _safe_float(row.get("disease_score", "")),
                "population_score": _safe_float(row.get("population_score", "")),
                "location_score": _safe_float(row.get("location_score", "")),
                "evidence_score": _safe_float(row.get("evidence_score", "")),
                "transmission_score": _safe_float(row.get("transmission_score", "")),
            }
    return screened


def _mcc(tp: int, fp: int, fn: int, tn: int) -> float:
    num = tp * tn - fp * fn
    denom = math.sqrt(
        max((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn), 0.0)
    )
    return num / denom if denom > 0 else 0.0


def _wss_at_95(
    ground_truth: Dict[str, Dict], screened: Dict[str, Dict]
) -> Optional[float]:
    total_gt = len(ground_truth)
    if total_gt == 0:
        return None

    scored = []
    missing_score = True
    for pmid, info in screened.items():
        score = info.get("overall_score")
        if score is not None:
            missing_score = False
        scored.append((pmid, score))

    if missing_score:
        return None

    target_tp = math.ceil(total_gt * 0.95)
    max_reachable = sum(1 for pmid in ground_truth if pmid in screened)
    if target_tp > max_reachable:
        return None

    scored.sort(key=lambda x: (x[1] is None, -(x[1] or 0.0)))
    tp = 0
    k = 0
    for pmid, _ in scored:
        k += 1
        if pmid in ground_truth:
            tp += 1
            if tp >= target_tp:
                break
    if k == 0:
        return None
    return 1.0 - (k / len(scored))


def compute_metrics(
    ground_truth: Dict[str, Dict], screened: Dict[str, Dict]
) -> Dict[str, float]:
    strong = []
    possible = []
    unlikely = []
    not_found = []

    for pmid in ground_truth:
        if pmid in screened:
            suggest = screened[pmid]["llm_suggest"]
            if suggest == "strong_candidate":
                strong.append(pmid)
            elif suggest == "possible_candidate":
                possible.append(pmid)
            else:
                unlikely.append(pmid)
        else:
            not_found.append(pmid)

    non_gt_pmids = set(screened.keys()) - set(ground_truth.keys())
    fp_strong = sum(
        1
        for pmid in non_gt_pmids
        if screened[pmid]["llm_suggest"] == "strong_candidate"
    )
    fp_possible = sum(
        1
        for pmid in non_gt_pmids
        if screened[pmid]["llm_suggest"] == "possible_candidate"
    )
    tn = sum(
        1
        for pmid in non_gt_pmids
        if screened[pmid]["llm_suggest"] == "unlikely_candidate"
    )

    tp = len(strong) + len(possible)
    fn = len(unlikely) + len(not_found)
    fp = fp_strong + fp_possible

    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    npv = tn / (tn + fn) if (tn + fn) > 0 else 0.0
    f1 = (
        2 * (precision * sensitivity) / (precision + sensitivity)
        if (precision + sensitivity) > 0
        else 0.0
    )
    accuracy = (
        (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0
    )
    mcc = _mcc(tp, fp, fn, tn)

    pool_n = len(screened)
    workload_reduction = 1.0 - ((tp + fp) / pool_n) if pool_n > 0 else 0.0
    nns = (tp + fp) / tp if tp > 0 else math.inf

    return {
        "gt_total": len(ground_truth),
        "pool_total": pool_n,
        "gt_missing": len(not_found),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "recall": sensitivity,
        "precision": precision,
        "workload_reduction": workload_reduction,
        "nns": nns,
        "specificity": specificity,
        "npv": npv,
        "f1": f1,
        "accuracy": accuracy,
        "mcc": mcc,
    }


def compute_metrics_from_counts(counts: Dict[str, int]) -> Dict[str, float]:
    tp = counts["tp"]
    fp = counts["fp"]
    fn = counts["fn"]
    tn = counts["tn"]
    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    npv = tn / (tn + fn) if (tn + fn) > 0 else 0.0
    f1 = (
        2 * (precision * sensitivity) / (precision + sensitivity)
        if (precision + sensitivity) > 0
        else 0.0
    )
    accuracy = (
        (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0
    )
    mcc = _mcc(tp, fp, fn, tn)
    pool_n = counts["pool_total"]
    workload_reduction = 1.0 - ((tp + fp) / pool_n) if pool_n > 0 else 0.0
    nns = (tp + fp) / tp if tp > 0 else math.inf
    return {
        "gt_total": counts["gt_total"],
        "pool_total": pool_n,
        "gt_missing": counts["gt_missing"],
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "recall": sensitivity,
        "precision": precision,
        "workload_reduction": workload_reduction,
        "nns": nns,
        "specificity": specificity,
        "npv": npv,
        "f1": f1,
        "accuracy": accuracy,
        "mcc": mcc,
    }


def _format_percent(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _format_float(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "-"
    if math.isinf(value):
        return "inf"
    return f"{value:.{digits}f}"


def _markdown_table(rows: List[Dict[str, str]], headers: List[str]) -> str:
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row.get(h, "") for h in headers) + " |")
    return "\n".join(lines)


def _collect_runs(root: Path, topics: Iterable[str]) -> List[Dict[str, str]]:
    runs = []
    for topic in topics:
        topic_dir = root / topic
        if not topic_dir.exists():
            print(f"[WARN] Topic not found: {topic_dir}")
            continue
        for pdir in sorted(topic_dir.iterdir()):
            if not pdir.is_dir() or not pdir.name.lower().startswith("p"):
                continue
            gt_files = list(pdir.glob("project_*_groundtruth.csv"))
            screened_files = list(pdir.glob("project_*_screened.csv"))
            project_files = list(pdir.glob("project.json"))

            if not gt_files or not screened_files:
                print(f"[WARN] Missing files in {pdir}")
                continue

            run = {
                "topic": topic,
                "config": pdir.name.upper(),
                "gt_path": str(gt_files[0]),
                "screened_path": str(screened_files[0]),
                "project_path": str(project_files[0]) if project_files else "",
            }
            runs.append(run)
    return runs


def main() -> None:
    parser = argparse.ArgumentParser(description="Academic screening report generator")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("evaluation/screening/GT_1/GT_export"),
        help="GT_export root directory",
    )
    parser.add_argument(
        "--topics",
        type=str,
        default="",
        help="Comma-separated topics (default: auto-detect under root)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("dev/literature_search/drafts"),
        help="Output directory for tables/figs/result.md",
    )
    parser.add_argument("--with-plots", action="store_true", help="Generate PNG figures")
    parser.add_argument(
        "--update-md",
        action="store_true",
        help="Update drafts/result.md with summary + figure links",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    out_dir = args.out.resolve()
    tables_dir = out_dir / "tables"
    figs_dir = out_dir / "figs"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figs_dir.mkdir(parents=True, exist_ok=True)

    if args.topics:
        topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    else:
        topics = [p.name for p in root.iterdir() if p.is_dir()]

    runs = _collect_runs(root, topics)
    if not runs:
        raise SystemExit("No valid runs found.")

    rows = []
    metrics_rows = []
    for run in runs:
        ground_truth = load_ground_truth_pmids(Path(run["gt_path"]))
        screened = load_screened_results(Path(run["screened_path"]))

        metrics = compute_metrics(ground_truth, screened)
        wss95 = _wss_at_95(ground_truth, screened)
        metrics["wss95"] = wss95

        row = {
            "Topic": run["topic"],
            "Config": run["config"],
            "Level": "config",
            "GT": metrics["gt_total"],
            "Pool": metrics["pool_total"],
            "GT_missing": metrics["gt_missing"],
            "TP": metrics["tp"],
            "FP": metrics["fp"],
            "FN": metrics["fn"],
            "TN": metrics["tn"],
            "Recall": metrics["recall"],
            "Precision": metrics["precision"],
            "WorkloadReduction": metrics["workload_reduction"],
            "NNS": metrics["nns"],
            "Specificity": metrics["specificity"],
            "NPV": metrics["npv"],
            "F1": metrics["f1"],
            "Accuracy": metrics["accuracy"],
            "MCC": metrics["mcc"],
            "WSS@95": metrics["wss95"],
        }
        rows.append(row)

        metrics_rows.append(
            {
                "topic": run["topic"],
                **metrics,
            }
        )

    summary_rows = []
    for topic in sorted(set(r["topic"] for r in metrics_rows)):
        topic_rows = [r for r in metrics_rows if r["topic"] == topic]
        counts = {
            "gt_total": sum(r["gt_total"] for r in topic_rows),
            "pool_total": sum(r["pool_total"] for r in topic_rows),
            "gt_missing": sum(r["gt_missing"] for r in topic_rows),
            "tp": sum(r["tp"] for r in topic_rows),
            "fp": sum(r["fp"] for r in topic_rows),
            "fn": sum(r["fn"] for r in topic_rows),
            "tn": sum(r["tn"] for r in topic_rows),
        }
        metrics = compute_metrics_from_counts(counts)
        row = {
            "Topic": topic,
            "Config": "ALL",
            "Level": "topic_summary",
            "GT": metrics["gt_total"],
            "Pool": metrics["pool_total"],
            "GT_missing": metrics["gt_missing"],
            "TP": metrics["tp"],
            "FP": metrics["fp"],
            "FN": metrics["fn"],
            "TN": metrics["tn"],
            "Recall": metrics["recall"],
            "Precision": metrics["precision"],
            "WorkloadReduction": metrics["workload_reduction"],
            "NNS": metrics["nns"],
            "Specificity": metrics["specificity"],
            "NPV": metrics["npv"],
            "F1": metrics["f1"],
            "Accuracy": metrics["accuracy"],
            "MCC": metrics["mcc"],
            "WSS@95": None,
        }
        summary_rows.append(row)

    overall_counts = {
        "gt_total": sum(r["gt_total"] for r in metrics_rows),
        "pool_total": sum(r["pool_total"] for r in metrics_rows),
        "gt_missing": sum(r["gt_missing"] for r in metrics_rows),
        "tp": sum(r["tp"] for r in metrics_rows),
        "fp": sum(r["fp"] for r in metrics_rows),
        "fn": sum(r["fn"] for r in metrics_rows),
        "tn": sum(r["tn"] for r in metrics_rows),
    }
    overall = compute_metrics_from_counts(overall_counts)
    summary_rows.append(
        {
            "Topic": "ALL",
            "Config": "ALL",
            "Level": "overall",
            "GT": overall["gt_total"],
            "Pool": overall["pool_total"],
            "GT_missing": overall["gt_missing"],
            "TP": overall["tp"],
            "FP": overall["fp"],
            "FN": overall["fn"],
            "TN": overall["tn"],
            "Recall": overall["recall"],
            "Precision": overall["precision"],
            "WorkloadReduction": overall["workload_reduction"],
            "NNS": overall["nns"],
            "Specificity": overall["specificity"],
            "NPV": overall["npv"],
            "F1": overall["f1"],
            "Accuracy": overall["accuracy"],
            "MCC": overall["mcc"],
            "WSS@95": None,
        }
    )

    all_rows = rows + summary_rows

    df = pd.DataFrame(all_rows)
    csv_path = tables_dir / "screening_summary.csv"
    df.to_csv(csv_path, index=False)

    md_headers = [
        "Topic",
        "Config",
        "Level",
        "GT",
        "Pool",
        "TP",
        "FP",
        "FN",
        "TN",
        "Recall",
        "Precision",
        "WorkloadReduction",
        "NNS",
        "Specificity",
        "NPV",
        "F1",
        "Accuracy",
        "MCC",
        "WSS@95",
    ]
    md_rows: List[Dict[str, str]] = []
    for row in all_rows:
        md_rows.append(
            {
                "Topic": row["Topic"],
                "Config": row["Config"],
                "Level": row["Level"],
                "GT": str(row["GT"]),
                "Pool": str(row["Pool"]),
                "TP": str(row["TP"]),
                "FP": str(row["FP"]),
                "FN": str(row["FN"]),
                "TN": str(row["TN"]),
                "Recall": _format_percent(row["Recall"]),
                "Precision": _format_percent(row["Precision"]),
                "WorkloadReduction": _format_percent(row["WorkloadReduction"]),
                "NNS": _format_float(row["NNS"]),
                "Specificity": _format_percent(row["Specificity"]),
                "NPV": _format_percent(row["NPV"]),
                "F1": _format_percent(row["F1"]),
                "Accuracy": _format_percent(row["Accuracy"]),
                "MCC": _format_float(row["MCC"], 2),
                "WSS@95": _format_percent(row["WSS@95"]),
            }
        )
    md_table = _markdown_table(md_rows, md_headers)
    md_path = tables_dir / "screening_summary.md"
    md_path.write_text(md_table, encoding="utf-8")

    tex_path = tables_dir / "screening_summary.tex"
    df_export = df.copy()
    df_export["Recall"] = df_export["Recall"].apply(lambda x: f"{x*100:.1f}%")
    df_export["Precision"] = df_export["Precision"].apply(lambda x: f"{x*100:.1f}%")
    df_export["WorkloadReduction"] = df_export["WorkloadReduction"].apply(
        lambda x: f"{x*100:.1f}%"
    )
    df_export["Specificity"] = df_export["Specificity"].apply(
        lambda x: f"{x*100:.1f}%"
    )
    df_export["NPV"] = df_export["NPV"].apply(lambda x: f"{x*100:.1f}%")
    df_export["F1"] = df_export["F1"].apply(lambda x: f"{x*100:.1f}%")
    df_export["Accuracy"] = df_export["Accuracy"].apply(lambda x: f"{x*100:.1f}%")
    df_export["MCC"] = df_export["MCC"].apply(lambda x: f"{x:.2f}")
    df_export["WSS@95"] = df_export["WSS@95"].apply(
        lambda x: "-" if x is None else f"{x*100:.1f}%"
    )
    df_export["NNS"] = df_export["NNS"].apply(
        lambda x: "inf" if math.isinf(x) else f"{x:.1f}"
    )
    tex_path.write_text(
        df_export.to_latex(index=False, escape=True),
        encoding="utf-8",
    )

    if args.with_plots:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "matplotlib is required for --with-plots. Install it and retry."
            ) from exc

        # Reference palette (paper-style)
        palette = {
            "blue": "#7E99F4",
            "orange": "#CC7C71",
            "green": "#7AB656",
            "red": "#CC7C71",
            "purple": "#925EB0",
            "yellow": "#A5AEB7",
            "teal": "#A5AEB7",
            "gray": "#A5AEB7",
        }
        plt.rcParams.update(
            {
                "font.family": "DejaVu Serif",
                "mathtext.fontset": "dejavuserif",
                "axes.titlesize": 16,
                "axes.labelsize": 13,
                "xtick.labelsize": 12,
                "ytick.labelsize": 12,
                "legend.fontsize": 11,
                "font.weight": "regular",
                "axes.titleweight": "bold",
                "axes.labelweight": "bold",
                "axes.grid": True,
                "grid.alpha": 0.25,
                "grid.linestyle": "--",
                "axes.spines.top": False,
                "axes.spines.right": False,
                "figure.dpi": 300,
                "savefig.dpi": 300,
                "savefig.facecolor": "white",
            }
        )

        for topic in sorted(set(t["Topic"] for t in rows)):
            topic_rows = [r for r in rows if r["Topic"] == topic]
            if not topic_rows:
                continue

            # Pareto: Recall vs Workload Reduction
            fig, ax = plt.subplots(figsize=(6.6, 4.6))
            points = []
            for r in topic_rows:
                points.append((r["WorkloadReduction"], r["Recall"], r["Config"]))
            points.sort(key=lambda x: (-x[0], -x[1]))
            best_recall = -1.0
            frontier = []
            for wr, rec, cfg in points:
                if rec > best_recall:
                    frontier.append((wr, rec))
                    best_recall = rec
            ax.scatter(
                [p[0] for p in points],
                [p[1] for p in points],
                s=55,
                alpha=0.9,
                color=palette["blue"],
                edgecolor="white",
                linewidth=0.6,
            )
            for wr, rec, cfg in points:
                ax.text(wr + 0.006, rec + 0.006, cfg, fontsize=10)
            if len(frontier) >= 2:
                ax.plot(
                    [p[0] for p in frontier],
                    [p[1] for p in frontier],
                    color=palette["purple"],
                    linewidth=2,
                    label="Pareto frontier",
                )
                ax.legend(fontsize=8)
            ax.set_xlabel("Workload Reduction")
            ax.set_ylabel("Recall")
            ax.set_title(f"Pareto: Recall vs Workload ({topic})")
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.grid(True, axis="both", linestyle="--", alpha=0.25)
            fig.tight_layout()
            fig.savefig(
                figs_dir / f"pareto_recall_workload_{topic}.png",
                dpi=300,
                bbox_inches="tight",
            )
            plt.close(fig)

            # Recall vs Workload bars
            topic_rows.sort(key=lambda r: r["Recall"], reverse=True)
            labels = [r["Config"] for r in topic_rows]
            recall_vals = [r["Recall"] for r in topic_rows]
            wr_vals = [r["WorkloadReduction"] for r in topic_rows]
            x = range(len(labels))
            width = 0.4
            fig, ax = plt.subplots(figsize=(7.6, 4.6))
            ax.bar(
                [i - width / 2 for i in x],
                recall_vals,
                width,
                label="Recall",
                color=palette["blue"],
            )
            ax.bar(
                [i + width / 2 for i in x],
                wr_vals,
                width,
                label="Workload Reduction",
                color=palette["orange"],
            )
            ax.set_xticks(list(x))
            ax.set_xticklabels(labels, rotation=20, ha="right")
            ax.set_ylim(0, 1)
            ax.set_ylabel("Rate")
            ax.set_title(f"Recall vs Workload Reduction ({topic})")
            ax.legend()
            ax.set_axisbelow(True)
            ax.grid(True, axis="y", linestyle="--", alpha=0.25)
            fig.tight_layout()
            fig.savefig(
                figs_dir / f"recall_workload_bars_{topic}.png",
                dpi=300,
                bbox_inches="tight",
            )
            plt.close(fig)

            # Funnel: Pool -> Predicted relevant -> GT
            topic_rows.sort(key=lambda r: r["Config"])
            stage_labels = ["Pool", "Predicted", "GT"]
            pool_max = max(r["Pool"] for r in topic_rows) if topic_rows else 1
            n_configs = len(topic_rows)
            fig_height = max(2.5, 1.2 * n_configs + 1.2)
            fig, axes = plt.subplots(
                nrows=n_configs, ncols=1, figsize=(7.8, fig_height), sharex=True
            )
            if n_configs == 1:
                axes = [axes]
            for ax, r in zip(axes, topic_rows):
                pool_val = r["Pool"]
                pred_val = r["TP"] + r["FP"]
                gt_val = r["GT"]
                tp_val = r["TP"]
                fn_val = r["FN"]

                widths = [pool_val, pred_val, gt_val]
                y_positions = [2, 1, 0]

                # Funnel polygons (clean, paper-like)
                funnel_colors = [palette["yellow"], palette["blue"]]
                for idx in range(2):
                    w0 = widths[idx]
                    w1 = widths[idx + 1]
                    y0 = y_positions[idx]
                    y1 = y_positions[idx + 1]
                    xs = [-w0 / 2, w0 / 2, w1 / 2, -w1 / 2]
                    ys = [y0, y0, y1, y1]
                    ax.fill(
                        xs,
                        ys,
                        color=funnel_colors[idx],
                        alpha=0.45,
                        edgecolor="#FFFFFF",
                        linewidth=1.2,
                    )
                    ax.plot(
                        xs + [xs[0]],
                        ys + [ys[0]],
                        color="#DDDDDD",
                        linewidth=0.8,
                    )

                # Stage value labels
                for val, y in zip(widths, y_positions):
                    ax.text(
                        val / 2 + pool_max * 0.05,
                        y,
                        f"{val}",
                        va="center",
                        fontsize=11,
                        fontweight="bold",
                        color="#333333",
                    )

                # FN highlight at GT stage
                gt_y = y_positions[-1]
                gt_left = -gt_val / 2
                bar_h = 0.24
                tp_width = max(tp_val, 0)
                fn_width = max(fn_val, 0)
                ax.barh(
                    gt_y,
                    tp_width,
                    left=gt_left,
                    height=bar_h,
                    color=palette["green"],
                    alpha=0.9,
                    edgecolor="white",
                    linewidth=0.7,
                )
                if fn_width > 0:
                    ax.barh(
                        gt_y,
                        fn_width,
                        left=gt_left + tp_width,
                        height=bar_h,
                        color=palette["red"],
                        alpha=0.9,
                        edgecolor="white",
                        linewidth=0.7,
                    )
                    ax.text(
                        gt_left + tp_width + fn_width / 2,
                        gt_y + 0.18,
                        f"FN {fn_width}",
                        ha="center",
                        va="bottom",
                        fontsize=10,
                        fontweight="bold",
                        color=palette["red"],
                    )

                ax.set_xlim(-pool_max * 0.62, pool_max * 0.62)
                ax.set_ylim(-0.6, 2.6)
                ax.set_title(f"{r['Config']}", loc="left", pad=6)
                ax.set_yticks(y_positions)
                ax.set_yticklabels(stage_labels, fontweight="bold")
                ax.set_xlabel("Count (symmetric)")
                ax.grid(True, axis="x", linestyle="--", alpha=0.25)
            fig.suptitle(
                f"Funnel Plot ({topic})",
                y=0.98,
                fontsize=16,
                fontweight="bold",
            )
            fig.tight_layout()
            fig.savefig(figs_dir / f"funnel_{topic}.png", dpi=300, bbox_inches="tight")
            plt.close(fig)

        # Dimension analysis per topic (merged across configs)
        dimensions = [
            ("disease_score", "Disease"),
            ("population_score", "Population"),
            ("location_score", "Location"),
            ("evidence_score", "Evidence"),
            ("transmission_score", "Transmission"),
        ]
        for topic in sorted(set(r["topic"] for r in runs)):
            topic_runs = [r for r in runs if r["topic"] == topic]
            if not topic_runs:
                continue

            merged_ground_truth: Dict[str, Dict[str, str]] = {}
            merged_screened: Dict[str, Dict[str, Optional[float]]] = {}
            for run in topic_runs:
                merged_ground_truth.update(load_ground_truth_pmids(Path(run["gt_path"])))
                merged_screened.update(load_screened_results(Path(run["screened_path"])))

            gt_set = set(merged_ground_truth.keys())
            scores_present = any(
                merged_screened[pmid].get(dim[0]) is not None
                for pmid in merged_screened
                for dim in dimensions
            )
            if not scores_present:
                print(f"[WARN] No dimension scores for topic {topic}")
                continue

            gt_means = []
            ngt_means = []
            for key, _ in dimensions:
                gt_vals = [
                    merged_screened[pmid][key]
                    for pmid in merged_screened
                    if pmid in gt_set and merged_screened[pmid][key] is not None
                ]
                ngt_vals = [
                    merged_screened[pmid][key]
                    for pmid in merged_screened
                    if pmid not in gt_set and merged_screened[pmid][key] is not None
                ]
                gt_means.append(sum(gt_vals) / len(gt_vals) if gt_vals else 0.0)
                ngt_means.append(sum(ngt_vals) / len(ngt_vals) if ngt_vals else 0.0)

            labels = [dim[1] for dim in dimensions]
            angles = [i / float(len(labels)) * 2 * math.pi for i in range(len(labels))]
            angles += angles[:1]

            gt_plot = gt_means + gt_means[:1]
            ngt_plot = ngt_means + ngt_means[:1]

            fig = plt.figure(figsize=(6.8, 5.2))
            ax = plt.subplot(111, polar=True)
            ax.set_theta_offset(math.pi / 2)
            ax.set_theta_direction(-1)
            ax.plot(angles, gt_plot, linewidth=2, label="GT", color=palette["blue"])
            ax.fill(angles, gt_plot, alpha=0.12, color=palette["blue"])
            ax.plot(
                angles, ngt_plot, linewidth=2, label="Non-GT", color=palette["green"]
            )
            ax.fill(angles, ngt_plot, alpha=0.12, color=palette["green"])
            angles_deg = [a * 180 / math.pi for a in angles[:-1]]
            ax.set_thetagrids(angles_deg, labels)
            for label, angle in zip(ax.get_xticklabels(), angles_deg):
                display_angle = (90 - angle) % 360
                label.set_rotation(display_angle + 90)
                label.set_rotation_mode("anchor")
                label.set_ha("center")
                label.set_va("center")
                label.set_fontweight("bold")
                label.set_fontsize(12)
            ax.set_ylim(0, 5)
            ax.set_title(f"Dimension Radar: GT vs Non-GT ({topic})", y=1.08)
            ax.legend(loc="upper right", bbox_to_anchor=(1.2, 1.1))
            ax.grid(True, linestyle="--", alpha=0.25)
            fig.tight_layout()
            fig.savefig(
                figs_dir / f"dimension_gt_vs_non_gt_{topic}.png",
                dpi=300,
                bbox_inches="tight",
            )
            plt.close(fig)

            class_order = [
                ("strong_candidate", "Strong"),
                ("possible_candidate", "Possible"),
                ("unlikely_candidate", "Unlikely"),
            ]
            class_means = {c[0]: [] for c in class_order}
            for key, _ in dimensions:
                for cls, _ in class_order:
                    cls_vals = [
                        merged_screened[pmid][key]
                        for pmid in merged_screened
                        if merged_screened[pmid]["llm_suggest"] == cls
                        and merged_screened[pmid][key] is not None
                    ]
                    class_means[cls].append(
                        sum(cls_vals) / len(cls_vals) if cls_vals else 0.0
                    )

            fig = plt.figure(figsize=(6.9, 5.3))
            ax = plt.subplot(111, polar=True)
            ax.set_theta_offset(math.pi / 2)
            ax.set_theta_direction(-1)
            class_colors = {
                "strong_candidate": palette["purple"],
                "possible_candidate": palette["blue"],
                "unlikely_candidate": palette["orange"],
            }
            for cls, label in class_order:
                vals = class_means[cls] + class_means[cls][:1]
                ax.plot(
                    angles, vals, linewidth=2, label=label, color=class_colors[cls]
                )
                ax.fill(angles, vals, alpha=0.12, color=class_colors[cls])
            angles_deg = [a * 180 / math.pi for a in angles[:-1]]
            ax.set_thetagrids(angles_deg, labels)
            for label, angle in zip(ax.get_xticklabels(), angles_deg):
                display_angle = (90 - angle) % 360
                label.set_rotation(display_angle + 90)
                label.set_rotation_mode("anchor")
                label.set_ha("center")
                label.set_va("center")
                label.set_fontweight("bold")
                label.set_fontsize(12)
            ax.set_ylim(0, 5)
            ax.set_title(f"Dimension Radar by Prediction ({topic})", y=1.08)
            ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1))
            ax.grid(True, linestyle="--", alpha=0.25)
            fig.tight_layout()
            fig.savefig(
                figs_dir / f"dimension_by_class_{topic}.png",
                dpi=300,
                bbox_inches="tight",
            )
            plt.close(fig)

    if args.update_md:
        md_body = f"""# Screening Results Summary

## Methods
- Data source: `{root}`
- Ground truth: `project_*_groundtruth.csv`
- Screened results: `project_*_screened.csv`
- Decision rule: Relevant = Strong + Possible; Not relevant = Unlikely; Missing GT treated as FN.
- Metrics focus: Recall, Precision, Workload Reduction, NNS (efficiency-first).

## Main Table
{md_table}

## Figures
- Pareto plots: `drafts/figs/pareto_recall_workload_<topic>.png`
- Recall vs Workload bars: `drafts/figs/recall_workload_bars_<topic>.png`
- Funnel plots: `drafts/figs/funnel_<topic>.png`
- Dimension scores (GT vs Non-GT): `drafts/figs/dimension_gt_vs_non_gt_<topic>.png`
- Dimension scores by class: `drafts/figs/dimension_by_class_<topic>.png`

## Appendix
- Per-config confusion matrices are available in screening logs under each topic/pXX folder.
"""
        (out_dir / "result.md").write_text(md_body, encoding="utf-8")

    print(f"[OK] Wrote summary CSV: {csv_path}")
    print(f"[OK] Wrote summary MD:  {md_path}")
    print(f"[OK] Wrote summary TEX: {tex_path}")
    if args.with_plots:
        print(f"[OK] Wrote figures to: {figs_dir}")
    if args.update_md:
        print(f"[OK] Updated report:  {out_dir / 'result.md'}")


if __name__ == "__main__":
    main()
