# Task 79E-R2-2 — Addendum: Closing 4 Items the Prior PASS Verdict Left Open

**This file is an ADDENDUM to `findings_and_tests_report.md` in this same
directory. It does NOT replace or edit that file's own evidence — that
report's tests, numbers, and reasoning remain exactly as they were run
and are preserved unchanged below this line. This addendum documents a
SEPARATE, later round of work that re-opened and closed 4 specific items
that report's own "Remaining, disclosed limitations" section had flagged
as non-blocking, and that this round's task brief identified as, in
fact, blocking.**

Continuation from `c9a4994` (this repo's own prior "Task 79E-R2" final
commit — see `git log --oneline` for confirmation) on
`research/talonx-strategy-validation`.

## Why the prior PASS was correct for what it tested, but incomplete

`findings_and_tests_report.md`'s own "Remaining, disclosed limitations"
section (items 1 and 2) already named the two biggest gaps closed here:
a genuine full-process restart did not rehydrate a still-pending (not
yet filled) entry, and the broker-boundary session check trusted a
caller-supplied `session_scope` rather than independently deriving it.
Both were explicitly recorded as "does not block the verdict below" —
this task's brief disagreed, and directed that they (plus two related
correctness defects surfaced independently) be closed as mandatory, not
deferred. This addendum is that closure.

## The 4 items, each reproduced before being fixed

### 1. Uncertain submissions — count-based resolution assumed absence proves non-submission

**Reproduction (confirmed against the pre-fix code before any change was
made):** `_resolve_uncertain_submissions` in the prior round required
exactly `UNCERTAIN_SUBMISSION_CONFIRMATION_THRESHOLD` (2) not-found
results before declaring `SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED` — after
the 2nd 404, the intent became terminal. A 3rd, later `reconcile()` call
never re-queried a terminal intent at all, so an order that only became
visible on the broker's side on a 3rd or later check (a real, documented
Alpaca eventual-consistency possibility, not a hypothetical) would never
be discovered, and the reservation/entry would have already been
released as if the order never existed.

**Fix:** `talonx_piv/lifecycle.py`
- Removed `UNCERTAIN_SUBMISSION_CONFIRMATION_THRESHOLD` entirely.
- Added `UNCERTAIN_SUBMISSION_BACKOFF_SCHEDULE_SECONDS` (line 60) — a
  tuple of increasing wait intervals, used ONLY to rate-limit how often
  an uncertain intent is re-checked, never to auto-resolve it.
- `_uncertain_submission_due_for_check` (line 935) — bounds polling
  cadence via the backoff schedule.
- `_resolve_uncertain_submissions` (line 952) — rewritten to NEVER
  auto-resolve. Tracks `not_found_confirmations`/`last_uncertain_check_at`
  for observability/backoff only. The intent, its exposure reservation,
  and its stable-`client_order_id` lookup all remain active indefinitely
  until a verified match is found or an operator explicitly resolves it.
- `operator_resolve_uncertain_submission` (line 1070) — new, the SOLE
  explicit escape hatch. Requires `operator_confirmation=True` (raises
  `PaperGuardError` otherwise); records `resolution_source="OPERATOR"`
  and an `operator_note`; reuses the existing
  `SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED` status string for downstream
  compatibility.

**Regression tests** (`tests/test_task79e_r2_activation_safety.py`):
- `test_repeated_404s_never_auto_confirm_not_submitted_then_order_appears_and_is_adopted_once`
  — reproduces the exact failure scenario: timeout, several 404s past
  the OLD threshold, then the real order becomes visible via lookup;
  asserts it is adopted exactly once, with no premature capacity release
  and no duplicate entry anywhere in the process.
- `test_repeated_reconciliation_is_idempotent_and_never_double_adopts` —
  repeated `reconcile()` calls after adoption never re-adopt or double-count.
