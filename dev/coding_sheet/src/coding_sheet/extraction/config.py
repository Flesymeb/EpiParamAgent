from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    """Load dotenv files for this module.

    Load order:
    1) .env (no override)
    2) .env.local (override)

    This lets you keep shared defaults in `.env` and machine secrets/overrides in
    `.env.local`.
    """

    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return

    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        _DOTENV_LOADED = True
        return

    # project root = .../dev/coding_sheet
    root = Path(__file__).resolve().parents[3]

    load_dotenv(root / ".env", override=False)
    load_dotenv(root / ".env.local", override=True)

    _DOTENV_LOADED = True


@dataclass
class LLMConfig:
    provider: Optional[str] = None  # "openai" | "anthropic"
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    max_tokens: int = (
        32000  # Conservative default; override via LLM_MAX_TOKENS in .env for larger models
    )
    temperature: float = 0.1


@dataclass
class MineruConfig:
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    endpoint: str = "/api/v4/extract/task"
    timeout_s: int = 180


def load_llm_config(params: Optional[dict[str, Any]] = None) -> LLMConfig:
    _load_dotenv_once()
    params = params or {}

    provider = (
        params.get("llm_provider") or os.getenv("LLM_PROVIDER") or ""
    ).strip() or None
    model = (params.get("llm_model") or os.getenv("LLM_MODEL") or "").strip() or None
    api_key = (
        params.get("llm_api_key")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("LLM_API_KEY")
    )
    api_base = (
        params.get("llm_api_base")
        or os.getenv("LLM_API_BASE")
        or os.getenv("OPENAI_API_BASE")
    )

    # Default to the dataclass default unless explicitly overridden.
    # Using an extremely large default here tends to trigger provider-side limits (e.g., OpenRouter 402).
    default_max_tokens = LLMConfig().max_tokens
    max_tokens = _safe_int(params.get("llm_max_tokens") or os.getenv("LLM_MAX_TOKENS"))
    if max_tokens is None:
        max_tokens = default_max_tokens
    temperature = _safe_float(
        params.get("llm_temperature") or os.getenv("LLM_TEMPERATURE") or 0.1
    )

    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def load_mineru_config(params: Optional[dict[str, Any]] = None) -> MineruConfig:
    """Load MinerU API config.

    Env vars:
    - MINERU_BASE_URL: base URL, e.g. https://mineru.net
    - MINERU_API_KEY: bearer token
    - MINERU_ENDPOINT: path, default /api/v4/extract/task
    - MINERU_TIMEOUT_S: request timeout seconds
    """

    _load_dotenv_once()
    params = params or {}

    base_url = (
        params.get("mineru_base_url") or os.getenv("MINERU_BASE_URL") or ""
    ).strip() or None
    if not base_url:
        base_url = "https://mineru.net"
    api_key = (
        params.get("mineru_api_key") or os.getenv("MINERU_API_KEY") or ""
    ).strip() or None
    endpoint = (
        params.get("mineru_endpoint") or os.getenv("MINERU_ENDPOINT") or ""
    ).strip() or "/api/v4/extract/task"
    timeout_s = (
        _safe_int(params.get("mineru_timeout_s") or os.getenv("MINERU_TIMEOUT_S"))
        or 180
    )

    return MineruConfig(
        base_url=base_url,
        api_key=api_key,
        endpoint=endpoint,
        timeout_s=timeout_s,
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
