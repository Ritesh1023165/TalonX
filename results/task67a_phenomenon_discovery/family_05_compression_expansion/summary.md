# Family 5 -- Compression -> Expansion (Precondition) -- Stage 1 Screening Summary

Question: does sitting in a compressed volatility state predict LATER unusually large movement and/or directional persistence, evaluated at horizons AFTER the compressed bar -- with NO requirement that expansion has already begun? (later-session/general-session only; first 30m of RTH explicitly excluded -- ORPB territory, out of scope.)

Data: DEVELOPMENT role, 35 symbols, 62 trading days (2026-05-15..2026-08-14). Friction assumption: 5.0bps one-way / 10.0bps round-trip. Primary horizon: 60m.

**Direction convention:** PRIMARY analysis is UNSIGNED (does compression predict expanded absolute movement?) -- own max(high)-min(low)-over-horizon statistic vs. matched controls. SECONDARY analysis is SIGNED (does a weak recent-drift-direction signal, sign of the 15m trailing return as of the compressed bar, predict the signed forward return?) -- run through the standard pipeline. Both are reported; VOLATILITY_EFFECT_PRESENT with DIRECTIONAL_EDGE_NOT_OBSERVED is an explicitly expected, valid outcome (compression can expand the range of outcomes without making the sign predictable), not a failure.

**Family rollup (standard verdict, secondary/signed analysis):** 0/3 PHENOMENON_PRESENT, 0/3 WEAK_SIGNAL, 3/3 PHENOMENON_NOT_OBSERVED, 0/3 INSUFFICIENT_DATA -- definitions are NOT averaged into one number; each is reported independently, per the brief. Standard verdicts are computed on the SECONDARY (signed/directional) analysis; the volatility-effect (primary/unsigned) and directional-edge flags are reported separately per definition below.

**Flag rollup:** Volatility-effect: 0/3 PRESENT, 3/3 NOT_OBSERVED. Directional-edge: 0/3 PRESENT, 3/3 NOT_OBSERVED.

## Definition: `persistent_compression_atr30_persist30`

Trailing 30m ATR proxy (bottom global tertile as a fraction of price) held CONTINUOUSLY for the entire trailing 30 minutes (every bar in the window individually below the tertile cutoff, not just the window average). No requirement that expansion has begun. Direction (secondary/weak signal) = sign of the 15m trailing return as of the compressed bar. Excludes first 30m of RTH.

- Dedup: group_keys=['symbol'], min_gap_minutes=30
- Raw events: 102621 -> Deduplicated events: 1230 (symbols=28, days=63)
- SECONDARY (signed) economic classification: **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: False (9 populated cells (n>=5): same_sign_frac=0.56 (overall sign=+), max|mean|/median|mean|=2.94.)
- MFE median (%, at max horizon): 0.3015463063670163; MAE median (%): 0.299245625628187

### Secondary (signed, directional) per-horizon results

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 1230 | 1047 | -0.0026 | 0.0061 | -0.0097 | [-0.0264, 0.0059] | 0.48 |
| 30m | 1230 | 1047 | 0.003 | -0.0018 | 0.0023 | [-0.0176, 0.0256] | 0.502 |
| 60m | 1230 | 1047 | 0.0024 | 0.0035 | 0.0034 | [-0.0236, 0.0354] | 0.496 |
| 120m | 1230 | 1047 | -0.0141 | 0.0133 | -0.012 | [-0.0462, 0.0234] | 0.48 |

### Primary (unsigned, volatility-effect) per-horizon results -- economic classification: **ECONOMICALLY_TOO_SMALL**; abs-range median at max horizon: 0.6933235907177382

| Horizon | n events | n matched pairs | raw mean abs-range % | matched control mean abs-range % | excess mean abs-range % | excess 95% CI |
|---|---|---|---|---|---|---|
| 15m | 1230 | 1047 | 0.2713 | 0.2783 | -0.0068 | [-0.0305, 0.0120] |
| 30m | 1230 | 1047 | 0.3839 | 0.4163 | -0.0357 | [-0.0688, -0.0094] |
| 60m | 1230 | 1047 | 0.5577 | 0.5661 | -0.0083 | [-0.0572, 0.0275] |
| 120m | 1230 | 1047 | 0.7701 | 0.7452 | 0.0115 | [-0.0422, 0.0552] |

### VERDICT (standard taxonomy, secondary/signed analysis): **PHENOMENON_NOT_OBSERVED**

4/6 early-kill checks failed (near-zero/incoherent excess effect, unstable effect surface, non-asymmetric MFE/MAE, high concentration, or a clustered-bootstrap CI for excess that straddles zero) -- most of the early-kill checklist holds, so this definition is treated as PHENOMENON_NOT_OBSERVED rather than cherry-picked into a weaker positive verdict.

Main weakness: Checks failing: coherent_direction, nontrivial_economic_scale, asymmetric_mfe_mae, excess_ci_excludes_zero

### VOLATILITY_EFFECT flag: **VOLATILITY_EFFECT_NOT_OBSERVED**  |  DIRECTIONAL_EDGE flag: **DIRECTIONAL_EDGE_NOT_OBSERVED**

## Definition: `relative_narrow_range_15v90`

Current 15m rolling high-low range pace (range/15) divided by the SAME symbol's own trailing 90m high-low range pace (range/90) -- a per-symbol-normalized ratio -- in the bottom global tertile. Tests whether the recent window is narrow relative to what THIS symbol itself has typically been doing, not an absolute range threshold. Direction (secondary/weak signal) = sign of the 15m trailing return. Excludes first 30m of RTH.

