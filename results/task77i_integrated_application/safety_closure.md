# Task 77I Stage 1 — Runtime Safety Closure

## 1. Decision contract wired into the actual runtime path
`talonx_piv/decision_engine.py::DecisionEngine._handle_entry`/`_check_exit` now call
`talonx_piv.decision_contract.decide(...)` before taking any action, with
`strategy_approval_status` hardcoded to `StrategyApprovalStatus.UNVALIDATED` for every real
caller (a `strategy_approval_status_override` field exists ONLY for
`TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE` construction sites; `cli.py` never sets it --
confirmed by both `grep` and `test_task77i_decision_engine_wiring.py::test_grep_confirms_cli_never_sets_the_test_only_override`).

**Consequence, stated plainly**: a real, natural QuantScanner BULLISH signal can no longer
reach `order_intent` at all, regardless of `paper_entry_settings.json`. This is the intended
tightening this stage exists to produce -- see `implementation_plan.md`.

## 2. Integration-level proof (not just direct decide() calls)
`tests/test_task77i_decision_engine_wiring.py` drives the REAL `DecisionEngine` (real
`QuantSignal`/`Bar` objects, a fake Redis pubsub, a fake broker transport) through:
- Bearish while flat -> zero broker orders, decision recorded `NO_TRADE`.
- Unvalidated + bullish + PAPER-enabled -> STILL zero broker orders (the actual production
  posture).
- Approved + bullish -> reaches the broker (proves the wiring is real, not merely disabled).
- PAPER entry disabled -> `recommendation` stays `BUY`, only `decision_execution_status`
  downgrades; still fully recorded, alerted, and shadow-tracked.
- Existing long, no exit condition -> `HOLD`, no sell.
- Existing long, stop hit -> `SELL_TO_CLOSE`, sell reaches the broker.
- Bearish signal while holding -> position remains held (no exit invented from market_view
  alone).
- A synthetic APPROVED fixture is provably unreachable from `cli.py`'s own construction path.

## 3. Partial-fill accounting
Fixed in `lifecycle.py::apply_broker_update` -- see `partial_fill_before_after.md` for the full
before/after and proof tests. Affects: remaining holdings (now tracked correctly via
`remaining_quantity`), pending exit reservations (unchanged, already correct pre-existing
logic, now operating on the correct `remaining_quantity`), filled-vs-remaining order quantities
(now distinguished via per-order incremental deltas), duplicate exits (the exact phantom-
position bug this closes), reconciliation (no more false-positive internal open position risk).

## 4. Broker-state and concurrency protection
See `broker_state_and_concurrency_evidence.json` for the full, disclosed accounting of what is
proven versus what is explicitly NOT invented (no new cross-process file-locking architecture --
none existed before this task, and none is required given no code path outside the single live-
session process ever reaches `order_intent`).

## 5. Shadow holding never authorises a broker SELL
Structural, not merely behavioral: `shadow_ledger.py` has zero import of or reference to
`lifecycle.py`/`broker.py`/`order_intent` anywhere in the module (confirmed by `grep` -- see
`broker_state_and_concurrency_evidence.json`). The two systems share only a read-only
`decision_id` cross-reference.

## 6. Existing protection and EOD remain available when new entries are disabled
Unchanged from Task 76S and re-confirmed here: `tests/test_task76s_protective_exit_eod.py`'s
7 tests plus `tests/test_task72o_eod_lifecycle.py`'s 22 tests both pass unchanged after this
stage's `lifecycle.py` edits -- `eod_lifecycle.py` itself has zero diff.

## Gate
- All new Stage 1 tests pass: `test_task77i_runtime_safety.py` (6),
  `test_task77i_decision_engine_wiring.py` (13), plus the 2 rewritten/added
  `test_task76s_broker_boundary.py` partial-fill tests.
- Zero regression in every pre-existing suite this stage touches (`test_task72o_eod_lifecycle.py`,
  `test_task76s_broker_boundary.py`, `test_task76s_protective_exit_eod.py`, `test_task64_piv.py`,
  `test_task65b_decision_engine.py`, `test_task65b_lifecycle_probe.py`) -- see `test_results.txt`
  for the full-suite reconciliation once Stage 4 closes.
- No protected strategy file touched (`talonx_quant/{strategy,indicators,consumer,config}.py`) --
  zero diff.
- No unresolved oversell/partial-fill risk deferred -- the one disclosed Task 76S follow-up item
  in this category (item 4) is closed, not carried forward.
