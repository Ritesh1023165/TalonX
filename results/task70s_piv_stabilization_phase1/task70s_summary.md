# Task 70S -- PIV Stabilisation Phase 1: Alpaca IEX Historical Warmup and Readiness Correctness

**Mode:** PAPER / NO REAL CAPITAL. No order was submitted, no broker-trading
endpoint was called, and no live PIV trading session was started at any
point in this task.

## 1. Root cause (Phase A)

On 2026-08-26, Task69R attempt 1 failed with
`WARMUP_CATASTROPHIC_FAILURE_ZERO_SYMBOLS_READY` at 04:19 ET
(`session_id=piv_2026-08-26_041902_1f17993c`). All 35 symbols reported
`INSUFFICIENT_1M_HISTORY` with only 18-20 1-minute bars against a
required 120 (the 15-minute HTF leg succeeded 200/200 for every symbol via
the same yfinance provider).

The entry point is `talonx_piv/warmup.py::preseed_and_verify`, which calls
`scanner.preseed_symbols()` (`talonx_quant/consumer.py`), which in turn
calls `talonx_quant/preseed.py::fetch_1m_history` --
`yfinance.Ticker(symbol).history(period="1d", interval="1m", prepost=True)`.
`period="1d"` is a **relative, wall-clock-anchored** window: at 04:19 ET
(19 minutes after the 04:00 ET pre-market open), yfinance's own "1 day" of
1-minute data had only accumulated ~18-20 real minutes of trading activity
to return -- there is no PRIOR trading day's data available in that
response at all. This is not a bug in this repo's code; it is an inherent
property of yfinance's `period=` semantics combined with querying very
early in the trading day. It matches the exact limitation this repo's own
prior `talonx_piv/alpaca_historical_warmup.py` docstring (Task 69Q Part 9)
had already documented and built a (previously unwired) prototype fix for.

**Why the 15-minute HTF leg was unaffected:** `preseed_15m_period="1mo"`
(a full month lookback) always has ample prior-session data regardless of
what time of day the process starts -- only the 1-minute leg's `1d` window
is time-of-day-sensitive in this way.

## 2. Files changed

- `talonx_piv/alpaca_historical_warmup.py` -- extended (the original Task
  69Q single-page `fetch_1m_bars` prototype is preserved, unchanged in
  external behavior) with a new `run_alpaca_1m_warmup()`: causal,
  paginated, bounded-retry Alpaca IEX 1-minute historical fetch producing
  one of exactly 7 deterministic outcomes (READY / INSUFFICIENT_HISTORY /
  EMPTY / TIMEOUT / RATE_LIMITED / PROVIDER_ERROR / INVALID_DATA).
- `talonx_piv/warmup.py` -- `preseed_and_verify()` gained optional
  `piv_config` / `now` / `alpaca_transport` / `alpaca_sleep_fn` keyword
  parameters (all defaulted so every existing caller/test is unaffected).
  When `piv_config` carries real Alpaca credentials, each symbol's
  1-minute `RollingBarBuffer` is hydrated from Alpaca FIRST, via the
  buffer's own public `add_bar()` API -- `talonx_quant/consumer.py`,
  `strategy.py`, `indicators.py`, and `config.py` are never imported or
  modified. `scanner.preseed_symbols()` (the yfinance path) still runs
  unconditionally afterward; its own pre-existing
  `_preseed_1m_if_needed` guard (`if buffer.bar_count(symbol) >=
  min_bars_required: return`) transparently skips yfinance for any symbol
  Alpaca already sufficiently warmed, and runs exactly as before for any
  symbol it did not -- a real fallback, never a silent override in either
  direction. `WarmupCheck` gained 5 new default-valued evidence fields
  (`alpaca_attempted`, `alpaca_status`, `alpaca_bar_count`,
  `alpaca_reason`, `bar_count_1m_source`).
- `talonx_piv/decision_engine.py` -- `DecisionEngine` gained an optional
  `piv_config: PivConfig | None = None` field (distinct from its existing,
  unrelated `config: QuantConfig`), threaded into `preseed_and_verify` via
  `start()`'s new optional `now` parameter.
- `talonx_piv/cli.py` -- one line: `DecisionEngine(redis_client, bus,
  lifecycle, piv_config=config)`, so a real `start` invocation now supplies
  the outer PivConfig's Alpaca credentials to the warmup path.
- `tests/test_task70s_alpaca_warmup_stabilization.py` -- new, 26 tests (see
  Section 4).

No file in `talonx_quant/{strategy,indicators,consumer,config}.py` was
opened for editing. No order/broker-trading endpoint (`submit_order`,
`cancel_all_orders`, `close_all_positions`) is reachable from any new code
path -- every fake transport in the new test file raises `AssertionError`
if `.post()`/`.delete()` is ever called, and the full-pipeline test
(`test_full_warmup_pipeline_never_touches_order_endpoints`) exercises this.

## 3. Behaviour before versus after

