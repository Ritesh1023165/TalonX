# Family 5 -- Compression -> Expansion (Precondition) -- Screening Spec

Task 67B Step 2. Stage 1 phenomenon-discovery screening, DEVELOPMENT data only
(35 symbols, 2026-05-15..2026-08-14, ~62 trading days). Read-only, exploratory --
NOT a trading engine, NOT a backtest, NOT strategy freezing.

Question: does sitting in a COMPRESSED volatility state predict LATER unusually
large movement and/or directional persistence, evaluated at horizons AFTER the
compressed bar -- with NO requirement that expansion has already begun?

This family is the deliberate complement to Family 3 (volatility/range EXPANSION),
whose event condition was "expansion is ALREADY HAPPENING NOW" (an
established-quiet-baseline followed IMMEDIATELY by a same-window ATR breakout).
Family 5's event condition never evaluates a "recent/expansion" window at all --
only whether the bar currently sits in (or has been sitting in, or is trending
toward) a compressed state. As with Family 3, this family excludes the first 30
minutes of RTH (opening-range territory is ORPB_V1's domain; `talonx_quant/
orpb_v1.py` was never opened or referenced while designing this family -- the
exclusion is defined independently via `screening_framework.
POST_OPENING_RANGE_UTC_HOUR`, 14:00 UTC) and requires >=15 minutes of same-day
room before RTH close.

## Definitions

### A) `persistent_compression_atr30_persist30`
Trailing 30m ATR proxy (`causal_atr_proxy`, as a fraction of price) in the bottom
GLOBAL tertile, held CONTINUOUSLY for the entire trailing 30 minutes -- every bar
in the window individually below the tertile cutoff, not just the window average.
Implemented by a new local helper, `_persistently_compressed_mask` (own copy in
the family script; family scripts are self-contained by convention here), which
checks a per-symbol cumulative-sum-of-violations over the trailing window (same
searchsorted + cumsum algorithm shape as `causal_atr_proxy`, and the SAME warmup
convention: False only for a session's literal first bar; a bar with SOME but
less than a full 30m of same-day history uses whatever same-day bars are
available, matching every other causal_* helper in this codebase rather than
requiring a literal elapsed duration none of the sibling helpers enforce either).
This is a genuinely stronger requirement than widening the ATR window to 30-45m
and taking its mean (a brief spike inside a wide window could still leave the
mean low) -- persistence requires every sub-bar to individually qualify.

### B) `relative_narrow_range_15v90`
Current 15m rolling high-low range, expressed as a PACE (range / window_minutes)
and divided by the SAME symbol's own trailing 90m high-low range pace (its own
recent "typical" range-per-minute) -- a per-symbol-normalized, dimensionless
ratio, in the bottom GLOBAL tertile. Implemented via a new local helper,
`_causal_trailing_hl_range` (genuine rolling max(high)-min(low), NOT the
per-bar-range MEAN that `causal_atr_proxy` computes), using pandas' time-based
`.rolling()` grouped by (symbol, trading_day) so the window can never reach
across the overnight gap regardless of window size, with an explicit NaN mask
for same-day warmup (pandas' own `min_periods=1` rolling does not distinguish
"less than a full window of history" from "a full window", so that gate is
applied separately here). Tests whether the recent window is narrow relative to
what THIS symbol itself has typically been doing lately, not an absolute $ range
threshold (which would conflate a naturally-quiet symbol with a naturally-loud
one).

### C) `declining_compression_atr30_lag30`
Current causal 30m ATR proxy < the SAME measure evaluated ~30 minutes earlier
(via `_value_at_offset`, a same-day causal lookback over a precomputed array --
own copy of Family 3's helper of the same shape, adapted here, not imported),
AND both the current and the lagged value are below the GLOBAL MEDIAN (as a
fraction of price, using ONE cutoff computed from the unlagged/current-bar
array's own distribution, applied to both). A genuine "compression is
DEEPENING" signal (a declining trend), not merely "compression exists right
now" -- a bar where the two ATR values are exactly equal (no real trend) does
NOT satisfy `now < prior` and does not fire, regardless of how low the absolute
level is.

All three additionally require: (i) at/after 14:00 UTC (excludes the first 30
minutes of RTH), (ii) >=15 minutes of same-day room before RTH close, (iii) a
nonzero weak directional signal (see below) -- events where it is exactly zero
(vanishingly rare on real float prices) are dropped so every retained event has
a well-defined `direction`.

## DIRECTION CONVENTION

Compression itself has no direction; this family reports TWO separate analyses
per definition, on the SAME deduplicated event set (same condition, same dedup),
for a direct comparison:

**PRIMARY (volatility-effect, UNSIGNED):** does compression predict an EXPANDED
ABSOLUTE range later? Implemented via approach (ii) from the brief: `compute_
volatility_effect` in the family script computes its own simple
absolute-forward-range statistic directly from raw bars -- `(max(high) -
min(low))` over each horizon window (bounded by that event's own session close,
via `research_stats.forward_return_horizons`'s own `favorable_excursion_high` /
`adverse_excursion_low` outputs, which are already exactly max(high)/min(low)
over that causally-bounded window -- reused rather than re-derived), as a % of
`entry_price`, for BOTH the events AND their matched controls (the SAME
matched-control population `family_runner.run_family_definition` builds
internally for the secondary analysis, reconstructed here via the identical
`sample_control_candidates` + `matched_control_sample` +
`family_runner.build_control_events_from_pairs` calls, same `match_keys`, same
seed -- `build_control_events_from_pairs` is IMPORTED from `family_runner.py`,
not modified). Approach (ii) was chosen over approach (i) (nominal-direction +
`abs()` of `forward_return_pct`) because computing `abs()` correctly PER MATCHED
PAIR (before differencing -- `abs(mean(diff)) != mean(diff of abs values)`)
would have required reaching into `run_family_definition`'s internal per-pair
merge anyway (it is not returned in its result dict); recomputing the range
statistic directly from bars is simpler, self-contained, and unambiguous. Applied
consistently across all three definitions.

Rule: **VOLATILITY_EFFECT_PRESENT** iff, at the primary horizon (60m): the
matched-control excess (event abs-range% minus paired-control abs-range%) is
POSITIVE (events show MORE absolute movement than controls -- the
hypothesis-aligned direction), its magnitude in bps is >= `ROUND_TRIP_
FRICTION_BPS` (10.0bps, same friction convention as the rest of Task 67A), AND
its clustered-by-symbol bootstrap 95% CI excludes zero on the positive side
(`ci_low > 0 and ci_high > 0`). Otherwise **VOLATILITY_EFFECT_NOT_OBSERVED**.
(See `_volatility_effect_flag` / `_positive_excess_ci_excludes_zero` in the
family script.)

**SECONDARY (directional edge, SIGNED):** the weak directional signal is the
SIGN of `causal_trailing_return` over a trailing 15m window ending at the
compressed bar (the most recent short-term drift direction observed AS OF the
compressed bar -- causal, no forward-looking information). That sign is set as
the event's `direction` and run through the STANDARD `run_family_definition`
pipeline exactly as Families 1-3 do, giving the usual events.csv /
horizon_metrics.csv / matched-control / bootstrap / verdict machinery "for
free". Rule: **DIRECTIONAL_EDGE_PRESENT** iff, at the primary horizon: the
SIGNED matched-control excess is POSITIVE (the weak recent-drift direction
continues), its magnitude is >= `ROUND_TRIP_FRICTION_BPS`, and its clustered
bootstrap 95% CI excludes zero on the positive side. Otherwise
**DIRECTIONAL_EDGE_NOT_OBSERVED**. Deliberately the SAME rule shape as the
volatility-effect flag, just applied to the signed rather than unsigned metric.

Both flags are reported ADDITIONALLY to (never instead of) the standard
PHENOMENON_PRESENT / WEAK_SIGNAL / PHENOMENON_NOT_OBSERVED / INSUFFICIENT_DATA
verdict that `determine_verdict` produces for the SECONDARY (signed) analysis.
Per the brief, it is an explicitly EXPECTED, useful, non-failure outcome for a
definition to show VOLATILITY_EFFECT_PRESENT while DIRECTIONAL_EDGE_NOT_OBSERVED
(compression can expand the range of outcomes without making the sign
predictable) -- this is stated explicitly in summary.md, never silently treated
as a weaker/failed result. The reverse is equally possible and equally reported
plainly.

Reported-but-not-flagged nuance observed in the actual run (see summary.md):
definition C's primary/unsigned excess at several horizons is NEGATIVE and its
CI excludes zero on the NEGATIVE side (matched controls show MORE absolute
movement than the declining-compression events) -- a substantively different,
also-informative outcome from "no effect", but it does not meet the
hypothesis-aligned (positive-excess) VOLATILITY_EFFECT_PRESENT bar by
construction, since the rule specifically tests the DIRECTION the phenomenon
predicts (expansion), not "any economically-significant difference from
controls in either direction".

## De-duplication

`research_stats.dedup_events`, `group_keys=["symbol"]`, `keep="first"`,
`min_gap_minutes=30` for all three definitions (uniform, unlike Family 3's
per-definition values) -- compression states tend to persist across many
consecutive bars (especially definitions A and C, which are explicitly about
sustained/deepening states), so a 30-minute min-gap collapses one persistent
compression episode into a single representative event, the same rationale
Family 3 used for its own 30-minute choices. Both RAW and DEDUPLICATED counts
are reported.

## Matched-control construction

Identical mechanism to Families 1-3: `sample_control_candidates` (stride 20m,
exclusion buffer 60m, warmup 90m, min lead 15m) + `matched_control_sample`
stratified by `["symbol", "time_of_day_bucket", "vol_bucket"]`, greedy
nearest-time pairing. For the secondary (signed) analysis, a paired control
borrows its matched event's direction; excess = per-pair difference in
direction-adjusted forward return, clustered (by symbol) bootstrap 95% CI. For
the primary (unsigned) analysis, the SAME pairing (same seed, same pool) is
reused but the paired difference is computed on the unsigned abs-range%
statistic instead (see DIRECTION CONVENTION above).

## Seeds

`DEFAULT_SEED = 670067` + `FAMILY_SEED_OFFSET = 500` (family 5; 100/200/300/600
already used by families 1/2/3/6) + definition index (0/1/2). Secondary
per-horizon bootstraps add the horizon's minute count (matching
`family_runner.py`'s own convention); primary (volatility-effect) per-horizon
bootstraps add `10_000 + horizon_minutes` instead, so their resamples are
independent of the secondary analysis's own per-horizon draws even though both
reuse the same underlying event/control pairing. Exact per-definition seeds
recorded in definitions.json / summary.json.

## Economic friction assumption

`screening_framework.ONE_WAY_FRICTION_BPS = 5.0`, `ROUND_TRIP_FRICTION_BPS =
10.0` (module constants, unchanged). Same `classify_economic_magnitude`
thresholds as Families 1-3, applied to both the secondary (signed) excess and
(separately) the primary (unsigned) excess.

## Effect-surface stability check

Same mechanism as Families 1-3, applied to the SECONDARY (signed) analysis
only: `effect_surface` over `trailing_vol_60m` x `minutes_of_day`
(tertile-binned) on the 60m-horizon direction-adjusted forward return;
`EFFECT_SURFACE_INSTABILITY` flagged on the same same-sign/isolated-spike
heuristic in `family_runner.py`. Not separately computed for the primary
(unsigned) analysis -- out of scope per the brief's deliverable list, which
asks for the flag pair as an addition to (not a full parallel pipeline
alongside) the standard per-definition deliverables.

## Verdict

Same taxonomy and threshold set as Families 1-3 (documented once in
`family_runner.py`, applied identically across all families), computed on the
SECONDARY (signed) analysis. The VOLATILITY_EFFECT_PRESENT/NOT_OBSERVED and
DIRECTIONAL_EDGE_PRESENT/NOT_OBSERVED flags are additional, not a replacement.

## Primary (unsigned) results location

The primary/unsigned per-horizon numbers (raw mean, matched-control mean, excess
mean, clustered bootstrap CI, all in abs-range% terms) are reported in
summary.json (per definition, under `volatility_effect.per_horizon`) and
summary.md, NOT as a separate CSV file -- the brief's deliverable file list
specifies the standard Family 1-3 CSV set (events.csv, horizon_metrics.csv,
matched_control_metrics.csv, mfe_mae.csv), which here reflect the SECONDARY
(signed) analysis exactly as in Families 1-3; the primary analysis's per-horizon
numbers live alongside the standard ones in the JSON/markdown summaries instead
of inventing a new, unlisted CSV.
