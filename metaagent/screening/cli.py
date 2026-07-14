"""Screening workflow commands."""

from __future__ import annotations

import csv
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table

from metaagent._cli_shared import (
    ACCENT,
    ACCENT_BOLD,
    ACCENT_DIM,
    DEV_ROOT,
    DISEASE_NAMES,
    StyledGroup,
    console,
    resolve_project_root,
    show_step,
    show_success,
    show_warning,
)
from tools.pubmed.metadata import inspect_csv_metadata


@click.group(cls=StyledGroup)
def screening():
    """Run, inspect, and evaluate literature screening."""


# ── prepare ────────────────────────────────────────────────────────────
@screening.command("prepare", hidden=True)
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
@click.option("--batch-concurrency", default=1, type=int, help="Concurrent batch groups")
@click.option("--batch-mode", default="single", type=click.Choice(["single", "multi"]), help="single=one API call per paper; multi=one API call per batch")
@click.option("--model", default=None, help="Override model name")
@click.option("--provider", default=None, help="Override provider profile (for example openrouter, openai, lab, lab2, boyue, or any env-backed custom provider)")
@click.option("--temperature", default=None, type=float, help="Override LLM temperature")
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
@click.option("--fulltext-cache-only", is_flag=True, help="Stage 2: use cached PDFs/markdown only")
@click.option(
    "--fix-missing/--no-fix-missing",
    default=None,
    help="Fill missing PubMed title, abstract, and keyword metadata before screening.",
)
@click.option(
    "--interactive/--no-interactive",
    default=None,
    help="Enable or disable metadata-completion prompts.",
)
@click.option(
    "--prefer-llm-tier/--no-prefer-llm-tier",
    default=True,
    help="Use LLM's own tier classification instead of code-side thresholds.",
)
def run(project_root, profile, disease, topic, input_file, output_file,
        ground_truth, research_question, batch_size, batch_concurrency, batch_mode,
        model, provider, temperature, strategy, experiment, cascade, auto_fulltext, fulltext_only,
        no_fulltext_rescue, skip_no_abstract,
        resume_fulltext, resume_possible_fulltext, resume_sp_fulltext, fulltext_cache_only,
        fix_missing, interactive, prefer_llm_tier):
    """Run LLM-based batch screening with optional cascade retrieval."""
    if cascade:
        _preflight_screening_llm(model=model, provider=provider)
        _run_cascade(project_root, profile, disease, topic, batch_size, batch_concurrency, batch_mode,
                     model, provider, temperature, strategy, experiment, prefer_llm_tier)
        return

    if not profile and not input_file:
        raise click.UsageError("Provide --profile or --input for screening.")
    if not profile and not research_question:
        raise click.UsageError(
            "Explicit input mode requires --research-question when --profile is omitted."
        )
    if output_file and not input_file and not profile:
        raise click.UsageError("--output without --input requires --profile.")
    if profile:
        from metaagent.screening.profile_registry import resolve_profile_context

        try:
            resolve_profile_context(profile, disease=disease, topic=topic or None)
        except (KeyError, ValueError) as exc:
            raise click.UsageError(str(exc)) from exc

    if interactive is None:
        interactive = sys.stdin.isatty()
    resolved_input = _resolve_run_input(
        project_root=project_root,
        profile=profile,
        disease=disease,
        topic=topic,
        input_file=input_file,
    )
    if resolved_input is None or not resolved_input.exists():
        raise click.ClickException(
            f"Screening input not found: {resolved_input}. "
            "Run 'metaagent pubmed query --search' first or pass --input."
        )
    _preflight_input_metadata(
        resolved_input,
        fix_missing=fix_missing,
        interactive=interactive,
    )
    _preflight_screening_llm(model=model, provider=provider)

    argv = [
        "--batch-size", str(batch_size),
        "--batch-concurrency", str(batch_concurrency),
        "--batch-mode", batch_mode,
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
    if temperature is not None: argv += ["--temperature", str(temperature)]
    if experiment:         argv += ["--experiment", experiment]
    if auto_fulltext:      argv += ["--auto-fulltext"]
    if fulltext_only:      argv += ["--fulltext-only"]
    if no_fulltext_rescue: argv += ["--no-fulltext-rescue"]
    if skip_no_abstract:   argv += ["--skip-no-abstract"]
    if resume_fulltext:    argv += ["--resume-fulltext"]
    if resume_possible_fulltext: argv += ["--resume-possible-fulltext"]
    if resume_sp_fulltext: argv += ["--resume-sp-fulltext"]
    if fulltext_cache_only: argv += ["--fulltext-cache-only"]
    if prefer_llm_tier:     argv += ["--prefer-llm-tier"]
    else:                   argv += ["--no-prefer-llm-tier"]

    _run_script("screening_llm_batch", argv)


@screening.command("summary")
@click.option("--input", "input_file", type=click.Path(path_type=Path, dir_okay=False))
@click.option("--profile", "-p", default=None, help="Screening profile (AI1, AIR1, P10, etc.)")
@click.option("--disease", default=None, help="Optional disease-key override for profile mode")
@click.option("--parameter", "--topic", "topic", default=None, help="Optional parameter-key override")
@click.option("--project-root", default="", help="Repository root")
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
def summary(input_file, profile, disease, topic, project_root, json_output):
    """Show Strong, Possible, and Unlikely counts for a screening result."""
    if input_file is not None:
        screened_path = input_file.expanduser().resolve()
    elif profile:
        from metaagent.screening.profile_registry import resolve_profile_paths

        root = resolve_project_root() if not project_root else Path(project_root).resolve()
        try:
            _, paths = resolve_profile_paths(
                project_root=root,
                profile_name=profile,
                disease=disease,
                topic=topic,
            )
        except KeyError as exc:
            raise click.ClickException(str(exc)) from exc
        screened_path = paths.screened_file
    else:
        raise click.UsageError("Provide --input or --profile")

    if not screened_path.exists():
        raise click.ClickException(f"Screening result not found: {screened_path}")

    try:
        with screened_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, ValueError, csv.Error) as exc:
        raise click.ClickException(f"Cannot read {screened_path}: {exc}") from exc

    counts = {"S": 0, "P": 0, "U": 0, "error": 0, "other": 0}
    for row in rows:
        counts[_screening_row_tier(row)] += 1

    total = len(rows)
    retained = counts["S"] + counts["P"]
    payload = {
        "input": str(screened_path),
        "total": total,
        "strong": counts["S"],
        "possible": counts["P"],
        "unlikely": counts["U"],
        "retained": retained,
        "errors": counts["error"],
        "other": counts["other"],
        "retained_share": retained / total if total else 0.0,
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    table = Table(title="Screening summary", header_style=f"bold {ACCENT_BOLD}")
    table.add_column("Tier", style=f"bold {ACCENT}")
    table.add_column("Meaning")
    table.add_column("Count", justify="right")
    table.add_column("Share", justify="right")
    for tier, meaning, count in (
        ("S", "Strong", counts["S"]),
        ("P", "Possible", counts["P"]),
        ("U", "Unlikely", counts["U"]),
        ("-", "Error/other", counts["error"] + counts["other"]),
    ):
        share = count / total if total else 0.0
        table.add_row(tier, meaning, str(count), f"{share:.1%}")
    console.print(table)
    console.print(
        f"[bold {ACCENT_BOLD}]Retained (S+P):[/bold {ACCENT_BOLD}] "
        f"{retained}/{total} ({payload['retained_share']:.1%})"
    )
    console.print(f"[{ACCENT_DIM}]Input: {screened_path}[/{ACCENT_DIM}]")


def _screening_row_tier(row: dict[str, str]) -> str:
    """Normalize current and legacy screening labels to S/P/U/error/other."""
    columns = {str(key).strip().casefold(): key for key in row}
    aliases = {
        "s": "S",
        "strong": "S",
        "strong_candidate": "S",
        "p": "P",
        "possible": "P",
        "possible_candidate": "P",
        "u": "U",
        "unlikely": "U",
        "unlikely_candidate": "U",
        "error": "error",
    }
    for name in ("llm_suggest", "final_tier", "screening_tier", "llm_tier", "tier"):
        key = columns.get(name)
        value = str(row.get(key, "") or "").strip().casefold() if key else ""
        if value:
            return aliases.get(value, "other")
    return "other"


def _resolve_run_input(
    *,
    project_root: str,
    profile: str | None,
    disease: str | None,
    topic: str,
    input_file: str,
) -> Path | None:
    """Resolve the CSV that screening will read."""
    if input_file:
        return Path(input_file).expanduser().resolve()
    if not profile:
        return None

    from metaagent.screening.profile_registry import resolve_profile_paths

    root = resolve_project_root() if not project_root else Path(project_root).resolve()
    _, paths = resolve_profile_paths(
        project_root=root,
        profile_name=profile,
        disease=disease,
        topic=topic or None,
    )
    return paths.raw_file


def _metadata_marker_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.metadata_enrichment.json")


def _enrich_input_metadata(input_path: Path) -> None:
    """Fill missing PubMed metadata in place using the existing fetcher."""
    from metaagent.config import load_runtime_env
    from tools.scripts.pubmed_manager import fix_missing_fields

    load_runtime_env()
    fix_missing_fields(input_path, input_path)


def _preflight_input_metadata(
    input_path: Path,
    *,
    fix_missing: bool | None,
    interactive: bool,
) -> None:
    """Offer PubMed metadata completion before LLM screening starts."""
    try:
        before = inspect_csv_metadata(input_path)
    except (OSError, csv.Error) as exc:
        raise click.ClickException(f"Cannot inspect screening input {input_path}: {exc}") from exc

    if before.total_rows == 0:
        raise click.ClickException(
            f"Screening input contains no records: {input_path}. "
            "Retrieve records first or pass a non-empty --input CSV."
        )
    if before.missing_pmid == before.total_rows:
        raise click.ClickException(
            f"Every row in {input_path} is missing PMID. "
            "Populate the PMID column before screening so full-text hand-off remains traceable."
        )

    marker_path = _metadata_marker_path(input_path)
    marker_is_current = bool(
        marker_path.exists()
        and marker_path.stat().st_mtime_ns >= input_path.stat().st_mtime_ns
    )
    has_enrichable_gaps = bool(
        before.needs_screening_enrichment or before.has_optional_gaps
    )
    enrichment_due = has_enrichable_gaps and (
        fix_missing is True or not marker_is_current
    )
    if not enrichment_due:
        if before.missing_title == before.total_rows:
            raise click.ClickException(
                "Every screening record is missing Title. Run metadata completion or provide titles."
            )
        if before.needs_screening_enrichment and marker_is_current:
            show_warning(
                "A previous PubMed completion attempt left some titles or abstracts "
                "unavailable; screening will use the available metadata."
            )
        return

    if interactive:
        details = Table.grid(padding=(0, 2))
        details.add_column(style="bold cyan")
        details.add_column(justify="right")
        details.add_row("Records", str(before.total_rows))
        details.add_row("Missing title", str(before.missing_title))
        details.add_row("Missing abstract", str(before.missing_abstract))
        details.add_row("Missing keywords", str(before.missing_keywords))
        details.add_row("Missing PMID", str(before.missing_pmid))
        console.print(
            Panel(
                details,
                title="[bold]Screening metadata check[/bold]",
                border_style=ACCENT,
                padding=(1, 2),
            )
        )

    should_enrich = bool(fix_missing)
    if fix_missing is None and interactive:
        should_enrich = click.confirm(
            "Complete available metadata from PubMed before screening?",
            default=True,
        )
    elif fix_missing is None and before.needs_screening_enrichment:
        show_warning(
            "Screening input has missing titles or abstracts; use --fix-missing to enrich it."
        )

    if not should_enrich:
        if before.missing_title == before.total_rows:
            raise click.ClickException(
                "Every screening record is missing Title. Re-run with --fix-missing or provide titles."
            )
        return

    backup_path = input_path.with_name(
        f"{input_path.stem}.before_enrichment{input_path.suffix}"
    )
    if not backup_path.exists():
        shutil.copy2(input_path, backup_path)

    try:
        _enrich_input_metadata(input_path)
        after = inspect_csv_metadata(input_path)
    except Exception as exc:
        raise click.ClickException(f"PubMed metadata completion failed: {exc}") from exc

    marker_path.write_text(
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "input_csv": str(input_path),
                "before": before.__dict__,
                "after": after.__dict__,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    show_success(
        "Metadata completion finished: "
        f"missing abstracts {before.missing_abstract} -> {after.missing_abstract}; "
        f"missing keywords {before.missing_keywords} -> {after.missing_keywords}"
    )
    if after.missing_title == after.total_rows:
        raise click.ClickException(
            "PubMed completion could not recover any titles; screening cannot continue."
        )


def _preflight_screening_llm(*, model: str | None, provider: str | None) -> None:
    """Fail before spawning a worker when the screening LLM is not configured."""
    from metaagent.config import is_usable_secret, load_llm_config

    cfg = load_llm_config(
        {"llm_model": model, "llm_provider": provider},
        module_hint="screening",
    )
    missing = []
    if not cfg.model:
        missing.append("SCREENING_LLM_MODEL")
    if not is_usable_secret(cfg.api_key):
        missing.append("the selected provider API key")
    if cfg.provider not in {None, "openai"} and not cfg.api_base:
        missing.append("the selected provider base URL")
    if missing:
        raise click.ClickException(
            "Screening LLM configuration is incomplete: missing "
            + ", ".join(missing)
            + ". Edit .env.local, then run "
            "'metaagent config check --stage screening'."
        )


def _run_cascade(project_root, profile, disease, topic, batch_size, batch_concurrency, batch_mode,
                 model, provider, temperature, strategy, experiment, prefer_llm_tier=True):
    """Run cascade screening with Tier-2 PubMed/PMC enrichment."""
    import asyncio

    from metaagent.config import load_llm_config
    from metaagent.screening.cascade import run_simple_cascade
    from metaagent.screening.engine import init_llm_model, screen_papers_batch_async

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
        temperature_override=temperature,
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
                "batch_mode": batch_mode,
                "screening_stage": "title_abstract",
                "content_label": "Abstract",
                "content_key": "Abstract",
                "content_fallback": "(NO ABSTRACT AVAILABLE — cannot assess evidence or parameter from title alone. Score conservatively.)",
                "strategy": strategy,
                "prefer_llm_tier": prefer_llm_tier,
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
@click.option("--experiment", default="", help="Experiment output subdirectory")
@click.option("--ground-truth", default="", help="Ground truth CSV path")
@click.option("--screened-results", default="", help="Screened results CSV")
@click.option("--search-results", default="", help="Search results CSV")
@click.option("--bucket", default="possible", type=click.Choice(["strong", "possible"]))
@click.option("--axis", default=None, type=click.Choice(["disease", "parameter", "evidence", "population", "location"]))
@click.option("--values", default="1,2,3,4", help="Comma-separated threshold values for sweep")
@click.pass_context
def evaluate(ctx, subcommand, project_root, profile, disease, topic,
             experiment, ground_truth, screened_results, search_results, bucket, axis, values):
    """Evaluate screening results (search-coverage | performance | threshold-sweep | retrieval-metrics)."""
    script_subcommand = "screening-performance" if subcommand == "performance" else subcommand
    argv = [script_subcommand]
    proj = str(resolve_project_root() if not project_root else Path(project_root).resolve())
    if profile and subcommand in {"performance", "threshold-sweep"}:
        from metaagent.screening.profile_registry import resolve_profile_paths

        try:
            _, paths = resolve_profile_paths(
                project_root=proj,
                profile_name=profile,
                disease=disease,
                topic=topic or None,
                experiment=experiment or None,
            )
        except (KeyError, ValueError) as exc:
            raise click.UsageError(str(exc)) from exc
        gt_path = Path(ground_truth).expanduser().resolve() if ground_truth else paths.ground_truth_file
        screened_path = (
            Path(screened_results).expanduser().resolve()
            if screened_results
            else paths.screened_file
        )
        if not gt_path.exists():
            raise click.ClickException(
                f"Ground-truth file not found: {gt_path}. Add a PMID-labelled "
                "ground_truth.csv or pass --ground-truth."
            )
        if not screened_path.exists():
            raise click.ClickException(
                f"Screening result not found: {screened_path}. Run screening first "
                "or pass --screened-results."
            )
    argv += ["--project-root", proj]
    if profile:          argv += ["--profile", profile]
    if disease:          argv += ["--disease", disease]
    if topic:            argv += ["--topic", topic]
    if experiment and script_subcommand in {"screening-performance", "threshold-sweep"}:
        argv += ["--experiment", experiment]
    if ground_truth:     argv += ["--ground-truth", ground_truth]
    if screened_results: argv += ["--screened-results", screened_results]
    if search_results:   argv += ["--search-results", search_results]
    if subcommand == "threshold-sweep":
        argv += ["--bucket", bucket]
        if axis: argv += ["--axis", axis]
        argv += ["--values", values]

    _run_script("screening_evaluation", argv)


# ── report ─────────────────────────────────────────────────────────────
@screening.command("report", hidden=True)
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
@screening.command("pipeline", hidden=True)
@click.option("--project-root", default="", help="Repository root")
@click.option("--profile", "-p", required=True, help="Screening profile")
@click.option("--disease", default=None, help="Disease filter")
@click.option("--topic", default="", help="Topic override")
@click.option("--include-gt/--no-include-gt", default=False)
@click.option("--fix-missing/--no-fix-missing", default=False)
@click.option("--batch-size", default=10, type=int)
@click.option("--batch-concurrency", default=1, type=int)
@click.option("--batch-mode", default="single", type=click.Choice(["single", "multi"]))
@click.option("--model", default=None, help="Override model name")
@click.option("--provider", default=None, help="Override provider profile")
@click.option("--temperature", default=None, type=float, help="Override LLM temperature")
@click.option("--auto-fulltext", is_flag=True)
@click.option("--fulltext-only", is_flag=True)
def pipeline(project_root, profile, disease, topic, include_gt, fix_missing,
             batch_size, batch_concurrency, batch_mode, model, provider, temperature, auto_fulltext, fulltext_only):
    """Legacy combined command; use the explicit workflow commands instead."""
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
        "--batch-mode", batch_mode,
        "--strategy", "5d",
    ]
    if disease:        eval_argv += ["--disease", disease]
    if topic:          eval_argv += ["--topic", topic]
    if model:          eval_argv += ["--model", model]
    if provider:       eval_argv += ["--provider", provider]
    if temperature is not None: eval_argv += ["--temperature", str(temperature)]
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
