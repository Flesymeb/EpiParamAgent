# LEADS-Mistral prompt comparison

- Old: `leads_mistral_strict_simple_20260506_185524` (`strict_simple`)
- New: `leads_mistral_disease_parameter_minimal_20260506_225001` (`disease_parameter_minimal`)

| group | recall old -> new | precision old -> new | F1 old -> new | workload reduction old -> new | TP/FP/FN/TN old -> new |
|---|---:|---:|---:|---:|---|
| covid19 | 0.952 -> 0.887 (-0.066) | 0.096 -> 0.094 (-0.002) | 0.174 -> 0.170 (-0.005) | 0.372 -> 0.402 (+0.030) | 537/5061/27/3289 -> 500/4830/64/3520 |
| mpox | 0.402 -> 0.779 (+0.377) | 0.044 -> 0.040 (-0.004) | 0.079 -> 0.075 (-0.003) | 0.795 -> 0.564 (-0.231) | 49/1076/73/4303 -> 95/2302/27/3077 |
| overall | 0.854 -> 0.867 (+0.013) | 0.087 -> 0.077 (-0.010) | 0.158 -> 0.141 (-0.017) | 0.534 -> 0.464 (-0.070) | 586/6137/100/7592 -> 595/7132/91/6597 |

Per-profile deltas are in `screening/comparison_strict_simple_vs_disease_parameter_minimal.csv`.
