# Stage 0 -- Baseline Verification

1. **Branch/HEAD/tree:** `research/talonx-strategy-validation` @
   `df6da2ba0d9a369a943b37d54dd71fd07319fbba` (full SHA, matches
   expected). Working tree clean. Origin fetched and confirmed identical
   (`origin/research/talonx-strategy-validation` == local HEAD).
2. **Concurrent use check:** no PIV/quant Python process running
   (`ps -W` shows only an unrelated VS Code extension helper);
   `lifecycle_state.json`: `session_enabled=False`, `kill_switch=False`;
   no `.pid`/`.lock` files at repo root. Safe to proceed.
3. **Prior evidence read:** `task72o_morning_report.md`,
   `stage2_root_cause.md`/`stage2_before_after.json`/
   `stage2_failure_reproduction.txt`, `stage3_preregistration.json`,
   `stage3_run_log.txt`, `stage3_profitability_verdict.md`.

## 4. QuantScanner class/version and long-only selection mechanism

**The Task 72O replay did NOT instantiate `talonx_quant.consumer.QuantScanner`
at all.** `talonx_backtest/engine.py`'s `BacktestEngine` imports and reuses
QuantScanner's own PRIVATE gate-evaluation helpers directly
(`_GATE_NAMES`, `_confluence_eligible`, `_evaluate_active_volatility_gate`,
`_fails_min_volatility`, `_opportunity_score`, `_partition`,
`_trend_gate_applicable` from `talonx_quant.consumer`) plus
`talonx_quant.strategy.evaluate_signals`/`calculate_trade_geometry`
directly -- a purpose-built, single-pass replay harness that reuses the
SAME underlying decision primitives as the live class, under its OWN
orchestration (not `QuantScanner.__init__`/`_handle_market_tick`/
`_publish_signal`). Task 72O's own preregistration description
("code_location: talonx_quant/strategy.py + consumer.py + indicators.py")
is accurate at the FUNCTION level but should not be read as "the live
QuantScanner class was executed as-is."

**Long-only is hardcoded engine behaviour, not a per-run configuration
choice.** `talonx_backtest/engine.py`'s own module docstring (lines
63-83): Task 24/25A (2026-08-20, `results/task24_requirements_parity_audit/`
+ `results/task25a_long_only_parity_fix/`) corrected a PRIOR bug where
this engine opened genuine shorts on BEARISH signals. Current, unmodified
behaviour: FLAT+BULLISH -> schedule a long entry; LONG+BULLISH -> no
additional position; FLAT+BEARISH -> no position opened
(`NO_ACTIVE_POSITION`, matching `talonx_paper`); LONG+BEARISH -> schedules
an exit only (`SIGNAL_EXIT`). `TradeSimulator.open_position` raises
(fail-closed) if ever handed a non-BULLISH signal. This is unconditional
engine logic, confirmed by a dedicated prior parity audit
(`long_short_flow.md`) -- not something Task 72O's run selected via a flag.

## 5. Meaning/units of "5/5/10bps" -- from `talonx_backtest/execution.py` directly

```python
def apply_entry_cost(raw_price, direction, config):
    total_bps = config.entry_slippage_bps + config.spread_bps / 2.0
    return _apply_cost(raw_price, direction, "entry", total_bps)

def apply_exit_cost(raw_price, direction, config):
    total_bps = config.exit_slippage_bps + config.spread_bps / 2.0
    return _apply_cost(raw_price, direction, "exit", total_bps)
```
`_apply_cost` moves price AGAINST the trader by `bps/10_000` of price
(e.g. 5bps = 0.05% = price * 1.0005 worse for a BULLISH entry). The
`spread_bps` field is a ROUND-TRIP spread, HALVED and charged separately
on each side (half at entry, half at exit) -- it is NOT an additional
5bps/5bps on top of a separately-modeled full spread. Task 72O's
"5/5/10bps" therefore means: entry_slippage=5bps + spread/2=5bps = 10bps
total entry-side cost; exit_slippage=5bps + spread/2=5bps = 10bps total
exit-side cost; **20bps total round-trip cost per trade** (0.20% of
notional). Confirmed directly from code, not assumed from the CLI flag
names alone.

## 6. Known failing test reproduced before any change

`.venv/Scripts/python.exe -m pytest tests/test_run_historical_regimes.py::test_real_end_to_end_run_against_the_sample_trade_dataset -q`
-> **1 failed in 6.98s** (see `stage0_repro_before.txt`). Identical
failure to Task 72O's own characterization.

## Verdict
No discrepancy from the expected baseline. **NOT BLOCKED.** Proceeding to
Stage 1.
