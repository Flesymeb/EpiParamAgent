"""Shared runtime configuration management for MetaAgent-Epi.

Preferred rules:
1. Shared defaults live in ``dev/.env`` and shared machine-local secrets in
   ``dev/.env.local``.
2. Module-specific differences should live in ``dev/<module>/.env.local``.
3. ``dev/<module>/.env`` is still supported for backward compatibility, but new
   setups should prefer module-local ``.env.local`` instead.
4. Callers should pass ``module_hint`` so one workflow does not accidentally
   load another workflow's env file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


_DOTENV_LOADED: set[str] = set()
_VALID_MODULE_HINTS = {"literature_search", "coding_sheet"}


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_module_hint(module_hint: Optional[str]) -> Optional[str]:
    if not module_hint:
        return None
    normalized = str(module_hint).strip().lower()
    if normalized not in _VALID_MODULE_HINTS:
        raise ValueError(
            f"Unsupported module_hint={module_hint!r}. "
            f"Expected one of: {sorted(_VALID_MODULE_HINTS)}"
        )
    return normalized


def _iter_env_candidates(module_hint: Optional[str]) -> Iterable[Path]:
    dev_root = get_project_root()
    yield dev_root
    normalized = _normalize_module_hint(module_hint)
    if normalized:
        yield dev_root / normalized


def load_runtime_env(module_hint: Optional[str] = None) -> None:
    """Load shared env first, then optional module-specific overrides."""
    normalized = _normalize_module_hint(module_hint)
    cache_key = normalized or "__shared__"
    if cache_key in _DOTENV_LOADED:
        return

    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        _DOTENV_LOADED.add(cache_key)
        return

    candidates = list(_iter_env_candidates(normalized))
    for idx, root in enumerate(candidates):
        is_shared = idx == 0
        if (root / ".env").exists():
            load_dotenv(root / ".env", override=not is_shared)
        if (root / ".env.local").exists():
            load_dotenv(root / ".env.local", override=True)

    _DOTENV_LOADED.add(cache_key)


def apply_langsmith_env(module_hint: Optional[str] = None) -> None:
    """Mirror LangSmith vars into LangChain-compatible env vars."""
    load_runtime_env(module_hint=module_hint)
    if os.getenv("LANGSMITH_API_KEY") and not os.getenv("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGSMITH_API_KEY", "")
    if os.getenv("LANGSMITH_PROJECT") and not os.getenv("LANGCHAIN_PROJECT"):
        os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "")
    if os.getenv("LANGSMITH_TRACING_V2") and not os.getenv("LANGCHAIN_TRACING_V2"):
        os.environ["LANGCHAIN_TRACING_V2"] = os.getenv("LANGSMITH_TRACING_V2", "")
    elif not os.getenv("LANGCHAIN_TRACING_V2"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ.setdefault("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")


@dataclass
class LLMConfig:
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    timeout_s: int = 120
    max_tokens: int = 32000
    temperature: float = 0.1
    verify_ssl: bool = True
    force_streaming: bool = False


@dataclass
class MineruConfig:
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    endpoint: str = "/api/v4/extract/task"
    timeout_s: int = 180
    no_proxy: bool = False
    retry_attempts: int = 3
    retry_base_delay_s: float = 1.0


def load_llm_config(
    params: Optional[dict[str, Any]] = None,
    *,
    module_hint: Optional[str] = None,
) -> LLMConfig:
    load_runtime_env(module_hint=module_hint)
    params = params or {}

    provider = (
        _strip_inline_comment(
            (params.get("llm_provider") or os.getenv("LLM_PROVIDER") or "").strip()
        )
        or None
    )
    model = (
        _strip_inline_comment(
            (params.get("llm_model") or os.getenv("LLM_MODEL") or "").strip()
        )
        or None
    )
    api_key = (
        params.get("llm_api_key")
        or os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
    )
    api_base = _strip_inline_comment(
        (
            params.get("llm_api_base")
            or os.getenv("LLM_API_BASE")
            or os.getenv("OPENAI_API_BASE")
            or os.getenv("ANTHROPIC_API_BASE")
            or ""
        ).strip()
    )
    if not api_base:
        api_base = None

    default_max_tokens = LLMConfig().max_tokens
    max_tokens = _safe_int(params.get("llm_max_tokens") or os.getenv("LLM_MAX_TOKENS"))
    if max_tokens is None:
        max_tokens = default_max_tokens

    timeout_s = _safe_int(params.get("llm_timeout_s") or os.getenv("LLM_TIMEOUT_S"))
    if timeout_s is None:
        timeout_s = LLMConfig().timeout_s

    temperature = _safe_float(
        params.get("llm_temperature") or os.getenv("LLM_TEMPERATURE") or 0.1
    )
    verify_ssl = _safe_bool(
        params.get("llm_verify_ssl") or os.getenv("LLM_VERIFY_SSL")
    )
    force_streaming = _safe_bool(
        params.get("llm_force_streaming") or os.getenv("LLM_FORCE_STREAMING") or False
    )

    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        timeout_s=timeout_s,
        max_tokens=max_tokens,
        temperature=temperature,
        verify_ssl=verify_ssl,
        force_streaming=force_streaming,
    )


def load_mineru_config(
    params: Optional[dict[str, Any]] = None,
    *,
    module_hint: Optional[str] = None,
) -> MineruConfig:
    load_runtime_env(module_hint=module_hint)
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
    no_proxy = _safe_bool(
        params.get("mineru_no_proxy") or os.getenv("MINERU_NO_PROXY") or False
    )
    retry_attempts = (
        _safe_int(params.get("mineru_retry_attempts") or os.getenv("MINERU_RETRY_ATTEMPTS"))
        or 3
    )
    retry_base_delay_s = (
        _safe_float(params.get("mineru_retry_base_delay_s") or os.getenv("MINERU_RETRY_BASE_DELAY_S") or 1.0)
        or 1.0
    )

    return MineruConfig(
        base_url=base_url,
        api_key=api_key,
        endpoint=endpoint,
        timeout_s=timeout_s,
        no_proxy=no_proxy,
        retry_attempts=retry_attempts,
        retry_base_delay_s=retry_base_delay_s,
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


def _safe_bool(val) -> bool:
    if val is None:
        return True
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    text = str(val).strip().lower()
    if text in {"0", "false", "no", "off"}:
        return False
    if text in {"1", "true", "yes", "on"}:
        return True
    return True


def _strip_inline_comment(val: str) -> str:
    if not val:
        return val
    if "#" in val:
        parts = val.split("#", 1)
        if parts[0].strip():
            return parts[0].strip()
    return val.strip()
