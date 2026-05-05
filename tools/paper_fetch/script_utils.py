#!/usr/bin/env python
# -*- encoding=utf8 -*-

"""
Filename: script_utils.py
Description: Utility functions for coding sheet scripts.
Author: Hyoung Yan
Created time: 2025-12-26 10:37:32
Last Modified time: 2025-12-26 14:50:34
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(name)


def iter_pdfs(input_path: Path) -> list[Path]:
    """Find all PDFs in a file or directory."""
    if input_path.is_file():
        return [input_path]
    pdfs = sorted(p for p in input_path.glob("**/*.pdf") if p.is_file())
    return pdfs


def safe_slug(s: str) -> str:
    """Create a safe filename/slug from a string."""
    s = (s or "").strip()
    if not s:
        return "unknown"
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s[:180].strip("_") or "unknown"


def read_urls(input_path: Path) -> list[str]:
    """Read URL inputs from a .txt (one url per line) or .jsonl ({"url":...} or {"urls":[...]})."""
    if not input_path.exists():
        return []

    if input_path.suffix.lower() == ".txt":
        lines = input_path.read_text(encoding="utf-8").splitlines()
        return [
            ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")
        ]

    if input_path.suffix.lower() == ".jsonl":
        urls: list[str] = []
        for ln in input_path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)

                # New format: {"doi": "...", "urls": [{"url": "...", "status": "available"|"downloaded", ...}]}
                if "urls" in obj and isinstance(obj["urls"], list):
                    # Prefer already-downloaded local PDFs when present
                    downloaded = []
                    for u in obj["urls"]:
                        if u.get("status") != "downloaded":
                            continue
                        local_path = (u.get("local_path") or u.get("url") or "").strip()
                        if local_path and Path(local_path).exists():
                            downloaded.append(local_path)
                    if downloaded:
                        urls.append(downloaded[0])
                        continue

                    # Otherwise, prioritize available URLs
                    available = [
                        (u.get("url") or "").strip()
                        for u in obj["urls"]
                        if u.get("status") == "available"
                        and (u.get("url") or "").strip()
                    ]
                    if available:
                        urls.append(available[0])
                        continue
                    # Fallback: use first URL regardless of status
                    if obj["urls"]:
                        first_url = obj["urls"][0].get("url")
                        if first_url:
                            urls.append(first_url)
                            continue

                # Old format: {"url": "..."}
                u = (obj.get("url") or obj.get("pdf_url") or "").strip()
                if u:
                    urls.append(u)
            except json.JSONDecodeError:
                continue
        return urls

    return []
