"""Shared optional estimate context, appended to effective extraction codebooks.

Definitions describe source assertions, never defaults or inferred study facts.
User-declared fields win by name; the legacy structural index schema is separate.
"""
from __future__ import annotations

import re

CONTEXT_SCHEMA_VERSION = 'coding_context_v1'

# (name, type, source-grounded instruction). No numerical study examples.
_COMMON = (
    ('method', 'str', 'Source-reported method metadata linked to this estimate, retaining its wording. This general method field does not automatically establish the analysis_method or statistical_model; preserve those meanings separately.'),
    ('statistic', 'str', 'Source-reported statistical summary label for this estimate, retaining distinctions such as arithmetic/geometric mean or posterior median. Preserve estimate_measure separately when declared; do not automatically copy or harmonize the fields.'),
    ('cohort_id', 'str', 'Source-reported cohort name or identifier for this estimate. Do not construct an identifier from PMID, author/year, country or numerical similarity. Leave null when not reported; report identity alone does not establish independence.'),
    ('stratum', 'str', 'Source-reported stratum to which this estimate belongs. Preserve the exact age, sex, variant, geography or other stratum and its relation to the estimate; do not invent an overall group.'),
    ('time_window', 'str', 'Source-reported observation or analysis window specifically associated with this estimate. Keep calendar period and follow-up/timepoint distinct; do not copy a whole-study period unless this estimate uses it.'),
    ('analysis_role', 'str', 'Source-supported role of this estimate, such as primary, secondary, subgroup or sensitivity analysis. Do not infer primary from prominence or select a preferred model; leave null when the source does not establish the role.'),
    ('analysis_method', 'str', 'Named analysis or estimation procedure producing this estimate, with its source wording. Distinguish the estimator from data collection, the fitted outcome distribution and a later meta-analysis; do not automatically copy the existing method field.'),
    ('statistical_model', 'str', 'Source-reported statistical model/specification linked to this estimate, including censoring or hierarchical structure when stated. Distinguish it from compartmental model_type and the outcome distribution; do not infer normality from a CI or standard error.'),
    ('adjustment_status', 'str', 'Whether this estimate is explicitly adjusted, unadjusted, stratified or otherwise adjusted as reported. Absence of covariate text is not proof of unadjusted analysis; leave null when unresolved.'),
    ('adjustment_variables', 'list[str]', 'Reported covariates or adjustment variables for this exact estimate. Quote source support for every listed variable and its role; do not assume standard covariates or convert subgroup labels into adjustment variables. Missing stays null.'),
    ('group_label', 'str', 'Verbatim source label for the population or analysis group to which this estimate applies. Keep distinct groups and intersections separate, with row/header evidence tying the group to its value.'),
    ('comparator', 'str', 'Source-reported comparator or reference group for this comparative estimate. Do not invent a comparator for a single-arm rate, interval or reproduction estimate; leave null if absent or not applicable.'),
    ('cohort_sample_size', 'str', 'Total source-reported cohort size, including its cases/pairs/clusters or other denominator description. This is not automatically the analytic sample for every estimate; do not copy sample_size without source support for this meaning.'),
    ('estimate_sample_size', 'str', 'Source-reported analytic sample specifically used for this estimate/group/model, retaining original count and wording. Do not substitute whole-cohort N, assumed pair counts or another model sample.'),
    ('estimate_sample_size_unit', 'str', 'Source-reported unit of the analytic sample, such as cases, people, transmission pairs or clusters. Do not infer the unit or use it to calculate a missing count.'),
    ('timepoint', 'str', 'Source-reported follow-up or time since a defined index event for this estimate, with the index event and original units. Distinguish it from a calendar estimation period and do not invent a shared follow-up.'),
    ('endpoint_definition', 'str', 'Operational endpoint/parameter definition used for this estimate, including exposure/index event and symptom-onset, rash-onset or other outcome definition when stated. Do not infer definitions from parameter_type or harmonize different endpoints during extraction.'),
)


def context_field_definitions(*, name='', effect_type='', disease='', parameters=None):
    """Return fresh optional field mappings; no config or scientific value mutation."""
    if str(effect_type).strip().casefold() == 'index':
        return []
    definitions = [{'name': key, 'label': key, 'type': kind, 'required': False, 'prompt': prompt}
                   for key, kind, prompt in _COMMON]
    parameters = parameters or {}
    domain = ' '.join(str(part or '').casefold() for part in (name, disease, parameters.get('disease')))
    if re.search(r'\b(?:mpox|monkeypox)\b', domain.replace('_',' ')):
        definitions.append({'name': 'clade', 'label': 'Clade', 'type': 'str', 'required': False,
                            'prompt': 'Source-reported mpox clade or lineage linked to this estimate. Do not infer clade from year, location or outbreak convention; leave null if not reported.'})
    return definitions
