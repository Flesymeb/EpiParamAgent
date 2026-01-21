from __future__ import annotations

import sys
from pathlib import Path

_tools_dir = Path(__file__).resolve().parents[3] / "tools"
if str(_tools_dir) not in sys.path:
    sys.path.insert(0, str(_tools_dir))

from mineru.pdf_reader_mineru import (  # type: ignore
    PdfMarkdownExtract,
    extract_pdf_markdown_mineru,
)

__all__ = [
    "PdfMarkdownExtract",
    "extract_pdf_markdown_mineru",
]
