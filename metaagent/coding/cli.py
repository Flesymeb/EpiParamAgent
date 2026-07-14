"""Coding sheet extraction and evaluation commands."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table

from metaagent._cli_shared import (
    ACCENT,
    DEV_ROOT,
    StyledGroup,
    console,
    resolve_project_root,
    show_success,
)


@click.group(cls=StyledGroup)
def coding():
    """Coding sheet extraction and evaluation."""


# ── extract ────────────────────────────────────────────────────────────
@coding.command("extract")
@click.option("--disease", default=None, help="Disease or pathogen key")
@click.option("--parameter", "--topic", "topic", default=None, help="Epidemiological parameter key")
@click.option("--project-id", default=None, help="Project identifier used by paper_pool (default: p1)")
@click.option("--profile", "-p", default=None, help="Screening profile (P13, MP4, etc.)")
@click.option(
    "--input",
    "input_path",
    type=click.Path(path_type=Path, exists=True, file_okay=True, dir_okay=True, readable=True),
    default=None,
    help="PMID list, PDF, or full-text directory; defaults to the project paper_pool manifest.",
)
@click.option(
    "--paper-pool",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Shared paper-pool root (default: <project>/paper_pool).",
)
@click.option("--stage", default="both", show_default=True, type=click.Choice(["fetch", "both", "index", "extract"]))
@click.option(
    "--fetch-mode",
    default="pmc_only",
    show_default=True,
    type=click.Choice(["pmc_only", "pmc_scihub", "pmc_scihub_manual"]),
)
@click.option("--out", type=click.Path(path_type=Path, file_okay=False), default=None, help="Explicit output directory")
@click.option("--codebook", type=click.Path(path_type=Path, dir_okay=False), default=None, help="Explicit codebook YAML path")
def extract(disease, topic, project_id, profile, input_path, paper_pool, stage, fetch_mode, out, codebook):
    """Run full-text evidence localization and structured extraction."""
    proj = resolve_project_root()

    disease, topic, inferred_project = _resolve_profile_context(
        profile=profile,
        disease=disease,
        topic=topic,
        project_id=project_id,
    )
    project_id = project_id or inferred_project or ("p1" if disease and topic else None)

    if codebook is not None:
        cb_path = codebook.expanduser().resolve()
    elif disease and topic:
        cb_path = proj / "configs" / disease / "codebooks" / f"{topic}.yaml"
    else:
        raise click.UsageError(
            "Provide --codebook, or provide --disease and --parameter so it can be resolved."
        )
    if not cb_path.exists():
        raise click.ClickException(
            f"Codebook not found: {cb_path}. Add the parameter codebook or pass --codebook."
        )

    pool_root = (paper_pool or (proj / "paper_pool")).expanduser().resolve()
    if input_path is not None:
        pmids_path = input_path.expanduser().resolve()
    elif disease and topic and project_id:
        project_manifest = (
            pool_root
            / "projects"
            / disease
            / topic
            / project_id.lower()
            / "pmids.txt"
        )
        legacy_input = (
            proj
            / "dataset"
            / disease
            / "coding"
            / topic
            / project_id.lower()
            / "pmids.txt"
        )
        pmids_path = project_manifest if project_manifest.exists() else legacy_input
    else:
        raise click.UsageError(
            "Provide --input, or identify a paper_pool project with --disease, "
            "--parameter, and --project-id/--profile."
        )
    if not pmids_path.exists():
        raise click.ClickException(
            f"Coding input not found: {pmids_path}. Run 'metaagent pdf fetch' first "
            "or pass --input explicitly."
        )

    argv = [
        "--input", str(pmids_path),
        "--codebook", str(cb_path),
        "--stage", stage,
        "--fetch-mode", fetch_mode,
    ]
    if out:
        argv += ["--out", str(out.expanduser().resolve())]
    elif profile:
        argv += ["--profile", profile]
    elif disease and topic and project_id:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        output_dir = (
            proj
            / "evaluation"
            / "coding"
            / disease
            / topic
            / project_id.lower()
            / "coding_runs"
            / timestamp
        )
        argv += ["--out", str(output_dir)]
    else:
        raise click.UsageError("Provide --out when no project context is available.")

    details = Table.grid(padding=(0, 2))
    details.add_column(style="bold cyan")
    details.add_column(style="white")
    details.add_row("Profile", profile or "custom")
    details.add_row("Input", str(pmids_path))
    details.add_row("Codebook", str(cb_path))
    details.add_row("Stage", stage)
    details.add_row("Full-text mode", fetch_mode)
    details.add_row("Paper pool", str(pool_root))
    details.add_row("Output", str(out.expanduser().resolve()) if out else "profile coding_runs directory")
    console.print(
        Panel(
            details,
            title="[bold]Coding and extraction plan[/bold]",
            border_style=ACCENT,
            padding=(1, 2),
        )
    )

    script_path = proj / "tools" / "scripts" / "extract_coding.py"
    if paper_pool is not None:
        _run_script(
            script_path,
            argv,
            env_overrides={"METAAGENT_PAPER_POOL": str(pool_root)},
        )
    else:
        _run_script(script_path, argv)
    show_success("Coding and extraction completed")


def _resolve_profile_context(
    *,
    profile: str | None,
    disease: str | None,
    topic: str | None,
    project_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Use the screening registry to fill missing coding project context."""
    if not profile:
        return disease, topic, None
    try:
        from metaagent.screening.profile_registry import resolve_profile_context

        resolved = resolve_profile_context(
            profile,
            disease=disease,
            topic=topic,
            project_id=project_id,
        )
    except (KeyError, ValueError) as exc:
        raise click.UsageError(str(exc)) from exc
    return (
        resolved.disease_key,
        resolved.topic_key,
        resolved.project_dir_name,
    )


