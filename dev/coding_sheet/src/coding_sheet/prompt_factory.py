"""Dynamic prompt generation from configuration.

Generates FIELD_DESCRIPTIONS and prompts from ProjectConfig.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from .config_schema import FieldConfig, ProjectConfig


def generate_field_descriptions(config: ProjectConfig) -> str:
    """Generate field descriptions section for LLM prompt.

    Args:
        config: ProjectConfig object

    Returns:
        Formatted string describing all fields
    """
    lines = [
        "# Field Extraction Guide",
        "",
        f"Project: {config.name}",
        f"Effect Type: {config.effect_type}",
        "",
        "Return a JSON array. Each item represents ONE effect-size record.",
        "If data not found: use null for numbers, 'NR' for required strings.",
        "",
        "## Fields",
        "",
    ]

    for fc in config.fields:
        # Field name and type
        type_str = fc.type
        if not fc.required:
            type_str += " | null"

        line = f"- **{fc.name}** ({type_str})"

        # Add range constraint
        if fc.range:
            min_val, max_val = fc.range
            if min_val is not None and max_val is not None:
                line += f" [range: {min_val} to {max_val}]"
            elif min_val is not None:
                line += f" [min: {min_val}]"
            elif max_val is not None:
                line += f" [max: {max_val}]"

        # Add required marker
        if fc.required:
            line += " **(required)**"

        lines.append(line)

        # Add prompt/description
        if fc.prompt:
            # Handle multi-line prompts
            prompt_lines = fc.prompt.strip().split("\n")
            for pl in prompt_lines:
                lines.append(f"  {pl.strip()}")

        # Add examples
        if fc.examples:
            examples_str = ", ".join(f'"{e}"' for e in fc.examples[:3])
            lines.append(f"  Examples: {examples_str}")

        lines.append("")  # Blank line between fields

    # Add evidence fields
    lines.extend(
        [
            "## Evidence Tracking",
            "",
            "- **evidence_chunk_ids** (list[int] | null)",
            "  IDs of source chunks used (reference <source id='N'> blocks)",
            "  Include 1-5 most relevant chunk IDs",
            "",
        ]
    )

    return "\n".join(lines)


def generate_extraction_rules(config: ProjectConfig) -> str:
    """Generate extraction rules section.

    Args:
        config: ProjectConfig object

    Returns:
        Formatted extraction instructions
    """
    if config.extraction_instructions:
        return config.extraction_instructions.strip()

    # Default rules if none provided
    return """## Default Extraction Rules

1. Create ONE record per unique effect size
2. If multiple predictors/outcomes/timepoints exist, create separate records
3. Use exact values from the paper, do not calculate or infer
4. Note any uncertainties in the notes field
"""


def generate_examples(
    config: ProjectConfig, examples: Optional[List[Dict]] = None
) -> str:
    """Generate example records as JSON.

    Args:
        config: ProjectConfig object
        examples: Optional custom examples, otherwise generates placeholder

    Returns:
        JSON string of examples
    """
    if examples:
        return json.dumps(examples, ensure_ascii=False, indent=2)

    # Generate placeholder example from field config
    example = {}
    for fc in config.fields:
        if fc.examples:
            example[fc.name] = fc.examples[0]
        elif fc.type == "str":
            example[fc.name] = "Example value" if fc.required else None
        elif fc.type == "int":
            example[fc.name] = 100 if fc.name == "n" else 1
        elif fc.type == "float":
            if fc.range and fc.range[0] is not None and fc.range[1] is not None:
                example[fc.name] = round((fc.range[0] + fc.range[1]) / 2, 2)
            else:
                example[fc.name] = 0.5
        else:
            example[fc.name] = None

    example["evidence_chunk_ids"] = [0, 1]

    return json.dumps([example], ensure_ascii=False, indent=2)


def build_system_prompt(config: ProjectConfig) -> str:
    """Build complete system prompt for LLM.

    Args:
        config: ProjectConfig object

    Returns:
        Complete system prompt string
    """
    field_desc = generate_field_descriptions(config)
    rules = generate_extraction_rules(config)

    return f"""You are an expert meta-analyst extracting coding-sheet data from research papers.

