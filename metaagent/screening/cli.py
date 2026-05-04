"""Screening workflow commands."""

from __future__ import annotations

import sys
from pathlib import Path

import click


from metaagent._cli_shared import (DEV_ROOT, REPO_ROOT, DISEASE_NAMES, TOPIC_NAMES, resolve_project_root, show_step, show_success, show_error, show_warning, show_command_header, StyledGroup, console, ACCENT, ACCENT_BOLD, ACCENT_DIM)


@click.group(cls=StyledGroup)
def screening():
    """Literature screening workflow: prepare → run → evaluate."""


# ── prepare ────────────────────────────────────────────────────────────
@screening.command("prepare")
@click.option("--project-root", default="", help="Repository root (auto-detected if empty)")
@click.option("--profile", "-p", required=True, help="Screening profile (P10, MP4, etc.)")
@click.option("--disease", default=None, help="Disease filter (covid19, mpox)")
@click.option("--topic", default="", help="Topic override")
@click.option("--query", default=None, help="PubMed search term")
@click.option("--date-range", default=None, help="Publication date filter")
@click.option("--retmax", default="all", help="Max records (int or 'all')")
@click.option("--raw-input", default="", help="Existing raw CSV to merge GT into")
@click.option("--output", default="", help="Output raw CSV path")
@click.option("--ground-truth", default="", help="Ground truth CSV path")
@click.option("--include-gt/--no-include-gt", default=False, help="Append GT PMIDs missing from raw")
@click.option("--fix-missing/--no-fix-missing", default=False, help="Fix missing Abstract/Keywords")
@click.option("--medline-only", is_flag=True, default=False, help="Restrict to MEDLINE indexed")
def prepare(project_root, profile, disease, topic, query, date_range, retmax,
            raw_input, output, ground_truth, include_gt, fix_missing, medline_only):
    """Prepare raw screening CSV from PubMed query."""
    argv = [
        "screening_prepare_raw.py",
        "--project-root", str(resolve_project_root() if not project_root else Path(project_root).resolve()),
        "--profile", profile,
    ]
    if topic:      argv += ["--topic", topic]
    if query:      argv += ["--query", query]
    if date_range: argv += ["--date-range", date_range]
    if retmax:     argv += ["--retmax", retmax]
    if raw_input:  argv += ["--raw-input", raw_input]
    if output:     argv += ["--output", output]
    if ground_truth: argv += ["--ground-truth", ground_truth]
    if include_gt: argv += ["--include-gt"]
    if fix_missing: argv += ["--fix-missing"]
    if medline_only: argv += ["--medline-only"]

    _run_script("screening_prepare_raw", argv)


# ── run ────────────────────────────────────────────────────────────────
@screening.command("run")
@click.option("--project-root", default="", help="Repository root")
@click.option("--profile", "-p", required=True, help="Screening profile (P10, MP4, etc.)")
@click.option("--disease", default=None, help="Disease filter")
@click.option("--topic", default="", help="Topic override")
@click.option("--batch-size", default=20, type=int, help="Papers per batch")
@click.option("--batch-concurrency", default=1, type=int, help="Concurrent batches")
@click.option("--model", default=None, help="Override model name")
@click.option("--strategy", default="5d", type=click.Choice(["5d", "binary", "binary_noguidance"]))
@click.option("--experiment", default=None, help="Experiment subdirectory")
@click.option("--auto-fulltext", is_flag=True, help="Auto-download full-text for no-abstract papers")
@click.option("--fulltext-only", is_flag=True, help="Skip title/abstract, only run full-text")
@click.option("--skip-no-abstract", is_flag=True, help="Route no-abstract papers to title-only")
@click.option("--resume-fulltext", is_flag=True, help="Resume from milestone, screen fulltext_eligible papers")
@click.option("--resume-possible-fulltext", is_flag=True, help="Stage 2: PMC-only full-text rescue for possible candidates")
@click.option("--resume-sp-fulltext", is_flag=True, help="Stage 2: PMC-only full-text for strong+possible")
def run(project_root, profile, disease, topic, batch_size, batch_concurrency,
        model, strategy, experiment, auto_fulltext, fulltext_only, skip_no_abstract,
        resume_fulltext, resume_possible_fulltext, resume_sp_fulltext):
    """Run LLM-based batch screening."""
    argv = [
        "screening_llm_batch.py",
        "--project-root", str(resolve_project_root() if not project_root else Path(project_root).resolve()),
        "--profile", profile,
        "--batch-size", str(batch_size),
        "--batch-concurrency", str(batch_concurrency),
        "--strategy", strategy,
    ]
    if topic:              argv += ["--topic", topic]
    if model:              argv += ["--model", model]
    if experiment:         argv += ["--experiment", experiment]
    if auto_fulltext:      argv += ["--auto-fulltext"]
    if fulltext_only:      argv += ["--fulltext-only"]
    if skip_no_abstract:   argv += ["--skip-no-abstract"]
    if resume_fulltext:    argv += ["--resume-fulltext"]
    if resume_possible_fulltext: argv += ["--resume-possible-fulltext"]
    if resume_sp_fulltext: argv += ["--resume-sp-fulltext"]

    _run_script("screening_llm_batch", argv)


