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


# ============================================================================
# Configuration Data Classes
# ============================================================================


@dataclass
class FieldConfig:
    """Configuration for a single field."""

    name: str
    label: str
    type: str  # str, int, float, bool, list[str], list[int]
    required: bool = False
    prompt: str = ""
    examples: List[str] = field(default_factory=list)
    range: Optional[List[Optional[float]]] = None  # [min, max], None means no limit

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

    mode: str = "chunked"  # "full_context" | "chunked"
    max_input_chars: int = 500000  # ~125k tokens
    truncation_marker: str = "\n\n[... document truncated, {chars} chars omitted ...]"

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "ExtractionConfig":
        if not data:
            return cls()
        return cls(
            mode=data.get("mode", "chunked"),
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
class ProjectConfig:
    """Complete project configuration."""

    name: str
    description: str = ""
    effect_type: str = "correlation"
    fields: List[FieldConfig] = field(default_factory=list)
    extraction_instructions: str = ""
    quality_rules: QualityRules = field(default_factory=QualityRules)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectConfig":
        project = data.get("project", {})
        fields_data = data.get("fields", [])
        quality_data = data.get("quality_rules")
        extraction_data = data.get("extraction")

        return cls(
            name=project.get("name", "Unnamed Project"),
            description=project.get("description", ""),
            effect_type=project.get("effect_type", "correlation"),
            fields=[FieldConfig.from_dict(f) for f in fields_data],
            extraction_instructions=data.get("extraction_instructions", ""),
            quality_rules=QualityRules.from_dict(quality_data),
            extraction=ExtractionConfig.from_dict(extraction_data),
        )


# ============================================================================
# Configuration Loading
# ============================================================================


def load_config(path: str | Path) -> ProjectConfig:
    """Load configuration from YAML file.

    Args:
        path: Path to YAML config file, or name of built-in template/example.
              Templates: "correlation", "intervention"
              Examples: "examples/early_numeracy"

    Returns:
        ProjectConfig object
    """
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML is required. Install with: pip install pyyaml")

    path = Path(path)
    configs_dir = Path(__file__).parent / "configs"

    # If file exists directly, use it
    if path.exists() and path.suffix == ".yaml":
        pass  # use path as-is
    # Check if it's a built-in template or example name
    elif not path.suffix or not path.exists():
        resolved = False

        # Normalize path separators for matching
        path_str = str(path).replace("\\", "/")

        # Try templates first (e.g., "correlation" or "templates/correlation")
        for name_variant in [path_str, path_str.replace("templates/", "")]:
            template_path = (
                configs_dir / "templates" / f"{Path(name_variant).stem}.yaml"
            )
            if template_path.exists():
                path = template_path
                resolved = True
                break

        if not resolved:
            # Try examples (e.g., "examples/early_numeracy" or "early_numeracy")
            for name_variant in [path_str, path_str.replace("examples/", "")]:
                example_path = (
                    configs_dir / "examples" / f"{Path(name_variant).stem}.yaml"
                )
                if example_path.exists():
                    path = example_path
                    resolved = True
                    break

        if not resolved:
            # Try direct path under configs (backward compat)
            direct_path = configs_dir / f"{path}.yaml"
            if direct_path.exists():
                path = direct_path
                resolved = True

        if not resolved:
            raise FileNotFoundError(
                f"Config not found: {path}. "
                f"Available: {list_templates()} | {list_examples()}"
            )

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return ProjectConfig.from_dict(data)


def list_templates() -> List[str]:
    """List available built-in templates."""
    templates_dir = Path(__file__).parent / "configs" / "templates"
    if not templates_dir.exists():
        return []
    return [p.stem for p in templates_dir.glob("*.yaml")]


def list_examples() -> List[str]:
    """List available example configurations."""
    examples_dir = Path(__file__).parent / "configs" / "examples"
    if not examples_dir.exists():
        return []
    return [f"examples/{p.stem}" for p in examples_dir.glob("*.yaml")]


# ============================================================================
# Dynamic Model Creation
# ============================================================================


def _python_type(type_str: str) -> type:
    """Convert config type string to Python type."""
    mapping = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list[str]": List[str],
        "list[int]": List[int],
    }
    return mapping.get(type_str, str)


def _build_field_definition(
    fc: FieldConfig,
) -> tuple[type, Any]:
    """Build Pydantic field definition from config."""
    py_type = _python_type(fc.type)

    # Handle optional fields
    if not fc.required:
        py_type = Optional[py_type]
        default = None
    else:
        default = ...  # Required marker

    # Build Field constraints
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
    else:
        return (py_type, default)


def create_model_from_config(config: ProjectConfig) -> Type[BaseModel]:
    """Dynamically create a Pydantic model from configuration.

    Args:
        config: ProjectConfig object

    Returns:
        A new Pydantic BaseModel class with fields from config
    """
    # Build field definitions
    field_definitions: Dict[str, Any] = {}
    required_str_fields: List[str] = []

    for fc in config.fields:
        field_definitions[fc.name] = _build_field_definition(fc)

        if fc.type == "str" and fc.required:
            required_str_fields.append(fc.name)

    # Add metadata fields (always present)
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
            "evidence_chunk_ids": (
                Optional[List[int]],
                Field(default=None, max_length=10),
            ),
        }
    )

    # Create base model
    model_name = config.name.replace(" ", "_").replace("-", "_")
    DynamicModel = create_model(model_name, **field_definitions)

    # Create validated version with quality scoring
    quality_rules = config.quality_rules

    class ValidatedModel(DynamicModel):  # type: ignore
        """Model with validation and quality scoring."""

        model_config = {"extra": "ignore"}  # Ignore unknown fields from LLM

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

            # Apply missing penalties
            for field_name, penalty in quality_rules.missing_penalties.items():
                value = getattr(self, field_name, None)
                if value is None:
                    confidence -= penalty
                    notes.append(f"Missing {field_name}")

            # Clamp confidence
            confidence = max(0.0, min(1.0, confidence))
            self.extraction_confidence = round(confidence, 3)

            # Flag for review
            if confidence < quality_rules.review_threshold:
                self.needs_review = True

            # Merge notes
            if notes:
                existing = (self.review_notes or "").strip()
                merged = "; ".join(notes)
                self.review_notes = f"{existing}; {merged}".strip("; ")

            return self

    ValidatedModel.__name__ = model_name
    ValidatedModel.__qualname__ = model_name

    # Attach config for later use (prompt generation, export)
    ValidatedModel._project_config = config  # type: ignore

    return ValidatedModel


# ============================================================================
# Convenience Functions
# ============================================================================


def get_model(config_or_template: str | Path | ProjectConfig) -> Type[BaseModel]:
    """Get a Pydantic model from config path, template name, or ProjectConfig.

    Args:
        config_or_template: One of:
            - Path to YAML config file
            - Built-in template name ("correlation", "intervention")
            - ProjectConfig object

    Returns:
        Pydantic BaseModel class
    """
    if isinstance(config_or_template, ProjectConfig):
        config = config_or_template
    else:
        config = load_config(config_or_template)

    return create_model_from_config(config)


def get_field_names(model: Type[BaseModel]) -> List[str]:
    """Get user-defined field names (excluding metadata fields)."""
    config: Optional[ProjectConfig] = getattr(model, "_project_config", None)
    if config:
        return [f.name for f in config.fields]
    # Fallback: all fields except known metadata
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
    """Get field name → Excel column label mapping."""
    config: Optional[ProjectConfig] = getattr(model, "_project_config", None)
    if not config:
        return {}
    return {f.name: f.label for f in config.fields}