{field_desc}

{rules}

## Output Format

Return ONLY a valid JSON array. No markdown code blocks, no explanations.
Each array item is one record with the fields defined above.
"""


def build_user_prompt(
    config: ProjectConfig,
    *,
    title: str,
    abstract: str,
    sources_xml: str,
    examples: Optional[List[Dict]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Build user prompt with paper content.

    Args:
        config: ProjectConfig object
        title: Paper title
        abstract: Paper abstract
        sources_xml: XML-formatted source chunks
        examples: Optional example records
        metadata: Optional paper metadata (doi, year, etc.)

    Returns:
        User prompt string
    """
    examples_json = generate_examples(config, examples)

    # Build metadata section if available
    metadata_section = ""
    if metadata:
        meta_lines = []
        if metadata.get("doi"):
            meta_lines.append(f"**DOI:** {metadata['doi']}")
        if metadata.get("year"):
            meta_lines.append(f"**Year:** {metadata['year']}")
        if meta_lines:
            metadata_section = "\n".join(meta_lines) + "\n\n"

    return f"""# Paper

**Title:** {title}

{metadata_section}**Abstract:** {abstract[:2000]}

## Evidence Sources

Each source has an ID you can reference in evidence_chunk_ids:

{sources_xml}

## Example Output Format

{examples_json}

---

Now extract all records from this paper. Return JSON array only."""


# ============================================================================
# Model-based convenience functions
# ============================================================================


