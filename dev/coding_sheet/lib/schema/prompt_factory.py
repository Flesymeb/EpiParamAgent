"""Dynamic prompt generation from configuration.

Generates FIELD_DESCRIPTIONS and prompts from ProjectConfig.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from .config_loader import ProjectConfig


def generate_field_descriptions(config: ProjectConfig) -> str:
    lines = [
        "# Field Extraction Guide",
        "",
        f"Project: {config.name}",
        f"Effect Type: {config.effect_type}",
        "",
        "Return a JSON array. Each item represents ONE record.",
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

    lines.extend(
        [
            "## Evidence Tracking",
            "",
            "- **evidence_locations** (list[str] | null)",
            "  1-3 evidence locations (e.g., 'Table t1', 'Results paragraph 2').",
            "",
        ]
    )

    return "\n".join(lines)


def generate_extraction_rules(config: ProjectConfig) -> str:
    if config.extraction_instructions:
        return config.extraction_instructions.strip()

    return """## Default Extraction Rules

1. Create ONE record per unique study row / effect / parameter.
2. Use exact values from the paper, do not calculate or infer unless explicitly instructed.
3. Note uncertainties in notes/evidence fields.
"""


def generate_examples(
    config: ProjectConfig, examples: Optional[List[Dict]] = None
) -> str:
    if examples:
        return json.dumps(examples, ensure_ascii=False, indent=2)
    if config.prompt.examples:
        return json.dumps(config.prompt.examples, ensure_ascii=False, indent=2)

    example = {}
    for fc in config.fields:
        if fc.examples:
            example[fc.name] = fc.examples[0]
        elif fc.type == "str":
            example[fc.name] = "Example value" if fc.required else None
        elif fc.type == "int":
            example[fc.name] = 1
        elif fc.type == "float":
            if fc.range and fc.range[0] is not None and fc.range[1] is not None:
                example[fc.name] = round((fc.range[0] + fc.range[1]) / 2, 2)
            else:
                example[fc.name] = 0.5
        else:
            example[fc.name] = None

    example["evidence_locations"] = ["Table 1"]

    return json.dumps([example], ensure_ascii=False, indent=2)


def build_system_prompt(config: ProjectConfig) -> str:
    field_desc = generate_field_descriptions(config)
    rules = generate_extraction_rules(config)

    system_header = (
        config.prompt.system.strip()
        if config.prompt.system
        else "You are an expert meta-analyst extracting coding-sheet data from research papers."
    )
    output_rules = (
        config.prompt.output_rules.strip()
        if config.prompt.output_rules
        else "Return ONLY a valid JSON array. No markdown, no explanations."
    )

    return f"""{system_header}

{field_desc}

{rules}

## Output Format

{output_rules}
"""


def build_user_prompt(
    config: ProjectConfig,
    *,
    title: str,
    abstract: str,
    sources_xml: str,
    examples: Optional[List[Dict]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    context_section: Optional[str] = None,
) -> str:
    examples_json = generate_examples(config, examples)

    metadata_section = ""
    if metadata:
        meta_lines = []
        if metadata.get("doi"):
            meta_lines.append(f"**DOI:** {metadata['doi']}")
        if metadata.get("year"):
            meta_lines.append(f"**Year:** {metadata['year']}")
        if meta_lines:
            metadata_section = "\n".join(meta_lines) + "\n\n"

    params_section = ""
    if config.parameters:
        params_lines = ["## Parameters"]
        for k, v in config.parameters.items():
            params_lines.append(f"- {k}: {v}")
        params_section = "\n".join(params_lines) + "\n\n"

    notes_section = ""
    if config.notes:
        notes_section = "## Notes\n" + config.notes.strip() + "\n\n"

    user_preamble = config.prompt.user_preamble.strip() if config.prompt.user_preamble else ""
    if user_preamble:
        user_preamble = f"{user_preamble}\n\n"

    context_block = ""
    if context_section:
        context_block = context_section.strip() + "\n\n"

    return f"""{user_preamble}# Paper

**Title:** {title}

{metadata_section}{params_section}{notes_section}{context_block}**Abstract:** {abstract[:2000]}

## Evidence Sources

{sources_xml}

## Example Output Format

{examples_json}

---

Now extract all records from this paper. Return JSON array only."""


def build_full_context_system_prompt(config: ProjectConfig) -> str:
    field_desc = generate_field_descriptions(config)
    rules = generate_extraction_rules(config)

    system_header = (
        config.prompt.system.strip()
        if config.prompt.system
        else "You are an expert meta-analyst extracting coding-sheet data from research papers."
    )
    output_rules = (
        config.prompt.output_rules.strip()
        if config.prompt.output_rules
        else "Return ONLY a valid JSON array. No markdown, no explanations."
    )

    return f"""{system_header}

You have access to the FULL TEXT of the paper.

{field_desc}

{rules}

## Output Format

{output_rules}
"""


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
    context_section: Optional[str] = None,
) -> str:
    examples_json = generate_examples(config, examples)

    truncation_note = ""
    if was_truncated:
        truncation_note = (
            "\n**Note:** This document was truncated due to length. "
            "Focus on the content provided.\n"
        )

    metadata_section = ""
    if metadata:
        meta_lines = []
        if metadata.get("doi"):
            meta_lines.append(f"**DOI:** {metadata['doi']}")
        if metadata.get("year"):
            meta_lines.append(f"**Year:** {metadata['year']}")
        if meta_lines:
            metadata_section = "\n".join(meta_lines) + "\n\n"

    params_section = ""
    if config.parameters:
        params_lines = ["## Parameters"]
        for k, v in config.parameters.items():
            params_lines.append(f"- {k}: {v}")
        params_section = "\n".join(params_lines) + "\n\n"

    notes_section = ""
    if config.notes:
        notes_section = "## Notes\n" + config.notes.strip() + "\n\n"

    user_preamble = config.prompt.user_preamble.strip() if config.prompt.user_preamble else ""
    if user_preamble:
        user_preamble = f"{user_preamble}\n\n"

    context_block = ""
    if context_section:
        context_block = context_section.strip() + "\n\n"

    tables_block = ""
    if tables_summary:
        tables_block = f"\n\n## Tables Summary\n{tables_summary}\n"

    return f"""{user_preamble}# Paper

**Title:** {title}

{metadata_section}{params_section}{notes_section}{context_block}**Abstract:** {abstract[:2000] if abstract else "(see full text below)"}
{truncation_note}
## Full Text

{full_text}
{tables_block}

## Example Output Format

{examples_json}

---

Now extract all records from this paper. Return JSON array only."""


def build_prompts_from_model(
    model: Type[BaseModel],
    *,
    title: str,
    abstract: str,
    sources_xml: str,
    examples: Optional[List[Dict]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    context_section: Optional[str] = None,
) -> tuple[str, str]:
    config: Optional[ProjectConfig] = getattr(model, "_project_config", None)
    if not config:
        raise ValueError("Model has no _project_config.")

    system = build_system_prompt(config)
    user = build_user_prompt(
        config,
        title=title,
        abstract=abstract,
        sources_xml=sources_xml,
        examples=examples,
        metadata=metadata,
        context_section=context_section,
    )

    return system, user
