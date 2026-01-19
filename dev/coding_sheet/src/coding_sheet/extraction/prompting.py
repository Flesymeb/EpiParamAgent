from __future__ import annotations

import json


FIELD_DESCRIPTIONS = """
# Field Extraction Guide

Return a JSON array. Each item represents ONE extracted record from the paper.
Never guess. If data not available, use null for numbers and "NR" (Not Reported) for required strings.

IMPORTANT:
- Do NOT return an empty array `[]`.
- If you cannot find complete data, return records with available fields + null/"NR" for missing fields.
- Extract ALL relevant data points from the paper (multiple records if the study reports multiple findings).

General Field Rules:
- study: "Author et al., YEAR" (string) - Extract from paper header/citation
- Use null for missing numeric values
- Use "NR" for missing required string fields
- Use evidence_chunk_ids to track sources (reference <source id='N'> blocks)

Evidence:
- evidence_chunk_ids: list[int] (1-5 ids). Each id must refer to a <source id="..."> block provided.
- evidence_quotes: Optional list[str] (1-3 short quotes). Can be null or [] to save tokens.

Extraction Rules:
- Create ONE record per distinct finding/estimate reported in the paper
- If the study reports multiple variants/timepoints/outcomes, create separate records for each
- Prioritize tables (marked with type="table") as they often contain key numerical data
- Do NOT guess: if evidence not found, use null (numbers) or "NR" (strings)
- Cross-reference Methods and Results sections to extract complete information
""".strip()


# Legacy examples - kept for backward compatibility with old CodingSheetRecord schema
# When using config-based extraction, examples are generated from config.examples
EXTRACTION_EXAMPLES = []


SYSTEM_PROMPT = """You are an expert epidemiologist and meta-analyst extracting structured data from infectious disease research papers.

Your task is to extract reproduction number (R0/Rt/Re) estimates and related epidemiological parameters from papers studying SARS-CoV-2 variants.

{field_descriptions}

Output MUST be valid JSON (array)."""


USER_PROMPT = """# Paper

Title: {title}

Abstract: {abstract}

Evidence sources (each chunk has an id you can cite):
{sources_xml}

# Examples (format reference only)
{examples}

Return JSON array now."""


def examples_as_json() -> str:
    return json.dumps(EXTRACTION_EXAMPLES, ensure_ascii=False, indent=2)
