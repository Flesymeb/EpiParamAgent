SYSTEM = """
You are an epidemiology research assistant creating a structured index from full text.
Use only evidence from the provided text. Do not guess or infer.
"""

USER = """
Task: Build a study-level index for epidemiology meta-analysis (Stage A).
This is a high-recall indexing task, not final extraction.
Capture document structure, tables (with captions), and evidence hints for key parameters.

You MUST scan the full text for any "Table X" or "Figure X" references and list them.
If a table/section mentions dispersion parameter (k), CI/CrI/Range, 20/80 rule, or R value,
capture those in field_evidence with specific evidence hints.

Return ONE JSON object with the following structure (this is the index):
{
  "doc_structure": [
    {"section": "Abstract", "subsections": [], "evidence_hint": "Abstract"},
    {"section": "Methods", "subsections": ["Study design", "Participants"], "evidence_hint": "Methods heading"}
  ],
  "tables": [
    {"table_id": "Table 1", "title_or_caption": "...", "table_type": "study_desc|parameter|other",
     "contains_k": true|false, "contains_ci": true|false, "contains_region": true|false,
     "evidence_hint": "..."}
  ],
  "study_meta": {
    "method_raw": "...",
    "period_raw": "...",
    "region_raw": "...",
    "evidence": "Methods / Table 1"
  },
  "parameter_mentions": [
    {"param": "k", "value_raw": "...", "ci_raw": "...", "ci_type": "CI|CrI|Range", "ci_level": "90%|95%|Other",
     "evidence": "Table 1 / Results"},
    {"param": "20/80_rule", "value_raw": "P=0.2, Q=0.8", "evidence": "Methods / Results"},
    {"param": "R", "value_raw": "...", "evidence": "Methods / Results"}
  ],
  "field_evidence": {
    "method": "Methods section",
    "period": "Table 1 / Study period",
    "region": "Table 1 / Setting",
    "k_value": "Table 1 / Results",
    "k_ci": "Table 1 / Results",
    "k_ci_type": "Methods / Results",
    "k_ci_level": "Methods / Results",
    "rule_20_80": "Methods / Results",
    "r_value": "Methods / Results"
  }
}

Use null for missing fields. Use empty arrays if none.
"""

OUTPUT = """
Return a JSON array with EXACTLY ONE object.
No markdown, no explanations.
"""
