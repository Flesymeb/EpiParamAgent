# LEADS official coding best-effort pooling

This uses only the LEADS official trial-result extraction schema outputs. It does not use the 5D codebook or MetaAgent coding evaluator. Continuous outcomes are simple means of extracted values because LEADS does not return per-study SE/CI in this schema. Fatality uses a best-effort mean of extracted rates; count outputs are converted as value / denomValue * 100 when possible.

| Profile | Topic | n | LEADS official (95% simple CI) | SR | 5D | Δ LEADS | Δ 5D | Closer | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P10 | serial_interval | 32 | 3.39 (3.07-3.72) days | 3.55 | 3.64 | -0.16 | 0.09 | 5D | median=3.15; no per-study SE in LEADS schema; Serial interval; SR mixed equal-weighted Delta/Omicron |
| P11 | serial_interval | 71 | 4.15 (3.83-4.47) days | 3.50 | 3.48 | 0.65 | -0.02 | 5D | median=4.00; no per-study SE in LEADS schema; Serial interval |
| P12 | serial_interval | 20 | 5.29 (4.92-5.66) days | 5.20 | 5.26 | 0.09 | 0.06 | 5D | median=5.20; no per-study SE in LEADS schema; Serial interval |
| P13 | serial_interval | 52 | 4.80 (4.45-5.15) days | 4.90 | 4.98 | -0.10 | 0.08 | 5D | median=4.72; no per-study SE in LEADS schema; Serial interval vs post-peak China |
| P14 | serial_interval | 9 | 4.94 (4.14-5.74) days | 5.40 | 5.38 | -0.46 | -0.02 | 5D | median=4.60; no per-study SE in LEADS schema; Serial interval vs fixed-effect SR |
| P4 | fatality | 55 | 24.11 (17.30-30.93) % | 45.00 | 44.70 | -20.89 | -0.30 | 5D | count-derived rates=48, direct percent values=7, aggregate=89.33%; Fatality CFR/IMV percent |
| P5 | fatality | 48 | 1.97 (0.93-3.02) % | 0.27 | 0.28 | 1.70 | 0.01 | 5D | count-derived rates=24, direct percent values=24, aggregate=9.90%; Fatality IFR median percent |
| P6 | fatality | 32 | 20.04 (11.28-28.79) % | 13.00 | 12.70 | 7.04 | -0.30 | 5D | count-derived rates=27, direct percent values=5, aggregate=19.50%; Fatality HFR percent; LEADS cannot separate HFR/ICU |
| P7 | reproduction_number | 67 | 2.54 (2.26-2.81) R | 2.66 | 2.74 | -0.12 | 0.08 | 5D | median=2.34; no per-study SE in LEADS schema; R0 |
| P8 | reproduction_number | 59 | 2.51 (2.20-2.82) R | 2.69 | 2.83 | -0.18 | 0.14 | 5D | median=2.40; no per-study SE in LEADS schema; R0 |
| P15 | reproduction_number | 27 | 3.33 (2.28-4.38) R | 2.87 | 3.06 | 0.46 | 0.19 | 5D | median=2.43; no per-study SE in LEADS schema; R0 |
| P16 | reproduction_number | 40 | 2.63 (2.29-2.97) R | 4.08 | 3.97 | -1.45 | -0.11 | 5D | median=2.46; no per-study SE in LEADS schema; R0 |
| P17 | reproduction_number | 13 | 2.77 (2.13-3.41) R | 3.32 | 2.87 | -0.55 | -0.45 | 5D | median=2.38; no per-study SE in LEADS schema; R0 |
| MP9 | reproduction_number | 3 | 1.07 (0.15-2.00) R | 1.80 | 1.78 | -0.73 | -0.02 | 5D | median=1.00; no per-study SE in LEADS schema; R0 |
| MP6 | serial_interval | 5 | 6.04 (3.29-8.80) days | 8.70 | 9.00 | -2.66 | 0.30 | 5D | median=6.30; no per-study SE in LEADS schema; Serial interval |
| MP10 | serial_interval | 14 | 9.19 (6.55-11.84) days | 12.00 | 11.42 | -2.81 | -0.58 | 5D | median=8.66; no per-study SE in LEADS schema; Serial interval |
| MP11 | serial_interval | 6 | 7.37 (6.35-8.39) days | 8.30 | 8.03 | -0.93 | -0.27 | 5D | median=7.50; no per-study SE in LEADS schema; Serial interval |
| MP5 | serial_interval | 8 | 8.34 (6.18-10.50) days | 8.26 | 8.55 | 0.08 | 0.29 | LEADS | median=9.90; no per-study SE in LEADS schema; Incubation period in report; dataset folder is serial_interval |
| MP4 | fatality | 14 | 3.00 (0.65-5.36) % | 5.80 | 5.80 | -2.80 | 0.00 | 5D | count-derived rates=13, direct percent values=1, aggregate=0.33%; Fatality aggregate percent |
| MP7 | fatality | 20 | 6.01 (1.46-10.55) % | 11.40 | 11.11 | -5.39 | -0.29 | 5D | count-derived rates=20, direct percent values=0, aggregate=0.36%; Fatality pre-2016 percent |
| MP8 | fatality | 17 | 7.81 (-3.60-19.22) % | 9.80 | 8.33 | -1.99 | -1.47 | 5D | count-derived rates=17, direct percent values=0, aggregate=99.91%; Fatality Clade I percent |
| MP12 | fatality | 13 | 3.34 (0.62-6.07) % | 11.00 | 10.46 | -7.66 | -0.54 | 5D | count-derived rates=12, direct percent values=1, aggregate=0.24%; Pediatric fatality; SR reports <=11% / range 4-20% |
