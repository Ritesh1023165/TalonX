# Stage 3 -- Profitability Verdict

## Candidate
`TALONX_PRODUCTION_QUANTSCANNER_INTRADAY_LONG_ONLY_V1` (the existing,
frozen, long-only production strategy -- `talonx_quant/strategy.py` +
`consumer.py` + `indicators.py`, unmodified). Preregistered in
`stage3_preregistration.json` before any run.

## What was run
- Symbol: AAPL (scope-reduced from the preregistered AAPL/MSFT/NVDA
  3-symbol set, for time-budget reasons -- see `stage3_run_log.txt`; a
  blind, non-result-driven reduction).
- Window: 2025-08-15 to 2025-12-31 (the full available overlap between
  the preregistered `range_chop_2025` regime and the on-disk data in
  `data/historical_1m/task7b_alpaca_long_history`).
- Cost assumption: entry slippage 5bps, exit slippage 5bps, spread
  10bps -- the exact worked-example assumption already documented in
  `docs/backtesting.md`, not invented for this task.
- Runner: `talonx_backtest` CLI directly (same engine
  `scripts/run_historical_regimes.py` wraps), unmodified.

## Result
**67,002 bars processed. 6 candidate signals generated; 0 published; 0
trades executed.** Rejection breakdown: 66,648 `LOW_VOLATILITY`, 4
`US_MARKET_SESSION_CLOSED`, 2 `LOW_CONFLUENCE`.

A shorter 1-month probe (2025-08-15 to 2025-09-15) on the same symbol
produced 0 signals at all (14,110/14,288 bars rejected `LOW_VOLATILITY`)
-- consistent with the same finding at a smaller scale.

## Classification: **INCONCLUSIVE**

Zero executed trades means expectancy, profit factor, win rate, total R,
max drawdown, bootstrap CI, outlier sensitivity, and symbol/window
concentration are all UNDEFINED for this run -- reported honestly as
such in the accompanying CSVs/JSON, never fabricated or interpolated.
This is NOT the same as `REJECTED` (which would require an actual
negative-edge trade sample) -- there is simply no trade-level evidence
to judge this candidate on, for THIS symbol/window/cost combination.

`VALIDATED_AND_REPLICATED` was, in any case, definitionally unreachable
this task (preregistered upfront: no validation-period run was
performed).

## Interpretation

`min_atr_pct=0.25` (the 2026-08-14-session-review volatility gate) is
evidently a tight filter for a single mega-cap name (AAPL) over an
unremarkable ~4.5-month window -- it rejected 99.5%+ of all bars before
any other gate was even reached. This is not evidence the strategy is
unprofitable; it is evidence that a single-symbol, single-window,
overnight-budget-constrained probe is the wrong instrument to evaluate a
low-signal-frequency intraday strategy. A meaningful read requires either
a much longer window, a wider symbol universe (the full 10-symbol set
already on disk), or both -- see `stage3_next_research_plan.md`.

## No candidate integrated
Per this task's explicit instruction, nothing here changes what runs
live. This is offline evidence generation only.
