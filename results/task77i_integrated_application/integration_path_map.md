# Task 77I — Integration Path Map (Stage 0)

## Live decision entry point
`talonx_piv/decision_engine.py::DecisionEngine._handle_entry` (per published `QuantSignal`) and
`::_check_exit` (per tick, per symbol with a tracked open position). Both are driven by
`SessionRunner.process_tick` -> `DecisionEngine.on_bars`, which itself is only fed
readiness+warmup+freshness-gated symbols (see `session_runner.py:315-331`). Prior to this task,
neither method consulted any decision contract or strategy-approval concept.

## Broker submission and exit paths
Unchanged since Task 76S: `talonx_piv.lifecycle.PaperLifecycle.order_intent` is the sole
chokepoint (4 callers: `decision_engine.py::_handle_entry`/`_check_exit`,
`lifecycle_probe.py::run_piv_lifecycle_probe`/`close_piv_lifecycle_probe`). Bulk-flatten paths
(`eod_lifecycle.run_eod_lifecycle`, `PaperLifecycle.activate_kill_switch`/`eod_flatten`,
`lifecycle.paper_cleanup`) remain a separate, exempt surface. Re-confirmed by re-reading
`lifecycle.py` in full this task -- no new caller added, no protected-file dependency.

## Persisted and authoritative broker state
`LifecycleState` (`{state_dir}/lifecycle_state.json`), loaded/saved via `PaperLifecycle._load`/
`_save` -- full-file JSON rewrite, restart-safe by construction (unchanged pattern, reused for
every new ledger this task adds). `reconcile()` is the sole authoritative broker-state-vs-local
comparison point (queries `broker.open_orders()`/`broker.positions()` fresh every call).

## Existing notification adapters
`talonx_piv/telegram.py::sender(token, chat_id) -> Callable[[str], bool]` -- a synchronous,
best-effort HTTP POST returning a bool. Currently invoked ONLY from inside
`EventBus.emit` (best-effort, deduplicated by a same-event key, never raises past `emit`,
never blocks the local JSONL write which happens first). This task adds a SECOND,
independent consumer of the same adapter factory (`NotificationOutbox`), never modifying
`telegram.py` itself.

## Existing event/ledger persistence
`talonx_piv/events.py::EventBus`/`PivEvent` -> `{state_dir}/piv_events.jsonl`, append-only,
37 event types, already durable-before-notify. Left untouched by this task (no new event
types added to `EVENT_TYPES`; new ledgers are separate files, cross-referenced by
`decision_id`/`correlation_id` fields already present on `PivEvent`).

## Existing dashboard/API projections
`talonx_piv/reporting.py::build_session_report` (writes `latest_session_report.json`),
`talonx_piv/telegram_inbound.py::build_piv_info` (feeds the live `/ping` reply). No web
dashboard exists for `talonx_piv` -- `dashboard.py`/`dashboard_web.py`/
`dashboard_web_static/index.html` belong to the unrelated `talonx_dispatch`/`talonx_core`/
`talonx_brain`/`talonx_paper` subsystem (confirmed zero references to `talonx_piv`/
`piv_events`/`PIV` in either file). See `implementation_plan.md` for the resulting minimal
read-only projection design.

## Partial-fill accounting quirk -- exact location
`talonx_piv/lifecycle.py::PaperLifecycle.apply_broker_update`, lines ~302-342 (pre-fix). See
`implementation_plan.md`'s "Partial-fill accounting fix" section and
`partial_fill_before_after.md` for the full before/after.

## Minimum files/interfaces needed (final)
- `talonx_piv/decision_ledger.py` (NEW) -- durable per-decision record.
- `talonx_piv/notification_outbox.py` (NEW) -- durable, retryable, deduplicated alert dispatch.
- `talonx_piv/shadow_ledger.py` (NEW) -- causal hypothetical-fill tracking, reusing
  `talonx_backtest.execution`.
- `talonx_piv/observability.py` (NEW) -- minimal read-only cross-ledger projection.
- `talonx_piv/lifecycle.py` (MODIFIED) -- partial-fill fix, timeout/reconcile hardening.
- `talonx_piv/decision_engine.py` (MODIFIED) -- wires `decide()` + the three new ledgers.
- `talonx_piv/session_runner.py` (MODIFIED) -- advances `ShadowLedger.on_bar`, calls
  `NotificationOutbox.dispatch_pending`, EOD-closes shadow positions.
- `talonx_piv/cli.py` (MODIFIED) -- constructs and wires the three new ledgers.
- `talonx_piv/reporting.py` (MODIFIED) -- new read-only counters, additive only.

No change required to any protected file
(`talonx_quant/{strategy,indicators,consumer,config}.py`) -- confirmed by the same reasoning as
Task 76S: nothing in this task's design reads or writes strategy internals; `decide()` only
ever receives already-published `QuantSignal` fields TalonX's public wire schema already
exposes.
