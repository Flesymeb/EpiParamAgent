"""Data-driven screening profile registry.

Profiles live in ``configs/screening_profiles/*.yaml`` so new evaluation
projects can be added without editing Python source files.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parents[2]
PROFILE_DIR = BASE_DIR / "configs" / "screening_profiles"


def _normalize_topic(topic: str) -> str:
    return str(topic).strip().lower().replace("-", "_").replace(" ", "_")


@dataclass(frozen=True)
class ScreeningProfile:
    id: str
    topic: str
    project_number: int
    research_question: str
    disease_focus: str
    disease_exclude: str
    transmission_focus: str
    transmission_exclude: str
    thresholds: dict[str, Any]
    policies: dict[str, Any]

    @property
    def topic_key(self) -> str:
        return _normalize_topic(self.topic)

    @property
    def profile_key(self) -> str:
        return self.id.upper()

    @property
    def project_dir_name(self) -> str:
        return f"p{self.project_number}"

    @property
    def project_file_stem(self) -> str:
        return f"project_{self.project_number}"

    def to_screening_config(self) -> dict[str, Any]:
        return {
            "profile_id": self.id,
            "topic": self.topic_key,
            "project_number": self.project_number,
            "research_question": self.research_question,
            "disease_focus": self.disease_focus,
            "disease_exclude": self.disease_exclude,
            "transmission_focus": self.transmission_focus,
            "transmission_exclude": self.transmission_exclude,
            "thresholds": self.thresholds,
            "policies": self.policies,
        }


@dataclass(frozen=True)
class ScreeningProjectPaths:
    topic: str
    topic_dir: Path
    project_dir: Path
    raw_file: Path
    ground_truth_file: Path
    screened_file: Path


def _merge_profile(defaults: dict[str, Any], profile_id: str, topic: str, raw: dict[str, Any]) -> ScreeningProfile:
    merged = {**defaults, **raw}
    return ScreeningProfile(
        id=profile_id.upper(),
        topic=_normalize_topic(topic),
        project_number=int(merged["project_number"]),
        research_question=str(merged["research_question"]),
        disease_focus=str(merged["disease_focus"]),
        disease_exclude=str(merged.get("disease_exclude", "none")),
        transmission_focus=str(merged["transmission_focus"]),
        transmission_exclude=str(merged.get("transmission_exclude", "none")),
        thresholds=dict(merged.get("thresholds", {})),
        policies=dict(merged.get("policies", {})),
    )


@lru_cache(maxsize=1)
def load_profile_registry() -> dict[str, ScreeningProfile]:
    registry: dict[str, ScreeningProfile] = {}
    if not PROFILE_DIR.exists():
        raise FileNotFoundError(f"Missing screening profile directory: {PROFILE_DIR}")

    for yaml_file in sorted(PROFILE_DIR.glob("*.yaml")):
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        topic = _normalize_topic(data.get("topic") or yaml_file.stem)
        defaults = {
            "thresholds": data.get("defaults", {}).get("thresholds", {}),
            "policies": data.get("defaults", {}).get("policies", {}),
        }
        profiles = data.get("profiles", {}) or {}
        for profile_id, profile_data in profiles.items():
            profile = _merge_profile(defaults, profile_id, topic, profile_data or {})
            registry[profile.profile_key] = profile

    return registry


def get_profile(profile_name: str | None) -> ScreeningProfile | None:
    if not profile_name:
        return None
    return load_profile_registry().get(str(profile_name).upper())


def resolve_profile_paths(
    *,
    project_root: str | Path,
    profile_name: str,
    topic: str | None = None,
) -> tuple[ScreeningProfile, ScreeningProjectPaths]:
    profile = get_profile(profile_name)
    if profile is None:
        raise KeyError(f"Unknown screening profile: {profile_name}")

    topic_key = _normalize_topic(topic) if topic else profile.topic_key
    base_dir = (
        Path(project_root)
        / "evaluation"
        / "screening"
        / "GT_1"
        / "GT_export"
        / topic_key
    )
    project_dir = base_dir / profile.project_dir_name
    stem = profile.project_file_stem
    paths = ScreeningProjectPaths(
        topic=topic_key,
        topic_dir=base_dir,
        project_dir=project_dir,
        raw_file=project_dir / f"{stem}_raw.csv",
        ground_truth_file=project_dir / f"{stem}_groundtruth.csv",
        screened_file=project_dir / f"{stem}_screened.csv",
    )
    return profile, paths


__all__ = [
    "ScreeningProfile",
    "ScreeningProjectPaths",
    "get_profile",
    "load_profile_registry",
    "resolve_profile_paths",
]
