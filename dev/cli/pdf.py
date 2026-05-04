"""PDF fetch and management commands."""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

import click

from cli.utils import DEV_ROOT, resolve_project_root


@click.group()
def pdf():
    """PDF fetch and conversion tools."""


# ── fetch ──────────────────────────────────────────────────────────────
@pdf.command("fetch")
@click.option("--input", "-i", required=True, help="Input CSV with PMIDs or DOIs")
@click.option("--input-type", default="auto", type=click.Choice(["auto", "doi", "pmid"]),
              help="Input type detection mode")
@click.option("--column", default=None, help="Column name containing identifiers")
@click.option("--download/--no-download", default=False, help="Actually download PDFs")
def fetch(input, input_type, column, download):
    """Fetch PDF URLs from Sci-Hub and optionally download."""
    argv = ["--input", input, "--input-type", input_type]
    if column:   argv += ["--column", column]
    if download: argv += ["--download"]

    proj = resolve_project_root()
    script_path = proj / "dev" / "tools" / "paper_fetch" / "pdf_fetcher.py"
    if not script_path.exists():
        raise click.ClickException(f"Script not found: {script_path}")

    result = subprocess.run(
        [sys.executable, str(script_path)] + argv,
        cwd=str(proj / "dev"),
    )
    if result.returncode != 0:
        raise click.ClickException(f"Script exited with code {result.returncode}")