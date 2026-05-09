# Prompt-Tuned Hybrid Summary - 2026-05-09

Policy: use complete Qwen3.6 Plus baseline except profiles where the tuned prompt full rerun improved F1/precision without unacceptable recall loss.

| Scope | Profiles | TP/FP/FN | Recall | Precision | F1 | NNS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 22 | 639/2670/29 | 95.7% | 19.3% | 0.321 | 5.18 |
| covid19 | 13 | 542/2398/19 | 96.6% | 18.4% | 0.310 | 5.42 |
| mpox | 9 | 97/272/10 | 90.7% | 26.3% | 0.408 | 3.80 |

## Selected Tuned Profiles

| Profile | Experiment | TP/FP/FN | Recall | Precision | F1 |
| --- | --- | ---: | ---: | ---: | ---: |
| mpox/fatality/p4 | prompt_tuned_sparse_boyue_qwen36plus_20260509 | 11/10/3 | 78.6% | 52.4% | 0.629 |
| mpox/fatality/p8 | prompt_tuned_sparse_boyue_qwen36plus_20260509 | 10/50/4 | 71.4% | 16.7% | 0.270 |
| mpox/fatality/p12 | prompt_tuned_sparse_boyue_qwen36plus_20260509 | 15/79/1 | 93.8% | 16.0% | 0.273 |
| mpox/reproduction_number/p9 | prompt_tuned_sparse_boyue_qwen36plus_20260509 | 3/3/0 | 100.0% | 50.0% | 0.667 |
| mpox/serial_interval/p6 | prompt_tuned_sparse_boyue_qwen36plus_20260509 | 5/15/0 | 100.0% | 25.0% | 0.400 |
| mpox/serial_interval/p10 | prompt_tuned_sparse_boyue_qwen36plus_20260509 | 14/14/1 | 93.3% | 50.0% | 0.651 |
| covid19/reproduction_number/p15 | prompt_tuned_sparse_r0recall_boyue_qwen36plus_20260509 | 25/402/0 | 100.0% | 5.9% | 0.111 |
| covid19/reproduction_number/p16 | prompt_tuned_sparse_r0recall_boyue_qwen36plus_20260509 | 34/248/2 | 94.4% | 12.1% | 0.214 |
