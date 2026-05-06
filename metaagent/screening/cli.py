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
@click.option("--profile", "-p", default=None, help="Screening profile (P10, MP4, etc.)")
@click.option("--disease", default=None, help="Disease filter")
@click.option("--topic", default="", help="Topic override")
@click.option("--input", "input_file", default="", help="Explicit input CSV")
@click.option("--output", "output_file", default="", help="Explicit output CSV")
@click.option("--ground-truth", default="", help="Explicit ground-truth CSV")
@click.option("--research-question", default="", help="Research question for explicit file mode")
@click.option("--batch-size", default=20, type=int, help="Papers per batch")
@click.option("--batch-concurrency", default=1, type=int, help="Concurrent batches")
@click.option("--model", default=None, help="Override model name")
@click.option("--provider", default=None, help="Override provider profile (openrouter, openai, lab, lab2)")
@click.option("--strategy", default="5d", type=click.Choice(["5d", "binary", "binary_noguidance", "binary_baseline", "peco"]))
@click.option("--experiment", default=None, help="Experiment subdirectory")
@click.option("--cascade", is_flag=True, help="Enable cascade screening (Tier1->Tier2->Tier3) with deep research retrieval")
@click.option("--auto-fulltext", is_flag=True, help="Auto-download full-text for no-abstract papers")
@click.option("--fulltext-only", is_flag=True, help="Skip title/abstract, only run full-text")
@click.option("--no-fulltext-rescue", is_flag=True, help="Disable profile full-text rescue policy")
@click.option("--skip-no-abstract", is_flag=True, help="Route no-abstract papers to title-only")
@click.option("--resume-fulltext", is_flag=True, help="Resume from milestone, screen fulltext_eligible papers")
@click.option("--resume-possible-fulltext", is_flag=True, help="Stage 2: PMC-only full-text rescue for possible candidates")
@click.option("--resume-sp-fulltext", is_flag=True, help="Stage 2: PMC-only full-text for strong+possible")
def run(project_root, profile, disease, topic, input_file, output_file,
        ground_truth, research_question, batch_size, batch_concurrency,
        model, provider, strategy, experiment, cascade, auto_fulltext, fulltext_only,
        no_fulltext_rescue, skip_no_abstract,
        resume_fulltext, resume_possible_fulltext, resume_sp_fulltext):
    """Run LLM-based batch screening with optional cascade retrieval."""
    if cascade:
        _run_cascade(project_root, profile, disease, topic, batch_size, batch_concurrency,
                     model, provider, strategy, experiment)
        return

    argv = [
        "--batch-size", str(batch_size),
        "--batch-concurrency", str(batch_concurrency),
        "--strategy", strategy,
    ]
    if project_root or profile:
        argv += ["--project-root", str(resolve_project_root() if not project_root else Path(project_root).resolve())]
    if profile:            argv += ["--profile", profile]
    if disease:            argv += ["--disease", disease]
    if topic:              argv += ["--topic", topic]
    if input_file:         argv += ["--input", input_file]
    if output_file:        argv += ["--output", output_file]
    if ground_truth:       argv += ["--ground-truth", ground_truth]
    if research_question:  argv += ["--research-question", research_question]
    if model:              argv += ["--model", model]
    if provider:           argv += ["--provider", provider]
    if experiment:         argv += ["--experiment", experiment]
    if auto_fulltext:      argv += ["--auto-fulltext"]
    if fulltext_only:      argv += ["--fulltext-only"]
    if no_fulltext_rescue: argv += ["--no-fulltext-rescue"]
    if skip_no_abstract:   argv += ["--skip-no-abstract"]
    if resume_fulltext:    argv += ["--resume-fulltext"]
    if resume_possible_fulltext: argv += ["--resume-possible-fulltext"]
    if resume_sp_fulltext: argv += ["--resume-sp-fulltext"]

    _run_script("screening_llm_batch", argv)


