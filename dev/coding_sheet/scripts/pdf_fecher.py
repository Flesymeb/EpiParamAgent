"""Entry point for the Sci-Hub/PubMed PDF fetcher.

Usage:
  python MetaAgent-Epi/dev/coding_sheet/scripts/pdf_fecher.py --download
"""
from __future__ import annotations

from pathlib import Path
import runpy


def main() -> None:
    target = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "paper_fetch"
        / "pdf_fecher.py"
    )
    if not target.exists():
        raise FileNotFoundError(f"Target script not found: {target}")
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
