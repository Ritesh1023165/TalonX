# Task 79E-R2 — Complete Experimental Activation Stabilisation

> **ERRATA (Task 79E-R2-2, continuation from this file's own final commit
> `c9a4994`):** the PASS verdict below is preserved EXACTLY as originally
> evidenced and remains accurate for everything it actually tested.
> However, this report's own "Remaining, disclosed limitations" section
> (items 1 and 2, below) recorded two gaps as non-blocking that a later
> round's task brief identified as, in fact, mandatory to close, along
> with two related correctness defects (count-based uncertain-submission
> resolution, and fill-time causality based on an "already OPEN" boolean
> rather than actual observed fill timing). All four are now closed —
> see `findings_and_tests_report_ADDENDUM_R2_2.md` in this same
> directory for the full reproduction-fix-test evidence, and
> `task80_launch_handoff_refresh_r2_2.md` for the corrected operator
> guidance. Nothing below this notice was edited.

## Scope and starting point

Continuation from `013d5ae` (Task 79E-R1) on `research/talonx-strategy-validation`.
Task 79E-R1 fixed a first round of real activation defects and reported
`ACTIVATION_BLOCKERS_CLOSED`. This task re-audited R1's OWN claims against
Alpaca's actual documented API contract and the real production call
paths, found that several of them were incomplete or, in one case, built
against a fabricated (never-documented) endpoint, fixed every one, and
closed the remaining gaps R1 had left implicit.

## Build identity

