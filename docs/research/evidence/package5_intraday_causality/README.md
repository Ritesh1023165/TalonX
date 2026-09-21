# Package 5 — Intraday Causal Execution & Post-Cost RRR Research-Lab Hardening

**Status: EVIDENCE BUNDLE. See the final report (delivered in-conversation) for the
PACKAGE5_* verdict.** This document is the durable record; it does not itself
carry authority beyond what it evidences.

## 0. Repository state

- Repository: `Ritesh1023165/TalonX`, branch `feature/task131-option-a-integration`.
- Starting SHA for this package: `1e2233c` (Package 4, clean).
- Production-safety check (re-run immediately before runtime-sensitive work, per
  this package's own instruction not to assume Package 3's earlier "no live
  process" finding still holds): confirmed no live TalonX process running.
  The only `python.exe` processes present were this package's own prior
  background `pytest` invocations (command lines directly inspected via
  `Get-CimInstance Win32_Process`); `talonx.pids.json` does not exist;
  `v2_lane.db` last modified 2026-09-15 (untouched by this package's work);
  no `paper_trading.db` present. **No launch, restart, stop, or production-DB
  mutation was performed.**

## 1. Scope discipline

This package is **methodology hardening**, not alpha-seeking. Per
`docs/product/DECISION_LOG.md` (Session 12, "Agreed release decisions" /
"Agreed staging order"): intraday is Research-Lab-only for the first
release; Package 5 exists to build/verify the Research-Lab-only *execution
and evidence discipline* that decision requires, not to make intraday
signal-frequent or profitable.

**Explicit scope note on prior-research reconciliation**: `DECISION_LOG.md`
also states the *comprehensive* mandatory prior-research review (`S12-01`)
"remains a distinct, separately-scoped future task" not discharged by this
or any prior package. Section 9 below (the P5-H table) is **narrower**: it
classifies only the specific prior experiments whose *causal-execution/RRR
methodology* this package's own audit needed to either confirm-as-precedent
or avoid silently repeating. It is not offered as, and does not claim to be,
the `S12-01` review.

No strategy tuning, no filter weakening, no profitability search, no
universe expansion, no V2 change, and no release integration were performed
or attempted anywhere in this package's work.

## 2. What was investigated (read-only, before any test was written)

Full reads: `talonx_backtest/engine.py` (970 lines), `execution.py` (305
lines), `portfolio.py` (107 lines), `reproducibility.py` (267 lines).
Targeted reads: `reports.py`, `metrics.py`, `data.py`, `analysis.py`
(cost-sensitivity). Direct grep-verification (not just doc-trust) of the
live scanner's Closed-Bar Evaluation in `talonx_quant/consumer.py` (~lines
1413-1428). Full read of `docs/modules/quant.md` (7 rounds of prior live-
scanner audits, all already fixed, not Package 5's job to redo). Targeted
reads of `docs/research/TALONX_RESEARCH_LEDGER.md` (Task 24/25A/25A.1/
25-LIVE-CAPTURE/25B/25C) plus, once located outside that ledger (see §9),
`results/task73s_regression_and_zero_trade_diagnosis/` and
`results/task74s_bounded_long_only_evaluation/`.

## 3. P5-A — Causal-flow map

```
 historical 1m OHLCV row (closed the instant it's read; no
 partial-bar state exists for backtest data)
        |
        v
 compute_indicators()/HTF aggregation  <-- SAME free functions as
        |                                  talonx_quant live scanner
        v
 evaluate_signals() -> candidate QuantSignal(s), timestamped to
   the CLOSED bar that produced them (bar_timestamp)
        |
        v
 gate pipeline (imported unchanged from talonx_quant.consumer):
   session/blackout -> loss-lockout -> cooldown -> confluence ->
   R:R -> HTF trend -> premarket-liquidity -> volatility
   (each drop = one _reject(symbol, REASON, count, timestamp) --
    one gate, one stable reason string, never merged/silenced)
        |
        v  (signal survives every gate)
 throttle queue -> _revalidate() at flush time (re-checks
   geometry/R:R/data-availability as of the REVALIDATION bar,
   never the original candidate bar)
        |
        v
 _pending_entry scheduled for the CURRENT bar
        |
        v
 NEXT bar's OPEN -> _finalize_fill_geometry() (re-anchors or
   rejects GEOMETRY_INVALIDATED_AT_FILL if the fill price has
   invalidated the screening-time stop/target) -> TradeSimulator.
   open_position() [fee/slippage/spread applied here, entry-side]
        |
        v
 each subsequent bar: check_bar_for_exit() against stop/target
   (deterministic same-bar rule, default stop_first) OR
   SIGNAL_EXIT (bearish-while-long) OR END_OF_SESSION OR DATA_END
        |
        v
 TradeSimulator.close/force_close() [fee/slippage/spread applied
   here, exit-side] -> Trade{gross_pnl, net_pnl, gross_R, net_R,
   every timestamp, MFE/MAE, exit_reason}
        |
        v
 BacktestResult.trades / .rejections -> metrics.metric_set()
   (BOTH gross and net PerformanceMetrics) -> reports.
   result_summary_json() (period/symbols/execution_assumptions/
   is_zero_cost_run()/reproducibility/rejections_by_reason)
```

**Per-stage findings** (all CONFIRMED by direct code read, not by trusting
documentation):

| Stage | Timestamp/bar used | Future-info risk | Live/paper/backtest code-path identity |
|---|---|---|---|
| Indicators/signal | the CLOSED bar only | none — `compute_indicators`/`evaluate_signals` never see later rows (proven directly by `test_backtest_lookahead.py`'s truncated-vs-full identity, re-confirmed by this package's own `test_p5b_1_truncated_dataset_produces_byte_identical_history_up_to_cutoff`) | SAME free functions as `talonx_quant` live scanner |
| Gate pipeline | the candidate's own bar | none — gates evaluate only currently-known state (Redis-backed cooldown/loss-lockout in live; deterministic in-memory dict keyed off historical timestamp in backtest — the ONLY deliberate, documented divergence besides GLOBAL_RISK_DEGRADED/UK-window/premarket-feed, all non-strategy concerns) | shared gate functions, `_GATE_NAMES` table shared verbatim |
| Entry fill | the bar AFTER the signal's bar, at that bar's OPEN | none — never the signal bar's own close | `talonx_paper`'s live fill-geometry validation (Task 25B) mirrors this next-bar convention |
| Stop/target | deterministic `check_bar_for_exit`, `stop_first` default | none — same-bar ambiguity resolved conservatively, not optimistically | shared `talonx_backtest.execution` module |
| Cost | `apply_entry_cost`/`apply_exit_cost`, bps-based, default 0.0 | n/a | backtest-only cost model; live/paper apply no cost model at all currently (see §7) |
| Evidence | `Trade` dataclass, every field timestamped | n/a | backtest-only record; not shared with live ledgers (see §8, research isolation) |

## 4. P5-B — Lookahead / same-bar execution audit

**No causal or lookahead defect found.** Confirmed by:
- Direct code read of `engine.py`'s own module docstring (explicit
  Requirement-3 discussion) and `run()`'s bar-by-bar loop.
- The pre-existing `tests/test_backtest_lookahead.py` (32 tests total with
  `test_backtest_execution.py`) passing cleanly at baseline (confirmed via
  targeted re-run, 32 passed).
- This package's own `test_p5b_1_signal_off_bar_n_cannot_fill_at_bar_n_close`
  and `test_p5b_1_truncated_dataset_produces_byte_identical_history_up_to_cutoff`
  (see §10) as an explicit, Package-5-labeled re-confirmation.
- Direct grep-verification that the LIVE scanner (`talonx_quant/consumer.py`
  ~1413-1428) independently implements Closed-Bar Evaluation the same way
  (`bar_just_closed` computed and `closed_bar_df` captured BEFORE
  `_update_1m_buffer(event)` runs).

**Explicit causal-execution rule (confirmed, not newly created)**: a signal
generated off a closed bar may only fill at the NEXT bar's open; the
signal's own bar's close/high/low may never be used as a fill price.

## 5. P5-C — Entry-price authority

- **Source**: the bar immediately following the signal's own bar; **price**:
  that bar's `open` (never a synthetic mid, never the signal bar's own
  close).
