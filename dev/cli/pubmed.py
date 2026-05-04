"""PubMed data management commands."""

from __future__ import annotations

import sys
import subprocess

import click

from cli.utils import resolve_project_root


@click.group()
def pubmed():
    """PubMed data management tools."""


# ── search ─────────────────────────────────────────────────────────────
@pubmed.command("search")
@click.option("--input", "-i", required=True, help="Title list file (.txt or .csv)")
@click.option("--output", "-o", required=True, help="Output CSV file")
@click.option("--focus", default="Epidemiology", help="Research focus label")
@click.option("--no-verify", is_flag=True, help="Skip verification step")
def search(input, output, focus, no_verify):
    """Search PubMed PMID by paper title."""
    argv = ["search-title", "--input", input, "--output", output, "--focus", focus]
    if no_verify: argv += ["--no-verify"]
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
    import subprocess

    proj = resolve_project_root()
    script_path = proj / "dev" / "literature_search" / "scripts" / "tools" / "pubmed_manager.py"
    if not script_path.exists():
        raise click.ClickException(f"Script not found: {script_path}")

    result = subprocess.run(
        [sys.executable, str(script_path)] + argv,
        cwd=str(proj / "dev"),
    )
    if result.returncode != 0:
        raise click.ClickException(f"Script exited with code {result.returncode}")