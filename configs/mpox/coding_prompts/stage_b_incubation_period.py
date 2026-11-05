"""Source-grounded extraction for the incubation-period task."""

SYSTEM = "Extract coding-sheet records only from evidence in the supplied source. Do not guess."
USER = """
Use the incubation-period codebook and full source. Stage A is navigation guidance
only. Extract explicitly reported incubation-period records, preserving population,
period, clade and onset definition in the appropriate fields or notes. Keep mean,
median and other reported statistics distinct. Do not extract a different measure
as a substitute and do not calculate new pooled values. Preserve uncertainty type,
level and limits. Use null for missing numbers and NR for required missing strings.
Record the actual supporting source locations. A source without PMID stays NR.
"""
OUTPUT = "Return a JSON array only, without Markdown or explanations."
