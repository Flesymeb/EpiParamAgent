from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from langchain_openai import ChatOpenAI


def init_llm():
    tools_dir = Path(__file__).resolve().parents[2] / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from common.config import load_llm_config

    cfg = load_llm_config(module_hint="coding_sheet")
    if not cfg.api_key:
        raise RuntimeError("Missing LLM_API_KEY/OPENAI_API_KEY")
    model = cfg.model or "openai/gpt-4.1"
    http_client = httpx.Client(verify=cfg.verify_ssl, timeout=cfg.timeout_s)
    return ChatOpenAI(
        model=model,
        api_key=cfg.api_key,
        base_url=cfg.api_base,
        temperature=cfg.temperature,
        max_retries=3,
        request_timeout=cfg.timeout_s,
        http_client=http_client,
    )
