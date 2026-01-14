"""Dimension criteria loader and prompt formatter for multi-dimensional screening.

This module loads screening criteria from YAML configuration and formats them
for injection into LLM prompts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import yaml

logger = logging.getLogger(__name__)


def load_dimensions_from_yaml(yaml_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load screening dimension criteria from YAML file.

    Args:
        yaml_path: Path to dimensions YAML file. If None, uses default location.

    Returns:
        Dict containing dimensions list, aggregation settings, and export config.

    Raises:
        FileNotFoundError: If YAML file doesn't exist.
        yaml.YAMLError: If YAML is malformed.
    """
    if yaml_path is None:
        # Default to configs/screening_dimensions.yaml
        default_path = (
            Path(__file__).parent.parent.parent
            / "configs"
            / "screening_dimensions.yaml"
        )
        yaml_path = default_path

    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Screening dimensions config not found: {yaml_path}\n"
            f"Create this file or specify a custom path."
        )

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        logger.info(
            f"Loaded {len(config.get('dimensions', []))} screening dimensions from {yaml_path}"
        )
        return config

    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML file {yaml_path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error loading dimensions config: {e}")
        raise


def format_dimensions_for_prompt(
    dimensions: List[Dict[str, Any]], include_weights: bool = False
) -> str:
    """Format dimension criteria as numbered text for LLM prompt.

    Args:
        dimensions: List of dimension dicts from YAML config.
        include_weights: Whether to show weights in the formatted output.

    Returns:
        Formatted string with numbered dimensions and criteria.
    """
    lines = []

    for idx, dim in enumerate(dimensions, start=1):
        dim_id = dim.get("id", "unknown")
        name = dim.get("name", dim_id)
        weight = dim.get("weight", 0.0)
        description = dim.get("description", "")

        # Header with optional weight
        if include_weights:
            lines.append(f"## {idx}. {name} (Weight: {weight:.2f})")
        else:
            lines.append(f"## {idx}. {name}")

        if description:
            lines.append(f"**Question**: {description}")
            lines.append("")

        # Criteria for each score level
        criteria_high = dim.get("criteria_high", "").strip()
        criteria_medium = dim.get("criteria_medium", "").strip()
        criteria_low = dim.get("criteria_low", "").strip()
        criteria_uncertain = dim.get("criteria_uncertain", "").strip()

        if criteria_high:
            lines.append("**Score HIGH if:**")
            lines.append(criteria_high)
            lines.append("")

        if criteria_medium:
            lines.append("**Score MEDIUM if:**")
            lines.append(criteria_medium)
            lines.append("")

        if criteria_low:
            lines.append("**Score LOW if:**")
            lines.append(criteria_low)
            lines.append("")

        if criteria_uncertain:
            lines.append("**Score UNCERTAIN if:**")
            lines.append(criteria_uncertain)
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def get_dimension_weights(dimensions: List[Dict[str, Any]]) -> Dict[str, float]:
    """Extract dimension weights as a dict.

    Args:
        dimensions: List of dimension dicts from YAML config.

    Returns:
        Dict mapping dimension IDs to weights.
    """
    return {dim["id"]: dim.get("weight", 0.0) for dim in dimensions}


def get_aggregation_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract aggregation settings from config.

    Args:
        config: Full YAML config dict.

    Returns:
        Aggregation configuration dict.
    """
    return config.get(
        "aggregation",
        {
            "method": "weighted_sum",
            "thresholds": {"include": 0.70, "maybe": 0.40, "exclude": 0.40},
            "critical_exclusions": [],
        },
    )


def validate_config(config: Dict[str, Any]) -> None:
    """Validate screening dimensions config structure.

    Args:
        config: Loaded YAML config.

    Raises:
        ValueError: If config is invalid.
    """
    if "dimensions" not in config:
        raise ValueError("Config must contain 'dimensions' key")

    dimensions = config["dimensions"]
    if not isinstance(dimensions, list) or len(dimensions) == 0:
        raise ValueError("'dimensions' must be a non-empty list")

    # Check required fields for each dimension
    required_fields = ["id", "name", "weight"]
    for idx, dim in enumerate(dimensions):
        for field in required_fields:
            if field not in dim:
                raise ValueError(f"Dimension {idx} missing required field: '{field}'")

    # Validate weights sum to approximately 1.0
    total_weight = sum(dim.get("weight", 0.0) for dim in dimensions)
    if not (0.95 <= total_weight <= 1.05):
        logger.warning(
            f"Dimension weights sum to {total_weight:.3f}, expected ~1.0. "
            f"Weights may need adjustment."
        )

    logger.info(
        f"Config validation passed: {len(dimensions)} dimensions, total weight={total_weight:.3f}"
    )


def load_and_format_dimensions(
    yaml_path: Optional[Path] = None,
    include_weights: bool = False,
    validate: bool = True,
) -> tuple[str, Dict[str, float], Dict[str, Any]]:
    """Load dimensions and return formatted prompt text, weights, and config.

    Convenience function that combines loading, validation, and formatting.

    Args:
        yaml_path: Path to YAML config. If None, uses default.
        include_weights: Whether to show weights in formatted output.
        validate: Whether to validate config structure.

    Returns:
        Tuple of (formatted_prompt_text, dimension_weights_dict, aggregation_config)
    """
    config = load_dimensions_from_yaml(yaml_path)

    if validate:
        validate_config(config)

    dimensions = config["dimensions"]
    formatted_text = format_dimensions_for_prompt(dimensions, include_weights)
    weights = get_dimension_weights(dimensions)
    aggregation = get_aggregation_config(config)

    return formatted_text, weights, aggregation
