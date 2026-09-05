# Task 79E-R1 — Close Experimental Activation Blockers — Findings & Tests

## Scope and starting point

Continuation from `84d8c73` (Task 79E) on `research/talonx-strategy-validation`.
Task 79E built a disabled-by-default experimental PAPER/shadow permission
mechanism and declared it `EXPERIMENTAL_MODE_READY_FOR_OPERATOR_REVIEW`, but
explicitly disclosed it as untested in several dimensions that only matter
once an operator actually enables it. This task re-audited the mechanism
end-to-end specifically for what would break in *enabled* mode, fixed every
confirmed defect, and re-verified the full repository regression suite.

Deadline: release-review cutoff Friday 28 August 2026, 06:00 UK / 05:00 UTC.
Clock checked repeatedly against the real system clock throughout (see
"Clock checks" below) — never assumed.

## Method

Each of the five required areas was checked against the ACTUAL code (not
assumed from Task 79E's own documentation), a concrete failure scenario was
constructed, and — where the defect was real — fixed in place with a
regression test proving the fix. Two areas (`shadow_ledger.py`/
`notification_outbox.py`'s alert/shadow independence, `eod_lifecycle.py`'s
source-agnostic flattening) were re-verified as already correct from Task
79E and are unchanged.

## Findings and fixes, by area

### 1. Exit recovery and partial fills — REAL DEFECTS, FIXED

- **`DecisionEngine.positions` was never rehydrated after a restart**
  (Task 79E's own disclosed gap, `remaining_issues.md` item 1). A crashed/
  restarted process silently lost every open position's stop/target plan
  until EOD force-flatten. **Fixed**: `lifecycle.order_intent` now persists
  `target_price` and the entry signal's `entry_signal_bar_timestamp`
  alongside `stop_price` on the position record (previously only
  `stop_price` survived a fill); `DecisionEngine._rehydrate_positions()`
  rebuilds `self.positions` from `lifecycle.state.positions` on
  construction, restoring the full plan.
- **`_check_exit` untracked a position the instant an exit was DECIDED, not
  when it was CONFIRMED flat** — a rejected, failed, timed-out, or
  partially-filled sell attempt silently abandoned all further monitoring
  for that symbol (nothing would ever retry it short of EOD). **Fixed**:
  the position is now only removed from `self.positions` after
  `lifecycle._open_position_for(symbol)` confirms CLOSED; a
  rejected/uncertain/partial attempt keeps the position tracked and
  re-attempts on the next bar.
- **Exit orders were sized to the fixed `PIV_QUANTITY` constant**, not
  actual remaining holdings — wrong for any position that has already
  partially exited. **Fixed**: added `PaperLifecycle.remaining_holdings()`
  (actual holdings minus whatever is already pending/uncertain-sell), used
  to size every exit attempt; a `<= 0` result means an attempt is already
  fully in flight and a duplicate submission is skipped.
- **Missing plans failed silently, not visibly**: an OPEN lifecycle
  position with no `self.positions` entry was simply never monitored, with
  no signal to an operator. **Fixed**: `_flag_orphaned_positions` emits a
  `BROKER_ERROR` (`MISSING_EXIT_PLAN_FOR_OPEN_POSITION`) for any such
  symbol observed in a tick's bars — never invents a plan for it.

### 2. Entry/exit causality — REAL DEFECT, FIXED

- **`on_bars` evaluates `_check_exit` against the SAME bar just fed to
  `_handle_entry`, in the same tick** — a fresh entry's own bar `low`/`high`
  could immediately trigger its own stop/target before any fill occurred.
  **Fixed, in two iterations** (see "Process note" above for the full
  story): the final design is purely structural, never wall-clock-based.
  `on_bars()` itself tracks which symbols received a brand-new position
  from a signal drained THIS tick and passes that set to `_check_exit` as
  `skip_price_check`; a forced EOD exit is time-based and always bypasses
  it. A DIRECT `_check_exit` call — every pre-existing test/caller that
  does not go through `on_bars()`, including
  `test_task76s_protective_exit_eod.py`'s pre-existing
  `test_entry_readiness_failure_does_not_disable_position_management` —
  is therefore never causality-gated at all, exactly its
  pre-Task79E-R1 behaviour; only `on_bars()`'s own same-tick
  entry-then-check sequence is affected.
- **Experimental signal freshness only checked message age, not session
  eligibility**: `_experimental_permissions` now also rejects a symbol not
  in `warmup_ready_symbols` (when warmup has actually run for this engine),
  so a fresh-looking but off-session/unwarmed symbol cannot reach the
  experimental path.

### 3. Session binding and revocation — REAL DEFECTS, FIXED

- **`session_scope` was parsed and stored but NEVER checked** by
  `permits_entry`/`permits_paper_execution` — a live REGULAR session would
  honor an authorization scoped to any other session type without
  complaint. **Fixed**: both methods now take a required `session_scope`
  argument and reject on mismatch (`WRONG_SESSION_SCOPE`); both real
  callers (decision layer and lifecycle broker boundary) pass the same
  fixed `"REGULAR"` constant identifying the live natural-strategy decision
  path (the isolated `PIV_LIFECYCLE_PROBE` lifecycle never routes through
  `order_intent(source="EXPERIMENTAL")` at all, so it is structurally
  excluded regardless).
- **The `ExperimentalAuthorization` object was loaded ONCE at process start
  and cached** in both `PaperLifecycle` and `DecisionEngine` — deleting,
  disabling, or editing `experimental_authorization.json` mid-session had
  NO effect until the next process restart (only expiry, which re-checks
  `now`, worked live). **Fixed**: added an optional
  `experimental_authorization_path` to both classes; when set, every
  permission check reloads the file FRESH from disk (never a cached
  object) via `_current_experimental_authorization()`. `cli.py::runtime()`
  now wires the PATH (not a pre-loaded object) into both constructors, so
  production gets live revocation for free. The pre-existing
  `experimental_authorization=<object>` construction path remains fully
  supported unchanged for every test that wants a fixed object.
- Revocation between decision and broker-boundary submission is proven by
  `test_revocation_between_decision_and_submission_via_file_deletion` — the
  file is deleted from inside a wrapped `order_intent` call, after the
  decision layer already approved, and the submission is still blocked.

### 4. Pending exposure and durable budgets — REAL DEFECTS, FIXED

- **`max_concurrent_exposure` only counted CONFIRMED OPEN positions** — two
  different symbols could each pass a `max_concurrent_exposure=1` guard
  back-to-back before either one's order actually filled (symbol A
  SUBMITTED-but-not-yet-FILLED when symbol B's own check ran and saw zero
  OPEN positions). **Fixed**: the guard now counts a per-symbol SET of
  OPEN positions, non-terminal pending orders, and orphaned
  `SUBMIT_FAILED_UNCERTAIN` intents — all tagged to the same
  `experiment_id` — so pending/uncertain exposure blocks a second symbol
  exactly like a confirmed one, without double-counting a single symbol's
  own partial-fill-plus-outstanding-remainder.
- **Uncertain submissions were never reconciled** — a
  `SUBMIT_FAILED_UNCERTAIN` intent (the request raised before any broker
  order id was received) stayed that way forever, permanently blocking
  `PENDING_ENTRY_EXISTS` for that symbol with no path to resolution and no
  visibility into whether the order actually reached the broker.
  **Fixed**: added `AlpacaPaperClient.find_order_by_client_id` (looks the
  order up by its stable, locally-derived `client_order_id` — never a
  blind resubmit) and `PaperLifecycle._resolve_uncertain_submissions()`,
  called from `reconcile()`: found → adopted into `state.orders` and its
  real status applied exactly as `poll_order_until_terminal` would have;
  not found → marked `SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED` (frees the
  pyramiding guard; the experimental budget reservation, if any, is
  deliberately NOT refunded even now — conservative in case the broker's
  own "not found" read is itself unreliable).
- **The durable budget record was trusted blindly**: a corrupted
  (non-dict, negative, boolean, non-finite) `experimental_budgets[id]`
  entry, or a MISSING entry despite real prior activity under that
  `experiment_id` (state loss, not a fresh start), would have crashed or
  silently reset spend to zero. **Fixed**:
  `PaperLifecycle._validated_budget_record` strictly validates the shape
  and fails closed (`EXPERIMENTAL_BUDGET_STATE_DAMAGED_FAIL_CLOSED`)
  without ever overwriting the damaged value — it is left in place as
  forensic evidence, and a `BROKER_ERROR` event carries a serialized copy
  of it.
- **Reference price accepted any non-`None` value**, including negative,
  zero, boolean, or non-finite — now validated as a genuine finite positive
  price (`EXPERIMENTAL_REFERENCE_PRICE_INVALID`).

### 5. Integration and reporting — VERIFIED ALREADY CORRECT, ONE ADDITION

- Alert/shadow independence under PAPER-disabled, budget-exhausted, or
  broker-unavailable failure was already structurally correct (both the
  notification and shadow-ledger calls happen in `_record_decision`, before
  `order_intent` is ever attempted) — re-verified with a NEW explicit test
  for the budget-exhausted case specifically (not previously tested),
  `test_budget_exhausted_still_preserves_alert_and_shadow`.
  `strategy_approval_status` is never promoted to `APPROVED` by anything in
  this diff (unchanged grep-provable invariant); Gemini enrichment remains
  non-authoritative and unchanged.
- `eod_lifecycle.py`'s flattening is source-agnostic
  (`broker.close_all_positions()` + a uniform loop over
  `lifecycle.state.positions`) — re-confirmed unchanged; no special-casing
  needed for experimental positions.
- `observability.py`'s per-decision execution-status join previously
  collapsed a resolved `SUBMIT_FAILED_UNCERTAIN`/
  `SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED` intent into the misleading
  `SUBMITTED_NO_BROKER_ACK_YET` bucket — added two explicit statuses
  (`SUBMISSION_UNCERTAIN_PENDING_RECONCILE`, `CONFIRMED_NOT_SUBMITTED`) so
  the dashboard/report never implies an outcome that was never actually
  observed.

## Tests

**26 new tests** across three files (59 pre-existing Task 79E tests +
26 = 85 total across the four `test_task79e_*` files, confirmed via
`pytest --collect-only`):

- `tests/test_task79e_r1_activation_safety.py` — **21 new tests**, one per
  reproduced defect above: restart rehydration (with experimental-identity
  survival), partial-fill retry sizing, rejected-exit retry, missing-plan
  visibility, same-bar-as-entry causality (both directions), wrong-session
  rejection, revocation-between-decision-and-submission,
  disablement-at-broker-boundary, mid-session binding edit, two-symbols-
  competing-for-one-slot, both uncertain-submission reconciliation outcomes
  (confirmed-not-submitted and confirmed-adopted), six damaged-budget
  shapes (parametrized), missing-budget-with-prior-activity, five invalid
  reference-price shapes (parametrized), and budget-exhausted alert/shadow
  preservation.
- `tests/test_task79e_experimental_authorization.py` — **4 new tests**
  (`test_wrong_session_scope_rejected`, `test_missing_session_scope_rejected`,
  `test_matching_session_scope_permits`,
  `test_wrong_session_scope_blocks_paper_execution_too`) plus a one-line fix
  to the shared `_binding()` fixture (added `session_scope="REGULAR"`) so
  every pre-existing direct `permits_entry`/`permits_paper_execution` call
  keeps its prior meaning under the new required parameter.
- `tests/test_task79e_lifecycle_experimental.py` — **1 new test**
  (`test_wrong_session_scope_rejected` at the `order_intent` boundary) plus
  a one-line fix to the shared `_order()` fixture (added
  `experimental_session_scope="REGULAR"`) for the same reason.

Every pre-existing test file touched by this diff was re-run and confirmed
either unchanged or fixed for a genuine, disclosed reason:

- `tests/test_task76s_protective_exit_eod.py::test_entry_readiness_failure_does_not_disable_position_management`
  caught an overly-strict first draft of the causality fix (see Area 2
  above) — the fix was corrected, not the test weakened.
- All 244 tests across every `lifecycle`/`decision_engine`/`session_runner`/
  `eod`/`supervisor`/`observability`/`dashboard`/`startup`/`task79e`-matching
  file pass unchanged otherwise.
- All `cli`-dependent test files (`test_task78i_cli_supervise.py`,
  `test_task78i_cli_ownership.py`, `test_task73s_control_fixture.py`,
  `test_task66a_runtime_parity.py`) pass against the new
  `experimental_authorization_path`-based `runtime()` wiring.

## Full repository regression suite

Baseline (Task 79G, carried through Task 79E): **2412 passed**.
Task 79E added 59 tests → **2471 passed / 1 skipped / 10 xfailed** (its own
final verified number).

This task adds **26** new tests (21 + 4 + 1, all listed above) on top of
that, so the expected authoritative total is **2497 passed** (2471 + 26),
skipped/xfailed counts unchanged.

Raw output: see `regression_results.txt` in this directory.

**Process note, disclosed rather than hidden** (same posture as Task 79E's
own final report): the first two full-suite attempts for this task were
NOT used as evidence.
- The first (`2464`-era background run from the START of this session) was
  launched, then invalidated by continued edits made while it ran — never
  used.
- The second full run (2496 passed, 1 failed) surfaced a genuine,
  reproducible defect: an earlier draft of the entry/exit causality fix
  (Area 2) compared `bar.timestamp > position.entry_bar_timestamp` using
  wall-clock `datetime.now()` values. Direct measurement on this execution
  environment showed two back-to-back `datetime.now(timezone.utc))` calls
  (with real serialization work between them) can return
  BIT-IDENTICAL values — `later > earlier` silently evaluated `False`.
  This was caught by `tests/test_task65b_decision_engine.py::
  test_stop_hit_triggers_controlled_exit` failing in the FULL suite while
  passing 20/20 in isolation (the tell-tale sign of a timing-sensitive,
  not state-sensitive, defect). The design was replaced with a
  wall-clock-free, purely structural mechanism: `on_bars()` itself tracks
  which symbols received a brand-new position from a signal drained THIS
  tick, and passes that set explicitly to `_check_exit` as
  `skip_price_check` -- a direct `_check_exit` call (every existing test
  that does not go through `on_bars()`) is never causality-gated at all,
  restoring its pre-Task79E-R1 behaviour exactly. See Area 2 below and the
  `OpenDecisionPosition`/`_check_exit`/`on_bars` docstrings in
  `decision_engine.py` for the full rationale.
- The THIRD full run, executed with the corrected design and zero further
  code edits in flight, is the one this verdict relies on.

**Confirmed final result: 2497 passed, 1 skipped, 10 xfailed, 0 failed,
exit code 0** — reconciles exactly with the predicted `2471 + 26 = 2497`.
See `regression_results.txt` for the raw output.

## Clock checks performed (never assumed)

- At task start (continuation directive received): `2026-08-28T00:41:37Z`
  (UK: `01:41:37 BST`), ~4h18m before the 05:00 UTC cutoff.
- Before beginning implementation (after reviewing Task 79E's own
  artifacts): `2026-08-28T00:47:10Z` (approx), ~4h13m remaining.
- Before launching the first (later-discarded) background full-suite run:
  ~4h05m remaining.
- After completing the core lifecycle.py/decision_engine.py/cli.py
  implementation and the new regression-test file, before the first
  authoritative-attempt full-suite run: `2026-08-28T01:14:00Z` (approx),
  ~3h46m remaining.
- After diagnosing and fixing the wall-clock causality defect (see
  "Process note" above): ~3h21m remaining.
- At the confirmed, zero-failure authoritative regression result:
  ~3h06m remaining before the 05:00 UTC / 06:00 UK cutoff.

## Verdict

# **ACTIVATION_BLOCKERS_CLOSED — EXPERIMENTAL_MODE_READY_FOR_OPERATOR_REVIEW**

Every activation blocker named in the task brief (exit recovery and
partial fills, entry/exit causality, session binding and revocation,
pending exposure and durable budgets, integration/reporting independence)
was reproduced against a concrete failure scenario, fixed in place, and
covered by a new regression test. The mechanism remains completely inert
in this repository today — no `experimental_authorization.json` exists
anywhere, tracked or untracked — so nothing about today's actual
production behaviour has changed; this task closes what would have broken
had an operator turned it on, not anything currently reachable.

Full repository regression suite: **2497 passed / 1 skipped / 10 xfailed /
0 failed** (exit code 0), reconciling exactly against baseline + new
tests. One genuine defect (the wall-clock causality comparison) was found
and fixed DURING this task's own verification process, not discovered
after the fact — disclosed honestly above rather than hidden.

Disabled-by-default is unchanged and still the operator's own decision to
lift; see `task80_launch_handoff_refresh.md` for activation instructions
and the still-recommended posture (do not activate as part of Task 80
itself). All hard-boundary confirmations below hold.

Then STOP — awaiting the operator's separate authorization to author a
live `experimental_authorization.json`, if they choose to at all. No
activation, launch, trading, or research starts automatically.

## Hard boundary confirmations

- **No live session started.** No `supervise`/`start
  --confirm-paper-session-start` invocation occurred.
- **No broker mutations.** No `eod`/`kill-switch`/`cleanup` command run
  against a real PAPER broker.
- **No notifications sent.** Every test uses a fake `send` callable.
- **No production permission enabled.** No `experimental_authorization.json`
  exists anywhere in this repository, tracked or untracked.
- **No strategy-validation promotion.** `strategy_approval_status` is never
  set to `APPROVED` by anything in this diff.
- **No holdout data accessed. No protected `talonx_quant` files changed.**
- **No task-owned background jobs left running** at the time this report's
  verdict was finalised.

## Remaining, non-blocking issues (disclosed)

1. `OpenDecisionPosition.exit_reason` (the in-memory latch that keeps a
   triggered exit being retried across bars even if price recovers) is
   NOT itself persisted to `lifecycle.state` — only `stop_price`/
   `target_price`/`entry_signal_bar_timestamp` are. A process restart
   strictly BETWEEN a triggered-but-unconfirmed exit and its resolution
   will re-derive the SAME trigger from the recovered stop/target on the
   next bar in the overwhelmingly common case (price still past the
   stop/target), but a restart during the rare window where price has
   since recovered mid-exit would not automatically re-trigger. This is a
   narrower residual gap than the ORIGINAL "no rehydration at all" defect
   this task closes, not a new one it introduces.
2. `find_order_by_client_id` relies on Alpaca's documented
   `client_order_id` query-filter support on `GET /v2/orders`; this task's
   fakes model that contract but it has not been exercised against a real
   Alpaca paper endpoint.
3. Task 79E's own disclosed item 4 (`observability.py`'s experimental
   section has no win-rate/P&L rollup) remains out of scope, unchanged.
