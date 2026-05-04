"""MetaAgent-Epi unified CLI.

Entry point: ``metaagent``
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

# ── sys.path setup ──────────────────────────────────────────────────────
# Make shared tools and screening/coding modules importable.
from cli.utils import DEV_ROOT, REPO_ROOT

_SRC_PATHS = [
    str(DEV_ROOT / "tools"),                   # common, mineru, paper_fetch, meta_analysis
    str(DEV_ROOT / "literature_search" / "src"), # screening, data_sources, epidemiology
]

for _p in _SRC_PATHS:
    if _p not in sys.path:
        sys.path.insert(0, _p)


@click.group()
@click.version_option(version="0.2.0", prog_name="metaagent")
def main():
    """MetaAgent-Epi: epidemiology meta-analysis CLI."""


# ── Lazy-load sub-groups to avoid heavy imports at startup ──────────
from cli.screening import screening
from cli.coding import coding
from cli.pubmed import pubmed
from cli.pdf import pdf

main.add_command(screening)
main.add_command(coding)
main.add_command(pubmed)
main.add_command(pdf)


if __name__ == "__main__":
    main()