"""Data-driven screening profile registry.

Profiles live in ``configs/{disease}/screening_profiles/*.yaml``. Fixed task
inputs live in ``dataset/{disease}/screening/{topic}/pN/`` and run outputs live
under ``evaluation/screening/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = BASE_DIR / "configs"
DATASET_DIR = BASE_DIR / "dataset"
DATASET_DISEASE_DIRS = {
    "covid19": "covid19",
    "covid_19": "covid19",
    "covid-19": "covid19",
    "mpox": "mpox",
}


def _normalize_topic(topic: str) -> str:
    return str(topic).strip().lower().replace("-", "_").replace(" ", "_")


def _dataset_disease_dir_name(disease_key: str) -> str:
    return DATASET_DISEASE_DIRS.get(_normalize_topic(disease_key), disease_key)


@dataclass(frozen=True)
class ScreeningProfile:
    id: str
    topic: str
    disease: str
    project_number: int
    research_question: str
    disease_focus: str
    disease_exclude: str
    parameter_focus: str
    parameter_exclude: str
    thresholds: dict[str, Any]
    policies: dict[str, Any]

    @property
    def topic_key(self) -> str:
        """Pure epidemiological parameter name (fatality, serial_interval, etc.)."""
        return _normalize_topic(self.topic)

    @property
    def disease_key(self) -> str:
        """Disease identifier (covid19, mpox, etc.)."""
        return _normalize_topic(self.disease)

    @property
    def path_key(self) -> str:
        """Two-level path segment: disease/parameter."""
        return f"{self.disease_key}/{self.topic_key}"

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
            "disease": self.disease_key,
            "topic": self.topic_key,
            "project_number": self.project_number,
            "research_question": self.research_question,
            "disease_focus": self.disease_focus,
            "disease_exclude": self.disease_exclude,
            "parameter_focus": self.parameter_focus,
            "parameter_exclude": self.parameter_exclude,
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


def _merge_profile(defaults: dict[str, Any], profile_id: str, topic: str, disease: str, raw: dict[str, Any]) -> ScreeningProfile:
    merged = {**defaults, **raw}
    merged["thresholds"] = {
        **(defaults.get("thresholds", {}) or {}),
        **(raw.get("thresholds", {}) or {}),
    }
    merged["policies"] = {
        **(defaults.get("policies", {}) or {}),
        **(raw.get("policies", {}) or {}),
    }
    return ScreeningProfile(
        id=profile_id.upper(),
        topic=_normalize_topic(topic),
        disease=_normalize_topic(disease),
        project_number=int(merged["project_number"]),
        research_question=str(merged["research_question"]),
        disease_focus=str(merged["disease_focus"]),
        disease_exclude=str(merged.get("disease_exclude", "none")),
        parameter_focus=str(merged["parameter_focus"]),
        parameter_exclude=str(merged.get("parameter_exclude", "none")),
        thresholds=dict(merged.get("thresholds", {})),
        policies=dict(merged.get("policies", {})),
    )


@lru_cache(maxsize=1)
def load_profile_registry() -> dict[str, ScreeningProfile]:
    registry: dict[str, ScreeningProfile] = {}
    if not CONFIG_DIR.exists():
        raise FileNotFoundError(f"Missing config directory: {CONFIG_DIR}")

    yaml_files = [
        path
        for path in sorted(CONFIG_DIR.glob("*/screening_profiles/*.yaml"))
        if not path.name.startswith("_")
    ]
    if not yaml_files:
        raise FileNotFoundError(f"No screening profiles found under: {CONFIG_DIR}")

    for yaml_file in yaml_files:
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        topic = _normalize_topic(data.get("topic") or yaml_file.stem)
        disease = _normalize_topic(data.get("disease", ""))
        defaults = {
            "thresholds": data.get("defaults", {}).get("thresholds", {}),
            "policies": data.get("defaults", {}).get("policies", {}),
        }
        profiles = data.get("profiles", {}) or {}
        for profile_id, profile_data in profiles.items():
            profile = _merge_profile(defaults, profile_id, topic, disease, profile_data or {})
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
    disease: str | None = None,
    experiment: str | None = None,
) -> tuple[ScreeningProfile, ScreeningProjectPaths]:
    profile = get_profile(profile_name)
    if profile is None:
        raise KeyError(f"Unknown screening profile: {profile_name}")

    topic_key = _normalize_topic(topic) if topic else profile.topic_key
    disease_key = _normalize_topic(disease) if disease else profile.disease_key
    dataset_topic_dir = (
        Path(project_root)
        / "dataset"
        / _dataset_disease_dir_name(disease_key)
        / "screening"
        / topic_key
    )
    dataset_project_dir = dataset_topic_dir / profile.project_dir_name
    output_topic_dir = (
        Path(project_root)
        / "evaluation"
        / "screening"
        / _dataset_disease_dir_name(disease_key)
        / topic_key
    )
    output_project_dir = output_topic_dir / profile.project_dir_name
    legacy_project_dir = (
        Path(project_root)
        / "dataset"
        / "_legacy_imports"
        / "evaluation_legacy"
        / "screening"
        / disease_key
        / "GT_1"
        / "GT_export"
        / topic_key
        / profile.project_dir_name
    )
    stem = profile.project_file_stem

    raw_candidates = [
        dataset_project_dir / "raw.csv",
        dataset_project_dir / f"{stem}_raw.csv",
        legacy_project_dir / f"{stem}_raw.csv",
    ]
    raw_file = next((path for path in raw_candidates if path.exists()), raw_candidates[0])

    ground_truth_candidates = [
        dataset_project_dir / "ground_truth.csv",
        dataset_project_dir / f"{stem}_groundtruth.csv",
        legacy_project_dir / f"{stem}_groundtruth.csv",
    ]
    ground_truth_file = next(
        (path for path in ground_truth_candidates if path.exists()),
        ground_truth_candidates[0],
    )

    # Fixed task inputs live under dataset/. New run outputs live under
    # evaluation/ so experiments do not mix with input data.
    if experiment:
        screened_dir = output_project_dir / "experiments" / experiment
    else:
        screened_dir = output_project_dir

    paths = ScreeningProjectPaths(
        topic=topic_key,
        topic_dir=dataset_topic_dir,
        project_dir=dataset_project_dir,
        raw_file=raw_file,
        ground_truth_file=ground_truth_file,
        screened_file=screened_dir / f"{stem}_screened.csv",
    )
    return profile, paths


__all__ = [
    "ScreeningProfile",
    "ScreeningProjectPaths",
    "get_profile",
    "load_profile_registry",
    "resolve_profile_paths",
]
