# Family 3 -- Volatility / Range Expansion -- Stage 1 Screening Summary

Question: does an established intraday range followed by genuine volatility/range expansion lead to abnormal subsequent directional movement? (later-session/general-session only; first 30m of RTH explicitly excluded -- ORPB territory, out of scope.)

Data: DEVELOPMENT role, 35 symbols, 62 trading days (2026-05-15..2026-08-14). Friction assumption: 5.0bps one-way / 10.0bps round-trip.

**Family rollup:** 0/3 PHENOMENON_PRESENT, 1/3 WEAK_SIGNAL, 2/3 PHENOMENON_NOT_OBSERVED, 0/3 INSUFFICIENT_DATA -- definitions are NOT averaged into one number; each is reported independently, per the brief.

## Definition: `compression60_expansion15_2x`

Established = 60m trailing ATR proxy, evaluated 15m before now (bottom global tertile as a fraction of price). Recent = 15m trailing ATR proxy (ending now) >= 2.0x the lagged established value. Direction = sign of the 15m trailing return (breakout direction). Excludes first 30m of RTH.

- Dedup: group_keys=['symbol'], min_gap_minutes=30
- Raw events: 1139 -> Deduplicated events: 141 (symbols=25, days=49)
- Economic classification: **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: True (9 populated cells (n>=5): same_sign_frac=0.67 (overall sign=+), max|mean|/median|mean|=4.16.)
- MFE median (%, at max horizon): 0.38802545113173187; MAE median (%): 0.37872683319903216

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 141 | 141 | -0.0078 | -0.007 | -0.0008 | [-0.0708, 0.0806] | 0.418 |
| 30m | 141 | 141 | 0.0472 | 0.0094 | 0.0378 | [-0.0636, 0.1544] | 0.447 |
| 60m | 141 | 141 | 0.117 | 0.0279 | 0.0891 | [-0.0300, 0.2419] | 0.511 |
| 120m | 141 | 141 | 0.1224 | 0.1502 | -0.0278 | [-0.1263, 0.1396] | 0.468 |

### VERDICT: **PHENOMENON_NOT_OBSERVED**

5/6 early-kill checks failed (near-zero/incoherent excess effect, unstable effect surface, non-asymmetric MFE/MAE, high concentration, or a clustered-bootstrap CI for excess that straddles zero) -- most of the early-kill checklist holds, so this definition is treated as PHENOMENON_NOT_OBSERVED rather than cherry-picked into a weaker positive verdict.

Main weakness: Checks failing: coherent_direction, nontrivial_economic_scale, stable_effect_surface, asymmetric_mfe_mae, excess_ci_excludes_zero

## Definition: `compression90_expansion10_2.5x`

Established = 90m trailing ATR proxy, evaluated 10m before now (bottom global tertile). Recent = 10m trailing ATR proxy >= 2.5x the lagged established value. Direction = sign of the 10m trailing return. Excludes first 30m of RTH.

- Dedup: group_keys=['symbol'], min_gap_minutes=20
- Raw events: 461 -> Deduplicated events: 76 (symbols=24, days=32)
- Economic classification: **STRONG_EFFECT**
- Data sufficiency: **LIMITED**
- Effect surface instability flagged: True (9 populated cells (n>=5): same_sign_frac=0.67 (overall sign=+), max|mean|/median|mean|=5.66.)
- MFE median (%, at max horizon): 0.5172240591204204; MAE median (%): 0.3809829286345616

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 76 | 76 | 0.0081 | 0.0179 | -0.0098 | [-0.1405, 0.1405] | 0.395 |
| 30m | 76 | 76 | 0.1391 | 0.015 | 0.124 | [-0.0253, 0.2841] | 0.5 |
| 60m | 76 | 76 | 0.2584 | 0.0002 | 0.2582 | [0.0677, 0.5147] | 0.579 |
| 120m | 76 | 76 | 0.301 | 0.1287 | 0.1723 | [-0.0252, 0.4565] | 0.526 |

### VERDICT: **WEAK_SIGNAL**

Some structure present (5/6 early-kill checks passed) but 1/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

Main weakness: Checks failing: stable_effect_surface

## Definition: `compression45_expansion20_1.75x`

Established = 45m trailing ATR proxy, evaluated 20m before now (bottom global tertile). Recent = 20m trailing ATR proxy >= 1.75x the lagged established value. Direction = sign of the 20m trailing return. Excludes first 30m of RTH.

- Dedup: group_keys=['symbol'], min_gap_minutes=30
- Raw events: 2334 -> Deduplicated events: 262 (symbols=27, days=57)
- Economic classification: **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: False (9 populated cells (n>=5): same_sign_frac=0.78 (overall sign=+), max|mean|/median|mean|=2.19.)
- MFE median (%, at max horizon): 0.32726645065464877; MAE median (%): 0.318052097147867

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 262 | 262 | -0.0051 | 0.0013 | -0.0065 | [-0.0470, 0.0419] | 0.477 |
| 30m | 262 | 262 | 0.0216 | -0.0211 | 0.0427 | [-0.0209, 0.1100] | 0.489 |
| 60m | 262 | 262 | 0.0726 | 0.0368 | 0.0358 | [-0.0509, 0.1309] | 0.527 |
| 120m | 262 | 262 | 0.0888 | 0.1367 | -0.0479 | [-0.1519, 0.0585] | 0.515 |

### VERDICT: **PHENOMENON_NOT_OBSERVED**

4/6 early-kill checks failed (near-zero/incoherent excess effect, unstable effect surface, non-asymmetric MFE/MAE, high concentration, or a clustered-bootstrap CI for excess that straddles zero) -- most of the early-kill checklist holds, so this definition is treated as PHENOMENON_NOT_OBSERVED rather than cherry-picked into a weaker positive verdict.

Main weakness: Checks failing: coherent_direction, nontrivial_economic_scale, asymmetric_mfe_mae, excess_ci_excludes_zero
