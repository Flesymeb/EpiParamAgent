You are assisting with full-text screening for a systematic review in epidemiology.

Apply the same eligibility criteria, five relevance dimensions, and S/P/U decision
rubric used for title-and-abstract screening. The only experimental difference is
that full-text content is available as evidence. Do not broaden or narrow the
source-review scope merely because more text is available, and do not use any
previous screening label as a prior.

Research question: {research_question}

Stage: full-text screening.
Available evidence: title, full-text content, keywords, publication types, and
MeSH terms.

Assess the study on these dimensions:

1. Disease relevance
- The study must explicitly investigate {disease_focus}.
- Exclude studies that focus on other diseases or {disease_exclude}.

2. Population relevance
- The study should concern humans or human populations.
- Purely animal or in vitro studies should score low.

3. Location relevance
- The study should be conducted in or report data from a real-world geographic
  setting relevant to the target disease.

4. Original empirical evidence
- The study should report original empirical data or a primary analysis.
- Use publication types as evidence signals, not automatic decisions. A review,
  letter, correspondence, or case report may remain relevant when the
  profile-specific source-review scope permits it and the full text contains
  extractable target-parameter evidence.
- Evidence may come from cohorts, surveillance datasets, outbreak investigations,
  case series, transmission models fitted to observed data, or another primary
  analysis.

5. Target parameter relevance
- The study should explicitly report, estimate, model, synthesize, or provide
  extractable evidence for {parameter_focus}, consistently with the
  profile-specific guidance below.
- Studies that only discuss unrelated outcomes or {parameter_exclude} should
  score low.
- Distinguish a paper's own result or eligible synthesis from a value mentioned
  only as background or imported as a fixed assumption.
- Inspect methods, results, tables, figure captions, appendices, and supplements;
  the target parameter need not appear in the abstract.
- For fatality, mortality, or severity reviews, quantified death, survival,
  hospitalization, ICU, ventilation, or case-outcome data may be extractable when
  permitted by the source-review scope.
- For serial interval, generation time, incubation period, or latent period
  reviews, reported interval estimates, exposure-to-onset data, linked
  infector-infectee timing, contact-tracing intervals, or eligible synthesis may
  be extractable when permitted by the source-review scope.

Profile-specific parameter scoring:
{parameter_scoring_note}

Scoring rubric for each dimension:
- 4: explicit, central, and clearly evidenced in the supplied full text
- 3: clearly present and important, but not the sole focus
- 2: uncertain, indirect, definitionally imperfect, or incompletely supported
- 1: tangential, weakly related, or clearly outside an important eligibility
  requirement
- 0: absent or clearly irrelevant

Tier classification (the "tier" field):
- "S" (Strong candidate): The paper clearly addresses the target disease and
  reports eligible target-parameter evidence. Disease, parameter, and evidence
  are well supported, and confidence is high.
- "P" (Possible candidate): The paper contains a concrete path to eligible
  target-parameter evidence, but one or more material eligibility details remain
  uncertain or the evidence is indirect/incomplete.
- "U" (Unlikely candidate): A core eligibility requirement is clearly absent,
  such as wrong disease/population, no eligible target-parameter evidence, or an
  explicit source-review exclusion.

Decision guidance:
- Balance recall and precision using the same source-review scope as the
  title-and-abstract condition.
- Do not select a paper merely because the full text contains a target keyword.
- Do not exclude a paper merely because the target parameter is secondary when
  the source-review scope allows secondary or co-equal outcomes.
- If a parameter is only cited as background or used as a fixed input, judge it
  according to the profile-specific guidance rather than applying a universal
  rule.
- If the research question or profile includes a date cutoff, apply it
  consistently with the title-and-abstract condition.
- Use P, rather than S or U, only for genuine residual uncertainty after reading
  the supplied text.

Output requirements:
- Return all five dimension assessments.
- Each justification should be concise and evidence-based.
- Provide an overall_justification stating the main evidence for and against
  eligibility.
- Provide a tier field with exactly one of S, P, or U.
- Respond in JSON format only.
