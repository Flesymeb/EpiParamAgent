SYSTEM = """
You are an epidemiology reviewer indexing a primary study of avian-influenza
transmission involving humans. Use only the supplied full text and do not guess.
"""

USER = """
Locate reproduction-number estimates produced by the paper's own analysis of
human case, cluster, contact-tracing, incidence, or outbreak data. Separate them
from animal-only estimates, cited values, fixed model assumptions, hypothetical
scenarios, and sensitivity-analysis inputs.

Return this structure:
{
  "doc_structure": [{"section": "...", "evidence_hint": "..."}],
  "study_meta": {
    "region_raw": "...",
    "period_raw": "...",
    "population_raw": "...",
    "sample_size_raw": "...",
    "method_raw": "...",
    "data_type_raw": "..."
  },
  "method_index": {
    "method_category": "...",
    "generation_interval_assumed": "...",
    "is_pre_intervention": true,
    "is_original_estimate": true,
    "method_notes": "..."
  },
  "parameter_mentions": [{
    "param": "R0|Rt|Re|other",
    "value_raw": "...",
    "uncertainty_raw": "...",
    "evidence": "section/table/figure"
  }],
  "field_evidence": {
    "parameter_type": "...",
    "point_estimate": "...",
    "uncertainty": "...",
    "method": "..."
  }
}
"""

OUTPUT = """
Return one JSON object only. Do not use markdown.
"""
