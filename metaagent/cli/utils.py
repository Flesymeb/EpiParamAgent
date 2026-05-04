"""Shared CLI utility functions."""

from __future__ import annotations

from pathlib import Path

import click


def _find_project_root() -> Path:
    """Find the MetaAgent-Epi project root by searching upward for a marker."""
    # Start from cwd and search for a directory containing evaluation/
    cwd = Path.cwd()
    for p in [cwd] + list(cwd.parents):
        if (p / "evaluation").exists() and (p / "dev").exists():
            return p
    # Fallback: use the source file location (works when running from dev/)
    src_dir = Path(__file__).resolve()
    # Walk up: cli/ -> dev/ -> MetaAgent-Epi/
    for p in src_dir.parents:
        if (p / "evaluation").exists() and (p / "metaagent").exists():
            return p
    raise click.ClickException("Cannot find MetaAgent-Epi project root. Run from project directory.")

REPO_ROOT = _find_project_root()
DEV_ROOT = REPO_ROOT  # Project root is the development root in new structure


def resolve_project_root(ctx: click.Context | None = None) -> Path:
    """Resolve project root directory.

    Priority:
    1. --project-root argument (if provided)
    2. Current working directory (if it contains evaluation/)
    3. REPO_ROOT from package layout
    """
    if ctx and ctx.params.get("project_root"):
        return Path(ctx.params["project_root"]).resolve()

    cwd = Path.cwd()
    if (cwd / "evaluation").exists():
        return cwd

    return REPO_ROOT


def resolve_profile(profile: str, disease: str | None = None):
    """Look up a screening profile and validate it."""
    from metaagent.screening.profile_registry import get_profile

    p = get_profile(profile.upper())
    if p is None:
        raise click.BadParameter(f"Unknown profile: {profile}")
    return p


DISEASE_NAMES = ["covid19", "mpox"]
TOPIC_NAMES = ["serial_interval", "reproduction_number", "fatality"]