- `test_uncertain_submission_response_verified_before_adoption`,
  `test_uncertain_submission_wrong_quantity_response_rejected`,
  `test_uncertain_submission_matching_response_is_adopted` — carried
  over from the prior round, still pass unchanged in intent (adoption
  still requires a verified match).
- `tests/test_task79e_r1_activation_safety.py::test_uncertain_submission_never_auto_resolves_operator_resolution_frees_pyramiding_guard`
  (renamed/rewritten this round from a prior test whose old name's own
  claim — implying automatic resolution — became false under the new
  design) — proves the pyramiding-guard (re-entry blocked while an
  intent is uncertain) stays blocked indefinitely absent resolution, and
  is correctly freed once `operator_resolve_uncertain_submission` is
  called explicitly.

### 2. Fill-time causality — an already-OPEN position said nothing about WHEN it filled

**Reproduction:** the prior round's `on_bars`-computed
`already_filled_before_tick` boolean asked only "is this position
already OPEN," which is true the instant a fill is applied, regardless
of the arriving bar's own timing relative to that fill. A pre-fill bar
(one whose actual market data predates the fill) that happened to arrive
on a LATER tick than the one the entry itself was submitted on would
read `already_filled_before_tick=True` and be evaluated for a natural
price-based exit with `skip_price_check=False` — using price action that
occurred before the position genuinely existed.

**Fix:** replaced the boolean gate with real broker-sourced timestamp
comparison.
- `talonx_piv/lifecycle.py::apply_broker_update` (line 650) — new
  `filled_at` parameter; persists `first_fill_observed_at` onto the
  BUY-fill position record, first-write-wins (an existing value is never
  overwritten by a later, less-authoritative update).
  `poll_order_until_terminal`, `_resolve_unconfirmed_orders`,
  `_resolve_uncertain_submissions`, and the new
  `_refresh_non_terminal_orders` all extract `filled_at =
  response.get("filled_at") or response.get("updated_at")` from the
  broker's own response and pass it through — never `datetime.now()`.
- `talonx_piv/decision_engine.py::_parse_iso_datetime` (line 66) — new
  helper.
- `talonx_piv/decision_engine.py::_check_exit` (line 668) — removed the
  `skip_price_check` parameter entirely. Now computes
  `first_fill_observed_at = _parse_iso_datetime(lifecycle_position.get("first_fill_observed_at"))`
  and gates natural (non-forced) exits on
  `causally_eligible = force_reason is not None or (first_fill_observed_at is not None and bar.timestamp > first_fill_observed_at)`.
  **Unknown timing (`None`) always fails closed** — no natural
  price-trigger exit is ever evaluated without a positively-known fill
  time. `force_reason` (forced EOD flatten) always bypasses the gate, so
  EOD safety is unaffected by unknown timing.
- `on_bars` (line 794) — the old `already_filled_before_tick`
  precomputation and `skip_price_check` argument passing were removed;
  `_check_exit` now determines eligibility itself from persisted state.

