"""Cross-stage workflow inspection and resume guidance."""

from __future__ import annotations

import csv
import contextlib
import os
import re
import sys
import json
import shlex
from collections import Counter
from pathlib import Path
from typing import Any

import click
import yaml
from rich.table import Table

from metaagent._cli_shared import (
    ACCENT,
    ACCENT_BOLD,
    StyledGroup,
    console,
    resolve_project_root,
)
from tools.pubmed.metadata import inspect_csv_metadata


class JsonOutputCommand(click.Command):
    """Keep --json parse failures inside the same single-document contract."""
    def make_context(self, info_name, args, parent=None, **extra):
        json_output = "--json" in args
        try:
            return super().make_context(info_name, args, parent=parent, **extra)
        except click.ClickException as exc:
            if not json_output:
                raise
            command = f"{parent.command_path} {info_name}" if parent else info_name
            _command_failure(exc, True, exit_code=exc.exit_code or 2,
                             suggestion=f"Check the indicated argument; run {command} --help for accepted inputs.")


@click.group(cls=StyledGroup)
def workflow():
    """Inspect a review workflow and resume it from the next incomplete stage."""


def _stage(status: str, artifact: Path | None, detail: str) -> dict[str, Any]:
    return {
        "status": status,
        "artifact": str(artifact) if artifact else None,
        "detail": detail,
    }


