# Family 1 -- Multi-Hour Trend Persistence -- Screening Spec

Task 67B Step 2. Stage 1 phenomenon-discovery screening, DEVELOPMENT data only
(35 symbols, 2026-05-15..2026-08-14, ~62 trading days). Read-only, exploratory --
NOT a trading engine, NOT a backtest, NOT strategy freezing.

Question: do stocks already exhibiting sustained multi-hour directional structure
have systematically different future return/path behavior than matched controls?

## Definitions

All three definitions are computed causally off `add_bar_features` output
(`research/task67a_lib/screening_framework.py`), using only same-day trailing
data (never crosses session close, never reaches into the prior session --
guaranteed by `causal_price_at_offset`/`causal_trailing_return`'s NaN-during-
warmup contract). An eligibility filter additionally requires >=15 minutes of
same-day room before RTH close (`_min_lead_filter` in the family script) so
events aren't dominated by bars with almost no forward window left.

### A) `trend60_slope_consistent`
`|60m trailing return| >= 0.4%` AND all three constituent 20-minute
sub-windows (0-20m ago, 20-40m ago, 40-60m ago) agree in sign with the 60m
trend. Direction = sign of the 60m return.

Implementation: `causal_price_at_offset` at offsets 0/20/40/60 minutes;
`ret60 = (p0-p60)/p60`; `sub1=(p0-p20)/p20`, `sub2=(p20-p40)/p40`,
`sub3=(p40-p60)/p60`; require `sign(sub1)==sign(sub2)==sign(sub3)==sign(ret60)`.

### B) `trend90_subwindow_agreement`
`|90m trailing return| >= 0.5%` AND at least 5 of the 6 constituent 15-minute
sub-windows agree in sign with the 90m trend. Direction = sign of the 90m
return.

Implementation: `causal_price_at_offset` at offsets 0/15/30/45/60/75/90
minutes; 6 consecutive sub-returns; agreement count >= 5.

### C) `multiwindow_agreement_30_60_90`
30m, 60m, and 90m trailing returns (`causal_trailing_return`) all share the
same sign, with `|90m return| >= 0.4%`. Direction = the shared sign.

None of the three implement pullback/reclaim entry logic (that is Family 2's
scope, per the brief).

## De-duplication

`research_stats.dedup_events`, `group_keys=["symbol"]`, `keep="first"`
(earliest event in a cluster is the representative). `min_gap_minutes` is set
to the definition's own defining window length (60 for A, 90 for B and C) --
the rationale: once a definition's condition is true it will typically stay
true for a stretch of consecutive bars as the trend continues (the same
underlying move re-satisfying the condition on every bar), and a gap equal to
the window length is a simple, transparent, non-tuned way to collapse "one
real multi-hour trend episode" into one representative event rather than
counting dozens of nearly-identical re-triggers. Both RAW and DEDUPLICATED
counts are reported in summary.json/summary.md for every definition.

## Matched-control construction

`screening_framework.sample_control_candidates` (stride 20 min, exclusion
buffer 60 min around any qualifying event on the same symbol, 90 min same-day
warmup exclusion, 15 min minimum lead before close) builds the candidate
control pool. `research_stats.matched_control_sample` then stratifies both
events and controls by `["symbol", "time_of_day_bucket", "vol_bucket"]` and
greedily nearest-time-pairs one control to one event within each populated
stratum (`family_runner.build_control_events_from_pairs`). The paired
control's DIRECTION is borrowed from its matched event (a control has no
direction of its own) so that "excess" is a like-for-like, direction-adjusted
comparison: `excess = event.forward_return_signed_pct - matched_control.
forward_return_signed_pct`, per matched pair, per horizon. The mean of these
per-pair excesses is clustered-bootstrapped (`bootstrap_ci_clustered`,
grouped by symbol) for a 95% CI.

Both the RAW conditional forward result (over ALL deduplicated events, not
just the matched subset) and the EXCESS-vs-matched-control result (over the
matched subset only, with a reported match rate) are in horizon_metrics.csv /
matched_control_metrics.csv / summary.json.

## Seeds

`DEFAULT_SEED = 670067` (research_stats.py) + `FAMILY_SEED_OFFSET = 100`
(family 1) + definition index (0/1/2) for `sample_control_candidates` /
`matched_control_sample`'s seed; the per-horizon clustered bootstrap further
adds the horizon's minute count so no two bootstraps in this family share a
seed. Exact per-definition seeds are recorded in definitions.json and
summary.json.

## Economic friction assumption

`screening_framework.ONE_WAY_FRICTION_BPS = 5.0`,
`ROUND_TRIP_FRICTION_BPS = 10.0` (module constants, not redefined here).
`classify_economic_magnitude` compares each definition's primary-horizon
(60m) excess-vs-control mean, in bps, against this round-trip friction:
ECONOMICALLY_TOO_SMALL if excess < 10bps, POTENTIALLY_TRADEABLE if
10bps <= excess < 20bps (or MFE upper bound < 20bps), STRONG_EFFECT
otherwise.

## Effect-surface stability check

`research_stats.effect_surface` is run over `trailing_vol_60m` (numeric,
event's own trailing 60m volatility proxy) x `minutes_of_day` (numeric,
event's own UTC minute-of-day), tertile-binned, on the 60m-horizon
direction-adjusted forward return. `family_runner._effect_surface_instability`
flags `EFFECT_SURFACE_INSTABILITY` if fewer than half of the adequately
populated cells (n>=5) share the population-weighted overall sign, or one
cell's |mean| exceeds 3x the median |mean| of the other populated cells
(isolated spike). This is a coarse robustness check, not a parameter sweep.

## Verdict

`screening_framework.VerdictInputs` / `determine_verdict` (exact taxonomy:
PHENOMENON_PRESENT / WEAK_SIGNAL / PHENOMENON_NOT_OBSERVED /
INSUFFICIENT_DATA). Threshold choices used to populate `VerdictInputs`
(documented once in `family_runner.py`, applied identically across all
families 1-3): matched-control support requires >=10 events AND >=10
controls in common support; temporal/symbol breadth require >=20% of the
62-day window / 35-symbol universe respectively; concentration-low requires
top1-symbol-share and best-day-share both <=40%; MFE/MAE asymmetry requires
the |MFE|/|MAE| ratio (at the largest horizon) to fall outside [0.8, 1.2];
coherent-direction requires >=75% of the 4 horizons to share the primary
(60m) horizon's excess sign.
