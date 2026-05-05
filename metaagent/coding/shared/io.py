from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

PMID_PATTERN = re.compile(r"PMID[_-]?(\d+)", re.IGNORECASE)


def infer_pmid_from_path(path: Path) -> str | None:
    for name in [path.stem, *(part for part in reversed(path.parts) if part != path.name)]:
        match = PMID_PATTERN.search(name)
        if match:
            return match.group(1)
        if name.upper().startswith("DOI_"):
            return name
        digits = re.findall(r"\d{6,}", name)
        if digits:
            return digits[0]
    return None


def iter_markdown_files(input_path: Path) -> Iterable[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() in (".md", ".txt"):
            yield input_path
        return
    for p in sorted(input_path.rglob("*.md")):
        yield p


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")
