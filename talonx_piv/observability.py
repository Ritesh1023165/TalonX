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


# Task 81 §4 (C1/C2): a missing OPTIONAL ledger, a genuine verified-zero,
# and an UNREADABLE required source are three distinct conditions -- the
# projection must name which one it is, never collapse all of them into a
# plausible-looking zero.
_HEALTHY_SOURCE_STATUSES = frozenset({"PRESENT_WITH_RECORDS", "VERIFIED_ZERO", "ABSENT_OPTIONAL"})


def _classify_json_source(
    path: Path, *, required: bool, total_records: int, in_scope_records: int, session_run_corroborated: bool,
) -> dict[str, Any]:
    if not path.exists():
        return {
            "status": "ABSENT_REQUIRED" if required else "ABSENT_OPTIONAL",
            "detail": "file does not exist",
        }
    try:
        text = path.read_text(encoding="utf-8")
        if text.strip():
            json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "UNREADABLE", "detail": f"{type(exc).__name__}: {exc}"}
    if total_records == 0:
        if session_run_corroborated:
            return {"status": "VERIFIED_ZERO", "detail": "present, parses, no records; a session run is corroborated by the events log"}
        return {"status": "ZERO_UNCORROBORATED", "detail": "present, parses, no records, and no session run is corroborated -- cannot distinguish 'nothing happened' from 'never populated'"}
    if in_scope_records == 0:
        return {"status": "WRONG_SESSION", "detail": f"{total_records} record(s) present but none belong to the scoped session/date"}
    return {"status": "PRESENT_WITH_RECORDS", "detail": f"{in_scope_records} of {total_records} record(s) in scope"}