See `warmup_before_after.csv` (all 35 universe symbols). Before (yfinance
alone, from the preserved attempt-1 evidence): 0/35 READY, 18-20 bars each,
`INSUFFICIENT_1M_HISTORY`. After (Alpaca-first, live-verified at the exact
same causal cutoff `2026-08-26T08:19:00Z` attempt 1 used): 35/35 READY, 726
to 1000 bars each (single page, zero retries) -- see
`readiness_by_symbol.csv` and `_live_smoke_summary.json`.

## 4. Tests and exact results

`tests/test_task70s_alpaca_warmup_stabilization.py`: **26 passed**, 0
failed (see `regression_test_results.txt` for the full run, including all
pre-existing suites). Covers: complete warmup -> READY; multi-page
pagination (including "stop once sufficient" bound); exact-cutoff and
past-cutoff future-bar exclusion; weekend-gap and holiday/early-close gap
handling; empty response; insufficient/missing-minutes; duplicate
/out-of-order/invalid-row sanitization; structurally invalid body;
timeout-then-retry and retry exhaustion; rate-limit-then-retry and
exhaustion; non-retryable 4xx (no retry); missing-credentials fail-closed;
original `fetch_1m_bars` prototype unchanged behavior; Alpaca-sufficient
skips yfinance; Alpaca-insufficient falls back to yfinance (additive
buffer, not overwritten); `piv_config=None` reproduces prior behavior
exactly; per-symbol isolation (one symbol's Alpaca failure does not affect
another); no cross-date cache reuse; no credential leakage (both at the
raw-result level and through the full `WarmupCheck`); no order/broker
endpoint ever touched.

Pre-existing suites: `tests/test_task65b_warmup.py`,
`tests/test_task69q_alpaca_historical_warmup.py`,
`tests/test_task64_piv.py`, `tests/test_task65_piv.py`,
`tests/test_task69p_telegram_piv_parity.py` -- all **62/62 still pass
unchanged**.

## 5. 35-symbol readiness evidence

Live, read-only Alpaca IEX historical-bars endpoint calls (real PAPER
account credentials already configured in this repo's `.env`; GET-only,
`feed=iex`, no order endpoint) against the full `DEFAULT_UNIVERSE` (35
symbols), at causal cutoff `2026-08-26T08:19:00Z` -- the EXACT timestamp
Task69R attempt 1 recorded. Result: **35/35 READY**. See
`readiness_by_symbol.csv` for the full per-symbol breakdown (status,
bar_count, pages_fetched, retries -- every symbol needed exactly 1 page and
0 retries).

This is real, live-read evidence (not mocked), clearly distinguished from
the mocked unit-test evidence above and labeled as such in
`_live_smoke_summary.json`.

## 6. Causality and data-integrity proof

See `causal_boundary_evidence.json`: the `end` request parameter is set to
exactly the declared causal cutoff; an independent post-fetch sanitization
pass additionally drops any bar at or after that cutoff regardless of what
the provider returned (verified empirically: 0 such drops across all 35
live symbols, and unit-tested directly for a bar placed exactly at, and
5 minutes after, the cutoff). No bar is ever fabricated, forward-filled, or
interpolated -- a row that fails to parse is dropped, never synthesized.
No cross-date warmup cache exists, so no stale prior-date state can ever be
reused (`test_no_cross_date_reuse_each_call_recomputes_from_current_cutoff`).

## 7. Limitations

See `stabilization_remaining_issues.md`'s final section -- summarized:
`REQUIRED_1M_BARS` (120, hardcoded in `talonx_piv/warmup.py`) and
`QuantConfig.min_bars_required` (120, env-overridable) are independently
configurable and only coincidentally share a default; raw (unadjusted)
bars are requested, matching every other Alpaca call already in this repo,
so a corporate-action split falling inside a ~10-day warmup lookback could
in principle show a discontinuity (not re-audited here, and much
lower-stakes for a short intraday-indicator warmup than the multi-day
return strategy already flagged in the separate research worktree); the
10-calendar-day default lookback is not trading-calendar-aware but was
empirically sufficient for every live symbol tested.

## 8. Remaining stabilisation issues

Retained without implementation in `stabilization_remaining_issues.md` --
opening-minute semantics, staleness isolation/recovery, Alpaca
provider-health reporting, cross-date readiness persistence, EOD/live
session identity linkage, dashboard scope/counter reconciliation, unified
orchestration, execution-independent alerts/shadow ledger, long-only
enforcement, premarket WATCH/validated-alpha separation, complete PAPER
end-to-end verification.

## 9. Branch, starting/final SHA

- Branch: `research/talonx-strategy-validation`
- Starting HEAD: `636fa9c08092f250a95b20081a8be641a60ce158`
- Starting working tree: clean (verified)
- Final HEAD: see git log after the commit described in Section 10.

## 10. Commit/push status

See the final report message for the actual commit SHA and push outcome
(this document is written before that step; the git-instructions gate --
one atomic commit only if every acceptance criterion passes -- is applied
after this file is written, using the full regression run captured in
`regression_test_results.txt`).

## 11. Final verdict

See the final chat-message report (Section titled "Final verdict") for the
PASS/PARTIAL/BLOCKED determination made after the full regression suite
completed.
