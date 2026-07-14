"""Coding sheet extraction and evaluation commands."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click

from metaagent._cli_shared import DEV_ROOT, StyledGroup, resolve_project_root


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
@click.option("--stage", default="both", show_default=True, type=click.Choice(["fetch", "both", "index", "extract"]))
@click.option(
    "--fetch-mode",
    default="pmc_only",
    show_default=True,
    type=click.Choice(["pmc_only", "pmc_scihub", "pmc_scihub_manual"]),
)
@click.option("--out", type=click.Path(path_type=Path, file_okay=False), default=None, help="Explicit output directory")
@click.option("--codebook", type=click.Path(path_type=Path, dir_okay=False), default=None, help="Explicit codebook YAML path")
def extract(disease, topic, project_id, profile, input_path, stage, fetch_mode, out, codebook):
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

    if input_path is not None:
        pmids_path = input_path.expanduser().resolve()
    elif disease and topic and project_id:
        project_manifest = (
            proj
            / "paper_pool"
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

    script_path = proj / "tools" / "scripts" / "extract_coding.py"
    _run_script(script_path, argv)


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
        from metaagent.screening.profile_registry import get_profile

        resolved = get_profile(profile.upper())
    except Exception:
        resolved = None
    if resolved is None:
        return disease, topic, profile.lower()

    def normalize_key(value: str) -> str:
        return value.strip().casefold().replace("-", "_").replace(" ", "_")

    conflicts = []
    if disease and normalize_key(disease) != resolved.disease_key:
        conflicts.append(f"--disease={disease} (profile uses {resolved.disease_key})")
    if topic and normalize_key(topic) != resolved.topic_key:
        conflicts.append(f"--parameter={topic} (profile uses {resolved.topic_key})")
    if project_id and normalize_key(project_id) != resolved.project_dir_name:
        conflicts.append(
            f"--project-id={project_id} (profile uses {resolved.project_dir_name})"
        )
    if conflicts:
        raise click.UsageError(
            f"{', '.join(conflicts)} conflicts with profile {resolved.profile_key}. "
            "Use the profile alone, or omit --profile and provide an explicit project context."
        )
    return (
        resolved.disease_key,
        resolved.topic_key,
        resolved.project_dir_name,
    )


# ── evaluate ───────────────────────────────────────────────────────────
@coding.command("evaluate")
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
def evaluate(disease, topic, project, parameter_type, all_parameter_types,
             estimate_measure, include_median, impute_se, method, run, output):
    """Compute pooled means from coding extraction results."""
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

    script_path = resolve_project_root() / "tools" / "scripts" / "evaluate_coding.py"
    _run_script(script_path, argv)


# ── Helper ─────────────────────────────────────────────────────────────
def _run_script(script_path: Path, argv: list[str]) -> None:
    """Run an existing argparse CLI script as a subprocess."""
    import subprocess

    if not script_path.exists():
        raise click.ClickException(f"Script not found: {script_path}")

    result = subprocess.run(
        [sys.executable, str(script_path)] + argv,
        cwd=str(DEV_ROOT),
    )
    if result.returncode != 0:
        raise click.ClickException(f"Script exited with code {result.returncode}")
