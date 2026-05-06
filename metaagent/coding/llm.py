from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from langchain_openai import ChatOpenAI


def _matches_no_proxy(url: str, no_proxy: str) -> bool:
    """Return True if the host in url matches any entry in the no_proxy list."""
    if not url or not no_proxy:
        return False
    host = url.split("//")[-1].split("/")[0].split(":")[0]
    return any(host.endswith(e.strip()) for e in no_proxy.split(",") if e.strip())


def init_llm():
    tools_dir = Path(__file__).resolve().parents[2] / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from metaagent.config import load_llm_config

    cfg = load_llm_config(module_hint="coding")
    if not cfg.api_key:
        raise RuntimeError("Missing LLM_API_KEY/OPENAI_API_KEY")
    model = cfg.model or "openai/gpt-4.1"

    # If the API endpoint is in NO_PROXY (e.g. internal 10.x.x.x), bypass the
    # system SOCKS proxy entirely; otherwise let httpx pick up env proxy settings.
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    trust_env = cfg.provider not in {"lab", "lab2"} and not _matches_no_proxy(cfg.api_base or "", no_proxy)

    http_client = httpx.Client(
        verify=cfg.verify_ssl,
        timeout=cfg.timeout_s,
        trust_env=trust_env,
    )
    return ChatOpenAI(
        model=model,
        api_key=cfg.api_key,
        base_url=cfg.api_base,
        temperature=cfg.temperature,
        max_retries=3,
        request_timeout=cfg.timeout_s,
        http_client=http_client,
    )
