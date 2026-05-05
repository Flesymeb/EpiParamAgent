"""MetaAgent-Epi unified CLI entry point.

Usage: python -m metaagent.cli [command]
"""

from __future__ import annotations

import sys

import click

from metaagent._cli_shared import (
    ACCENT, ACCENT_BOLD, ACCENT_DIM, REPO_ROOT, DEV_ROOT,
    StyledGroup, console, show_command_header,
)


def _show_banner():
    from metaagent import __version__
    from metaagent._cli_shared import show_banner
    show_banner(__version__)


@click.group(invoke_without_command=True, cls=StyledGroup)
@click.version_option(
    version="0.3.0",
    prog_name="metaagent",
    message=f"[{ACCENT}]%(prog)s[/{ACCENT}] [bold]%(version)s[/bold]",
)
@click.pass_context
def main(ctx):
    """MetaAgent-Epi: epidemiology meta-analysis CLI."""
    if ctx.invoked_subcommand is None:
        _show_banner()


# ── Register command groups from domain modules ───────────────
sys.path.insert(0, str(DEV_ROOT))

from metaagent.screening.cli import screening
from metaagent.coding.cli import coding
from tools.pubmed.cli import pubmed
from tools.paper_fetch.cli import pdf

main.add_command(screening)
main.add_command(coding)
main.add_command(pubmed)
main.add_command(pdf)


if __name__ == "__main__":
    main()
