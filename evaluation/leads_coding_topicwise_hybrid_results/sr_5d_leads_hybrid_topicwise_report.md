# SR vs 5D vs LEADS-Hybrid Topicwise

LEADS-Hybrid Topicwise is the selected coding baseline package. It uses `official_trial_result_lite` for continuous outcomes (`reproduction_number`, `serial_interval`) and `official_trial_result_final` for fatality outcomes. This keeps the better continuous behavior of Lite while using the stronger fatality behavior of the full official prompt.

LEADS confidence intervals are simple across-extraction intervals, not random-effects meta-analysis intervals.

## Summary

| Scope | Profiles | LEADS MAE | 5D MAE | LEADS closer | 5D closer | Tie | LEADS n | lite profiles | final profiles |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overall | 22 | 2.571 | 0.255 | 5 | 17 | 0 | 552 | 15 | 7 |
| continuous | 15 | 0.607 | 0.180 | 5 | 10 | 0 | 353 | 15 | 0 |
| fatality | 7 | 6.781 | 0.416 | 0 | 7 | 0 | 199 | 0 | 7 |
| r0 | 6 | 0.432 | 0.165 | 1 | 5 | 0 | 175 | 6 | 0 |
| serial_interval | 9 | 0.723 | 0.190 | 4 | 5 | 0 | 178 | 9 | 0 |
| covid19 | 13 | 2.569 | 0.142 | 4 | 9 | 0 | 460 | 10 | 3 |
| mpox | 9 | 2.574 | 0.418 | 1 | 8 | 0 | 92 | 5 | 4 |

## Project Estimates

| Profile | Disease | Parameter | Source | SR reference | 5D | LEADS-Hybrid | n | Delta 5D | Delta LEADS | Closer | Note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P10 | covid19 | Serial interval | official_trial_result_lite | 3.55 (3.28-3.82) days | 3.64 (3.45-3.84) days | 3.50 (3.16-3.84) days | 21 | 0.09 | -0.05 | LEADS-Hybrid | SR mixed Delta/Omicron |
| P11 | covid19 | Serial interval | official_trial_result_lite | 3.50 (3.00-4.00) days | 3.48 (3.32-3.64) days | 4.40 (4.05-4.76) days | 57 | -0.02 | 0.90 | 5D | Variant-stratified SR; global approximation |
| P12 | covid19 | Serial interval | official_trial_result_lite | 5.20 (4.90-5.50) days | 5.26 (4.82-5.70) days | 5.19 (4.81-5.56) days | 19 | 0.06 | -0.01 | LEADS-Hybrid |  |
| P13 | covid19 | Serial interval | official_trial_result_lite | 4.90 (1.90-6.50) days | 4.98 (4.68-5.28) days | 4.85 (4.49-5.22) days | 47 | 0.08 | -0.05 | LEADS-Hybrid | SR post-peak China reference |
| P14 | covid19 | Serial interval | official_trial_result_lite | 5.40 (5.19-5.61) days | 5.38 (4.70-6.06) days | 5.18 (4.27-6.09) days | 8 | -0.02 | -0.22 | 5D | SR fixed-effect reference |
| P7 | covid19 | R0 | official_trial_result_lite | 2.66 (2.41-2.94) R | 2.74 (2.53-2.97) R | 2.34 (2.02-2.66) R | 54 | 0.08 | -0.32 | 5D |  |
| P8 | covid19 | R0 | official_trial_result_lite | 2.69 (2.40-2.98) R | 2.83 (2.40-3.34) R | 2.57 (1.94-3.20) R | 37 | 0.14 | -0.12 | LEADS-Hybrid |  |
| P15 | covid19 | R0 | official_trial_result_lite | 2.87 (2.39-3.44) R | 3.06 (2.69-3.49) R | 3.21 (2.19-4.23) R | 31 | 0.19 | 0.34 | 5D |  |
| P16 | covid19 | R0 | official_trial_result_lite | 4.08 (3.09-5.39) R | 3.97 (2.96-4.98) R | 2.96 (2.54-3.37) R | 39 | -0.11 | -1.12 | 5D |  |
| P17 | covid19 | R0 | official_trial_result_lite | 3.32 (2.81-3.82) R | 2.87 (2.30-3.59) R | 2.68 (1.97-3.39) R | 12 | -0.45 | -0.64 | 5D |  |
| P4 | covid19 | CFR (IMV) | official_trial_result_final | 45.00 (39.00-52.00) % | 44.70 (31.90-57.40) % | 24.11 (17.30-30.93) % | 55 | -0.30 | -20.89 | 5D |  |
| P5 | covid19 | IFR median | official_trial_result_final | 0.27 % | 0.28 % | 1.97 (0.93-3.02) % | 48 | 0.01 | 1.70 | 5D | SR/5D median no CI |
| P6 | covid19 | CFR (HFR) | official_trial_result_final | 13.00 (9.00-17.00) % | 12.70 (10.50-14.90) % | 20.04 (11.28-28.79) % | 32 | -0.30 | 7.04 | 5D | P6 ICU row not shown; LEADS cannot separate HFR/ICU |
| MP9 | mpox | R0 | official_trial_result_lite | 1.80 (1.70-1.90) R | 1.78 (1.67-1.90) R | 1.75 (1.65-1.86) R | 2 | -0.02 | -0.05 | 5D |  |
| MP6 | mpox | Serial interval | official_trial_result_lite | 8.70 (6.50-11.00) days | 9.00 (6.74-11.27) days | 6.02 (3.27-8.78) days | 5 | 0.30 | -2.68 | 5D |  |
| MP10 | mpox | Serial interval | official_trial_result_lite | 12.00 (8.01-15.99) days | 11.42 (8.37-14.48) days | 10.32 (7.10-13.54) days | 10 | -0.58 | -1.68 | 5D |  |
| MP11 | mpox | Serial interval | official_trial_result_lite | 8.30 (6.74-10.23) days | 8.03 (7.12-8.93) days | 7.42 (6.15-8.69) days | 5 | -0.27 | -0.88 | 5D |  |
| MP5 | mpox | Incubation period | official_trial_result_lite | 8.26 (7.55-8.97) days | 8.55 (7.02-10.09) days | 8.22 (5.35-11.08) days | 6 | 0.29 | -0.04 | LEADS-Hybrid | Dataset topic folder is serial_interval |
| MP4 | mpox | CFR aggregate | official_trial_result_final | 5.80 % | 5.80 % | 3.00 (0.65-5.36) % | 14 | 0.00 | -2.80 | 5D |  |
| MP7 | mpox | CFR pre-2016 | official_trial_result_final | 11.40 (5.80-21.10) % | 11.11 (9.51-12.71) % | 6.01 (1.46-10.55) % | 20 | -0.29 | -5.39 | 5D |  |
| MP8 | mpox | CFR Clade I | official_trial_result_final | 9.80 % | 8.33 (6.39-10.27) % | 7.81 (-3.60-19.22) % | 17 | -1.47 | -1.99 | 5D |  |
| MP12 | mpox | Pediatric CFR | official_trial_result_final | 11.00 (4.00-20.00) % | 10.46 (7.74-13.17) % | 3.34 (0.62-6.07) % | 13 | -0.54 | -7.66 | 5D | SR point treated as 11 |
