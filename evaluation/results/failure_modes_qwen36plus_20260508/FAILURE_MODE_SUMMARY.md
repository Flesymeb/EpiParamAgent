# Screening Failure Mode Analysis — Qwen3.6 Plus

Updated: 2026-05-08 04:34:00

Model slug: `model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus`

## Metric Context

| Scope | TP/FP/FN/TN | Recall | Precision | F1 | FDR | NNS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| covid19 | 542/2474/19/5878 | 96.6% | 18.0% | 30.3% | 82.0% | 5.56 |
| covid19 / Fatality | 133/1017/3/3327 | 97.8% | 11.6% | 20.7% | 88.4% | 8.65 |
| covid19 / Reproduction number | 238/1206/4/1194 | 98.3% | 16.5% | 28.2% | 83.5% | 6.07 |
| covid19 / Serial interval | 171/251/12/1357 | 93.4% | 40.5% | 56.5% | 59.5% | 2.47 |
| mpox | 92/472/15/3266 | 86.0% | 16.3% | 27.4% | 83.7% | 6.13 |
| mpox / Fatality | 58/325/13/1374 | 81.7% | 15.1% | 25.6% | 84.9% | 6.60 |
| mpox / Reproduction number | 3/17/0/799 | 100.0% | 15.0% | 26.1% | 85.0% | 6.67 |
| mpox / Serial interval | 31/130/2/1093 | 93.9% | 19.3% | 32.0% | 80.7% | 5.19 |
| Overall | 634/2946/34/9144 | 94.9% | 17.7% | 29.8% | 82.3% | 5.65 |

## Error-Type Summary

Percentages are within the FP or FN denominator for that disease/topic scope.

### covid19 / Fatality — FP

| Type | Count | Share |
| --- | ---: | ---: |
| `plausibly_relevant_not_in_sr_gt` | 386/1017 | 38.0% |
| `sparse_metadata_over_inclusion` | 189/1017 | 18.6% |
| `broad_topic_over_inclusion` | 172/1017 | 16.9% |
| `weak_or_indirect_target_parameter` | 137/1017 | 13.5% |
| `borderline_possible_over_inclusion` | 71/1017 | 7.0% |
| `review_signal_overridden_by_model` | 31/1017 | 3.0% |
| `weak_original_evidence` | 20/1017 | 2.0% |
| `wrong_epidemiological_parameter` | 11/1017 | 1.1% |

Examples for top type `plausibly_relevant_not_in_sr_gt`:
- PMID 33214992: Changing epidemiology of COVID-19. (D=4, E=4, Par=4, tier=S)
- PMID 32234121: Estimating the infection and case fatality ratio for coronavirus disease (COVID-19) using age-adjusted data from the outbreak on the Diamond Princess cruise ship, February 2020. (D=4, E=4, Par=4, tier=S)
- PMID 32332856: COVID-19 in persons with haematological cancers. (D=4, E=4, Par=4, tier=S)
- PMID 33320895: COVID-19: Spatial analysis of hospital case-fatality rate in France. (D=4, E=4, Par=4, tier=S)
- PMID 32611978: SARS-CoV-2 in Italy: Population Density Correlates with Morbidity and Mortality. (D=4, E=4, Par=4, tier=S)

### covid19 / Fatality — FN

| Type | Count | Share |
| --- | ---: | ---: |
| `target_parameter_not_detected` | 2/3 | 66.7% |
| `possible_gt_non_original_or_review` | 1/3 | 33.3% |

Examples for top type `target_parameter_not_detected`:
- PMID 32431287: Critical Care Management of Patients with COVID-19: Early Experience in Thailand. (D=4, E=2, Par=2, tier=U)
- PMID 33284413: Endotoxemia and circulating bacteriome in severe COVID-19 patients. (D=4, E=4, Par=2, tier=U)

### covid19 / Reproduction number — FP

