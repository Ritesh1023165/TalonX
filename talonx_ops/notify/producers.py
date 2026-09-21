"""
talonx_ops.notify.producers -- OPERATIONS event producers (RI-2, RI2-E).
====================================================================
Deliberately a POLL-AND-DIFF scanner, not an inline hook inside
``V2Store``'s own mutation methods (``mark_exit_unresolved``,
``record_account_block``) -- Package 1/2 already made those methods'
atomicity/idempotency the load-bearing safety guarantee (account blocks
stop new exposure; EXIT_UNRESOLVED retains capacity); RI-2 does not
touch them. Scanning ``v2_store.unresolved_positions()``/
``active_account_blocks()`` and enqueueing an OPERATIONS notification
for anything not yet enqueued (idempotent on ``event_id``) gets the
same observability with ZERO risk to that already-tested code, and is
naturally restart-safe: a restart just re-scans the same (unchanged)
state and finds nothing new to enqueue.

Each producer below is the ONE authoritative producer for its event
type (RI2-O) -- there is no other code path that enqueues these into
``ops_notification_outbox``.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from talonx_ops.notify import OPERATIONS, RESEARCH

_PRODUCER = "talonx_ops.notify.producers"


def _event_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def scan_v2_operational_events(v2_store, ops_store) -> dict[str, int]:
    """Enqueues an OPERATIONS event for every currently-unresolved V2
    position and every currently-active V2 account block not already
    enqueued. Safe to call every tick -- idempotent, cheap (read-only on
    v2_store, additive-only on ops_store)."""
    counts = {"exit_unresolved": 0, "account_block": 0}

    for pos in v2_store.unresolved_positions():
        pid = pos["episode_id"]
        eid = _event_id("EXIT_UNRESOLVED", str(pos["position_id"]))
        payload = (
            f"⚠️ *EXIT_UNRESOLVED* — *{pos['symbol']}*\n"
            "————————————\n"
            f"Position {pos['position_id']} (episode {pid}) could not be closed at its "
            f"target exit session ({pos.get('target_exit_session')}) or any fall-forward "
            "session -- no valid exit price observed. Capacity/cost remain retained "
            "(Package 1/2 containment policy); no new account exposure is admitted until "
            "an operator resolves and clears this. Paper only."
        )
        new = ops_store.enqueue(
            event_id=eid, destination=OPERATIONS, event_type="EXIT_UNRESOLVED",
            producer=_PRODUCER, dedup_key=f"exit_unresolved:{pos['position_id']}",
            payload_text=payload,
            provenance={"position_id": pos["position_id"], "episode_id": pid,
                       "symbol": pos["symbol"], "target_exit_session": pos.get("target_exit_session")},
        )
        if new:
            counts["exit_unresolved"] += 1

    for block in v2_store.active_account_blocks():
        bid = block.get("block_id") or block.get("id")
        eid = _event_id("ACCOUNT_BLOCK", str(bid))
        payload = (
            f"🚫 *ACCOUNT BLOCKED* — {block.get('reason_type')}\n"
            "————————————\n"
            f"Account `{block.get('account_id')}` is blocked from new admissions "
            f"(block {bid}, reference {block.get('reference')}). "
            f"Detail: {block.get('detail') or 'n/a'}. "
            "Existing recovery/exit obligations continue unaffected; this only stops "
            "NEW exposure until an operator reviews and clears the block."
        )
        new = ops_store.enqueue(
            event_id=eid, destination=OPERATIONS, event_type="ACCOUNT_BLOCK",
            producer=_PRODUCER, dedup_key=f"account_block:{bid}",
            payload_text=payload,
            provenance={"block_id": bid, "account_id": block.get("account_id"),
                       "reason_type": block.get("reason_type"), "reference": block.get("reference")},
        )
        if new:
            counts["account_block"] += 1

    return counts


def enqueue_reconciliation_failure(ops_store, *, campaign_id: str, findings: list[str],
                                   reference: str = "") -> bool:
    """RI2-E: a V2 reconciliation failure (LEDGER_MISMATCH / CASH_DEFICIT
    or any other `_v2_reconcile()` invariant FAIL) is an operations
    incident. The ONE authoritative producer for this event type --
    called from `talonx_ops.prospective.close` right where the failing
    asserts are already computed (never re-derived here)."""
    now = datetime.now(timezone.utc)
    dedup_key = f"reconciliation_failure:{campaign_id}:{now.date().isoformat()}:{reference}"
    eid = _event_id("RECONCILIATION_FAILURE", dedup_key)
    payload = (
        f"🚨 *RECONCILIATION FAILURE* — campaign `{campaign_id}`\n"
        "————————————\n"
        + "\n".join(f"- {f}" for f in findings[:10])
        + ("\n(+ more, see dashboard/logs)" if len(findings) > 10 else "")
    )
    return ops_store.enqueue(
        event_id=eid, destination=OPERATIONS, event_type="RECONCILIATION_FAILURE",
        producer="talonx_ops.prospective.close", dedup_key=dedup_key, payload_text=payload,
        provenance={"campaign_id": campaign_id, "findings": findings, "reference": reference},
    )


def enqueue_lifecycle_event(ops_store, *, event_type: str, campaign_id: str, detail: str = "") -> bool:
    """RI2-M: startup/shutdown. ``event_type`` is "STARTUP" or
    "SHUTDOWN". Called from `talonx_ops.prospective.__main__`'s own
    start/close commands -- the ONE authoritative producer."""
    assert event_type in ("STARTUP", "SHUTDOWN")
    now = datetime.now(timezone.utc)
    dedup_key = f"{event_type.lower()}:{campaign_id}:{now.isoformat()}"
    eid = _event_id(event_type, dedup_key)
    payload = f"ℹ️ *{event_type}* — campaign `{campaign_id}`\n{detail or 'no additional detail'}"
    return ops_store.enqueue(
        event_id=eid, destination=OPERATIONS, event_type=event_type,
        producer="talonx_ops.prospective.__main__", dedup_key=dedup_key, payload_text=payload,
        provenance={"campaign_id": campaign_id, "detail": detail},
        deliver_by_utc=(now + timedelta(hours=2)).isoformat(),
    )


def enqueue_research_event(ops_store, *, event_type: str, summary: str, source: str,
                           reference: str = "") -> bool:
    """RI2-F: intraday Research Lab output (e.g. a Package-5 backtest
    evaluation, a future live-shadow research report) is ALWAYS
    recorded/audited here -- classification is destination=RESEARCH
    regardless of whether RESEARCH is currently enabled (RI2-C/F: OFF
    by default is a DELIVERY gate, not a recording gate; the durable
    audit row exists either way -- see `worker.drain`'s own
    ``skipped_disabled`` behavior). Never routes to TRADE_EVENT or
    OPERATIONS merely because RESEARCH is disabled -- this function
    has no fallback destination at all, by construction (destination
    is hardcoded RESEARCH, not a parameter)."""
    now = datetime.now(timezone.utc)
    dedup_key = f"research:{source}:{event_type}:{reference}:{now.date().isoformat()}"
    eid = _event_id("RESEARCH", dedup_key)
    payload = f"🔬 *RESEARCH* — {event_type} ({source})\n————————————\n{summary}"
    return ops_store.enqueue(
        event_id=eid, destination=RESEARCH, event_type=event_type,
        producer=source, dedup_key=dedup_key, payload_text=payload,
        provenance={"source": source, "reference": reference, "summary": summary},
    )


def enqueue_delivery_subsystem_failure(ops_store, *, destination: str, reason: str,
                                       producer: str) -> bool:
    """RI2-E: 'notification-delivery failure itself' is an operations
    condition. Deliberately enqueued into OPERATIONS regardless of which
    destination failed (including a failure draining OPERATIONS itself)
    -- to avoid an infinite self-referential loop, the caller MUST use a
    stable dedup_key (time-bucketed) so repeated failures collapse into
    one notification per bucket rather than flooding, per RI2-E's own
    "avoid flooding" instruction."""
    now = datetime.now(timezone.utc)
    bucket = now.strftime("%Y-%m-%dT%H")  # one notification per destination per hour
    dedup_key = f"delivery_failure:{destination}:{bucket}"
    eid = _event_id("DELIVERY_FAILURE", dedup_key)
    payload = (f"🚨 *DELIVERY SUBSYSTEM FAILURE* — destination `{destination}`\n"
              f"————————————\n{reason}")
    return ops_store.enqueue(
        event_id=eid, destination=OPERATIONS, event_type="DELIVERY_FAILURE",
        producer=producer, dedup_key=dedup_key, payload_text=payload,
        provenance={"failed_destination": destination, "reason": reason},
    )


def enqueue_degraded_health(ops_store, *, component: str, condition: str, now=None) -> bool:
    """One incident per component/condition/hour; raw errors never enter payloads."""
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    key = f"health:{component}:{condition}:{now:%Y-%m-%dT%H}"
    return ops_store.enqueue(
        event_id=_event_id(key), destination=OPERATIONS, event_type="DEGRADED_HEALTH",
        producer=component, dedup_key=key,
        payload_text=f"OPERATIONS: {component}: {condition}. Inspect dashboard and local evidence.",
        provenance={"component": component, "condition": condition},
        deliver_by_utc=(now + timedelta(hours=1)).isoformat())


def record_intelligence_health(*, degraded: bool, now=None):
    """Runtime-only opt-in; shared independently enabled Operations outbox."""
    import os
    if not degraded or os.environ.get("TALONX_NOTIFY_OPERATIONS_ENABLED", "0") != "1":
        return False
    from talonx_ops.notify.outbox import NotifyStore
    return enqueue_degraded_health(
        NotifyStore(os.environ.get("TALONX_NOTIFY_DB_PATH", "notifications.db")),
        component="intelligence", condition="PROCESSING_OR_INPUT_DEGRADED", now=now)
