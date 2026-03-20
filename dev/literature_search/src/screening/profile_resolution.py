"""Resolve screening profiles and explicit filesystem inputs for CLI workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .profile_registry import get_profile, resolve_profile_paths


def _normalize_topic(topic: str) -> str:
    return str(topic).strip().lower().replace("-", "_").replace(" ", "_")


def resolve_profile_config(
    profile_name: str | None,
    topic: str | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Resolve a screening profile dict and its research question."""
    profile_config = None
    research_question = "Epidemiology screening workflow"
    if not profile_name:
        return profile_config, research_question

    profile = get_profile(profile_name)
    if profile is None:
        raise KeyError(f"Unknown screening profile: {profile_name}")

    profile_config = profile.to_screening_config()
    if topic and profile_config.get("topic") != _normalize_topic(topic):
        profile_config["topic_override"] = str(topic).strip()
    research_question = profile_config.get("research_question", research_question)
    print(f"✓ 使用 profile: {profile.profile_key}")
    print(f"  Topic: {profile.topic_key}")
    print(f"  Project: {profile.project_dir_name}")
    print(f"  Research question: {research_question}")
    print(f"  Disease focus: {profile_config['disease_focus'][:80]}...")
    print(f"  Transmission focus: {profile_config['transmission_focus'][:80]}...\n")

    return profile_config, research_question


def resolve_explicit_cli_paths(
    *,
    base_dir: Path,
    input_raw: str,
    output_raw: str,
    ground_truth_raw: str,
) -> tuple[Path, Path, Path]:
    """Resolve explicit CLI path arguments relative to the literature_search root."""

    def resolve_arg(raw: str) -> Path:
        path = Path(str(raw).strip().strip("\"'").strip()).expanduser()
        return path if path.is_absolute() else (base_dir / path).resolve()

    return (
        resolve_arg(input_raw),
        resolve_arg(output_raw),
        resolve_arg(ground_truth_raw),
    )


def resolve_profile_io_paths(
    *,
    project_root: str | Path,
    profile_name: str,
    topic: str | None = None,
) -> tuple[dict[str, Any], Path, Path, Path]:
    """Resolve profile metadata and canonical IO paths for an evaluation project."""
    profile, paths = resolve_profile_paths(
        project_root=project_root,
        profile_name=profile_name,
        topic=topic,
    )
    return (
        profile.to_screening_config(),
        paths.raw_file,
        paths.screened_file,
        paths.ground_truth_file,
    )


__all__ = [
    "resolve_explicit_cli_paths",
    "resolve_profile_config",
    "resolve_profile_io_paths",
]
