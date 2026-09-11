# Task 74S — Stage 3: One Frozen Replay — Results and Funnel

## Run identity
`git_commit f7ff865` (this task's own Stage 0-2 checkpoint), `strategy_version 2ae6216bca70`,
`config_hash 3556debe52af` (unchanged from Task 72O/73S), `dataset_hash 5e5412a960bf`,
`working_tree_dirty: false`. 10 symbols, 1,903,044 bars, single chronological pass,
`--research-telemetry` enabled, primary cost config (5/5/10bps). Completed cleanly, exit code 0, empty
stderr. No correctness defect encountered — the run is reported as-is.

## Headline result
**Zero trades executed, for every one of the 10 symbols, across the entire ~1-year window.**
`trades.csv`/`trades.json`/`equity_curve.csv` are all empty (header/`[]` only). This generalizes Task
73S's AAPL-only (2025-08-15..2025-12-31) `NO_ELIGIBLE_LONG_SETUPS` finding to the full preregistered
10-symbol, full-available-history scope — it is not a narrow-window or single-symbol artifact.

## Aggregate funnel (see `stage3_funnel.csv` for exact counts/units)
- 1,903,044 bars processed. **93.63%** (1,781,848) rejected `LOW_VOLATILITY` before any candidate could
  even form — the same dominant bottleneck Task 73S identified for AAPL alone, now confirmed dataset-wide.
- 5,021 raw candidates formed (0.26% of bars) — 2,488 bullish, 2,533 bearish, an almost even split.
- Of the 5,021 candidates, **3,640 (72.5%)** were rejected `LOW_CONFLUENCE` — by far the dominant
  candidate-level rejection reason (the next largest, `OPENING_BLACKOUT`, is 3.9x smaller).
- Only 12 of the 2,488 bullish candidates (0.48%) reached the minimum confluence threshold
  (`confluence_score >= 2`); of those, only **4** were in the `regular` trading session (the other 8
  fired `pre_market` or after `closed`, structurally ineligible to trigger an entry regardless of
  confluence).
- Of the 4 regular-session, confluence-eligible bullish candidates: 2 (STX 2025-10-22, AMD
  2025-11-20) had `trend_component == False` (price below the 200-bar/15-min HTF SMA) and 2 (PYPL
  2026-08-14, same bar, two overlapping signal_types) had `risk_reward_ratio` unavailable
  (`NaN` — geometry could not be computed). **Not one bullish candidate in the entire dataset survived
  every gate simultaneously.** The exact per-candidate gate-evaluation order that ultimately classified
  each of these 4 (e.g. why AMD is not the same `TREND_GATE` rejection reason STX received despite
  both showing `trend_component=False`) is not re-derived here — Task 73S already established that
  single-candidate mechanism tracing methodology; this task reports the observed aggregate distribution
  faithfully rather than re-deriving or inventing an explanation for each one.
- `signals_published = 3`, and all 3 are **bearish**, correctly rejected downstream as
  `NO_ACTIVE_POSITION` (the long-only lifecycle taking no action while flat) — **zero bullish signals
  were ever published**, so `trades_executed = 0` follows directly, not from any downstream execution
  failure.
- **Zero-short invariant**: trivially holds — zero trades of any direction were ever opened.

## Per-symbol breakdown (`stage3_per_symbol_summary.csv`)
Every one of the 10 symbols individually shows the identical pattern: `LOW_CONFLUENCE` is the dominant
candidate-level rejection reason by a wide margin (ranging 34 for AAPL to 1,552 for STX, tracking each
symbol's own candidate volume), no symbol ever reaches a published bullish signal, and no symbol
executes a single trade. STX and AMD produce the most raw candidates (1,994 and 1,242 respectively —
also the two highest-volatility/most price-active names in this universe by candidate count) but are
rejected at the same rate as the quietest names (AAPL, 71 candidates). Concentration of raw candidate
volume in 2 of 10 symbols does not change the outcome: both are still `LOW_ELIGIBLE_LONG_SETUPS` like
every other symbol.

## Per-calendar-month-bucket breakdown (`stage3_per_bucket_summary.csv`)
All 13 buckets (2025-08 partial through 2026-08 partial) show zero trades. Candidate volume varies by
bucket (63 in 2025-08 partial up to 896 in 2026-07) but this variation never translates into an
eligible, in-session, threshold-clearing bullish signal in any single month across the full year.

## Correctness / defect check
No correctness defect was found or introduced. This is the same frozen, unmodified strategy/harness
Task 73S already proved correct via 3 labeled control-fixture tests (re-run in Stage 2 of this task,
3/3 passed, before this replay was launched). The result is reported as observed; no code was changed
to try to produce a different outcome.

**Stage 3 verdict: PASS. Result: `NO_ELIGIBLE_LONG_SETUPS`, universe-wide.**