- **Missing price**: `talonx_backtest.data.check_data_quality` tracks
  `nan_values`/`invalid_prices`/`missing_bars` explicitly per symbol — a
  missing price is counted and surfaced, never fabricated as zero or
  silently dropped from the count. Confirmed directly (this package's own
  `test_p5c_3_missing_price_is_flagged_not_fabricated_as_zero`).
- **Stale/invalidated bracket at fill time**: `_finalize_fill_geometry`
  (Task 13/25B lineage) either re-anchors the stop/target bracket to the
  REAL fill price or rejects the fill outright (`GEOMETRY_INVALIDATED_AT_FILL`)
  — never silently opens a position whose bracket no longer makes sense for
  the price it actually filled at.

## 6. P5-D — Stop/target same-bar ambiguity

Confirmed already fully implemented (`talonx_backtest/execution.py::check_bar_for_exit`)
and already tested (`test_backtest_execution.py`). This package adds explicit,
Package-5-labeled boundary coverage: stop-only, target-only, neither, both
(conservative `stop_first` default AND the alternate explicit
`target_first` configuration), and gap-through-stop (a bar whose own low is
far below the stop is still caught by the same high/low comparison — no
special-cased "gap" carve-out that would silently skip it).

## 7. P5-E — Gross vs. post-cost RRR