def build_decision_status(state_dir: Path, decision_id: str) -> dict[str, Any]:
    """Task 78I Stage 1C -- derives a decision's CURRENT notification/
    shadow/execution status by joining against the authoritative, linked
    durable records every time this is called -- never a separately stored,
    independently-mutable status field that could regress or go stale.
    Rebuilding this after a restart, or after a late/duplicate event has
    been persisted, always reflects exactly the current ledger truth (pure
    function of on-disk state) -- see status_projection_recovery.json.

    Read-only; performs zero writes.
    """
    decisions = _read_json(state_dir / "decision_ledger.json", {})
    decision = decisions.get(decision_id)
    if decision is None:
        return {"decision_id": decision_id, "found": False}

    notifications = _read_json(state_dir / "notification_outbox.json", {})
    notification_status = "NOT_APPLICABLE"
    for record in notifications.values():
        if record.get("decision_id") == decision_id:
            notification_status = record.get("status", "UNKNOWN")
            break
    else:
        # Known, disclosed limitation: NotificationOutbox deduplicates by
        # (ticker, date, classification, recommendation, reason_codes), NOT
        # by decision_id -- a decision whose identical situation was already
        # queued under an EARLIER decision_id will show no direct record
        # here even though an equivalent alert was sent. Reported as
        # NOT_APPLICABLE (never fabricated as SENT) -- see remaining_issues.md.
        pass

    shadow = _read_json(state_dir / "shadow_ledger.json", {})
    shadow_status = "NOT_APPLICABLE"
    for record in shadow.values():
        if record.get("decision_id") == decision_id:
            shadow_status = record.get("status", "UNKNOWN")
            break

    gemini = _read_json(state_dir / "gemini_enrichment.json", {})
    gemini_record = gemini.get(decision_id)
    gemini_status = gemini_record.get("status", "NOT_REQUESTED") if gemini_record is not None else "NOT_REQUESTED"

    decision_execution_status = decision.get("decision_execution_status", "NOT_APPLICABLE")
    # Task 79E: ENTRY_ELIGIBLE_EXPERIMENTAL_PAPER is the experimental
    # analogue of ENTRY_ELIGIBLE -- a real order_intent call was attempted
    # for it too, so it must join against lifecycle intents/orders below the
    # same way, never fall through to NOT_ATTEMPTED_BY_DESIGN.
    if decision_execution_status not in ("ENTRY_ELIGIBLE", "EXIT_ELIGIBLE", "ENTRY_ELIGIBLE_EXPERIMENTAL_PAPER"):
        execution_status = "NOT_ATTEMPTED_BY_DESIGN"
    else:
        lifecycle_state = _read_json(state_dir / "lifecycle_state.json", {})
        intents = lifecycle_state.get("intents", {})
        orders = lifecycle_state.get("orders", {})
        matching_intent_id = next((iid for iid, intent in intents.items() if intent.get("decision_id") == decision_id), None)
        if matching_intent_id is None:
            # The decision layer wanted to execute (ENTRY/EXIT_ELIGIBLE), but
            # no persisted intent references this decision_id -- either the
            # order_intent call was rejected by a STATEFUL guard (which
            # rejects before persisting an intent -- e.g. a race against
            # ALREADY_HOLDING_NO_PYRAMIDING) or the attempt has not yet
            # happened. Honestly reported as unknown, never guessed.
            execution_status = "ATTEMPTED_OUTCOME_UNKNOWN_NO_PERSISTED_INTENT"
        else:
            intent = intents[matching_intent_id]
            if intent.get("status") == "REJECTED":
                execution_status = "REJECTED"
            elif intent.get("status") == "SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED":
                # Task 79E-R1: reconcile() resolved a genuinely uncertain
                # submission (no broker order id received) via its stable
                # client_order_id and confirmed it never reached the broker
                # at all -- distinct from REJECTED (which means the broker
                # DID receive and decline it) and from the generic
                # ATTEMPTED_OUTCOME_UNKNOWN fallback (this one IS resolved,
                # just to a negative outcome).
                execution_status = "CONFIRMED_NOT_SUBMITTED"
            elif intent.get("status") == "SUBMIT_FAILED_UNCERTAIN":
                # Not yet reconciled -- genuinely unknown, reported as such
                # rather than defaulting to the more optimistic-sounding
                # SUBMITTED_NO_BROKER_ACK_YET below.
                execution_status = "SUBMISSION_UNCERTAIN_PENDING_RECONCILE"
            else:
                order = next((o for o in orders.values() if o.get("intent_id") == matching_intent_id), None)
                if order is None:
                    execution_status = "SUBMITTED_NO_BROKER_ACK_YET"
                elif order.get("status") == "filled":
                    execution_status = "FILLED"
                elif order.get("status") in ("rejected", "canceled", "expired"):
                    execution_status = "REJECTED"
                elif order.get("status") == "UNCONFIRMED_TIMEOUT":
                    execution_status = "UNCONFIRMED"
                else:
                    execution_status = "PENDING"

    return {
        "decision_id": decision_id, "found": True,
        "recommendation": decision.get("recommendation"),
        "decision_execution_status": decision_execution_status,
        "notification_status": notification_status,
        "shadow_status": shadow_status,
        "gemini_status": gemini_status,
        "execution_status": execution_status,
    }


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

    decisions_raw = _read_json(state_dir / "decision_ledger.json", {})
    decisions = dict(decisions_raw)
    if session_id is not None:
        decisions = {k: v for k, v in decisions.items() if v.get("session_id") == session_id}
    session_decision_ids = set(decisions.keys())

    notifications_raw = _read_json(state_dir / "notification_outbox.json", {})
    notifications = {k: v for k, v in notifications_raw.items() if v.get("decision_id") in session_decision_ids}

    shadow_raw = _read_json(state_dir / "shadow_ledger.json", {})
    shadow = {k: v for k, v in shadow_raw.items() if v.get("decision_id") in session_decision_ids}

    gemini_raw = _read_json(state_dir / "gemini_enrichment.json", {})
    gemini = {k: v for k, v in gemini_raw.items() if k in session_decision_ids}

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

    gemini_status_counts = {"not_requested": 0, "pending": 0, "completed": 0, "timeout": 0, "malformed": 0, "unavailable": 0}
    for record in gemini.values():
        status = record.get("status", "PENDING").lower()
        key = status if status in gemini_status_counts else "not_requested"
        gemini_status_counts[key] += 1

    execution_failure_count = session_report.get("rejections", 0)  # PAPER_ORDER_REJECTED count -- broker-boundary rejections, distinct from entry_blocked_paper_disabled_count above (a decision-layer, pre-broker classification)

    # Task 79E: explicit, additive-only visibility into experimental
    # activity -- deliberately counted SEPARATELY from
    # actionable_approved_count above (EXPERIMENTAL_BUY/
    # EXPERIMENTAL_SELL_TO_CLOSE are distinct recommendation/classification
    # strings from BUY/SELL_TO_CLOSE, so they were already naturally
    # excluded from that count; this section makes the exclusion visible
    # and auditable rather than merely implicit).
    experimental_decision_count = sum(1 for record in decisions.values() if record.get("recommendation") == "EXPERIMENTAL_BUY")
    experimental_notification_count = sum(1 for record in notifications.values() if str(record.get("classification", "")).startswith("EXPERIMENTAL"))
    experimental_shadow_count = sum(1 for record in shadow.values() if record.get("experimental") is True)
    experimental_paper_order_count = sum(1 for order in orders.values() if order.get("source") == "EXPERIMENTAL")

    freshness_report = _read_json(state_dir / "freshness_report.json", {})

    # -- Task 81 §4 (C1/C2/C3): explicit source-health diagnostics --
    events_path = state_dir / "piv_events.jsonl"
    events_total = events_scoped = 0
    events_status = "ABSENT_REQUIRED"
    events_detail = "file does not exist"
    if events_path.exists():
        try:
            lines = [ln for ln in events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            parsed = []
            unreadable = 0
            for ln in lines:
                try:
                    parsed.append(json.loads(ln))
                except json.JSONDecodeError:
                    unreadable += 1
            events_total = len(parsed)
            events_scoped = sum(
                1 for r in parsed
                if (trading_date_et is None or r.get("trading_date_et") == trading_date_et)
            )
            if unreadable:
                events_status, events_detail = "UNREADABLE", f"{unreadable} unparseable line(s)"
            elif not lines:
                events_status, events_detail = "EMPTY_REQUIRED", "present but empty"
            elif events_scoped == 0 and events_total:
                events_status, events_detail = "STALE_SCOPE", f"{events_total} event(s) present, none for the scoped date {trading_date_et}"
            else:
                events_status, events_detail = "PRESENT_WITH_RECORDS", f"{events_scoped} of {events_total} event(s) in scope"
        except OSError as exc:
            events_status, events_detail = "UNREADABLE", f"{type(exc).__name__}: {exc}"
    session_run_corroborated = events_status == "PRESENT_WITH_RECORDS"

    identity_status = (
        "PRESENT_WITH_RECORDS" if identity.get("session_id")
        else ("UNREADABLE" if (state_dir / "session_identity.json").exists() else "ABSENT_REQUIRED")
    )
    if identity.get("session_id") and session_id and identity.get("session_id") != session_id:
        identity_status = "WRONG_SESSION"

    source_health = {
        "session_identity": {"status": identity_status, "detail": identity.get("session_id") or "no session_id resolved"},
        "piv_events": {"status": events_status, "detail": events_detail},
        "decision_ledger": _classify_json_source(
            state_dir / "decision_ledger.json", required=False,
            total_records=len(decisions_raw), in_scope_records=len(decisions),
            session_run_corroborated=session_run_corroborated,
        ),
        "shadow_ledger": _classify_json_source(
            state_dir / "shadow_ledger.json", required=False,
            total_records=len(shadow_raw), in_scope_records=len(shadow),
            session_run_corroborated=session_run_corroborated,
        ),
        "notification_outbox": _classify_json_source(
            state_dir / "notification_outbox.json", required=False,
            total_records=len(notifications_raw), in_scope_records=len(notifications),
            session_run_corroborated=session_run_corroborated,
        ),
        "gemini_enrichment": _classify_json_source(
            state_dir / "gemini_enrichment.json", required=False,
            total_records=len(gemini_raw), in_scope_records=len(gemini),
            session_run_corroborated=session_run_corroborated,
        ),
        "lifecycle_state": _classify_json_source(
            state_dir / "lifecycle_state.json", required=True,
            total_records=len(lifecycle_state.get("orders", {})) + len(lifecycle_state.get("positions", {})) + len(lifecycle_state.get("intents", {})),
            in_scope_records=len(lifecycle_state.get("orders", {})) + len(lifecycle_state.get("positions", {})) + len(lifecycle_state.get("intents", {})),
            session_run_corroborated=session_run_corroborated,
        ),
        "latest_reconciliation": {
            "status": ("PRESENT_WITH_RECORDS" if reconciliation else ("UNREADABLE" if (state_dir / "latest_reconciliation.json").exists() and not isinstance(reconciliation, dict) else "ABSENT_OPTIONAL")),
            "detail": "broker/internal reconciliation snapshot",
        },
        "freshness_report": {
            "status": ("PRESENT_WITH_RECORDS" if freshness_report else "ABSENT_OPTIONAL"),
            "detail": f"provider_state={freshness_report.get('provider_state')}" if freshness_report else "no session-end provider/symbol state recorded",
        },
    }
    source_health_diagnostics = [
        f"{name}: {entry['status']} ({entry['detail']})"
        for name, entry in source_health.items()
        if entry["status"] not in _HEALTHY_SOURCE_STATUSES
    ]
    source_health_ok = not source_health_diagnostics

    # Task 83 §6: PIV has NO durable QuantStateStore. The reused in-process
    # QuantScanner keeps rolling bar buffers and funnel counters in memory
    # only; they do not survive a PIV restart. Task 82 reserved an isolated
    # path (<state_dir>/piv_quant.db) so a future enablement cannot select
    # Original's database -- but a reserved, isolated path is NOT evidence
    # that persistence exists. Surfaced here as an explicit capability
    # limitation so no dashboard can imply otherwise.
    quant_db_path = state_dir / "piv_quant.db"
    capability_limitations = {
        "durable_quant_state_store": {
            "status": "NOT_IMPLEMENTED",
            "persistence_exists": False,
            "isolated_path_reserved": str(quant_db_path),
            "isolated_path_present_on_disk": quant_db_path.exists(),
            "detail": (
                "PIV Quant counters/buffers are session-lifetime, in-memory only. "
                "The isolated path is reserved (Task 82) but unused; its presence or "
                "absence on disk does not indicate that PIV Quant state is persisted."
            ),
        },
    }

    return {
        "source_health": source_health,
        "source_health_ok": source_health_ok,
        "source_health_diagnostics": source_health_diagnostics,
        "capability_limitations": capability_limitations,
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
        "gemini_enrichment": {
            "scope": "gemini_enrichment.json records keyed directly by decision_id (no dedup indirection, unlike notifications) whose decision_id belongs to a decision in-scope above",
            "total": len(gemini),
            **gemini_status_counts,
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
        "experimental": {
            "scope": "Task 79E -- EXPERIMENTAL_BUY decisions / EXPERIMENTAL-classified notifications / experimental-flagged shadow records / EXPERIMENTAL-sourced paper orders, all already scoped in-session above. Reported separately -- NEVER folded into decisions.actionable_approved_count, notifications totals-by-classification, or any validated-strategy statistic, since an experimental record is explicitly UNVALIDATED evidence, not proof the strategy is profitable.",
            "decision_count": experimental_decision_count,
            "notification_count": experimental_notification_count,
            "shadow_count": experimental_shadow_count,
            "paper_order_count": experimental_paper_order_count,
        },
    }
