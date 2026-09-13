# Task 125 Part 4 — data acquisition and validation acceptance

Covers `research/scripts/task125_acquire_intraday.py` (acquisition) and
`research/scripts/task125_merge_and_validate.py` (validation), run
against the frozen specification in
`docs/research/TASK125_FROZEN_EXTENSION_PROTOCOL.md`. No return,
trigger, or P&L was computed by either script.

## Acquisition

- **Endpoint**: `https://data.alpaca.markets/v2/stocks/{symbol}/bars`,
  `feed=sip` (explicit), `adjustment=raw`, `timeframe=1Min` — reusing
  the exact request/retry pattern already used by
  `research/scripts/task107a_prices.py` (jittered backoff on 429/5xx)
  and `research/scripts/task63r_probe_alpaca_feeds.py`/`task124_alpaca_feed_probe.py`
  (single-symbol endpoint, page-token pagination). No new provider
  integration.
- **Symbols × date partitions**: 15 symbols (12 original + BABA/SHOP/
  SPCX) × 4 calendar-chunk partitions each (2022-12, 2023 full, 2024
  full, 2025-01→08-14) = **60 partitions**. Durable, resumable progress
  tracked per-partition in `results/task125_intraday_extension/acquisition_progress.json`
  — a re-run would skip any partition already marked `DATA_PRESENT`/
  `EMPTY_RESPONSE` and resume only what remains, never restarting the
  whole batch.
- **Pilot measurement**: first partition (AAPL, Dec 2022) completed in
  1.10s. A 4-partition follow-up including one full-year partition
  (AAPL 2023, 187,088 rows) measured 7.26s/partition average, revising
  the estimate for the remaining 55 partitions to ~400s (6.7 min).
- **Actual full run**: all 60 partitions completed, **0 failures**, in
  506.3s for the remaining 55 (9.21s/partition average — full-year,
  higher-volume-name partitions like TSLA/NVDA 2023-2024 ran up to
  ~25-30s each). Every partition recorded its request parameters,
  retrieval timestamp, feed, adjustment, row count, and file SHA-256 in
  `acquisition_progress.json`.
- **Deduplication/ordering**: each partition's bars are deduplicated on
  timestamp and sorted before being written (pagination boundaries can
  repeat the boundary bar across pages).
- **No credentials printed**: `APCA_API_KEY_ID`/`APCA_API_SECRET_KEY`
  were loaded via `dotenv.load_dotenv(..., override=False)` and used
  only inside request headers, consistent with every prior task's
  handling.
- **Storage**: `results/task125_intraday_extension/_raw/<symbol>/<start>_<end>.csv`
  — local only, `/results/` is gitignored (repo convention), never
  committed.

## Merge and validation (`task125_merge_and_validate.py`)

For each of the 15 symbols, all 4 partitions are concatenated,
deduplicated on timestamp (dropping any cross-partition-boundary
repeats), sorted, and checked for non-positive prices / negative
volume (none found for any symbol) before being written to
`results/task125_intraday_extension/_merged/<symbol>.csv`.

| symbol | rows (final) | distinct dates | sessions w/ open→cutoff coverage | single-bar jumps >30% |
|---|---:|---:|---:|---:|
| AAPL | 511,910 | 715 | 677 | 0 |
| AMAT | 297,245 | 708 | 677 | 0 |
| AMD | 521,036 | 715 | 677 | 0 |
| AVGO | 348,919 | 710 | 677 | **1** (2024-07-15) |
| CSCO | 309,296 | 709 | 677 | 0 |
| GOOGL | 446,690 | 715 | 677 | 0 |
| INTC | 490,177 | 715 | 677 | 0 |
| MSFT | 419,619 | 715 | 677 | 0 |
| NVDA | 584,056 | 715 | 677 | **1** (2024-06-10) |
| PYPL | 362,334 | 714 | 677 | 0 |
| STX | 266,968 | 683 | 677 | 0 |
| TSLA | 621,475 | 715 | 677 | 0 |
| BABA | 467,334 | 715 | 677 | 0 |
| SHOP | 344,701 | 713 | 677 | 0 |
| SPCX | 2,844 | 606 | 573 | 0 |

- **Corporate-action check confirmed real, not a data defect**: the
  two flagged single-bar jumps land EXACTLY on AVGO's (Broadcom) and
  NVDA's (Nvidia) publicly documented 10-for-1 stock splits (effective
  2024-07-15 and 2024-06-10 respectively) — this is the RAW/unadjusted
  discontinuity the frozen protocol anticipated, not an acquisition
  bug. No manual price adjustment is applied; the evaluation's own
  `EXTREME_RETURN_EXCLUSION_ABS=0.50` guard is the sole, predeclared
  handling (§5).
- **SPCX's thinness reproduces Task 124's finding**: 2,844 rows across
  606 calendar dates (≈4.7 bars/day) and only 573/606 dates with ANY
  bar inside the open→cutoff window — genuine illiquidity, not an
  acquisition or entitlement defect, exactly as Task 124's probe
  already established.
- **No non-positive prices, no negative volume, no duplicate
  timestamps after dedup, all series monotonically ordered** — for
  every one of the 15 symbols.
- **Missing-bar handling**: the merge step does NOT forward-fill or
  manufacture any bar; sessions without a bar at the exact cutoff/
  entry/next-open timestamp are surfaced as exclusions inside the
  evaluation script (§5 of `TASK125_OVERNIGHT_ACTIONABLE_RESULTS.md`),
  never silently substituted here.

Full machine-readable detail: `results/task125_intraday_extension/data_acceptance.json`
(copied to `docs/research/evidence/task125/`).

## Acceptance

All 15 symbols' merged series are accepted for evaluation under the
frozen protocol. No symbol is excluded at this stage — SPCX's extreme
thinness will instead surface naturally as a high missing-bar
exclusion rate inside the evaluation funnel, exactly as intended by
the "exclude and count, never fabricate" rule, not pre-filtered here
based on an outcome.
