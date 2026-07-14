"""Shared runtime configuration management for MetaAgent-Epi.


Preferred rules:
1. All configuration lives in ``.env.local`` at the project root.
2. Module-specific values use root-level prefixes such as
   ``QUERY_LLM_MODEL``, ``SCREENING_LLM_MODEL``, or ``CODING_LLM_MODEL``.
3. Callers should pass ``module_hint`` so each workflow can select the right
   root-level module prefix without hidden module-local env files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional


_DOTENV_LOADED: set[str] = set()
_VALID_MODULE_HINTS = {"query", "screening", "coding"}
_PROVIDER_ALIASES = {
    "lab1": "lab",
    "lab-1": "lab",
    "lab-api": "lab",
    "lab2": "lab2",
    "lab-2": "lab2",
    "lab-api-2": "lab2",
    "lab-dsv3": "lab2",
    "dsv3": "lab2",
    "deepseek-v3": "lab2",
    "deepseekv3": "lab2",
    "open-router": "openrouter",
}
_PROVIDER_ENV_SPECS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "base_vars": ("OPENROUTER_BASE_URL", "OPENROUTER_API_BASE"),
        "key_vars": ("OPENROUTER_API_KEY",),
        "model_vars": ("OPENROUTER_MODEL",),
        "default_base": "https://openrouter.ai/api/v1",
    },
    "openai": {
        "base_vars": ("OPENAI_BASE_URL", "OPENAI_API_BASE"),
        "key_vars": ("OPENAI_API_KEY",),
        "model_vars": ("OPENAI_MODEL",),
        "default_base": "https://api.openai.com/v1",
    },
    "lab": {
        "base_vars": ("LAB_BASE_URL", "LAB_API_BASE", "LAB1_BASE_URL", "LAB1_API_BASE"),
        "key_vars": ("LAB_API_KEY",),
        "model_vars": ("LAB_MODEL", "LAB1_MODEL"),
    },
    "lab2": {
        "base_vars": ("LAB_BASE_URL_2", "LAB_API_BASE_2", "LAB2_BASE_URL", "LAB2_API_BASE"),
        "key_vars": ("LAB_API_KEY_2", "LAB2_API_KEY"),
        "model_vars": ("LAB_MODEL_2", "LAB2_MODEL"),
    },
}


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


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


def load_runtime_env(module_hint: Optional[str] = None) -> None:
    """Load root env files only.

    Module-specific settings should live in the project-root env file with
    prefixes such as QUERY_LLM_MODEL, SCREENING_LLM_MODEL, and
    CODING_LLM_MODEL.
    """
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
    api_key: Optional[str] = field(default=None, repr=False)
    api_base: Optional[str] = None
    timeout_s: int = 120
    max_tokens: int = 32000
    temperature: float = 0.1
    verify_ssl: bool = True
    force_streaming: bool = False
    reasoning_effort: Optional[str] = None


@dataclass
class MineruConfig:
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    endpoint: str = "/api/v4/extract/task"
    timeout_s: int = 180
    no_proxy: bool = False
    retry_attempts: int = 3
    retry_base_delay_s: float = 1.0


def is_usable_secret(value: str | None) -> bool:
    """Return whether a credential is non-empty and not an example placeholder."""
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.casefold()
    placeholders = ("replace_", "your_", "example", "changeme", "<", ">")
    return not any(marker in lowered for marker in placeholders)


def load_llm_config(
    params: Optional[dict[str, Any]] = None,
    *,
    module_hint: Optional[str] = None,
) -> LLMConfig:
    load_runtime_env(module_hint=module_hint)
    params = params or {}
    normalized_module = _normalize_module_hint(module_hint)

    provider = _normalize_provider(
        _first_config_value(
            params.get("llm_provider"),
            params.get("provider"),
            _module_env_value(normalized_module, "LLM_PROVIDER"),
            os.getenv("LLM_PROVIDER"),
        )
    )
    model = _first_config_value(
        params.get("llm_model"),
        params.get("model"),
        _module_env_value(normalized_module, "LLM_MODEL"),
        _provider_env_value(provider, "model_vars"),
        os.getenv("LLM_MODEL"),
        os.getenv("ANTHROPIC_MODEL"),
    )
    # Strip [1m] suffix if present — proxy does not support it as a model variant
    if model and "[1m]" in model:
        model = model.split("[")[0].strip()
    provider_api_key = _provider_env_value(provider, "key_vars")
    provider_api_base = _provider_env_value(provider, "base_vars")
    if provider and not provider_api_base:
        provider_api_base = _provider_default_base(provider)

    api_key = _first_config_value(
        params.get("llm_api_key"),
        _module_env_value(normalized_module, "LLM_API_KEY"),
        provider_api_key,
        os.getenv("LLM_API_KEY"),
        os.getenv("OPENAI_API_KEY"),
        os.getenv("OPENROUTER_API_KEY"),
        os.getenv("ANTHROPIC_API_KEY"),
        os.getenv("ANTHROPIC_AUTH_TOKEN"),
    )
    api_base = _first_config_value(
        params.get("llm_api_base"),
        _module_env_value(normalized_module, "LLM_API_BASE"),
        _module_env_value(normalized_module, "LLM_BASE_URL"),
        provider_api_base,
        os.getenv("LLM_API_BASE"),
        os.getenv("LLM_BASE_URL"),
        os.getenv("OPENAI_API_BASE"),
        os.getenv("OPENAI_BASE_URL"),
        os.getenv("OPENROUTER_API_BASE"),
        os.getenv("OPENROUTER_BASE_URL"),
        os.getenv("ANTHROPIC_API_BASE"),
        os.getenv("ANTHROPIC_BASE_URL"),
    )
    # Auto-append /v1 for OpenAI-compatible proxies
    if api_base and not api_base.rstrip("/").endswith("/v1"):
        api_base = api_base.rstrip("/") + "/v1"

    default_max_tokens = LLMConfig().max_tokens
    max_tokens = _safe_int(
        params.get("llm_max_tokens")
        or params.get("max_tokens")
        or _module_env_value(normalized_module, "LLM_MAX_TOKENS")
        or os.getenv("LLM_MAX_TOKENS")
    )
    if max_tokens is None:
        max_tokens = default_max_tokens

    timeout_s = _safe_int(
        params.get("llm_timeout_s")
        or params.get("timeout_s")
        or _module_env_value(normalized_module, "LLM_TIMEOUT_S")
        or os.getenv("LLM_TIMEOUT_S")
    )
    if timeout_s is None:
        timeout_s = LLMConfig().timeout_s

    temperature = _safe_float(
        _first_defined_value(
            params.get("llm_temperature"),
            params.get("temperature"),
            _module_env_value(normalized_module, "LLM_TEMPERATURE"),
            os.getenv("LLM_TEMPERATURE"),
            0.1,
        )
    )
    verify_ssl = _safe_bool(
        _first_defined_value(
            params.get("llm_verify_ssl"),
            params.get("verify_ssl"),
            _module_env_value(normalized_module, "LLM_VERIFY_SSL"),
            os.getenv("LLM_VERIFY_SSL"),
        )
    )
    force_streaming = _safe_bool(
        _first_defined_value(
            params.get("llm_force_streaming"),
            params.get("force_streaming"),
            _module_env_value(normalized_module, "LLM_FORCE_STREAMING"),
            _provider_env_value(provider, "streaming_vars"),
            os.getenv("LLM_FORCE_STREAMING"),
            False,
        )
    )
    reasoning_effort = _first_config_value(
        params.get("llm_reasoning_effort"),
        params.get("reasoning_effort"),
        _module_env_value(normalized_module, "LLM_REASONING_EFFORT"),
        _provider_env_value(provider, "reasoning_vars"),
        os.getenv("LLM_REASONING_EFFORT"),
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
        reasoning_effort=reasoning_effort,
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


def _normalize_provider(provider: str | None) -> str | None:
    if not provider:
        return None
    normalized = provider.strip().lower().replace("_", "-")
    return _PROVIDER_ALIASES.get(normalized, normalized) or None


def _provider_env_value(provider: str | None, key: str) -> Optional[str]:
    if not provider:
        return None
    spec = _PROVIDER_ENV_SPECS.get(provider, {})
    names = tuple(spec.get(key, ())) + _dynamic_provider_env_names(provider, key)
    return _first_config_value(*(os.getenv(name) for name in _dedupe(names)))


def _provider_default_base(provider: str | None) -> Optional[str]:
    if not provider:
        return None
    spec = _PROVIDER_ENV_SPECS.get(provider)
    if not spec:
        return None
    return _first_config_value(spec.get("default_base"))


def _module_env_value(module_hint: str | None, name: str) -> Optional[str]:
    if not module_hint:
        return None
    return _first_config_value(os.getenv(f"{module_hint.upper()}_{name}"))


def _dynamic_provider_env_names(provider: str, key: str) -> tuple[str, ...]:
    prefix = _provider_env_prefix(provider)
    if key == "base_vars":
        return (f"{prefix}_BASE_URL", f"{prefix}_API_BASE", f"{prefix}_BASE")
    if key == "key_vars":
        return (f"{prefix}_API_KEY", f"{prefix}_KEY")
    if key == "model_vars":
        return (f"{prefix}_MODEL",)
    if key == "streaming_vars":
        return (f"{prefix}_FORCE_STREAMING", f"{prefix}_STREAMING")
    if key == "reasoning_vars":
        return (f"{prefix}_REASONING_EFFORT",)
    return ()


def _provider_env_prefix(provider: str) -> str:
    chars = [ch if ch.isalnum() else "_" for ch in provider.upper()]
    prefix = "".join(chars).strip("_")
    while "__" in prefix:
        prefix = prefix.replace("__", "_")
    return prefix


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _first_config_value(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = _strip_inline_comment(str(value).strip())
        if text:
            return text
    return None


def _first_defined_value(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = _strip_inline_comment(value.strip())
            if text:
                return text
            continue
        return value
    return None
