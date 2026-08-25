# Family 6 -- Opening Information -> Later-Session Continuation -- Stage 1 Screening Summary

Question: does what happens in the first 30 minutes of RTH (13:30-14:00 UTC) carry information about the LATER session, when used purely as a signal (not traded itself)? This is NOT ORPB -- the opening window is never traded; it only produces a number that conditions a decision placed strictly after it (14:00 UTC). Forward horizons (15/30/60/120m) are measured from that 14:00 UTC decision point.

Data: DEVELOPMENT role, 35 symbols, 62 trading days (2026-05-15..2026-08-14). Definition B additionally uses the SPY benchmark CSV (data/historical_1m/task67a_benchmarks/SPY.csv), loaded directly since only its DEVELOPMENT-range data was ever materialized. Friction assumption: 5.0bps one-way / 10.0bps round-trip.

**Family rollup:** 3/3 PHENOMENON_PRESENT, 0/3 WEAK_SIGNAL, 0/3 PHENOMENON_NOT_OBSERVED, 0/3 INSUFFICIENT_DATA -- definitions are NOT averaged into one number; each is reported independently, per the brief.

## Continuation vs. mean-reversion (definition A)

Definition A's 60m excess forward return is NEGATIVE (-0.1561%), i.e. strong opens tend to MEAN-REVERT (reversal) into the later session, on this dataset/definition.

## Relative (definition B) vs. absolute (definition A) opening strength

Definition A (absolute) 60m excess = -0.1561%; Definition B (relative-to-SPY) 60m excess = -0.1291%. The larger-magnitude excess is definition A (absolute)'s -- see summary.md's side-by-side table for the full horizon comparison and each definition's verdict/economic classification before drawing any conclusion about which (if either) is the cleaner effect.

## Definition: `opening_return_magnitude`

Signal = symbol's own 13:30->14:00 UTC opening-to-close return of the opening window. Condition: |signal| >= global top-tertile cutoff of |signal| across the dataset. Direction = sign(signal). Decision timestamp = first bar at/after 14:00 UTC. Tests continuation vs. mean-reversion of a strong ABSOLUTE opening move into the later session.

- Dedup: group_keys=['symbol'], min_gap_minutes=1200
- Raw events: 735 -> Deduplicated events: 735 (symbols=35, days=63)
- Economic classification: **POTENTIALLY_TRADEABLE**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: False (3 populated cells (n>=5): same_sign_frac=0.67 (overall sign=-), max|mean|/median|mean|=1.19.)
- MFE median (%, at max horizon): 0.9459653146051263; MAE median (%): 1.0490463215258994

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 735 | 735 | -0.0263 | 0.0498 | -0.076 | [-0.1443, -0.0047] | 0.482 |
| 30m | 735 | 735 | 0.0218 | 0.0714 | -0.0496 | [-0.1490, 0.0490] | 0.499 |
| 60m | 735 | 735 | -0.0779 | 0.0782 | -0.1561 | [-0.2838, -0.0306] | 0.472 |
| 120m | 735 | 735 | -0.0875 | 0.087 | -0.1745 | [-0.3026, -0.0428] | 0.459 |

### VERDICT: **PHENOMENON_PRESENT**

Coherent direction across horizons, matched-control support present, non-trivial economic scale, adequate event count/breadth (temporal AND symbol), stable effect surface, and the clustered-bootstrap CI for excess excludes zero.

Main weakness: Checks failing: asymmetric_mfe_mae

## Definition: `opening_relative_strength_vs_spy`

Signal = symbol's opening-30m return MINUS SPY's opening-30m return, same day (simple raw relative strength, deliberately simpler than a beta-adjusted approach). Condition: |signal| >= global top-tertile cutoff of |signal|. Direction = sign(signal). Decision timestamp = first bar at/after 14:00 UTC. Tests whether RELATIVE (vs. SPY), not absolute, opening strength carries continuation information -- compare against definition A in summary.md.

- Dedup: group_keys=['symbol'], min_gap_minutes=1200
- Raw events: 735 -> Deduplicated events: 735 (symbols=35, days=63)
- Economic classification: **POTENTIALLY_TRADEABLE**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: False (3 populated cells (n>=5): same_sign_frac=0.67 (overall sign=-), max|mean|/median|mean|=1.49.)
- MFE median (%, at max horizon): 0.9162560288601129; MAE median (%): 0.9971194327498243

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 735 | 735 | -0.0139 | 0.0915 | -0.1053 | [-0.1895, -0.0155] | 0.483 |
| 30m | 735 | 735 | 0.0437 | 0.0922 | -0.0484 | [-0.1638, 0.0595] | 0.509 |
| 60m | 735 | 735 | -0.0486 | 0.0805 | -0.1291 | [-0.2463, -0.0061] | 0.475 |
| 120m | 735 | 735 | -0.0793 | 0.1124 | -0.1917 | [-0.3226, -0.0570] | 0.465 |

### VERDICT: **PHENOMENON_PRESENT**

Coherent direction across horizons, matched-control support present, non-trivial economic scale, adequate event count/breadth (temporal AND symbol), stable effect surface, and the clustered-bootstrap CI for excess excludes zero.

Main weakness: Checks failing: asymmetric_mfe_mae

## Definition: `opening_relative_volume`

Signal = symbol's opening-30m cumulative volume / that symbol's leave-one-day-out median opening-30m volume (median computed from all OTHER DEVELOPMENT days for that symbol). Condition: relative_volume >= global top-tertile cutoff. Direction = sign of that SAME day's opening-30m return (definition A's signal) -- an explicitly documented simplification conflating volume-magnitude (condition) with direction-source (borrowed from A). Decision timestamp = first bar at/after 14:00 UTC.

- Dedup: group_keys=['symbol'], min_gap_minutes=1200
- Raw events: 731 -> Deduplicated events: 731 (symbols=35, days=63)
- Economic classification: **POTENTIALLY_TRADEABLE**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: False (3 populated cells (n>=5): same_sign_frac=1.00 (overall sign=-), max|mean|/median|mean|=1.11.)
- MFE median (%, at max horizon): 0.8273532152842502; MAE median (%): 0.982891842970877

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI | positive freq |
|---|---|---|---|---|---|---|---|
| 15m | 731 | 731 | -0.0654 | 0.0902 | -0.1556 | [-0.2188, -0.0955] | 0.469 |
| 30m | 731 | 731 | -0.0161 | 0.0871 | -0.1031 | [-0.1750, -0.0320] | 0.492 |
| 60m | 731 | 731 | -0.0828 | 0.0651 | -0.1479 | [-0.2664, -0.0283] | 0.468 |
| 120m | 731 | 731 | -0.1006 | 0.0298 | -0.1305 | [-0.2646, -0.0022] | 0.462 |

### VERDICT: **PHENOMENON_PRESENT**

Coherent direction across horizons, matched-control support present, non-trivial economic scale, adequate event count/breadth (temporal AND symbol), stable effect surface, and the clustered-bootstrap CI for excess excludes zero.

Main weakness: Checks failing: asymmetric_mfe_mae
