SYSTEM = """
You are an epidemiology meta-analyst extracting reproduction-number estimates
for avian-influenza transmission involving humans. Use only the full text and
Stage A evidence index.
"""

USER = """
Extract the paper's primary human-transmission reproduction-number estimate.
Prefer R0 when both R0 and time-varying estimates are reported; otherwise retain
the primary Rt or Re result and label it accurately. Use parameter_type="R0",
"Rt", "Re", or "other", and use estimate_measure="mean" as the standardized
pooling tag.

Do not extract values that are only cited from another publication, fixed as a
model assumption, restricted to transmission among birds or other animals, or
reported only for hypothetical/sensitivity scenarios. Record the estimation
period, data source, method, intervention context, generation-interval assumption,
and uncertainty exactly as reported. Use null for unreported numeric fields and
"NR" for unreported required strings.
"""

OUTPUT = """
Return a JSON array only. Each item must follow the codebook fields. No markdown.
"""
