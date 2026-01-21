"""
Deprecated wrapper for Sci-Hub URL extraction.

Usage:
  python MetaAgent-Epi/dev/coding_sheet/scripts/get_scihub_urls.py

Note:
  The implementation now lives at:
  MetaAgent-Epi/dev/tools/paper_fetch/pdf_fetcher.py

Preferred:
  python MetaAgent-Epi/dev/coding_sheet/scripts/pdf_fetcher.py
"""

from pathlib import Path
import runpy


def main() -> None:
    target = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "paper_fetch"
        / "pdf_fetcher.py"
    )
    if not target.exists():
        raise FileNotFoundError(f"Target script not found: {target}")
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
