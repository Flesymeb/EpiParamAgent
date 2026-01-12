Provider: ERIC (https://api.ies.ed.gov/eric/)

Write boolean queries for ERIC that mirror PubMed-style structure, while staying ERIC-compatible.

Rules:
- Do NOT use phrase quotes on free-text fields. `"foo bar"` will raise a PhraseQuery error. Use `foo AND bar` instead.
- Use longer OR groups (8-15 terms) to preserve recall. Parentheses recommended.
- Prefer 3-clause structure with AND: (constructs) AND (outcomes) AND (design/method).
- You may add a 4th clause for population or measurement when useful.
- Allowed field scoping: `title:term` (no quotes), `subject:term`, `author:Lastname`.
- You may use wildcards like `math*`, `predict*`, `traject*`, `numerac*`.
- Avoid overly short queries; aim for PubMed-like coverage.

Return JSON: {"queries": ["q1", "q2", ...]} with 6-12 queries. No extra text.
