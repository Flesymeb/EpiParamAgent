"""Configuration-driven Schema system.

Load YAML config → Create dynamic Pydantic model → Generate prompts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field, create_model, field_validator, model_validator

logger = logging.getLogger(__name__)


@dataclass
class FieldConfig:
    """Configuration for a single field."""

    name: str
    label: str
    type: str  # str, int, float, bool, list[str], list[int]
    required: bool = False
    prompt: str = ""
    examples: List[str] = field(default_factory=list)
    range: Optional[List[Optional[float]]] = None  # [min, max]

    @classmethod
    def from_dict(cls, data: dict) -> "FieldConfig":
        return cls(
            name=data["name"],
            label=data.get("label", data["name"]),
            type=data.get("type", "str"),
            required=data.get("required", False),
            prompt=data.get("prompt", ""),
            examples=data.get("examples", []),
            range=data.get("range"),
        )


@dataclass
class ExtractionConfig:
    """Configuration for extraction mode and context handling."""

    mode: str = "full_context"  # "full_context" | "chunked"
    max_input_chars: int = 500000
    truncation_marker: str = "\n\n[... document truncated, {chars} chars omitted ...]"

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "ExtractionConfig":
        if not data:
            return cls()
        return cls(
            mode=data.get("mode", "full_context"),
            max_input_chars=data.get("max_input_chars", 500000),
            truncation_marker=data.get(
                "truncation_marker",
                "\n\n[... document truncated, {chars} chars omitted ...]",
            ),
        )


@dataclass
class QualityRules:
    """Quality scoring rules."""

    missing_penalties: Dict[str, float] = field(default_factory=dict)
    review_threshold: float = 0.7

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "QualityRules":
        if not data:
            return cls()
        return cls(
            missing_penalties=data.get("missing_penalties", {}),
            review_threshold=data.get("review_threshold", 0.7),
        )


@dataclass
class PromptConfig:
    """Prompt customization embedded in config."""

    system: str = ""
    user_preamble: str = ""
    output_rules: str = ""
    examples: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "PromptConfig":
        if not data:
            return cls()
        return cls(
            system=data.get("system", ""),
            user_preamble=data.get("user_preamble", ""),
            output_rules=data.get("output_rules", ""),
            examples=data.get("examples", []) or [],
        )


@dataclass
class ProjectConfig:
    """Complete project configuration."""

    name: str
    description: str = ""
    effect_type: str = ""
    fields: List[FieldConfig] = field(default_factory=list)
    extraction_instructions: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    prompt: "PromptConfig" = field(default_factory=lambda: PromptConfig())
    quality_rules: QualityRules = field(default_factory=QualityRules)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectConfig":
        project = data.get("project", {})
        fields_data = data.get("fields", [])
        quality_data = data.get("quality_rules")
        extraction_data = data.get("extraction")
        prompt_data = data.get("prompt")

        return cls(
            name=project.get("name", "Unnamed Project"),
            description=project.get("description", ""),
            effect_type=project.get("effect_type", ""),
            fields=[FieldConfig.from_dict(f) for f in fields_data],
            extraction_instructions=data.get("extraction_instructions", ""),
            parameters=data.get("parameters", {}) or {},
            notes=data.get("notes", "") or "",
            prompt=PromptConfig.from_dict(prompt_data),
            quality_rules=QualityRules.from_dict(quality_data),
            extraction=ExtractionConfig.from_dict(extraction_data),
        )


def _resolve_config_path(path: Path, base_dir: Optional[Path] = None) -> Path:
    configs_dir = Path(__file__).resolve().parents[2] / "configs"

    if base_dir and not path.is_absolute():
        candidate = (base_dir / path).resolve()
        if candidate.exists() and candidate.suffix == ".yaml":
            return candidate

    if path.exists() and path.suffix == ".yaml":
        return path

    path_str = str(path).replace("\\", "/")
    for name_variant in [path_str, path_str.replace("templates/", "")]:
        template_path = configs_dir / "templates" / f"{Path(name_variant).stem}.yaml"
        if template_path.exists():
            return template_path

    for name_variant in [path_str, path_str.replace("custom/", "")]:
        custom_path = configs_dir / "custom" / f"{Path(name_variant).stem}.yaml"
        if custom_path.exists():
            return custom_path

    direct_path = configs_dir / f"{path}.yaml"
    if direct_path.exists():
        return direct_path

    raise FileNotFoundError(
        f"Config not found: {path}. Available: {list_templates()} | {list_custom()}"
    )


def _load_yaml_dict(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML is required. Install with: pip install pyyaml")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def _extract_prompt_section(text: str, label: str) -> Optional[str]:
    import re

    pattern = rf"{label}\s*=\s*\"\"\"(.*?)\"\"\""
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()

    pattern = rf"\[{label}\](.*?)\[/\s*{label}\]"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()

    return None


def _apply_prompt_files(data: dict, base_dir: Path) -> dict:
    prompt = data.get("prompt")
    if not isinstance(prompt, dict):
        return data

    def _load_file(key: str, target: str) -> None:
        value = prompt.get(key)
        if not value:
            return
        p = Path(str(value))
        if not p.is_absolute():
            p = (base_dir / p).resolve()
        prompt[target] = p.read_text(encoding="utf-8")

    prompt_file = prompt.get("prompt_file")
    if prompt_file:
        p = Path(str(prompt_file))
        if not p.is_absolute():
            p = (base_dir / p).resolve()
        text = p.read_text(encoding="utf-8")

        system = _extract_prompt_section(text, "SYSTEM")
        user = _extract_prompt_section(text, "USER")
        output = _extract_prompt_section(text, "OUTPUT")
        if system:
            prompt["system"] = system
        if user:
            prompt["user_preamble"] = user
        if output:
            prompt["output_rules"] = output

    _load_file("system_file", "system")
    _load_file("user_preamble_file", "user_preamble")
    _load_file("output_rules_file", "output_rules")

    return data


def _merge_fields(base_fields: list, override_fields: list) -> list:
    if not override_fields:
        return base_fields
    base_by_name = {f.get("name"): f for f in base_fields if isinstance(f, dict)}
    override_by_name = {
        f.get("name"): f for f in override_fields if isinstance(f, dict)
    }

    merged: list = []
    for f in base_fields:
        name = f.get("name") if isinstance(f, dict) else None
        if name and name in override_by_name:
            merged.append({**f, **override_by_name[name]})
        else:
            merged.append(f)

    for name, f in override_by_name.items():
        if name not in base_by_name:
            merged.append(f)

    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _merge_configs(base: dict, override: dict) -> dict:
    result = dict(base)

    if "project" in override:
        result["project"] = _deep_merge(result.get("project", {}), override["project"])

    if "fields" in override:
        result["fields"] = _merge_fields(
            result.get("fields", []), override.get("fields", [])
        )

    if "prompt" in override:
        result["prompt"] = _deep_merge(result.get("prompt", {}), override["prompt"])

    if "extraction_instructions" in override:
        base_instr = (result.get("extraction_instructions") or "").strip()
        override_instr = (override.get("extraction_instructions") or "").strip()
        if base_instr and override_instr:
            result["extraction_instructions"] = base_instr + "\n\n" + override_instr
        else:
            result["extraction_instructions"] = override_instr or base_instr

    for key in ("quality_rules", "extraction", "parameters"):
        if key in override:
            result[key] = _deep_merge(result.get(key, {}), override[key])

    if "notes" in override:
        result["notes"] = override.get("notes", result.get("notes", ""))

    for k, v in override.items():
        if k in {
            "project",
            "fields",
            "prompt",
            "extraction_instructions",
            "quality_rules",
            "extraction",
            "parameters",
            "notes",
            "base",
        }:
            continue
        result[k] = v

    return result


def _normalize_stage_prompts(data: dict) -> dict:
    stage_b = data.get("stage_b")
    if isinstance(stage_b, dict):
        base_prompt = data.get("prompt")
        if not isinstance(base_prompt, dict):
            base_prompt = {}
        data["prompt"] = _deep_merge(base_prompt, stage_b)
    return data


def _load_config_dict(path: Path, visited: set[str]) -> dict:
    resolved = _resolve_config_path(path)
    resolved_key = str(resolved.resolve())
    if resolved_key in visited:
        raise ValueError(f"Config base cycle detected at: {resolved}")
    visited.add(resolved_key)

    data = _load_yaml_dict(resolved)
    if "base" in data:
        base_path = Path(str(data.get("base")))
        base_data = _load_config_dict(base_path, visited)
        data = _merge_configs(base_data, data)

    data = _normalize_stage_prompts(data)

    return data


def load_config(path: str | Path) -> ProjectConfig:
    path = Path(path)
    data = _load_config_dict(path, visited=set())
    resolved = _resolve_config_path(path)
    data = _apply_prompt_files(data, resolved.parent)
    config = ProjectConfig.from_dict(data)
    setattr(config, "_raw_config", data)
    setattr(config, "_config_path", resolved)
    return config


def list_templates() -> List[str]:
    templates_dir = Path(__file__).resolve().parents[2] / "configs" / "templates"
    if not templates_dir.exists():
        return []
    return [p.stem for p in templates_dir.glob("*.yaml")]


def list_custom() -> List[str]:
    custom_dir = Path(__file__).resolve().parents[2] / "configs" / "custom"
    items: List[str] = []
    if custom_dir.exists():
        items.extend([f"custom/{p.stem}" for p in custom_dir.glob("*.yaml")])
    return items


def _python_type(type_str: str) -> type:
    mapping = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list[str]": List[str],
        "list[int]": List[int],
        "dict": Dict[str, Any],
        "list[dict]": List[Dict[str, Any]],
    }
    return mapping.get(type_str, str)


def _build_field_definition(fc: FieldConfig) -> tuple[type, Any]:
    py_type = _python_type(fc.type)

    if fc.type == "str" and fc.required:
        default = ...
    else:
        py_type = Optional[py_type]
        default = None

    field_kwargs: Dict[str, Any] = {}
    if fc.range:
        min_val, max_val = fc.range
        if min_val is not None:
            field_kwargs["ge"] = min_val
        if max_val is not None:
            field_kwargs["le"] = max_val

    if fc.prompt:
        field_kwargs["description"] = fc.prompt

    if field_kwargs:
        return (py_type, Field(default=default, **field_kwargs))
    return (py_type, default)


def create_model_from_config(config: ProjectConfig) -> Type[BaseModel]:
    field_definitions: Dict[str, Any] = {}
    required_str_fields: List[str] = []

    for fc in config.fields:
        field_definitions[fc.name] = _build_field_definition(fc)
        if fc.type == "str" and fc.required:
            required_str_fields.append(fc.name)

    field_definitions.update(
        {
            "source_id": (Optional[str], None),
            "source_doi": (Optional[str], None),
            "source_database": (Optional[str], None),
            "extractor_model": (Optional[str], None),
            "extraction_timestamp": (
                str,
                Field(default_factory=lambda: datetime.now().isoformat()),
            ),
            "extraction_confidence": (float, Field(default=0.0, ge=0.0, le=1.0)),
            "needs_review": (bool, False),
            "review_notes": (Optional[str], None),
            "evidence_chunk_ids": (Optional[List[int]], Field(default=None)),
        }
    )

    model_name = config.name.replace(" ", "_").replace("-", "_")
    DynamicModel = create_model(model_name, **field_definitions)
    quality_rules = config.quality_rules

    class ValidatedModel(DynamicModel):  # type: ignore
        model_config = {"extra": "ignore"}

        @field_validator(*required_str_fields, mode="before")
        @classmethod
        def _non_empty_str(cls, v):
            if v is None:
                return "NR"
            v = str(v).strip()
            if not v:
                return "NR"
            return v

        @model_validator(mode="after")
        def _quality_check(self):
            confidence = 1.0
            notes: List[str] = []

            for field_name, penalty in quality_rules.missing_penalties.items():
                value = getattr(self, field_name, None)
                if value is None or (
                    isinstance(value, str) and value.strip().upper() in {"", "NR"}
                ):
                    confidence -= penalty
                    notes.append(f"Missing {field_name}")

            confidence = max(0.0, min(1.0, confidence))
            self.extraction_confidence = round(confidence, 3)

            if confidence < quality_rules.review_threshold:
                self.needs_review = True

            if notes:
                existing = (self.review_notes or "").strip()
                merged = "; ".join(notes)
                self.review_notes = f"{existing}; {merged}".strip("; ")

            return self

    ValidatedModel.__name__ = model_name
    ValidatedModel.__qualname__ = model_name

    ValidatedModel._project_config = config  # type: ignore

    return ValidatedModel


def get_model(config_or_template: str | Path | ProjectConfig) -> Type[BaseModel]:
    if isinstance(config_or_template, ProjectConfig):
        config = config_or_template
    else:
        config = load_config(config_or_template)
    return create_model_from_config(config)


def get_field_names(model: Type[BaseModel]) -> List[str]:
    config: Optional[ProjectConfig] = getattr(model, "_project_config", None)
    if config:
        return [f.name for f in config.fields]
    metadata_fields = {
        "source_id",
        "source_doi",
        "source_database",
        "extractor_model",
        "extraction_timestamp",
        "extraction_confidence",
        "needs_review",
        "review_notes",
        "evidence_chunk_ids",
    }
    return [k for k in model.model_fields.keys() if k not in metadata_fields]


def get_column_mapping(model: Type[BaseModel]) -> Dict[str, str]:
    config: Optional[ProjectConfig] = getattr(model, "_project_config", None)
    if not config:
        return {}
    return {f.name: f.label for f in config.fields}