# ── evaluate ───────────────────────────────────────────────────────────
@coding.command("evaluate")
@click.option("--profile", "-p", default=None, help="Review profile (AI1, AIR1, P10, etc.)")
@click.option("--disease", default=None, metavar="KEY", help="Filter by disease key")
@click.option(
    "--parameter",
    "--topic",
    "topic",
    default=None,
    metavar="KEY",
    help="Filter by epidemiological parameter key",
)
@click.option("--project", default=None, help="Filter by project (e.g. p13)")
@click.option("--parameter-type", default=None, help="Override parameter_type filter")
@click.option(
    "--all-parameter-types",
    is_flag=True,
    help="Pool all parameter types intentionally instead of applying a parameter filter",
)
@click.option("--estimate-measure", default="mean", help="Estimate measure to pool")
@click.option("--include-median", is_flag=True, help="Include medians as mean approximations")
@click.option("--impute-se/--no-impute-se", default=True, help="Impute missing SE")
@click.option("--method", default="random", type=click.Choice(["random", "fixed"]))
@click.option("--run", default=None, help="Exact coding run directory name to evaluate")
@click.option("--output", default=None, help="Output CSV path")
def evaluate(profile, disease, topic, project, parameter_type, all_parameter_types,
             estimate_measure, include_median, impute_se, method, run, output):
    """Compute pooled means from coding extraction results."""
    disease, topic, inferred_project = _resolve_profile_context(
        profile=profile,
        disease=disease,
        topic=topic,
        project_id=project,
    )
    project = project or inferred_project

    argv = [
        "--estimate-measure", estimate_measure,
        "--method", method,
    ]
    if disease:
        argv += ["--disease", disease]
    if topic:
        argv += ["--topic", topic]
    if project:
        argv += ["--project", project]
    if parameter_type:
        argv += ["--parameter-type", parameter_type]
    if all_parameter_types:
        argv += ["--all-parameter-types"]
    if include_median:
        argv += ["--include-median"]
    if not impute_se:
        argv += ["--no-impute-se"]
    if run:
        argv += ["--run", run]
    if output:
        argv += ["--output", output]
    elif profile and disease and topic and project:
        pooled_output = (
            resolve_project_root()
            / "evaluation"
            / "coding"
            / disease
            / topic
            / project
            / "pooled_summary.csv"
        )
        argv += ["--output", str(pooled_output)]

    script_path = resolve_project_root() / "tools" / "scripts" / "evaluate_coding.py"
    _run_script(script_path, argv)


# ── Helper ─────────────────────────────────────────────────────────────
def _run_script(
    script_path: Path,
    argv: list[str],
    env_overrides: dict[str, str] | None = None,
) -> None:
    """Run an existing argparse CLI script as a subprocess."""
    import os
    import subprocess

    if not script_path.exists():
        raise click.ClickException(f"Script not found: {script_path}")

    env = os.environ.copy()
    env.update(env_overrides or {})
    result = subprocess.run(
        [sys.executable, str(script_path)] + argv,
        cwd=str(DEV_ROOT),
        env=env,
    )
    if result.returncode != 0:
        raise click.ClickException(f"Script exited with code {result.returncode}")
