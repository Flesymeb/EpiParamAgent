#!/usr/bin/env python3
"""
PubMed title-to-PMID search (wrapper).

Usage:
  python pubmed_search_titles.py --input titles.txt --output out.csv

Equivalent:
  python pubmed_manager.py search-title --input titles.txt --output out.csv
"""

import argparse
from pathlib import Path

from tools.scripts.pubmed_manager import search_titles_to_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="根据标题列表搜索PubMed PMID")
    parser.add_argument("--input", required=True, help="标题列表文件(.txt或.csv)")
    parser.add_argument("--output", required=True, help="输出CSV文件")
    parser.add_argument("--focus", default="Serial interval", help="研究焦点")
    args = parser.parse_args()

    search_titles_to_csv(
        Path(args.input),
        Path(args.output),
        focus=args.focus,
        verify=True,
        legacy_output=True,
    )


if __name__ == "__main__":
    main()
