from __future__ import annotations

import json
import re
from typing import Any


def parse_json_records(text: str) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return []

    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline > 0:
            closing = text.rfind("```")
            if closing > first_newline:
                text = text[first_newline + 1 : closing].strip()

    try:
        data = json.loads(text)
        return _normalize(data)
    except Exception:
        pass

    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        try:
            data = json.loads(m.group(1))
            return _normalize(data)
        except Exception:
            pass

    m = re.search(r"\[.*\]|\{.*\}", text, flags=re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            return _normalize(data)
        except Exception:
            pass

    return []


def _normalize(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in (
            "records",
            "record",
            "items",
            "item",
            "data",
            "results",
            "output",
            "index",
        ):
            v = data.get(key) if isinstance(data, dict) else None
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                return [v]
        return [data]
    return []
