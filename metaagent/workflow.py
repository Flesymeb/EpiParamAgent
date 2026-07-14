"""Cross-stage workflow inspection and resume guidance."""

from __future__ import annotations

import csv
import json
import shlex
from collections import Counter
from pathlib import Path
from typing import Any

import click
import yaml
from rich.table import Table

from metaagent._cli_shared import (
    ACCENT,
    ACCENT_BOLD,
    StyledGroup,
    console,
    resolve_project_root,
)
from tools.pubmed.metadata import inspect_csv_metadata


@click.group(cls=StyledGroup)
def workflow():
    """Inspect a review workflow and resume it from the next incomplete stage."""


def _stage(status: str, artifact: Path | None, detail: str) -> dict[str, Any]:
    return {
        "status": status,
        "artifact": str(artifact) if artifact else None,
        "detail": detail,
    }


def _newest_file(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    candidates = [path for path in root.glob(pattern) if path.is_file()]
    return max(candidates, key=lambda path: path.stat().st_mtime_ns) if candidates else None


def _nonempty_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _coding_config_files(root: Path, disease: str, topic: str) -> tuple[Path, list[Path]]:
    codebook = root / "configs" / disease / "codebooks" / f"{topic}.yaml"
    prompts_dir = root / "configs" / disease / "coding_prompts"
    required = [codebook, prompts_dir / "stage_a.yaml"]
    if codebook.exists():
        try:
            payload = yaml.safe_load(codebook.read_text(encoding="utf-8")) or {}
            for stage_name in ("stage_a", "stage_b"):
                prompt_file = (payload.get(stage_name) or {}).get("prompt_file")
                if prompt_file:
                    candidate = Path(str(prompt_file))
                    if not candidate.is_absolute():
                        candidate = (codebook.parent / candidate).resolve()
                    required.append(candidate)
        except (OSError, yaml.YAMLError, AttributeError):
            pass
    return codebook, required


def _quoted_command(parts: list[str | Path]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


@workflow.command("status")
@click.option("--profile", "-p", required=True, help="Review profile (AI1, AIR1, P10, etc.)")
@click.option("--project-root", default="", help="Repository root (auto-detected if empty)")
@click.option(
    "--raw-csv",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Existing raw.csv to use instead of the profile dataset path.",
)
@click.option(
    "--screened-csv",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Existing screened CSV to inspect instead of the profile output path.",
)
@click.option(
    "--paper-pool",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Paper-pool root (default: <project>/paper_pool).",
)
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
def status(profile, project_root, raw_csv, screened_csv, paper_pool, json_output):
    """Show completed artifacts and the exact command for the next stage."""
    from metaagent.screening.profile_registry import (
        resolve_profile_context,
        resolve_profile_paths,
    )

    root = (
        resolve_project_root()
        if not project_root
        else Path(project_root).expanduser().resolve()
    )
    try:
        resolved = resolve_profile_context(profile)
        _, paths = resolve_profile_paths(
            project_root=root,
            profile_name=resolved.profile_key,
        )
    except (KeyError, ValueError) as exc:
        raise click.UsageError(str(exc)) from exc

    raw_path = (raw_csv or paths.raw_file).expanduser().resolve()
    screened_path = (screened_csv or paths.screened_file).expanduser().resolve()
    pool_root = (paper_pool or (root / "paper_pool")).expanduser().resolve()
    fetch_dir = (
        pool_root
        / "projects"
        / resolved.disease_key
        / resolved.topic_key
        / resolved.project_dir_name
    )
    pmids_path = fetch_dir / "pmids.txt"
    fetch_results = fetch_dir / "fetch_results.csv"
    coding_project = (
        root
        / "evaluation"
        / "coding"
        / resolved.disease_key
        / resolved.topic_key
        / resolved.project_dir_name
    )
    coding_sheet = _newest_file(coding_project / "coding_runs", "*/coding_sheet*.xlsx")
    pooled_path = coding_project / "pooled_summary.csv"

    codebook, config_files = _coding_config_files(
        root,
        resolved.disease_key,
        resolved.topic_key,
    )
    missing_config = [path for path in config_files if not path.exists()]
    stages: dict[str, dict[str, Any]] = {}
    stages["configuration"] = _stage(
        "ready" if not missing_config else "blocked",
        codebook,
        "Coding configuration is ready."
        if not missing_config
        else "Missing: " + ", ".join(str(path) for path in missing_config),
    )

    raw_count = _csv_rows(raw_path)
    stages["retrieval"] = _stage(
        "complete" if raw_count else "pending",
        raw_path,
        f"{raw_count} records" if raw_count else "No raw retrieval found.",
    )

    metadata_ready = False
    metadata_detail = "Waiting for raw.csv."
    if raw_count:
        try:
            metadata = inspect_csv_metadata(raw_path)
            marker = raw_path.with_name(f"{raw_path.stem}.metadata_enrichment.json")
            attempted = marker.exists() and marker.stat().st_mtime_ns >= raw_path.stat().st_mtime_ns
            gaps = metadata.needs_screening_enrichment or metadata.has_optional_gaps
            metadata_ready = not gaps or attempted
            metadata_detail = (
                f"missing title={metadata.missing_title}, abstract={metadata.missing_abstract}, "
                f"keywords={metadata.missing_keywords}"
            )
            if attempted and gaps:
                metadata_detail += "; PubMed completion already attempted"
        except (OSError, ValueError, csv.Error) as exc:
            metadata_detail = f"Cannot inspect metadata: {exc}"
    stages["metadata"] = _stage(
        "complete" if metadata_ready else ("pending" if raw_count else "blocked"),
        raw_path if raw_count else None,
        metadata_detail,
    )

    screened_count = _csv_rows(screened_path)
    screening_fresh = bool(
        raw_count
        and screened_count
        and screened_path.stat().st_mtime_ns >= raw_path.stat().st_mtime_ns
    )
    stages["screening"] = _stage(
        "complete" if screening_fresh else ("stale" if screened_count else "pending"),
        screened_path,
        f"{screened_count} decisions"
        if screening_fresh
        else ("Screening output predates raw.csv." if screened_count else "No screening output found."),
    )

    selected_count = _nonempty_lines(pmids_path)
    plan_fresh = bool(
        selected_count
        and screening_fresh
        and pmids_path.stat().st_mtime_ns >= screened_path.stat().st_mtime_ns
    )
    fetch_detail = f"{selected_count} selected PMIDs"
    fetch_attempt_count = 0
    fetch_results_fresh = False
    if fetch_results.exists():
        with fetch_results.open("r", encoding="utf-8-sig", newline="") as handle:
            fetch_rows = list(csv.DictReader(handle))
        fetch_attempt_count = len(fetch_rows)
        fetch_counts = Counter(str(row.get("status", "unknown")) for row in fetch_rows)
        fetch_results_fresh = bool(
            plan_fresh
            and fetch_attempt_count >= selected_count
            and fetch_results.stat().st_mtime_ns >= pmids_path.stat().st_mtime_ns
        )
        fetch_detail += (
            f"; PDFs downloaded={fetch_counts.get('downloaded', 0)}/{len(fetch_rows)}"
        )
    elif selected_count:
        fetch_detail += "; retrieval has not been run"
    fetch_fresh = fetch_results_fresh
    stages["full_text"] = _stage(
        "complete"
        if fetch_fresh
        else ("stale" if fetch_results.exists() else "pending"),
        fetch_results if fetch_results.exists() else pmids_path,
        fetch_detail if selected_count else "No S+P full-text plan found.",
    )

    coding_fresh = bool(
        coding_sheet
        and fetch_fresh
        and coding_sheet.stat().st_mtime_ns >= pmids_path.stat().st_mtime_ns
    )
    if missing_config:
        coding_status = "blocked"
        coding_detail = "Coding configuration is incomplete."
    elif coding_fresh:
        coding_status = "complete"
        coding_detail = "Latest coding sheet is current."
    elif coding_sheet:
        coding_status = "stale"
        coding_detail = "Coding output predates the current PMID selection."
    else:
        coding_status = "pending"
        coding_detail = "No coding sheet found."
    stages["coding"] = _stage(coding_status, coding_sheet, coding_detail)

    pooling_fresh = bool(
        pooled_path.exists()
        and coding_fresh
        and pooled_path.stat().st_mtime_ns >= coding_sheet.stat().st_mtime_ns
    )
    stages["pooling"] = _stage(
        "complete" if pooling_fresh else ("stale" if pooled_path.exists() else "pending"),
        pooled_path,
        "Pooled estimate is current."
        if pooling_fresh
        else ("Pooled estimate predates coding output." if pooled_path.exists() else "No pooled summary found."),
    )

    root_args = ["--project-root", root] if project_root else []
    if not raw_count:
        current_stage = "retrieval"
        next_command = _quoted_command(
            ["metaagent", "pubmed", "query", "--profile", resolved.profile_key, *root_args]
        )
    elif not metadata_ready:
        current_stage = "metadata"
        next_command = _quoted_command(
            ["metaagent", "pubmed", "metadata", "complete", "--input", raw_path]
        )
    elif not screening_fresh:
        current_stage = "screening"
        command: list[str | Path] = [
            "metaagent",
            "screening",
            "run",
            "--profile",
            resolved.profile_key,
            *root_args,
        ]
        if raw_csv is not None:
            command.extend(["--input", raw_path])
        next_command = _quoted_command(command)
    elif not fetch_fresh:
        current_stage = "full_text"
        command = ["metaagent", "pdf", "fetch", "--profile", resolved.profile_key]
        if project_root:
            command.extend(["--project-root", root])
        if screened_csv is not None:
            command.extend(["--input", screened_path])
        if paper_pool is not None:
            command.extend(["--paper-pool", pool_root])
        command.append("--download")
        next_command = _quoted_command(command)
    elif missing_config:
        current_stage = "coding_configuration"
        next_command = None
    elif not coding_fresh:
        current_stage = "coding"
        command = ["metaagent", "coding", "extract", "--profile", resolved.profile_key]
        if paper_pool is not None:
            command.extend(["--paper-pool", pool_root])
        next_command = _quoted_command(command)
    elif not pooling_fresh:
        current_stage = "pooling"
        next_command = _quoted_command(
            ["metaagent", "coding", "evaluate", "--profile", resolved.profile_key]
        )
    else:
        current_stage = "complete"
        next_command = None

    payload = {
        "profile": resolved.profile_key,
        "disease": resolved.disease_key,
        "parameter": resolved.topic_key,
        "project": resolved.project_dir_name,
        "current_stage": current_stage,
        "next_command": next_command,
        "stages": stages,
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    table = Table(title=f"Workflow status: {resolved.profile_key}", header_style=f"bold {ACCENT_BOLD}")
    table.add_column("Stage", style=f"bold {ACCENT}")
    table.add_column("Status")
    table.add_column("Detail")
    for name, stage in stages.items():
        table.add_row(name.replace("_", " ").title(), stage["status"], stage["detail"])
    console.print(table)
    if next_command:
        console.print(f"\n[bold]Next command[/bold]\n[cyan]{next_command}[/cyan]")
    elif current_stage == "complete":
        console.print("\n[green]Workflow artifacts are current.[/green]")
    else:
        console.print("\n[yellow]Add the missing coding configuration before continuing.[/yellow]")


__all__ = ["workflow"]
