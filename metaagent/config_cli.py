"""Preflight checks for a reproducible MetaAgent-Epi run."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import click
from rich.table import Table

from metaagent._cli_shared import (
    ACCENT,
    ACCENT_BOLD,
    StyledGroup,
    console,
    resolve_project_root,
)
from metaagent.config import (
    is_usable_secret,
    load_llm_config,
    load_mineru_config,
    load_runtime_env,
)


@click.group(cls=StyledGroup)
def config():
    """Inspect runtime configuration without exposing credentials."""


def _llm_check(module: str) -> dict[str, Any]:
    cfg = load_llm_config(module_hint=module)
    missing = []
    if not cfg.model:
        missing.append(f"{module.upper()}_LLM_MODEL")
    if not is_usable_secret(cfg.api_key):
        missing.append("provider API key")
    if cfg.provider not in {None, "openai"} and not cfg.api_base:
        missing.append("provider base URL")
    return {
        "component": f"{module} LLM",
        "status": "ready" if not missing else "missing",
        "required": True,
        "detail": (
            f"{cfg.provider or 'default'}/{cfg.model or 'model not set'}"
            if not missing
            else "Set " + ", ".join(missing) + " in .env.local"
        ),
    }


def _mineru_check() -> dict[str, Any]:
    cfg = load_mineru_config(module_hint="coding")
    ready = is_usable_secret(cfg.api_key)
    return {
        "component": "PDF parser",
        "status": "ready" if ready else "missing",
        "required": True,
        "detail": (
            f"MinerU endpoint: {cfg.base_url}"
            if ready
            else "Set MINERU_API_KEY; cached Markdown can bypass PDF parsing"
        ),
    }


def _ncbi_check() -> dict[str, Any]:
    email = os.getenv("NCBI_EMAIL", "").strip()
    api_key = os.getenv("NCBI_API_KEY", "").strip()
    ready = bool(email and is_usable_secret(api_key))
    return {
        "component": "NCBI",
        "status": "ready" if ready else "optional",
        "required": False,
        "detail": (
            "Email and API key configured"
            if ready
            else "Set NCBI_EMAIL and NCBI_API_KEY for sustained retrieval"
        ),
    }


def _profile_checks(profile_id: str, root: Path, stage: str) -> list[dict[str, Any]]:
    from metaagent.screening.profile_registry import resolve_profile_context
    from metaagent.workflow import resolve_coding_config_files

    try:
        item = resolve_profile_context(profile_id)
    except KeyError as exc:
        return [
            {
                "component": "profile",
                "status": "missing",
                "required": True,
                "detail": str(exc.args[0]),
            }
        ]

    checks = []
    if stage in {"all", "query"}:
        dates_ready = bool(item.query_date_from and item.query_date_to)
        checks.append(
            {
                "component": "query window",
                "status": "ready" if dates_ready else "missing",
                "required": True,
                "detail": (
                    f"{item.query_date_from} to {item.query_date_to}"
                    if dates_ready
                    else f"Add query_date_from/query_date_to to profile {item.profile_key}"
                ),
            }
        )
    if stage in {"all", "coding"}:
        codebook, required_files = resolve_coding_config_files(
            root,
            item.disease_key,
            item.topic_key,
        )
        missing_files = [path for path in required_files if not path.exists()]
        checks.append(
            {
                "component": "coding schema",
                "status": "ready" if not missing_files else "missing",
                "required": True,
                "detail": (
                    str(codebook)
                    if not missing_files
                    else "Missing " + ", ".join(str(path) for path in missing_files)
                ),
            }
        )
    return checks


@config.command("check")
@click.option("--profile", "profile_id", default=None, help="Also validate one review profile")
@click.option(
    "--stage",
    type=click.Choice(["all", "query", "screening", "coding"]),
    default="all",
    show_default=True,
    help="Limit checks to one workflow stage",
)
@click.option("--project-root", default="", help="Repository root (auto-detected if empty)")
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
@click.pass_context
def check_config(
    ctx: click.Context,
    profile_id: str | None,
    stage: str,
    project_root: str,
    json_output: bool,
):
    """Check models, credentials, services, and optional profile files."""
    load_runtime_env()
    root = (
        resolve_project_root()
        if not project_root
        else Path(project_root).expanduser().resolve()
    )
    modules = ["query", "screening", "coding"] if stage == "all" else [stage]
    checks = [_llm_check(module) for module in modules]
    if stage in {"all", "coding"}:
        checks.append(_mineru_check())
    if stage in {"all", "query"}:
        checks.append(_ncbi_check())
    if profile_id:
        checks.extend(_profile_checks(profile_id, root, stage))

    ready = all(item["status"] != "missing" for item in checks if item["required"])
    payload = {"ready": ready, "stage": stage, "profile": profile_id, "checks": checks}
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
    else:
        table = Table(title="Configuration check", header_style=f"bold {ACCENT_BOLD}")
        table.add_column("Component", style=f"bold {ACCENT}")
        table.add_column("Status")
        table.add_column("Detail")
        for item in checks:
            table.add_row(item["component"], item["status"], item["detail"])
        console.print(table)
        if ready:
            console.print("\n[green]Configuration is ready for the selected stage.[/green]")
        else:
            console.print(
                "\n[yellow]Complete the missing required values in .env.local, "
                "then run this check again.[/yellow]"
            )
    if not ready:
        ctx.exit(1)


__all__ = ["config"]
