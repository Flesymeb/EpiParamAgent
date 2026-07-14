"""Install shell completion for the MetaAgent-Epi CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
from click.shell_completion import get_completion_class

from metaagent._cli_shared import ACCENT_DIM, StyledGroup, console, show_success

SUPPORTED_SHELLS = ("bash", "zsh", "fish")


def _resolve_shell(shell: str) -> str:
    """Resolve an explicit shell name or infer it from ``$SHELL``."""
    if shell != "auto":
        return shell
    detected = Path(os.environ.get("SHELL", "")).name
    if detected not in SUPPORTED_SHELLS:
        raise click.ClickException(
            "Cannot detect a supported shell from $SHELL. "
            "Use --shell bash, --shell zsh, or --shell fish."
        )
    return detected


def _completion_source(shell: str) -> str:
    """Generate Click's completion source for the installed command tree."""
    from metaagent.cli import main

    completion_class = get_completion_class(shell)
    if completion_class is None:
        raise click.ClickException(f"Unsupported shell: {shell}")
    return completion_class(
        main,
        {},
        "metaagent",
        "_METAAGENT_COMPLETE",
    ).source()


def _default_completion_path(shell: str) -> Path:
    """Return a per-user completion path for a supported shell."""
    home = Path.home()
    if shell == "bash":
        return home / ".local/share/bash-completion/completions/metaagent"
    if shell == "zsh":
        return home / ".zfunc/_metaagent"
    return home / ".config/fish/completions/metaagent.fish"


def _activation_hint(shell: str, path: Path) -> str:
    if shell == "bash":
        return f"Open a new shell, or run: source {path}"
    if shell == "zsh":
        return "Add ~/.zfunc to fpath, then run: autoload -Uz compinit && compinit"
    return "Fish loads files in ~/.config/fish/completions automatically."


@click.group(cls=StyledGroup)
def completion():
    """Generate or install shell Tab completion."""


@completion.command("show")
@click.option(
    "--shell",
    type=click.Choice(["auto", *SUPPORTED_SHELLS], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Shell syntax to generate",
)
def show(shell: str):
    """Print a completion script to standard output."""
    resolved = _resolve_shell(shell.lower())
    click.echo(_completion_source(resolved))


@completion.command("install")
@click.option(
    "--shell",
    type=click.Choice(["auto", *SUPPORTED_SHELLS], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Shell to configure",
)
@click.option(
    "--path",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Override the per-user completion file",
)
@click.option("--force", is_flag=True, help="Replace a different existing completion file")
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
def install(shell: str, output_path: Path | None, force: bool, json_output: bool):
    """Install completion idempotently in the current user's home directory."""
    resolved = _resolve_shell(shell.lower())
    target = (output_path or _default_completion_path(resolved)).expanduser().resolve()
    source = _completion_source(resolved).rstrip() + "\n"

    status = "installed"
    if target.exists():
        if target.read_text(encoding="utf-8") == source:
            status = "already_current"
        elif not force:
            raise click.ClickException(
                f"Completion file already exists and differs: {target}. "
                "Use --force to replace it."
            )

    if status == "installed":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")

    payload = {
        "shell": resolved,
        "path": str(target),
        "status": status,
        "activation": _activation_hint(resolved, target),
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    if status == "already_current":
        show_success(f"Completion is already current: {target}")
    else:
        show_success(f"Installed {resolved} completion: {target}")
    console.print(f"[{ACCENT_DIM}]{payload['activation']}[/{ACCENT_DIM}]")


__all__ = ["completion"]
