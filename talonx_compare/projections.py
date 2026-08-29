"""Task 83 §2 -- project raw Original / PIV sources onto ComparisonRecords.

Pure, read-only transformation functions. Each returns
``(records, diagnostics)`` where a diagnostic is a dict describing a
malformed / duplicate / missing / stale / wrong-session condition found
while projecting. None of these functions perform I/O beyond being handed
already-read text/dicts.
"""

from __future__ import annotations

import json
from typing import Any

from .identity import (
    EXEC_EXPERIMENTAL,
    EXEC_NONE,
    EXEC_PIV_PAPER,
    EXEC_PIV_SHADOW,
    EXEC_SIMULATED_PAPER,
    PIPELINE_ORIGINAL,
    PIPELINE_PIV,
    ComparisonRecord,
    make_record,
    trading_date_for,
)

# --- PIV event type -> comparison stage --------------------------------------

_EVENT_STAGE = {
    "STARTUP": "lifecycle", "PREFLIGHT_PASS": "lifecycle", "PREFLIGHT_FAIL": "lifecycle",
    "PAPER_SESSION_STARTED": "lifecycle",
    "MARKET_DATA_READY": "readiness", "DATA_NOT_READY": "readiness",
    "SESSION_READINESS_STATE_RESTORED": "readiness", "SESSION_READINESS_STATE_MISSING": "readiness",
    "SESSION_READINESS_STATE_INVALID": "readiness", "SESSION_READINESS_STATE_STALE": "readiness",
    "STALE_DATA": "freshness", "DATA_RECOVERED": "freshness", "PROVIDER_RECOVERED": "freshness",
    "SIGNAL": "quant",
    "ORDER_INTENT": "lifecycle", "PAPER_ORDER_SUBMITTED": "lifecycle",
    "PAPER_ORDER_ACCEPTED": "lifecycle", "PAPER_ORDER_REJECTED": "lifecycle",
    "PAPER_ORDER_CANCELLED": "lifecycle", "PARTIAL_FILL": "lifecycle", "FILLED": "lifecycle",
    "POSITION_OPENED": "lifecycle", "STOP_TRIGGERED": "lifecycle", "EXIT_TRIGGERED": "lifecycle",
    "EXIT_REQUESTED": "lifecycle", "EXIT_FILLED": "lifecycle", "POSITION_CLOSED": "lifecycle",
    "EOD_FLATTEN": "eod", "SESSION_SUMMARY": "eod", "EOD_SUMMARY": "eod",
    "EOD_STARTED": "eod", "EOD_CANCEL_REQUESTED": "eod", "EOD_FLATTEN_REQUESTED": "eod",
    "EOD_RECONCILIATION_STARTED": "reconciliation", "EOD_RECONCILIATION_PASSED": "reconciliation",
    "EOD_RECONCILIATION_FAILED": "reconciliation", "SESSION_COMPLETED": "eod",
    "BROKER_ERROR": "lifecycle", "KILL_SWITCH": "lifecycle",
    "RUNTIME_PARITY_PASS": "lifecycle", "RUNTIME_PARITY_FAIL": "lifecycle",
    "PREMARKET_WATCH": "readiness", "PREMARKET_WATCH_CLEARED": "readiness",
    "STATUS_HEARTBEAT": "lifecycle", "MARKET_DATA": "market",
}


def _diag(kind: str, source: str, detail: str, **extra: Any) -> dict[str, Any]:
    d = {"kind": kind, "source": source, "detail": detail}
    d.update(extra)
    return d


# --- PIV: piv_events.jsonl -------------------------------------------------

