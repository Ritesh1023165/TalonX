"""Task 77I Stage 4 -- minimal, read-only, cross-ledger projection.

No existing PIV-native dashboard/API surface exists beyond
`reporting.py::build_session_report` and `telegram_inbound.py::build_piv_info`
(neither of which knows about the three new ledgers this task adds), and the
repository's actual web dashboard (`dashboard.py`/`dashboard_web.py`) belongs
to an entirely different, unrelated subsystem with zero existing awareness of
`talonx_piv` (confirmed by grep -- see implementation_plan.md). Per this
task's own fallback instruction ("If no suitable existing surface exists,
provide the minimal read-only projection"), this module aggregates the
events log, decision ledger, notification outbox, shadow ledger, and
lifecycle state into ONE read-only dict for a future UI to consume. It
issues zero writes, zero order-placement/mutation of any kind, and does not
redesign any existing report.

Every count below has an explicitly documented scope, and reconciles back to
its own ledger file (see dashboard_counter_reconciliation.json for the
verification of this). Historical probe/other-session records are excluded
by construction: notification and shadow records are scoped to the target
session by cross-referencing their `decision_id` against the decision
ledger's OWN session-scoped records -- the only place session_id is
directly recorded for those two ledgers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .reporting import build_session_report


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def build_integrated_projection(
    state_dir: Path, *, session_id: str | None = None, trading_date_et: str | None = None,
) -> dict[str, Any]:
    """Read-only. Reads (never writes) piv_events.jsonl, decision_ledger.json,
    notification_outbox.json, shadow_ledger.json, lifecycle_state.json,
    session_identity.json, freshness_report.json, latest_reconciliation.json
    -- all optional (a fresh/never-started session simply yields empty/zero
    sections, never an error)."""
    identity = _read_json(state_dir / "session_identity.json", {})
    session_id = session_id or identity.get("session_id")
    trading_date_et = trading_date_et or identity.get("trading_date_et")

    decisions = _read_json(state_dir / "decision_ledger.json", {})
    if session_id is not None:
        decisions = {k: v for k, v in decisions.items() if v.get("session_id") == session_id}
    session_decision_ids = set(decisions.keys())

    notifications = _read_json(state_dir / "notification_outbox.json", {})
    notifications = {k: v for k, v in notifications.items() if v.get("decision_id") in session_decision_ids}

    shadow = _read_json(state_dir / "shadow_ledger.json", {})
    shadow = {k: v for k, v in shadow.items() if v.get("decision_id") in session_decision_ids}

    lifecycle_state = _read_json(state_dir / "lifecycle_state.json", {})
    orders = lifecycle_state.get("orders", {})

    reconciliation = _read_json(state_dir / "latest_reconciliation.json", {})
    events_path = state_dir / "piv_events.jsonl"
    session_report = build_session_report(events_path, reconciliation, trading_date_et=trading_date_et, session_id=session_id)

    decision_recommendation_counts: dict[str, int] = {}
    watch_observation_count = 0
    entry_blocked_paper_disabled_count = 0
    for record in decisions.values():
        rec = record.get("recommendation", "UNKNOWN")
        decision_recommendation_counts[rec] = decision_recommendation_counts.get(rec, 0) + 1
        if "STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION" in (record.get("reason_codes") or []):
            watch_observation_count += 1
        if record.get("decision_execution_status") == "ENTRY_BLOCKED_PAPER_DISABLED":
            entry_blocked_paper_disabled_count += 1

    notification_status_counts = {"pending": 0, "sent": 0, "failed": 0, "unknown": 0}
    for record in notifications.values():
        status = record.get("status")
        if status in ("PENDING", "RETRY"):
            notification_status_counts["pending"] += 1
        elif status == "SENT":
            notification_status_counts["sent"] += 1
        elif status == "FAILED":
            notification_status_counts["failed"] += 1
        else:  # UNCERTAIN or anything unrecognized
            notification_status_counts["unknown"] += 1

    shadow_status_counts = {"pending": 0, "open": 0, "closed": 0, "unresolved": 0}
    for record in shadow.values():
        status = record.get("status")
        if status == "PENDING_FILL":
            shadow_status_counts["pending"] += 1
        elif status == "OPEN":
            shadow_status_counts["open"] += 1
        elif status == "CLOSED":
            shadow_status_counts["closed"] += 1
        else:
            shadow_status_counts["unresolved"] += 1

    paper_order_status_counts = {"submitted": 0, "filled": 0, "rejected": 0, "unknown": 0}
    for order in orders.values():
        status = order.get("status")
        if status in ("SUBMITTED", "new", "accepted", "partially_filled"):
            paper_order_status_counts["submitted"] += 1
        elif status == "filled":
            paper_order_status_counts["filled"] += 1
        elif status in ("rejected", "REJECTED", "canceled", "expired"):
            paper_order_status_counts["rejected"] += 1
        else:  # UNCONFIRMED_TIMEOUT or anything else genuinely unresolved
            paper_order_status_counts["unknown"] += 1

    execution_failure_count = session_report.get("rejections", 0)  # PAPER_ORDER_REJECTED count -- broker-boundary rejections, distinct from entry_blocked_paper_disabled_count above (a decision-layer, pre-broker classification)

    freshness_report = _read_json(state_dir / "freshness_report.json", {})

    return {
        "scope": {
            "session_id": session_id, "trading_date_et": trading_date_et,
            "runtime_sha": identity.get("runtime_sha"), "config_hash": identity.get("config_hash"),
        },
        "decisions": {
            "scope": "decision_ledger.json records with session_id == the scope session_id above",
            "total": len(decisions),
            "by_recommendation": decision_recommendation_counts,
            "observational_watch_count": watch_observation_count,
            "actionable_approved_count": decision_recommendation_counts.get("BUY", 0) + decision_recommendation_counts.get("SELL_TO_CLOSE", 0),
        },
        "notifications": {
            "scope": "notification_outbox.json records whose decision_id belongs to a decision in-scope above",
            "total": len(notifications),
            **notification_status_counts,
        },
        "shadow": {
            "scope": "shadow_ledger.json records whose decision_id belongs to a decision in-scope above",
            "total": len(shadow),
            **shadow_status_counts,
        },
        "paper_orders": {
            "scope": "lifecycle_state.json orders (ALL orders in the current state file -- lifecycle_state.json is not itself session-scoped, matching its own existing schema)",
            "total": len(orders),
            **paper_order_status_counts,
        },
        "natural_vs_test": {
            "scope": "piv_events.jsonl, scoped to trading_date_et if supplied -- reused from reporting.build_session_report, never re-parsed independently",
            "natural_strategy": session_report.get("natural_strategy"),
            "piv_test_traffic": session_report.get("piv_test_traffic"),
        },
        "entry_disabled_vs_execution_failure": {
            "scope": "entry_disabled: decision_ledger records with decision_execution_status==ENTRY_BLOCKED_PAPER_DISABLED (pre-broker). execution_failure: piv_events.jsonl PAPER_ORDER_REJECTED count for the same date/session (broker-boundary), via reporting.build_session_report's own 'rejections' field.",
            "entry_disabled_paper_setting": entry_blocked_paper_disabled_count,
            "broker_boundary_rejections": execution_failure_count,
        },
        "provider_and_data_health": {
            "scope": "freshness_report.json (session-end provider/symbol state) and reporting.build_session_report's data_feed_health (DATA_NOT_READY/STALE_DATA event counts)",
            "provider_state": freshness_report.get("provider_state"),
            "data_feed_health": session_report.get("data_feed_health"),
        },
    }
