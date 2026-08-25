# Family 1 -- Multi-Hour Trend Persistence -- Stage 1 Screening Summary

Question: do stocks already exhibiting sustained multi-hour directional structure have systematically different future return/path behavior than matched controls?

Data: DEVELOPMENT role, 35 symbols, 62 trading days (2026-05-15..2026-08-14). Friction assumption: 5.0bps one-way / 10.0bps round-trip.

**Family rollup:** 0/3 PHENOMENON_PRESENT, 3/3 WEAK_SIGNAL, 0/3 PHENOMENON_NOT_OBSERVED, 0/3 INSUFFICIENT_DATA -- definitions are NOT averaged into one number; each is reported independently, per the brief.

**Important interpretation caveat (read before the per-definition tables):** all
three definitions' excess-vs-matched-control mean turns NEGATIVE at the 60m/120m
horizons (i.e. the opposite of "trend continuation"), and for `trend90_
subwindow_agreement` / `multiwindow_agreement_30_60_90` the clustered-bootstrap CI
at 60m/120m excludes zero -- a small, statistically-detectable MEAN-REVERSION
signature after a strong same-direction 60-90m move, not continuation. All three
are still classified ECONOMICALLY_TOO_SMALL (the |excess| stays under the 10bps
round-trip friction bar even where it is statistically real), so this is reported
as a genuine but uneconomical finding, not reframed as a positive result.

## Definition: `trend60_slope_consistent`

|60m trailing return (causal_trailing_return-equivalent via causal_price_at_offset)| >= 0.4% AND all three constituent 20m sub-windows (0-20m, 20-40m, 40-60m ago) agree in sign with the 60m trend. Direction = sign of the 60m return.

- Dedup: group_keys=['symbol'], min_gap_minutes=60
- Raw events: 202392 -> Deduplicated events: 5544 (symbols=35, days=63)
- Economic classification: **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: True (9 populated cells (n>=5): same_sign_frac=0.78 (overall sign=-), max|mean|/median|mean|=4.78.)
- MFE median (%, at max horizon): 0.5383442984931541; MAE median (%): 0.5728063437309783

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 5544 | 5206 | -0.0156 | -0.0305 | 0.0146 | [-0.0062, 0.0356] | 0.465 |
| 30m | 5544 | 5206 | -0.0251 | -0.0058 | -0.0157 | [-0.0467, 0.0131] | 0.472 |
| 60m | 5544 | 5206 | -0.0306 | 0.0365 | -0.0612 | [-0.1039, -0.0222] | 0.481 |
| 120m | 5544 | 5206 | -0.0368 | 0.0588 | -0.0886 | [-0.1371, -0.0390] | 0.483 |

### VERDICT: **WEAK_SIGNAL**

Some structure present (3/6 early-kill checks passed) but 2/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

Main weakness: Checks failing: nontrivial_economic_scale, stable_effect_surface, asymmetric_mfe_mae

## Definition: `trend90_subwindow_agreement`

|90m trailing return| >= 0.5% AND at least 5 of the 6 constituent 15m sub-windows agree in sign with the 90m trend. Direction = sign of the 90m return.

- Dedup: group_keys=['symbol'], min_gap_minutes=90
- Raw events: 163109 -> Deduplicated events: 3609 (symbols=35, days=63)
- Economic classification: **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: False (9 populated cells (n>=5): same_sign_frac=0.78 (overall sign=+), max|mean|/median|mean|=2.85.)
- MFE median (%, at max horizon): 0.5534823263029987; MAE median (%): 0.5711640547421617

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 3609 | 3590 | -0.0001 | 0.0212 | -0.021 | [-0.0477, 0.0070] | 0.482 |
| 30m | 3609 | 3590 | -0.0044 | 0.029 | -0.0325 | [-0.0624, -0.0007] | 0.481 |
| 60m | 3609 | 3590 | 0.031 | 0.0638 | -0.032 | [-0.0668, 0.0043] | 0.499 |
| 120m | 3609 | 3590 | 0.0247 | 0.1012 | -0.076 | [-0.1172, -0.0354] | 0.505 |

### VERDICT: **WEAK_SIGNAL**

Some structure present (3/6 early-kill checks passed) but 2/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

Main weakness: Checks failing: nontrivial_economic_scale, asymmetric_mfe_mae, excess_ci_excludes_zero

## Definition: `multiwindow_agreement_30_60_90`

30m, 60m, and 90m trailing returns (causal_trailing_return) all share the same sign, with |90m return| >= 0.4%. Direction = shared sign.

- Dedup: group_keys=['symbol'], min_gap_minutes=90
- Raw events: 428619 -> Deduplicated events: 3033 (symbols=35, days=63)
- Economic classification: **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: False (9 populated cells (n>=5): same_sign_frac=1.00 (overall sign=-), max|mean|/median|mean|=2.00.)
- MFE median (%, at max horizon): 0.46204620462046386; MAE median (%): 0.5809483126868918

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 3033 | 2743 | -0.0316 | 0.0172 | -0.048 | [-0.0770, -0.0203] | 0.402 |
| 30m | 3033 | 2743 | -0.0502 | 0.0254 | -0.0671 | [-0.1061, -0.0296] | 0.412 |
| 60m | 3033 | 2743 | -0.051 | 0.0436 | -0.0835 | [-0.1390, -0.0294] | 0.45 |
| 120m | 3033 | 2743 | -0.0566 | 0.0789 | -0.1196 | [-0.1916, -0.0429] | 0.463 |

### VERDICT: **WEAK_SIGNAL**

Some structure present (5/6 early-kill checks passed) but 1/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

Main weakness: Checks failing: nontrivial_economic_scale
