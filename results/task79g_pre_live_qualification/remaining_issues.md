# Task 79G — Remaining Issues

## Newly found this task

### 1. `cli.py supervise` has no dry-run / `--no-live-loop` equivalent
`start` supports `--no-live-loop` (flip `session_enabled`, return immediately, never enter the
live poll loop) — useful for a pure readiness check. `supervise` (Task 78I's unified supervisor)
has no equivalent flag: if its 5-step startup sequence and `Preflight` both pass, it proceeds
directly into `run_with_bounded_restart(lambda: run_session(runner, listener), ...)`, i.e. the
real live loop. This is why this task never invoked `supervise` for real (constructing and
observing it end-to-end is only done via fakes in `test_task78i_cli_supervise.py`, re-confirmed
passing this task). Not a safety defect — `supervise` still fails closed on any preflight/
ownership problem exactly like `start` does — but it means an operator cannot get a "would this
have started cleanly" answer from `supervise` itself without accepting that it will actually
begin running. **Recommendation for Task 80**: use `preflight` (read-only) for a dry check, or
`start --no-live-loop` (which shares the same `Preflight` + `PaperLifecycle.start_session` logic,
though not the newer 5-step ownership/reconcile sequence) rather than requesting a new flag be
added under time pressure tonight.

## Carried forward from Task 78I (re-confirmed still accurate this task, not re-litigated)

1. No strategy-approval registry exists — every real decision resolves `UNVALIDATED`; shadow
   tracking and real PAPER execution are both, by design, inert for natural strategy traffic.
2. `paper_entry_settings.json` still does not exist in production.
3. `DecisionRecord.shadow_status`/`execution_status` fields remain intentionally
   write-back-unpopulated (pure recompute design, not a shortfall).
4. `NotificationOutbox` `UNCERTAIN`-retry gap — already fixed in Task 78I Stage 5; re-verified
   fixed and passing this task (`test_task78i_stage5_rehearsal.py::test_06`).
5. `DecisionEngine`/dispatch steps do not themselves catch raw transport/Redis exceptions —
   `SessionRunner.process_tick`'s outer per-tick guard is the actual safety net (confirmed again
   via fresh code read this task, `remaining_issues.md` item 5 in Task 78I).
6. No cross-process file locking beyond the account-execution lock.
7. `gemini_enrichment` has no automatic follow-up alert on completion (deliberate).
8. Supervisor restart/backoff untested against a real multi-hour live session (still true — this
   task, like Task 78I, does not authorise or perform a live session).
9. Dashboard `/piv/status` is a single JSON route, not a rendered UI panel (deliberate,
   unchanged).
10. `talonx_ops/preflight.py`'s and `talonx_piv/preflight.py`'s duplicate-process checks are two
    hand-maintained copies of the same PowerShell command (unchanged, not refactored this task).

## Newly confirmed (not previously stated this precisely) — the probe's fail-closed layering

The `PIV_LIFECYCLE_PROBE` path was already known to require `--confirm-piv-lifecycle-probe`, but
this task empirically confirmed (fresh test, fake broker, isolated state) that it ALSO requires
`paper_entry_settings.json` to separately enable the probe symbol — the CLI flag alone does not
activate it. This is a genuine, positive safety property (two independent operator actions
required), now explicitly documented in `probe_plan.md` rather than left implicit.

## Not investigated this task (explicitly out of scope)

- Actual Telegram MESSAGE delivery (only bot identity/`getMe` was checked — no `sendMessage` call
  was made, per this task's own hard boundary). Marked `NOT YET VERIFIED` in
  `external_readonly_checks.json`.
- Actual Gemini model-generation call (`.generate()`) — only chain CONSTRUCTION was verified.
- Real-account live behaviour of the execution-ownership lock (unit/integration-tested with
  genuine competing OS subprocesses against ISOLATED fake-account state only, per this task's own
  constraint).
