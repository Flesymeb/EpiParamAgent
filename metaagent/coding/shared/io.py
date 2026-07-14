"""Path and text helpers for coding-pipeline inputs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

PMID_PATTERN = re.compile(r"PMID[_-]?(\d+)", re.IGNORECASE)


def infer_pmid_from_path(path: Path) -> str | None:
    """Infer a PMID from a file name or one of its parent directories."""
    name = path.stem
    for component in (name, *(parent.name for parent in path.parents)):
        match = PMID_PATTERN.search(component)
        if match:
            return match.group(1)
    if name.upper().startswith("DOI_"):
        return name
    digits = re.findall(r"\d{6,}", name)
    if digits:
        return digits[0]
    return None


def iter_markdown_files(input_path: Path) -> Iterable[Path]:
    """Yield Markdown inputs from a file or directory tree."""
    if input_path.is_file():
        if input_path.suffix.lower() in (".md", ".txt"):
            yield input_path
        return
    yield from sorted(input_path.rglob("*.md"))


def read_text(path: Path) -> str:
    """Read a UTF-8 text file while tolerating malformed characters."""
    return path.read_text(encoding="utf-8", errors="ignore")
