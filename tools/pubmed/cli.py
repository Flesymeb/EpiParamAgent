"""PubMed data management commands."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import click
from pydantic import ValidationError
from rich.panel import Panel
from rich.table import Table

from metaagent._cli_shared import (
    ACCENT,
    ACCENT_BOLD,
    ACCENT_DIM,
    StyledGroup,
    console,
    resolve_project_root,
    show_success,
    show_warning,
)
from tools.pubmed.metadata import (
    MetadataCompleteness,
    MetadataCompletionResult,
    complete_csv_metadata,
    inspect_csv_metadata,
)
from tools.pubmed.query_generator import (
    PubMedQueryGenerator,
    PubMedQueryRequest,
    create_manual_query_artifact,
    default_output_dir,
    save_query_artifact,
    search_pubmed_to_csv,
)


@click.group(cls=StyledGroup)
def pubmed():
    """PubMed data management tools."""


class ISODateType(click.ParamType):
    """Click parameter type for strict ISO calendar dates."""

    name = "YYYY-MM-DD"

    def convert(self, value, param, ctx):
        """Validate and preserve a strict ISO date string."""
        if value is None:
            return None
        text = str(value).strip()
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            self.fail("Date must use YYYY-MM-DD and be a valid calendar date", param, ctx)
        return text


ISO_DATE = ISODateType()


def _parse_retmax(value: str | None) -> int | None:
    text = str(value or "all").strip().lower()
    if text == "all":
        return None
    try:
        parsed = int(text)
    except ValueError as exc:
        raise click.BadParameter("must be a positive integer or 'all'", param_hint="--retmax") from exc
    if parsed <= 0:
        raise click.BadParameter("must be a positive integer or 'all'", param_hint="--retmax")
    return parsed


def _prompt(label: str, *, default: str | None = None, value_type=None) -> str:
    return click.prompt(
        click.style(label, fg="cyan", bold=True),
        default=default,
        type=value_type or str,
        show_default=default is not None,
    )


def _show_query_summary(artifact, output_dir: Path) -> None:
    details = Table.grid(padding=(0, 2))
    details.add_column(style=f"bold {ACCENT_BOLD}")
    details.add_column(style="white")
    details.add_row("Disease", artifact.request.disease)
    details.add_row("Parameter", artifact.request.parameter)
    details.add_row(
        "Date range",
        f"{artifact.request.start_date.isoformat()} to {artifact.request.end_date.isoformat()}",
    )
    details.add_row("Model", f"{artifact.provider}/{artifact.model}")
    details.add_row("Saved to", str(output_dir))
    console.print(
        Panel(
            details,
            title="[bold]PubMed query ready[/bold]",
            border_style=ACCENT,
            padding=(1, 2),
        )
    )
    console.print(
        Panel(
            artifact.query,
            title="[bold]Copy-ready query[/bold]",
            border_style=ACCENT_DIM,
            padding=(1, 2),
        )
    )
    for warning in artifact.terms.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")


def _metadata_payload(summary: MetadataCompleteness) -> dict[str, int]:
    """Return stable metadata counts for JSON output."""
    return summary.as_dict()


def _show_metadata_summary(
    summary: MetadataCompleteness,
    path: Path,
    *,
    title: str = "PubMed metadata",
) -> None:
    """Display available and missing screening metadata."""
    table = Table(title=title, header_style=f"bold {ACCENT_BOLD}", border_style=ACCENT_DIM)
    table.add_column("Field", style=f"bold {ACCENT}")
    table.add_column("Available", justify="right")
    table.add_column("Missing", justify="right")
    for label, missing in (
        ("PMID", summary.missing_pmid),
        ("Title", summary.missing_title),
        ("Abstract", summary.missing_abstract),
        ("Keywords", summary.missing_keywords),
    ):
        available = max(0, summary.total_rows - missing)
        missing_style = "yellow" if missing else "green"
        table.add_row(label, str(available), f"[{missing_style}]{missing}[/{missing_style}]")
    console.print(table)
    console.print(f"[{ACCENT_DIM}]Records: {summary.total_rows}  •  File: {path}[/{ACCENT_DIM}]")


def _show_metadata_completion(result: MetadataCompletionResult) -> None:
    """Display before/after missing-field counts after completion."""
    table = Table(
        title="Metadata completion",
        header_style=f"bold {ACCENT_BOLD}",
        border_style=ACCENT_DIM,
    )
    table.add_column("Field", style=f"bold {ACCENT}")
    table.add_column("Before", justify="right")
    table.add_column("After", justify="right")
    table.add_column("Recovered", justify="right")
    for label, attr in (
        ("PMID", "missing_pmid"),
        ("Title", "missing_title"),
        ("Abstract", "missing_abstract"),
        ("Keywords", "missing_keywords"),
    ):
        before = getattr(result.before, attr)
        after = getattr(result.after, attr)
        table.add_row(label, str(before), str(after), str(max(0, before - after)))
    console.print(table)
    if result.backup_path:
        console.print(f"[{ACCENT_DIM}]Backup: {result.backup_path}[/{ACCENT_DIM}]")
    console.print(f"[{ACCENT_DIM}]Completion record: {result.marker_path}[/{ACCENT_DIM}]")
    if result.after.has_any_gaps:
        show_warning(
            "Some fields remain unavailable. PubMed does not provide abstracts or "
            "keywords for every record; these papers remain eligible for downstream handling."
        )


def _complete_metadata(path: Path, *, json_output: bool = False) -> MetadataCompletionResult:
    """Complete metadata with a visible status in human-facing mode."""
    if json_output:
        return complete_csv_metadata(path, quiet=True)
    with console.status("[bold cyan]Completing available metadata from PubMed...[/bold cyan]"):
        return complete_csv_metadata(path, quiet=True)


# ── query ──────────────────────────────────────────────────────────────
@pubmed.command("query")
@click.option("--profile", "-p", default=None, help="Review profile (AI1, AIR1, P10, etc.)")
@click.option("--project-root", default="", help="Repository root (auto-detected if empty)")
@click.option("--question", help="Systematic-review research question")
@click.option("--disease", help="Target disease or pathogen")
@click.option("--parameter", help="Target epidemiological parameter")
@click.option("--start-date", type=ISO_DATE, help="Publication start date (YYYY-MM-DD)")
@click.option("--end-date", type=ISO_DATE, help="Publication end date (YYYY-MM-DD)")
@click.option("--project-id", default=None, help="Review task identifier (default: p1)")
@click.option("--query", "custom_query", help="Use a user-authored final PubMed query")
@click.option(
    "--query-file",
    type=click.Path(path_type=Path, dir_okay=False, readable=True),
    help="Read the user-authored final PubMed query from a text file",
)
@click.option(
    "--manual-query",
    is_flag=True,
    help="Prompt for a final query instead of generating one with the LLM",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    help="Directory for query.json, query.txt, and optional raw.csv",
)
@click.option("--provider", default=None, help="Override the query LLM provider")
@click.option("--model", default=None, help="Override the query LLM model")
@click.option("--interactive/--no-interactive", default=None, help="Enable or disable the input wizard")
@click.option("--search/--no-search", "run_search", default=None, help="Run PubMed after saving the query")
@click.option("--retmax", default=None, help="Maximum PubMed records or 'all' (default: all)")
@click.option("--medline-only", is_flag=True, help="Restrict retrieval to MEDLINE-indexed records")
@click.option(
    "--fix-missing/--no-fix-missing",
    default=None,
    help="Complete available title, abstract, and keyword metadata after retrieval.",
)
@click.option("--force", is_flag=True, help="Replace existing query/raw files")
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
def query_command(
    profile,
    project_root,
    question,
    disease,
    parameter,
    start_date,
    end_date,
    project_id,
    custom_query,
    query_file,
    manual_query,
    output_dir,
    provider,
    model,
    interactive,
    run_search,
    retmax,
    medline_only,
    fix_missing,
    force,
    json_output,
):
    """Generate and save a reproducible PubMed query.

    Run without options for the guided wizard. For automation, provide all
    review fields with --no-interactive and choose --search or --no-search.
    Use --manual-query, --query, or --query-file to save a query you edited
    yourself while keeping the same project metadata and retrieval workflow.
    """
    if custom_query and query_file:
        raise click.UsageError("Use only one of --query and --query-file")
    if fix_missing is True and run_search is False:
        raise click.UsageError("--fix-missing requires --search")
    manual_mode = bool(manual_query or custom_query or query_file)
    if interactive is None:
        interactive = sys.stdin.isatty()
    if fix_missing is True and not interactive and run_search is not True:
        raise click.UsageError("--fix-missing requires --search in non-interactive mode")

    root = (
        resolve_project_root()
        if not project_root
        else Path(project_root).expanduser().resolve()
    )
    resolved_profile = None
    if profile:
        from metaagent.screening.profile_registry import (
            load_profile_project_metadata,
            resolve_profile_context,
        )

        try:
            resolved_profile = resolve_profile_context(
                profile,
                disease=disease,
                topic=parameter,
                project_id=project_id,
            )
            project_metadata = load_profile_project_metadata(
                project_root=root,
                profile=resolved_profile,
            )
        except (KeyError, ValueError) as exc:
            raise click.UsageError(str(exc)) from exc

        question = question or resolved_profile.research_question
        disease = disease or resolved_profile.disease_key.replace("_", " ")
        parameter = parameter or resolved_profile.topic_key.replace("_", " ")
        project_id = project_id or resolved_profile.project_dir_name
        start_date = (
            start_date
            or resolved_profile.query_date_from
            or project_metadata.get("query_date_from")
        )
        end_date = (
            end_date
            or resolved_profile.query_date_to
            or project_metadata.get("query_date_to")
        )

    required = {
        "--question": question,
        "--disease": disease,
        "--parameter": parameter,
        "--start-date": start_date,
        "--end-date": end_date,
    }
    if not interactive:
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise click.UsageError(
                "Missing required options in non-interactive mode: " + ", ".join(missing)
            )
    elif not json_output:
        console.print(
            Panel(
                "Enter the review scope below. Dates must use [bold]YYYY-MM-DD[/bold].\n"
                "The generated query is always saved before PubMed retrieval is offered.",
                title="[bold]New PubMed search[/bold]",
                border_style=ACCENT,
                padding=(1, 2),
            )
        )

    if interactive:
        question = question or _prompt("Research question")
        disease = disease or _prompt("Disease or pathogen")
        parameter = parameter or _prompt("Epidemiological parameter")
        start_date = start_date or _prompt("Start date", value_type=ISO_DATE)
        end_date = end_date or _prompt("End date", value_type=ISO_DATE)
        project_id = project_id or _prompt("Project ID", default="p1")
        if manual_mode and not custom_query and not query_file:
            custom_query = _prompt("Final PubMed query")
    else:
        project_id = project_id or "p1"
        if manual_mode and not custom_query and not query_file:
            raise click.UsageError(
                "Manual mode requires --query or --query-file in non-interactive mode"
            )

    try:
        request = PubMedQueryRequest(
            question=question,
            disease=disease,
            parameter=parameter,
            start_date=start_date,
            end_date=end_date,
            project_id=project_id,
        )
    except ValidationError as exc:
        raise click.UsageError(str(exc)) from exc

    if output_dir is None:
        if resolved_profile is not None:
            from metaagent.screening.profile_registry import resolve_profile_paths

            _, profile_paths = resolve_profile_paths(
                project_root=root,
                profile_name=resolved_profile.profile_key,
            )
            output_dir = profile_paths.project_dir
        else:
            output_dir = default_output_dir(
                project_root=root,
                disease=request.disease,
                parameter=request.parameter,
                project_id=request.project_id,
            )
    output_dir = output_dir.expanduser().resolve()

    query_files_exist = any((output_dir / name).exists() for name in ("query.json", "query.txt"))
    if query_files_exist and not force:
        if interactive and click.confirm("Replace existing query files?", default=False):
            force = True
        else:
            raise click.ClickException("Query files already exist; use --force to replace them")

    try:
        if manual_mode:
            if query_file:
                custom_query = query_file.read_text(encoding="utf-8")
            artifact = create_manual_query_artifact(request, custom_query or "")
        else:
            generator = PubMedQueryGenerator(provider=provider, model=model)
            if interactive and not json_output:
                with console.status("[bold cyan]Generating PubMed vocabulary...[/bold cyan]"):
                    artifact = generator.generate(request)
            else:
                artifact = generator.generate(request)
        json_path, text_path = save_query_artifact(artifact, output_dir, force=force)
    except (OSError, RuntimeError, ValueError, FileExistsError) as exc:
        raise click.ClickException(str(exc)) from exc

    if not json_output:
        _show_query_summary(artifact, output_dir)
        show_success("Saved query.json and query.txt")

    if run_search is None:
        run_search = click.confirm("Search PubMed now?", default=False) if interactive else False

    search_result = None
    metadata_result: MetadataCompletionResult | None = None
    metadata_before: MetadataCompleteness | None = None
    raw_path = output_dir / "raw.csv"
    if run_search:
        if raw_path.exists() and not force:
            if interactive and click.confirm("Replace existing raw.csv?", default=False):
                force = True
            else:
                raise click.ClickException("raw.csv already exists; use --force to replace it")
        if retmax is None and interactive:
            retmax = _prompt("Maximum records (integer or all)", default="all")
        limit = _parse_retmax(retmax)
        if not json_output:
            label = "all matching records" if limit is None else f"up to {limit} records"
            console.print(f"[{ACCENT_DIM}]Retrieving {label} from PubMed...[/{ACCENT_DIM}]")
        try:
            search_result = search_pubmed_to_csv(
                artifact.query,
                raw_path,
                retmax=limit,
                medline_only=medline_only,
            )
        except Exception as exc:
            raise click.ClickException(f"PubMed retrieval failed: {exc}") from exc
        if not json_output:
            show_success(
                f"Saved {search_result['retrieved']} records to {raw_path} "
                f"({search_result['total_matches']} total matches)"
            )

        try:
            metadata_before = inspect_csv_metadata(raw_path)
        except (OSError, ValueError) as exc:
            raise click.ClickException(f"Cannot inspect retrieved metadata: {exc}") from exc

        if not json_output:
            _show_metadata_summary(metadata_before, raw_path)

        enrichment_available = bool(
            metadata_before.needs_screening_enrichment
            or metadata_before.has_optional_gaps
        )
        should_complete = bool(fix_missing)
        if fix_missing is None and interactive and not json_output and enrichment_available:
            should_complete = click.confirm(
                "Complete available metadata from PubMed now?",
                default=True,
            )
        if should_complete and enrichment_available:
            try:
                metadata_result = _complete_metadata(raw_path, json_output=json_output)
            except Exception as exc:
                raise click.ClickException(f"PubMed metadata completion failed: {exc}") from exc
            if not json_output:
                _show_metadata_completion(metadata_result)
                show_success(f"Metadata-ready CSV: {raw_path}")

    if json_output:
        payload = artifact.model_dump(mode="json")
        payload["files"] = {
            "query_json": str(json_path),
            "query_text": str(text_path),
            "raw_csv": str(raw_path) if search_result is not None else None,
        }
        payload["search"] = search_result
        if metadata_before is None:
            payload["metadata"] = None
        elif metadata_result is not None:
            payload["metadata"] = metadata_result.as_dict()
        else:
            payload["metadata"] = {
                "attempted": False,
                "input": str(raw_path),
                "output": str(raw_path),
                "backup": None,
                "marker": None,
                "before": _metadata_payload(metadata_before),
                "after": _metadata_payload(metadata_before),
            }
        click.echo(json.dumps(payload, ensure_ascii=False))


# ── search ─────────────────────────────────────────────────────────────
@pubmed.command("search")
@click.option("--input", "-i", required=True, help="Title list file (.txt or .csv)")
@click.option("--output", "-o", required=True, help="Output CSV file")
@click.option("--focus", default="Epidemiology", help="Research focus label")
@click.option("--no-verify", is_flag=True, help="Skip verification step")
def search(input, output, focus, no_verify):
    """Search PubMed PMID by paper title."""
    argv = ["search-title", "--input", input, "--output", output, "--focus", focus]
    if no_verify:
        argv += ["--no-verify"]
    _run_pubmed_manager(argv)


# ── fetch ──────────────────────────────────────────────────────────────
@pubmed.command("fetch")
@click.option("--pmids", required=True, help="Comma-separated or file of PMIDs")
@click.option("--output", "-o", required=True, help="Output CSV file")
def fetch(pmids, output):
    """Batch-fetch paper details from PubMed."""
    argv = ["fetch", "--pmids", pmids, "--output", output]
    _run_pubmed_manager(argv)


# ── metadata ───────────────────────────────────────────────────────────
@pubmed.group("metadata", cls=StyledGroup)
def metadata_group():
    """Inspect or complete metadata used for screening."""


@metadata_group.command("inspect")
@click.option(
    "--input",
    "input_file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False, readable=True),
    required=True,
    help="PubMed CSV to inspect",
)
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable counts")
def metadata_inspect(input_file: Path, json_output: bool):
    """Report missing PMID, title, abstract, and keyword values."""
    try:
        summary = inspect_csv_metadata(input_file)
    except (OSError, ValueError) as exc:
        raise click.ClickException(f"Cannot inspect {input_file}: {exc}") from exc

    if json_output:
        click.echo(
            json.dumps(
                {"input": str(input_file.resolve()), **_metadata_payload(summary)},
                ensure_ascii=False,
            )
        )
        return
    _show_metadata_summary(summary, input_file.resolve(), title="Metadata completeness")


@metadata_group.command("complete")
@click.option(
    "--input",
    "input_file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False, readable=True),
    required=True,
    help="PubMed CSV containing incomplete metadata",
)
@click.option(
    "--output",
    "output_file",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Output CSV; defaults to an in-place update with backup",
)
@click.option("--backup/--no-backup", default=True, help="Back up an in-place input before updating")
@click.option("--force", is_flag=True, help="Replace an existing separate output file")
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
def metadata_complete(
    input_file: Path,
    output_file: Path | None,
    backup: bool,
    force: bool,
    json_output: bool,
):
    """Retrieve available missing metadata from PubMed EFetch."""
    source = input_file.expanduser().resolve()
    target = (output_file or source).expanduser().resolve()
    if target != source and target.exists() and not force:
        raise click.ClickException(
            f"Output already exists: {target}. Use --force to replace it."
        )

    try:
        before = inspect_csv_metadata(source)
    except (OSError, ValueError) as exc:
        raise click.ClickException(f"Cannot inspect {source}: {exc}") from exc
    if not json_output:
        _show_metadata_summary(before, source, title="Before metadata completion")

    try:
        if json_output:
            result = complete_csv_metadata(
                source,
                target,
                create_backup=backup,
                quiet=True,
            )
        else:
            with console.status(
                "[bold cyan]Completing available metadata from PubMed...[/bold cyan]"
            ):
                result = complete_csv_metadata(
                    source,
                    target,
                    create_backup=backup,
                    quiet=True,
                )
    except Exception as exc:
        raise click.ClickException(f"PubMed metadata completion failed: {exc}") from exc

    if json_output:
        click.echo(json.dumps(result.as_dict(), ensure_ascii=False))
        return
    _show_metadata_completion(result)
    show_success(f"Metadata-ready CSV: {result.output_path}")


# ── fix ────────────────────────────────────────────────────────────────
@pubmed.command("fix", hidden=True)
@click.option("--input", "-i", required=True, help="Input CSV with missing fields")
@click.option("--output", "-o", required=True, help="Output CSV with fixed fields")
def fix(input, output):
    """Legacy alias for metadata completion."""
    argv = ["fix-missing", "--input", input, "--output", output]
    _run_pubmed_manager(argv)


# ── enrich ─────────────────────────────────────────────────────────────
@pubmed.command("enrich")
@click.option("--input", "-i", required=True, help="Input CSV")
@click.option("--output", "-o", required=True, help="Output CSV with enriched abstracts")
def enrich(input, output):
    """Fill missing abstract fields via PubMed EFetch."""
    argv = ["enrich-abstracts", "--input", input, "--output", output]
    _run_pubmed_manager(argv)


# ── append ─────────────────────────────────────────────────────────────
@pubmed.command("append")
@click.option("--pmids", required=True, help="Comma-separated or file of PMIDs to add")
@click.option("--output", "-o", required=True, help="Existing CSV to append to")
def append(pmids, output):
    """Append new papers by PMID to an existing CSV."""
    argv = ["append", "--pmids", pmids, "--output", output]
    _run_pubmed_manager(argv)


# ── search-doi ─────────────────────────────────────────────────────────
@pubmed.command("search-doi")
@click.option("--input", "-i", required=True, help="DOI list file")
@click.option("--output", "-o", required=True, help="Output CSV")
@click.option("--column", default="DOI", help="Column name containing DOIs")
def search_doi(input, output, column):
    """Search PubMed PMID by DOI."""
    argv = ["search-doi", "--input", input, "--output", output, "--column", column]
    _run_pubmed_manager(argv)


# ── Helper ─────────────────────────────────────────────────────────────
def _run_pubmed_manager(argv: list[str]) -> None:
    """Run pubmed_manager.py as a subprocess."""
    import os
    import subprocess

    proj = resolve_project_root()
    script_path = proj / "tools" / "scripts" / "pubmed_manager.py"
    if not script_path.exists():
        raise click.ClickException(f"Script not found: {script_path}")

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(proj)
        if not env.get("PYTHONPATH")
        else f"{proj}{os.pathsep}{env['PYTHONPATH']}"
    )
    result = subprocess.run(
        [sys.executable, str(script_path)] + argv,
        cwd=str(proj),
        env=env,
    )
    if result.returncode != 0:
        raise click.ClickException(f"Script exited with code {result.returncode}")