# ── evaluate ───────────────────────────────────────────────────────────
@screening.command("evaluate")
@click.argument("subcommand", type=click.Choice([
    "search-coverage", "performance", "threshold-sweep", "retrieval-metrics"
]))
@click.option("--project-root", default="", help="Repository root")
@click.option("--profile", "-p", default=None, help="Screening profile")
@click.option("--disease", default=None, help="Disease filter")
@click.option("--topic", default="", help="Topic override")
@click.option("--ground-truth", default="", help="Ground truth CSV path")
@click.option("--screened-results", default="", help="Screened results CSV")
@click.option("--search-results", default="", help="Search results CSV")
@click.option("--bucket", default="possible", type=click.Choice(["strong", "possible"]))
@click.option("--axis", default=None, type=click.Choice(["disease", "parameter", "evidence", "population", "location"]))
@click.option("--values", default="1,2,3,4", help="Comma-separated threshold values for sweep")
@click.pass_context
def evaluate(ctx, subcommand, project_root, profile, disease, topic,
             ground_truth, screened_results, search_results, bucket, axis, values):
    """Evaluate screening results (search-coverage | performance | threshold-sweep | retrieval-metrics)."""
    argv = [subcommand]
    proj = str(resolve_project_root() if not project_root else Path(project_root).resolve())
    argv += ["--project-root", proj]
    if profile:          argv += ["--profile", profile]
    if topic:            argv += ["--topic", topic]
    if ground_truth:     argv += ["--ground-truth", ground_truth]
    if screened_results: argv += ["--screened-results", screened_results]
    if search_results:   argv += ["--search-results", search_results]
    if subcommand == "threshold-sweep":
        argv += ["--bucket", bucket]
        if axis: argv += ["--axis", axis]
        argv += ["--values", values]

    _run_script("screening_evaluation", argv)


# ── report ─────────────────────────────────────────────────────────────
@screening.command("report")
@click.option("--disease", default="covid19", type=click.Choice(DISEASE_NAMES))
@click.option("--root", default=None, help="GT_export root override")
@click.option("--topics", default="", help="Comma-separated topics (auto-detect if empty)")
@click.option("--out", default=None, help="Output directory")
@click.option("--with-plots/--no-plots", default=False, help="Generate PNG figures")
@click.option("--update-md/--no-update-md", default=False, help="Update drafts/result.md")
def report(disease, root, topics, out, with_plots, update_md):
    """Generate academic-style screening report with tables and figures."""
    argv = ["screening_report_academic.py", "--disease", disease]
    if root:       argv += ["--root", root]
    if topics:     argv += ["--topics", topics]
    if out:        argv += ["--out", out]
    if with_plots: argv += ["--with-plots"]
    if update_md:  argv += ["--update-md"]

    _run_script("screening_report_academic", argv)


# ── pipeline (combined: prepare + run + evaluate) ──────────────────────
@screening.command("pipeline")
@click.option("--project-root", default="", help="Repository root")
@click.option("--profile", "-p", required=True, help="Screening profile")
@click.option("--disease", default=None, help="Disease filter")
@click.option("--topic", default="", help="Topic override")
@click.option("--include-gt/--no-include-gt", default=False)
@click.option("--fix-missing/--no-fix-missing", default=False)
@click.option("--batch-size", default=10, type=int)
@click.option("--batch-concurrency", default=1, type=int)
@click.option("--auto-fulltext", is_flag=True)
@click.option("--fulltext-only", is_flag=True)
def pipeline(project_root, profile, disease, topic, include_gt, fix_missing,
             batch_size, batch_concurrency, auto_fulltext, fulltext_only):
    """Full screening pipeline: prepare → run → evaluate."""
    proj = str(resolve_project_root() if not project_root else Path(project_root).resolve())

    # Step 1: prepare
    show_step(1, 2, "Prepare raw CSV")
    prep_argv = ["--project-root", proj, "--profile", profile]
    if topic:       prep_argv += ["--topic", topic]
    if include_gt:  prep_argv += ["--include-gt"]
    if fix_missing: prep_argv += ["--fix-missing"]
    _run_script("screening_prepare_raw", prep_argv)

    # Step 2: run + evaluate
    show_step(2, 2, "LLM screening + evaluation")
    eval_argv = [
        "--project-root", proj, "--profile", profile,
        "--batch-size", str(batch_size),
        "--batch-concurrency", str(batch_concurrency),
        "--strategy", "5d",
    ]
    if topic:          eval_argv += ["--topic", topic]
    if auto_fulltext:  eval_argv += ["--auto-fulltext"]
    if fulltext_only:  eval_argv += ["--fulltext-only"]
    _run_script("screening_llm_batch", eval_argv)
    show_success("Pipeline complete")