def _newest_file(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    candidates = [path for path in root.glob(pattern) if path.is_file()]
    return max(candidates, key=lambda path: path.stat().st_mtime_ns) if candidates else None


def _nonempty_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _screening_error_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(
            str(row.get("llm_suggest", "")).strip().casefold() == "error"
            for row in csv.DictReader(handle)
        )


def resolve_coding_config_files(
    root: Path,
    disease: str,
    topic: str,
) -> tuple[Path, list[Path]]:
    """Return a codebook and every prompt/schema file required by it."""
    codebook = root / "configs" / disease / "codebooks" / f"{topic}.yaml"
    prompts_dir = root / "configs" / disease / "coding_prompts"
    required = [codebook, prompts_dir / "stage_a.yaml"]
    if codebook.exists():
        try:
            payload = yaml.safe_load(codebook.read_text(encoding="utf-8")) or {}
            for stage_name in ("stage_a", "stage_b"):
                prompt_file = (payload.get(stage_name) or {}).get("prompt_file")
                if prompt_file:
                    candidate = Path(str(prompt_file))
                    if not candidate.is_absolute():
                        candidate = (codebook.parent / candidate).resolve()
                    required.append(candidate)
        except (OSError, yaml.YAMLError, AttributeError):
            pass
    return codebook, required


def _quoted_command(parts: list[str | Path]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def _llm_runtime_ready(module: str) -> bool:
    from metaagent.config import is_usable_secret, load_llm_config

    cfg = load_llm_config(module_hint=module)
    endpoint_ready = cfg.provider in {None, "openai"} or bool(cfg.api_base)
    return bool(cfg.model and is_usable_secret(cfg.api_key) and endpoint_ready)


def _coding_runtime_ready() -> bool:
    from metaagent.config import is_usable_secret, load_mineru_config

    mineru = load_mineru_config(module_hint="coding")
    return _llm_runtime_ready("coding") and is_usable_secret(mineru.api_key)


@workflow.command("status", cls=JsonOutputCommand)
@click.option("--profile", "-p", help="Review profile (AI1, AIR1, P10, etc.)")
@click.option("--run-dir", type=click.Path(path_type=Path, file_okay=False), help="Compatibility alias for --output-dir; inspect a workflow run manifest.")
@click.option("--output-dir", type=click.Path(path_type=Path, file_okay=False), help="Inspect a saved run; outputs JSON by default. No service calls.")
@click.option("--project-root", default="", help="Repository root (auto-detected if empty)")
@click.option(
    "--raw-csv",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Existing raw.csv to use instead of the profile dataset path.",
)
@click.option(
    "--screened-csv",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Existing screened CSV to inspect instead of the profile output path.",
)
@click.option(
    "--paper-pool",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Paper-pool root (default: <project>/paper_pool).",
)
@click.option("--json", "json_output", is_flag=True, help="Emit a machine-readable result")
def status(profile, run_dir, output_dir, project_root, raw_csv, screened_csv, paper_pool, json_output):
    """Show completed artifacts and the exact command for the next stage."""
    json_output = json_output or output_dir is not None
    if run_dir and output_dir and run_dir.resolve() != output_dir.resolve():
        _command_failure(ValueError("--run-dir and --output-dir must refer to the same run"), json_output, exit_code=2)
    run_dir = output_dir or run_dir
    if profile and run_dir:
        _command_failure(ValueError("Choose --profile for legacy inspection or --output-dir/--run-dir for a saved run"), json_output, exit_code=2)
    if run_dir:
        from metaagent.workflow_runner import file_hash

        path = run_dir / "workflow_manifest.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("stage_results", {}), dict) or not isinstance(payload.get("status"), str):
                raise ValueError("Manifest requires status and stage_results fields")
            payload["manifest"] = str(path.resolve())
            invalid = []
            for name, stage in payload.get("stage_results", {}).items():
                hashes = stage.get("output_hashes", {})
                valid = bool(hashes) and all(Path(p).is_file() and file_hash(Path(p)) == digest for p, digest in hashes.items())
                stage["outputs_verified"] = valid
                if stage.get("status") == "complete" and not valid:
                    invalid.append(name)
            if not invalid:
                invalid = [name for name, stage in payload.get("stage_results", {}).items() if stage.get("stale")]
            if invalid:
                payload["recorded_status"] = payload.get("status")
                payload["status"] = "stale"
                payload["invalid_stages"] = invalid
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            _command_failure(exc, json_output, suggestion="Check --output-dir contains a readable workflow_manifest.json; rerun the original workflow command if outputs are missing.")
        payload["stages"] = {k: {"status": v.get("status"), "stale": v.get("stale", False), "reused": v.get("reused", False), "outputs_verified": v.get("outputs_verified", False)} for k, v in payload.get("stage_results", {}).items()}
        payload.setdefault("artifact_overrides", {})
        if json_output:
            click.echo(json.dumps(payload, ensure_ascii=False))
        else:
            click.echo(f"{payload.get('profile', run_dir.name)}: {payload['status']}")
            for name, stage in payload.get("stage_results", {}).items():
                click.echo(f"  {name}: {stage['status']}; outputs verified={stage['outputs_verified']}")
        if payload["status"] not in {"complete", "completed", "ok"}:
            raise click.exceptions.Exit(1)
        return
    if not profile:
        _command_failure(ValueError("Provide --output-dir (or --run-dir) for a saved run, or --profile for legacy artifacts"), json_output, exit_code=2)
    from metaagent.screening.profile_registry import (
        resolve_profile_context,
        resolve_profile_paths,
    )

    root = (
        resolve_project_root()
        if not project_root
        else Path(project_root).expanduser().resolve()
    )
    try:
        resolved = resolve_profile_context(profile)
        _, paths = resolve_profile_paths(
            project_root=root,
            profile_name=resolved.profile_key,
        )
    except (KeyError, ValueError) as exc:
        _command_failure(exc, json_output, exit_code=2)

    raw_path = (raw_csv or paths.raw_file).expanduser().resolve()
    screened_path = (screened_csv or paths.screened_file).expanduser().resolve()
    pool_root = (paper_pool or (root / "paper_pool")).expanduser().resolve()
    fetch_dir = (
        pool_root
        / "projects"
        / resolved.disease_key
        / resolved.topic_key
        / resolved.project_dir_name
    )
    pmids_path = fetch_dir / "pmids.txt"
    fetch_results = fetch_dir / "fetch_results.csv"
    coding_project = (
        root
        / "evaluation"
        / "coding"
        / resolved.disease_key
        / resolved.topic_key
        / resolved.project_dir_name
    )
    coding_sheet = _newest_file(coding_project / "coding_runs", "*/coding_sheet*.xlsx")
    coding_manifest = (
        _newest_file(coding_sheet.parent, "run_manifest_coding_sheet_extraction*.json")
        if coding_sheet
        else None
    )
    coding_errors = 0
    if coding_manifest:
        try:
            manifest_payload = json.loads(coding_manifest.read_text(encoding="utf-8"))
            coding_errors = int((manifest_payload.get("extra") or {}).get("error_count", 0))
        except (OSError, ValueError, TypeError):
            coding_errors = 1
    pooled_path = coding_project / "pooled_summary.csv"

    codebook, config_files = resolve_coding_config_files(
        root,
        resolved.disease_key,
        resolved.topic_key,
    )
    missing_config = [path for path in config_files if not path.exists()]
    stages: dict[str, dict[str, Any]] = {}
    stages["configuration"] = _stage(
        "ready" if not missing_config else "blocked",
        codebook,
        "Coding schema files are ready."
        if not missing_config
        else "Missing: " + ", ".join(str(path) for path in missing_config),
    )

    raw_count = _csv_rows(raw_path)
    stages["retrieval"] = _stage(
        "complete" if raw_count else "pending",
        raw_path,
        f"{raw_count} records" if raw_count else "No raw retrieval found.",
    )

    metadata_ready = False
    metadata_detail = "Waiting for raw.csv."
    if raw_count:
        try:
            metadata = inspect_csv_metadata(raw_path)
            marker = raw_path.with_name(f"{raw_path.stem}.metadata_enrichment.json")
            attempted = marker.exists() and marker.stat().st_mtime_ns >= raw_path.stat().st_mtime_ns
            gaps = metadata.needs_screening_enrichment or metadata.has_optional_gaps
            metadata_ready = not gaps or attempted
            metadata_detail = (
                f"missing title={metadata.missing_title}, abstract={metadata.missing_abstract}, "
                f"keywords={metadata.missing_keywords}"
            )
            if attempted and gaps:
                metadata_detail += "; PubMed completion already attempted"
        except (OSError, ValueError, csv.Error) as exc:
            metadata_detail = f"Cannot inspect metadata: {exc}"
    stages["metadata"] = _stage(
        "complete" if metadata_ready else ("pending" if raw_count else "blocked"),
        raw_path if raw_count else None,
        metadata_detail,
    )

    screened_count = _csv_rows(screened_path)
    screening_errors = _screening_error_count(screened_path)
    screening_fresh = bool(
        raw_count
        and screened_count == raw_count
        and not screening_errors
        and screened_path.stat().st_mtime_ns >= raw_path.stat().st_mtime_ns
    )
    if screening_fresh:
        screening_detail = f"{screened_count} decisions"
    elif screening_errors:
        screening_detail = f"{screened_count} rows; {screening_errors} LLM errors require rerun"
    elif screened_count and screened_count != raw_count:
        screening_detail = (
            f"Row-count mismatch: raw={raw_count}, screened={screened_count}"
        )
    elif screened_count:
        screening_detail = "Screening output predates raw.csv."
    else:
        screening_detail = "No screening output found."
    stages["screening"] = _stage(
        "complete"
        if screening_fresh
        else ("incomplete" if screening_errors else ("stale" if screened_count else "pending")),
        screened_path,
        screening_detail,
    )

    selected_count = _nonempty_lines(pmids_path)
    plan_fresh = bool(
        selected_count
        and screening_fresh
        and pmids_path.stat().st_mtime_ns >= screened_path.stat().st_mtime_ns
    )
    fetch_detail = f"{selected_count} selected PMIDs"
    fetch_attempt_count = 0
    fetch_results_fresh = False
    if fetch_results.exists():
        with fetch_results.open("r", encoding="utf-8-sig", newline="") as handle:
            fetch_rows = list(csv.DictReader(handle))
        fetch_attempt_count = len(fetch_rows)
        fetch_counts = Counter(str(row.get("status", "unknown")) for row in fetch_rows)
        fetch_results_fresh = bool(
            plan_fresh
            and fetch_attempt_count >= selected_count
            and fetch_results.stat().st_mtime_ns >= pmids_path.stat().st_mtime_ns
        )
        fetch_detail += (
            f"; PDFs downloaded={fetch_counts.get('downloaded', 0)}/{len(fetch_rows)}"
        )
    elif selected_count:
        fetch_detail += "; retrieval has not been run"
    fetch_fresh = fetch_results_fresh
    stages["full_text"] = _stage(
        "complete"
        if fetch_fresh
        else ("stale" if fetch_results.exists() else "pending"),
        fetch_results if fetch_results.exists() else pmids_path,
        fetch_detail if selected_count else "No S+P full-text plan found.",
    )

    coding_fresh = bool(
        coding_sheet
        and fetch_fresh
        and not coding_errors
        and coding_sheet.stat().st_mtime_ns >= pmids_path.stat().st_mtime_ns
    )
    if missing_config:
        coding_status = "blocked"
        coding_detail = "Coding configuration is incomplete."
    elif coding_fresh:
        coding_status = "complete"
        coding_detail = "Latest coding sheet is current."
    elif coding_errors:
        coding_status = "incomplete"
        coding_detail = f"Latest coding run reports {coding_errors} processing errors."
    elif coding_sheet:
        coding_status = "stale"
        coding_detail = "Coding output predates the current PMID selection."
    else:
        coding_status = "pending"
        coding_detail = "No coding sheet found."
    stages["coding"] = _stage(coding_status, coding_sheet, coding_detail)

    pooling_fresh = bool(
        pooled_path.exists()
        and coding_fresh
        and pooled_path.stat().st_mtime_ns >= coding_sheet.stat().st_mtime_ns
    )
    stages["pooling"] = _stage(
        "complete" if pooling_fresh else ("stale" if pooled_path.exists() else "pending"),
        pooled_path,
        "Pooled estimate is current."
        if pooling_fresh
        else ("Pooled estimate predates coding output." if pooled_path.exists() else "No pooled summary found."),
    )

    root_args = ["--project-root", root] if project_root else []
    query_runtime_ready = _llm_runtime_ready("query")
    screening_runtime_ready = _llm_runtime_ready("screening")
    coding_runtime_ready = _coding_runtime_ready()
    if not raw_count and not query_runtime_ready:
        current_stage = "query_configuration"
        next_command = _quoted_command(
            [
                "metaagent",
                "config",
                "check",
                "--stage",
                "query",
                "--profile",
                resolved.profile_key,
                *root_args,
            ]
        )
    elif not raw_count:
        current_stage = "retrieval"
        next_command = _quoted_command(
            ["metaagent", "pubmed", "query", "--profile", resolved.profile_key, *root_args]
        )
    elif not metadata_ready:
        current_stage = "metadata"
        next_command = _quoted_command(
            ["metaagent", "pubmed", "metadata", "complete", "--input", raw_path]
        )
    elif not screening_fresh and not screening_runtime_ready:
        current_stage = "screening_configuration"
        next_command = _quoted_command(
            [
                "metaagent",
                "config",
                "check",
                "--stage",
                "screening",
                "--profile",
                resolved.profile_key,
                *root_args,
            ]
        )
    elif not screening_fresh:
        current_stage = "screening"
        command: list[str | Path] = [
            "metaagent",
            "screening",
            "run",
            "--profile",
            resolved.profile_key,
            *root_args,
            "--batch-mode",
            "multi",
            "--batch-size",
            "20",
            "--batch-concurrency",
            "5",
        ]
        if raw_csv is not None:
            command.extend(["--input", raw_path])
        next_command = _quoted_command(command)
    elif not fetch_fresh:
        current_stage = "full_text"
        command = ["metaagent", "pdf", "fetch", "--profile", resolved.profile_key]
        if project_root:
            command.extend(["--project-root", root])
        if screened_csv is not None:
            command.extend(["--input", screened_path])
        if paper_pool is not None:
            command.extend(["--paper-pool", pool_root])
        command.append("--download")
        next_command = _quoted_command(command)
    elif missing_config:
        current_stage = "coding_configuration"
        next_command = None
    elif not coding_fresh and not coding_runtime_ready:
        current_stage = "coding_configuration"
        next_command = _quoted_command(
            [
                "metaagent",
                "config",
                "check",
                "--stage",
                "coding",
                "--profile",
                resolved.profile_key,
                *root_args,
            ]
        )
    elif not coding_fresh:
        current_stage = "coding"
        command = ["metaagent", "coding", "extract", "--profile", resolved.profile_key]
        if paper_pool is not None:
            command.extend(["--paper-pool", pool_root])
        next_command = _quoted_command(command)
    elif not pooling_fresh:
        current_stage = "pooling"
        next_command = _quoted_command(
            ["metaagent", "coding", "evaluate", "--profile", resolved.profile_key]
        )
    else:
        current_stage = "complete"
        next_command = None

    payload = {
        "profile": resolved.profile_key,
        "disease": resolved.disease_key,
        "parameter": resolved.topic_key,
        "project": resolved.project_dir_name,
        "current_stage": current_stage,
        "next_command": next_command,
        "runtime_ready": {
            "query": query_runtime_ready,
            "screening": screening_runtime_ready,
            "coding": coding_runtime_ready,
        },
        "stages": stages,
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    table = Table(title=f"Workflow status: {resolved.profile_key}", header_style=f"bold {ACCENT_BOLD}")
    table.add_column("Stage", style=f"bold {ACCENT}")
    table.add_column("Status")
    table.add_column("Detail")
    for name, stage in stages.items():
        label = "Coding Schema" if name == "configuration" else name.replace("_", " ").title()
        table.add_row(label, stage["status"], stage["detail"])
    console.print(table)
    if next_command:
        console.print(f"\n[bold]Next command[/bold]\n[cyan]{next_command}[/cyan]")
    elif current_stage == "complete":
        console.print("\n[green]Workflow artifacts are current.[/green]")
    else:
        console.print("\n[yellow]Add the missing coding configuration before continuing.[/yellow]")


__all__ = ["resolve_coding_config_files", "workflow"]


def _execution_options(func):
    """Keep plan and run options identical for reviewable execution plans."""
    from metaagent.workflow_runner import STAGES

    options = [
        click.option("--profile", "-p", default="task", help="Registered benchmark profile, or use --task-config."),
        click.option("--dataset-root", type=click.Path(path_type=Path, exists=True, file_okay=False), default="."),
        click.option("--task-config", type=click.Path(path_type=Path, exists=True, dir_okay=False), help="Standalone YAML/JSON review task, independent of benchmark profiles."),
        click.option("--document-manifest", type=click.Path(path_type=Path, exists=True, dir_okay=False)),
        click.option("--estimates-input", type=click.Path(path_type=Path, exists=True, dir_okay=False)),
        click.option("--chunk-chars", type=click.IntRange(min=256)),
        click.option("--stage-a-empty-retries", type=click.IntRange(min=0, max=2), default=None, help="Bounded A-only verification of empty candidates; inherits task settings."),
        click.option("--analysis-protocol", type=click.Path(path_type=Path, exists=True, dir_okay=False)),
        click.option("--synthesis-backend", type=click.Choice(["pi", "deterministic"]), default=None,
                     help="Pi plans, writes, executes and validates analysis code; old tasks retain deterministic synthesis."),
        click.option("--research-question", default=None, help="Synthesis question override; otherwise inherit the task/profile question."),
        click.option("--method-source", "method_sources", multiple=True, type=click.Path(path_type=Path, exists=True, dir_okay=False),
                     help="Explicit original method document; repeat for PDF/MD/TXT/HTML/DOCX sources."),
        click.option("--synthesis-max-executions", type=click.IntRange(1, 8), default=None),
        click.option("--synthesis-max-turns", type=click.IntRange(1, 100), default=None),
        click.option("--synthesis-max-tokens", type=click.IntRange(1, 1000000), default=None),
        click.option("--synthesis-total-timeout-s", type=click.IntRange(1, 86400), default=None),
        click.option("--synthesis-exec-timeout-s", type=click.IntRange(1, 3600), default=None),
        click.option("--pi-command", default=None, help="Pinned local Pi executable name/path; no shell evaluation."),
        click.option("--ablation", type=click.Choice(["full", "without_a", "without_b"]), default="full", show_default=True),
        click.option("--output-dir", type=click.Path(path_type=Path, file_okay=False), required=True),
        click.option("--project-root", type=click.Path(path_type=Path, exists=True, file_okay=False)),
        click.option("--start-at", type=click.Choice(STAGES), default="retrieval", show_default=True),
        click.option("--stop-after", type=click.Choice(STAGES), default="pooling", show_default=True),
        click.option("--input-mode", type=click.Choice(["search", "raw_search", "raw_pool"]), default="search", show_default=True,
                     help="search runs task sources or PubMed; raw_search replays a frozen natural pool; raw_pool explicitly opts into an augmented pool."),
        click.option("--raw-input", type=click.Path(path_type=Path, exists=True, dir_okay=False)),
        click.option("--query", help="Explicit final PubMed query, with any desired date filters included."),
        click.option("--model", envvar="WORKFLOW_LLM_MODEL", help="Optional global override; otherwise resolve each module independently."),
        click.option("--api-base", envvar="WORKFLOW_LLM_API_BASE", help="API base or complete /chat/completions URL."),
        click.option("--api-key-env", default="WORKFLOW_LLM_API_KEY", show_default=True),
        click.option("--limit", type=click.IntRange(min=1)),
        click.option("--resume/--no-resume", default=True, show_default=True),
        click.option("--batch-size", type=click.IntRange(min=1), default=20),
        click.option("--batch-concurrency", type=click.IntRange(min=1), default=1),
        click.option("--batch-mode", type=click.Choice(["single", "multi"]), default="single", show_default=True,
                     help="single makes one model request per record; multi sends a batch per request."),
        click.option("--strategy", type=click.Choice(["5d", "binary", "peco"]), default="5d"),
        click.option("--fetch-mode", type=click.Choice(["pmc_only"]), default="pmc_only"),
        click.option("--codebook", type=click.Path(path_type=Path, exists=True, dir_okay=False)),
        click.option("--parameter-type"),
        click.option("--estimate-measure", default="mean"),
        click.option("--pooling-method", type=click.Choice(["random", "fixed"]), default="random"),
        click.option("--extraction-backend", type=click.Choice(["llm", "langextract"]), default=None, help="Task coding backend; new tasks default to LangExtract inside A."),
        click.option("--skip-fulltext-screening", is_flag=True, help="Explicitly bypass eligibility screening for a fixed coding-only input set."),
        click.option("--temperature", type=float, default=None),
        click.option("--start-date", help="Publication start date for generated queries (YYYY-MM-DD)."),
        click.option("--end-date", help="Publication end date for generated queries (YYYY-MM-DD)."),
        click.option("--json", "json_output", is_flag=True),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def _safe_error_message(exc):
    """Expose actionable validation locations, never Pydantic inputs/YAML source."""
    from pydantic import ValidationError
    if isinstance(exc, ValidationError):
        message = "; ".join(".".join(map(str, item["loc"])) + ": " + item["msg"] for item in exc.errors(include_input=False))
    elif isinstance(exc, yaml.YAMLError):
        mark = getattr(exc, "problem_mark", None)
        message = f"Invalid YAML at line {mark.line + 1}, column {mark.column + 1}" if mark else "Invalid YAML; check indentation and document structure"
    else:
        message = str(exc)
    for key, value in os.environ.items():
        if ("API_KEY" in key or "AUTH_TOKEN" in key) and value and len(value) >= 4:
            message = message.replace(value, "[REDACTED]")
    # A credential can be accidentally pasted into a method/other rejected field
    # before it is configured in the environment. Do not echo common key tokens.
    return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", message)


def _command_failure(exc, json_output, *, suggestion="Correct the indicated configuration, then run workflow validate before retrying.", exit_code=1, manifest=None):
    detail = {"type": type(exc).__name__, "message": _safe_error_message(exc), "suggestion": suggestion, "retryable": False}
    if json_output:
        payload = dict(manifest or {})
        payload.setdefault("status", "failed")
        payload["error"] = detail
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        raise click.exceptions.Exit(exit_code) from exc
    error_type = click.UsageError if exit_code == 2 else click.ClickException
    raise error_type(detail["message"] + "\n" + suggestion) from exc


def _local_validation(options):
    if not options.task_config:
        return None
    from metaagent.workflow_task import validate_task_files
    from metaagent.workflow_runner import STAGES
    selected = STAGES[STAGES.index(options.start_at):STAGES.index(options.stop_after) + 1]
    return validate_task_files(Path(options.task_config), codebook_override=options.codebook,
                               backend_override=options.extraction_backend,
                               check_codebook="coding" in selected, check_analyses="pooling" in selected,
                               check_backend="coding" in selected and options.ablation != "without_a",
                               analysis_override=options.analysis_protocol, synthesis_options=options)


def _execute_workflow_command(*, dry_run, json_output, **kwargs):
    from metaagent.workflow_runner import WorkflowOptions, WorkflowRunError, plan_workflow, run_workflow
    try:
        # Preserve stdout as a single JSON document. Core diagnostics remain on stderr.
        with contextlib.redirect_stdout(sys.stderr) if json_output else contextlib.nullcontext():
            options = WorkflowOptions(**kwargs)
            validation = _local_validation(options)
            result = plan_workflow(options) if dry_run else run_workflow(options)
            if validation is not None:
                result["local_validation"] = validation
    except WorkflowRunError as exc:
        _command_failure(exc, json_output, manifest=exc.manifest,
                         suggestion=f"Inspect workflow status --output-dir {kwargs['output_dir']} and the recorded stage logs; fix the cause, then resume the original workflow run command.")
    except Exception as exc:
        _command_failure(exc, json_output)
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, default=str))
    else:
        click.echo(f"{result.get('status', 'planned')}: {result['profile']} ({result['pool_kind']})")
        click.echo("Stages: " + " -> ".join(result["stages"]))
        if not dry_run:
            click.echo(str(Path(result["output_dir"]) / "workflow_manifest.json"))
    if not dry_run and result.get("status") not in {"complete", "completed", "ok"}:
        raise click.exceptions.Exit(1)
    return result


@workflow.command("plan", cls=JsonOutputCommand)
@_execution_options
def plan_command(**kwargs):
    """Inspect an execution plan without network access or filesystem writes."""
    _execute_workflow_command(dry_run=True, **kwargs)


@workflow.command("run", cls=JsonOutputCommand)
@_execution_options
@click.option("--dry-run", is_flag=True, help="Render the same plan as workflow plan without executing.")
def run_command(dry_run, **kwargs):
    """Run any stage range, resuming only verified input/config/output hashes."""
    _execute_workflow_command(dry_run=dry_run, **kwargs)


@workflow.command('variants', cls=JsonOutputCommand)
@_execution_options
def variants_command(json_output, **kwargs):
    """Run explicit stage ablations against one frozen screened document bundle."""
    from metaagent.experiments import run_variants
    from metaagent.workflow_runner import WorkflowOptions, WorkflowRunError
    try:
        with contextlib.redirect_stdout(sys.stderr) if json_output else contextlib.nullcontext():
            options = WorkflowOptions(**kwargs)
            _local_validation(options)
            result = run_variants(options)
    except WorkflowRunError as exc:
        _command_failure(exc, json_output, manifest=exc.manifest)
    except Exception as exc:
        _command_failure(exc, json_output)
    click.echo(json.dumps(result, ensure_ascii=False) if json_output else f"{result['status']}: {Path(kwargs['output_dir']) / 'variants.json'}")
    if result['status'] != 'complete':
        raise click.exceptions.Exit(1)


@workflow.command('validate', cls=JsonOutputCommand)
@click.option('--task-config', required=True, type=click.Path(path_type=Path, dir_okay=False))
@click.option('--json', 'json_output', is_flag=True, help='Emit exactly one JSON validation result (also the default for this command).')
def validate_task_command(task_config, json_output):
    """Check task, review/analysis protocols, codebook and backend locally. No API calls.

    Example: metaagent workflow validate --task-config task.yaml --json
    """
    from metaagent.workflow_task import validate_task_files
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = validate_task_files(task_config)
    except Exception as exc:
        _command_failure(exc, True)
    click.echo(json.dumps(result, ensure_ascii=False))
