"""Deprecated alias entrypoint for the Sci-Hub/PubMed PDF fetcher.

Usage:
  python pdf_fecher_alias.py --input pmid.txt --input-type pmid --download
"""
from __future__ import annotations

from pathlib import Path
import runpy


def main() -> None:
    script_path = Path(__file__).with_name("pdf_fecher.py")
    runpy.run_path(str(script_path), run_name="__main__")


if __name__ == "__main__":
    main()