- Dedup: group_keys=['symbol'], min_gap_minutes=30
- Raw events: 264620 -> Deduplicated events: 5811 (symbols=35, days=63)
- SECONDARY (signed) economic classification: **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: True (9 populated cells (n>=5): same_sign_frac=0.56 (overall sign=-), max|mean|/median|mean|=7.28.)
- MFE median (%, at max horizon): 0.5125072331983215; MAE median (%): 0.493448631039343

### Secondary (signed, directional) per-horizon results

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 5811 | 4545 | 0.0068 | -0.0021 | 0.0044 | [-0.0167, 0.0232] | 0.511 |
| 30m | 5811 | 4545 | 0.0186 | 0.0068 | 0.0037 | [-0.0197, 0.0261] | 0.515 |
| 60m | 5811 | 4545 | -0.0011 | 0.0313 | -0.0393 | [-0.0743, -0.0071] | 0.508 |
| 120m | 5811 | 4545 | 0.0039 | 0.0353 | -0.0322 | [-0.0681, 0.0041] | 0.504 |

### Primary (unsigned, volatility-effect) per-horizon results -- economic classification: **ECONOMICALLY_TOO_SMALL**; abs-range median at max horizon: 1.1866442469373042

| Horizon | n events | n matched pairs | raw mean abs-range % | matched control mean abs-range % | excess mean abs-range % | excess 95% CI |
|---|---|---|---|---|---|---|
| 15m | 5811 | 4545 | 0.6123 | 0.5501 | -0.0032 | [-0.0144, 0.0087] |
| 30m | 5811 | 4545 | 0.8544 | 0.7607 | 0.0072 | [-0.0059, 0.0219] |
| 60m | 5811 | 4545 | 1.1499 | 1.0403 | 0.006 | [-0.0163, 0.0278] |
| 120m | 5811 | 4545 | 1.4895 | 1.3416 | 0.0344 | [0.0077, 0.0639] |

### VERDICT (standard taxonomy, secondary/signed analysis): **PHENOMENON_NOT_OBSERVED**

4/6 early-kill checks failed (near-zero/incoherent excess effect, unstable effect surface, non-asymmetric MFE/MAE, high concentration, or a clustered-bootstrap CI for excess that straddles zero) -- most of the early-kill checklist holds, so this definition is treated as PHENOMENON_NOT_OBSERVED rather than cherry-picked into a weaker positive verdict.

Main weakness: Checks failing: coherent_direction, nontrivial_economic_scale, stable_effect_surface, asymmetric_mfe_mae

### VOLATILITY_EFFECT flag: **VOLATILITY_EFFECT_NOT_OBSERVED**  |  DIRECTIONAL_EDGE flag: **DIRECTIONAL_EDGE_NOT_OBSERVED**

## Definition: `declining_compression_atr30_lag30`

Current causal 30m ATR proxy < the same measure evaluated ~30 minutes earlier (same-day causal lookback), AND both values below the global median as a fraction of price -- compression is DEEPENING, not merely present. Direction (secondary/weak signal) = sign of the 15m trailing return. Excludes first 30m of RTH.

- Dedup: group_keys=['symbol'], min_gap_minutes=30
- Raw events: 148284 -> Deduplicated events: 2788 (symbols=33, days=63)
- SECONDARY (signed) economic classification: **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: False (9 populated cells (n>=5): same_sign_frac=0.56 (overall sign=+), max|mean|/median|mean|=2.70.)
- MFE median (%, at max horizon): 0.32891643469106335; MAE median (%): 0.3448659231969246

### Secondary (signed, directional) per-horizon results

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 2788 | 2582 | 0.0052 | -0.0047 | 0.0099 | [-0.0007, 0.0213] | 0.497 |
| 30m | 2788 | 2582 | 0.0041 | -0.0041 | 0.0099 | [-0.0059, 0.0266] | 0.49 |
| 60m | 2788 | 2582 | 0.0005 | 0.013 | -0.0136 | [-0.0355, 0.0083] | 0.492 |
| 120m | 2788 | 2582 | -0.0045 | 0.0351 | -0.0421 | [-0.0694, -0.0113] | 0.487 |

### Primary (unsigned, volatility-effect) per-horizon results -- economic classification: **POTENTIALLY_TRADEABLE**; abs-range median at max horizon: 0.7708017692494601

| Horizon | n events | n matched pairs | raw mean abs-range % | matched control mean abs-range % | excess mean abs-range % | excess 95% CI |
|---|---|---|---|---|---|---|
| 15m | 2788 | 2582 | 0.3174 | 0.4203 | -0.1012 | [-0.1135, -0.0890] |
| 30m | 2788 | 2582 | 0.4543 | 0.5939 | -0.1358 | [-0.1540, -0.1173] |
| 60m | 2788 | 2582 | 0.6454 | 0.777 | -0.1264 | [-0.1545, -0.0970] |
| 120m | 2788 | 2582 | 0.8711 | 0.985 | -0.1077 | [-0.1370, -0.0763] |

### VERDICT (standard taxonomy, secondary/signed analysis): **PHENOMENON_NOT_OBSERVED**

4/6 early-kill checks failed (near-zero/incoherent excess effect, unstable effect surface, non-asymmetric MFE/MAE, high concentration, or a clustered-bootstrap CI for excess that straddles zero) -- most of the early-kill checklist holds, so this definition is treated as PHENOMENON_NOT_OBSERVED rather than cherry-picked into a weaker positive verdict.

Main weakness: Checks failing: coherent_direction, nontrivial_economic_scale, asymmetric_mfe_mae, excess_ci_excludes_zero

### VOLATILITY_EFFECT flag: **VOLATILITY_EFFECT_NOT_OBSERVED**  |  DIRECTIONAL_EDGE flag: **DIRECTIONAL_EDGE_NOT_OBSERVED**
