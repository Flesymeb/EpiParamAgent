"""MetaAgent-Epi unified CLI entry point.

Usage: python -m metaagent.cli [command]
"""

from __future__ import annotations

import click

from metaagent._cli_shared import (
    ACCENT,
    ACCENT_DIM,
    TEXT_DIM,
    StyledGroup,
    console,
)
from metaagent.coding.cli import coding
from metaagent.completion import completion
from metaagent.config_cli import config
from metaagent.evaluation.cli import evaluation
from metaagent.profile_cli import profile
from metaagent.screening.cli import screening
from metaagent.workflow import workflow
from metaagent.review import review
from metaagent.annotations import annotations
from metaagent.synthesis.cli import synthesis
from tools.paper_fetch.cli import pdf
from tools.literature.cli import literature
from tools.pubmed.cli import pubmed

_LOGO_LEFT = "#f4a261"
_LOGO_SPACER = [
    "        ",
    "        ",
    "   ██   ",
    "   ██   ",
    "        ",
    "        ",
]
_LOGO_META = [
    "██╗ ██╗ ██████╗ ██████╗  █████╗",
    "███╗███║██╔═══╝ ╚══██╔╝ ██╔══██╗",
    "██╔████║█████╗    ██║   ███████║",
    "██║╚╝██║██╔══╝    ██║   ██╔══██║",
    "██║  ██║██████╗   ██║   ██║  ██║",
    "╚═╝  ╚═╝╚═════╝   ╚═╝   ╚═╝  ╚═╝",
]
_LOGO_AGENT = [
    " █████╗  █████╗  ██████╗ ██╗ ██╗ ██████╗ ",
    "██╔══██╗██╔═══╝ ██╔═══╝ ███████║╚══██╔╝ ",
    "███████║██║ ██╗ █████╗  ██╔████║  ██║   ",
    "██╔══██║██║ ╚██╗██╔══╝  ██║╚███║  ██║   ",
    "██║  ██║╚█████╔╝██████╗ ██║ ╚██║  ██║   ",
    "╚═╝  ╚═╝ ╚════╝ ╚═════╝ ╚═╝  ╚═╝  ╚═╝   ",
]


def _show_banner():
    from metaagent import __version__

    console.print(f"[{ACCENT}]" + "━" * 80 + f"[/{ACCENT}]")
    for meta, spacer, agent in zip(_LOGO_META, _LOGO_SPACER, _LOGO_AGENT):
        console.print(
            f"[bold {_LOGO_LEFT}]{meta}[/bold {_LOGO_LEFT}]"
            f"[bold {ACCENT}]{spacer}[/bold {ACCENT}]"
            f"[bold white]{agent}[/bold white]"
        )
    console.print(
        f"[bold {ACCENT}]Epidemiology Meta-Analysis Agent[/bold {ACCENT}]"
    )
    console.print(
        f"[{ACCENT_DIM}]Version {__version__}[/{ACCENT_DIM}]  "
        f"[{ACCENT}]•[/{ACCENT}]  "
        f"[{ACCENT_DIM}]https://github.com/Flesymeb/MetaAgent-Epi[/{ACCENT_DIM}]"
    )
    console.print(f"[{ACCENT}]" + "━" * 80 + f"[/{ACCENT}]")
    console.print(
        f"[{TEXT_DIM}]Start with [bold]metaagent pubmed query[/bold], "
        f"[bold]metaagent screening --help[/bold], or "
        f"[bold]metaagent coding --help[/bold].[/{TEXT_DIM}]"
    )
    console.print()


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
main.add_command(screening)
main.add_command(coding)
main.add_command(synthesis)
main.add_command(review)
main.add_command(annotations)
main.add_command(evaluation)
main.add_command(pubmed)
main.add_command(literature)
main.add_command(pdf)
main.add_command(completion)
main.add_command(workflow)
main.add_command(config)
main.add_command(profile)

# Benchmark is an optional domain module; other commands remain usable while
# installing extensions or when the benchmark dependency is unavailable.
try:
    from metaagent.benchmark.cli import benchmark
except ModuleNotFoundError as exc:
    if not (exc.name or "").startswith("metaagent.benchmark"):
        raise
else:
    main.add_command(benchmark)


if __name__ == "__main__":
    main()
