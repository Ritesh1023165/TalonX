"""Deterministic post-session PIV report schema."""

from __future__ import annotations
from collections import Counter
import json
from pathlib import Path

ANOMALY_CLASSES = (
    "PARITY_OK", "ENGINE_DEFECT", "DATA_ISSUE", "EXECUTION_DRIFT",
    "STRATEGY_BEHAVIOR_EXPECTED", "REVIEW_REQUIRED",
)


def build_session_report(
    event_path: Path, reconciliation: dict, feed_mode: str | None = None,
    *, trading_date_et: str | None = None, session_id: str | None = None,
    quant_funnel: dict | None = None, integrated_projection: dict | None = None,
) -> dict:
    """trading_date_et (Task 69Q Part 2): when given, scopes every count
    below to just that America/New_York calendar date -- piv_events.jsonl
    is append-only and can span multiple trading dates (confirmed in
    Task69P's raw evidence), so a report built without this filter risks
    silently mixing e.g. 2026-08-24 and 2026-08-25 activity. Omit it only
    for legacy/whole-file callers that intentionally want the full history.

    integrated_projection (Task 77I Stage 4): the optional, read-only
    talonx_piv.observability.build_integrated_projection(...) output, passed
    through unchanged under result["integrated_projection"] when supplied --
    this function never computes it itself (no new parsing logic duplicated
    here)."""
    # Task 81 §4 (C1): an absent / empty / unreadable events source must
    # produce an EXPLICIT diagnostic -- never a plausible-looking
    # zero-activity PARITY_OK report.
    events_source_health = "OK"
    all_rows: list[dict] = []
    if not event_path.exists():
        events_source_health = "EVENTS_SOURCE_ABSENT"
    else:
        raw_lines = [line for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for line in raw_lines:
            try:
                all_rows.append(json.loads(line))
            except json.JSONDecodeError:
                events_source_health = "EVENTS_SOURCE_UNREADABLE"
        if events_source_health == "OK" and not raw_lines:
            events_source_health = "EVENTS_SOURCE_EMPTY"
    rows = all_rows
    if trading_date_et is not None:
        scoped = [row for row in rows if row.get("trading_date_et") == trading_date_et]
        if events_source_health == "OK" and not scoped and rows:
            # The file has activity, but none for the session/date being
            # reported -- a wrong-session / stale-scope condition, not
            # "verified zero activity".
            events_source_health = "EVENTS_SCOPE_EMPTY_FILE_HAS_OTHER_DATES"
        rows = scoped
    counts = Counter(row["event"] for row in rows)
    data_issues = counts["DATA_NOT_READY"] + counts["STALE_DATA"]
    execution_drift = len(reconciliation.get("unexpected_broker_symbols", [])) + len(reconciliation.get("missing_broker_symbols", []))
    classification = "PARITY_OK"
    if events_source_health != "OK":
        classification = "REVIEW_REQUIRED"
    elif execution_drift: classification = "EXECUTION_DRIFT"
    elif data_issues: classification = "DATA_ISSUE"
    elif counts["BROKER_ERROR"]: classification = "REVIEW_REQUIRED"
    resolved_feed_mode = feed_mode or (rows[0].get("feed_mode") if rows else None)

    # Task 69Q Part 4: natural (source=STRATEGY) vs PIV probe traffic must
    # never be conflated into one statistic -- see events.py's source field.
    execution_event_types = {
        "ORDER_INTENT", "PAPER_ORDER_SUBMITTED", "PAPER_ORDER_ACCEPTED", "PAPER_ORDER_REJECTED",
        "PAPER_ORDER_CANCELLED", "PARTIAL_FILL", "FILLED", "POSITION_OPENED", "POSITION_CLOSED",
    }
    natural_rows = [row for row in rows if row.get("source") == "STRATEGY"]
    probe_rows = [row for row in rows if row.get("source") == "PIV_LIFECYCLE_PROBE"]
    natural_counts = Counter(row["event"] for row in natural_rows if row["event"] in execution_event_types)
    probe_counts = Counter(row["event"] for row in probe_rows if row["event"] in execution_event_types)
    closed_natural = [row for row in natural_rows if row.get("event") == "POSITION_CLOSED"]
    gross_pnls = [row["gross_pnl"] for row in closed_natural if row.get("gross_pnl") is not None]
    net_pnls = [row["net_pnl"] for row in closed_natural if row.get("net_pnl") is not None]

    result = {
        "session_id": session_id,
        "trading_date_et": trading_date_et,
        "classification": classification,
        "events_source_health": events_source_health,
        "feed_mode": resolved_feed_mode,
        "canonical_alpha_evidence": resolved_feed_mode == "RESEARCH_SIP",
        "data_feed_health": {"data_not_ready": counts["DATA_NOT_READY"], "stale_data": counts["STALE_DATA"]},
        "expected_strategy_signals": counts["SIGNAL"], "actual_strategy_signals": counts["SIGNAL"],
        "rejections": counts["PAPER_ORDER_REJECTED"], "paper_order_intents": counts["ORDER_INTENT"],
        "submitted_orders": counts["PAPER_ORDER_SUBMITTED"], "broker_accepts": counts["PAPER_ORDER_ACCEPTED"],
        "broker_rejects": counts["PAPER_ORDER_REJECTED"], "partial_fills": counts["PARTIAL_FILL"],
        "full_fills": counts["FILLED"], "positions_opened": counts["POSITION_OPENED"],
        "positions_closed": counts["POSITION_CLOSED"], "exit_reasons": {},
        "unexpected_orders": reconciliation.get("unexpected_broker_symbols", []),
        "missed_orders": reconciliation.get("missing_broker_symbols", []),
        "duplicate_prevention_events": sum(row.get("reason") == "DUPLICATE_ORDER_INTENT" for row in rows),
        "telegram_delivery_status": "see runtime counters/logs",
        "broker_internal_reconciliation": reconciliation,
        "paper_pnl": None, "gross_R": None, "cost_R": None,
        "natural_strategy": {
            "candidates_published": counts["SIGNAL"] if not natural_rows else sum(1 for r in natural_rows if r["event"] == "SIGNAL"),
            "orders": natural_counts["PAPER_ORDER_SUBMITTED"], "fills": natural_counts["FILLED"] + natural_counts["PARTIAL_FILL"],
            "positions_opened": natural_counts["POSITION_OPENED"], "positions_closed": natural_counts["POSITION_CLOSED"],
            "gross_pnl": sum(gross_pnls) if gross_pnls else (0.0 if closed_natural else None),
            "net_pnl": sum(net_pnls) if net_pnls else (0.0 if closed_natural else None),
        },
        "piv_test_traffic": {
            "orders": probe_counts["PAPER_ORDER_SUBMITTED"], "fills": probe_counts["FILLED"] + probe_counts["PARTIAL_FILL"],
            "positions_opened": probe_counts["POSITION_OPENED"], "positions_closed": probe_counts["POSITION_CLOSED"],
            "alpha_evidence": False,
        },
    }
    if quant_funnel is not None:
        result["quant_funnel"] = quant_funnel
        if quant_funnel.get("unaccounted_candidates", 0):
            result["quant_funnel_flag"] = "UNACCOUNTED_CANDIDATES_DETECTED"
    if integrated_projection is not None:
        result["integrated_projection"] = integrated_projection
    return result


def finalize_session_report(
    state_dir: Path, events_path: Path, *, config_feed_mode: str | None,
    live_session_id: str | None, trading_date_et: str | None, eod_outcome: dict,
) -> dict:
    """Task 81 §4 (C4/C5/C6): build and durably write
    ``latest_session_report.json`` for a completed session, scoped to the
    ORIGINAL live session identity, for EVERY EOD outcome (PASSED / FAILED /
    INCONCLUSIVE). Pure read of the durable ledgers / events / reconciliation
    -- it never cancels or closes anything at the broker, so a retry can be
    issued freely. Report-generation status is recorded SEPARATELY from the
    broker/EOD status so a degraded report is never mistaken for a failed
    session (or vice versa)."""
    from .observability import build_integrated_projection

    diagnostics: list[str] = []
    report_generation_status = "OK"

    reconciliation = dict(eod_outcome.get("reconciliation") or {})
    reconciliation["feed_mode"] = config_feed_mode
    reconciliation["eod_status"] = eod_outcome.get("status")
    reconciliation["live_session_id"] = eod_outcome.get("session_id")
    reconciliation["reconciliation_run_id"] = eod_outcome.get("reconciliation_run_id")
    try:
        (state_dir / "latest_reconciliation.json").write_text(
            json.dumps(reconciliation, indent=2, sort_keys=True), encoding="utf-8",
        )
    except OSError as exc:
        report_generation_status = "DEGRADED"
        diagnostics.append(f"latest_reconciliation_write_failed:{exc}")

    quant_funnel = None
    funnel_path = state_dir / "quant_funnel_report.json"
    if funnel_path.exists():
        try:
            quant_funnel = json.loads(funnel_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report_generation_status = "DEGRADED"
            diagnostics.append(f"quant_funnel_unreadable:{exc}")

    integrated_projection = None
    if live_session_id is not None:
        try:
            integrated_projection = build_integrated_projection(
                state_dir, session_id=live_session_id, trading_date_et=trading_date_et,
            )
        except Exception as exc:  # noqa: BLE001 -- report generation must never crash shutdown
            report_generation_status = "DEGRADED"
            diagnostics.append(f"integrated_projection_failed:{type(exc).__name__}:{exc}")
    else:
        report_generation_status = "DEGRADED"
        diagnostics.append("no_live_session_identity_scope_unavailable")

    report = build_session_report(
        events_path, reconciliation, config_feed_mode,
        trading_date_et=trading_date_et, session_id=live_session_id,
        quant_funnel=quant_funnel, integrated_projection=integrated_projection,
    )
    report["eod_status"] = eod_outcome.get("status")
    report["report_generation_status"] = report_generation_status
    report["report_generation_diagnostics"] = diagnostics
    report["scoped_to"] = {"session_id": live_session_id, "trading_date_et": trading_date_et}
    if integrated_projection is not None:
        report["source_health_ok"] = integrated_projection.get("source_health_ok")
        report["source_health_diagnostics"] = integrated_projection.get("source_health_diagnostics", [])

    try:
        (state_dir / "latest_session_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8",
        )
    except OSError as exc:
        report["report_generation_status"] = "FAILED"
        report["report_generation_diagnostics"] = diagnostics + [f"latest_session_report_write_failed:{exc}"]
    return report
