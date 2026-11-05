"""Evaluation reporting and visualization commands."""

from __future__ import annotations

from pathlib import Path

import click

from metaagent._cli_shared import StyledGroup
from metaagent.evaluation.visualization import (
    plot_coding_intervals,
    plot_screening_recall_nns,
    read_coding_rows,
    read_screening_rows,
)


@click.group(cls=StyledGroup)
def evaluation():
    """Experiment analysis and paper visualization."""


@evaluation.command("diagnose")
@click.option("--manifest", "manifest_path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--json", "json_output", is_flag=True, help="Emit the structured observed-attrition report.")
def diagnose(manifest_path, output, json_output):
    """Inspect existing workflow artifacts without models, network or gold data."""
    import json
    from .diagnostics import diagnose_workflow
    try:
        result = diagnose_workflow(manifest_path)
        encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(encoded, encoding="utf-8")
    except (OSError, ValueError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output or output is None:
        click.echo(encoded, nl=False)
    else:
        click.echo(str(output))


@evaluation.command("plot-screening")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("output/paper_figures/screening/screening_recall_nns.png"),
)
@click.option("--title", default="Screening Performance by Literature")
def plot_screening(input_path: Path, output: Path, title: str) -> None:
    """Plot per-literature recall and NNS from screening summaries."""
    rows = read_screening_rows(input_path)
    plot_screening_recall_nns(rows, output, title=title)
    alt = output.with_suffix(".pdf") if output.suffix.lower() != ".pdf" else output.with_suffix(".png")
    click.echo(f"Saved {output} and {alt}")


@evaluation.command("plot-coding")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("output/paper_figures/coding/coding_intervals.png"),
)
@click.option("--title", default="Coding Estimates vs Source Review")
@click.option("--x-label", default="")
def plot_coding(input_path: Path, output: Path, title: str, x_label: str) -> None:
    """Plot SR reference intervals versus LLM coding estimates."""
    rows = read_coding_rows(input_path)
    plot_coding_intervals(rows, output, title=title, x_label=x_label or None)
    alt = output.with_suffix(".pdf") if output.suffix.lower() != ".pdf" else output.with_suffix(".png")
    click.echo(f"Saved {output} and {alt}")


@evaluation.command("benchmark")
@click.option("--dataset-root", type=click.Path(exists=True, file_okay=False, path_type=Path), default=Path("dataset/benchmark_releases/20261104_experiment_ready_v1"), show_default=True)
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("evaluation/experiment_ready_v1"), show_default=True)
@click.option("--run-id", required=True)
@click.option("--profile", "profiles", multiple=True, help="Repeat for a subset; omitted means every task in profiles.csv.")
@click.option("--mode", "modes", multiple=True, type=click.Choice(["screening", "coding", "synthesis", "e2e"]), default=("screening",), show_default=True)
@click.option("--input-mode", type=click.Choice(["search", "raw_search", "raw_pool"]), default="search", show_default=True, help="E2E defaults to natural retrieval; screening uses a frozen raw_search pool. raw_pool is explicitly augmented.")
@click.option("--limit", type=click.IntRange(min=1), default=None, help="Explicit first-N per task; recorded as a limited subset, not full evaluation.")
@click.option("--resume", is_flag=True, help="Reuse only an identical benchmark/model/backend/limit fingerprint.")
@click.option("--model", default="", help="Required for model modes; omitted for synthesis-only.")
@click.option("--api-base", default="", help="Required for model modes; omitted for synthesis-only.")
@click.option("--api-key-env", default="WORKFLOW_LLM_API_KEY", show_default=True)
@click.option("--extraction-backend", type=click.Choice(["llm", "langextract"]), default="langextract", show_default=True)
@click.option("--synthesis-backend", type=click.Choice(["deterministic", "pi"]), default="deterministic", show_default=True, help="Synthesis backend for e2e; independent synthesis mode retains its deterministic contract.")
@click.option("--reference-policy", type=click.Choice(["strict", "source_transcribed"]), default="strict", show_default=True, help="source_transcribed scores provisional source-table references; it does not imply expert adjudication.")
@click.option("--batch-size", type=click.IntRange(min=1), default=20, show_default=True)
@click.option("--batch-concurrency", type=click.IntRange(min=1), default=1, show_default=True)
@click.option("--batch-mode", type=click.Choice(["single", "multi"]), default="single", show_default=True, help="Explicit screening request layout; multi sends independently identified papers in a shared request.")
@click.option("--codebook", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option("--retrieval-plan", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="JSON list of profile/executed_query/deviations; explicit E2E queries, no silent fallback for missing tasks.")
@click.option("--reference-target", default=None, help="Explicit catalog target ID for deterministic source-oracle synthesis; omitted selects declared main target.")
@click.option("--analysis-protocol", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Explicit YAML/JSON analysis protocol, otherwise task.json.analysis_protocol.")
@click.option("--synthesis-input", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Structured estimate input for synthesis mode, otherwise task synthesis_input.jsonl.")
@click.option("--plan", "plan_only", is_flag=True, help="Validate/show the experiment without API calls or writes.")
@click.option("--json", "json_output", is_flag=True)
def benchmark(dataset_root, output_dir, run_id, profiles, modes, input_mode, limit, resume, model, api_base, api_key_env, extraction_backend, synthesis_backend, reference_policy, batch_size, batch_concurrency, batch_mode, codebook, retrieval_plan, reference_target, analysis_protocol, synthesis_input, plan_only, json_output):
    """Run task-level screening, extraction, or end-to-end benchmark evaluation."""
    import json

    from .benchmark import BenchmarkOptions, plan_benchmark, run_benchmark

    options = BenchmarkOptions(dataset_root=dataset_root, output_dir=output_dir, run_id=run_id, profiles=profiles, modes=modes, input_mode=input_mode, limit=limit, resume=resume, model=model, api_base=api_base, api_key_env=api_key_env, extraction_backend=extraction_backend, synthesis_backend=synthesis_backend, reference_policy=reference_policy, batch_size=batch_size, batch_concurrency=batch_concurrency, batch_mode=batch_mode, codebook=codebook, retrieval_plan=retrieval_plan, analysis_protocol=analysis_protocol, synthesis_input=synthesis_input, reference_target=reference_target)
    try:
        result = plan_benchmark(options) if plan_only else run_benchmark(options)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    elif plan_only:
        click.echo(f"Plan: {len(result['tasks'])} task(s), modes={','.join(modes)}, input={input_mode}, limit={limit}, backend={extraction_backend}")
        click.echo(f"Fingerprint: {result['fingerprint']}")
    else:
        click.echo(f"{result['status']}: {output_dir / run_id / 'benchmark_run.json'}")
    if not plan_only and result["status"] != "completed":
        raise click.exceptions.Exit(1)
