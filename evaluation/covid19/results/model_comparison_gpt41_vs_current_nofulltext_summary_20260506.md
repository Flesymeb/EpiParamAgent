# COVID19 Screening Model Comparison (No Full-text Rescue)

- Source TSV: `model_comparison_gpt41_vs_current_nofulltext_final_20260506_010358.tsv`
- Scope: COVID19 registry profiles P4-P8 and P10-P17 (13 projects).
- New run: `openai/gpt-4.1`, strategy `5d`, `--batch-size 500`, `--batch-concurrency 64`, `--skip-no-abstract`, `--no-fulltext-rescue`.
- Baseline: existing root `project_*_screened.csv` files labeled `gpt-5.4_current`.
- Kimi K2.5 was not included in full COVID13 because P14 smoke tests were too slow and unstable under OpenRouter structured output.

| model | projects | GT | pool | TP | FP | FN | TN | micro recall | micro precision | workload reduction | micro F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-5.4_current | 13 | 564 | 8912 | 507 | 2033 | 57 | 6317 | 0.899 | 0.200 | 0.715 | 0.327 |
| openai/gpt-4.1 | 13 | 564 | 8912 | 492 | 2452 | 72 | 5898 | 0.872 | 0.167 | 0.670 | 0.281 |

| profile | topic | current recall | gpt-4.1 recall | current precision | gpt-4.1 precision | current WR | gpt-4.1 WR |
|---|---|---:|---:|---:|---:|---:|---:|
| P4 | fatality | 1.000 | 0.982 | 0.252 | 0.252 | 0.357 | 0.368 |
| P5 | fatality | 0.958 | 1.000 | 0.291 | 0.144 | 0.916 | 0.823 |
| P6 | fatality | 0.872 | 0.846 | 0.051 | 0.037 | 0.707 | 0.609 |
| P7 | reproduction_number | 0.877 | 0.713 | 0.633 | 0.659 | 0.706 | 0.770 |
| P8 | reproduction_number | 0.932 | 0.841 | 0.167 | 0.167 | 0.574 | 0.614 |
| P10 | serial_interval | 0.786 | 1.000 | 0.537 | 0.412 | 0.932 | 0.886 |
| P11 | serial_interval | 0.934 | 0.987 | 0.507 | 0.292 | 0.834 | 0.694 |
| P12 | serial_interval | 0.789 | 0.947 | 0.484 | 0.265 | 0.786 | 0.531 |
| P13 | serial_interval | 0.824 | 0.902 | 0.609 | 0.541 | 0.378 | 0.234 |
| P14 | serial_interval | 0.889 | 1.000 | 0.170 | 0.143 | 0.500 | 0.330 |
| P15 | reproduction_number | 1.000 | 0.840 | 0.061 | 0.065 | 0.423 | 0.544 |
| P16 | reproduction_number | 0.875 | 0.812 | 0.113 | 0.123 | 0.569 | 0.633 |
| P17 | reproduction_number | 0.800 | 0.600 | 0.121 | 0.110 | 0.526 | 0.608 |
