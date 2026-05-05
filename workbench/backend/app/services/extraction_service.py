from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def list_runs(root: Path) -> list[dict[str, Any]]:
    manifests = sorted(root.rglob("run_manifest_coding_sheet_extraction_*.json"), reverse=True)
    return [_to_summary(path) for path in manifests]


def get_run(root: Path, run_id: str) -> dict[str, Any] | None:
    manifests = sorted(root.rglob("run_manifest_coding_sheet_extraction_*.json"), reverse=True)
    selected = None
    payload = None
    for path in manifests:
        current_payload = _read_json(path)
        current_id = _manifest_id(path)
        if current_id == run_id:
            selected = path
            payload = current_payload
            break
    if not selected or payload is None:
        return None

    extra = payload.get("extra") or {}
    return {
        "run": {
            "id": _manifest_id(selected),
            "label": _build_label(payload, selected),
            "module": "coding_sheet",
            "timestamp_utc": payload.get("timestamp_utc"),
            "stage": (payload.get("params") or {}).get("stage"),
            "manifest_path": str(selected),
            "workflow": payload.get("workflow"),
            "codebook": (payload.get("params") or {}).get("codebook"),
            "run": payload,
        },
        "metrics": [
            {"label": "Input Papers", "value": int(extra.get("input_paper_count", 0))},
            {"label": "Records", "value": int(extra.get("record_count", 0))},
        ],
        "outputs": payload.get("outputs") or [],
    }


def _to_summary(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    params = payload.get("params") or {}
    return {
        "id": _manifest_id(path),
        "label": _build_label(payload, path),
        "module": "coding_sheet",
        "topic": None,
        "config": params.get("stage"),
        "timestamp_utc": payload.get("timestamp_utc"),
        "status": "ready",
        "screened_csv": None,
        "manifest_path": str(path),
    }


def _build_label(payload: dict[str, Any], path: Path) -> str:
    ts = (payload.get("timestamp_utc") or "")[:19].replace("T", " ")
    params = payload.get("params") or {}
    stage = params.get("stage") or "-"
    return f"{ts} | extraction | {stage} | {path.name}"


def _manifest_id(path: Path) -> str:
    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
