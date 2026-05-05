"""Shared CLI display helpers, constants, and utility functions.

Imported by domain CLI modules (screening/cli.py, coding/cli.py, etc.).
Separated from cli.py to avoid circular imports.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

# ── Console ────────────────────────────────────────────────────
console = Console(width=120)

# ── Colors ─────────────────────────────────────────────────────
ACCENT = "#00b4d8"
ACCENT_DIM = "#90e0ef"
ACCENT_BOLD = "#0077b6"
TEXT_DIM = "#caf0f8"
LOGO_LEFT = "#f4a261"
SUCCESS = "#2dc653"
WARN = "#f9c74f"
ERROR = "#f94144"

# ── Domain constants ───────────────────────────────────────────
DISEASE_NAMES = ["covid19", "mpox"]
TOPIC_NAMES = ["serial_interval", "reproduction_number", "fatality"]


# ── Display functions ──────────────────────────────────────────

def show_command_header(title: str, subtitle: str = "") -> None:
    text = f"[bold {ACCENT_BOLD}]{title}[/bold {ACCENT_BOLD}]"
    if subtitle:
        text += f"  [{ACCENT_DIM}]{subtitle}[/{ACCENT_DIM}]"
    console.rule(text, style=ACCENT)


def show_success(message: str) -> None:
    console.print(f"[{SUCCESS}]OK[/{SUCCESS}] {message}")


def show_error(message: str) -> None:
    console.print(f"[{ERROR}]ERROR[/{ERROR}] {message}")


def show_warning(message: str) -> None:
    console.print(f"[{WARN}]WARN[/{WARN}] {message}")


def show_step(step: int, total: int, label: str) -> None:
    console.rule(
        f"[bold {ACCENT}]Step {step}/{total}: {label}[/bold {ACCENT}]",
        style=ACCENT,
    )


class StyledGroup(click.Group):
    """Click Group with Rich-styled help output."""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        group_name = ctx.command.name or "metaagent"
        help_text = (self.help or "").split("\n")[0]
        console.rule(
            f"[bold {ACCENT_BOLD}]{group_name}[/bold {ACCENT_BOLD}]  "
            f"[{ACCENT_DIM}]{help_text}[/{ACCENT_DIM}]",
            style=ACCENT,
        )
        console.print()
        if self.commands:
            table = Table(show_header=True, header_style=f"bold {ACCENT_BOLD}",
                          border_style=ACCENT_DIM, title="Commands", title_style=f"bold {ACCENT}")
            table.add_column("Command", style=f"bold {ACCENT}", min_width=14)
            table.add_column("Description", style="white")
            for name, cmd in sorted(self.commands.items()):
                desc = (cmd.help or "").split("\n")[0]
                table.add_row(name, desc)
            console.print(table)
            console.print()
        console.print(
            f"[{ACCENT_DIM}]Run [bold]metaagent {group_name} <subcommand> --help[/bold] "
            f"for details.[/{ACCENT_DIM}]"
        )


# ── Project root resolution ────────────────────────────────────

def _find_project_root() -> Path:
    cwd = Path.cwd()
    for p in [cwd] + list(cwd.parents):
        if (p / "evaluation").exists() and (p / "metaagent").exists():
            return p
    src_dir = Path(__file__).resolve()
    for p in src_dir.parents:
        if (p / "evaluation").exists() and (p / "metaagent").exists():
            return p
    raise click.ClickException(
        "Cannot find MetaAgent-Epi project root. Run from project directory."
    )


REPO_ROOT = _find_project_root()
DEV_ROOT = REPO_ROOT


def resolve_project_root(ctx: click.Context | None = None) -> Path:
    if ctx and ctx.params.get("project_root"):
        return Path(ctx.params["project_root"]).resolve()
    cwd = Path.cwd()
    if (cwd / "evaluation").exists():
        return cwd
    return REPO_ROOT


# ── ASCII art banner ───────────────────────────────────────────
_LOGO = [
    "██╗ ██╗ ██████╗ ██████╗  █████╗",
    "███╗███║██╔═══╝ ╚══██╔╝ ██╔══██╗",
    "██╔████║█████╗    ██║   ███████║",
    "██║╚╝██║██╔══╝    ██║   ██╔══██║",
    "██║  ██║██████╗   ██║   ██║  ██║",
    "╚═╝  ╚═╝╚═════╝   ╚═╝   ╚═╝  ╚═╝",
]
_LOGO2 = [
    " █████╗  █████╗ ██████╗ ██╗ ██╗ ██████╗ ",
    "██╔══██╗██╔═══╝ ██╔═══╝ ███████║╚══██╔╝ ",
    "███████║██║ ██╗ █████╗  ██╔████║  ██║   ",
    "██╔══██║██║ ╚██╗██╔══╝  ██║╚███║  ██║   ",
    "██║  ██║╚█████╔╝██████╗ ██║ ╚██║  ██║   ",
    "╚═╝  ╚═╝ ╚════╝ ╚═════╝ ╚═╝  ╚═╝  ╚═╝   ",
]
_SEP = [
    "        ",
    "        ",
    "   ██   ",
    "   ██   ",
    "        ",
    "        ",
]


def show_banner(version: str = "0.3.0") -> None:
    """Print the MetaAgent startup banner."""
    console.print(f"[{ACCENT}]" + "━" * 80 + f"[/{ACCENT}]")
    for meta, sep, agent in zip(_LOGO, _SEP, _LOGO2):
        console.print(
            f"[bold {LOGO_LEFT}]{meta}[/bold {LOGO_LEFT}]"
            f"[bold {ACCENT}]{sep}[/bold {ACCENT}]"
            f"[bold #ffffff]{agent}[/bold #ffffff]"
        )
    console.print(f"[bold {ACCENT}]Epidemiology Meta-Analysis Agent[/bold {ACCENT}]")
    console.print(
        f"[{ACCENT_DIM}]Version {version}[/{ACCENT_DIM}]  "
        f"[{ACCENT}]•[/{ACCENT}]  "
        f"[{ACCENT_DIM}]https://github.com/Flesymeb/MetaAgent-Epi[/{ACCENT_DIM}]"
    )
    console.print(f"[{ACCENT}]" + "━" * 80 + f"[/{ACCENT}]")
    console.print(
        f"[{TEXT_DIM}]Start with "
        f"[bold]metaagent screening prepare[/bold] or "
        f"[bold]metaagent coding extract[/bold].[/{TEXT_DIM}]\n"
    )
