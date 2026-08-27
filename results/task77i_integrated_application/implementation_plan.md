# Task 77I — Implementation Plan

## Intended flow (Stage 0 requirement)

```
Market inputs (bars, published QuantSignal)
  -> decide() [talonx_piv.decision_contract, unchanged pure function from Task 76S]
  -> DecisionLedger.record() [NEW, durable -- must succeed or the entry is blocked]
  -> three INDEPENDENT branches, each wrapped so a failure in one cannot block another:
       - NotificationOutbox.enqueue()/dispatch_pending()  [NEW -- Stage 2]
       - ShadowLedger.consider_entry()/on_bar()            [NEW -- Stage 3]
       - PaperLifecycle.order_intent() (existing, Task 76S hardened boundary) -- only
         reached at all when decision.recommendation == BUY/SELL_TO_CLOSE
```

Enqueue/shadow calls from `decision_engine.py` are each wrapped in their own
`try/except Exception: pass` so a Telegram outage cannot suppress shadow creation, and a
shadow-ledger bug cannot suppress a notification or (most importantly) cannot suppress or
alter the real order_intent call, which is reached through completely separate code with no
dependency on either. `order_intent`'s own hardened boundary (Task 76S) is untouched by this
task except for the two specific, disclosed fixes below.

## Reuse decisions (not parallel implementations)

