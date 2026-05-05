from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
LIT_SEARCH_SRC = ROOT
if str(LIT_SEARCH_SRC) not in sys.path:
    sys.path.insert(0, str(LIT_SEARCH_SRC))

from metaagent.screening.dashboard_data import (  # type: ignore
    discover_screening_runs,
    load_screened_dataframe,
    load_text_preview,
    summarize_dataframe,
)


def list_runs(root: Path) -> list[dict[str, Any]]:
    runs = discover_screening_runs(root)
    return [_to_summary(run) for run in runs]


def get_run(root: Path, run_id: str) -> dict[str, Any] | None:
    selected = _find_run(root, run_id)
    if not selected:
        return None

    df = load_screened_dataframe(selected.get("screened_csv"))
    summary = summarize_dataframe(df)
    confusion = _compute_confusion_matrix(df)

    return {
        "run": {**selected, "id": _run_id(selected)},
        "metrics": [
            {"label": "Pool", "value": int(summary["pool"])},
            {"label": "GT in Pool", "value": int(summary["gt_in_pool"])},
            {"label": "Strong", "value": int(_count_matching(summary["decision_counts"], "strong"))},
            {"label": "Possible", "value": int(_count_matching(summary["decision_counts"], "possible"))},
            {"label": "Unlikely", "value": int(_count_matching(summary["decision_counts"], "unlikely"))},
            {"label": "Full-text Errors", "value": int(_count_matching(summary["fulltext_counts"], "error"))},
        ],
        "decision_counts": _series_to_counts(summary["decision_counts"]),
        "stage_counts": _series_to_counts(summary["stage_counts"]),
        "fulltext_counts": _series_to_counts(summary["fulltext_counts"]),
        "confusion_matrix": confusion,
        "report_preview": load_text_preview(selected.get("report_path")),
    }


def get_run_papers(root: Path, run_id: str) -> dict[str, Any] | None:
    selected = _find_run(root, run_id)
    if not selected:
        return None

    df = load_screened_dataframe(selected.get("screened_csv"))
    papers = []
    if not df.empty:
        papers = json.loads(df.fillna("").to_json(orient="records", force_ascii=False))
    return {
        "run_id": run_id,
        "count": len(papers),
        "papers": papers,
    }


def _to_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _run_id(run),
        "label": run.get("label"),
        "module": "screening",
        "topic": run.get("topic"),
        "config": run.get("config"),
        "timestamp_utc": run.get("timestamp_utc"),
        "status": "ready",
        "screened_csv": run.get("screened_csv"),
        "manifest_path": run.get("manifest_path"),
    }


def _find_run(root: Path, run_id: str) -> dict[str, Any] | None:
    runs = discover_screening_runs(root)
    return next((run for run in runs if _run_id(run) == run_id), None)


def _series_to_counts(series) -> list[dict[str, Any]]:
    if getattr(series, "empty", True):
        return []
    return [
        {"label": str(label), "count": int(count)}
        for label, count in series.items()
    ]


def _count_matching(series, needle: str) -> int:
    if getattr(series, "empty", True):
        return 0
    total = 0
    for label, count in series.items():
        if needle in str(label).strip().lower():
            total += int(count)
    return total


def _run_id(run: dict[str, Any]) -> str:
    source = (
        run.get("manifest_path")
        or run.get("screened_csv")
        or run.get("label")
        or "screening"
    )
    return hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:12]


def _compute_confusion_matrix(df) -> dict[str, Any]:
    if getattr(df, "empty", True):
        return {
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "tn": 0,
            "recall": 0.0,
            "precision": 0.0,
            "specificity": 0.0,
            "accuracy": 0.0,
        }

    gt_mask = df.apply(_is_ground_truth_row, axis=1)
    pred_mask = df.apply(_is_predicted_relevant_row, axis=1)

    tp = int((gt_mask & pred_mask).sum())
    fp = int((~gt_mask & pred_mask).sum())
    fn = int((gt_mask & ~pred_mask).sum())
    tn = int((~gt_mask & ~pred_mask).sum())

    recall = _safe_ratio(tp, tp + fn)
    precision = _safe_ratio(tp, tp + fp)
    specificity = _safe_ratio(tn, tn + fp)
    accuracy = _safe_ratio(tp + tn, tp + fp + fn + tn)

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "recall": recall,
        "precision": precision,
        "specificity": specificity,
        "accuracy": accuracy,
    }


def _is_ground_truth_row(row) -> bool:
    for key in ("is_ground_truth", "ground_truth", "gt"):
        value = row.get(key)
        if _truthy_gt(value):
            return True
    return False


def _truthy_gt(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"✓", "gt", "true", "1", "yes", "y"}


def _is_predicted_relevant_row(row) -> bool:
    suggest = str(row.get("llm_suggest") or "").strip().lower()
    if not suggest:
        return False
    return ("strong" in suggest) or ("possible" in suggest)


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