def project_piv_events(
    raw_text: str, *, expected_session_id: str | None, expected_trading_date: str | None,
) -> tuple[list[ComparisonRecord], list[dict[str, Any]]]:
    records: list[ComparisonRecord] = []
    diags: list[dict[str, Any]] = []
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    scopes_seen: set[str] = set()
    for i, ln in enumerate(lines):
        try:
            row = json.loads(ln)
        except json.JSONDecodeError as exc:
            diags.append(_diag("MALFORMED", "piv_events.jsonl", f"line {i + 1}: {exc}"))
            continue
        if not isinstance(row, dict) or "event" not in row or "timestamp" not in row:
            diags.append(_diag("MALFORMED", "piv_events.jsonl", f"line {i + 1}: missing event/timestamp"))
            continue
        sess = row.get("session_id")
        if sess:
            scopes_seen.add(sess)
        if expected_session_id is not None and sess is not None and sess != expected_session_id:
            diags.append(_diag(
                "WRONG_SESSION", "piv_events.jsonl",
                f"line {i + 1}: session_id {sess!r} != manifest {expected_session_id!r}",
                event=row.get("event"),
            ))
            continue
        evt = row["event"]
        stage = _EVENT_STAGE.get(evt, "lifecycle")
        symbol = row.get("symbol") or ""
        td = row.get("trading_date_et") or trading_date_for(row["timestamp"])
        if expected_trading_date is not None and td != expected_trading_date:
            # not an error -- the append-only file legitimately spans dates;
            # we simply don't project other dates into this day's evidence.
            continue
        exec_class = EXEC_NONE
        if stage in ("lifecycle", "eod", "reconciliation") and evt not in ("STARTUP", "KILL_SWITCH"):
            exec_class = EXEC_PIV_PAPER
        if row.get("source") == "PIV_LIFECYCLE_PROBE":
            exec_class = EXEC_NONE
        records.append(make_record(
            pipeline=PIPELINE_PIV, stage=stage, symbol=symbol,
            event_time=row["timestamp"], session_id=sess, trading_date=td,
            source_bar_time=row.get("bar_time") or row.get("source_bar_time"),
            decision_id=row.get("correlation_id") or row.get("signal_id") or row.get("order_intent_id"),
            decision_outcome=row.get("status") or evt,
            reason_codes=[row["reason"]] if row.get("reason") else (),
            execution_class=exec_class,
            source="piv_events.jsonl",
            fingerprint_payload={"event": evt, "status": row.get("status"),
                                "reason": row.get("reason"), "quantity": row.get("quantity")},
        ))
    if expected_session_id is not None and scopes_seen and expected_session_id not in scopes_seen:
        diags.append(_diag(
            "WRONG_SESSION", "piv_events.jsonl",
            f"no events for manifest session {expected_session_id!r}; file has {sorted(scopes_seen)}",
        ))
    return records, diags


# --- PIV: session_readiness_state.json -----------------------------------

