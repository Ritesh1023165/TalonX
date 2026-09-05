# Stage 0 -- Baseline and Task 71S-R1 Audit

- Branch: research/talonx-strategy-validation
- HEAD: 3fa0c51 (confirmed, matches expected)
- Working tree: clean
- Origin: in sync (origin/research/talonx-strategy-validation == 3fa0c51)

## d1764a8..3fa0c51 diff review
17 files changed: talonx_piv/{freshness,gap_forensics,session_runner}.py,
2 test files, 12 results artifacts. No talonx_quant file. No cli.py/
decision_engine.py/broker.py/lifecycle.py changes.

## Confirmations
- `CONFIRMED_NO_IEX_TRADE`: zero references in talonx_piv/ or tests/
  except one negative assertion (`assert not hasattr(gf,
  "CONFIRMED_NO_IEX_TRADE")`) proving it was fully retired. Renamed to
  NO_IEX_BAR_OBSERVED, an honest aggregate-bar-only label.
- No unsupported trade-level claim remains (grep-verified).
- No alpha/order path changed: `on_bars` has exactly one call site
  (session_runner.py:331), gated by `decision_eligible` = `_ready_symbols
  & warmup_ready_symbols`, further filtered (subtractive only) by
  freshness state. `_check_stale` (the widened observational monitoring)
  contains zero references to `decision_engine`/`on_bars` -- confirmed by
  direct grep; it cannot call on_bars under any code path.
- Recovery cannot bypass readiness: `observe_fresh`/DATA_RECOVERED only
  clear the freshness-layer STALE/DATA_GAP exclusion; the two upstream
  gates (`_ready_symbols`, `warmup_ready_symbols`) are untouched dataclass
  fields set only by `_finalize_readiness` (09:30-09:59 window) and
  `DecisionEngine.start` (historical warmup) respectively -- neither is
  written to by freshness.py or gap_forensics.py.

## Targeted tests
tests/test_task70s_alpaca_warmup_stabilization.py +
tests/test_task71s_data_freshness_stabilization.py +
tests/test_task71s_r1_live_iex_semantics.py +
tests/test_task65_session_runner.py + tests/test_task65b_warmup.py:
**95 passed, 0 failed.**

## Known full-suite baseline (recorded, not re-run this stage)
2137 passed, 1 failed (test_run_historical_regimes.py::test_real_end_to_end_run_against_the_sample_trade_dataset),
1 skipped, 15 xfailed (per Task 71S-R1's own regression_test_results.txt).

## Verdict
No unrelated decision/order change found. **NOT BLOCKED.** Proceeding to
Stage 1. No commit required (read-only audit).
