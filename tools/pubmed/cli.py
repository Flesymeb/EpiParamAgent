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


# ── query ──────────────────────────────────────────────────────────────
@pubmed.command("query")
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
@click.option("--force", is_flag=True, help="Replace existing query/raw files")
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
def query_command(
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
    manual_mode = bool(manual_query or custom_query or query_file)
    if interactive is None:
        interactive = sys.stdin.isatty()

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
        output_dir = default_output_dir(
            project_root=resolve_project_root(),
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

    if json_output:
        payload = artifact.model_dump(mode="json")
        payload["files"] = {
            "query_json": str(json_path),
            "query_text": str(text_path),
            "raw_csv": str(raw_path) if search_result is not None else None,
        }
        payload["search"] = search_result
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


# ── fix ────────────────────────────────────────────────────────────────
@pubmed.command("fix")
@click.option("--input", "-i", required=True, help="Input CSV with missing fields")
@click.option("--output", "-o", required=True, help="Output CSV with fixed fields")
def fix(input, output):
    """Fix missing abstract/keywords in PubMed CSV."""
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
