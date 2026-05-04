"""
筛选结果评估工具。

支持两种模式：
1. profile 模式：--project-root + --profile
2. 显式文件模式：直接传入 raw / screened / ground-truth 文件

使用示例：
    python scripts/cli/screening_evaluation.py search-coverage --project-root D:/repo/MetaAgent-Epi --profile P13
    python scripts/cli/screening_evaluation.py screening-performance --project-root D:/repo/MetaAgent-Epi --profile P13
    python scripts/cli/screening_evaluation.py retrieval-metrics --ground-truth outputs/raw.csv --retrieved-results outputs/retrieved.jsonl
"""

import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Dict, Set, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from metaagent.provenance import write_run_manifest
from metaagent.screening.profile_registry import resolve_profile_paths

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console() if HAS_RICH else None

# Set CSV field size limit to maximum possible value
try:
    csv.field_size_limit(sys.maxsize)
except (AttributeError, ValueError, OverflowError):
    try:
        csv.field_size_limit(2**31 - 1)  # 2GB fallback
    except (AttributeError, ValueError, OverflowError):
        pass


def load_ground_truth_pmids(csv_file: Path) -> Dict[str, Dict]:
    """
    从ground truth CSV加载PMIDs

    Returns:
        Dict[pmid -> {id, title, first_author, year, variant_focus}]
    """
    ground_truth = {}
    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 处理可能的BOM
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


def load_search_results(csv_file: Path) -> Set[str]:
    """加载搜索结果的PMID集合"""
    pmids = set()
    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pmid = row.get("PMID", "").strip()
            if pmid:
                pmids.add(pmid)
    return pmids


def load_screened_results(csv_file: Path) -> Dict[str, Dict]:
    """
    加载筛选结果

    Returns:
        Dict[pmid -> {llm_suggest, overall_score, dimension scores, ...}]
    """
    screened = {}
    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pmid = row.get("PMID", "").strip()
            if pmid:
                parameter_score_raw = row.get("parameter_score", "")
                if not str(parameter_score_raw).strip():
                    parameter_score_raw = row.get("transmission_score", "0")
                screened[pmid] = {
                    "pmid": pmid,
                    "llm_suggest": row.get("llm_suggest", ""),
                    "original_llm_suggest": row.get("llm_suggest", ""),
                    "overall_score": row.get("overall_score", "0"),
                    "overall_justification": row.get("overall_justification", ""),
                    "title": row.get("Title", ""),
                    "screening_stage": row.get("screening_stage", "").strip(),
                    "screening_mode": row.get("screening_mode", "").strip(),
                    # 5个核心维度评分
                    "disease_score": int(row.get("disease_score", "0") or "0"),
                    "population_score": int(row.get("population_score", "0") or "0"),
                    "location_score": int(row.get("location_score", "0") or "0"),
                    "evidence_score": int(row.get("evidence_score", "0") or "0"),
                    "parameter_score": int(parameter_score_raw or "0"),
                }
    return screened


def build_threshold_overrides(args: argparse.Namespace) -> Dict[str, Dict[str, int]] | None:
    """Collect CLI threshold overrides for evaluation-only reclassification."""
    thresholds: Dict[str, Dict[str, int]] = {"strong": {}, "possible": {}}
    field_map = {
        "disease": "disease_min",
        "parameter": "parameter_min",
        "evidence": "evidence_min",
        "population": "population_min",
        "location": "location_min",
    }
    for bucket in ("strong", "possible"):
        for field, key in field_map.items():
            value = getattr(args, f"{bucket}_{field}_min", None)
            if value is not None:
                thresholds[bucket][key] = int(value)

    if any(thresholds[bucket] for bucket in thresholds):
        return thresholds
    return None


def normalize_eval_thresholds(
    overrides: Dict[str, Dict[str, int]] | None,
) -> Dict[str, Dict[str, int]]:
    """Canonical threshold defaults for evaluation-side sensitivity analysis."""
    defaults = {
        "strong": {
            "disease_min": 4,
            "parameter_min": 4,
            "evidence_min": 3,
            "population_min": 2,
            "location_min": 2,
        },
        "possible": {
            "disease_min": 3,
            "parameter_min": 3,
            "evidence_min": 2,
            "population_min": 2,
            "location_min": 2,
        },
    }
    merged = {
        "strong": dict(defaults["strong"]),
        "possible": dict(defaults["possible"]),
    }
    for bucket, values in (overrides or {}).items():
        if bucket not in merged:
            continue
        for key, value in values.items():
            if key in merged[bucket] and value is not None:
                merged[bucket][key] = int(value)
    return merged


def resolve_eval_stage_mode(paper: Dict[str, Any]) -> str:
    """Resolve stage mode from screened CSV metadata for evaluation-time reclassification."""
    mode = str(paper.get("screening_mode", "") or "").strip().lower()
    if mode:
        return mode

    stage = str(paper.get("screening_stage", "") or "").strip().lower()
    if stage == "title_only":
        return "lenient"
    if stage == "full_text":
        return "standard"
    return "strict"


def apply_eval_stage_mode(threshold_block: Dict[str, int], *, stage_mode: str) -> Dict[str, int]:
    """Mirror screening-time lenient title-only behavior inside evaluation."""
    adjusted = dict(threshold_block)
    if stage_mode != "lenient":
        return adjusted

    relaxed_by_one = {
        "disease_min": 2,
        "parameter_min": 2,
        "evidence_min": 1,
        "population_min": 1,
        "location_min": 1,
    }
    for key, floor in relaxed_by_one.items():
        adjusted[key] = max(floor, adjusted[key] - 1)
    return adjusted


