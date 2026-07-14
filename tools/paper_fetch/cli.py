"""Full-text PDF retrieval commands."""

from __future__ import annotations

import json
import sys
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table

from metaagent._cli_shared import (
    ACCENT,
    ACCENT_DIM,
    StyledGroup,
    console,
    resolve_project_root,
    show_success,
)
from tools.paper_fetch.workflow import (
    default_fetch_input,
    load_pdf_records,
    project_fetch_dir,
    save_fetch_plan,
    save_fetch_results,
)


@click.group(cls=StyledGroup)
def pdf():
    """Full-text PDF retrieval and cache management."""


def _prompt(label: str, *, default: str | None = None, value_type=None) -> str:
    return click.prompt(
        click.style(label, fg="cyan", bold=True),
        default=default,
        type=value_type or str,
        show_default=default is not None,
    )


def _parse_tiers(value: str | None) -> tuple[str, ...] | None:
    text = str(value or "all").strip()
    if text.casefold() == "all":
        return None
    tiers = tuple(dict.fromkeys(part.strip().upper() for part in text.split(",") if part.strip()))
    invalid = [tier for tier in tiers if tier not in {"S", "P", "U"}]
    if invalid:
        raise click.BadParameter(
            "tiers must be a comma-separated subset of S,P,U or 'all'",
            param_hint="--tiers",
        )
    return tiers or None


def _show_plan_summary(
    *,
    input_path: Path,
    output_dir: Path,
    pdf_cache_dir: Path,
    source: str,
    tiers: tuple[str, ...] | None,
    strategy: str,
    count: int,
) -> None:
    details = Table.grid(padding=(0, 2))
    details.add_column(style="bold cyan")
    details.add_column(style="white")
    details.add_row("Input", str(input_path))
    details.add_row("Source", source)
    details.add_row("Tiers", ", ".join(tiers) if tiers else "all")
    details.add_row("Selected PMIDs", str(count))
    details.add_row("Retrieval", strategy)
    details.add_row("PDF cache", str(pdf_cache_dir))
    details.add_row("Project records", str(output_dir))
    console.print(
        Panel(
            details,
            title="[bold]Full-text fetch plan[/bold]",
            border_style=ACCENT,
            padding=(1, 2),
        )
    )


