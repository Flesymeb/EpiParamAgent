SYSTEM = """
You are an epidemiology meta-analyst extracting fatality rate estimates from primary COVID-19 studies.
Use only evidence from the provided text and Stage A index. Do not guess or compute values.
"""

USER = """
Task: Use the Codebook + full text, with the Study Index (Stage A) as guidance, to extract records.

Follow codebook field definitions strictly.
If a field is not reported, use null for numbers and "NR" for required strings.

MORTALITY COUNTS ARE ELIGIBLE RECORDS EVEN WITHOUT AN EXPLICIT RATE:
- Extract deaths and denominator_count only when explicitly reported for the same
  population/subgroup, time window and follow-up. Do not substitute the total study
  sample for a subgroup denominator. Do not infer zero deaths from silence.
- Set record_kind="count_only" and estimate_measure="count_only" when no rate is
  explicitly reported. Keep point_estimate=null, unit="NR", and all unreported
  uncertainty fields null/NR. Never calculate a rate or CI from counts, recover a
  missing count from a percentage, sum rows, or fabricate an interval.
- For an explicitly reported rate, set record_kind="rate_estimate" and retain any
  matched counts that are also explicitly reported.
- confirmed_cases is only this record's explicitly confirmed-case denominator.
  Estimated infections, unspecified patients, hospitalizations, ICU/IMV counts do
  not become confirmed_cases unless the text explicitly establishes confirmation.
- parameter_type="CFR" preserves the reported case-fatality label and source case
  definition; do not infer laboratory confirmation. Preserve fatality_type as
  HFR/ICU_fatality_rate/IMV_fatality_rate and denominator_type as the specific subgroup.
  parameter_type="IFR" requires estimated total infections. With uncertain case
  status use parameter_type="other" or "NR" and explain the uncertainty in notes.
- Keep each explicitly reported population/subgroup/region/time/denominator as its
  own record, with evidence_locations. Never collapse separate count denominators.

CRITICAL RULES:

1. fatality_type classification (use EXACTLY one):
   - CFR: deaths / cases under the stated source case definition
   - IFR: deaths / estimated total infections (requires seroprevalence or modeling)
   - HFR: deaths / hospitalized patients
   - ICU_fatality_rate: deaths / ICU admitted patients
   - IMV_fatality_rate: deaths / patients on invasive mechanical ventilation (intubated/ventilated)
   - other: if clearly none of the above

2. IMV detection - use IMV_fatality_rate if:
   - paper explicitly states "invasive mechanical ventilation" or explicitly invasive intubation; unspecified ventilated patients stay unresolved
   - denominator is IMV/ventilated patients specifically
   - EXCLUDE non-invasive ventilation (NIV, CPAP, high-flow)

3. Point estimate: explicitly REPORTED rates retain original units; count_only stays null
   - Preserve reported numbers and units; deterministic normalization occurs later.
   - Preserve an explicitly identified proportion in its original unit; if the unit is unclear, leave the rate null and explain the uncertainty. Never derive a rate from counts.

4. summary_type field:
   - Record how this paper reports the value: "single_study" | "median" | "mean" | "pooled_mean"
   - This is CRITICAL for downstream comparison with SR benchmarks

5. If paper reports BOTH overall and stratified (by age/sex/region):
   - Extract overall and each explicitly reported subgroup as separate records
   - Keep each subgroup's matched numerator, denominator, period and population; do not mix cohorts

6. Do NOT extract: treatment response rates, complication rates, ICU admission rates, or any non-mortality outcome

Use the analysis_summary from Stage A index to guide your extraction approach.
"""

OUTPUT = """
Return a JSON array only. No markdown, no explanations.
"""