Both `gross_R`/`net_R` and `gross_pnl`/`net_pnl` are computed on every
`Trade`; `metrics.metric_set()` computes a full `PerformanceMetrics` for
each. **Current cost-model assumption**: `ExecutionConfig()`'s defaults are
all zero (`entry_slippage_bps=0.0`, `exit_slippage_bps=0.0`,
`spread_bps=0.0`) — this is an explicit, disclosed baseline
(`reports.is_zero_cost_run()` returns `True` and `result_summary_json()`
embeds a literal `"zero_cost_baseline_warning": true` flag), not a hidden
assumption. **This package invents no new numerical cost assumption** — the
10/5/5 bps illustrative figures used in one of this package's own tests
(`test_p5e_10_gross_and_net_r_diverge_under_a_nonzero_cost_model`) are
TEST-ONLY, to prove the mechanism diverges gross from net under cost; they
are not proposed as a calibrated research parameter.

**Mechanism-correctness vs. numerical-assumption-validity, kept distinct**:
the machinery to compute post-cost RRR is complete and correct; whether the
current zero-cost baseline (or any other bps figure) is the *right*
assumption for intraday specifically is an open, unresolved calibration
question — same status as V2's own zero-fee assumption (Package 4,
`OPS-014`/S10-22). Not resolved here; not a Package-5 acceptance failure
per the task's own explicit rule.

## 8. P5-F — Realized-R / trade-outcome evidence

`Trade` (portfolio.py) already carries every field required for full
reconstruction: `signal_timestamp`, `entry_timestamp`, `entry_price`,
`stop_price`, `target_price`, `exit_timestamp`, `exit_price`,
`exit_reason`, `gross_pnl`, `net_pnl`, `gross_R`, `net_R`, MFE/MAE.
Reconciliation confirmed directly:
`gross_R == (exit_price - entry_price) / abs(entry_price - stop_price)` for
a real TARGET-exit trade (this package's own
`test_p5f_11_realized_r_reconciles_with_persisted_execution_economics`).

## 9. P5-G — Research account isolation

Confirmed at the **import-boundary** level (AST-parsed, not string-grepped,
to avoid false negatives/positives from comments or string literals):
- `talonx_dispatch/`, `talonx_v2/`, and `talonx_ops/dashboard_read.py`
  (primary-delivery / first-release-accounting / primary dashboard) contain
  **zero** imports of `talonx_backtest`, anywhere.
