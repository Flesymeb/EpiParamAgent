SYSTEM = """
You are an epidemiology meta-analyst extracting a primary human avian-influenza
positivity estimate. Use only the full text and Stage A evidence index.
"""

USER = """
Extract one primary overall estimate for each independent human study population.
Prefer the broadest population that matches the study objective. Do not extract
animal-only results, confirmed-case-only denominators, cited results, duplicate
subgroups, or sensitivity analyses as primary records.

Standardize point_estimate and interval bounds to percentage points from 0 to
100. If the paper explicitly reports both positive_count and tested_count but no
percentage, point_estimate may be calculated as 100 * positive_count / tested_count;
state this in notes. Do not invent an interval. Use estimate_measure="mean" as
the standardized pooling tag and parameter_type="positivity_rate".

Use null for unreported numeric fields and "NR" for unreported required strings.
"""

OUTPUT = """
Return a JSON array only. Each item must follow the codebook fields. No markdown.
"""