def project_piv_readiness(
    data: Any, *, session_id: str | None, expected_trading_date: str | None,
) -> tuple[list[ComparisonRecord], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        return [], [_diag("MALFORMED", "session_readiness_state.json", "not a JSON object")]
    td = data.get("session_date") or expected_trading_date
    if td is None:
        return [], [_diag("MALFORMED", "session_readiness_state.json", "no session_date")]
    if expected_trading_date is not None and td != expected_trading_date:
        return [], [_diag(
            "WRONG_SESSION", "session_readiness_state.json",
            f"session_date {td} != {expected_trading_date}",
        )]
    records: list[ComparisonRecord] = []
    for symbol, tel in (data.get("finalized") or {}).items():
        status = tel.get("status") if isinstance(tel, dict) else None
        records.append(make_record(
            pipeline=PIPELINE_PIV, stage="readiness", symbol=symbol,
            event_time=(tel.get("decided_at") if isinstance(tel, dict) else None),
            trading_date=td, session_id=session_id,
            decision_outcome=status,
            reason_codes=[tel.get("reason")] if isinstance(tel, dict) and tel.get("reason") else (),
            source="session_readiness_state.json",
            fingerprint_payload={"status": status},
        ))
    return records, []


# --- PIV: decision_ledger.json ------------------------------------------

def _decision_exec_class(rec: dict) -> str:
    if rec.get("recommendation") == "EXPERIMENTAL_BUY" or rec.get("evidence_category") == "test_probe":
        return EXEC_EXPERIMENTAL if rec.get("recommendation") == "EXPERIMENTAL_BUY" else EXEC_NONE
    return EXEC_NONE


def project_piv_decisions(
    data: Any, *, session_id: str | None, expected_trading_date: str | None,
) -> tuple[list[ComparisonRecord], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        return [], [_diag("MALFORMED", "decision_ledger.json", "not a JSON object")]
    records, diags = [], []
    for did, rec in data.items():
        if not isinstance(rec, dict):
            diags.append(_diag("MALFORMED", "decision_ledger.json", f"{did}: not an object"))
            continue
        if session_id is not None and rec.get("session_id") not in (None, session_id):
            diags.append(_diag(
                "WRONG_SESSION", "decision_ledger.json",
                f"{did}: session_id {rec.get('session_id')!r} != {session_id!r}",
            ))
            continue
        td = rec.get("trading_date_et") or expected_trading_date
        if expected_trading_date is not None and td != expected_trading_date:
            continue
        records.append(make_record(
            pipeline=PIPELINE_PIV, stage="decision", symbol=rec.get("symbol") or "",
            event_time=rec.get("timestamp"), trading_date=td, session_id=rec.get("session_id") or session_id,
            source_bar_time=rec.get("source_bar_time"),
            decision_id=did, decision_outcome=rec.get("recommendation"),
            reason_codes=rec.get("reason_codes") or (),
            execution_class=_decision_exec_class(rec),
            source="decision_ledger.json",
            fingerprint_payload={
                "recommendation": rec.get("recommendation"),
                "market_view": rec.get("market_view"),
                "decision_execution_status": rec.get("decision_execution_status"),
                "data_readiness": rec.get("data_readiness"),
            },
        ))
    return records, diags


# --- PIV: shadow_ledger.json ------------------------------------------

def project_piv_shadow(
    data: Any, *, session_id: str | None, decision_dates: dict[str, str],
    expected_trading_date: str | None,
) -> tuple[list[ComparisonRecord], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        return [], [_diag("MALFORMED", "shadow_ledger.json", "not a JSON object")]
    records, diags = [], []
    for sid, rec in data.items():
        if not isinstance(rec, dict):
            diags.append(_diag("MALFORMED", "shadow_ledger.json", f"{sid}: not an object"))
            continue
        did = rec.get("decision_id")
        td = decision_dates.get(did) or expected_trading_date
        if td is None:
            continue
        if expected_trading_date is not None and td != expected_trading_date:
            continue
        records.append(make_record(
            pipeline=PIPELINE_PIV, stage="shadow", symbol=rec.get("symbol") or "",
            event_time=rec.get("filled_at") or rec.get("created_at"),
            trading_date=td, session_id=session_id,
            decision_id=did, decision_outcome=rec.get("status"),
            execution_class=EXEC_EXPERIMENTAL if rec.get("experimental") else EXEC_PIV_SHADOW,
            source="shadow_ledger.json",
            fingerprint_payload={"status": rec.get("status"),
                                 "gross_r": rec.get("gross_r"), "net_r": rec.get("net_r")},
        ))
    return records, diags


# --- PIV: lifecycle_state.json --------------------------------------

def project_piv_lifecycle(
    data: Any, *, session_id: str | None, expected_trading_date: str | None,
) -> tuple[list[ComparisonRecord], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        return [], [_diag("MALFORMED", "lifecycle_state.json", "not a JSON object")]
    records: list[ComparisonRecord] = []
    for kind, container in (("order", data.get("orders", {})), ("position", data.get("positions", {}))):
        for key, rec in (container or {}).items():
            if not isinstance(rec, dict):
                continue
            records.append(make_record(
                pipeline=PIPELINE_PIV, stage="lifecycle", symbol=rec.get("symbol") or "",
                event_time=rec.get("updated_at") or rec.get("created_at"),
                trading_date=expected_trading_date, session_id=session_id,
                decision_id=rec.get("decision_id") or rec.get("intent_id"),
                decision_outcome=f"{kind}:{rec.get('status')}",
                execution_class=EXEC_PIV_PAPER,
                source="lifecycle_state.json",
                fingerprint_payload={"kind": kind, "status": rec.get("status"),
                                     "quantity": rec.get("quantity") or rec.get("qty")},
            )) if expected_trading_date else None
    flags = data.get("reconciliation_flags") or {}
    if flags:
        records.append(make_record(
            pipeline=PIPELINE_PIV, stage="reconciliation", symbol="",
            event_time=flags.get("updated_at"), trading_date=expected_trading_date,
            session_id=session_id, decision_outcome="ENTRY_ADMISSION_BLOCKED"
            if flags.get("entry_admission_blocked") else "CLEAR",
            reason_codes=flags.get("reasons") or (),
            source="lifecycle_state.json",
            fingerprint_payload={"entry_admission_blocked": bool(flags.get("entry_admission_blocked"))},
        )) if expected_trading_date else None
    return [r for r in records if r is not None], []


# --- PIV: freshness_report.json -----------------------------------

def project_piv_freshness(
    data: Any, *, session_id: str | None, expected_trading_date: str | None,
) -> tuple[list[ComparisonRecord], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        return [], [_diag("MALFORMED", "freshness_report.json", "not a JSON object")]
    if not expected_trading_date:
        return [], []
    records: list[ComparisonRecord] = []
    provider_state = data.get("provider_state")
    records.append(make_record(
        pipeline=PIPELINE_PIV, stage="freshness", symbol="",
        event_time=None, trading_date=expected_trading_date, session_id=session_id,
        decision_outcome=f"provider:{provider_state}",
        source="freshness_report.json",
        fingerprint_payload={"provider_state": provider_state},
    ))
    for symbol, state in (data.get("symbols") or {}).items():
        records.append(make_record(
            pipeline=PIPELINE_PIV, stage="freshness", symbol=symbol,
            event_time=None, trading_date=expected_trading_date, session_id=session_id,
            decision_outcome=str(state),
            source="freshness_report.json",
            fingerprint_payload={"state": str(state)},
        ))
    return records, []


# --- PIV: latest_reconciliation.json / eod_state.json ------------

def project_piv_reconciliation(
    data: Any, *, session_id: str | None, expected_trading_date: str | None,
) -> tuple[list[ComparisonRecord], list[dict[str, Any]]]:
    if not isinstance(data, dict) or not expected_trading_date:
        return [], []
    return [make_record(
        pipeline=PIPELINE_PIV, stage="reconciliation", symbol="",
        event_time=data.get("reconciled_at"), trading_date=expected_trading_date,
        session_id=session_id,
        decision_outcome="COMPLETE_CONSISTENT" if (data.get("complete") and data.get("consistent"))
        else "INCOMPLETE_OR_INCONSISTENT",
        reason_codes=(data.get("contradictory_broker_orders") or [])
        + (data.get("orders_missing_from_broker_list") or []),
        execution_class=EXEC_PIV_PAPER,
        source="latest_reconciliation.json",
        fingerprint_payload={"complete": bool(data.get("complete")),
                             "consistent": bool(data.get("consistent"))},
    )], []


def project_piv_eod(
    data: Any, *, session_id: str | None, expected_trading_date: str | None,
) -> tuple[list[ComparisonRecord], list[dict[str, Any]]]:
    if not isinstance(data, dict) or not expected_trading_date:
        return [], []
    if data.get("trading_date_et") not in (None, expected_trading_date):
        return [], [_diag("WRONG_SESSION", "eod_state.json",
                          f"trading_date_et {data.get('trading_date_et')} != {expected_trading_date}")]
    return [make_record(
        pipeline=PIPELINE_PIV, stage="eod", symbol="",
        event_time=data.get("completed_at") or data.get("started_at"),
        trading_date=expected_trading_date, session_id=session_id,
        decision_outcome=data.get("status"),
        execution_class=EXEC_PIV_PAPER,
        source="eod_state.json",
        fingerprint_payload={"status": data.get("status")},
    )], []


# --- Original: Redis metrics keys --------------------------------

_ORIGINAL_STAGE_FOR_MODULE = {
    "ingest": "warmup", "quant": "quant", "brain": "brain",
    "core": "core", "dispatch": "dispatch",
}


def project_original_metrics(
    metrics: dict[str, dict[str, int]], *, trading_date: str, run_scope: str | None,
    as_of: str | None,
) -> tuple[list[ComparisonRecord], list[dict[str, Any]]]:
    """metrics == {module: {counter: value}} as read from
    ``metrics:{date}:{module}:{counter}`` keys on Redis DB 0. Each counter
    becomes an explicit AGGREGATE record (§3.5) -- compared as a value,
    never collapsed with individual events."""
    from .identity import KIND_AGGREGATE

    records: list[ComparisonRecord] = []
    for module, counters in sorted(metrics.items()):
        stage = _ORIGINAL_STAGE_FOR_MODULE.get(module, module)
        for counter, value in sorted(counters.items()):
            is_telegram = module == "dispatch" and "telegram" in counter
            agg_name = f"{module}:{counter}"
            records.append(make_record(
                pipeline=PIPELINE_ORIGINAL,
                stage="telegram" if is_telegram else stage,
                symbol="",
                event_time=as_of, trading_date=trading_date, session_id=None,
                run_scope=run_scope,
                record_kind=KIND_AGGREGATE, aggregate_name=agg_name, aggregate_value=float(value),
                decision_outcome=counter,
                source=f"redis:metrics:{module}",
                # value IS in the fingerprint so a changed counter appends a
                # new versioned line; alignment_key (agg:<name>) is stable,
                # so alignment keeps only the LATEST value per counter.
                fingerprint_payload={"aggregate_name": agg_name, "aggregate_value": float(value)},
            ))
    return records, []


# --- Original: live pub/sub messages ---------------------------

_CHANNEL_STAGE = {
    "talonx:market:stream": ("market", EXEC_NONE),
    "talonx:signals:quant": ("quant", EXEC_NONE),
    "talonx:reports:brain": ("brain", EXEC_NONE),
    "talonx:alerts:dispatch": ("core", EXEC_NONE),
    "talonx:paper:trades": ("lifecycle", EXEC_SIMULATED_PAPER),
}


_PIV_CHANNEL_STAGE = {
    "talonx:piv:market:stream": ("market", EXEC_NONE),
    "talonx:piv:signals:quant": ("quant", EXEC_NONE),
    "talonx:piv:quant:rejected": ("quant", EXEC_NONE),
    "talonx:piv:news:events": ("core", EXEC_NONE),
    "talonx:piv:paper:trades": ("lifecycle", EXEC_NONE),
}


def project_original_messages(
    messages: list[dict[str, Any]], *, trading_date: str | None, run_scope: str | None,
    pipeline: str = PIPELINE_ORIGINAL,
) -> tuple[list[ComparisonRecord], list[dict[str, Any]]]:
    """messages == [{"channel": str, "data": str-json}] captured live off
    the Original (or, with pipeline=PIV, the PIV) channels. Read-only
    projection; the collector never re-publishes these."""
    records, diags = [], []
    channel_map = _PIV_CHANNEL_STAGE if pipeline == PIPELINE_PIV else _CHANNEL_STAGE
    for msg in messages:
        channel = msg.get("channel")
        stage_exec = channel_map.get(channel) or _CHANNEL_STAGE.get(channel)
        if stage_exec is None:
            continue
        stage, exec_class = stage_exec
        raw = msg.get("data")
        try:
            payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except json.JSONDecodeError as exc:
            diags.append(_diag("MALFORMED", f"redis:{channel}", str(exc)))
            continue
        if not isinstance(payload, dict):
            diags.append(_diag("MALFORMED", f"redis:{channel}", "payload not an object"))
            continue
        symbol = payload.get("ticker") or payload.get("symbol") or ""
        ts = payload.get("timestamp") or payload.get("emitted_at") or payload.get("ts")
        td = trading_date
        if td is None and ts:
            try:
                td = trading_date_for(ts)
            except ValueError:
                td = None
        if td is None:
            diags.append(_diag("MALFORMED", f"redis:{channel}", "no timestamp/trading_date"))
            continue
        records.append(make_record(
            pipeline=pipeline, stage=stage, symbol=symbol,
            event_time=ts, trading_date=td,
            session_id=(run_scope if pipeline == PIPELINE_PIV else None),
            run_scope=run_scope,
            source_bar_time=payload.get("bar_time") or payload.get("source_bar_time"),
            decision_id=payload.get("alert_id") or payload.get("signal_id"),
            decision_outcome=payload.get("action") or payload.get("signal_type")
            or payload.get("order_type") or payload.get("verdict"),
            reason_codes=payload.get("reason_codes") or (),
            execution_class=exec_class,
            source=f"redis:{channel}",
            fingerprint_payload={"action": payload.get("action"),
                                 "signal_type": payload.get("signal_type"),
                                 "order_type": payload.get("order_type")},
        ))
    return records, diags