- `talonx_backtest/` contains **zero** imports of `talonx_v2` or
  `talonx_paper` (Original's live/paper ledger) anywhere.

`talonx_piv` (a separate, broader Alpaca-paper-broker research/validation
platform) reuses a small set of PURE functions from `talonx_backtest`
(`get_strategy_version`, `check_bar_for_exit`, `apply_entry_cost`,
`apply_exit_cost`) for fingerprinting/shadow-ledger purposes — this is a
one-directional, side-effect-free dependency (`talonx_piv` -> pure
`talonx_backtest` functions), not a live-ledger or accounting coupling, and
is out of this package's narrow scope to change.

## 10. Targeted tests added

`tests/test_package5_intraday_causality.py` — new file, 20 tests, mapped
1:1 to the 15 minimum required scenarios (several scenarios get 2 tests:
a mechanism unit test plus an engine-level end-to-end proof). Reuses the
project's own established fixtures rather than inventing a parallel
framework:
- `examples/data/sample_multi_trade_1m.csv` (the project's existing
  real-trade-producing CSV fixture, already used by
  `test_backtest_cost_sensitivity.py`) for every test that requires REAL
  filled/exited trades (not merely candidates) — hand-rolled synthetic
  bars were tried first and found NOT to reliably clear the full
  production gate pipeline (`LOW_CONFLUENCE`), confirming gate strictness
  is genuine, not a fixture artifact.
- The exact `QuantSignal`/`_dt()`/`_signal()`/`ExecutionConfig`/
  `TradeSimulator` fixture pattern from `test_backtest_execution.py` for
  direct mechanism unit tests (stop/target ambiguity, cost direction).
- The exact `_relaxed_config()`/`_build_bars()`/`_bars_to_df()` pattern
  from `test_backtest_lookahead.py` for the truncation-identity lookahead
  re-proof.

Result: **20 passed, 0 failed** (`452.16s`). One test-fixture bug found and
fixed during development (a multi-symbol timestamp collision in
`test_p5c_2` — `sample_multi_trade_1m.csv` carries three symbols sharing
timestamps; the fix filters by `(timestamp, symbol)`, not timestamp alone)
— a test-authoring defect, not a `talonx_backtest` defect. See final
report §14.

## 11. Targeted regression

Pre-existing, directly relevant test files re-run (none touched/modified
by this package, confirming no regression from a read-only investigation):
- `test_backtest_lookahead.py` + `test_backtest_execution.py`: 32 passed.
- `test_backtest_long_only_lifecycle.py` + `test_backtest_fill_geometry.py`
  + `test_backtest_cost_sensitivity.py` + `test_backtest_reproducibility.py`:
  76 passed.
- (Combined with an earlier confirmed 108-test run covering the same/
  overlapping files.)

No file under `talonx_backtest/`, `talonx_quant/`, `talonx_v2/`,
`talonx_paper/` was modified by this package. **Only new files were added**
(this test file and this evidence bundle) — zero risk of regressing any
protected/frozen module, including the V2 release fingerprint (unaffected
by construction, since no `V2Config`-adjacent file was touched).

## 12. Limitations / explicitly out of scope

- Whether intraday is profitable remains **unresolved** — Task 74S's own
  verdict (`INCONCLUSIVE`, `NO_ELIGIBLE_LONG_SETUPS`) stands unchanged;
  this package neither confirms nor overturns it, and does not attempt to.
- The zero-cost baseline's numerical validity for intraday specifically is
  not calibrated here (same open status as V2's zero-fee assumption).
- Task 25C's replay was **halted, never completed** (input-integrity
  defect in the live-capture window, unrelated to any backtest-engine
  causal defect) — no narrowly-targeted replay was found "strictly
  required" by this package's own investigation, since Task 25A/25B's own
  corrections were already validated at the unit-test level and
  profitability materiality is explicitly out of this package's scope (see
  §13 for the full reasoning).
- The comprehensive `S12-01` prior-research review remains a distinct,
  separately-scoped future task (see §1) — not discharged here.

## 13. P5-H — Prior-experiment classification

See the final report's §9 table (delivered in-conversation) for the full
classification (VALID_UNDER_CURRENT_METHOD / METHOD_INCOMPATIBLE /
ALREADY_REJECTED / INCONCLUSIVE / NOT_RELEVANT) covering Task 24, 25A,
25A.1, 25-LIVE-CAPTURE, 25B, 25C, 73S, and 74S. Summary conclusion: no
narrowly-targeted replay is required before this package can be accepted;
the underlying execution/causal corrections (Task 25A/25B) are already
independently unit-tested and reconfirmed by this package's own targeted
tests, and Task 25C's halt was an input-capture-integrity problem, not a
backtest-engine defect.
