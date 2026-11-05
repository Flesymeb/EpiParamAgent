from __future__ import annotations

import os
import sys
import json
from pathlib import Path

import httpx
from langchain_openai import ChatOpenAI


def _env_int(*names: str, default: int) -> int:
    for name in names:
        value = os.environ.get(name)
        if not value:
            continue
        try:
            parsed = int(value)
        except ValueError:
            continue
        if parsed >= 0:
            return parsed
    return default


def _matches_no_proxy(url: str, no_proxy: str) -> bool:
    """Return True if the host in url matches any entry in the no_proxy list."""
    if not url or not no_proxy:
        return False
    host = url.split("//")[-1].split("/")[0].split(":")[0]
    return any(host.endswith(e.strip()) for e in no_proxy.split(",") if e.strip())


def init_llm(config_overrides: dict[str, object] | None = None):
    from metaagent.llm_rate_limit import httpx_event_hooks
    tools_dir = Path(__file__).resolve().parents[2] / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from metaagent.config import is_usable_secret, load_llm_config, merge_thinking_policy, resolve_extra_body

    cfg = load_llm_config(config_overrides, module_hint="coding")
    if not is_usable_secret(cfg.api_key):
        raise RuntimeError("Missing LLM_API_KEY/OPENAI_API_KEY")
    model = cfg.model or "openai/gpt-4.1"

    # If the API endpoint is in NO_PROXY (e.g. internal 10.x.x.x), bypass the
    # system SOCKS proxy entirely; otherwise let httpx pick up env proxy settings.
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    trust_env = cfg.provider not in {"lab", "lab2"} and not _matches_no_proxy(cfg.api_base or "", no_proxy)

    timeout = httpx.Timeout(
        cfg.timeout_s,
        connect=min(10, cfg.timeout_s),
        read=cfg.timeout_s,
        write=min(30, cfg.timeout_s),
        pool=min(10, cfg.timeout_s),
    )
    # The extraction call wrapper owns retries so every attempt is recorded.
    # Hidden SDK retries would make timing, cost and failure logs incomplete.
    max_retries = 0

    http_client = httpx.Client(
        verify=cfg.verify_ssl,
        timeout=timeout,
        trust_env=trust_env,
        event_hooks=httpx_event_hooks(),
    )
    extra_body = None
    thinking = getattr(cfg, "thinking", None)
    if thinking is None and cfg.provider == "bailian" and (
        str(model).lower().startswith("glm-")
        or str(model).lower().startswith("qwen")
    ):
        # Bailian reasoning models default to thinking mode. Direct extraction
        # needs compact, JSON-first responses, so use non-thinking mode for
        # both the existing GLM baseline and the Qwen ablation backbone.
        extra_body = {"enable_thinking": False}
    extra_body = merge_thinking_policy(extra_body, thinking)
    parsed_body = resolve_extra_body(config_overrides, module_hint="coding")
    if parsed_body:
        # Explicit transport JSON remains the highest-precedence coding override.
        # Remove generated thinking aliases before applying a user-supplied mode,
        # so an implicit policy cannot contradict the explicit native protocol.
        if "thinking" in parsed_body or "enable_thinking" in parsed_body:
            extra_body = {key:value for key,value in (extra_body or {}).items()
                          if key not in {"thinking", "enable_thinking"}}
        extra_body = {**(extra_body or {}), **parsed_body}

    extra_body = merge_thinking_policy(extra_body, None)

    if (config_overrides or {}).get('_coding_response_format'):
        extra_body={**(extra_body or {}),'response_format':config_overrides['_coding_response_format']}

    options = dict(
        model=model,
        api_key=cfg.api_key,
        base_url=cfg.api_base,
        temperature=cfg.temperature,
        max_retries=max_retries,
        request_timeout=cfg.timeout_s,
        http_client=http_client,
        extra_body=extra_body,
        max_tokens=cfg.max_tokens,
        streaming=cfg.force_streaming,
    )
    if cfg.reasoning_effort:
        options["reasoning_effort"] = cfg.reasoning_effort
    return ChatOpenAI(**options)
