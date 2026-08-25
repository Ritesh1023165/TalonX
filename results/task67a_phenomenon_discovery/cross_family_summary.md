# Task 67B - Cross-Family Synthesis

## Family comparison (representative definition per family)

| Family | Verdict | Econ | n_dedup | symbols | days | evt/wk | unstable? | top1 sym share | excess 60m [CI] |
|---|---|---|---|---|---|---|---|---|---|
| F1 Multi-Hour Trend | WEAK_SIGNAL | ECONOMICALLY_TOO_SMALL | 5544 | 35 | 63 | 447.1 | True | 0.046 | -0.0612 [-0.1039, -0.0222] |
| F2 Structural Pullback | WEAK_SIGNAL | POTENTIALLY_TRADEABLE | 7481 | 35 | 63 | 603.3 | True | 0.056 | -0.1008 [-0.1365, -0.0623] |
| F3 Range Expansion | WEAK_SIGNAL | STRONG_EFFECT | 76 | 24 | 32 | 6.1 | True | 0.167 | 0.2582 [0.0677, 0.5147] |
| F4 Relative Strength | WEAK_SIGNAL | ECONOMICALLY_TOO_SMALL | 2208 | 35 | 32 | 175.2 | False | 0.062 | 0.0636 [0.0255, 0.1043] |
| F5 Compression->Expansion | PHENOMENON_NOT_OBSERVED | ECONOMICALLY_TOO_SMALL | 5811 | 35 | 63 | 468.6 | True | 0.053 | -0.0393 [-0.0743, -0.0071] |
| F6 Opening->Later | PHENOMENON_PRESENT | POTENTIALLY_TRADEABLE | 735 | 35 | 63 | 59.3 | False | 0.093 | -0.1561 [-0.2838, -0.0306] |

## Ranking (composite score, method documented in phenomenon_ranking.json)

| Rank | Family | Verdict tier | Econ tier | Breadth | Stability | Concentration | Composite |
|---|---|---|---|---|---|---|---|
| 1 | F6 Opening->Later | 3 | 2 | 1.0 | 1.0 | 0.907 | 17.907 |
| 2 | F3 Range Expansion | 2 | 3 | 0.597 | 0.0 | 0.833 | 14.027 |
| 3 | F2 Structural Pullback | 2 | 2 | 1.0 | 0.0 | 0.944 | 12.944 |
| 4 | F4 Relative Strength | 2 | 1 | 0.754 | 1.0 | 0.938 | 12.446 |
| 5 | F1 Multi-Hour Trend | 2 | 1 | 1.0 | 0.0 | 0.954 | 10.954 |
| 6 | F5 Compression->Expansion | 1 | 1 | 1.0 | 0.0 | 0.947 | 7.947 |

## Redundant family pairs (>40% same-symbol-TIME overlap, 5-min tolerance)

Same-symbol-DAY overlap is NOT used for this flag -- with only 63 DEVELOPMENT trading days and several families firing thousands of events across nearly every symbol, day-level overlap is close to saturated (frequently >=0.99 in one direction) for purely combinatorial reasons and says little about whether two families detect the same episodes. Same-symbol-TIME overlap (is family A firing within 5 minutes of family B, not just on the same calendar day) is the meaningful signal.

| family_a | family_b | a_covered_by_b_time_frac | b_covered_by_a_time_frac |
|---|---|---|---|
| F4 Relative Strength | F6 Opening->Later | 0.1644021739130435 | 0.49387755102040815 |
| F5 Compression->Expansion | F6 Opening->Later | 0.05799346067802444 | 0.45850340136054424 |

## Event overlap matrix (full, 5-minute same-symbol-time tolerance)

| family_a | family_b | n_events_a | n_events_b | a_covered_by_b_time_frac | b_covered_by_a_time_frac | a_covered_by_b_day_frac | b_covered_by_a_day_frac |
|---|---|---|---|---|---|---|---|
| F1 Multi-Hour Trend | F2 Structural Pullback | 5544 | 7481 | 0.145 | 0.107 | 1.0 | 1.0 |
| F1 Multi-Hour Trend | F3 Range Expansion | 5544 | 76 | 0.001 | 0.105 | 0.031 | 1.0 |
| F1 Multi-Hour Trend | F4 Relative Strength | 5544 | 2208 | 0.042 | 0.106 | 0.494 | 1.0 |
| F1 Multi-Hour Trend | F5 Compression->Expansion | 5544 | 5811 | 0.062 | 0.059 | 1.0 | 1.0 |
| F1 Multi-Hour Trend | F6 Opening->Later | 5544 | 735 | 0.008 | 0.059 | 0.332 | 1.0 |
| F2 Structural Pullback | F3 Range Expansion | 7481 | 76 | 0.0 | 0.013 | 0.03 | 1.0 |
| F2 Structural Pullback | F4 Relative Strength | 7481 | 2208 | 0.034 | 0.115 | 0.494 | 1.0 |
| F2 Structural Pullback | F5 Compression->Expansion | 7481 | 5811 | 0.114 | 0.146 | 1.0 | 0.999 |
| F2 Structural Pullback | F6 Opening->Later | 7481 | 735 | 0.02 | 0.199 | 0.369 | 1.0 |
| F3 Range Expansion | F4 Relative Strength | 76 | 2208 | 0.105 | 0.004 | 0.434 | 0.026 |
| F3 Range Expansion | F5 Compression->Expansion | 76 | 5811 | 0.0 | 0.0 | 1.0 | 0.035 |
| F3 Range Expansion | F6 Opening->Later | 76 | 735 | 0.0 | 0.0 | 0.184 | 0.019 |
| F4 Relative Strength | F5 Compression->Expansion | 2208 | 5811 | 0.182 | 0.069 | 1.0 | 0.482 |
| F4 Relative Strength | F6 Opening->Later | 2208 | 735 | 0.164 | 0.494 | 0.381 | 0.518 |
| F5 Compression->Expansion | F6 Opening->Later | 5811 | 735 | 0.058 | 0.459 | 0.326 | 1.0 |