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

- [Stage 2] PASS. Reproduced Task 72O's exact AAPL replay byte-for-byte
  (same bars_processed/config_hash/dataset_hash). Built the complete
  funnel: 99.47% of bars rejected LOW_VOLATILITY before any trigger; of
  6 generated candidates (all bullish, zero bearish), 4 fired outside
  market hours, 2 in-session ones scored confluence 1 and 0 (need 2).
  No pre-roll exists but is immaterial; HTF warmup was never a blocker
  for this real 1-year dataset. Timezone/session classification
  verified correct per-row. Cost affects only fill economics, never
  eligibility.
- [Stage 3] PASS, no harness defect found. New
  tests/test_task73s_control_fixture.py (3 tests, all labeled
  TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE): eligible setup reaches
  signal->order->fill->TARGET exit->ledger (reusing Stage 1's repaired
  fixture, injection point disclosed); rejected setup correctly
  excluded; readiness-blocked (insufficient warmup) setup correctly
  returns compute_indicators()=None. No code changed (no defect to
  fix) -- Stage 2's zero-trade finding stands unmodified.
- [Stage 4] COMPLETE. Classification: NO_ELIGIBLE_LONG_SETUPS.
  Profitability verdict: INCONCLUSIVE (zero trades, not negative/
  positive/validated). Protected files and EOD code confirmed unchanged
  since df6da2b via direct git diff. Zero holdouts/notifications/broker
  mutations. Full suite: 2168 passed, 0 failed, 1 skipped, 10 xfailed.
  Task 73S complete.
