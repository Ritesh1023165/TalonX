# Task 73S -- Close Regression Failure and Diagnose Zero-Trade Replay

## Stage 0 -- Baseline verification: PASS
Branch/HEAD/tree verified, no concurrent session. `BacktestEngine` reuses
QuantScanner's private gate functions directly (not the live class);
long-only is Task24/25A's hardcoded engine behavior; "5/5/10bps" =
20bps total round-trip cost, verified from `talonx_backtest/execution.py`
directly. Known test reproduced failing before any change. See
`stage0_baseline_audit.md`.

## Stage 1 -- Regression fixture repair: PASS
Independently re-verified Task 72O's `TEST_ISOLATION_DEFECT`
classification but corrected the cited mechanism: the rejected candidate
is a BEARISH `macd_bearish_cross` blocked by the MACD no-self-credit rule
(commit `83aee8b`, 2026-08-22), not an RSI-recovery candidate blocked by
the RSI-curl rule (`3c97d9d`) as previously stated -- confirmed directly
via `--research-telemetry`. Found and resolved a second, independent
blocker (the 200-bar HTF trend gate, which a 2-day fixture can never
satisfy), corroborated by a pre-existing xfail marker in
`tests/test_backtest_sample_data.py` anticipating exactly this fix.
Repaired `examples/data/sample_AAPL_trade_1m.csv` by construction only
(pre-roll + a calibrated bullish recovery, empirically verified against
the real unmodified indicator/strategy code at every step) -- produces
exactly one trade, TARGET exit. Full suite: 2165 passed, 0 failed, 1
skipped, 10 xfailed -- delta from baseline fully accounted for. Committed
`13328eb`, pushed. See `stage1_root_cause.md`, `stage1_fixture_diff_explanation.md`.

## Stage 2 -- Zero-trade reproduction and funnel: PASS
Reproduced Task 72O's exact AAPL/2025-08-15..2025-12-31/5-5-10bps replay
byte-for-byte (same `bars_processed`, `signals_generated`,
`config_hash`, `dataset_hash`). Built the complete funnel
(`stage2_funnel.csv`): 67,002 bars, 99.47% rejected `LOW_VOLATILITY`
before any trigger check; of the 6 candidates that DID form, 4 fired
outside market hours (correctly rejected `US_MARKET_SESSION_CLOSED`) and
the 2 in-session ones scored confluence 1 and 0 against a required
minimum of 2. Zero pre-roll exists but is immaterial (RSI/MACD/ATR/HTF
all warm up within the first ~8 trading days of a 4.5-month window;
`HTF_DATA_UNAVAILABLE` never appears). Timezone/session classification
independently verified correct per-row. Cost assumptions affect only
fill economics, never eligibility (verified from code). See
`stage2_zero_trade_diagnosis.md`.

## Stage 3 -- Harness reachability proof: PASS, no defect found
Three labeled `TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE` control cases
(new test file `tests/test_task73s_control_fixture.py`, 3/3 passing):
(1) an eligible setup (reusing Stage 1's repaired fixture, injection
point disclosed) reaches signal publication -> order -> fill -> TARGET
exit -> ledger; (2) a rejected setup (the fixture's own pre-existing
bearish candidate) is correctly excluded from every downstream stage;
(3) a readiness-blocked (insufficient-warmup) setup correctly returns
`compute_indicators() is None`, and `talonx_backtest/engine.py`'s
pre-existing `if snapshot is None: return` guard skips it with zero
fabricated data. No harness defect exists; no code changed in Stage 3;
the Stage 2 zero-trade finding stands unmodified. See
`stage3_control_fixture_evidence.json`, `stage3_harness_before_after.md`.

## Stage 4 -- Verdict
**Classification: NO_ELIGIBLE_LONG_SETUPS.**
Software correctness and profitability are kept separate: the harness
and strategy code are proven correct (Stages 1 and 3); the AAPL/
2025-08-15..2025-12-31 zero-trade outcome is a genuine, evidence-
supported absence of a qualifying setup for this specific
symbol/window/config, NOT a bug. Per this task's own instruction, zero
trades means profitability here is **INCONCLUSIVE** -- not profitable,
not unprofitable, not validated.

## Files changed / commits
- Stage 1 (committed `13328eb`, pushed): `examples/data/sample_AAPL_trade_1m.csv`,
  `tests/test_backtest_sample_data.py`, plus Stage 0/1 evidence.
- Stage 2/3/4 (this commit): `tests/test_task73s_control_fixture.py` (new),
  Stage 2/3/4 evidence artifacts. No `talonx_backtest` code change (no
  defect found).

## Protected files / EOD code
Zero diff since `df6da2b` in `talonx_quant/{strategy,indicators,consumer,config}.py`
or `talonx_piv/{eod_lifecycle,session_runner,cli,events}.py` -- verified
directly via `git diff df6da2b..HEAD`.

## Holdouts / notifications / broker mutations
Zero reserved holdouts accessed (only `data/historical_1m/task7b_alpaca_long_history`,
already used by Task 72O). Zero external notifications (no Telegram/Gemini
call anywhere in this task). Zero broker mutations (all backtest runs are
pure offline simulation via `talonx_backtest.TradeSimulator`; the Stage 1
test-suite runs use `AlpacaPaperClient`-style fakes only where PIV code
paths are touched at all, which this task never does).

## Full test results
See `stage1_test_results.txt`, `stage1_full_suite_results.txt`,
`stage4_final_full_suite_results.txt` (final, after the Stage 3 test
file addition).