**Wall-clock collision risk, addressed directly per the task's own
instruction ("use controlled timestamps rather than `datetime.now()`
ordering assumptions"):** two independently-generated `datetime.now()`
calls (a fake transport's auto-fill timestamp and a test's own
"next bar" timestamp) can tie or invert due to clock resolution. Every
test in this round that constructs a bar immediately following an entry
uses an explicit `+ timedelta(minutes=1)` offset from the fill, never an
adjacent bare `datetime.now()` call. This gate going live for real
surfaced latent flakiness in 4 PRE-EXISTING tests, found across two
separate passes:

- First pass (found via a broad `-k` regression sweep re-run):
  `test_task65b_decision_engine.py::test_stop_hit_triggers_controlled_exit`,
  `test_task76s_protective_exit_eod.py::test_disable_entries_after_opening_protective_exit_still_works`,
  `test_task79e_decision_engine_experimental.py::test_exit_remains_available_after_experimental_entry`.
- Second pass (found because the FIRST full-repository regression run
  produced a DIFFERENT 3rd failure —
  `test_task76s_protective_exit_eod.py::test_target_hit_triggers_controlled_exit_unaffected_by_contract`
  — than the 3 already fixed, proving the first pass's manual file-list
  sweep had not been exhaustive): a systematic script-driven audit was
  run afterward, splitting every test file into individual test-function
  bodies and flagging any function containing 2+ `on_bars`/`_check_exit`
  calls together with a `Bar(datetime.now(timezone.utc)...)` construction
  with no `timedelta` offset. This surfaced exactly the one remaining
  case above and confirmed, by exhaustive enumeration (not spot-checking),
  that no further instance exists anywhere in `tests/` — every OTHER
  2+-call test either constructs each bar against a separate
  `DecisionEngine` instance (no shared fill to collide with), already
  uses an explicit deterministic offset (`test_task77i_decision_engine_wiring.py`'s
  own `bar(price, *, offset_seconds=0.0)` helper), or uses fully fixed
  timestamps unrelated to `datetime.now()` entirely
  (`test_task78i_stage5_rehearsal.py::test_09_horizon_expiry_with_and_without_data`'s
  `ShadowLedger`-only scenario).

All 4 fixed the same way (explicit `+timedelta(minutes=1)` offset on the
post-entry bar), confirmed stable via 5 repeated re-runs of the
newly-discovered case and 2 repeated re-runs of the broader `-k` sweep
(no further failures) before trusting the final full-suite run below.

**Regression tests** (`tests/test_task79e_r2_activation_safety.py`):
- `test_delayed_fill_across_multiple_ticks_is_still_causally_protected` —
  a pre-fill bar arriving on a later tick is rejected for price-trigger
  evaluation; a genuinely post-fill bar is accepted.
- `test_restart_mid_pending_entry_restores_plan_and_applies_causality_correctly`
  — same guarantee survives a simulated process restart.
- `test_forced_eod_exit_unaffected_by_unknown_fill_timing` — with
  `first_fill_observed_at` unknown (`None`), a natural price-trigger
  exit is correctly rejected, but `flatten_all`'s forced EOD exit still
  submits the sell; confirmed-flat is then observed once the broker
  update lands.

### 3. Independent session enforcement — the broker-entry guard trusted the caller's own claim

**Reproduction:** `_enforce_experimental_paper_guards` called
`auth.permits_paper_execution(..., session_scope=session_scope)` where
`session_scope` was whatever the CALLER (`decision_engine.py`) passed
in. In production `decision_engine.py` was the only real caller and
always passed the correct value, so this was never wrong in practice —
but the guard itself provided no independent verification: a caller
that (by bug or otherwise) supplied a stale or wrong session_id would
have been accepted at the broker boundary with no check catching it.
The exact reproduction: `lifecycle.events.session_id` is session-B,
`authorization` permits session-A, and the caller supplies session-A —
the prior guard accepted it (both values matched EACH OTHER, never
matched against the lifecycle's own actual session).

**Fix:** `talonx_piv/lifecycle.py::_authoritative_session_scope` (line
158) — returns `self.events.session_id or None`, derived directly from
this lifecycle's own `EventBus`, never from any parameter.
`_enforce_experimental_paper_guards` (line 407) now always passes
`session_scope=self._authoritative_session_scope()` to
`auth.permits_paper_execution` — the caller-supplied value is no longer
consulted for the actual authorization decision at all. Missing
identity (`None`) is rejected by `permits_paper_execution`'s own
existing missing-value handling — fails closed, not open.

**Full-process recovery contract** (not just an in-memory `EventBus`
reconstruction test): `talonx_piv/session_identity.py::resolve_session_identity`
(line 82) — reuses the persisted `session_id` from
`session_identity.json` when its `trading_date_et` matches today AND
`lifecycle_state.json` shows `session_enabled=True` and
`kill_switch is not True`; mints a genuinely fresh identity via
`build_session_identity` in every other case (missing/malformed file,
stale date, disabled/kill-switched session) — fails closed toward
minting new, unambiguous identity rather than resuming something
uncertain. Wired into `talonx_piv/cli.py::main()` (was an unconditional
`build_session_identity` call before this round).

**Regression tests** (`tests/test_task79e_r2_activation_safety.py`):
- `test_broker_boundary_ignores_a_contradictory_caller_supplied_session_scope`
  — the exact reproduction scenario: session-B is the lifecycle's real
  session, authorization permits session-A, caller supplies session-A;
  the guard now rejects it because it checks session-B (the real one)
  against the authorization, not the caller's claim.
- `test_authorization_bound_to_real_session_id_not_fixed_category`,
  `test_authorization_bound_to_correct_live_session_id_permits`,
  `test_unrelated_session_id_rejected`,
  `test_same_session_recovery_permitted_across_reconstruction` —
  carried over, re-verified against the new derivation path.
- `test_combined_restart_recovery_scenario_through_real_session_runner`
  — proves across 3 simulated full-process restarts (via
  `resolve_session_identity`, not an in-memory object held across the
  test) that the SAME `session_id` is reused throughout a still-live
  session.

### 4. Runtime recovery — self-healing depended on an external call; restart lost pending-entry plans

**Reproduction:** ordinary ticks through `SessionRunner.process_tick`
never called `lifecycle.reconcile()` at all — only `cli.py`'s `start`
command called it once, before constructing `DecisionEngine`, and the
`supervise` path's `run_startup_sequence`. Once a session was running,
nothing periodically reconciled uncertain submissions, refreshed
adopted-but-pending orders, or caught up on outstanding exits — recovery
only ever happened at EOD or via a manually-invoked helper. Separately,
a full process restart rebuilt `DecisionEngine.positions` only from
OPEN lifecycle positions (`_rehydrate_positions`); an entry that was
merely accepted-and-pending (an `INTENT` record, not yet an OPEN
position) at "crash" time had no plan restored at all once it did fill.

**Fix:**
- `talonx_piv/session_runner.py::SessionRunner._maybe_reconcile` (line
  281), gated by new `reconcile_interval_seconds` (default 300.0, line
  103) and `_last_reconcile_wall` — called at the top of `process_tick`
  (right after the session-boundary reset, before `fetch_bars_latest()`)
  on every tick, runs unconditionally on the session's very first tick,
  and is rate-limited thereafter. A `reconcile()` failure is caught and
  logged (`PERIODIC_RECONCILE_FAILED_<ExceptionType>`,
  `status="RECONCILIATION_SKIPPED_LAST_KNOWN_STATE_RETAINED"`) — never
  crashes the tick loop, and the reconciliation flags simply retain
  their last-known (fail-closed) state on failure, so a failed or
  mismatched reconciliation degrades to blocking unsafe admissions
  rather than being silently ignored.
- `talonx_piv/lifecycle.py::_refresh_non_terminal_orders` (line 1114) —
  new; iterates every non-terminal order (excluding
  `UNCONFIRMED_TIMEOUT`, handled separately) on every `reconcile()`
  call, re-queries it, and applies the update — closes the
  "adopted-but-pending order sits stale forever" gap. Wired into
  `reconcile()` (line 1158).
- `talonx_piv/decision_engine.py::_rehydrate_pending_entries` (line 222)
  — new, called from `__post_init__` (line 188) immediately after
  `_rehydrate_positions()`. For any BUY-side INTENT record where
  `lifecycle.entry_still_pending_or_uncertain(symbol)` is true and no
  in-memory position already exists, restores a stop/target plan from
  the durable intent — closes "full-process restart fails to restore
  pending-entry plans."
- `talonx_piv/lifecycle.py::entry_still_pending_or_uncertain` (line
  261) broadened to also cover a stuck `"ORDER_INTENT"`-status intent
  (a crash between persisting the intent and calling `submit_order`),
  used by both the guard and the new rehydration path.

**Regression tests** (`tests/test_task79e_r2_activation_safety.py`):
- `test_combined_restart_recovery_scenario_through_real_session_runner`
  — the mandated end-to-end scenario, driven through REAL
  `SessionRunner.process_tick` calls (never a manually-invoked recovery
  helper as a substitute — the test builds a real `SessionRunner` +
  `DecisionEngine` + `PaperLifecycle` stack against
  `AlpacaContractTransport`, a fake modeling Alpaca's actual documented
  endpoints): accepted entry → simulated process restart (fresh
  `PaperLifecycle`/`DecisionEngine`/`SessionRunner` objects re-reading
  the same on-disk state, via `resolve_session_identity`) → delayed fill
  observed via periodic reconciliation → monitoring restored (plan
  rehydrated) → triggered partial exit → second restart with the
  recovered price → completed exit. Confirms reservations,
  experiment/decision linkage, and exit-trigger reasons are preserved
  across every restart.
- `test_accepted_unfilled_entry_keeps_exit_tracking`,
  `test_uncertain_entry_also_keeps_tracking_until_resolved`,
  `test_uncertain_entry_self_heals_into_decision_engine_once_resolved_and_filled`,
  `test_triggered_exit_reason_persists_and_survives_price_recovery_after_restart`,
  `test_rehydration_blocked_when_quantity_information_missing`,
  `test_rehydration_degraded_when_no_protective_levels`,
  `test_rehydration_healthy_case_still_reports_no_action_required` —
  carried over, re-verified against the broadened rehydration path.

## Test count change

`tests/test_task79e_r2_activation_safety.py`: **24 → 27** (net +3):
4 new tests
(`test_broker_boundary_ignores_a_contradictory_caller_supplied_session_scope`,
`test_combined_restart_recovery_scenario_through_real_session_runner`,
`test_forced_eod_exit_unaffected_by_unknown_fill_timing`,
`test_repeated_404s_never_auto_confirm_not_submitted_then_order_appears_and_is_adopted_once`),
1 test removed as superseded (`test_single_404_never_confirms_not_submitted`
— its scenario is now the FIRST phase of the more complete
`test_repeated_404s_...` test above, which additionally proves the
later-discovered-and-adopted-once behavior the old test could not
express under the old threshold design).

No other `test_task79e_*` file changed its test COUNT (fixture-only
edits: `session_id` on `EventBus` construction, explicit `filled_at`
arguments). Confirmed via direct function-count comparison against this
round's own starting commit `c9a4994` for every touched test file.

## Full repository regression suite

Baseline supplied by this round's own task brief (== the prior "Task
79E-R2" round's own final confirmed count, at commit `c9a4994`):
**2521 passed / 1 skipped / 10 xfailed**.

This round adds net +3 tests (see above), so the expected authoritative
total is **2524 passed / 1 skipped / 10 xfailed**.

Commands run, in order, with zero further code edits in flight once the
final full runs started:

```
.venv/Scripts/python.exe -m pytest tests/test_task65b_decision_engine.py::test_stop_hit_triggers_controlled_exit tests/test_task76s_protective_exit_eod.py::test_disable_entries_after_opening_protective_exit_still_works tests/test_task79e_decision_engine_experimental.py::test_exit_remains_available_after_experimental_entry -q
.venv/Scripts/python.exe -m pytest tests/test_task79e_r2_activation_safety.py -q
.venv/Scripts/python.exe -m pytest tests/ -k "lifecycle or decision_engine or session_runner or eod or supervisor or observability or dashboard or startup or task79e or task65b or task76s or task78i or task77i or task72o or task71s" -q   # run TWICE for flakiness confirmation
.venv/Scripts/python.exe -m pytest tests/ -q   # FULL run #1 -- surfaced 1 more flaky test (see above), fixed, then:
.venv/Scripts/python.exe -m pytest tests/test_task76s_protective_exit_eod.py::test_target_hit_triggers_controlled_exit_unaffected_by_contract -q   # x5, confirming determinism
.venv/Scripts/python.exe -m pytest tests/ -q   # FULL run #2 -- clean, only the 2 pre-existing unrelated failures
.venv/Scripts/python.exe -m pytest tests/ -q   # FULL run #3 -- confirmation re-run, see regression_results_r2_2_confirm.txt
```

Raw output: `regression_results_r2_2.txt` (FULL run #2, the first clean
run after the last code fix) and `regression_results_r2_2_confirm.txt`
(FULL run #3, an independent confirmation re-run with zero code changes
between the two) in this directory. FULL run #1's raw output, which
surfaced the 3rd flaky test before it was fixed, is not separately
retained (its terminal summary was captured in this document's own
revision history via the Monitor tool output shown during that run);
its outcome was `2 failed [pre-existing] + 1 failed [flaky,
subsequently fixed], 2521 passed`, and is fully accounted for above.

**Final result (FULL run #2): `2 failed, 2522 passed, 1 skipped, 10
xfailed, 48 warnings in 861.12s (0:14:21)`.**

**Confirmation result (FULL run #3): `2 failed, 2522 passed, 1 skipped,
10 xfailed, 48 warnings in 856.43s (0:14:16)` — identical to run #2
(same 2 pre-existing, unrelated failures; same 2522 passed count).
Two consecutive independent full-suite runs, zero code changes between
them, produced byte-identical pass/fail/skip/xfail counts — the
regression suite is confirmed stable, not merely lucky once.**

**Reconciliation:** 2522 passed + 2 failed = 2524 total outcomes,
exactly matching the expected 2521 + 3 = 2524. Skipped (1) and xfailed
(10) counts are unchanged from baseline, as expected (no skip/xfail
markers touched by this round).

**The 2 failures, explained:**
`tests/test_yfinance_poller.py::test_healthy_cycle_does_not_reset_session`
and `tests/test_yfinance_poller.py::test_degraded_cycle_is_not_silently_treated_as_healthy`
fail with `AssertionError: Expected mock to have been awaited once.
Awaited 0 times.` This module (`talonx_ingest.market_data.yfinance_poll`)
is entirely unrelated to this round's diff (PIV paper-trading
activation lifecycle) — it was never touched, directly or transitively,
by any file changed in this round. **Reproduced on the pristine starting
commit `c9a4994` itself**, via `git stash` (removing every change this
round made) followed by re-running just these 2 tests: they fail
identically, in isolation, in 0.20s, with the exact same assertion
error, on the UNMODIFIED baseline. This proves the failure is a
pre-existing environment/dependency-drift issue (this repo's installed
`pytest-asyncio` is `1.4.0`; the failure pattern — an `AsyncMock` used
as an `asyncio.sleep` replacement never being awaited — is consistent
with an `asyncio.sleep`/mock-library interaction that changed
independently of this round's own code, not a code regression), not
something this round introduced, broke, or is required to fix (out of
this round's own explicit scope — "fix related defects found in this
lifecycle" refers to the PIV paper-trading activation lifecycle, not the
unrelated yfinance market-data ingestion module). Not fixed, not waived
silently — disclosed here with full reproduction evidence per the "no
waived failures" instruction. Every other file in the full collection
passed, including every `test_task79e_*`, `test_task65b_*`,
`test_task76s_*`, `test_task77i_*`, `test_task78i_*` file.

## Corroborating evidence: a pre-existing rehearsal scenario's own recorded evidence changed

`results/task78i_full_application_rehearsal/rehearsal_scenarios.csv`,
scenario `12_crash_restart_outstanding_work` — its `observed` column's
`reconciled` field flipped from `reconciled=False` to `reconciled=True`
purely as a side effect of re-running
`tests/test_task78i_stage5_rehearsal.py` against this round's own
Requirement 4 fix (`_refresh_non_terminal_orders`). This is independent,
incidental corroboration that the periodic-reconciliation fix changes
real, previously-recorded behavior in the direction required — a
crash-restart scenario that used to leave `reconciled=False` in its own
evidence file now genuinely reconciles.

## Hard boundary confirmations (unchanged from the prior round, re-verified)

- **No live session started.** No `supervise`/`start --confirm-paper-session-start` invocation occurred.
- **No broker mutations.** No `eod`/`kill-switch`/`cleanup` command run against a real PAPER broker.
- **No notifications sent.** Every test uses a fake `send` callable / fake pubsub.
- **No production permission enabled.** No `experimental_authorization.json` exists anywhere in this repository, tracked or untracked (re-confirmed at the end of this round).
- **No strategy-validation promotion.** `strategy_approval_status` is never set to `APPROVED` by anything in this diff's production code (test fixtures' own `strategy_approval_status_override=StrategyApprovalStatus.APPROVED` remains test-only, unchanged pattern from every prior round).
- **No holdout data accessed. No protected `talonx_quant` files changed. No alpha tuning.**
- **Long-only enforcement, `UNVALIDATED` status, Gemini non-authority, and EOD safety** — all untouched by this round's production diff; EOD safety additionally re-proven directly by `test_forced_eod_exit_unaffected_by_unknown_fill_timing`.

## Verdict

# **PASS**

All 4 items from this round's task brief have a concrete reproduction
of the prior defect, a concrete implementation fix, and at least one
regression test that fails against the pre-fix code and passes against
the fix:

1. **Uncertain submissions** — count-based auto-resolution removed;
   backoff-only rate limiting; explicit operator-resolution escape
   hatch; proved via the exact reproduction (timeout → several 404s →
   original order appears → adopted once, no premature capacity
   release, no duplicate entry).
2. **Fill-time causality** — real broker-sourced `first_fill_observed_at`
   replaces the "already OPEN" boolean; unknown timing always fails
   closed; proved via pre-fill/overlapping bars rejected, valid
   post-fill bars accepted, and forced EOD exits unaffected, all through
   actual `on_bars` wiring.
3. **Independent session enforcement** — the broker-entry guard now
   derives and checks its own session identity, rejecting a
   contradictory caller-supplied value; proved via the exact
   reproduction scenario. Full-process session recovery
   (`resolve_session_identity`) closes the "in-memory EventBus
   reconstruction only" gap, proved via 3 simulated full-process
   restarts reusing the same session_id.
4. **Runtime recovery** — bounded, rate-limited reconciliation now runs
   inside the live tick loop itself, and a full-process restart now
   restores a still-pending entry's plan from its durable intent, not
   only from an OPEN position; failed/mismatched reconciliation degrades
   to fail-closed, never silently ignored. Proved end to end through
   real `SessionRunner.process_tick` calls across the mandated combined
   scenario (accepted entry → restart → delayed fill → restored
   monitoring → triggered partial exit → restart with recovered price →
   completed exit), never a manually-invoked recovery helper.

All prior mandatory acceptance requirements (this round's own
`findings_and_tests_report.md`, Requirements 1-6, and everything in the
chain before it) remain evidenced and unbroken — every one of those
tests still passes unchanged in intent (see the "Test count change"
section above: no pre-existing `test_task79e_*` file lost a test, only
gained fixture updates required by the new fill-time-causality gate).

Full repository regression suite reconciles exactly against baseline +
new tests, with the only 2 non-passing outcomes proven (via reproduction
on the unmodified starting commit) to be pre-existing and unrelated to
this round's diff — zero regressions, zero waived failures belonging to
this round's own scope.

**Disabled-by-default is unchanged: no `experimental_authorization.json`
exists anywhere in this repository** (re-confirmed at the end of this
round — see the boundary confirmations above). See
`task80_launch_handoff_refresh_r2_2.md` for the still-recommended
posture (do not activate as part of Task 80).

**Then STOP** — awaiting the operator's own separate authorization for
Task 80, and for whether to ever author a live authorization file.