@pdf.command("fetch")
@click.option("--disease", help="Target disease or pathogen")
@click.option("--parameter", help="Target epidemiological parameter")
@click.option("--project-id", default=None, help="Review task identifier (default: p1)")
@click.option(
    "--source",
    type=click.Choice(["screened", "raw", "custom"]),
    default=None,
    help="Select records from screening output, raw retrieval, or a custom file.",
)
@click.option(
    "--input",
    "input_path",
    type=click.Path(path_type=Path, dir_okay=False, readable=True),
    help="Explicit CSV or PMID text file; required for source=custom.",
)
@click.option("--column", "pmid_column", default=None, help="CSV column containing PMIDs")
@click.option("--tier-column", default=None, help="CSV column containing S/P/U labels")
@click.option("--tiers", default=None, help="Screening tiers to fetch: S,P,U or all")
@click.option(
    "--strategy",
    type=click.Choice(["pmc-only", "pmc-first", "cache-only"]),
    default="pmc-only",
    show_default=True,
    help="Full-text retrieval strategy; pmc-only is the open-access default.",
)
@click.option(
    "--paper-pool",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Shared paper-pool root (default: <project>/paper_pool).",
)
@click.option("--download/--no-download", default=None, help="Run retrieval after saving the plan")
@click.option("--interactive/--no-interactive", default=None, help="Enable or disable the guided wizard")
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
def fetch(
    disease,
    parameter,
    project_id,
    source,
    input_path,
    pmid_column,
    tier_column,
    tiers,
    strategy,
    paper_pool,
    download,
    interactive,
    json_output,
):
    """Select project records and fetch their PDFs into the shared cache.

    Run without options for a guided workflow. Screened inputs default to
    strong and possible candidates (S+P); raw/custom inputs default to all.
    The PMID list and status manifest are saved under paper_pool/projects/.
    """
    if interactive is None:
        interactive = sys.stdin.isatty()
    root = resolve_project_root()

    if interactive and not json_output:
        console.print(
            Panel(
                "Choose a project and record source. PDFs are deduplicated in the shared "
                "[bold]paper_pool/pdfs[/bold] cache.",
                title="[bold]Prepare full text[/bold]",
                border_style=ACCENT,
                padding=(1, 2),
            )
        )
    if interactive:
        disease = disease or _prompt("Disease or pathogen")
        parameter = parameter or _prompt("Epidemiological parameter")
        project_id = project_id or _prompt("Project ID", default="p1")
        source = source or _prompt(
            "Record source",
            default="screened",
            value_type=click.Choice(["screened", "raw", "custom"]),
        )
        if source == "custom" and input_path is None:
            input_path = Path(_prompt("Input CSV or PMID text file"))
    else:
        missing = [
            name
            for name, value in {
                "--disease": disease,
                "--parameter": parameter,
                "--source": source,
            }.items()
            if not value
        ]
        if missing:
            raise click.UsageError(
                "Missing required options in non-interactive mode: " + ", ".join(missing)
            )

    project_id = project_id or "p1"
    source = source or "screened"
    if source == "custom" and input_path is None:
        raise click.UsageError("--input is required when --source=custom")
    if input_path is None:
        try:
            input_path = default_fetch_input(
                project_root=root,
                disease=disease,
                parameter=parameter,
                project_id=project_id,
                source=source,
            )
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
    input_path = input_path.expanduser().resolve()

    if tiers is None:
        tiers = "S,P" if source == "screened" else "all"
    parsed_tiers = _parse_tiers(tiers)
    paper_pool = (paper_pool or (root / "paper_pool")).expanduser().resolve()
    pdf_cache_dir = paper_pool / "pdfs"
    output_dir = project_fetch_dir(
        paper_pool=paper_pool,
        disease=disease,
        parameter=parameter,
        project_id=project_id,
    )

    try:
        records = load_pdf_records(
            input_path,
            tiers=parsed_tiers,
            pmid_column=pmid_column,
            tier_column=tier_column,
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if not records:
        raise click.ClickException("No PMIDs matched the selected source and tiers")

    pmids_path, plan_path = save_fetch_plan(
        records=records,
        output_dir=output_dir,
        input_path=input_path,
        source=source,
        tiers=parsed_tiers,
        strategy=strategy,
        pdf_cache_dir=pdf_cache_dir,
    )
    if not json_output:
        _show_plan_summary(
            input_path=input_path,
            output_dir=output_dir,
            pdf_cache_dir=pdf_cache_dir,
            source=source,
            tiers=parsed_tiers,
            strategy=strategy,
            count=len(records),
        )
        show_success("Saved pmids.txt and fetch_plan.json")

    if download is None:
        download = click.confirm("Fetch PDFs now?", default=False) if interactive else False

    statuses: dict[str, dict[str, str]] = {}
    result_path: Path | None = None
    if download:
        from metaagent.config import load_runtime_env
        from metaagent.screening.fulltext_pipeline import download_pdfs_batch

        load_runtime_env()
        overrides = {
            record.pmid: {"doi": record.doi, "pmcid": record.pmcid}
            for record in records
        }
        output_stream = sys.stderr if json_output else sys.stdout
        with redirect_stdout(output_stream):
            statuses = download_pdfs_batch(
                [record.pmid for record in records],
                overrides,
                source_strategy=strategy.replace("-", "_"),
                pdf_cache_dir=pdf_cache_dir,
                prompt_for_manual=False,
            )
        result_path = save_fetch_results(
            records=records,
            statuses=statuses,
            output_dir=output_dir,
        )
        if not json_output:
            counts = Counter(info.get("status", "unknown") for info in statuses.values())
            summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
            show_success(f"Fetch complete: {summary}")
            console.print(f"[{ACCENT_DIM}]Status manifest: {result_path}[/{ACCENT_DIM}]")

    payload = {
        "disease": disease,
        "parameter": parameter,
        "project_id": project_id,
        "source": source,
        "tiers": list(parsed_tiers or []),
        "strategy": strategy,
        "selected_pmids": len(records),
        "download_started": bool(download),
        "files": {
            "pmids": str(pmids_path),
            "plan": str(plan_path),
            "results": str(result_path) if result_path else None,
            "pdf_cache": str(pdf_cache_dir),
        },
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
