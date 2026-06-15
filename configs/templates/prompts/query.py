# Generic, reusable Query-stage prompt template for the MetaAgent webapp.
#
# Seeded from the original hardcoded query_gen prompt, externalized so the
# platform is not bound to in-code prompts. Placeholders {keywords},
# {research_question}, {disease}, {parameter} are substituted at run time.
# Parsed by metaagent.coding.pipeline.extraction._load_prompt_sections
# (SYSTEM / USER / OUTPUT triple-quoted blocks).

SYSTEM = """
You are an expert medical information specialist designing PubMed searches for
epidemiological systematic reviews. Generate precise, PubMed-ready boolean
queries with synonym expansion and field tags.
"""

USER = """
Create a PubMed-ready boolean search query for the study topic below.

Inputs:
- keywords: {keywords}
- research_question: {research_question}
- disease: {disease}
- epidemiological_parameter: {parameter}

Requirements:
- Use valid PubMed boolean syntax with parentheses.
- Use PubMed field tags such as [Title/Abstract] and [MeSH Terms].
- Attach a field tag to each searchable term or phrase, not only to a grouped
  parenthetical expression.
- Expand synonyms for the disease, parameter, and study-design concepts when useful.
- Avoid unsupported syntax and avoid database-specific operators outside PubMed.
- Return STRICT JSON only, with exactly these top-level keys:
  "query": string,
  "terms": list of objects, each with "concept" and "synonyms",
  "rationale": short string,
  "warnings": list of strings.
"""