| Type | Count | Share |
| --- | ---: | ---: |
| `plausibly_relevant_not_in_sr_gt` | 471/1206 | 39.1% |
| `weak_or_indirect_target_parameter` | 312/1206 | 25.9% |
| `broad_topic_over_inclusion` | 197/1206 | 16.3% |
| `sparse_metadata_over_inclusion` | 93/1206 | 7.7% |
| `borderline_possible_over_inclusion` | 72/1206 | 6.0% |
| `weak_original_evidence` | 34/1206 | 2.8% |
| `review_signal_overridden_by_model` | 27/1206 | 2.2% |

Examples for top type `plausibly_relevant_not_in_sr_gt`:
- PMID 32614817: Estimation of country-level basic reproductive ratios for novel Coronavirus (SARS-CoV-2/COVID-19) using synthetic contact matrices. (D=4, E=4, Par=4, tier=S)
- PMID 32959618: Epidemic Landscape and Forecasting of SARS-CoV-2 in India. (D=4, E=4, Par=4, tier=S)
- PMID 32703910: Evolution and epidemic spread of SARS-CoV-2 in Brazil. (D=4, E=4, Par=4, tier=S)
- PMID 32794161: Epidemiology of SARS-CoV-2 in Egypt. (D=4, E=4, Par=4, tier=S)
- PMID 32275295: Association of Public Health Interventions With the Epidemiology of the COVID-19 Outbreak in Wuhan, China. (D=4, E=4, Par=4, tier=S)

### covid19 / Reproduction number — FN

| Type | Count | Share |
| --- | ---: | ---: |
| `target_parameter_not_detected` | 4/4 | 100.0% |

Examples for top type `target_parameter_not_detected`:
- PMID 32119825: Feasibility of controlling COVID-19 outbreaks by isolation of cases and contacts. (D=4, E=3, Par=2, tier=U)
- PMID 32511457: Risk for Transportation of 2019 Novel Coronavirus (COVID-19) from Wuhan to Cities in China. (D=4, E=3, Par=0, tier=U)
- PMID 32987502: The within-host viral kinetics of SARS-CoV-2. (D=4, E=3, Par=2, tier=U)
- PMID 33003939: Power-law distribution in the number of confirmed COVID-19 cases. (D=4, E=4, Par=1, tier=U)

### covid19 / Serial interval — FP

| Type | Count | Share |
| --- | ---: | ---: |
| `plausibly_relevant_not_in_sr_gt` | 124/251 | 49.4% |
| `weak_or_indirect_target_parameter` | 101/251 | 40.2% |
| `broad_topic_over_inclusion` | 11/251 | 4.4% |
| `sparse_metadata_over_inclusion` | 10/251 | 4.0% |
| `review_signal_overridden_by_model` | 3/251 | 1.2% |
| `weak_original_evidence` | 1/251 | 0.4% |
| `borderline_possible_over_inclusion` | 1/251 | 0.4% |

Examples for top type `plausibly_relevant_not_in_sr_gt`:
- PMID 35176230: Generation time of the alpha and delta SARS-CoV-2 variants: an epidemiological analysis. (D=4, E=4, Par=4, tier=S)
- PMID 35791373: Intrinsic generation time of the SARS-CoV-2 Omicron variant: An observational study of household transmission. (D=4, E=4, Par=4, tier=S)
- PMID 36524247: Estimation of the incubation period and generation time of SARS-CoV-2 Alpha and Delta variants from contact tracing data. (D=4, E=4, Par=4, tier=S)
- PMID 34865022: Transmission Dynamics of the Delta Variant of SARS-CoV-2 Infections in South Korea. (D=4, E=4, Par=4, tier=S)
- PMID 36511336: Transmission dynamics of SARS-CoV-2 Omicron variant infections in Hangzhou, Zhejiang, China, January-February 2022. (D=4, E=4, Par=4, tier=S)

### covid19 / Serial interval — FN

| Type | Count | Share |
| --- | ---: | ---: |
| `target_parameter_not_detected` | 10/12 | 83.3% |
| `possible_gt_non_original_or_review` | 2/12 | 16.7% |