- **Durable ledger pattern**: `LifecycleState`'s `_load`/`_save` full-file-JSON-rewrite pattern
  (already the established persistence idiom in this codebase, also used by
  `eod_lifecycle.py`'s `eod_state.json`) is reused verbatim for `DecisionLedger`,
  `NotificationOutbox`, and `ShadowLedger` -- no new persistence mechanism invented.
- **Notification adapter**: the existing `talonx_piv.telegram.sender(token, chat_id)` factory
  (a bare `Callable[[str], bool]`) is reused unchanged as the outbox's send adapter. Tests
  supply a fake callable; production code is never changed to call Telegram directly.
- **Shadow execution semantics**: `talonx_backtest.execution` (`ExecutionConfig`,
  `apply_entry_cost`, `apply_exit_cost`, `check_bar_for_exit`) -- the exact, already-tested
  cost model and same-bar stop/target ambiguity rule (stop-first, conservative) used by the
  historical backtest engine -- is imported and reused directly by `ShadowLedger`, rather than
  reimplementing cost/ambiguity logic. `talonx_backtest.engine.py`'s own `_PendingEntry`
  next-bar-open fill convention (documented in `execution.py`'s module docstring: "a published
  signal's entry is executed at the OPEN of the NEXT bar... never a same-bar close") is
  replicated exactly for the same non-lookahead reason. `TradeSimulator`'s stateful class
  itself is NOT reused as-is (it holds a live pydantic `QuantSignal` + `datetime` objects that
  do not round-trip through JSON) -- `ShadowLedger` persists its own primitive-typed
  `ShadowPosition` record using the reused pure functions for computation. This split is
  recorded here so it is not mistaken for reinventing the execution model.
- **Event bus**: `events.py::EventBus`/`PivEvent` (already durable-write-before-notify, see
  `EventBus.emit`: the local JSONL append happens unconditionally before the best-effort
  Telegram attempt, which is already wrapped so a Telegram exception cannot raise past
  `emit`) is left completely unmodified and continues to record raw operational telemetry.
  The new `DecisionLedger`/`NotificationOutbox`/`ShadowLedger` are additive, keyed by
  `decision_id`, and never replace or duplicate `piv_events.jsonl`.

## Decision contract wiring -- the one substantive behavior change

`decision_engine.py`'s `_handle_entry`/`_check_exit` currently decide BUY/SELL with their own
ad hoc logic (bullish + flat -> buy; stop/target cross -> sell) and never consult strategy
approval at all. After wiring, both call `decision_contract.decide(...)` with
`strategy_approval_status` **hardcoded to `StrategyApprovalStatus.UNVALIDATED`** for every real
caller (no registry exists; none is invented here, per instruction). Consequence, stated
explicitly because it is a real behavior change and the whole point of this stage: **a real,
natural QuantScanner BULLISH signal can no longer reach `order_intent` at all**, even if an
operator later populates `paper_entry_settings.json` -- `decide()` will resolve to
`NO_TRADE` / `STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION` before execution eligibility is
even evaluated. This is the correct, intended tightening ("Production entries remain blocked
unless an independently authorised strategy and PAPER setting already permit them. Do not
create such approval in this task") -- previously this was blocked only incidentally (an empty
`paper_entry_settings.json`), now it is blocked structurally at the decision layer too.

A test-only override (`DecisionEngine(..., strategy_approval_status_override=...)`, defaulting
to `None` meaning "always UNVALIDATED") lets integration tests exercise the full BUY/shadow/
alert path without inventing a production approval mechanism -- `cli.py` never sets this
parameter (grep-provable), so it is not reachable from any real code path.

## Shadow tracking is gated on the SAME actionability bar as PAPER execution

`ShadowLedger.consider_entry` only opens a shadow position when `decision.recommendation ==
Recommendation.BUY` -- i.e. only for an APPROVED-strategy decision, exactly mirroring the real
broker gate. This is a deliberate design choice, not an oversight: gating shadow P&L on raw
signal direction (ignoring strategy-approval) would let an unvalidated strategy accumulate an
informal, unaudited "shadow track record" as a backdoor substitute for the real validation this
whole research program (Tasks 74S/75S) has been careful never to manufacture accidentally. See
`shadow_simulation_policy.md`. Consequence: today, with no approval registry, shadow tracking
is (like PAPER execution) inert for real natural-strategy traffic and is exercised in this
task only via `TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE` fixtures and the E2E scenarios.

## Partial-fill accounting fix (disclosed Task 76S follow-up item 4)

`PaperLifecycle.apply_broker_update`'s closing-sell branch marks a position `CLOSED` and
deletes its `open_position_by_symbol` entry on the FIRST fill update it sees for a closing sell
order, using the position's original ENTRY quantity (not the actual fill quantity) to compute
`gross_pnl`. A second fill-status transition on the SAME order (e.g. `partially_filled` ->
`filled`) then falls through to the `else` (open-side) branch and fabricates a phantom new
`OPEN` position for a SELL fill, orphaned (never reachable via `open_position_by_symbol`, so
never sellable again) -- which would show up as a false-positive internal position in
`reconcile()`, risking a false `EOD_RECONCILIATION_FAILED`. Fixed in Stage 1 by: (1) tracking
per-order incremental fill deltas (Alpaca reports cumulative `filled_qty`; the delta since the
previous stored value is what actually happened this update), (2) accumulating exit quantity
and realized P&L per position across every closing fill, and (3) only finalizing the position
(status `CLOSED`, remove `open_position_by_symbol` mapping) once cumulative exit quantity
reaches the position's full remaining size -- a genuine partial close reduces the position and
leaves it `OPEN` with the correct remaining quantity, never orphaning a second phantom record.
See `partial_fill_before_after.md`.

## Timed-out submissions ("uncertain until reconciled")

`poll_order_until_terminal` previously returned silently on timeout with no state change and no
signal that the true broker outcome is unknown -- nothing prevented treating that order as
inert. Fixed: on timeout it marks the order's persisted status `UNCONFIRMED_TIMEOUT` (a
sentinel deliberately outside `_TERMINAL_ORDER_STATUSES`, so oversell/pyramiding/pending-entry
guards continue to treat it as outstanding) and emits a `BROKER_ERROR` event. `reconcile()` is
extended to actively resolve any `UNCONFIRMED_TIMEOUT` order by re-querying
`broker.get_order()` and applying the real status via the (now-fixed) `apply_broker_update` --
restart-safe since this state is persisted and re-resolved on the next `reconcile()` call
(EOD, probe pre-check, or a manual CLI invocation).

## Concurrency -- disclosed, not invented

No file-locking architecture exists anywhere in this codebase today (confirmed by search). This
task does not add cross-process advisory locking -- inventing one would be a new architectural
component, not a bounded safety fix, and risks a false sense of guarantee on Windows. What
already holds, and is what actually protects the required test scenarios:
- `order_intent` is a single synchronous method with no `await`/yield point -- within one
  Python process (the only way two "competing" natural-strategy or probe calls can originate
  today, since there is exactly one live session process), calls cannot interleave.
- Every guard re-reads `self.state` (already in memory, freshly mutated) on every call -- a
  second call in the same process always sees the first call's effect.
- A second, genuinely separate OS process (e.g. a manual `cli.py kill-switch` invoked in another
  terminal while a live session runs) only ever reaches the bulk-flatten/kill-switch path, never
  `order_intent` -- so the one code path that mutates per-order state has no real multi-process
  writer in the current architecture. This is recorded, not silently assumed -- see
  `broker_state_and_concurrency_evidence.json`.

## Dashboard/observability surface (Stage 4)

`dashboard.py`/`dashboard_web.py`/`dashboard_web_static/` belong to a different, unrelated
subsystem (`talonx_dispatch`/`talonx_core`/`talonx_brain`/`talonx_paper`) with zero existing
awareness of `talonx_piv` (confirmed by grep -- no match for `talonx_piv`/`piv_events`/`PIV` in
either file). Per the task's own fallback clause ("If no suitable existing surface exists,
provide the minimal read-only projection and document the remaining UI connection"), this task
extends the existing PIV-native surfaces instead of touching that unrelated dashboard:
`reporting.py::build_session_report` (already the canonical end-of-session PIV projection) gets
new read-only counters for decision/notification/shadow ledgers, and a new minimal read-only
`talonx_piv/observability.py::build_integrated_projection()` function aggregates all four
ledgers (events, decisions, notifications, shadow) into one JSON projection for a future UI to
consume -- no server, no order-placement controls, no redesign of any existing report shape.
