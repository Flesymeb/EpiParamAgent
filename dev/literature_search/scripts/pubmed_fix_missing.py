#!/usr/bin/env python3
"""
PubMed missing-field repair (wrapper).

Usage:
  python pubmed_fix_missing.py --input INPUT.csv --output OUTPUT.csv

Equivalent:
  python pubmed_manager.py fix-missing --input INPUT.csv --output OUTPUT.csv
"""

import argparse
from pathlib import Path

from pubmed_manager import fix_missing_fields


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix missing abstract/keywords using PubMed EFetch"
    )
    parser.add_argument("--input", required=True, help="Input CSV file")
    parser.add_argument("--output", required=True, help="Output CSV file")
    args = parser.parse_args()

    fix_missing_fields(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()
