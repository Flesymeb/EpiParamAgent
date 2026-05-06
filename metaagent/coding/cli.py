"""Coding sheet extraction and evaluation commands."""

from __future__ import annotations

import sys
from pathlib import Path

import click


from metaagent._cli_shared import (DEV_ROOT, REPO_ROOT, DISEASE_NAMES, TOPIC_NAMES, resolve_project_root, show_step, show_success, show_error, show_warning, show_command_header, StyledGroup, console, ACCENT, ACCENT_BOLD, ACCENT_DIM)


DATASET_DISEASE_DIRS = {
    "covid19": "covid19",
    "mpox": "mpox",
}


@click.group(cls=StyledGroup)
def coding():
    """Coding sheet extraction and evaluation."""


# ── extract ────────────────────────────────────────────────────────────
@coding.command("extract")
@click.option("--disease", default="covid19", type=click.Choice(DISEASE_NAMES), help="Disease context")
@click.option("--topic", required=True, type=click.Choice(TOPIC_NAMES), help="Epidemiological parameter")
@click.option("--profile", "-p", default=None, help="Screening profile (P13, MP4, etc.)")
@click.option("--stage", default="all", type=click.Choice(["all", "fetch", "both", "index", "extract"]))
@click.option("--fetch-mode", default="pmc_scihub", type=click.Choice(["pmc_only", "pmc_scihub", "pmc_scihub_manual"]))
@click.option("--out", default=None, help="Explicit output directory (overrides --profile)")
@click.option("--codebook", default=None, help="Explicit codebook YAML path")
def extract(disease, topic, profile, stage, fetch_mode, out, codebook):
    """Extract coding sheet from papers (PDF fetch + Stage A/B LLM extraction)."""
    proj = resolve_project_root()

    # Resolve codebook from disease + topic
    if codebook:
        cb_path = Path(codebook)
    else:
        cb_path = proj / "configs" / disease / "codebooks" / f"{topic}.yaml"
        if not cb_path.exists():
            raise click.BadParameter(f"Codebook not found: {cb_path}")

    # Resolve pmids.txt
    if profile:
        project_id = profile.lower()
        disease_dir = DATASET_DISEASE_DIRS.get(disease, disease)
        pmids_path = proj / "dataset" / disease_dir / "coding" / topic / project_id / "pmids.txt"
        if not pmids_path.exists():
            raise click.BadParameter(f"pmids.txt not found: {pmids_path}")
    else:
        raise click.BadParameter("--profile is required (or use --out for explicit mode)")

    # Construct argv for extract_epi.py
    argv = [
        "--input", str(pmids_path),
        "--codebook", str(cb_path),
        "--stage", stage,
        "--fetch-mode", fetch_mode,
    ]
    if out:
        argv += ["--out", out]
    elif profile:
        argv += ["--profile", profile]

    # Run the extraction script
    script_path = DEV_ROOT / "tools" / "scripts" / "extract_coding.py"
    _run_script(script_path, argv)


# ── evaluate ───────────────────────────────────────────────────────────
@coding.command("evaluate")
@click.option("--disease", default=None, type=click.Choice(DISEASE_NAMES), help="Filter by disease")
@click.option("--topic", default=None, type=click.Choice(TOPIC_NAMES), help="Filter by topic")
@click.option("--project", default=None, help="Filter by project (e.g. p13)")
@click.option("--parameter-type", default=None, help="Override parameter_type filter")
@click.option("--estimate-measure", default="mean", help="Estimate measure to pool")
@click.option("--include-median", is_flag=True, help="Include medians as mean approximations")
@click.option("--impute-se/--no-impute-se", default=True, help="Impute missing SE")
@click.option("--method", default="random", type=click.Choice(["random", "fixed"]))
@click.option("--output", default=None, help="Output CSV path")
def evaluate(disease, topic, project, parameter_type, estimate_measure,
             include_median, impute_se, method, output):
    """Compute pooled means from coding extraction results."""
    argv = [
        "--estimate-measure", estimate_measure,
        "--method", method,
    ]
    if disease:         argv += ["--disease", disease]
    if topic:           argv += ["--topic", topic]
    if project:         argv += ["--project", project]
    if parameter_type:  argv += ["--parameter-type", parameter_type]
    if include_median:  argv += ["--include-median"]
    if not impute_se:   argv += ["--no-impute-se"]
    if output:          argv += ["--output", output]

    proj = resolve_project_root()
    script_path = DEV_ROOT / "tools" / "scripts" / "evaluate_coding.py"
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