Examples for top type `target_parameter_not_detected`:
- PMID 36650162: Rapid transmission and tight bottlenecks constrain the evolution of highly transmissible SARS-CoV-2 variants. (D=4, E=4, Par=0, tier=U)
- PMID 32035431: Epidemiologic characteristics of early cases with 2019 novel coronavirus (2019-nCoV) disease in Korea. (D=4, E=4, Par=0, tier=U)
- PMID 32943787: Clustering and superspreading potential of SARS-CoV-2 infections in Hong Kong. (D=4, E=4, Par=0, tier=U)
- PMID 36263065: SARS-CoV-2 containment was achievable during the early stage of the pandemic: a retrospective modelling study of the Xinfadi outbreak in Beijing. (D=4, E=3, Par=0, tier=U)
- PMID 33362233: Estimation of the incubation period of COVID-19 in Vietnam. (D=4, E=4, Par=0, tier=U)

### mpox / Fatality — FP

| Type | Count | Share |
| --- | ---: | ---: |
| `weak_or_indirect_target_parameter` | 129/325 | 39.7% |
| `sparse_metadata_over_inclusion` | 105/325 | 32.3% |
| `plausibly_relevant_not_in_sr_gt` | 36/325 | 11.1% |
| `weak_original_evidence` | 26/325 | 8.0% |
| `borderline_possible_over_inclusion` | 13/325 | 4.0% |
| `broad_topic_over_inclusion` | 9/325 | 2.8% |
| `review_signal_overridden_by_model` | 7/325 | 2.2% |

Examples for top type `weak_or_indirect_target_parameter`:
- PMID 36858309: Lymphofollicular lesions associated with monkeypox (Mpox) virus proctitis. (D=4, E=3, Par=2, tier=P)
- PMID 39672537: A new method for the estimation of stochastic epidemic descriptors reinforced by Kalman-based dynamic parameter estimation. Application to mpox data. (D=4, E=3, Par=2, tier=P)
- PMID 37947018: Prior Sexually Transmitted Infections and HIV in Patients With Mpox, Chicago, Illinois (June 2022-March 2023). (D=4, E=4, Par=2, tier=P)
- PMID 38342913: Case report: atypical presentation of mpox with massive hematochezia and prolonged viral shedding despite tecovirimat treatment. (D=4, E=3, Par=2, tier=P)
- PMID 38263944: [A Case Report of Monkeypox Disease in an Adolescent]. (D=4, E=3, Par=2, tier=P)

### mpox / Fatality — FN

| Type | Count | Share |
| --- | ---: | ---: |
| `target_parameter_not_detected` | 12/13 | 92.3% |
| `insufficient_title_abstract_evidence` | 1/13 | 7.7% |

Examples for top type `target_parameter_not_detected`:
- PMID 25600603: Cytokine modulation correlates with severity of monkeypox disease in humans. (D=4, E=4, Par=1, tier=U)
- PMID 14688573: A case of severe monkeypox virus disease in an American child: emerging infections and changing professional values. (D=4, E=3, Par=1, tier=U)
- PMID 35837859: Infection-competent monkeypox virus contamination identified in domestic settings following an imported case of monkeypox into the UK. (D=4, E=3, Par=0, tier=U)
- PMID 32338590: Imported Monkeypox, Singapore. (D=4, E=3, Par=1, tier=U)
- PMID 35389974: Monkeypox in a Traveler Returning from Nigeria - Dallas, Texas, July 2021. (D=4, E=3, Par=1, tier=U)

### mpox / Reproduction number — FP

| Type | Count | Share |
| --- | ---: | ---: |
| `sparse_metadata_over_inclusion` | 8/17 | 47.1% |
| `weak_or_indirect_target_parameter` | 4/17 | 23.5% |
| `borderline_possible_over_inclusion` | 3/17 | 17.6% |
| `broad_topic_over_inclusion` | 2/17 | 11.8% |

Examples for top type `sparse_metadata_over_inclusion`:
- PMID 39041467: Mpox outbreak - Response and epidemiology of confirmed cases in Ireland from May 2022 to May 2023. (D=4, E=3, Par=2, tier=P)
- PMID 38069519: Causal factors for the rapid decline of the global Mpox outbreak 2022. (D=4, E=2, Par=2, tier=P)
- PMID 37271200: The arrival of Mpox in Venezuela: Why so few cases? (D=4, E=2, Par=2, tier=P)
- PMID 36310269: [Not Available]. (D=4, E=2, Par=1, tier=P)
- PMID 35691542: Risk of monkeypox outbreak in Nepal. (D=4, E=2, Par=2, tier=P)

