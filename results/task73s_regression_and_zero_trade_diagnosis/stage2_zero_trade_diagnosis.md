# Stage 2 -- Zero-Trade Diagnosis

## Reproduction

Byte-for-byte identical to Task 72O: `bars_processed=67002,
signals_generated=6, signals_published=0, trades_executed=0`,
`config_hash`/`dataset_hash` match exactly (see
`stage2_reproduction_manifest.json`). Written to
`results/task73s_regression_and_zero_trade_diagnosis/stage2_reproduction/`
-- Task 72O's own evidence is untouched.

## Complete funnel

See `stage2_funnel.csv` (13 items, units explicitly labeled, no forced
reconciliation between bars/candidates/signals -- these are genuinely
different countable things and are reported as such).

## Answers to the specific investigation questions

**Was the intended scanner actually invoked?** Not the live `QuantScanner`
class itself -- `talonx_backtest.BacktestEngine` reuses QuantScanner's own
private gate functions (`_fails_min_volatility`, `_confluence_eligible`,
etc.) and `talonx_quant.strategy.evaluate_signals` directly, under its own
orchestration (see `stage0_baseline_audit.md` item 4). This IS the
intended, designed replay path for this kind of offline evidence -- not a
misconfiguration.

**Did sufficient causal pre-roll exist?** No pre-roll exists (the file's
own earliest row IS the requested start), but this is immaterial: RSI/MACD/
ATR settle within ~120 bars and the 200-bar HTF SMA within ~8 trading
days, both negligible against a 4.5-month window, and `HTF_DATA_UNAVAILABLE`
never appears in the rejection breakdown -- confirming this was NOT a
blocking factor (contrast with Stage 1's tiny 2-day fixture, where it
WAS the dominant blocker).

**Were evaluation dates/time zones correct?** Verified directly: every
candidate telemetry row's `session` tag matches its own timestamp
converted to America/New_York -- e.g. `2025-10-10 21:22:00+00:00` ->
17:22 ET (`closed`, correctly outside 09:30-16:00); `2025-10-10
15:10:00+00:00` -> 11:10 ET (`regular`, correctly inside). No tz bug found.

**Did readiness block most or all evaluation?** `talonx_backtest` has no
separate PIV-style readiness validator (see Stage 0 finding). The
functional analogue -- the volatility gate -- blocked 66,648/67,002
(99.47%) of ALL bars from ever reaching a trigger check. This is the
single largest filter in the entire funnel, and it is exactly the
documented, unmodified `min_atr_pct=0.25` gate (Task 70S/71S's own
findings already established AAPL as a comparatively low-relative-
volatility name against this gate over ordinary windows).

**Were long candidates generated?** Yes -- all 6 generated candidates
were BULLISH (long-compatible). Zero bearish candidates were generated at
all in this window (not a bug; simply how AAPL's RSI/MACD/MA state
happened to align over these 4.5 months).

**Were valid outputs filtered by an adapter?** No adapter-level filtering
exists between `evaluate_signals`'s raw output and the recorded
telemetry/rejections -- every one of the 6 generated candidates has a
telemetry row AND a matching rejection-reason row; nothing is silently
dropped between generation and rejection-logging.

**Did a long-only filter discard short outputs as intended?** N/A here --
zero short candidates were ever generated to discard. (Stage 1's
independent fixture-repair work separately confirmed the long-only filter
itself works exactly as designed for a genuine bearish candidate.)

**Did published signals fail to reach the simulator?** N/A -- zero
signals were ever published (all 6 rejected before publication), so there
is nothing for the simulator to have failed to receive. `trades.csv`/
`trades.json` are correctly empty (header-only / `[]`), not missing or
malformed.

**Were exceptions or empty outputs treated as successful completion?**
No. `exit_code=0` reflects a genuinely completed run with a real,
non-exceptional zero-trade outcome -- `rejections_by_reason` accounts for
every one of the 6 generated candidates (4+2=6), and the empty
trades/equity-curve outputs are the CORRECT shape for zero trades (see
Stage 1's `test_smoke_dataset_output_files_are_valid_with_zero_trades`
for the established, already-tested convention this run's outputs match).

**Did the cost configuration affect eligibility or only economics?**
Only economics. `entry_slippage_bps`/`exit_slippage_bps`/`spread_bps` are
applied in `talonx_backtest/execution.py`'s `apply_entry_cost`/
`apply_exit_cost` -- called ONLY after a trade is already opened/closing,
computing the FILL PRICE. Nothing in `talonx_quant/strategy.py`'s gates
(volatility, confluence, structural R:R, session/blackout) ever reads
`ExecutionConfig`. Cost could not possibly have caused the zero-trade
outcome here, since zero signals ever reached publication in the first
place -- cost is entirely downstream of that point.

## Root cause of the zero trades

**NO_ELIGIBLE_LONG_SETUPS** for this specific symbol/window/configuration
combination: the (unmodified, intentionally strict) volatility gate
eliminated 99.47% of all bars outright; of the tiny remainder that
produced a trigger, most (4/6) fired outside market hours entirely
(correctly rejected), and the two that fired during regular hours scored
confluence 1 and 0 respectively against a required minimum of 2. This is
a genuine, evidence-supported "the strategy correctly found nothing to do
here," not a data problem, not a harness defect, and not a
configuration/adapter mismatch.
