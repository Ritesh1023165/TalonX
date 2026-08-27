# Task 73S Execution Journal

- [Stage 0] PASS. Branch/HEAD confirmed (df6da2b), clean tree, origin
  synced, no concurrent session. Confirmed BacktestEngine reuses
  QuantScanner's private gate functions directly (not the live class),
  long-only is hardcoded Task24/25A engine behavior, "5/5/10bps" means
  20bps total round-trip cost (verified from talonx_backtest/execution.py
  directly). Known test reproduced failing before any change.
- [Stage 1] PASS. Independently re-verified Task72O's root-cause
  classification (TEST_ISOLATION_DEFECT confirmed) but CORRECTED the
  cited mechanism: the rejected candidate is actually a BEARISH
  macd_bearish_cross blocked by the MACD no-self-credit rule (commit
  83aee8b, 2026-08-22), not an RSI-recovery candidate blocked by the
  RSI-curl rule (3c97d9d) as previously stated. Found a second,
  independent blocker (200-bar HTF trend gate, corroborated by a
  pre-existing xfail marker in test_backtest_sample_data.py). Repaired
  examples/data/sample_AAPL_trade_1m.csv (prepended ~9 days of quiet
  pre-roll + appended a calibrated bullish recovery, verified
  empirically against the real unmodified indicator/strategy code) --
  produces exactly 1 trade, TARGET exit. Removed the now-resolved xfail
  marker from 5 tests in test_backtest_sample_data.py (left the
  sample_multi_trade_1m.csv marker untouched/still-blocked, correctly
  out of scope). Full suite: 2165 passed, 0 failed, 1 skipped, 10
  xfailed -- delta from baseline (2159/1/1/15) fully and exactly
  accounted for. No protected file touched. Committing as
  `fix(test): repair historical regime fixture isolation`.
