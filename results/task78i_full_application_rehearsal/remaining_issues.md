# Task 78I — Remaining Issues (deliberately not resolved in this task)

## 1. No strategy-approval registry (carried forward from Task 76S/77I)
Every real decision resolves `StrategyApprovalStatus.UNVALIDATED`. Shadow tracking and real PAPER
execution are both, by design, inert for natural strategy traffic until a separate task builds an
approval registry — not invented here, per this task's own explicit instruction.

## 2. `paper_entry_settings.json` still does not exist in production
Unchanged — no ticker is entry-enabled until an operator explicitly creates the file.

## 3. Decision-record `shadow_status`/`execution_status` fields remain write-back-unpopulated
Unchanged design decision from Task 77I — `observability.build_decision_status` computes these
fresh by joining linked ledgers instead (see `status_projection_recovery.json`), which is
believed to be the better design (no regression risk from a mutable field), not a shortfall.

## 4. Notification `UNCERTAIN` retry fix (discovered and fixed THIS task, Stage 5)
While building the rehearsal's notification-failure-and-restart scenario, discovered that
`NotificationOutbox.dispatch_pending`'s `PENDING_STATUSES` tuple did not include `"UNCERTAIN"` --
a record left `UNCERTAIN` (adapter exception, true delivery status unknown) was never retried by
a later `dispatch_pending()` call, silently stuck in limbo permanently (neither retried nor
terminal). Fixed by including `"UNCERTAIN"` in the retry-eligible set (bounded by the same
`max_attempts` as `PENDING`/`RETRY`) — see `talonx_piv/notification_outbox.py`'s own updated
comment and `test_task78i_stage5_rehearsal.py::test_06_notification_failure_and_restart_recovery`.
This is a genuine, disclosed fix, not a pre-existing known limitation being carried forward.

## 5. DecisionEngine/dispatch steps do not themselves catch raw transport/Redis exceptions
Confirmed (not assumed) via rehearsal scenarios 5 and 14: `DecisionEngine._handle_entry` only
catches `PaperGuardError` (a deliberate safety rejection), not a raw transport-level exception
(a genuine network/Redis failure) — that exception propagates. `SessionRunner.process_tick`'s own
OUTER per-tick `try/except` (unchanged, pre-existing, Task 65B/72O) is the actual safety net for
this in the live loop, not `DecisionEngine`/`GeminiEnrichmentOutbox`/`NotificationOutbox`
themselves. This is architecturally sound (single point of tick-isolation, not duplicated at every
layer) but is recorded here explicitly since Stage 5 is where it was first directly proven rather
than assumed.

## 6. No genuine cross-process file locking beyond the account-execution lock
Unchanged from Task 78I Stage 1D — the account-level `ExecutionOwnership` lock is the one
multi-process safety mechanism; no broader distributed-locking architecture exists or was added.

## 7. `gemini_enrichment` has no automatic follow-up alert on completion
Deliberate (see `gemini_authority_boundary.md`) — avoids inventing an "update/follow-up" alert
mechanism that does not already exist in this codebase; enrichment is exposed read-only instead.

## 8. Supervisor restart/backoff is untested against a REAL multi-hour live session
`run_with_bounded_restart`'s logic is unit-tested and exercised in the rehearsal with fast/fake
clocks; it has never observed a genuine multi-hour SessionRunner.run() failure-and-recovery cycle
in a live environment (this task explicitly does not authorise a live session).

## 9. Dashboard `/piv/status` is a single new GET route, not a full UI panel
Per this task's own instruction ("do not redesign dashboards... provide the minimal read-only
projection"), no new HTML/JS was added to `dashboard_web_static/` — the route returns JSON only.
A future task could add a rendered panel consuming it.

## 10. `talonx_ops/preflight.py`'s general-app duplicate-process check and `talonx_piv/preflight.py`'s
new copy are two separate, hand-maintained PowerShell command strings (intentionally identical
today). A future refactor could extract this into one shared helper both modules import, rather
than two copies that could drift.
