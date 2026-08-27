# Task 77I — Execution Journal

## Baseline
- Branch: research/talonx-strategy-validation
- Starting SHA: 2c597c0e38077c390f1c4280d84dc5816e6a4d97
- Working tree: clean at start
- origin/research/talonx-strategy-validation == 2c597c0 (in sync)
- No `talonx.pids.json` present, no python.exe processes running -- no conflicting checkout/session.
- Correction: this repo's actual test environment is `.venv` (Python 3.12.10), NOT the
  `python`/`pip` resolved by the shell's default PATH (which pointed at an unrelated global
  Python 3.14 install with neither `psutil` nor `python-telegram-bot`). All commands in this
  task use `.venv/Scripts/python.exe` explicitly from this point on.
- Dependency repair (same policy as Task 75S): `tests/test_task64_piv.py` (and everything that
  imports `talonx_piv.preflight`) failed to collect under the WRONG interpreter with
  `ModuleNotFoundError: psutil` then `ModuleNotFoundError: telegram` -- both packages are
  **already declared** in `talonx_dispatch/requirements.txt` (`psutil>=5.9`,
  `python-telegram-bot>=20.0`). This was a red herring caused by using the wrong interpreter;
  `.venv` already has both installed (`psutil 7.2.2`, `python-telegram-bot 22.8`). No manifest
  change was needed. (The two `pip install` calls run against the wrong global interpreter
  before this was caught are harmless -- that environment is not used by this repository at
  all -- and are recorded here for transparency, not reverted since they affect nothing.)
- Full collection under `.venv`: **2257 collected, 0 errors** -- matches Task 76S's ending
  baseline exactly.
- Directly-affected baseline suites (EOD, broker boundary, protective exit, Task64 CLI,
  decision engine, lifecycle probe, decision contract, execution settings) all pass:
  **134 passed, 0 failed**.

## Stage log
See `stage_status.json` for the authoritative machine-readable checkpoint ledger. Prose
narrative per stage is appended below as each stage completes.

## Stage 1 — COMPLETE (commit 3a7e404)
Decision contract wired into decision_engine.py's real _handle_entry/_check_exit. Partial-fill
accounting bug fixed in lifecycle.py::apply_broker_update. Timed-out submissions now marked
UNCONFIRMED_TIMEOUT and resolved via reconcile(). Three new durable ledgers introduced
(decision_ledger.py, notification_outbox.py, shadow_ledger.py), wired as independent branches.
6 pre-existing tests updated (Task 76S's fail-closed-approval-style disclosed changes) across
test_task65b_decision_engine.py, test_task76s_broker_boundary.py,
test_task76s_protective_exit_eod.py. One flaky test discovered and fixed (a decision_id
collision from two datetime.now() calls landing on the identical value under Windows clock
resolution in a fast test loop -- a test-fixture-only artifact, not a production risk, since
real market bars are always >=1 minute apart; fixed by using explicit, deterministically-offset
timestamps in the affected tests rather than changing decision_id's production scheme).

## Stage 2 — COMPLETE (commit bac0845)
decision_event_schema.json, alert_delivery_contract.md.

## Stage 3 — COMPLETE (commit b82f3c9)
shadow_simulation_policy.md, shadow_test_results.csv.

## Stage 4 — COMPLETE
observability.py (new minimal read-only projection module), reporting.py (additive
integrated_projection passthrough), cli.py wiring, 12 accelerated end-to-end scenarios driving
the real SessionRunner+DecisionEngine stack. Found and fixed a benign RuntimeWarning (unawaited
coroutine) in 4 pre-existing AsyncMock-based SessionRunner tests, caused by
notification_outbox.dispatch_pending() being auto-mocked as async by AsyncMock's default
attribute behavior -- fixed by stubbing it as a plain sync callable in those 4 fixtures
(test_task65_session_runner.py, test_task71s_data_freshness_stabilization.py x2,
test_task71s_r1_live_iex_semantics.py). Final full suite: 2316 passed, 1 skipped, 10 xfailed,
zero failures, zero unexplained regression (see task77i_summary.json for the exact
reconciliation math).
