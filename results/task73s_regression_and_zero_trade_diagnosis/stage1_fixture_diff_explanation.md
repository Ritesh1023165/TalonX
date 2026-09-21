# Stage 1 -- Fixture Repair: What Changed and Why

## File changed
`examples/data/sample_AAPL_trade_1m.csv` (a non-protected example/test
fixture -- not `talonx_quant/{strategy,indicators,consumer,config}.py`).

Original backed up, untouched, at
`results/task73s_regression_and_zero_trade_diagnosis/stage1_original_fixture_backup.csv`
(462 data rows).

## What was added (nothing existing was removed or edited)

1. **~9 trading days of quiet pre-roll** (3,510 rows, 2025-12-23 through
   2026-01-02, prepended BEFORE the original 2026-01-05/01-06 content) --
   a gentle, deterministic ~-1.8%/trading-day synthetic decline (each
   individual 1-minute bar's move is ~0.0046%, far under
   `min_atr_pct`/any volatility gate -- every one of these bars is
   rejected `LOW_VOLATILITY`, exactly like ~99% of the file's own
   pre-existing content, so nothing about this addition changes the
   file's own character). Its ONLY purpose: the ALREADY-EXISTING,
   unmodified 200-bar/15-minute HTF trend gate
   (`talonx_quant/consumer.py::_trend_gate_applicable`,
   `config.htf_sma_period=200`) needs ~7.7 trading days of regular-
   session data to ever produce a non-`None` `htf_sma_200` -- without
   this, EVERY bullish candidate in the original 2-day fixture is
   rejected `HTF_DATA_UNAVAILABLE` regardless of confluence (see
   `stage1_root_cause.md`).

2. **11 (then 14, after one extension -- see below) rows appended after**
   the original, unchanged 462 rows: a 3-bar further decline (continuing
   the existing fixture's own downtrend, from 95.27 to 94.13) followed
   by an 8-bar (+3 more, final) recovery at +0.7%/bar with volume at
   5,250 (vs. the ~1,000-1,500 baseline elsewhere) -- calibrated (see
   below) to produce exactly one genuine, gate-clearing signal.

## Why this specific shape, and how it was verified (not guessed)

Calibration was done empirically against the REAL, unmodified
`talonx_quant.indicators.compute_indicators` /
`talonx_quant.aggregation.HtfBarAggregator` / `talonx_quant.strategy.evaluate_signals`
functions directly (see `results/task73s_regression_and_zero_trade_diagnosis/scratch_stage1/`
for every intermediate iteration's exact numeric output), not by trial-
and-error against the final pass/fail test result:

- The recovery must curl RSI back through 30 (oversold) while the
  independent MACD line is ALSO crossing its signal line on the SAME
  bar -- verified bar-by-bar: at the trigger bar, `rsi=29.72` (< 30,
  scores the confluence RSI leg for this MACD-triggered candidate, since
  only the MACD leg is self-excluded here, not RSI) and
  `volume_surge_ratio=2.545` (> 2.0 threshold, scores the volume leg).
  `confluence_score = 0(macd, self-excluded) + 1(rsi) + 1(volume) = 2`,
  exactly meeting `confluence_score_min=2` -- verified directly via
  `--research-telemetry`'s `candidate_telemetry.csv` output, not inferred.
- The recovery must ALSO push price above the 200-bar 15-min SMA at that
  same instant -- verified directly via
  `talonx_quant.aggregation.HtfBarAggregator` +
  `talonx_quant.indicators.compute_htf_trend` reused exactly as the
  production code does: `close=96.12 > htf_sma_200=91.64` at the trigger
  bar (with the -1.8%/day preroll decline, chosen specifically to pull
  the 200-bar SMA down into a range the recovery could credibly clear
  without an unrealistically large move).
- Structural R:R was already comfortably clear at every iteration
  (`risk_reward_ratio~3.5` vs. `min_risk_reward_ratio=1.5`) -- pivots
  come from the existing Jan-5 session, untouched.
- A final 3-bar extension was added (same +0.7%/bar pace) purely so the
  resulting trade's exit reason is `TARGET` rather than `DATA_END` --
  the original 11-row tail fell just 0.04% short of the computed target
  price (99.577 vs. reached 99.534); extending by 3 more bars lets the
  trade actually reach it, restoring `test_trade_dataset_exercises_a_concrete_exit_path`'s
  own pre-existing "hits TARGET, not just runs out of data" contract
  (see below).

## End-to-end confirmation (full pipeline, not just the target test)

`.venv/Scripts/python.exe -m talonx_backtest --data examples/data/sample_AAPL_trade_1m.csv --symbol AAPL --tz America/New_York ...`:
`signals_generated=5, signals_published=1, trades_executed=1`. The one
published/executed trade: `macd_bullish_cross`, `confluence_score=2`,
`risk_reward_ratio=3.499`, `entry_price=96.1226`, `exit_reason=TARGET`,
`exit_price=99.5775`, `gross_R=net_R=3.499` (zero-cost default, matching
the target test's own invocation).

## A second, pre-existing test file this same repair resolves

`tests/test_backtest_sample_data.py` already carried a `strict=True`
xfail marker (`_XFAIL_PENDING_SAMPLE_DATA_REGENERATION`, written at Task
25A 2026-08-20) on 5 tests specific to this exact fixture, anticipating
precisely this repair ("an eventual CSV regeneration is forced to remove
this marker, not silently leave it stale"). All 5 now pass with the
marker removed (see `stage1_test_results.txt`); the marker itself is
narrowed to `sample_multi_trade_1m.csv` only, which Task 73S does NOT
touch (out of scope; remains a genuine, still-pending follow-up).

## No strategy change, no weakened assertion

Zero edits to `talonx_quant/strategy.py`, `indicators.py`, `consumer.py`,
or `config.py`. `test_run_historical_regimes.py`'s own assertion
(`total_trades == 1`) is unchanged. `test_backtest_sample_data.py`'s
assertions are unchanged (only the now-inapplicable xfail decorator was
removed from 5 tests whose own assertions were never touched).