def meets_threshold_block(paper: Dict[str, Any], threshold_block: Dict[str, int]) -> bool:
    score_map = {
        "disease_min": "disease_score",
        "parameter_min": "parameter_score",
        "evidence_min": "evidence_score",
        "population_min": "population_score",
        "location_min": "location_score",
    }
    return all(
        int(paper.get(score_map[key], 0) or 0) >= min_score
        for key, min_score in threshold_block.items()
    )


def reclassify_screened_results(
    screened: Dict[str, Dict],
    threshold_overrides: Dict[str, Dict[str, int]] | None,
) -> tuple[Dict[str, Dict], Dict[str, Dict[str, int]]]:
    """Recompute llm_suggest from five-dimension scores for evaluation-only threshold sweeps."""
    thresholds = normalize_eval_thresholds(threshold_overrides)
    reclassified: Dict[str, Dict] = {}
    for pmid, paper in screened.items():
        updated = dict(paper)
        stage_mode = resolve_eval_stage_mode(updated)
        if meets_threshold_block(updated, thresholds["strong"]):
            updated["llm_suggest"] = "strong_candidate"
        else:
            possible_block = apply_eval_stage_mode(
                thresholds["possible"], stage_mode=stage_mode
            )
            updated["llm_suggest"] = (
                "possible_candidate"
                if meets_threshold_block(updated, possible_block)
                else "unlikely_candidate"
            )
        reclassified[pmid] = updated
    return reclassified, thresholds


def compute_confusion_counts(
    ground_truth: Dict[str, Dict],
    screened: Dict[str, Dict],
) -> Dict[str, int]:
    """Compute binary confusion counts from screened labels."""
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
        1 for pmid in non_gt_pmids if screened[pmid]["llm_suggest"] == "strong_candidate"
    )
    fp_possible = sum(
        1 for pmid in non_gt_pmids if screened[pmid]["llm_suggest"] == "possible_candidate"
    )
    tn = sum(
        1 for pmid in non_gt_pmids if screened[pmid]["llm_suggest"] == "unlikely_candidate"
    )

    tp = len(strong) + len(possible)
    fn = len(unlikely) + len(not_found)
    fp = fp_strong + fp_possible
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "strong": len(strong),
        "possible": len(possible),
        "unlikely": len(unlikely),
        "missing": len(not_found),
    }


def summarize_counts(counts: Dict[str, int], pool_size: int) -> Dict[str, float]:
    """Compute point metrics from confusion counts."""
    tp = counts["tp"]
    fp = counts["fp"]
    fn = counts["fn"]
    tn = counts["tn"]
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    npv = tn / (tn + fn) if (tn + fn) else 0.0
    accuracy = (tp + tn) / pool_size if pool_size else 0.0
    wr = (tn + fn) / pool_size if pool_size else 0.0
    nns = (tp + fp) / tp if tp else math.inf
    mcc = matthews_corrcoef(tp, fp, fn, tn)
    return {
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "specificity": specificity,
        "npv": npv,
        "accuracy": accuracy,
        "wr": wr,
        "nns": nns,
        "mcc": mcc,
        "wss95": wr - 0.05,
    }


def threshold_sweep(
    ground_truth: Dict[str, Dict],
    screened: Dict[str, Dict],
    *,
    axis: str,
    values: List[int],
    bucket: str,
    topic: str = "",
    project_label: str = "",
) -> List[Dict[str, str]]:
    """Run evaluation-only threshold sensitivity analysis over one threshold axis."""
    axis_key_map = {
        "disease": "disease_min",
        "parameter": "parameter_min",
        "evidence": "evidence_min",
        "population": "population_min",
        "location": "location_min",
    }
    if axis not in axis_key_map:
        raise ValueError(f"Unsupported sweep axis: {axis}")

    rows: List[Dict[str, str]] = []
    pool_size = len(screened)
    threshold_key = axis_key_map[axis]

    print("\n" + "=" * 120)
    print(f"Threshold sweep | {project_label or 'custom'} | {topic or 'unknown'}")
    print("=" * 120)
    print(f"Axis: {bucket}.{axis} | Values: {values}\n")
    print(
        f"{'Value':>5} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4} {'Recall':>8} {'Precision':>10} {'F1':>8} {'WR':>8} {'NNS':>8}"
    )
    print("-" * 80)

    for value in values:
        overrides = {bucket: {threshold_key: int(value)}}
        reclassified, applied = reclassify_screened_results(screened, overrides)
        counts = compute_confusion_counts(ground_truth, reclassified)
        metrics = summarize_counts(counts, pool_size)
        row = {
            "project": project_label or "custom",
            "topic": topic or "unknown",
            "bucket": bucket,
            "axis": axis,
            "value": str(value),
            "tp": str(counts["tp"]),
            "fp": str(counts["fp"]),
            "fn": str(counts["fn"]),
            "tn": str(counts["tn"]),
            "recall": format_pct(metrics["recall"]),
            "precision": format_pct(metrics["precision"]),
            "f1": format_pct(metrics["f1"]),
            "wr": format_pct(metrics["wr"]),
            "nns": format_ratio(metrics["nns"]),
            "specificity": format_pct(metrics["specificity"]),
            "npv": format_pct(metrics["npv"]),
            "accuracy": format_pct(metrics["accuracy"]),
            "mcc": f"{metrics['mcc']:.3f}",
            "wss95": format_pct(metrics["wss95"]),
            "thresholds": json.dumps(applied, ensure_ascii=False),
        }
        rows.append(row)
        print(
            f"{value:>5} {counts['tp']:>4} {counts['fp']:>4} {counts['fn']:>4} {counts['tn']:>4} "
            f"{row['recall']:>8} {row['precision']:>10} {row['f1']:>8} {row['wr']:>8} {row['nns']:>8}"
        )

    return rows


