# Task 77I — Integrated Safety, Alerts, Shadow Tracking and Observability

## Stage 0 — Baseline and integration plan: COMPLETE
Verified branch/SHA/clean-tree/origin-sync at `2c597c0`; corrected an environment mistake (the
shell's default `python` resolves to an unrelated global interpreter, not this repo's `.venv` —
all subsequent commands used `.venv/Scripts/python.exe` explicitly). No conflicting session
(`talonx.pids.json` absent, no `python.exe` processes running). Mapped every live decision entry
point, broker path, persisted state, notification adapter, event/ledger persistence, and
dashboard/report projection. Identified the exact partial-fill accounting quirk location. See
`integration_path_map.md`, `implementation_plan.md`.

## Stage 1 — Complete runtime safety: COMPLETE
- Wired `decision_contract.decide()` into `decision_engine.py`'s live `_handle_entry`/
  `_check_exit`, hardcoding `strategy_approval_status=UNVALIDATED` for every real caller. A real
  natural BULLISH signal can no longer reach `order_intent` at all — the intended tightening.
  Proven via 12 real-`DecisionEngine` integration tests covering every required behaviour-table
  row (`test_task77i_decision_engine_wiring.py`).
- Fixed the disclosed Task 76S partial-fill accounting defect: a second fill-status transition
  on a closing sell order used to fabricate an orphan phantom `OPEN` position. Now tracks
  per-order incremental fill deltas and cumulative exit quantity/P&L correctly. See
  `partial_fill_before_after.md`.
- Hardened timed-out submissions: `UNCONFIRMED_TIMEOUT` sentinel status (fail-closed against
  oversell/pyramiding), actively resolved by `reconcile()` against a fresh broker read.
- Disclosed, not invented, cross-process concurrency posture — see
  `broker_state_and_concurrency_evidence.json`.
- New durable ledgers (`decision_ledger.py`, `notification_outbox.py`, `shadow_ledger.py`)
  introduced and wired as three structurally independent branches.

## Stage 2 — Durable execution-independent alerts: COMPLETE
`NotificationOutbox` — durable, deduplicated, bounded-retry, honest-delivery-state outbox reusing
the existing `telegram.py::sender` adapter interface. `ACTIONABLE_BUY`/`ACTIONABLE_SELL`/
`WATCH_OBSERVATION_ONLY` classification; `HOLD`/non-actionable `NO_TRADE` never notified.
Dispatch is a separate `SessionRunner` tick step, never inline with enqueue. See
`alert_delivery_contract.md`, `decision_event_schema.json`.

## Stage 3 — Causal shadow tracking: COMPLETE
`ShadowLedger` reuses `talonx_backtest.execution`'s already-tested pure functions
(`check_bar_for_exit`, `apply_entry_cost`/`apply_exit_cost`) and replicates the historical
backtest's own next-bar-open, non-lookahead fill convention. Deliberately gated on the SAME
actionability bar as real PAPER execution (see `shadow_simulation_policy.md` for why). Zero
structural coupling to `lifecycle.py`/`broker.py` (grep-confirmed). See
`shadow_simulation_policy.md`, `shadow_test_results.csv`.

## Stage 4 — Observability and integrated offline verification: COMPLETE
`observability.py::build_integrated_projection` — a new, minimal, read-only cross-ledger
projection (no existing PIV-native dashboard surface beyond `reporting.py`/`telegram_inbound.py`
existed; the repository's actual web dashboard is a wholly unrelated subsystem with zero
`talonx_piv` awareness, confirmed by grep). `reporting.py::build_session_report` gained one
additive, optional `integrated_projection` passthrough parameter — no existing report shape
redesigned. 12 accelerated end-to-end scenarios drive the ACTUAL `SessionRunner`+`DecisionEngine`
stack with fake clock/deterministic bars/fake services — see `end_to_end_scenarios.csv`.

## Verification
Full collection: **2327 collected, 0 errors** (was 2257 at Task 76S's end). Full suite:
**2316 passed, 1 skipped, 10 xfailed** (was 2246 passed) — `2316 − 2246 = 70`, exactly matching
the 70 new/net-added tests (69 new-file tests + 1 net addition in
`test_task76s_broker_boundary.py`, where 1 stale partial-fill test was replaced by 2 corrected
ones). **Zero unexplained regression, zero failures.** See `test_results.txt`.

Protected files (`talonx_quant/{strategy,indicators,consumer,config}.py`) and
`talonx_piv/eod_lifecycle.py`: zero diff since `2c597c0`.

## Recommendation
Next task: full application orchestration and offline failure/recovery rehearsal — see
`remaining_integration_work.md` for the specific gaps (strategy-approval registry, decision-ledger
write-back fields, provider-identity threading) that task would naturally close.
