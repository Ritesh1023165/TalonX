# Family 2 -- Structural Pullback -- Screening Spec

Task 67B Step 2. Stage 1 phenomenon-discovery screening, DEVELOPMENT data only
(35 symbols, 2026-05-15..2026-08-14, ~62 trading days). Read-only, exploratory --
NOT a trading engine, NOT a backtest, NOT strategy freezing.

Question: after a strong directional move followed by a controlled retracement
that preserves broader structure, does continuation occur more than in matched
controls?

## Definitions

All three definitions are simple two/three-timestamp comparisons using
`causal_price_at_offset` (and, for definition B, `causal_session_vwap`) -- no
full state-machine, no true peak-detection, per the brief's "keep definitions
simple and causal" instruction.

### A) `strong_move90_shallow_retrace20`
Let `p0` = price now, `p_retrace` = price 20m ago, `p_base` = price 90m ago.
`prior_move = (p_retrace - p_base) / p_base` (the "strong move", measured over
t-90m..t-20m). `giveback = (p0 - p_retrace) / p_retrace` (the retracement,
measured over t-20m..t). Condition: `|prior_move| >= 0.6%` AND
`sign(giveback) == -sign(prior_move)` (a genuine pullback, not a continued
extension in the same direction) AND `|giveback| <= 0.5 * |prior_move|` (shallow
giveback -- retraced no more than half the prior move). Direction = sign of
`prior_move` (tests CONTINUATION after the pullback).

### B) `pullback_toward_vwap_holds`
Same `p0`/`p_retrace` (15m ago)/`p_base` (60m ago) structure, `prior_move`
computed the same way, threshold `|prior_move| >= 0.5%`. Additionally requires
the causal session VWAP (`causal_session_vwap`, evaluated now) to have held as a
structural reference: for an up-move (`prior_move > 0`), require
`p_retrace > vwap_now` (the move happened above VWAP) AND
`vwap_now <= p0 < p_retrace` (price has pulled back off the recent high but has
NOT crossed below VWAP); the down-move case is the mirror image. Direction =
sign of `prior_move`.

### C) `strong_move45_shallow_retrace10`
Same shape as (A) at a coarser/faster timeframe: prior move over t-45m..t-10m,
`|prior_move| >= 0.4%`; retracement over t-10m..t opposite in sign and
`<= 0.6 * |prior_move|` (a slightly more permissive giveback ratio than (A),
appropriate to the shorter/noisier timeframe).

All three additionally require >=15 minutes of same-day room before RTH close
(`_min_lead_filter`).

## De-duplication

`research_stats.dedup_events`, `group_keys=["symbol"]`, `keep="first"`.
`min_gap_minutes`: 60 (A), 45 (B), 30 (C) -- roughly the base-window length,
same rationale as Family 1: once the pattern is true it typically stays true on
consecutive bars as price continues its shallow drift, so collapsing a
gap-bounded run into one representative event avoids counting dozens of
near-identical re-triggers as independent occurrences.

## Matched-control construction

Identical mechanism to Family 1: `sample_control_candidates` (stride 20m,
exclusion buffer 60m, warmup 90m, min lead 15m) builds the control pool;
`matched_control_sample` stratifies both events and controls by `["symbol",
"time_of_day_bucket", "vol_bucket"]` and greedily nearest-time-pairs one control
per event within each populated stratum
(`family_runner.build_control_events_from_pairs`); the paired control borrows
its matched event's direction (a control has no direction of its own); excess =
per-matched-pair difference in direction-adjusted forward return, clustered
(by symbol) bootstrapped for a 95% CI.

## Seeds

`DEFAULT_SEED = 670067` + `FAMILY_SEED_OFFSET = 200` (family 2) + definition
index (0/1/2), plus the per-horizon clustered bootstrap adds the horizon's
minute count. Exact per-definition seeds recorded in definitions.json /
summary.json.

## Economic friction assumption

`screening_framework.ONE_WAY_FRICTION_BPS = 5.0`,
`ROUND_TRIP_FRICTION_BPS = 10.0` (module constants, unchanged).
`classify_economic_magnitude` is MAGNITUDE-ONLY (it does not look at sign) --
see summary.md's interpretation caveat: two of this family's three definitions
classify as POTENTIALLY_TRADEABLE by |excess| magnitude alone, but the excess's
SIGN is the opposite of the hypothesized continuation effect (a mean-reversion-
relative-to-control pattern, not continuation). This is reported explicitly
rather than let the classification label alone imply a positive result.

## Effect-surface stability check

Same mechanism as Family 1: `effect_surface` over `trailing_vol_60m` x
`minutes_of_day` (tertile-binned) on the 60m-horizon direction-adjusted forward
return; `EFFECT_SURFACE_INSTABILITY` flagged on the same same-sign/isolated-
spike heuristic in `family_runner.py`. All three definitions in this family ARE
flagged unstable (same_sign_frac 0.44 in all three cases -- fewer than half of
the populated vol/time-of-day cells share the population-weighted overall
sign), which is itself informative: whatever effect exists here is not broadly
shared across volatility/time-of-day regimes.

## Verdict

Same taxonomy and threshold set as Family 1 (documented once in
`family_runner.py`, applied identically across all three families 1-3).
