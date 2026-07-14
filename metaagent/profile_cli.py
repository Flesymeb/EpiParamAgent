"""Discover and inspect tracked review profiles."""

from __future__ import annotations

import json

import click
from rich.table import Table

from metaagent._cli_shared import ACCENT, ACCENT_BOLD, StyledGroup, console
from metaagent.screening.profile_registry import (
    ScreeningProfile,
    load_profile_registry,
    resolve_profile_context,
)


@click.group(cls=StyledGroup)
def profile():
    """Discover configured systematic-review tasks."""


def _profile_payload(item: ScreeningProfile) -> dict[str, object]:
    return {
        "id": item.profile_key,
        "disease": item.disease_key,
        "parameter": item.topic_key,
        "project": item.project_dir_name,
        "research_question": item.research_question,
        "query_date_from": item.query_date_from,
        "query_date_to": item.query_date_to,
    }


@profile.command("list")
@click.option("--disease", default=None, help="Filter by disease key")
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
def list_profiles(disease: str | None, json_output: bool):
    """List profile IDs accepted by workflow commands."""
    normalized_disease = (
        disease.strip().casefold().replace("-", "_").replace(" ", "_")
        if disease
        else None
    )
    profiles = sorted(
        (
            item
            for item in load_profile_registry().values()
            if normalized_disease is None or item.disease_key == normalized_disease
        ),
        key=lambda item: (item.disease_key, item.topic_key, item.project_number),
    )
    payload = [_profile_payload(item) for item in profiles]
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    table = Table(title="Review profiles", header_style=f"bold {ACCENT_BOLD}")
    table.add_column("ID", style=f"bold {ACCENT}")
    table.add_column("Disease")
    table.add_column("Parameter")
    table.add_column("Project")
    table.add_column("Query window")
    for item in profiles:
        date_range = (
            f"{item.query_date_from} to {item.query_date_to}"
            if item.query_date_from and item.query_date_to
            else "not configured"
        )
        table.add_row(
            item.profile_key,
            item.disease_key,
            item.topic_key,
            item.project_dir_name,
            date_range,
        )
    console.print(table)
    if not profiles:
        raise click.ClickException(f"No profiles match disease={disease!r}")


@profile.command("show")
@click.argument("profile_id")
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
def show_profile(profile_id: str, json_output: bool):
    """Show the review scope and retrieval window for one profile."""
    try:
        item = resolve_profile_context(profile_id)
    except KeyError as exc:
        raise click.ClickException(str(exc.args[0])) from exc

    payload = {
        **_profile_payload(item),
        "disease_focus": item.disease_focus,
        "disease_exclude": item.disease_exclude,
        "parameter_focus": item.parameter_focus,
        "parameter_exclude": item.parameter_exclude,
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    table = Table.grid(padding=(0, 2))
    table.add_column(style=f"bold {ACCENT}")
    table.add_column()
    for label, key in (
        ("ID", "id"),
        ("Disease", "disease"),
        ("Parameter", "parameter"),
        ("Project", "project"),
        ("Research question", "research_question"),
        ("Query start", "query_date_from"),
        ("Query end", "query_date_to"),
        ("Disease scope", "disease_focus"),
        ("Disease exclusions", "disease_exclude"),
        ("Parameter scope", "parameter_focus"),
        ("Parameter exclusions", "parameter_exclude"),
    ):
        table.add_row(label, str(payload[key] or "not configured"))
    console.print(table)


__all__ = ["profile"]