def write_threshold_sweep_tsv(
    output_dir: Path,
    rows: List[Dict[str, str]],
    *,
    axis: str,
    bucket: str,
) -> Path:
    """Persist threshold sweep rows as TSV for downstream comparison."""
    output_path = output_dir / f"threshold_sweep_{bucket}_{axis}.tsv"
    headers = [
        "project",
        "topic",
        "bucket",
        "axis",
        "value",
        "tp",
        "fp",
        "fn",
        "tn",
        "recall",
        "precision",
        "f1",
        "wr",
        "nns",
        "specificity",
        "npv",
        "accuracy",
        "mcc",
        "wss95",
        "thresholds",
    ]
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(headers) + "\n")
        for row in rows:
            f.write("\t".join(row[h] for h in headers) + "\n")
    return output_path


def load_retrieved_jsonl(jsonl_file: Path) -> Set[str]:
    """从JSONL文件加载检索到的PMIDs"""
    pmids = set()
    with open(jsonl_file, "r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            pmid = obj["id"].replace("pubmed:", "")
            pmids.add(pmid)
    return pmids


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    """Compute a Wilson score interval for a binomial proportion."""
    if total <= 0:
        return 0.0, 0.0
    p_hat = successes / total
    z2 = z * z
    denominator = 1 + z2 / total
    center = (p_hat + z2 / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt((p_hat * (1 - p_hat) / total) + (z2 / (4 * total * total)))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def matthews_corrcoef(tp: int, fp: int, fn: int, tn: int) -> float:
    """Compute the Matthews correlation coefficient."""
    denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    if denominator == 0:
        return 0.0
    return ((tp * tn) - (fp * fn)) / denominator


def format_pct(value: float) -> str:
    return f"{value:.1%}"


def format_ratio(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.2f}"


def format_recall_ci(recall: float, ci_low: float, ci_high: float) -> str:
    return f"{format_pct(recall)} [{format_pct(ci_low)}, {format_pct(ci_high)}]"


def format_ci_display(value: float, ci_low: float, ci_high: float, *, ratio: bool = False) -> str:
    if ratio:
        return f"{format_ratio(value)} [{format_ratio(ci_low)}, {format_ratio(ci_high)}]"
    return f"{format_pct(value)} [{format_pct(ci_low)}, {format_pct(ci_high)}]"


def bootstrap_wr_nns_ci(
    *,
    tp: int,
    fp: int,
    fn: int,
    tn: int,
    n_boot: int = 4000,
    seed: int = 20260331,
    alpha: float = 0.05,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Bootstrap 95% CI for Workload Reduction and NNS from confusion counts."""
    total = tp + fp + fn + tn
    if total <= 0:
        return (0.0, 0.0), (0.0, 0.0)

    y_true = [1] * (tp + fn) + [0] * (fp + tn)
    y_pred = [1] * tp + [0] * fn + [1] * fp + [0] * tn
    pairs = list(zip(y_true, y_pred))

    rng = random.Random(seed)
    wr_samples: list[float] = []
    nns_samples: list[float] = []

    for _ in range(max(200, n_boot)):
        b_tp = b_fp = b_fn = b_tn = 0
        for _ in range(total):
            t, pred = pairs[rng.randrange(total)]
            if pred == 1 and t == 1:
                b_tp += 1
            elif pred == 1 and t == 0:
                b_fp += 1
            elif pred == 0 and t == 1:
                b_fn += 1
            else:
                b_tn += 1

        wr_samples.append((b_tn + b_fn) / total)
        if b_tp > 0:
            nns_samples.append((b_tp + b_fp) / b_tp)

    wr_samples.sort()
    nns_samples.sort()

    low_idx = max(0, int((alpha / 2) * len(wr_samples)) - 1)
    high_idx = min(len(wr_samples) - 1, int((1 - alpha / 2) * len(wr_samples)) - 1)
    wr_ci = (wr_samples[low_idx], wr_samples[high_idx])

    if not nns_samples:
        nns_ci = (math.nan, math.nan)
    else:
        n_low_idx = max(0, int((alpha / 2) * len(nns_samples)) - 1)
        n_high_idx = min(len(nns_samples) - 1, int((1 - alpha / 2) * len(nns_samples)) - 1)
        nns_ci = (nns_samples[n_low_idx], nns_samples[n_high_idx])

    return wr_ci, nns_ci


def render_paper_summary(summary: Dict[str, float | int | str]) -> None:
    """Render a compact CLI summary plus a copy-paste paper row."""
    headers = [
        "Topic",
        "#Project",
        "GT",
        "Pool",
        "TP",
        "FP",
        "FN",
        "TN",
        "Recall (95% CI)",
        "Precision (95% CI)",
        "Workload Reduction (95% CI)",
        "NNS (95% CI)",
        "Specificity",
        "NPV",
        "F1",
        "Accuracy",
        "MCC",
        "WSS@95",
    ]
    values = [
        str(summary["topic"]),
        str(summary["project_label"]),
        str(summary["ground_truth_count"]),
        str(summary["screened_count"]),
        str(summary["tp"]),
        str(summary["fp"]),
        str(summary["fn"]),
        str(summary["tn"]),
        str(summary["recall_ci_display"]),
        str(summary["precision_ci_display"]),
        str(summary["workload_reduction_ci_display"]),
        str(summary["nns_ci_display"]),
        str(summary["specificity_display"]),
        str(summary["npv_display"]),
        str(summary["f1_display"]),
        str(summary["accuracy_display"]),
        str(summary["mcc_display"]),
        str(summary["wss95_display"]),
    ]

    if HAS_RICH:
        overview = Table(title="Evaluation Summary", expand=False, show_header=True)
        overview.add_column("Field", style="cyan", no_wrap=True)
        overview.add_column("Value", style="white")
        for key, value in [
            ("Topic", summary["topic"]),
            ("#Project", summary["project_label"]),
            ("GT", summary["ground_truth_count"]),
            ("Pool", summary["screened_count"]),
            ("TP / FP / FN / TN", f"{summary['tp']} / {summary['fp']} / {summary['fn']} / {summary['tn']}"),
            ("Recall (95% CI)", summary["recall_ci_display"]),
            ("Precision (95% CI)", summary["precision_ci_display"]),
            ("Workload Reduction (95% CI)", summary["workload_reduction_ci_display"]),
            ("NNS (95% CI)", summary["nns_ci_display"]),
            ("Specificity", summary["specificity_display"]),
            ("NPV", summary["npv_display"]),
            ("F1", summary["f1_display"]),
            ("Accuracy", summary["accuracy_display"]),
            ("MCC", summary["mcc_display"]),
            ("WSS@95", summary["wss95_display"]),
        ]:
            overview.add_row(str(key), str(value))

        console.print(
            Panel.fit(
                f"[bold green]{summary['project_label']}[/bold green]  "
                f"[cyan]{summary['topic']}[/cyan]  "
                f"GT={summary['ground_truth_count']}  Pool={summary['screened_count']}",
                title="Evaluation Target",
            )
        )
        console.print(overview)
    else:
        print("\n" + "=" * 120)
        print("Paper-Ready Summary")
        print("=" * 120)
        print(f"Topic: {summary['topic']}")
        print(f"#Project: {summary['project_label']}")
        print(
            "Counts: "
            f"GT={summary['ground_truth_count']} Pool={summary['screened_count']} "
            f"TP={summary['tp']} FP={summary['fp']} FN={summary['fn']} TN={summary['tn']}"
        )
        print(
            "Metrics: "
            f"Recall={summary['recall_ci_display']} Precision={summary['precision_ci_display']} "
            f"WR={summary['workload_reduction_ci_display']} NNS={summary['nns_ci_display']} "
            f"Specificity={summary['specificity_display']} NPV={summary['npv_display']} "
            f"F1={summary['f1_display']} Accuracy={summary['accuracy_display']} "
            f"MCC={summary['mcc_display']} WSS@95={summary['wss95_display']}"
        )


def write_paper_summary_tsv(output_dir: Path, summary: Dict[str, float | int | str]) -> Path:
    """Write a copy-paste friendly TSV row for paper tables."""
    output_path = output_dir / "paper_summary.tsv"
    headers = [
        "Topic",
        "#Project",
        "GT",
        "Pool",
        "TP",
        "FP",
        "FN",
        "TN",
        "Recall (95% CI)",
        "Precision (95% CI)",
        "Workload Reduction (95% CI)",
        "NNS (95% CI)",
        "Specificity",
        "NPV",
        "F1",
        "Accuracy",
        "MCC",
        "WSS@95",
    ]
    values = [
        str(summary["topic"]),
        str(summary["project_label"]),
        str(summary["ground_truth_count"]),
        str(summary["screened_count"]),
        str(summary["tp"]),
        str(summary["fp"]),
        str(summary["fn"]),
        str(summary["tn"]),
        str(summary["recall_ci_display"]),
        str(summary["precision_ci_display"]),
        str(summary["workload_reduction_ci_display"]),
        str(summary["nns_ci_display"]),
        str(summary["specificity_display"]),
        str(summary["npv_display"]),
        str(summary["f1_display"]),
        str(summary["accuracy_display"]),
        str(summary["mcc_display"]),
        str(summary["wss95_display"]),
    ]
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(headers) + "\n")
        f.write("\t".join(values) + "\n")
    return output_path


def evaluate_search_coverage(
    ground_truth: Dict[str, Dict], search_results: Set[str]
) -> Dict[str, float | int]:
    """评估搜索策略对ground truth的覆盖率"""
    print("\n" + "=" * 100)
    print("Search coverage analysis")
    print("=" * 100)

    total_gt = len(ground_truth)
    found = set(ground_truth.keys()) & search_results
    not_found = set(ground_truth.keys()) - search_results

    coverage = len(found) / total_gt * 100 if total_gt > 0 else 0

    print(f"\nGround Truth总数: {total_gt} 篇")
    print(f"搜索结果总数: {len(search_results)} 篇")
    print(f"\nFound in search results: {len(found)} ({coverage:.1f}%)")
    print(
        f"Missing from search results: {len(not_found)} ({len(not_found)/total_gt*100:.1f}%)"
    )

    if not_found:
        print(f"\n\nGround-truth papers missing from search results:\n")
        print("=" * 100)
        for i, pmid in enumerate(sorted(not_found), 1):
            gt = ground_truth[pmid]
            print(f"[{i}] PMID: {pmid} | {gt['first_author']} ({gt['year']})")
            print(f"    变异株: {gt['variant_focus']}")
            print(f"    标题: {gt['title']}")
            print()

    return {
        "ground_truth_count": total_gt,
        "search_result_count": len(search_results),
        "found_count": len(found),
        "not_found_count": len(not_found),
        "coverage": round(coverage, 6),
    }


def meets_core_criteria(paper: Dict, threshold: int = 3) -> bool:
    """
    判断论文是否满足所有核心纳入标准

    Args:
        paper: 论文数据（包含5个维度评分）
        threshold: 每个维度的最低分数要求（默认3分=比较相关）

    Returns:
        True if 所有5个维度都 >= threshold
    """
    dimensions = [
        "disease_score",
        "population_score",
        "location_score",
        "evidence_score",
        "parameter_score",
    ]
    return all(paper.get(dim, 0) >= threshold for dim in dimensions)


def evaluate_screening_performance(
    ground_truth: Dict[str, Dict],
    screened: Dict[str, Dict],
    *,
    topic: str = "",
    project_label: str = "",
    threshold_overrides: Dict[str, Dict[str, int]] | None = None,
) -> Dict[str, float | int | str]:
    """评估LLM筛选效果（含混淆矩阵）"""
    applied_thresholds = None
    if threshold_overrides:
        screened, applied_thresholds = reclassify_screened_results(
            screened, threshold_overrides
        )

    # 分类ground truth
    strong = []
    possible = []
    unlikely = []
    not_found = []

    for pmid, gt in ground_truth.items():
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

    total_gt = len(ground_truth)
    combined_relevant = len(strong) + len(possible)

    screened_count = len(screened)

    # 非ground truth的分类
    non_gt_pmids = set(screened.keys()) - set(ground_truth.keys())
    FP_strong = sum(
        1
        for pmid in non_gt_pmids
        if screened[pmid]["llm_suggest"] == "strong_candidate"
    )
    FP_possible = sum(
        1
        for pmid in non_gt_pmids
        if screened[pmid]["llm_suggest"] == "possible_candidate"
    )
    TN = sum(
        1
        for pmid in non_gt_pmids
        if screened[pmid]["llm_suggest"] == "unlikely_candidate"
    )

    TP = combined_relevant  # Ground truth被正确识别为相关
    FN = len(unlikely) + len(not_found)  # Ground truth被错误标记为不相关
    FP = FP_strong + FP_possible  # 非GT被错误标记为相关

    # 性能指标
    sensitivity = TP / (TP + FN) if (TP + FN) > 0 else 0
    specificity = TN / (TN + FP) if (TN + FP) > 0 else 0
    precision = TP / (TP + FP) if (TP + FP) > 0 else 0
    npv = TN / (TN + FN) if (TN + FN) > 0 else 0
    f1 = (
        2 * (precision * sensitivity) / (precision + sensitivity)
        if (precision + sensitivity) > 0
        else 0
    )
    accuracy = (TP + TN) / (TP + TN + FP + FN) if (TP + TN + FP + FN) > 0 else 0
    workload_reduction = (TN + FN) / screened_count if screened_count > 0 else 0
    nns = (TP + FP) / TP if TP > 0 else math.inf
    mcc = matthews_corrcoef(TP, FP, FN, TN)
    wss95 = workload_reduction - 0.05
    recall_ci_low, recall_ci_high = wilson_interval(TP, TP + FN)
    precision_ci_low, precision_ci_high = wilson_interval(TP, TP + FP)
    (wr_ci_low, wr_ci_high), (nns_ci_low, nns_ci_high) = bootstrap_wr_nns_ci(
        tp=TP,
        fp=FP,
        fn=FN,
        tn=TN,
    )
    recall_ci_display = format_recall_ci(sensitivity, recall_ci_low, recall_ci_high)

    summary: Dict[str, float | int | str] = {
        "topic": topic or "unknown",
        "project_label": project_label or "N/A",
        "ground_truth_count": total_gt,
        "screened_count": screened_count,
        "tp": TP,
        "fp": FP,
        "fn": FN,
        "tn": TN,
        "strong_count": len(strong),
        "possible_count": len(possible),
        "unlikely_count": len(unlikely),
        "not_found_count": len(not_found),
        "sensitivity": round(sensitivity, 6),
        "specificity": round(specificity, 6),
        "precision": round(precision, 6),
        "npv": round(npv, 6),
        "f1": round(f1, 6),
        "accuracy": round(accuracy, 6),
        "workload_reduction": round(workload_reduction, 6),
        "nns": None if math.isinf(nns) else round(nns, 6),
        "mcc": round(mcc, 6),
        "wss95": round(wss95, 6),
        "recall_ci_low": round(recall_ci_low, 6),
        "recall_ci_high": round(recall_ci_high, 6),
        "precision_ci_low": round(precision_ci_low, 6),
        "precision_ci_high": round(precision_ci_high, 6),
        "workload_reduction_ci_low": round(wr_ci_low, 6),
        "workload_reduction_ci_high": round(wr_ci_high, 6),
        "nns_ci_low": None if math.isnan(nns_ci_low) else round(nns_ci_low, 6),
        "nns_ci_high": None if math.isnan(nns_ci_high) else round(nns_ci_high, 6),
        "recall_ci_display": recall_ci_display,
        "precision_display": format_pct(precision),
        "workload_reduction_display": format_pct(workload_reduction),
        "nns_display": format_ratio(nns),
        "precision_ci_display": format_ci_display(
            precision,
            precision_ci_low,
            precision_ci_high,
        ),
        "workload_reduction_ci_display": format_ci_display(
            workload_reduction,
            wr_ci_low,
            wr_ci_high,
        ),
        "nns_ci_display": (
            "inf"
            if math.isinf(nns)
            else format_ci_display(
                nns,
                nns if math.isnan(nns_ci_low) else nns_ci_low,
                nns if math.isnan(nns_ci_high) else nns_ci_high,
                ratio=True,
            )
        ),
        "specificity_display": format_pct(specificity),
        "npv_display": format_pct(npv),
        "f1_display": format_pct(f1),
        "accuracy_display": format_pct(accuracy),
        "mcc_display": f"{mcc:.3f}",
        "wss95_display": format_pct(wss95),
        "threshold_mode": "score_reclassified" if applied_thresholds else "original_labels",
        "threshold_overrides": json.dumps(applied_thresholds, ensure_ascii=False)
        if applied_thresholds
        else "",
    }

    render_paper_summary(summary)

    print("\n" + "=" * 100)
    print("LLM screening evaluation")
    print("=" * 100)
    if applied_thresholds:
        print(f"\nEvaluation thresholds override: {applied_thresholds}")
    print(
        f"\nGround-truth breakdown (GT={total_gt} | Pool={screened_count})\n"
    )
    print(f"┌─────────────────────────────┬─────────┬─────────┐")
    print(f"│ 类别                        │  数量   │  占比   │")
    print(f"├─────────────────────────────┼─────────┼─────────┤")
    if total_gt == 0:
        print("│ Strong candidates           │  0     │   0.0%  │")
        print("│ Possible candidates         │  0     │   0.0%  │")
        print("│ Unlikely candidates         │  0     │   0.0%  │")
        print("│ Missing                     │  0     │   0.0%  │")
    else:
        print(
            f"│ Strong candidates           │  {len(strong):4d}   │ {len(strong)/total_gt*100:5.1f}%  │"
        )
        print(
            f"│ Possible candidates         │  {len(possible):4d}   │ {len(possible)/total_gt*100:5.1f}%  │"
        )
        print(
            f"│ Unlikely candidates         │  {len(unlikely):4d}   │ {len(unlikely)/total_gt*100:5.1f}%  │"
        )
        print(
            f"│ Missing                     │  {len(not_found):4d}   │ {len(not_found)/total_gt*100:5.1f}%  │"
        )
    print(f"├─────────────────────────────┼─────────┼─────────┤")
    if total_gt == 0:
        print("│ Recall (S+P)                │  0     │   0.0%  │")
        print("│ Strong-only recall          │  0     │   0.0%  │")
    else:
        print(
            f"│ Recall (S+P)                │  {combined_relevant:4d}   │ {combined_relevant/total_gt*100:5.1f}%  │"
        )
        print(
            f"│ Strong-only recall          │  {len(strong):4d}   │ {len(strong)/total_gt*100:5.1f}%  │"
        )
    print(f"└─────────────────────────────┴─────────┴─────────┘")

    print(f"\n\nThree-class confusion matrix\n")
    print("混淆矩阵:")
    print(f"┌─────────────────────────┬──────────────────┬──────────────────┐")
    print(f"│                         │   实际相关(GT)   │   实际不相关     │")
    print(f"├─────────────────────────┼──────────────────┼──────────────────┤")
    print(
        f"│ Strong                 │      {len(strong):2d}          │      {FP_strong:2d}          │"
    )
    print(f"├─────────────────────────┼──────────────────┼──────────────────┤")
    print(
        f"│ Possible               │      {len(possible):2d}          │      {FP_possible:2d}          │"
    )
    print(f"├─────────────────────────┼──────────────────┼──────────────────┤")
    print(
        f"│ Unlikely               │      {len(unlikely)+len(not_found):2d}          │      {TN:2d}          │"
    )
    print(f"└─────────────────────────┴──────────────────┴──────────────────┘")

    print(f"\n\nBinary confusion matrix (Strong+Possible = relevant)\n")
    print(f"┌─────────────────────────┬──────────────────┬──────────────────┐")
    print(f"│                         │   实际相关(GT)   │   实际不相关     │")
    print(f"├─────────────────────────┼──────────────────┼──────────────────┤")
    print(
        f"│ 预测相关(S+P)           │   TP = {TP:2d}        │   FP = {FP:2d}        │"
    )
    print(f"├─────────────────────────┼──────────────────┼──────────────────┤")
    print(
        f"│ 预测不相关(Unlikely)    │   FN = {FN:2d}        │   TN = {TN:2d}        │"
    )
    print(f"└─────────────────────────┴──────────────────┴──────────────────┘")

    print(f"\nMetrics:")
    print(f"┌─────────────────────────────┬─────────┬─────────────────────────┐")
    print(f"│ 指标                        │  数值   │  计算公式               │")
    print(f"├─────────────────────────────┼─────────┼─────────────────────────┤")
    print(
        f"│ Recall                      │ {sensitivity:6.1%}  │ TP/(TP+FN) = {TP}/{TP+FN:2d}      │"
    )
    print(
        f"│ Specificity                 │ {specificity:6.1%}  │ TN/(TN+FP) = {TN}/{TN+FP:2d}      │"
    )
    print(
        f"│ Precision                   │ {precision:6.1%}  │ TP/(TP+FP) = {TP}/{TP+FP:2d}      │"
    )
    print(
        f"│ NPV                         │ {npv:6.1%}  │ TN/(TN+FN) = {TN}/{TN+FN:2d}      │"
    )
    print(f"│ F1-score                    │ {f1:6.1%}  │ 2×P×R/(P+R)             │")
    print(
        f"│ Accuracy                    │ {accuracy:6.1%}  │ (TP+TN)/Total = {TP+TN}/{TP+TN+FP+FN}   │"
    )
    print(
        f"│ Workload Reduction          │ {workload_reduction:6.1%}  │ (TN+FN)/Pool = {TN+FN}/{screened_count}   │"
    )
    print(
        f"│ NNS                         │ {format_ratio(nns):>6}  │ (TP+FP)/TP = {TP+FP}/{TP:2d}      │"
    )
    print(f"│ MCC                         │ {mcc:6.3f}  │ Matthews correlation    │")
    print(
        f"│ WSS@95                      │ {wss95:6.1%}  │ WR - 5%                  │"
    )
    print(
        f"│ Recall 95% CI               │ {format_pct(sensitivity):>6}  │ [{format_pct(recall_ci_low)}, {format_pct(recall_ci_high)}] │"
    )
    print(
        f"│ Precision 95% CI            │ {format_pct(precision):>6}  │ [{format_pct(precision_ci_low)}, {format_pct(precision_ci_high)}] │"
    )
    print(
        f"│ WR 95% CI (bootstrap)       │ {format_pct(workload_reduction):>6}  │ [{format_pct(wr_ci_low)}, {format_pct(wr_ci_high)}] │"
    )
    if math.isinf(nns):
        print("│ NNS 95% CI (bootstrap)      │    inf  │ [inf, inf]                 │")
    else:
        nns_low_text = format_ratio(nns if math.isnan(nns_ci_low) else nns_ci_low)
        nns_high_text = format_ratio(nns if math.isnan(nns_ci_high) else nns_ci_high)
        print(
            f"│ NNS 95% CI (bootstrap)      │ {format_ratio(nns):>6}  │ [{nns_low_text}, {nns_high_text}]            │"
        )
    print(f"└─────────────────────────────┴─────────┴─────────────────────────┘")

    return summary


def evaluate_retrieval_metrics(
    ground_truth_pmids: Set[str], retrieved_pmids: Set[str]
) -> Dict[str, float | int]:
    """评估检索结果的召回率和精确率"""
    print("\n" + "=" * 100)
    print("📊 检索指标分析")
    print("=" * 100)

    tp = len(ground_truth_pmids & retrieved_pmids)
    fp = len(retrieved_pmids - ground_truth_pmids)
    fn = len(ground_truth_pmids - retrieved_pmids)

    recall = tp / len(ground_truth_pmids) if len(ground_truth_pmids) > 0 else 0
    precision = tp / len(retrieved_pmids) if len(retrieved_pmids) > 0 else 0
    f1 = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0
    )

    print(f"\nGround Truth: {len(ground_truth_pmids)} 篇")
    print(f"检索结果: {len(retrieved_pmids)} 篇")
    print(f"\nTP (命中): {tp}")
    print(f"FP (误检): {fp}")
    print(f"FN (漏检): {fn}")
    print(f"\n📈 Recall (召回率): {recall:.1%}")
    print(f"💎 Precision (精确率): {precision:.1%}")
    print(f"🏆 F1-score: {f1:.1%}")

    return {
        "ground_truth_count": len(ground_truth_pmids),
        "retrieved_count": len(retrieved_pmids),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall": round(recall, 6),
        "precision": round(precision, 6),
        "f1": round(f1, 6),
    }


def main():
    parser = argparse.ArgumentParser(
        description="筛选结果评估工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # search-coverage
    search_parser = subparsers.add_parser("search-coverage", help="评估搜索覆盖率")
    search_parser.add_argument("--project-root", default="", help="仓库根目录；与 --profile 配合使用时自动解析 evaluation 路径")
    search_parser.add_argument("--profile", default="", help="实验 profile 名称，例如 P13")
    search_parser.add_argument("--topic", default="", help="可选 topic 覆盖；默认使用 profile 自带 topic")
    search_parser.add_argument(
        "--ground-truth", default="", help="Ground truth CSV文件"
    )
    search_parser.add_argument(
        "--search-results", default="", help="搜索结果CSV文件"
    )

    # screening-performance
    screen_parser = subparsers.add_parser("screening-performance", help="评估筛选效果")
    screen_parser.add_argument("--project-root", default="", help="仓库根目录；与 --profile 配合使用时自动解析 evaluation 路径")
    screen_parser.add_argument("--profile", default="", help="实验 profile 名称，例如 P13")
    screen_parser.add_argument("--topic", default="", help="可选 topic 覆盖；默认使用 profile 自带 topic")
    screen_parser.add_argument(
        "--ground-truth", default="", help="Ground truth CSV文件"
    )
    screen_parser.add_argument(
        "--screened-results", default="", help="筛选结果CSV文件"
    )
    screen_parser.add_argument("--strong-disease-min", type=int, default=None, help="evaluation时 strong 的 disease 最低分")
    screen_parser.add_argument("--strong-parameter-min", type=int, default=None, help="evaluation时 strong 的 parameter 最低分")
    screen_parser.add_argument("--strong-evidence-min", type=int, default=None, help="evaluation时 strong 的 evidence 最低分")
    screen_parser.add_argument("--strong-population-min", type=int, default=None, help="evaluation时 strong 的 population 最低分")
    screen_parser.add_argument("--strong-location-min", type=int, default=None, help="evaluation时 strong 的 location 最低分")
    screen_parser.add_argument("--possible-disease-min", type=int, default=None, help="evaluation时 possible 的 disease 最低分")
    screen_parser.add_argument("--possible-parameter-min", type=int, default=None, help="evaluation时 possible 的 parameter 最低分")
    screen_parser.add_argument("--possible-evidence-min", type=int, default=None, help="evaluation时 possible 的 evidence 最低分")
    screen_parser.add_argument("--possible-population-min", type=int, default=None, help="evaluation时 possible 的 population 最低分")
    screen_parser.add_argument("--possible-location-min", type=int, default=None, help="evaluation时 possible 的 location 最低分")

    # threshold-sweep
    sweep_parser = subparsers.add_parser("threshold-sweep", help="按单个阈值轴做 evaluation 敏感性分析")
    sweep_parser.add_argument("--project-root", default="", help="仓库根目录；与 --profile 配合使用时自动解析 evaluation 路径")
    sweep_parser.add_argument("--profile", default="", help="实验 profile 名称，例如 P7")
    sweep_parser.add_argument("--topic", default="", help="可选 topic 覆盖；默认使用 profile 自带 topic")
    sweep_parser.add_argument("--ground-truth", default="", help="Ground truth CSV文件")
    sweep_parser.add_argument("--screened-results", default="", help="筛选结果CSV文件")
    sweep_parser.add_argument("--bucket", choices=["strong", "possible"], default="possible", help="扫描 strong 还是 possible 阈值")
    sweep_parser.add_argument("--axis", choices=["disease", "parameter", "evidence", "population", "location"], required=True, help="扫描哪个维度阈值")
    sweep_parser.add_argument("--values", default="1,2,3,4", help="阈值列表，逗号分隔，例如 2,3,4")

    # retrieval-metrics
    retrieval_parser = subparsers.add_parser("retrieval-metrics", help="评估检索指标")
    retrieval_parser.add_argument(
        "--ground-truth", required=True, help="Ground truth CSV文件"
    )
    retrieval_parser.add_argument(
        "--retrieved-results", required=True, help="检索结果JSONL文件"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "search-coverage":
        if args.project_root and args.profile:
            _, paths = resolve_profile_paths(
                project_root=args.project_root,
                profile_name=args.profile,
                topic=args.topic or None,
            )
            gt_file = paths.ground_truth_file
            search_file = paths.raw_file
        else:
            if not args.ground_truth or not args.search_results:
                raise ValueError(
                    "search-coverage requires explicit files or --project-root/--profile."
                )
            gt_file = Path(args.ground_truth)
            search_file = Path(args.search_results)

        ground_truth = load_ground_truth_pmids(gt_file)
        search_results = load_search_results(search_file)

        summary = evaluate_search_coverage(ground_truth, search_results)
        manifest_path = write_run_manifest(
            output_dir=search_file.parent,
            workflow="search_coverage_evaluation",
            module="literature_search",
            params={
                "command": args.command,
                "profile": getattr(args, "profile", ""),
                "topic": getattr(args, "topic", ""),
            },
            inputs=[gt_file, search_file],
            outputs=[search_file.parent],
            extra={"summary": summary},
        )
        print(f"\nManifest: {manifest_path}")

    elif args.command == "screening-performance":
        if args.project_root and args.profile:
            profile, paths = resolve_profile_paths(
                project_root=args.project_root,
                profile_name=args.profile,
                topic=args.topic or None,
            )
            gt_file = paths.ground_truth_file
            screened_file = paths.screened_file
        else:
            if not args.ground_truth or not args.screened_results:
                raise ValueError(
                    "screening-performance requires explicit files or --project-root/--profile."
                )
            gt_file = Path(args.ground_truth)
            screened_file = Path(args.screened_results)
            profile = None

        ground_truth = load_ground_truth_pmids(gt_file)
        screened = load_screened_results(screened_file)
        threshold_overrides = build_threshold_overrides(args)

        summary = evaluate_screening_performance(
            ground_truth,
            screened,
            topic=(profile.topic if profile else (getattr(args, "topic", "") or "unknown")),
            project_label=(profile.profile_key if profile else "custom"),
            threshold_overrides=threshold_overrides,
        )
        paper_summary_path = write_paper_summary_tsv(screened_file.parent, summary)
        manifest_path = write_run_manifest(
            output_dir=screened_file.parent,
            workflow="screening_evaluation",
            module="literature_search",
            params={
                "command": args.command,
                "profile": getattr(args, "profile", ""),
                "topic": getattr(args, "topic", ""),
                "threshold_overrides": threshold_overrides or {},
            },
            inputs=[gt_file, screened_file],
            outputs=[screened_file.parent, paper_summary_path],
            extra={"summary": summary, "paper_summary_tsv": str(paper_summary_path)},
        )
        print(f"\nPaper summary TSV: {paper_summary_path}")
        print(f"\nManifest: {manifest_path}")

    elif args.command == "threshold-sweep":
        if args.project_root and args.profile:
            profile, paths = resolve_profile_paths(
                project_root=args.project_root,
                profile_name=args.profile,
                topic=args.topic or None,
            )
            gt_file = paths.ground_truth_file
            screened_file = paths.screened_file
        else:
            if not args.ground_truth or not args.screened_results:
                raise ValueError(
                    "threshold-sweep requires explicit files or --project-root/--profile."
                )
            gt_file = Path(args.ground_truth)
            screened_file = Path(args.screened_results)
            profile = None

        values = [int(part.strip()) for part in str(args.values).split(",") if part.strip()]
        if not values:
            raise ValueError("--values must include at least one integer")

        ground_truth = load_ground_truth_pmids(gt_file)
        screened = load_screened_results(screened_file)
        rows = threshold_sweep(
            ground_truth,
            screened,
            axis=args.axis,
            values=values,
            bucket=args.bucket,
            topic=(profile.topic if profile else (getattr(args, "topic", "") or "unknown")),
            project_label=(profile.profile_key if profile else "custom"),
        )
        sweep_path = write_threshold_sweep_tsv(
            screened_file.parent,
            rows,
            axis=args.axis,
            bucket=args.bucket,
        )
        manifest_path = write_run_manifest(
            output_dir=screened_file.parent,
            workflow="screening_threshold_sweep",
            module="literature_search",
            params={
                "command": args.command,
                "profile": getattr(args, "profile", ""),
                "topic": getattr(args, "topic", ""),
                "bucket": args.bucket,
                "axis": args.axis,
                "values": values,
            },
            inputs=[gt_file, screened_file],
            outputs=[screened_file.parent, sweep_path],
            extra={"rows": rows, "threshold_sweep_tsv": str(sweep_path)},
        )
        print(f"\nThreshold sweep TSV: {sweep_path}")
        print(f"\nManifest: {manifest_path}")

    elif args.command == "retrieval-metrics":
        gt_file = Path(args.ground_truth)
        retrieved_file = Path(args.retrieved_results)

        ground_truth = load_ground_truth_pmids(gt_file)
        retrieved = load_retrieved_jsonl(retrieved_file)

        summary = evaluate_retrieval_metrics(set(ground_truth.keys()), retrieved)
        manifest_path = write_run_manifest(
            output_dir=retrieved_file.parent,
            workflow="retrieval_evaluation",
            module="literature_search",
            params={"command": args.command},
            inputs=[gt_file, retrieved_file],
            outputs=[retrieved_file.parent],
            extra={"summary": summary},
        )
        print(f"\nManifest: {manifest_path}")


if __name__ == "__main__":
    main()