def _run_cascade(project_root, profile, disease, topic, batch_size, batch_concurrency,
                 model, provider, strategy, experiment):
    """Run cascade screening with Tier-2 PubMed/PMC enrichment."""
    import asyncio, csv
    from metaagent.config import load_llm_config
    from metaagent.screening.engine import init_llm_model, screen_papers_batch_async
    from metaagent.screening.staging import partition_papers, annotate_ground_truth
    from metaagent.screening.cascade import run_simple_cascade

    root = resolve_project_root()
    print(f"Starting cascade screening with strategy={strategy}")
    print(f"Project root: {root}")

    cfg = load_llm_config(
        {
            "llm_model": model,
            "llm_provider": provider,
        },
        module_hint="screening",
    )
    llm = init_llm_model(
        model_override=model or None,
        provider_override=provider or None,
    )
    print(f"Model: {cfg.provider or 'default'}/{cfg.model}")

    # Load input CSV (resolve from profile or explicit path)
    input_file = root / "evaluation" / "screening" / (disease or "covid19") / "raw.csv"
    if not input_file.exists():
        print(f"Warning: input file not found at {input_file}")
        print("Cascade mode requires a CSV with Title, Abstract, Keywords, PMID columns.")
        print("Run 'metaagent screening prepare' first.")
        return

    with open(input_file, encoding="utf-8-sig") as f:
        papers = list(csv.DictReader(f))
    print(f"Loaded {len(papers)} papers from {input_file}")

    # Run cascade
    async def _run():
        await run_simple_cascade(
            papers=papers,
            screen_fn=screen_papers_batch_async,
            screen_kwargs={
                "research_question": "",
                "llm_model": llm,
                "batch_size": int(batch_size),
                "batch_concurrency": int(batch_concurrency),
                "screening_stage": "title_abstract",
                "content_label": "Abstract",
                "content_key": "Abstract",
                "content_fallback": "(Abstract unavailable)",
                "strategy": strategy,
            },
            try_pmc=True,
        )

    asyncio.run(_run())

    # Save output
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    exp_name = experiment or f"cascade_{strategy}_{disease or 'all'}_{ts}"
    out_dir = root / "evaluation" / "experiments" / exp_name / "screening" / (disease or "all")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"screened_{ts}.csv"

    fieldnames = list(papers[0].keys()) if papers else []
    with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(papers)

    print(f"Output saved to {out_file}")


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
    script_subcommand = "screening-performance" if subcommand == "performance" else subcommand
    argv = [script_subcommand]
    proj = str(resolve_project_root() if not project_root else Path(project_root).resolve())
    argv += ["--project-root", proj]
    if profile:          argv += ["--profile", profile]
    if disease:          argv += ["--disease", disease]
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
    argv = ["--disease", disease]
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
@click.option("--model", default=None, help="Override model name")
@click.option("--provider", default=None, help="Override provider profile")
@click.option("--auto-fulltext", is_flag=True)
@click.option("--fulltext-only", is_flag=True)
def pipeline(project_root, profile, disease, topic, include_gt, fix_missing,
             batch_size, batch_concurrency, model, provider, auto_fulltext, fulltext_only):
    """Full screening pipeline: prepare → run → evaluate."""
    proj = str(resolve_project_root() if not project_root else Path(project_root).resolve())

    # Step 1: prepare
    show_step(1, 3, "Prepare raw CSV")
    prep_argv = ["--project-root", proj, "--profile", profile]
    if disease:     prep_argv += ["--disease", disease]
    if topic:       prep_argv += ["--topic", topic]
    if include_gt:  prep_argv += ["--include-gt"]
    if fix_missing: prep_argv += ["--fix-missing"]
    _run_script("screening_prepare_raw", prep_argv)

    # Step 2: run
    show_step(2, 3, "LLM screening")
    eval_argv = [
        "--project-root", proj, "--profile", profile,
        "--batch-size", str(batch_size),
        "--batch-concurrency", str(batch_concurrency),
        "--strategy", "5d",
    ]
    if disease:        eval_argv += ["--disease", disease]
    if topic:          eval_argv += ["--topic", topic]
    if model:          eval_argv += ["--model", model]
    if provider:       eval_argv += ["--provider", provider]
    if auto_fulltext:  eval_argv += ["--auto-fulltext"]
    if fulltext_only:  eval_argv += ["--fulltext-only"]
    _run_script("screening_llm_batch", eval_argv)

    # Step 3: evaluate
    show_step(3, 3, "Evaluate screening performance")
    perf_argv = ["screening-performance", "--project-root", proj, "--profile", profile]
    if disease: perf_argv += ["--disease", disease]
    if topic: perf_argv += ["--topic", topic]
    _run_script("screening_evaluation", perf_argv)
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
    import os
    import subprocess

    script_map = {
        "screening_prepare_raw":    "screening_prepare",
        "screening_llm_batch":      "screening_llm_batch",
        "screening_evaluation":     "screening_evaluation",
        "screening_report_academic": "screening_report",
        "run_sp_fulltext_all":      "run_sp_fulltext_all",
        "prompt_optimizer":         "prompt_optimizer",
        "prepare_downstream_experiment": "prepare_downstream_experiment",
    }

    scripts_dir = DEV_ROOT / "tools" / "scripts"
    script_path = scripts_dir / f"{script_map.get(script_name, script_name)}.py"
    if not script_path.exists():
        legacy_path = DEV_ROOT / "dev" / "literature_search" / "scripts" / "cli" / f"{script_name}.py"
        if legacy_path.exists():
            script_path = legacy_path

    if not script_path.exists():
        raise click.ClickException(f"Script not found: {script_path}")

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(DEV_ROOT)
        if not env.get("PYTHONPATH")
        else f"{DEV_ROOT}{os.pathsep}{env['PYTHONPATH']}"
    )

    result = subprocess.run(
        [sys.executable, str(script_path)] + argv,
        cwd=str(DEV_ROOT),
        env=env,
    )
    if result.returncode != 0:
        raise click.ClickException(f"Script exited with code {result.returncode}")
