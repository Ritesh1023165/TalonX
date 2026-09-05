# Task 79E — Final Report

## Task

Implement and test a narrowly-scoped experimental mode so an otherwise-
eligible natural long-only signal may generate an explicitly-experimental
alert, research shadow position, and optional PAPER entry while its
strategy remains `UNVALIDATED` — permission to experiment, explicitly never
treated as evidence the strategy is profitable, and never weakening the
existing production approval gate.

Deadline: release-review cutoff Friday 28 August 2026, 06:00 UK time
(05:00 UTC) — verified against the real system clock at multiple points
during this task (see "Clock checks" below), never assumed.

## What was built

See `implementation_plan.md` for the full design and every file touched.
Summary: a new, disabled-by-default `ExperimentalAuthorization` permission
object, structurally distinct from `StrategyApprovalStatus` throughout;
re-validated fresh (never cached) both at decision time and again at the
true broker boundary; a durable, restart-surviving PAPER budget ledger that
is never refunded on a failed submission; a closed submission-timeout-
before-broker-id gap; honest experimental-classified alerts with the
required banner; shadow tracking gated on the same actionability bar as the
normal path; and the mechanism wired into the REAL runtime construction and
decision loop (`decision_engine.py::_handle_entry`/`_check_exit`,
`cli.py::runtime()`/`main()`) — not a helper or test-only override, proven
by `tests/test_task79e_decision_engine_experimental.py`'s 7 end-to-end
scenarios driving the actual `DecisionEngine.on_bars` path.

Two real defects were found and fixed DURING implementation, before any
test asserted the buggy behaviour as correct (see `implementation_plan.md`
for full detail):

1. `strategy_version` would have been permanently unmatchable (`""` vs. a
   required-non-empty file field) — fixed by binding to the existing,
   tested `talonx_backtest.reproducibility.get_strategy_version()`
   fingerprint instead of a fabricated placeholder.
2. A regression in a pre-existing Task 78I behavioural contract (raw
   transport exceptions must propagate uncaught past `_handle_entry` to
   `SessionRunner`'s outer per-tick guard) was introduced by the Stage 2
   submission-safety fix and caught by re-running
   `test_task78i_stage5_rehearsal.py` — restored, with the two new tests
   that had asserted the wrong exception type corrected.

## Test evidence

59 new tests (34 authorization unit tests, 18 lifecycle-guard tests, 7
decision-engine end-to-end tests) — see `test_matrix.md` for the full
breakdown. Every pre-existing test file this task's diff touches was
re-run after every code change and confirmed unchanged (zero regressions)
except the one pre-existing test whose exception-propagation contract was
restored to its documented behaviour (see above).

Full repository regression suite (`regression_results.txt`): **2471 passed,
1 skipped, 10 xfailed, 0 failed** — exit code 0, run in 768.71s. Reconciles
exactly: `2471 = 2412 (Task 79G's own baseline) + 59 (this task's new
tests)`; skipped/xfailed counts identical to baseline; total collected
(2482) matches `pytest --collect-only`'s own count exactly.

**Process note, disclosed rather than hidden:** the FIRST full-suite run
attempted for this task (started immediately after the lifecycle
regression fix) was invalidated before use — it was launched in the
background and then several more files were edited while it ran
(`cli.py`'s wiring, the `strategy_version` fix, the new 7-test
`test_task79e_decision_engine_experimental.py`, and `observability.py`'s
additions), so its result (2464 passed) reflected a stale, incomplete
snapshot of the code, not the final diff. Caught by reconciling its passed
count against a fresh `pytest --collect-only` total (2482 collected vs.
2475 executed — a 7-test gap matching exactly the new integration-test
file added after that run started) before this report was written. The
run recorded in `regression_results.txt` was executed with zero further
code edits in flight and is the one this verdict relies on.

## Hard boundary confirmations

- **No live session started.** No `supervise`/`start --confirm-paper-session-start`
  invocation occurred.
- **No broker mutations.** No `eod`, `kill-switch`, or `cleanup` command was
  run against the real PAPER broker at any point this task.
- **No notifications sent.** No real Telegram `sendMessage` call occurred —
  every notification-outbox test uses a fake in-memory `send` callable.
- **No production permission enabled.** No `experimental_authorization.json`
  exists anywhere in this repository, tracked or untracked, live or
  templated (only the explicitly-inactive
  `inactive_configuration_example.json` template, `"enabled": false`).
- **No strategy-validation promotion.** `strategy_approval_status` is never
  set to `APPROVED` by anything in this diff; grep-provable exactly like
  the pre-existing `strategy_approval_status_override` invariant.
- **No holdout data accessed.**
- **No protected Quant files changed.**
  `talonx_quant/{strategy,indicators,consumer,config}.py` — unchanged
  (verify via `git diff --stat` against this task's commit).
- **No task-owned background jobs left running.** The full-suite regression
  run was the only background process this task started, and it completed
  before this report's verdict was finalised.

## Clock checks performed (never assumed)

- At task start: `~2026-08-27T23:44:52Z`, ~5h15m before the 05:00 UTC
  cutoff.
- Mid-implementation (after the lifecycle wiring and regression-fix pass):
  `~2026-08-27T23:51:48Z`, ~5h8m remaining.
- Before launching the authoritative (second, valid) full-suite run:
  `2026-08-28T00:02:21Z`, ~4h58m remaining.
- At verdict time: `2026-08-28T00:15:28Z` (UK: `01:15:28 BST`), ~4h44m
  remaining before the 05:00 UTC / 06:00 UK cutoff.

## Verdict

# **EXPERIMENTAL_MODE_READY_FOR_OPERATOR_REVIEW**

Implemented within the deadline, with margin to spare (~4h44m remaining at
verdict time). The mechanism is fully built, wired into the real runtime
decision loop, and covered by 59 new tests plus a clean, reconciled,
zero-regression full-repository run (2471 passed / 1 skipped / 10 xfailed /
0 failed). It is completely inert in this repository today — no
`experimental_authorization.json` exists anywhere, live or templated — so
nothing about today's actual production behaviour has changed. Activation
remains entirely an operator decision, governed by
`authorization_contract.md`, with the explicit recommendation (see
`task80_launch_handoff_refresh.md`) not to activate it as part of Task 80
itself.

All hard-boundary confirmations above hold: no live session, no broker
mutations, no notifications sent, no production permission enabled, no
strategy-validation promotion, no holdout access, no protected Quant file
changes, no task-owned background jobs left running.

See `remaining_issues.md` for the honestly-disclosed, non-blocking items an
operator should read before ever authoring a live authorization file.

Then STOP — awaiting the operator's separate Task 80 prompt. No activation,
launch, trading, or research starts automatically at either the 06:00 UK
release-review cutoff or the ~08:00 UK Task 80 handoff.
