You are assisting with conservative full-text re-review of records that were excluded at title/abstract screening for an epidemiology systematic review.

The paper was labeled UNLIKELY at stage 1. Your task is to decide whether the exclusion was clearly wrong. Do not use ground truth labels. Use only the full text/retrieved evidence and bibliographic metadata.

Research question: {research_question}

Target disease: {disease_focus}
Target parameter: {parameter_focus}
Parameter exclusions: {parameter_exclude}

Source-review and parameter-specific scope:
{parameter_scoring_note}

Decision tiers:
- S: rescue as a strong candidate only if the full text clearly matches the source review scope and directly reports an extractable target-parameter estimate from original eligible human observational data.
- P: rescue as plausible only if the full text likely matches the source review scope but one non-critical detail is uncertain.
- U: keep excluded if the paper does not clearly match the source review scope.

Conservative U-pass rules:
- Default to U. A stage-1 excluded paper should be promoted only with strong full-text evidence.
- Do not promote review articles, narrative summaries, meta-analyses, editorials, comments, letters, protocols, diagnostics-only, treatment-only, surgery-only, preparedness, policy, modelling-only, or broad clinical-characterization papers unless the source review explicitly includes that article type.
- Do not promote a paper merely because it mentions an incubation period, serial interval, generation time, or an endpoint that could be calculated. The paper must directly report an extractable target-parameter estimate that is central enough for the source review.
- For P12-like serial interval/incubation period reviews, incubation period is in scope only when it is a primary eligible outcome from original observational cases or transmission/contact data. A longest observed incubation time, a generic background value, a literature-summary value, or a secondary pooled estimate from another review is not enough for rescue.
- If evidence is real but scope is uncertain, choose P only when it is likely the source review would screen it at full text. Otherwise choose U.
- Treat date metadata cautiously. Date alone should not rescue a paper, and date alone should not exclude a paper when the full-text/source-review scope otherwise clearly matches.

Assess five dimensions:
1. Disease relevance.
2. Human population relevance.
3. Real-world location/context relevance.
4. Original review-eligible evidence.
5. Target parameter and source-review scope relevance.

Return all five dimension assessments and an explicit tier field with exactly one of S, P, or U. In the overall justification, state the main reason: `eligible_original_parameter`, `review_or_secondary`, `clinical_only`, `parameter_not_central`, `cited_or_input_only`, `wrong_scope`, `insufficient_full_text`, or `uncertain`.
