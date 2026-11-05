"""Evidence indexing for the incubation-period task."""

SYSTEM = "Use only the supplied source to build a structured evidence index. Never guess missing information."
USER = """
Locate explicitly reported incubation-period estimates and their supporting source
passages, tables and figure captions. Keep the authors' population, study period,
clade, measure, uncertainty type, unit and onset definition attached to each item.
Do not substitute a serial-interval or generation-time estimate.
Return a study_meta object with region_raw, period_raw, population_raw,
sample_size_raw and method_raw, and field_evidence identifying source locations
for parameter_type, point_estimate and uncertainty. Use null for missing data.
"""
OUTPUT = "Return a JSON array with exactly one index object, without Markdown."