### mpox / Serial interval — FP

| Type | Count | Share |
| --- | ---: | ---: |
| `weak_or_indirect_target_parameter` | 57/130 | 43.8% |
| `sparse_metadata_over_inclusion` | 22/130 | 16.9% |
| `plausibly_relevant_not_in_sr_gt` | 21/130 | 16.2% |
| `wrong_epidemiological_parameter` | 9/130 | 6.9% |
| `weak_original_evidence` | 8/130 | 6.2% |
| `broad_topic_over_inclusion` | 7/130 | 5.4% |
| `borderline_possible_over_inclusion` | 4/130 | 3.1% |
| `review_signal_overridden_by_model` | 2/130 | 1.5% |

Examples for top type `weak_or_indirect_target_parameter`:
- PMID 34387184: Family cluster of three cases of monkeypox imported from Nigeria to the United Kingdom, May 2021. (D=4, E=3, Par=2, tier=P)
- PMID 32023204: Human-to-Human Transmission of Monkeypox Virus, United Kingdom, October 2018. (D=4, E=4, Par=2, tier=P)
- PMID 37212312: Presymptomatic viral shedding in high-risk mpox contacts: A prospective cohort study. (D=4, E=4, Par=2, tier=P)
- PMID 39360827: Viral genetics and transmission dynamics in the second wave of mpox outbreak in Portugal and forecasting public health scenarios. (D=4, E=4, Par=2, tier=P)
- PMID 38666400: Scenarios of future mpox outbreaks among men who have sex with men: a modelling study based on cross-sectional seroprevalence data from the Netherlands, 2022. (D=4, E=4, Par=2, tier=P)

### mpox / Serial interval — FN

| Type | Count | Share |
| --- | ---: | ---: |
| `target_parameter_not_detected` | 1/2 | 50.0% |
| `possible_gt_non_original_or_review` | 1/2 | 50.0% |

Examples for top type `target_parameter_not_detected`:
- PMID 36950196: Investigation of a mpox outbreak in Central African Republic, 2021-2022. (D=4, E=4, Par=1, tier=U)

## Category Definitions

- `non_original_or_secondary_literature`: FP: review/commentary/editorial-like paper admitted as candidate.
- `sparse_metadata_over_inclusion`: FP: little or no abstract, yet model still kept it.
- `wrong_epidemiological_parameter`: FP: evidence points to another parameter family rather than the target one.
- `weak_or_indirect_target_parameter`: FP: target parameter score was weak or indirect but still admitted.
- `weak_original_evidence`: FP: original evidence score was weak but still admitted.
- `borderline_possible_over_inclusion`: FP: possible-candidate bucket admitted a broad or ambiguous paper.
- `review_signal_overridden_by_model`: FP: review/commentary signal existed but was outweighed by model.
- `plausibly_relevant_not_in_sr_gt`: FP: high disease/evidence/parameter scores; likely broad relevant paper absent from SR GT or out of SR scope.
- `broad_topic_over_inclusion`: FP: broad disease/topic relevance without enough extractable target evidence.
- `possible_gt_non_original_or_review`: FN: GT paper itself looks review-like or secondary from metadata; needs manual GT audit.
- `insufficient_title_abstract_evidence`: FN: title/abstract too sparse for the model to confirm relevance.
- `disease_scope_underestimated`: FN: disease dimension was scored too low.
- `target_parameter_not_detected`: FN: target parameter signal was missed or scored weakly.
- `original_evidence_underestimated`: FN: paper appears relevant but evidence dimension was scored too low.
- `population_or_setting_scope_underestimated`: FN: population/location setting lowered the tier.
- `llm_tier_too_conservative`: FN: scores support inclusion but LLM tier excluded it.
- `mixed_borderline_under_inclusion`: FN: multiple moderate weaknesses led to exclusion.
