from __future__ import annotations

import json
import re
from typing import Any


def parse_json_records(text: str) -> list[dict[str, Any]]:
    """Parse LLM output into a list of dicts.

    Supports:
    - raw JSON array
    - JSON wrapped in ```json code blocks
    - a single JSON object
    """
    text = (text or "").strip()

    if not text:
        return []

    # Remove common markdown code block wrappers
    # Handle ```json\n...\n``` or ```\n...\n```
    if text.startswith("```"):
        # Find first newline after opening ```
        first_newline = text.find("\n")
        if first_newline > 0:
            # Find closing ```
            closing = text.rfind("```")
            if closing > first_newline:
                text = text[first_newline + 1 : closing].strip()

    # Direct JSON
    try:
        data = json.loads(text)
        return _normalize(data)
    except Exception:
        pass

    # Code block JSON (fallback regex)
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        try:
            data = json.loads(m.group(1))
            return _normalize(data)
        except Exception:
            pass

    # First JSON object/array substring
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
        # Common wrapper patterns: {"records": [...]}, {"data": [...]}, etc.
        for key in ("records", "record", "items", "item", "data", "results", "output"):
            v = data.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                return [v]
        return [data]
    return []
