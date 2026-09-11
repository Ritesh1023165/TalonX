# Task 78I Stage 1 — Integration Gap Closure

## A. Shadow independence
**Finding**: no forbidden coupling existed in the implemented code — `ShadowLedger.consider_entry`
was already gated solely on `decision.recommendation == Recommendation.BUY` (itself a function of
approved strategy + market view + data readiness only), never on `paper_entry_enabled`, broker
availability, or PAPER submission/fill success. This was AUDITED, not assumed — see
`shadow_independence_matrix.csv` for the full permitted/forbidden matrix and the new
`test_task78i_shadow_independence.py` tests (source-inspection proof + a byte-identical-outcome
comparison test for PAPER enabled vs. disabled). No code correction was needed; the audit and its
evidence are the closure.

## B. Horizon-based shadow exits
**Implemented**: `shadow_ledger.py` gained `horizon_policy: dict[str, timedelta]`, checked after
stop/target on every bar, computing the deadline from the position's ACTUAL fill time (never the
decision/recommendation time), exiting at the first causally-observed bar reaching or passing the
deadline using that bar's real close (never a fabricated price). `DEFAULT_HORIZON_POLICY = {}` —
no duration is invented for `INTRADAY_SHORT` (the only horizon value any real caller ever
attaches), per this task's explicit instruction. See `horizon_exit_evidence.json` and
`test_task78i_horizon_exit.py` (11 tests: boundary, gap, no-executable-observation, restart).

## C. Status projections
**Implemented**: `observability.py::build_decision_status` — a PURE function joining
`decision_ledger.json`/`notification_outbox.json`/`shadow_ledger.json`/`lifecycle_state.json` by
`decision_id` (the latter join newly enabled by threading an optional `decision_id` parameter
through `lifecycle.PaperLifecycle.order_intent`, wired from `decision_engine.py`). No mutable
status field written back onto the immutable `DecisionRecord` — every call recomputes fresh from
disk, so late/duplicate events and restarts can never regress a status. See
`status_projection_recovery.json` and `test_task78i_status_projection.py` (9 tests).

## D. Execution ownership
**Implemented**: `execution_ownership.py` — an OS-level advisory exclusive file lock (crash-safe
by construction, never a hand-written PID file), scoped to `(broker_endpoint, account_id)` at a
FIXED global location (never `state_dir`). Enforced at `AlpacaPaperClient.submit_order`/
`cancel_all_orders`/`close_all_positions` (the actual broker-mutation chokepoint — covers normal
orders, probes, manual CLI paths, and EOD's direct `lifecycle.broker.*` calls uniformly). Wired
into `cli.py`'s `start`/`kill-switch`/`eod`/`cleanup` command branches, acquired after identity
verification, before any mutation. See `multiprocess_ownership_evidence.json` (including two
GENUINE multi-process tests: a real competing child process, and an abrupt-kill crash-safety
proof) and `test_task78i_execution_ownership.py` / `test_task78i_cli_ownership.py`.

## Stage 1 gate
All four gaps closed with evidence; no unresolved safety issue carried into Stage 2. See
`test_results.txt` (Stage 1 subset) for the passing test run.
