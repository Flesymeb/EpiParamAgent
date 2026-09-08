from __future__ import annotations

import os
import sys
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
    tools_dir = Path(__file__).resolve().parents[2] / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from metaagent.config import is_usable_secret, load_llm_config

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
    max_retries = _env_int("CODING_LLM_MAX_RETRIES", "LLM_MAX_RETRIES", default=3)

    http_client = httpx.Client(
        verify=cfg.verify_ssl,
        timeout=timeout,
        trust_env=trust_env,
    )
    extra_body = None
    if cfg.provider == "bailian" and (
        str(model).lower().startswith("glm-")
        or str(model).lower().startswith("qwen")
    ):
        # Bailian reasoning models default to thinking mode. Direct extraction
        # needs compact, JSON-first responses, so use non-thinking mode for
        # both the existing GLM baseline and the Qwen ablation backbone.
        extra_body = {"enable_thinking": False}

    return ChatOpenAI(
        model=model,
        api_key=cfg.api_key,
        base_url=cfg.api_base,
        temperature=cfg.temperature,
        max_retries=max_retries,
        request_timeout=cfg.timeout_s,
        http_client=http_client,
        extra_body=extra_body,
    )
