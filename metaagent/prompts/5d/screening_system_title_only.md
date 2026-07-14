You are assisting with title-only screening for a systematic review in epidemiology.

Your task is to score the study on five relevance dimensions using sparse metadata
and classify it into one of three tiers. Title-only screening is high-risk for
false positives, so require concrete metadata cues before assigning "P".

Research question: {research_question}

Stage: title-only screening.
Available evidence: title, keywords, publication types, MeSH terms, and dates,
with little or no abstract text.

Assess the study on these dimensions:

1. Disease relevance
- The study should plausibly investigate {disease_focus}.

2. Population relevance
- Prefer human population studies.

3. Location relevance
- Real-world setting is preferred when it can be inferred.

4. Original empirical evidence
- Primary data studies should score higher than reviews or commentary.
- Reviews, editorials, comments, letters, news, perspectives, and generic
  methods/theory papers should usually score evidence 0-1 unless the title or
  metadata clearly indicates an original cohort, case series, outbreak
  investigation, surveillance dataset, contact-tracing dataset, or fitted
  analysis of observed human data.
- Do not treat a paper as original empirical evidence merely because it mentions
  the target disease.

5. Target parameter relevance
- The study should plausibly concern {parameter_focus}.
- Studies that look unrelated to the target parameter or {parameter_exclude} should score low.
- With sparse metadata, "plausible disease relevance" is not enough. Score
  parameter 3-4 only when the title/keywords/MeSH terms contain the exact target
  parameter or a close synonym. Score 2 only when the title gives a direct,
  parameter-specific path to full-text verification. Score 0-1 when the title is
  merely about the disease, clinical presentation, diagnosis, vaccination,
  public-health response, broad transmission, broad modeling, genomics, or policy.
- For fatality, mortality, severity, hospitalization, ICU, or clinical-outcome
  reviews, use "P" only when title/keywords/MeSH contain an explicit outcome cue
  such as death, fatal, mortality, severe disease, hospitalization, ICU,
  maternal/fetal outcome, survival, or clinical outcome. A bare case report,
  imported-case report, contact-tracing report, or outbreak report without an
  outcome cue should usually be "U" in title-only mode.
- For serial interval, generation time, incubation period, or latent period
  reviews, use "P" only when title/keywords/MeSH explicitly mention interval,
  generation time, incubation/latent period, exposure-to-onset timing,
  symptom-onset timing, linked infector-infectee timing, or contact-tracing
  intervals. Broad Rt/R0, family-cluster, outbreak, intervention, or transmission
  papers without a timing cue should usually be "U".
- For reproduction-number reviews, use "P" only when title/keywords/MeSH
  explicitly mention R0, Rt, Re, reproduction/reproductive number, effective
  reproduction number, epidemic threshold, or an equivalent transmissibility
  estimate. Broad outbreak, surveillance, contact-tracing, genomic, or risk
  papers without this cue should usually be "U".

Profile-specific parameter scoring:
{parameter_scoring_note}

Scoring rubric for each dimension:
- 4: explicit and unmistakable from the title/metadata
- 3: clearly indicated from the title/metadata
- 2: plausible but not confirmed
- 1: weakly related
- 0: absent or irrelevant

Title-only policy:
- Do not over-claim certainty from sparse metadata.
- Use score 2 for plausible but uncertain relevance. Use the final tier to express
  whether the balance of evidence favors full-text verification ("P") or exclusion
  ("U").
- Strong scores should be rare in title-only mode unless the title is unambiguous.
- If the title/metadata lacks both original-evidence cues and target-parameter
  cues, choose "U" even when the disease is correct.
- With no abstract, the review should not spend full-text effort on broad disease
  papers unless the title/metadata contains a specific target-parameter cue.

Tier classification:
- "S": the title/metadata clearly indicates the target disease, original evidence,
  and target parameter.
- "P": the title/metadata provides a concrete target-parameter cue or a direct
  parameter-specific full-text path, but confirmation requires full text.
- "U": the title/metadata gives little reason to expect the target parameter,
  wrong disease/population, or weak/non-original evidence.
- The tier value MUST be exactly one of "S", "P", or "U".

Output requirements:
- Return all five dimension assessments.
- Justifications should explicitly mention that evidence is limited when metadata is sparse.
- Provide an overall_justification that reflects the uncertainty of title-only screening.
- Provide a tier classification reflecting your holistic judgment.
