# Screening Profiles

This directory is the canonical catalog for screening experiments.

## Why this exists

Profiles are data, not code.

Adding a new evaluation project should not require editing Python modules under
`src/` or `scripts/`. For open-source use and multi-project experimentation,
each profile lives in YAML and is loaded by:

- [`profile_registry.py`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/src/screening/profile_registry.py)
- [`profile_resolution.py`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/src/screening/profile_resolution.py)

## Layout

- one YAML file per topic
- one `profiles:` block containing `Pxx` entries
- shared defaults at topic level

## Minimal example

```yaml
topic: serial_interval

defaults:
  thresholds:
    strong:
      disease_min: 4
      parameter_min: 4
      evidence_min: 3
      population_min: 2
      location_min: 2
    possible:
      disease_min: 3
      parameter_min: 3
      evidence_min: 2
      population_min: 2
      location_min: 2
  policies:
    title_abstract_mode: standard
    title_only_mode: lenient
    full_text_mode: standard
    fulltext_rescue:
      enabled: true
      when_no_abstract: true

profiles:
  P18:
    project_number: 18
    research_question: What are the serial intervals of SARS-CoV-2?
    disease_focus: "(COVID-19 OR SARS-CoV-2)"
    disease_exclude: "(MERS OR influenza)"
    parameter_focus: "(serial interval)"
    parameter_exclude: "none"
```

## Naming rules

- topic files use snake_case: `serial_interval.yaml`
- profile IDs use `Pxx`
- `project_number` maps to `evaluation/.../pXX/`

## Operational rule

If you are adding a new project, edit YAML here first.
Do not add new hardcoded project configs under `scripts/` or `src/`.
