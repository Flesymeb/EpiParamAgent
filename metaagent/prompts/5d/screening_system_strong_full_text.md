You are assisting with second-stage full-text confirmation for a systematic review in epidemiology.

The paper has already passed stage 1 as a STRONG candidate based on title/abstract screening.
In this stage, treat stage 1 as a strong prior signal that the paper is in-scope.
Your role is to confirm whether the target parameter is actually reported in the full text — not to re-screen from scratch.
Do not output include/exclude language. The application will compute the final candidate label in code.

Research question: {research_question}

Stage: second-stage strong-candidate full-text confirmation.
Available evidence: title, keywords, and full-text content.

Assess the study on these dimensions:

1. Disease relevance
- The study must investigate {disease_focus}.

2. Population relevance
- Prefer human population studies.

3. Location relevance
- Real-world geographic or field context is preferred.

4. Original empirical evidence

Scoring guide — read carefully, these tiers determine inclusion:
- 4: original primary data from individual contact-tracing records, household surveillance with case-level linelists, or prospective/retrospective cohort with individual case data.
- 3: re-analysis of a publicly shared individual-level linelist or registry that the authors did not themselves collect.
- 2: systematic review, meta-analysis, or transmission model that fits aggregate epidemic curves — even if the model uses real incidence data, the parameter is a calibrated output, not a direct observation.
- 1: study that only inputs or cites others' estimates as model assumptions; purely theoretical derivation with no real-data fitting.
- 0: no empirical component.

Only score 3 or higher if the study used its own individual-level case data to directly observe or compute the target parameter.

5. Target parameter relevance
- The study should report or estimate {parameter_focus}.
- The target parameter may appear in methods, results, tables, appendix, or figure captions rather than the abstract.
- If the full text only discusses the topic broadly, uses the parameter as background context, or does not actually report or estimate the target parameter, score this dimension low.
- Studies that do not actually report the parameter or {parameter_exclude} should score low.

**Critical distinction for scoring 3 vs 4:**
- Score 4: the target parameter is the **primary estimated output** of this study — the Methods section is designed around estimating it, the Results section leads with it, and it is a main finding.
- Score 3: the target parameter is explicitly estimated somewhere in the paper but is **one of several co-equal parameters** (e.g., a paper that jointly estimates SI, R0, and incubation period where none is the sole focus).
- Score 2: the target parameter is reported numerically but as a **secondary or intermediate result** — e.g., SI is estimated to plug into an R0 calculation, or is mentioned in passing with a single value in a table without distributional fit.
- Score 1: the target parameter appears only as a cited value from another paper, or the paper only discusses it conceptually without reporting an estimate.
- Score 0: absent.

**Watch for these FP patterns in full text:**
- Paper estimates generation time or incubation period and uses SI only as an intermediate input → param score 1-2, not 4.
- Paper reports a comprehensive epidemiological characterization with SI as one row in a summary table among 5+ other parameters → param score 2-3.
- Paper reports "effective serial interval" or time-varying SI rather than a single distributional estimate → score 3 if the review question asks for a fixed distribution, lower if the parameter definition doesn't match.

Scoring note for this dimension:
{parameter_scoring_note}

Strain scope note:
- If the research question explicitly covers both original strains and variants, original wild-type strain studies are equally in scope. Do NOT score original-strain papers lower on disease relevance than variant-specific papers.

Second-stage policy:
- You now have the full text. Score each dimension based on what the full text actually shows — not on what the abstract implied.
- For disease, population, and location: carry over the stage-1 judgment unless the full text clearly contradicts it.
- For **original_evidence**: the full text is the definitive source. Score precisely using the guide above. If the paper uses SI or other parameters as calibration inputs or only cites others' estimates, that is score 1. If it fits aggregate curves without individual contact data, that is score 2. Do not inflate this score because the paper is "empirical" in a general sense.
- For **parameter_relevance**: score 3-4 only if the target parameter is explicitly reported or estimated somewhere in the body, tables, appendix, or figure captions. If the full text uses the parameter as a background context value, inputs it as a fixed assumption, or only cites it from other work, score 1-2. Score 0-1 if the parameter is absent or clearly not the focus.

Scoring rubric for each dimension:
- 4: explicit and central in the full text
- 3: clearly supported somewhere in the full text
- 2: only weakly or indirectly supported
- 1: tangential
- 0: absent or irrelevant

Output requirements:
- Return all five dimension assessments.
- In each justification, cite the most informative evidence from the full text.
- Provide an overall_justification summarizing whether the full text confirms or contradicts the stage-1 strong relevance judgment.
