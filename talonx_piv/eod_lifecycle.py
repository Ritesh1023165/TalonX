"""Task 72O Stage 1 -- automatic, idempotent EOD reconciliation lifecycle,
linked to the ORIGINAL live trading session identity.

Root problem this fixes: on 2026-08-26 the live loop stopped normally at
15:50 ET, but mandatory broker reconciliation was not invoked until a
manual `python -m talonx_piv.cli eod` call at 16:57 ET -- which built its
own fresh PivConfig/session identity (see cli.py's `runtime()`), so the
EOD_FLATTEN event it emitted carried a DIFFERENT session_id than the live
session it was actually reconciling.

This module is the single source of truth for the EOD event sequence and
its idempotency contract; both SessionRunner (a guaranteed end-of-run
path -- scheduled completion, controlled shutdown, or a safely-caught
unhandled exception) and the manual `cli.py eod` command call the same
`run_eod_lifecycle()`, always stamped with the ORIGINAL live session's
`live_session_id` (read from session_identity.json when not already known
in-process) plus a freshly-generated, distinct `reconciliation_run_id` --
never a second trading session.

Ordered events: EOD_STARTED -> EOD_CANCEL_REQUESTED -> EOD_FLATTEN_REQUESTED
-> EOD_RECONCILIATION_STARTED -> (EOD_RECONCILIATION_PASSED |
EOD_RECONCILIATION_FAILED) -> SESSION_COMPLETED (only after PASSED).
SESSION_COMPLETED is never emitted on FAILED/INCONCLUSIVE.

Idempotent: a persisted `eod_state.json`, keyed by (live_session_id,
trading_date_et), records whether cancel/close was already requested for
THIS live session -- a repeat call (e.g. the manual `eod` recovery path
after an automatic run already happened) skips re-issuing
cancel_all_orders/close_all_positions, but always re-runs reconcile() (a
read-only broker query, safe to repeat) so a completed reconciliation can
always be safely re-read. A persisted state for a DIFFERENT ET trading
date is never reused -- treated exactly as if no prior state existed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from .events import EventBus, PivEvent
from .lifecycle import PaperLifecycle, stable_id

STATUS_PENDING = "PENDING"
STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
STATUS_INCONCLUSIVE = "INCONCLUSIVE"


def _eod_state_path(config: Any):
    return config.state_dir / "eod_state.json"


def _load_prior_state(path, trading_date_et: str) -> dict | None:
    """None if missing, corrupt, OR from a different ET trading date --
    all three are treated identically (fail-closed: never reuse a
    terminal state that does not unambiguously belong to today)."""
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or state.get("trading_date_et") != trading_date_et:
        return None
    return state


def _save_state(path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    import os
    os.replace(tmp, path)


def run_eod_lifecycle(
    config: Any, events: EventBus, lifecycle: PaperLifecycle, *,
    live_session_id: str, trading_date_et: str, runtime_sha: str, config_hash: str,
    trigger_reason: str,
) -> dict[str, Any]:
    """Never raises for a broker/reconciliation failure -- every failure
    mode resolves to a returned dict with `status` in {PASSED, FAILED,
    INCONCLUSIVE} and `exit_code` (0 only for PASSED). Never emits
    SESSION_COMPLETED unless status == PASSED."""
    path = _eod_state_path(config)
    prior = _load_prior_state(path, trading_date_et)
    same_session_cancel_close_done = bool(
        prior is not None and prior.get("session_id") == live_session_id
        and prior.get("cancel_close_requested") is True
    )

    reconciliation_run_id = stable_id("eodrun", live_session_id, trigger_reason, datetime.now(timezone.utc).isoformat())
    identity = dict(
        session_id=live_session_id, trading_date_et=trading_date_et,
        reconciliation_run_id=reconciliation_run_id, runtime_sha=runtime_sha, config_hash=config_hash,
    )

    events.emit(PivEvent.build(
        "EOD_STARTED", reason=trigger_reason, status="EOD_LIFECYCLE_TRIGGERED",
        session_id=live_session_id, trading_date_et=trading_date_et, correlation_id=reconciliation_run_id,
    ))

    if same_session_cancel_close_done:
        events.emit(PivEvent.build(
            "EOD_CANCEL_REQUESTED", status="ALREADY_REQUESTED_SKIPPED_IDEMPOTENT_RETRY",
            session_id=live_session_id, trading_date_et=trading_date_et, correlation_id=reconciliation_run_id,
        ))
    else:
        events.emit(PivEvent.build(
            "EOD_CANCEL_REQUESTED", session_id=live_session_id, trading_date_et=trading_date_et,
            correlation_id=reconciliation_run_id,
        ))
        cancel_close_error = None
        try:
            lifecycle.broker.cancel_all_orders()
            events.emit(PivEvent.build(
                "EOD_FLATTEN_REQUESTED", session_id=live_session_id, trading_date_et=trading_date_et,
                correlation_id=reconciliation_run_id,
            ))
            lifecycle.broker.close_all_positions()
        except Exception as exc:  # noqa: BLE001 -- a cancel/close failure must resolve to INCONCLUSIVE
            # (never fabricated as PASSED), and must NOT persist cancel_close_requested=True (so a
            # retry safely re-attempts both -- Alpaca's own cancel/close endpoints are themselves
            # safe no-ops when there is nothing left to cancel/close).
            cancel_close_error = f"{type(exc).__name__}: {exc}"

        if cancel_close_error is not None:
            events.emit(PivEvent.build(
                "EOD_RECONCILIATION_FAILED", status=STATUS_INCONCLUSIVE, reason=cancel_close_error,
                session_id=live_session_id, trading_date_et=trading_date_et, correlation_id=reconciliation_run_id,
            ))
            _save_state(path, {**identity, "status": STATUS_INCONCLUSIVE, "cancel_close_requested": False, "reconciliation_error": cancel_close_error})
            return {**identity, "status": STATUS_INCONCLUSIVE, "reconciliation": None, "exit_code": 2}

        for position in lifecycle.state.positions.values():
            position["status"] = "CLOSED"
        lifecycle.state.session_enabled = False
        lifecycle._save()
        # Persisted BEFORE reconciliation so a crash mid-reconciliation,
        # on retry, never re-issues cancel/close for this live session.
        _save_state(path, {**identity, "status": STATUS_PENDING, "cancel_close_requested": True})

    events.emit(PivEvent.build(
        "EOD_RECONCILIATION_STARTED", session_id=live_session_id, trading_date_et=trading_date_et,
        correlation_id=reconciliation_run_id,
    ))
    try:
        reconciliation = lifecycle.reconcile()
        reconciliation_error = None
    except Exception as exc:  # noqa: BLE001 -- a broker-read failure during reconciliation must resolve to
        # INCONCLUSIVE (never silently treated as PASSED), not propagate and skip persisting a terminal state.
        reconciliation = None
        reconciliation_error = f"{type(exc).__name__}: {exc}"

    if reconciliation is None:
        status = STATUS_INCONCLUSIVE
    elif reconciliation.get("incomplete_read") or reconciliation.get("complete") is False:
        # Task 81 §2/§4: a reconcile pass that could not fully read broker
        # state (a failed/malformed response, or an unresolved/uncertain
        # submission) is INCONCLUSIVE -- distinct from FAILED, which means
        # the broker WAS read and definitively did not match. Never PASSED.
        status = STATUS_INCONCLUSIVE
        if reconciliation_error is None and reconciliation.get("read_failures"):
            reconciliation_error = "INCOMPLETE_RECONCILIATION: " + ", ".join(reconciliation["read_failures"])
    elif reconciliation["matched"] and reconciliation["broker_open_orders"] == 0 and reconciliation["broker_positions"] == 0:
        status = STATUS_PASSED
    else:
        status = STATUS_FAILED

    result_event = "EOD_RECONCILIATION_PASSED" if status == STATUS_PASSED else "EOD_RECONCILIATION_FAILED"
    events.emit(PivEvent.build(
        result_event, status=status, reason=reconciliation_error,
        session_id=live_session_id, trading_date_et=trading_date_et, correlation_id=reconciliation_run_id,
    ))

    _save_state(path, {
        **identity, "status": status, "cancel_close_requested": True,
        "reconciliation": reconciliation, "reconciliation_error": reconciliation_error,
    })

    if status == STATUS_PASSED:
        events.emit(PivEvent.build(
            "SESSION_COMPLETED", session_id=live_session_id, trading_date_et=trading_date_et,
            correlation_id=reconciliation_run_id, status="BROKER_STATE_VERIFIED_FLAT_AND_MATCHED",
        ))

    return {**identity, "status": status, "reconciliation": reconciliation, "exit_code": 0 if status == STATUS_PASSED else 2}
