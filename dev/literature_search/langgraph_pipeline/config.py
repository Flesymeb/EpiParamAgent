"""Lightweight config loader for the LangGraph experiment.

Reads from env or params; keeps dependencies minimal. If an LLM model is
not available, callers should gracefully fall back.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class LLMConfig:
    provider: Optional[str] = None  # e.g., "openai", "anthropic"
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None  # e.g., OpenRouter base URL
    max_tokens: Optional[int] = None
    temperature: float = 0.0


def load_llm_config(params: Dict[str, Any]) -> LLMConfig:
    """Load LLM config from params first, then env."""
    return LLMConfig(
        provider=params.get("llm_provider") or os.getenv("LLM_PROVIDER"),
        model=params.get("llm_model") or os.getenv("LLM_MODEL"),
        api_key=params.get("llm_api_key")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("LLM_API_KEY"),
        api_base=params.get("llm_api_base")
        or os.getenv("LLM_API_BASE")
        or os.getenv("OPENAI_API_BASE"),
        max_tokens=_safe_int(
            params.get("llm_max_tokens") or os.getenv("LLM_MAX_TOKENS")
        ),
        temperature=_safe_float(
            params.get("llm_temperature") or os.getenv("LLM_TEMPERATURE") or 0.0
        ),
    )


def _safe_int(val) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except Exception:
        return None


def _safe_float(val) -> float:
    try:
        return float(val)
    except Exception:
        return 0.0