def build_prompts_from_model(
    model: Type[BaseModel],
    *,
    title: str,
    abstract: str,
    sources_xml: str,
    examples: Optional[List[Dict]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> tuple[str, str]:
    """Build system and user prompts from a model with attached config.

    Args:
        model: Pydantic model created by create_model_from_config
        title: Paper title
        abstract: Paper abstract
        sources_xml: XML-formatted source chunks
        examples: Optional example records
        metadata: Optional paper metadata (doi, year, etc.)

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    config: Optional[ProjectConfig] = getattr(model, "_project_config", None)
    if not config:
        raise ValueError(
            "Model has no _project_config. "
            "Use create_model_from_config() to create the model."
        )

    system = build_system_prompt(config)
    user = build_user_prompt(
        config,
        title=title,
        abstract=abstract,
        sources_xml=sources_xml,
        examples=examples,
        metadata=metadata,
    )

    return system, user


# ============================================================================
# Full-context mode prompts
# ============================================================================


def build_full_context_system_prompt(config: ProjectConfig) -> str:
    """Build system prompt for full-context extraction mode.

    Args:
        config: ProjectConfig object

    Returns:
        System prompt string optimized for full document context
    """
    field_desc = generate_field_descriptions_full_context(config)
    rules = generate_extraction_rules(config)

    return f"""You are an expert meta-analyst extracting coding-sheet data from research papers.

You have access to the FULL TEXT of the paper. Use this to:
- Trace variable definitions from Methods to their effect sizes in Results
- Cross-reference tables with text descriptions
- Identify all relevant statistical values across the entire document

{field_desc}

{rules}

## Key Instructions for Full-Context Extraction

1. **Variable-Effect Size Linking**: Variables may be defined in Methods but their effect sizes reported in Results/Tables. Track these connections.

2. **Table Priority**: Tables (marked with <!-- table: tN -->) often contain key numerical data. Reference them as "Table t1", "Table t2", etc.

3. **Multiple N Values**: Papers may report different sample sizes (total N, analysis N, subgroup N). Extract the N used for the specific estimate.

4. **Cross-Section Evidence**: When citing evidence, reference the location (e.g., "Table t1", "Methods section", "Results paragraph 3").

## Output Format

Return ONLY a valid JSON array. No markdown code blocks, no explanations.
Each array item is one record with the fields defined above.
"""


def generate_field_descriptions_full_context(config: ProjectConfig) -> str:
    """Generate field descriptions for full-context mode.

    Similar to generate_field_descriptions but uses evidence_locations instead of evidence_chunk_ids.
    """
    lines = [
        "# Field Extraction Guide",
        "",
        f"Project: {config.name}",
        f"Effect Type: {config.effect_type}",
        "",
        "Return a JSON array. Each item represents ONE effect-size record.",
        "If data not found: use null for numbers, 'NR' for required strings.",
        "",
        "## Fields",
        "",
    ]

    for fc in config.fields:
        type_str = fc.type
        if not fc.required:
            type_str += " | null"

        line = f"- **{fc.name}** ({type_str})"

        if fc.range:
            min_val, max_val = fc.range
            if min_val is not None and max_val is not None:
                line += f" [range: {min_val} to {max_val}]"
            elif min_val is not None:
                line += f" [min: {min_val}]"
            elif max_val is not None:
                line += f" [max: {max_val}]"

        if fc.required:
            line += " **(required)**"

        lines.append(line)

        if fc.prompt:
            prompt_lines = fc.prompt.strip().split("\n")
            for pl in prompt_lines:
                lines.append(f"  {pl.strip()}")

        if fc.examples:
            examples_str = ", ".join(f'"{e}"' for e in fc.examples[:3])
            lines.append(f"  Examples: {examples_str}")

        lines.append("")

    # Evidence fields for full-context mode
    lines.extend(
        [
            "## Evidence Tracking (Full-Context Mode)",
            "",
            "- **evidence_locations** (list[str] | null)",
            "  Locations in the document where evidence was found.",
            "  Use descriptive references like:",
            '  - "Table t1" (for marked tables)',
            '  - "Methods section"',
            '  - "Results section, main findings paragraph"',
            "  Include 1-3 most relevant locations.",
            "",
            "- **evidence_quotes** (list[str] | null)",
            "  Brief quotes (10-20 words) supporting key extracted values.",
            "  Optional but helpful for verification.",
            "",
        ]
    )

    return "\n".join(lines)


def build_full_context_user_prompt(
    config: ProjectConfig,
    *,
    title: str,
    abstract: str,
    full_text: str,
    tables_summary: str = "",
    was_truncated: bool = False,
    examples: Optional[List[Dict]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Build user prompt for full-context extraction mode.

    Args:
        config: ProjectConfig object
        title: Paper title
        abstract: Paper abstract (may be empty if in full_text)
        full_text: Complete paper text with table markers
        tables_summary: Summary of tables in document
        was_truncated: Whether the document was truncated
        examples: Optional example records
        metadata: Optional paper metadata (doi, year, etc.)

    Returns:
        User prompt string
    """
    examples_json = generate_examples(config, examples)

    truncation_note = ""
    if was_truncated:
        truncation_note = """
**Note:** This document was truncated due to length. Focus on the content provided, 
which includes the most important sections (Abstract, Methods, Results, Tables).
"""

    # Build metadata section if available
    metadata_section = ""
    if metadata:
        meta_lines = []
        if metadata.get("doi"):
            meta_lines.append(f"**DOI:** {metadata['doi']}")
        if metadata.get("year"):
            meta_lines.append(f"**Year:** {metadata['year']}")
        if meta_lines:
            metadata_section = "\n".join(meta_lines) + "\n\n"

    return f"""# Paper

**Title:** {title}

{metadata_section}**Abstract:** {abstract[:2000] if abstract else "(see full text below)"}
{truncation_note}
## Full Text

{full_text}

{tables_summary}

## Example Output Format

{examples_json}

---

Now extract ALL records from this paper. 
- Create one record per unique (predictor × outcome × timepoint) combination
- Reference tables as "Table t1", "Table t2", etc.
- Use evidence_locations to cite where you found each value

Return JSON array only."""
