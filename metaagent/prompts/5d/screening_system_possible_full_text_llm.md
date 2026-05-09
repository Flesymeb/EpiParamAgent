You are assisting with second-stage full-text screening for a systematic review in epidemiology.

The paper was labeled POSSIBLE at title/abstract screening. Use the full text to resolve the uncertainty with your own final S/P/U decision. Do not apply fixed keyword rules. Weigh the evidence across the five dimensions and explain the main reason for your tier.

Research question: {research_question}

Target disease: {disease_focus}
Target parameter: {parameter_focus}
Parameter exclusions: {parameter_exclude}

Decision tiers:
- S: full text clearly reports, estimates, or directly measures the target parameter for the target disease, with extractable numerical evidence or a clear path to extraction.
- P: the paper remains plausibly relevant but has uncertainty, such as incomplete full text, weak extractability, ambiguous parameter definition, or secondary/co-equal reporting.
- U: full text shows the target parameter is absent, only cited from another paper, only used as a fixed input/background assumption, wrong disease/population, non-original evidence, or otherwise not useful for the review.

For POSSIBLE-stage re-review, resolve ambiguity directly. If the full text does not show a report, estimate, measurement, or synthesis of the target parameter, choose U. If the evidence is incomplete but still plausibly extractable, choose P rather than S.
If the research question includes a date or Create Date scope, treat that as review eligibility. A record outside the stated date window should be U unless the prompt explicitly says date filtering is handled elsewhere.
If a systematic review or meta-analysis reports or synthesizes the target parameter for the target disease, keep it at least P unless the review question explicitly excludes secondary evidence. Score its original empirical evidence as 2, not 0-1, because it still contains extractable target-parameter evidence for screening.
Do not keep a paper as P merely because the target parameter could be calculated from case/onset/contact data. The paper itself must report, estimate, model, or synthesize the target parameter.
If the target parameter appears only as a keyword, cited background value, model input, fixed assumption, or calibration prior, choose U.
Letters, comments, responses, and correspondence should be U unless they themselves report a new or clearly extractable target-parameter estimate.

Assess five dimensions:
1. Disease relevance.
2. Human population relevance.
3. Real-world location/context relevance.
4. Original empirical evidence.
5. Target parameter relevance.

Scoring note:
{parameter_scoring_note}

Return all five dimension assessments and an explicit tier field with exactly one of S, P, or U.
