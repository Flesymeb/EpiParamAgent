"""Source-grounded reproduction-number extraction; numerical thresholds do not define labels."""
SYSTEM = "Use only supplied study evidence. Do not guess or compute missing values."
USER = """
Extract all in-scope reported estimates, retaining statistics, methods, strata and
periods separately. Candidate evidence is navigation guidance, not authoritative.
Preserve raw parameter labels, values, units, interval types and levels.
Do not prefer a headline value or discard Rt merely because R0 is also reported.
Do not classify R0/Rt by numerical thresholds. Do not substitute SI/IP/generation
time or treat an assumed model input as an original estimated result.
Null is not zero. Retain explicitly reported zero events and negative serial
intervals with their reported definitions; do not force values into typical ranges.
Record supporting source quotes and locations. Do not compute pooled estimates.
"""
OUTPUT = "Return a JSON array only, without Markdown or explanations."
