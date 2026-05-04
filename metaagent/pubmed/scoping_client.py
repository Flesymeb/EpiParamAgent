"""Lightweight scoping search helpers for Tavily/Serper.

These are intended for exploratory term discovery only, not formal retrieval.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
SERPER_SEARCH_URL = "https://google.serper.dev/search"


def _env_first(*names: str) -> Optional[str]:
    for name in names:
        val = os.getenv(name)
        if val:
            return val
    return None


def tavily_search(
    query: str,
    *,
    api_key: Optional[str] = None,
    max_results: int = 5,
    search_depth: str = "basic",
    timeout: int = 20,
) -> List[Dict[str, Any]]:
    key = api_key or _env_first("TAVILY_API_KEY", "TAVILY_KEY")
    if not key:
        raise ValueError("Tavily API key missing (set TAVILY_API_KEY).")
    payload = {
        "api_key": key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": False,
        "include_raw_content": False,
    }
    resp = requests.post(TAVILY_SEARCH_URL, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    results: List[Dict[str, Any]] = []
    for item in data.get("results", []) or []:
        results.append(
            {
                "provider": "tavily",
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("content") or item.get("snippet") or "",
            }
        )
    return results


def serper_search(
    query: str,
    *,
    api_key: Optional[str] = None,
    max_results: int = 5,
    timeout: int = 20,
) -> List[Dict[str, Any]]:
    key = api_key or _env_first("SERPER_API_KEY", "SERPER_KEY")
    if not key:
        raise ValueError("Serper API key missing (set SERPER_API_KEY).")
    headers = {"X-API-KEY": key, "Content-Type": "application/json"}
    payload = {"q": query, "num": max_results}
    resp = requests.post(SERPER_SEARCH_URL, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    results: List[Dict[str, Any]] = []
    for item in data.get("organic", []) or []:
        results.append(
            {
                "provider": "serper",
                "title": item.get("title") or "",
                "url": item.get("link") or "",
                "snippet": item.get("snippet") or "",
            }
        )
    return results


def run_scoping_search(
    query: str,
    *,
    providers: Iterable[str],
    max_results: int = 5,
    tavily_api_key: Optional[str] = None,
    serper_api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for provider in providers:
        p = provider.lower().strip()
        try:
            if p == "tavily":
                results.extend(
                    tavily_search(
                        query,
                        api_key=tavily_api_key,
                        max_results=max_results,
                    )
                )
            elif p == "serper":
                results.extend(
                    serper_search(
                        query,
                        api_key=serper_api_key,
                        max_results=max_results,
                    )
                )
        except Exception as e:
            logger.warning("Scoping search failed for %s: %s", provider, e)
    return results


def build_scoping_context(
    results: List[Dict[str, Any]],
    *,
    max_items: int = 8,
    max_chars: int = 1600,
) -> str:
    lines: List[str] = []
    for item in results[:max_items]:
        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        if not title and not snippet:
            continue
        if title and snippet:
            line = f"{title} - {snippet}"
        else:
            line = title or snippet
        lines.append(line)
    context = "\n".join(lines).strip()
    if len(context) > max_chars:
        context = context[: max_chars - 3].rstrip() + "..."
    return context
