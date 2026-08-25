# Family 2 -- Structural Pullback -- Stage 1 Screening Summary

Question: after a strong directional move followed by a controlled retracement that preserves broader structure, does continuation occur more than in matched controls?

Data: DEVELOPMENT role, 35 symbols, 62 trading days (2026-05-15..2026-08-14). Friction assumption: 5.0bps one-way / 10.0bps round-trip.

**Family rollup:** 0/3 PHENOMENON_PRESENT, 3/3 WEAK_SIGNAL, 0/3 PHENOMENON_NOT_OBSERVED, 0/3 INSUFFICIENT_DATA -- definitions are NOT averaged into one number; each is reported independently, per the brief.

**Important interpretation caveat (read before the per-definition tables):** for
all three definitions, the excess-vs-matched-control mean is **NEGATIVE** at the
60m/120m horizons (`[-0.15, -0.08]` excess, CI excluding zero) -- i.e. the effect
that clears the economic-magnitude bar is the OPPOSITE of the hypothesized
"shallow pullback preserves structure -> continuation" effect. Matched controls
(same symbol/time-of-day/vol regime, borrowing the paired event's direction, but
NOT conditioned on the shallow-pullback pattern) show a STRONGER positive
direction-adjusted forward return than the actual pullback events do. In plain
terms: buying/shorting a strong move's continuation right after a shallow,
structure-preserving pullback underperforms an otherwise-similar random entry in
the same direction -- a mild momentum-exhaustion / mean-reversion-relative-to-
control signature, not a continuation edge. `classify_economic_magnitude` is
magnitude-only (does not look at sign), so "POTENTIALLY_TRADEABLE" here should be
read as "the |excess| clears the friction bar," NOT as "the continuation
hypothesis is confirmed and tradeable in the hypothesized direction." This is
reported in full rather than reframed, per the brief's "preserve negative/weak
results" instruction.

## Definition: `strong_move90_shallow_retrace20`

Prior move over t-90m..t-20m has |return| >= 0.6%; retracement over t-20m..t (now) is OPPOSITE in sign (genuine pullback, not a continued extension) and its magnitude is <= 50% of the prior move's magnitude (shallow giveback, structure preserved). Direction = sign of the prior move (tests continuation after the pullback).

- Dedup: group_keys=['symbol'], min_gap_minutes=60
- Raw events: 146116 -> Deduplicated events: 5084 (symbols=35, days=63)
- Economic classification: **POTENTIALLY_TRADEABLE**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: True (9 populated cells (n>=5): same_sign_frac=0.44 (overall sign=-), max|mean|/median|mean|=1.92.)
- MFE median (%, at max horizon): 0.5870576592286045; MAE median (%): 0.5805055934435859

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 5084 | 4743 | 0.0028 | 0.0222 | -0.0195 | [-0.0485, 0.0022] | 0.49 |
| 30m | 5084 | 4743 | 0.0022 | 0.0572 | -0.0532 | [-0.0876, -0.0240] | 0.494 |
| 60m | 5084 | 4743 | -0.003 | 0.1406 | -0.1473 | [-0.1916, -0.1065] | 0.5 |
| 120m | 5084 | 4743 | -0.024 | 0.1321 | -0.1576 | [-0.2101, -0.1117] | 0.496 |

### VERDICT: **WEAK_SIGNAL**

Some structure present (4/6 early-kill checks passed) but 1/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

Main weakness: Checks failing: stable_effect_surface, asymmetric_mfe_mae

## Definition: `pullback_toward_vwap_holds`

Prior move over t-60m..t-15m has |return| >= 0.5%, moving away from the causal session VWAP; price has since pulled back from the t-15m extreme toward VWAP but has NOT crossed back through it (VWAP held as a structural reference level). Direction = sign of the prior move.

- Dedup: group_keys=['symbol'], min_gap_minutes=45
- Raw events: 126137 -> Deduplicated events: 7481 (symbols=35, days=63)
- Economic classification: **POTENTIALLY_TRADEABLE**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: True (9 populated cells (n>=5): same_sign_frac=0.44 (overall sign=+), max|mean|/median|mean|=3.17.)
- MFE median (%, at max horizon): 0.5971769815417993; MAE median (%): 0.5678083170580585

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 7481 | 6203 | 0.0137 | -0.0101 | 0.0227 | [0.0053, 0.0390] | 0.505 |
| 30m | 7481 | 6203 | 0.0036 | 0.0126 | -0.0112 | [-0.0352, 0.0152] | 0.496 |
| 60m | 7481 | 6203 | 0.004 | 0.0971 | -0.1008 | [-0.1365, -0.0623] | 0.506 |
| 120m | 7481 | 6203 | -0.0058 | 0.0794 | -0.0921 | [-0.1287, -0.0539] | 0.504 |

### VERDICT: **WEAK_SIGNAL**

Some structure present (4/6 early-kill checks passed) but 1/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

Main weakness: Checks failing: stable_effect_surface, asymmetric_mfe_mae

## Definition: `strong_move45_shallow_retrace10`

Coarser/faster-timeframe variant of definition A: prior move over t-45m..t-10m has |return| >= 0.4%; retracement over t-10m..t is opposite in sign and its magnitude is <= 60% of the prior move's magnitude. Direction = sign of the prior move.

- Dedup: group_keys=['symbol'], min_gap_minutes=30
- Raw events: 162853 -> Deduplicated events: 10215 (symbols=35, days=63)
- Economic classification: **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: True (9 populated cells (n>=5): same_sign_frac=0.44 (overall sign=+), max|mean|/median|mean|=2.21.)
- MFE median (%, at max horizon): 0.5504636186302547; MAE median (%): 0.543848348210172

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 10215 | 7459 | 0.0038 | 0.0118 | -0.0041 | [-0.0177, 0.0092] | 0.484 |
| 30m | 10215 | 7459 | 0.0014 | 0.0186 | -0.0137 | [-0.0334, 0.0058] | 0.49 |
| 60m | 10215 | 7459 | 0.0082 | 0.0756 | -0.0761 | [-0.1084, -0.0443] | 0.502 |
| 120m | 10215 | 7459 | -0.003 | 0.0816 | -0.0869 | [-0.1237, -0.0535] | 0.496 |

### VERDICT: **WEAK_SIGNAL**

Some structure present (3/6 early-kill checks passed) but 2/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

Main weakness: Checks failing: nontrivial_economic_scale, stable_effect_surface, asymmetric_mfe_mae
