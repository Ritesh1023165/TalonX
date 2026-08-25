# Family 3 -- Volatility / Range Expansion -- Screening Spec

Task 67B Step 2. Stage 1 phenomenon-discovery screening, DEVELOPMENT data only
(35 symbols, 2026-05-15..2026-08-14, ~62 trading days). Read-only, exploratory --
NOT a trading engine, NOT a backtest, NOT strategy freezing.

Question: does an established intraday range followed by genuine volatility/range
expansion lead to abnormal subsequent directional movement?

This family explicitly tests LATER-session/general-session compression -> expansion
and EXCLUDES the first 30 minutes of RTH (opening-range territory is ORPB_V1's
domain). `talonx_quant/orpb_v1.py` was never opened or referenced while designing
this family -- the exclusion is defined independently via
`screening_framework.POST_OPENING_RANGE_UTC_HOUR` (14:00 UTC, i.e. 30 minutes after
the 13:30 UTC RTH open), a constant that already existed in Step 1's shared module
for exactly this purpose.

## Definitions

All three definitions share one shape: an "established" trailing-ATR-proxy measure
over a base window, evaluated **strictly before** a subsequent "recent" (expansion)
window begins -- via a new local helper, `_value_at_offset` (in the family script,
NOT added to the shared `screening_framework.py`), which generalizes
`causal_price_at_offset`'s same-day, per-symbol, searchsorted lookback algorithm to
an arbitrary precomputed array (here, `causal_atr_proxy`'s own output) instead of
just price.

Why the lag matters: if "established" were evaluated unlagged, AT the current bar
(i.e. `causal_atr_proxy`'s raw output), its own trailing window would already
include part of the very expansion burst being detected -- the two windows overlap
at the tail, diluting "established was quiet BEFORE the burst" by however much the
recent window overlaps the base window. Evaluating established at
`(t - recent_window_minutes)` instead means the established window ends exactly
where the recent (expansion) window begins: no overlap, no self-dilution. This was
caught during test-writing (`tests/test_task67a_family03_range_expansion.py`) --
an unlagged first draft failed to fire on a clean hand-constructed
quiet-then-burst synthetic price path because the established measure was itself
inflated by the burst it was supposed to precede.

"Established... bottom global tertile": `established` (in $ terms) is expressed as
a fraction of price and compared against a WHOLE-DATASET (all 35 symbols, all
days) tertile cutoff, computed fresh per definition via
`_global_low_tertile_mask` (same global-cutpoint rationale as
`add_bar_features`'s own `vol_bucket`, but recomputed here because `established`
is this family's own LAGGED series, not `add_bar_features`'s unlagged
`trailing_vol_60m`).

### A) `compression60_expansion15_2x`
Established = 60m trailing ATR proxy, evaluated 15m before now (bottom global
tertile). Recent = 15m trailing ATR proxy (ending now) >= 2.0x the lagged
established value. Direction = sign of the 15m trailing return (the breakout's own
direction).

### B) `compression90_expansion10_2.5x`
Established = 90m trailing ATR proxy, evaluated 10m before now (bottom global
tertile). Recent = 10m trailing ATR proxy >= 2.5x established. Direction = sign of
the 10m trailing return.

### C) `compression45_expansion20_1.75x`
Established = 45m trailing ATR proxy, evaluated 20m before now (bottom global
tertile). Recent = 20m trailing ATR proxy >= 1.75x established. Direction = sign of
the 20m trailing return.

All three additionally require: (i) at/after 14:00 UTC (excludes the first 30
minutes of RTH), (ii) >=15 minutes of same-day room before RTH close.

## De-duplication

`research_stats.dedup_events`, `group_keys=["symbol"]`, `keep="first"`.
`min_gap_minutes` = 30 (A, C) / 20 (B) -- shorter than Family 1's gaps, reflecting
that a range-expansion burst is inherently a shorter-lived phenomenon than a
multi-hour trend (the defining "recent" windows here are 10-20 minutes, not
60-90). Both RAW and DEDUPLICATED counts are reported.

## Matched-control construction

Identical mechanism to Families 1-2: `sample_control_candidates` (stride 20m,
exclusion buffer 60m, warmup 90m, min lead 15m) + `matched_control_sample`
stratified by `["symbol", "time_of_day_bucket", "vol_bucket"]`, greedy
nearest-time pairing, paired control borrows its matched event's direction,
excess = per-pair difference in direction-adjusted forward return, clustered
(by symbol) bootstrap 95% CI.

## Seeds

`DEFAULT_SEED = 670067` + `FAMILY_SEED_OFFSET = 300` (family 3) + definition index
(0/1/2), plus the per-horizon bootstrap adds the horizon's minute count. Exact
per-definition seeds recorded in definitions.json / summary.json.

## Economic friction assumption

`screening_framework.ONE_WAY_FRICTION_BPS = 5.0`,
`ROUND_TRIP_FRICTION_BPS = 10.0` (module constants, unchanged). Same
`classify_economic_magnitude` thresholds as Families 1-2.

## Effect-surface stability check

Same mechanism as Families 1-2: `effect_surface` over `trailing_vol_60m` x
`minutes_of_day` (tertile-binned) on the 60m-horizon direction-adjusted forward
return; `EFFECT_SURFACE_INSTABILITY` flagged on the same same-sign/isolated-spike
heuristic in `family_runner.py`.

## Verdict

Same taxonomy and threshold set as Families 1-2 (documented once in
`family_runner.py`, applied identically across all three families).
