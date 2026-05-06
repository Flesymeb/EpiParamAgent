# COVID13 Overnight Screening Model Comparison

- Generated: 2026-05-06T02:55:08
- TSV: `model_comparison_overnight_covid13_20260506_025445.tsv`
- Scope: COVID19 P4-P8 and P10-P17.
- Run mode: strategy `5d`, `--skip-no-abstract`, `--no-fulltext-rescue`.

| model | projects | TP | FP | FN | TN | micro recall | micro precision | workload reduction | micro F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-5.4_current | 13 | 507 | 2033 | 57 | 6317 | 0.899 | 0.200 | 0.715 | 0.327 |
| openai/gpt-4.1 | 13 | 492 | 2452 | 72 | 5898 | 0.872 | 0.167 | 0.670 | 0.281 |
| qwen/qwen-turbo | 11 | 489 | 2676 | 28 | 4929 | 0.946 | 0.155 | 0.610 | 0.266 |

## Non-ok Rows

- qwen/qwen-turbo P16: missing_output
- qwen/qwen-turbo P17: missing_output
- minimax/minimax-m2.5 P4: missing_output
- minimax/minimax-m2.5 P5: missing_output
- minimax/minimax-m2.5 P6: missing_output
- minimax/minimax-m2.5 P7: missing_output
- minimax/minimax-m2.5 P8: missing_output
- minimax/minimax-m2.5 P10: missing_output
- minimax/minimax-m2.5 P11: missing_output
- minimax/minimax-m2.5 P12: missing_output
- minimax/minimax-m2.5 P13: missing_output
- minimax/minimax-m2.5 P14: missing_output
- minimax/minimax-m2.5 P15: missing_output
- minimax/minimax-m2.5 P16: missing_output
- minimax/minimax-m2.5 P17: missing_output
- deepseek/deepseek-v4-flash P4: missing_output
- deepseek/deepseek-v4-flash P5: missing_output
- deepseek/deepseek-v4-flash P6: missing_output
- deepseek/deepseek-v4-flash P7: missing_output
- deepseek/deepseek-v4-flash P8: missing_output
- deepseek/deepseek-v4-flash P10: missing_output
- deepseek/deepseek-v4-flash P11: missing_output
- deepseek/deepseek-v4-flash P12: missing_output
- deepseek/deepseek-v4-flash P13: missing_output
- deepseek/deepseek-v4-flash P14: missing_output
- deepseek/deepseek-v4-flash P15: missing_output
- deepseek/deepseek-v4-flash P16: missing_output
- deepseek/deepseek-v4-flash P17: missing_output
