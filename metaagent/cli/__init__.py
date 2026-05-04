"""MetaAgent-Epi unified CLI.

Entry point: ``metaagent``
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from metaagent.cli.utils import DEV_ROOT, REPO_ROOT
from metaagent.cli.display import console, ACCENT, ACCENT_BOLD, ACCENT_DIM, StyledGroup

_SRC_PATHS = [
    str(DEV_ROOT),                   # common, mineru, paper_fetch, meta_analysis
    str(DEV_ROOT), # screening, data_sources, epidemiology
]

for _p in _SRC_PATHS:
    if _p not in sys.path:
        sys.path.insert(0, _p)


@click.group(invoke_without_command=True, cls=StyledGroup)
@click.version_option(version="0.2.0", prog_name="metaagent", message=f"[{ACCENT}]%(prog)s[/{ACCENT}] [bold]%(version)s[/bold]")
@click.pass_context
def main(ctx):
    """MetaAgent-Epi: epidemiology meta-analysis CLI."""
    if ctx.invoked_subcommand is None:
        from metaagent.cli.display import show_banner
        show_banner()


# ── Lazy-load sub-groups to avoid heavy imports at startup ──────────
from metaagent.cli.screening import screening
from metaagent.cli.coding import coding
from metaagent.cli.pubmed import pubmed
from metaagent.cli.pdf import pdf

main.add_command(screening)
main.add_command(coding)
main.add_command(pubmed)
main.add_command(pdf)


if __name__ == "__main__":
    main()