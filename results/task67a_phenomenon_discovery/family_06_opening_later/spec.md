# Family 6 -- Opening Information -> Later-Session Continuation -- Screening Spec

Task 67B Step 2. Stage 1 phenomenon-discovery screening, DEVELOPMENT data only
(35 symbols, 2026-05-15..2026-08-14, ~62-63 trading days). Read-only, exploratory --
NOT a trading engine, NOT a backtest, NOT strategy freezing.

Question: does what happens in the first 30 minutes of RTH (13:30-14:00 UTC) carry
information about the LATER session, when used PURELY AS A SIGNAL (not traded
itself)?

**This is NOT ORPB.** `talonx_quant/orpb_v1.py` was never opened or referenced while
designing this family. The 13:30-14:00 UTC opening window here produces a NUMBER (a
signal value) that CONDITIONS a LATER entry -- the opening window itself is never
traded. The actual event/decision timestamp is always placed strictly AFTER the
window: the first bar at or after 14:00 UTC for that symbol/day (exactly 14:00 UTC
whenever this dataset has continuous 1-minute coverage there; the next available bar
on a rare data-gap day -- a fixed, documented rule, identical for every symbol/day,
not a per-event choice). Forward horizons (15/30/60/120m) are measured FROM that
14:00 UTC decision point into the later session, per the brief.

## Signal computation

`_opening_window_agg` restricts to bars with `13:30 <= minutes_of_day < 14:00` (a
strict boolean time-window mask -- never a causal-lookback helper that could reach
outside that window), then aggregates per (symbol, trading_day): the window's first
bar's own `open` print, the window's last bar's own `close` print, the window's
summed `volume`, and a bar count (`n_bars`) used to apply a data-quality guard
(`OPENING_WINDOW_MIN_BARS = 20` of the nominal 30 -- a sparse/gappy opening window's
signal is not trusted). `opening_return = (window_close - window_open) / window_open`.

The decision bar itself (`_decision_bars`) is, separately, the first bar at/after
14:00 UTC per (symbol, trading_day) -- `entry_price`, `trailing_vol_60m`,
`time_of_day_bucket`, `vol_bucket`, `trading_day` are all sourced straight from that
`bars_feat` row, per `run_family_definition`'s contract.

## Definitions

### A) `opening_return_magnitude`
Signal = the symbol's own opening-30m return (as above). Condition: `|signal| >=`
the GLOBAL top-tertile cutoff of `|signal|` across every (symbol, day) in the
dataset (`SIGNAL_TOP_TERTILE_QUANTILE = 2/3`, i.e. top ~33% by absolute opening-30m
move -- a broad, round choice, not fine-tuned). Direction = `sign(signal)`. Tests
whether STRONG opens (either direction) continue (momentum) or mean-revert
(reversal) into the later session -- summary.md reports whichever the excess sign
actually shows.

### B) `opening_relative_strength_vs_spy`
Signal = the symbol's opening-30m return MINUS SPY's own opening-30m return on the
SAME day (both computed by the identical `_opening_window_agg` helper -- SPY is
just another "symbol" here). Deliberately simpler than a beta-adjusted approach: no
beta estimation, no rolling regression -- a documented simplification given the time
budget (Family 4, which would supply that fuller machinery, does not exist yet in
this repo; this family was designed without reading or depending on it). Same
top-tertile-of-`|signal|` condition, `sign(signal)` direction. Tests whether it is
RELATIVE (vs. SPY), not ABSOLUTE, opening strength that carries continuation
information -- summary.md compares this against definition A side by side.

