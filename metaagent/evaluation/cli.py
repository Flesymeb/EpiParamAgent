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