# ── fulltext (batch) ───────────────────────────────────────────────────
@screening.command("fulltext")
@click.option("--project-root", default="", help="Repository root")
@click.option("--disease", default="covid19", type=click.Choice(DISEASE_NAMES))
@click.option("--dry-run", is_flag=True, help="Print commands without executing")
@click.option("--profiles", default=None, help="Override profile list (space-separated)")
def fulltext(project_root, disease, dry_run, profiles):
    """Batch second-stage fulltext screening for all profiles."""
    argv = ["--project-root", str(resolve_project_root() if not project_root else Path(project_root).resolve()),
            "--disease", disease]
    if dry_run:   argv += ["--dry-run"]
    if profiles:  argv += ["--profiles"] + profiles.split()

    _run_script("run_sp_fulltext_all", argv)


# ── optimize ───────────────────────────────────────────────────────────
@screening.command("optimize")
@click.option("--project-root", default="", help="Repository root")
@click.option("--profile", "-p", required=True)
@click.option("--topic", default="")
@click.option("--experiment", default=None)
@click.option("--min-recall", default=0.80, type=float)
@click.option("--max-iterations", default=5, type=int)
@click.option("--target-reduction", default=25, type=int, help="Target word-count reduction %")
@click.option("--seed", default=42, type=int)
def optimize(project_root, profile, topic, experiment, min_recall,
             max_iterations, target_reduction, seed):
    """Iteratively compress screening prompt while preserving recall."""
    argv = [
        "--project-root", str(resolve_project_root() if not project_root else Path(project_root).resolve()),
        "--profile", profile,
        "--min-recall", str(min_recall),
        "--max-iterations", str(max_iterations),
        "--target-reduction", str(target_reduction),
        "--seed", str(seed),
    ]
    if topic:      argv += ["--topic", topic]
    if experiment: argv += ["--experiment", experiment]

    _run_script("prompt_optimizer", argv)


# ── downstream ─────────────────────────────────────────────────────────
@screening.command("downstream")
@click.option("--screened-csv", required=True, help="Path to project_*_screened.csv")
@click.option("--gt-csv", required=True, help="Path to project_*_groundtruth.csv")
@click.option("--out-dir", required=True, help="Output directory")
@click.option("--project-name", default=None, help="Project label")
@click.option("--paper-pool-pdf-dir", default=None, help="Override PDF cache directory")
def downstream(screened_csv, gt_csv, out_dir, project_name, paper_pool_pdf_dir):
    """Prepare downstream robustness experiment assets."""
    argv = ["--screened-csv", screened_csv, "--gt-csv", gt_csv, "--out-dir", out_dir]
    if project_name:       argv += ["--project-name", project_name]
    if paper_pool_pdf_dir: argv += ["--paper-pool-pdf-dir", paper_pool_pdf_dir]

    _run_script("prepare_downstream_experiment", argv)


# ── Helper: run an existing CLI script via subprocess ────────────────────
def _run_script(script_name: str, argv: list[str]) -> None:
    """Run an existing argparse CLI script as a subprocess."""
    import subprocess

    script_map = {
        "screening_prepare_raw":    "screening_prepare_raw",
        "screening_llm_batch":      "screening_llm_batch",
        "screening_evaluation":     "screening_evaluation",
        "screening_report_academic": "screening_report_academic",
        "run_sp_fulltext_all":      "run_sp_fulltext_all",
        "prompt_optimizer":         "prompt_optimizer",
        "prepare_downstream_experiment": "prepare_downstream_experiment",
    }

    scripts_dir = DEV_ROOT / "tools" / "scripts"
    script_path = scripts_dir / f"{script_name}.py"

    if not script_path.exists():
        raise click.ClickException(f"Script not found: {script_path}")

    result = subprocess.run(
        [sys.executable, str(script_path)] + argv,
        cwd=str(DEV_ROOT),
    )
    if result.returncode != 0:
        raise click.ClickException(f"Script exited with code {result.returncode}")