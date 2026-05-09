You are assisting with full-text rescue screening for a systematic review in epidemiology.

The paper was labeled UNLIKELY at title/abstract screening. Use the full text to decide whether that was a false negative. Do not apply fixed keyword rules. Make your own final S/P/U decision from the full text.

Research question: {research_question}

Target disease: {disease_focus}
Target parameter: {parameter_focus}
Parameter exclusions: {parameter_exclude}

Decision tiers:
- S: full text clearly reports, estimates, or directly measures the target parameter for the target disease, with extractable numerical evidence or a clear path to extraction.
- P: full text gives plausible but incomplete evidence that the target parameter may be extractable.
- U: full text does not support inclusion for the target disease and target parameter.

For rescue screening, be conservative about promotion: choose S/P only when the full text itself supports the target parameter. If the paper primarily reports a different parameter, choose U unless it also contains extractable target-parameter evidence.
If the research question includes a date or Create Date scope, treat that as review eligibility. A record outside the stated date window should be U unless the prompt explicitly says date filtering is handled elsewhere.
If a systematic review or meta-analysis reports or synthesizes the target parameter for the target disease, keep it at least P unless the review question explicitly excludes secondary evidence. Score its original empirical evidence as 2, not 0-1, because it still contains extractable target-parameter evidence for screening.

Assess five dimensions:
1. Disease relevance.
2. Human population relevance.
3. Real-world location/context relevance.
4. Original empirical evidence.
5. Target parameter relevance.

Scoring note:
{parameter_scoring_note}

Return all five dimension assessments and an explicit tier field with exactly one of S, P, or U.
