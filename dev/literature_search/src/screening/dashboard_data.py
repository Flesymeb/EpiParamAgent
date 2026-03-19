"""Data loading helpers for the screening Streamlit dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

TOPIC_NAMES = {"serial_interval", "reproduction_number", "fatality"}


def discover_screening_runs(root: Path) -> list[dict[str, Any]]:
    """Discover screening manifests under a root directory."""
    root = Path(root)
    manifests = sorted(root.rglob("run_manifest_screening_*.json"), reverse=True)
    runs: list[dict[str, Any]] = []
    seen_outputs: set[str] = set()
    for manifest_path in manifests:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        record = _normalize_run_record(manifest_path, payload)
        if record.get("screened_csv"):
            seen_outputs.add(str(Path(record["screened_csv"]).resolve()))
        runs.append(record)

    for csv_path in sorted(root.rglob("*screened*.csv"), reverse=True):
        resolved = str(csv_path.resolve())
        if resolved in seen_outputs:
            continue
        runs.append(_build_legacy_run_record(csv_path))

    return sorted(runs, key=lambda item: item.get("timestamp_utc") or "", reverse=True)


def load_screened_dataframe(csv_path: str | Path | None) -> pd.DataFrame:
    """Load screened CSV if available."""
    if not csv_path:
        return pd.DataFrame()
    path = Path(csv_path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def load_text_preview(path_like: str | Path | None, max_chars: int = 4000) -> str:
    """Load a short preview from a text file."""
    if not path_like:
        return ""
    path = Path(path_like)
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
        return text[:max_chars]
    except Exception:
        return ""


def summarize_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Compute chart-friendly summaries from screened output."""
    if df.empty:
        return {
            "pool": 0,
            "gt_in_pool": 0,
            "decision_counts": pd.Series(dtype="int64"),
            "stage_counts": pd.Series(dtype="int64"),
            "fulltext_counts": pd.Series(dtype="int64"),
        }

    gt_col = "is_ground_truth" if "is_ground_truth" in df.columns else None
    gt_in_pool = int((df[gt_col] == "✓").sum()) if gt_col else 0
    decision_counts = (
        df["llm_suggest"].fillna("missing").value_counts()
        if "llm_suggest" in df.columns
        else pd.Series(dtype="int64")
    )
    stage_counts = (
        df["screening_stage"].fillna("missing").value_counts()
        if "screening_stage" in df.columns
        else pd.Series(dtype="int64")
    )
    fulltext_counts = (
        df["fulltext_status"].fillna("missing").value_counts()
        if "fulltext_status" in df.columns
        else pd.Series(dtype="int64")
    )
    return {
        "pool": int(len(df)),
        "gt_in_pool": gt_in_pool,
        "decision_counts": decision_counts,
        "stage_counts": stage_counts,
        "fulltext_counts": fulltext_counts,
    }


def filter_papers(
    df: pd.DataFrame,
    *,
    suggestions: list[str] | None = None,
    only_gt: bool = False,
    query: str = "",
) -> pd.DataFrame:
    """Apply interactive dashboard filters to paper rows."""
    if df.empty:
        return df

    filtered = df.copy()
    if suggestions and "llm_suggest" in filtered.columns:
        filtered = filtered[filtered["llm_suggest"].isin(suggestions)]
    if only_gt and "is_ground_truth" in filtered.columns:
        filtered = filtered[filtered["is_ground_truth"] == "✓"]
    if query:
        needle = query.lower().strip()
        title_series = filtered.get("Title", "").fillna("").astype(str).str.lower()
        pmid_series = filtered.get("PMID", "").fillna("").astype(str).str.lower()
        filtered = filtered[title_series.str.contains(needle) | pmid_series.str.contains(needle)]
    return filtered


def _normalize_run_record(
    manifest_path: Path, payload: dict[str, Any]
) -> dict[str, Any]:
    outputs = payload.get("outputs") or []
    inputs = payload.get("inputs") or []
    screened_csv = _pick_output(outputs, ".csv", contains="screened")
    report_path = _pick_output(outputs, ".txt", contains="screening_report")
    topic = _infer_topic(screened_csv or report_path or manifest_path)
    params = payload.get("params") or {}
    extra = payload.get("extra") or {}
    label = _build_label(payload, topic, screened_csv)
    return {
        "label": label,
        "timestamp_utc": payload.get("timestamp_utc"),
        "workflow": payload.get("workflow"),
        "module": payload.get("module"),
        "topic": topic,
        "config": params.get("config"),
        "manifest_path": str(manifest_path),
        "screened_csv": screened_csv,
        "report_path": report_path,
        "inputs": inputs,
        "outputs": outputs,
        "params": params,
        "runtime": payload.get("runtime") or {},
        "extra": extra,
        "git": payload.get("git") or {},
    }


def _build_legacy_run_record(csv_path: Path) -> dict[str, Any]:
    topic = _infer_topic(csv_path)
    report_path = _find_nearest_report(csv_path)
    timestamp = csv_path.stat().st_mtime
    ts = pd.Timestamp(timestamp, unit="s", tz="UTC").isoformat()
    return {
        "label": f"{ts[:19].replace('T', ' ')} | {topic} | legacy | {csv_path.name}",
        "timestamp_utc": ts,
        "workflow": "screening",
        "module": "literature_search",
        "topic": topic,
        "config": None,
        "manifest_path": None,
        "screened_csv": str(csv_path),
        "report_path": str(report_path) if report_path else None,
        "inputs": [],
        "outputs": [{"path": str(csv_path), "exists": True}],
        "params": {},
        "runtime": {},
        "extra": {},
        "git": {},
    }


def _pick_output(
    outputs: list[dict[str, Any]], suffix: str, contains: str | None = None
) -> str | None:
    for item in outputs:
        path = item.get("path")
        if not path:
            continue
        if Path(path).suffix.lower() != suffix.lower():
            continue
        if contains and contains not in Path(path).name:
            continue
        return path
    return None


def _infer_topic(path_like: str | Path | None) -> str:
    if not path_like:
        return "unknown"
    path = Path(path_like)
    for part in path.parts:
        if part in TOPIC_NAMES:
            return part
    return "unknown"


def _build_label(
    payload: dict[str, Any], topic: str, screened_csv: str | None
) -> str:
    ts = payload.get("timestamp_utc", "")[:19].replace("T", " ")
    params = payload.get("params") or {}
    config = params.get("config") or "-"
    output_name = Path(screened_csv).name if screened_csv else "no-output"
    return f"{ts} | {topic} | {config} | {output_name}"


def _find_nearest_report(csv_path: Path) -> Path | None:
    log_dir = csv_path.parent / "screening_logs"
    if not log_dir.exists():
        return None
    reports = sorted(log_dir.glob("screening_report_*.txt"), reverse=True)
    return reports[0] if reports else None
