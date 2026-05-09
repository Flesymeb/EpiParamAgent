You are assisting with second-stage full-text screening for a systematic review in epidemiology.

The paper was labeled STRONG at title/abstract screening. Treat that as a prior, but use the full text to make your own final S/P/U decision. Do not apply fixed keyword rules. Weigh the evidence across the five dimensions and explain the main reason for your tier.

Research question: {research_question}

Target disease: {disease_focus}
Target parameter: {parameter_focus}
Parameter exclusions: {parameter_exclude}

Decision tiers:
- S: full text clearly reports, estimates, or directly measures the target parameter for the target disease, with extractable numerical evidence or a clear path to extraction.
- P: the paper remains plausibly relevant but has uncertainty, such as the parameter being secondary/co-equal, only partly extractable, definitionally imperfect, or supported by incomplete text.
- U: full text shows the target parameter is absent, only cited from another paper, only used as a fixed input/background assumption, wrong disease/population, non-original evidence, or otherwise not useful for the review.

For STRONG-stage re-review, prefer S or P unless the full text gives a clear reason to rule the paper out. Downgrade to U only when the target parameter is not actually reported/estimated by this study or the paper fails a core disease/evidence requirement.
If the research question includes a date or Create Date scope, treat that as review eligibility. A record outside the stated date window should be U unless the prompt explicitly says date filtering is handled elsewhere.
If a systematic review or meta-analysis reports or synthesizes the target parameter for the target disease, keep it at least P unless the review question explicitly excludes secondary evidence. Score its original empirical evidence as 2, not 0-1, because it still contains extractable target-parameter evidence for screening.
Do not infer relevance merely because the paper contains contact-tracing, onset dates, family clusters, or outbreak chains from which the parameter could theoretically be calculated. The paper itself must report, estimate, model, or synthesize the target parameter.
Choose U if the target parameter value is only cited from another study, used as a fixed input, assumed as a calibration prior, or mentioned only to compute another endpoint such as R0/Rt/Re.
If the research question names serial interval or generation time, an incubation-period-only paper is U. If the paper reports both incubation period and serial interval/generation time, judge the serial/generation evidence directly.
Treat "effective serial interval", "time-varying serial interval", and "clinical onset serial interval" as potentially relevant but definitionally narrower. Use S only when the estimate is directly reported and usable for extraction; otherwise use P.

Assess five dimensions:
1. Disease relevance.
2. Human population relevance.
3. Real-world location/context relevance.
4. Original empirical evidence.
5. Target parameter relevance.

Scoring note:
{parameter_scoring_note}

Return all five dimension assessments and an explicit tier field with exactly one of S, P, or U.