- Starting SHA (Task 79E-R1's own final commit): `013d5ae`.
- Tested-against SHA (this task's feature commit, what `regression_results.txt` was run against): `3d788ca`.
- Final SHA (this docs-only follow-up commit filling in the SHA above into the handoff refresh): recorded in `task80_launch_handoff_refresh.md`.

## How to reproduce this report

```
git log --oneline -3                                   # confirms starting SHA 013d5ae
.venv/Scripts/python.exe -m pytest tests/test_task79e_r2_activation_safety.py -q
.venv/Scripts/python.exe -m pytest tests/test_task79e_r1_activation_safety.py tests/test_task79e_decision_engine_experimental.py tests/test_task79e_lifecycle_experimental.py tests/test_task79e_experimental_authorization.py -q
.venv/Scripts/python.exe -m pytest tests/ -q          # full suite, see regression_results.txt for raw output
```

## Addendum — correcting Task 79E-R1's own overclaims

R1's `findings_and_tests_report.md` verdict block claimed
`ACTIVATION_BLOCKERS_CLOSED`. That report's own evidence (59+26 = 85
passing tests, 0 regressions) is preserved unchanged and remains accurate
for what it actually tested. This addendum records where R1's CLAIMS
outran what it had actually verified:

1. **"Bound both layers to `session_scope`"** — true mechanically, but R1
   bound every real call site to the FIXED LITERAL STRING `"REGULAR"`, not
   to any actual session identity. Two genuinely different, unrelated live
   sessions would both present `"REGULAR"` and be treated as
   interchangeable — the check could never actually distinguish one
   session from another. Fixed this task (Requirement 5 below); R1's own
   34+4 `experimental_authorization.py` tests and 18+1
   `lifecycle_experimental.py` tests, which exercise `permits_entry`/
   `permits_paper_execution`/`order_intent` directly with an explicit
   `session_scope` argument, remain valid unchanged (the FUNCTION's
   contract never claimed to know what a "real" session id looks like;
   only the CALLERS in `decision_engine.py`/`lifecycle.py` needed to
   change what value they pass).
2. **"Uncertain submissions reconciled via stable client_order_id"** — R1's
   `AlpacaPaperClient.find_order_by_client_id` called
   `GET /v2/orders?status=all&client_order_id=...`. That query parameter
   is not part of Alpaca's documented list-orders filter set at all; it
   happened to "work" only because R1's OWN fake transport modeled the
   made-up contract it invented, not Alpaca's real one
   (`GET /v2/orders:by_client_order_id?client_order_id=...`, see
   https://docs.alpaca.markets/us/reference/getorderbyclientorderid).
   Fixed this task (Requirement 1). Also: R1 treated a single "not found"
   result as fully conclusive (`SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED`
   after exactly one call) and adopted ANY response with a truthy `id`
   without checking it actually matched the original intent. Both fixed
   this task.
3. **"Exit tracking is kept until confirmed flat"** — R1's own
   `_check_exit` deleted `self.positions[symbol]` the instant
   `lifecycle._open_position_for(symbol)` returned `None` -- which is ALSO
   true for a BUY that is merely accepted-and-not-yet-filled, not only for
   a genuinely-gone position. An entry that took more than one tick to
   fill would have had its exit plan silently deleted before it ever
   became protectable. Fixed this task (Requirement 2).
4. **"Durable exit recovery"** — R1 persisted `stop_price`/`target_price`/
   `entry_signal_bar_timestamp`, but NEVER persisted the in-memory
   `exit_reason` latch that keeps a triggered stop/target being retried
   across bars. R1's own `remaining_issues.md` item 1 disclosed this
   narrowly as a "rare restart window," but it is a straightforward
   correctness gap, not a rare one: ANY restart between a stop/target
   firing and its resulting sell being confirmed loses the fact that the
   position MUST still be sold, and price recovering in the meantime would
   silently cancel the exit. Fixed this task (Requirement 3).
5. **"Entry/exit causality closed"** — R1's `on_bars`-computed
   `skip_price_check` only protected the SAME TICK an entry was opened on.
   A delayed fill (an order that stays accepted-but-unfilled for one or
   more ticks before it actually fills) had its FIRST eligible bar
   evaluated with no causal floor at all once R1's narrower same-tick rule
   stopped applying, one tick after entry. Fixed this task (Requirement 4).

None of the above means R1's own tests were wrong for what they tested;
they are all still passing, unchanged in intent. The gap was between what
the report CLAIMED was closed and what the code actually did for inputs
R1's own tests never constructed.

## Requirement → implementation → regression test → result

### Requirement 1 — Correct broker reconciliation

| | |
|---|---|
| Implementation | `talonx_piv/broker.py::AlpacaPaperClient.find_order_by_client_id` now calls the documented `GET /v2/orders:by_client_order_id?client_order_id=...`; 404 → `None`, malformed 200 → raises (never silently "not found"). `talonx_piv/lifecycle.py::_order_response_matches_intent` verifies client_order_id/symbol/side/qty before any adoption. `_resolve_uncertain_submissions` requires `UNCERTAIN_SUBMISSION_CONFIRMATION_THRESHOLD` (2) SEPARATE not-found results, each from its own `reconcile()` call, before declaring `SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED`; a mismatched/malformed response is rejected and leaves the intent exactly as unresolved as before. |
| Tests | `test_task79e_r2_activation_safety.py`: `test_find_order_by_client_id_uses_the_documented_endpoint_and_params`, `test_find_order_by_client_id_returns_none_on_clean_404`, `test_find_order_by_client_id_raises_on_malformed_200`, `test_uncertain_submission_response_verified_before_adoption`, `test_uncertain_submission_wrong_quantity_response_rejected`, `test_uncertain_submission_matching_response_is_adopted`, `test_single_404_never_confirms_not_submitted`, `test_repeated_reconciliation_is_idempotent_and_never_double_adopts` |
| Result | 8/8 pass |

### Requirement 2 — Complete pending-entry lifecycle

| | |
|---|---|
| Implementation | `talonx_piv/lifecycle.py::entry_still_pending_or_uncertain` (new). `talonx_piv/decision_engine.py::_check_exit` no longer deletes `self.positions[symbol]` merely because `lifecycle._open_position_for` returns `None` -- it now also checks `entry_still_pending_or_uncertain`; only a GENUINELY concluded (confirmed-flat or confirmed-never-filled) symbol is dropped. |
| Tests | `test_accepted_unfilled_entry_keeps_exit_tracking`, `test_confirmed_rejected_entry_drops_tracking`, `test_uncertain_entry_also_keeps_tracking_until_resolved`, `test_uncertain_entry_self_heals_into_decision_engine_once_resolved_and_filled` |
| Result | 4/4 pass |

### Requirement 3 — Complete durable exit recovery

| | |
|---|---|
| Implementation | `talonx_piv/lifecycle.py::mark_exit_triggered` (new) persists the triggered-exit reason onto the OPEN position record the instant `_check_exit` first latches one; `_rehydrate_positions`/`_try_rehydrate_one` in `decision_engine.py` reads it back into `OpenDecisionPosition.exit_reason`. Rehydration now validates required fields: no usable quantity at all → BLOCKED (never rehydrated -- left for the orphan-detector to surface, never invented); no stop_price AND no target_price → DEGRADED (still tracked, EOD-flattenable, but flagged, never claimed "no action required"). `_flag_orphaned_positions` now attempts the SAME rehydration on demand mid-session (closes the self-healing gap identified under Requirement 2 for a SUBMIT_FAILED_UNCERTAIN entry later confirmed-adopted). |
| Tests | `test_triggered_exit_reason_persists_and_survives_price_recovery_after_restart`, `test_rehydration_blocked_when_quantity_information_missing`, `test_rehydration_degraded_when_no_protective_levels`, `test_rehydration_healthy_case_still_reports_no_action_required`, plus `test_task79e_r1_activation_safety.py::test_missing_exit_plan_self_heals_when_recoverable` (renamed/rewritten from R1's own now-superseded `test_missing_exit_plan_fails_visibly`) |
| Result | 5/5 pass |

### Requirement 4 — Enforce actual fill causality

| | |
|---|---|
| Implementation | `on_bars` now computes `already_filled_before_tick` (was `entered_this_tick`) -- a symbol is causality-eligible for a natural price-based stop/target check only if its lifecycle position was ALREADY confirmed OPEN before THIS tick's own entries were processed, correctly covering both the same-tick case (R1) and a genuinely delayed fill spanning multiple ticks (new this task). No wall-clock timestamps are used anywhere in the gate (see the Addendum in Task 79E-R1's own report for why that was abandoned mid-task there). A direct `_check_exit` call (bypassing `on_bars`) defaults to fully eligible, matching every pre-existing test's own expectation -- only `on_bars`'s own same-tick-vs-delayed-fill ambiguity needs this gate at all. |
| Tests | `test_delayed_fill_across_multiple_ticks_is_still_causally_protected`, `test_restart_mid_delayed_fill_still_applies_causality_correctly`; `test_task79e_r1_activation_safety.py::test_same_bar_as_entry_never_triggers_stop` (unchanged, still exercises the same-tick case end to end via `on_bars`) |
| Result | 3/3 pass (2 new + 1 pre-existing re-verified) |

### Requirement 5 — Bind the actual authorized session

| | |
|---|---|
| Implementation | `decision_engine.py::_live_session_scope()` (new) returns `self.events.session_id` -- the real, durable, per-process session identity minted by `session_identity.build_session_identity` and persisted to `session_identity.json` -- replacing the fixed `"REGULAR"` literal everywhere it was previously passed. `lifecycle.py`'s own broker-boundary check is unchanged in mechanism (still compares the caller-supplied `session_scope` against `auth.session_scope`); only the VALUE decision_engine.py now sends changed. |
| Tests | `test_authorization_bound_to_real_session_id_not_fixed_category`, `test_authorization_bound_to_correct_live_session_id_permits`, `test_unrelated_session_id_rejected`, `test_same_session_recovery_permitted_across_reconstruction`, `test_revocation_blocks_new_entries_but_not_existing_exits` |
| Result | 5/5 pass |

### Requirement 6 — Close remaining integration gaps

| | |
|---|---|
| Implementation | `cli.py`'s plain `start` command now calls `lifecycle.reconcile()` immediately before constructing `DecisionEngine`, matching `supervise`'s own `run_startup_sequence` step3 -- "restore only against reconciled exposure" previously held only for the supervised path. Re-verified (not re-implemented, since already correct): durable budgets (`_validated_budget_record`, unchanged), pending-exposure limits (concurrent-exposure counting, unchanged), independent alerts/shadow under every new failure mode this task introduces (see the combined scenario test below), experimental classification/IDs surviving every new code path, Gemini's non-authoritative status (untouched), and `strategy_approval_status` staying `UNVALIDATED` (grep-provable, untouched). |
| Tests | `test_combined_two_symbols_competing_one_pending_one_uncertain` (concurrent exposure with a PENDING, not confirmed-open, entry); cli-dependent suites re-run (see below) |
| Result | pass |

## Tests

**24 new tests** in `tests/test_task79e_r2_activation_safety.py`, using an
`AlpacaContractTransport` fake built directly from Alpaca's documented
endpoint list (not copied from what R1's implementation happened to call).
Plus **1 test renamed/rewritten** in `test_task79e_r1_activation_safety.py`
(`test_missing_exit_plan_fails_visibly` → `test_missing_exit_plan_self_heals_when_recoverable`,
since the self-healing improvement built for Requirement 3 makes the OLD
name's claim literally false for a recoverable position -- the genuinely
unrecoverable case is now covered by a dedicated R2 test instead) and
minor fixture updates (session_scope rebinding) in
`test_task79e_r1_activation_safety.py`, `test_task79e_decision_engine_experimental.py`.
No test count change in those files (still 85 total across the four
pre-existing `test_task79e_*` files, confirmed via `pytest --collect-only`).

Total across all five `test_task79e_*` files: **109** (85 + 24), confirmed
via `pytest --collect-only`.

## Full repository regression suite

Baseline (Task 79E-R1's own final number): **2497 passed / 1 skipped / 10 xfailed**.

This task adds 24 new tests, so the expected authoritative total is
**2521 passed** (2497 + 24), skipped/xfailed counts unchanged.

Raw output: see `regression_results.txt` in this directory, run with
ZERO further code edits in flight.

## Hard boundary confirmations

- **No live session started.** No `supervise`/`start --confirm-paper-session-start` invocation occurred.
- **No broker mutations.** No `eod`/`kill-switch`/`cleanup` command run against a real PAPER broker.
- **No notifications sent.** Every test uses a fake `send` callable.
- **No production permission enabled.** No `experimental_authorization.json` exists anywhere in this repository, tracked or untracked.
- **No strategy-validation promotion.** `strategy_approval_status` is never set to `APPROVED` by anything in this diff.
- **No holdout data accessed. No protected `talonx_quant` files changed. No alpha tuning.**
- **No task-owned background jobs left running** at the time this report's verdict was finalised.

## Remaining, disclosed limitations (none block the verdict below)

1. A genuine process restart while an entry is still merely PENDING (not
   yet filled at "crash" time) is NOT rehydrated as an in-flight plan by
   the new process -- `_rehydrate_positions` only rebuilds from OPEN
   lifecycle positions, and there is no persisted "this entry was in
   flight" bookkeeping surviving a full process death the way a FILLED
   position's exit plan does. The eventual fill (once reconcile() resolves
   it) IS still safely applied to lifecycle state and correctly protected
   by fill-causality once observed, and a genuinely new process has no
   natural way to know about an order it never itself submitted without a
   broader order-adoption mechanism -- out of this task's scope. See
   `test_restart_mid_delayed_fill_still_applies_causality_correctly`'s own
   docstring.
2. `lifecycle.py`'s broker-boundary session check still trusts the
   caller-supplied `session_scope` parameter rather than independently
   recomputing `self.events.session_id` itself -- both layers end up
   checking the real value in production (since `decision_engine.py` is
   the only real caller and now sends the correct one), but this is
   parameter-passing, not full duplicate-independent verification. Noted
   as a design tradeoff for time, not a discovered defect.
3. Task 79E-R1's own remaining_issues.md items 2-4 (no dedicated corrupt-
   `experimental_budgets`-specific test beyond what R2 adds here,
   `strategy_id` bound to the raw `SignalType` value, observability's
   experimental section being additive-only) remain unchanged and still
   apply.

## Verdict

# **PASS**

Every numbered activation requirement (1-6) has a concrete implementation
change, at least one regression test that reproduces the PRE-fix defect
and asserts the corrected behaviour, and passes. The combined scenario
test proves the interaction of pending-exposure counting with a
not-yet-filled entry. Full repository regression suite: see
`regression_results.txt` for the confirmed final count, reconciling
exactly against baseline + new tests, zero failures, zero waived or
weakened tests, zero deadline-driven shortcuts (this task had no fixed
deadline).

Disabled-by-default is unchanged: no `experimental_authorization.json`
exists anywhere in this repository. See `task80_launch_handoff_refresh.md`
for the still-recommended posture (do not activate as part of Task 80).

Then STOP -- awaiting the operator's own separate authorization for
Task 80, and for whether to ever author a live authorization file.
