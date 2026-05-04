"""MetaAgent-Epi rich console styling."""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── Global console ──────────────────────────────────────────────────────
console = Console(width=120)

# ── Color palette (epidemiology / teal theme) ──────────────────────────
ACCENT      = "#00b4d8"   # teal — primary accent
ACCENT_DIM  = "#90e0ef"   # light teal — secondary info
ACCENT_BOLD = "#0077b6"   # deep blue — strong emphasis
TEXT_DIM    = "#caf0f8"   # pale teal — hints/tips
LOGO_LEFT   = "#f4a261"   # warm orange — "META" in banner
SUCCESS     = "#2dc653"   # green — OK
WARN        = "#f9c74f"   # amber — warnings
ERROR       = "#f94144"   # red — errors


# ── ASCII art banner (solid block characters, Prism4MAS outline style) ─
_SEP = [
    "        ",
    "        ",
    "   ██   ",
    "   ██   ",
    "        ",
    "        ",
]
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


def show_banner(version: str = "0.2.0") -> None:
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


def show_command_header(title: str, subtitle: str = "") -> None:
    """Print a styled command header with horizontal rule."""
    text = f"[bold {ACCENT_BOLD}]{title}[/bold {ACCENT_BOLD}]"
    if subtitle:
        text += f"  [{ACCENT_DIM}]{subtitle}[/{ACCENT_DIM}]"
    console.rule(text, style=ACCENT)


def show_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[{SUCCESS}]✓[/{SUCCESS}] {message}")


def show_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[{ERROR}]✗[/{ERROR}] {message}")


def show_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[{WARN}]⚠[/{WARN}] {message}")


def show_step(step: int, total: int, label: str) -> None:
    """Print a pipeline step indicator."""
    console.rule(
        f"[bold {ACCENT}]Step {step}/{total}: {label}[/bold {ACCENT}]",
        style=ACCENT,
    )


def make_summary_table(title: str, rows: list[tuple[str, str]],
                       header_style: str = ACCENT_BOLD) -> Table:
    """Create a simple key-value summary table."""
    table = Table(title=title, header_style=f"bold {header_style}", show_lines=False)
    table.add_column("Field", style="bold")
    table.add_column("Value", overflow="fold")
    for key, val in rows:
        table.add_row(key, val)
    return table


class StyledGroup(click.Group):
    """Click Group that renders help with rich-styled tables."""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        group_name = ctx.command.name or "metaagent"
        help_text = (self.help or "").split("\n")[0]
        console.rule(f"[bold {ACCENT_BOLD}]{group_name}[/bold {ACCENT_BOLD}]  [{ACCENT_DIM}]{help_text}[/{ACCENT_DIM}]", style=ACCENT)
        console.print()

        # Commands table
        if self.commands:
            table = Table(
                show_header=True,
                header_style=f"bold {ACCENT_BOLD}",
                border_style=ACCENT_DIM,
                title="Commands",
                title_style=f"bold {ACCENT}",
            )
            table.add_column("Command", style=f"bold {ACCENT}", min_width=14)
            table.add_column("Description", style="white")
            for name, cmd in sorted(self.commands.items()):
                desc = (cmd.help or "").split("\n")[0]
                table.add_row(name, desc)
            console.print(table)
            console.print()

        # Options table
        opts = []
        for param in self.params:
            if isinstance(param, click.Option):
                names = ", ".join(param.opts)
                opts.append((names, param.help or ""))
        if opts:
            opt_table = Table(
                show_header=True,
                header_style=f"bold {ACCENT_BOLD}",
                border_style=ACCENT_DIM,
                title="Options",
                title_style=f"bold {ACCENT}",
            )
            opt_table.add_column("Flag", style=f"bold {ACCENT}", min_width=14)
            opt_table.add_column("Description", style="white")
            for flag, desc in opts:
                opt_table.add_row(flag, desc)
            console.print(opt_table)
            console.print()

        if group_name == "main":
            console.print(f"[{ACCENT_DIM}]Run [bold]metaagent <command> --help[/bold] for command details.[/{ACCENT_DIM}]")
        else:
            console.print(f"[{ACCENT_DIM}]Run [bold]metaagent {group_name} <subcommand> --help[/bold] for details.[/{ACCENT_DIM}]")