### C) `opening_relative_volume`
Signal = the symbol's opening-30m cumulative volume divided by that SAME symbol's
LEAVE-ONE-DAY-OUT median opening-30m volume (median computed from all OTHER
DEVELOPMENT days for that symbol, excluding the day being scored --
`_leave_one_day_out_median`, the more defensible of the two normalization options
the brief offered; chosen since the time budget allowed it). Condition:
`relative_volume >=` the global top-tertile cutoff of `relative_volume` (not
absolute, since "typical" volume varies hugely across this 35-symbol universe).
Volume has no inherent sign, so direction = `sign` of that SAME day's opening-30m
return (definition A's own signal) -- an explicitly documented simplification that
conflates volume-MAGNITUDE (the condition) with direction-SOURCE (borrowed from A).
The resulting test is "does a HIGH-VOLUME opening move, in the direction it moved,
continue later".

## De-duplication

`group_keys=["symbol"]`, `min_gap_minutes=1200` (~20 hours) for all three
definitions. Because the decision timestamp is a FIXED clock time (14:00 UTC) common
to every event, there is naturally at most one candidate event per symbol per day
already -- consecutive same-symbol events are >=24h apart (next trading day), well
over the 1200-minute gap, so nothing is actually merged in practice. Dedup here is a
formality/safety net (guards only against the pathological case of two candidate
rows landing on the same symbol/day), unlike Families 1-3/5 where the same condition
can legitimately retrigger on many adjacent bars within one session.

## Matched-control construction

Identical mechanism to Families 1-3: `sample_control_candidates` (stride 20m,
exclusion buffer 60m, warmup 90m, min lead 15m) + `matched_control_sample`
stratified by `["symbol", "time_of_day_bucket", "vol_bucket"]`, greedy nearest-time
pairing, paired control borrows its matched event's direction, excess = per-pair
difference in direction-adjusted forward return, clustered (by symbol) bootstrap 95%
CI.

## Seeds

`DEFAULT_SEED = 670067` + `FAMILY_SEED_OFFSET = 600` (family 6, following the
existing `family_number * 100` convention from Families 1-3) + definition index
(0/1/2), plus the per-horizon bootstrap adds the horizon's minute count. Exact
per-definition seeds recorded in definitions.json / summary.json.

## Economic friction assumption

`screening_framework.ONE_WAY_FRICTION_BPS = 5.0`,
`ROUND_TRIP_FRICTION_BPS = 10.0` (module constants, unchanged). Same
`classify_economic_magnitude` thresholds as Families 1-3.

## Effect-surface stability check (deviation from Families 1-3)

Families 1-3 pass `run_family_definition`'s default
`effect_surface_param_cols=("trailing_vol_60m", "minutes_of_day")`. Family 6's
decision timestamp is, BY CONSTRUCTION, the same fixed clock time (14:00 UTC) for
every event, so `minutes_of_day` is constant across the whole event set --
`research_stats.effect_surface` bins each param column via `pd.qcut`, and a constant
column collapses to zero populated quantile bins (confirmed directly: a
`qcut(..., duplicates="drop")` call on an all-identical Series returns a
categorical with ZERO categories and every value `NaN`, which `groupby(...,
observed=True)` then silently drops entirely, returning a completely EMPTY effect-
surface DataFrame -- this was caught while first running the family script end-to-
end on real data, not assumed in advance). Rather than fabricate a
`minutes_of_day` axis this family does not have, Family 6 calls
`run_family_definition(..., effect_surface_param_cols=("trailing_vol_60m",))` --
a single-axis stability check over the causal trailing-60m volatility proxy only.
This uses an existing, already-exposed `run_family_definition` keyword argument;
`family_runner.py` and `research_stats.py` themselves are untouched.

## Verdict

Same taxonomy and threshold set as Families 1-3 (documented once in
`family_runner.py`, applied identically across all families).

## Result headline (from the actual DEVELOPMENT-data run)

All three definitions returned `PHENOMENON_PRESENT` / `POTENTIALLY_TRADEABLE`, with
a NEGATIVE 60m matched-control excess in every definition -- i.e. on this dataset
and these definitions, strong opening moves (whether measured absolutely, relative
to SPY, or as high-volume moves) tend to MEAN-REVERT rather than continue into the
later session. See `summary.md` for the full per-horizon table, the continuation-
vs-reversal discussion, and the relative-vs-absolute (definition B vs. A)
comparison. As with every Stage 1 screen, this is a discovery-only observation on
DEVELOPMENT data -- not validated out-of-sample, not a claim of harvestable alpha.
