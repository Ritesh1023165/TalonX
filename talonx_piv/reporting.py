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
    rows = []
    if event_path.exists():
        rows = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if trading_date_et is not None:
        rows = [row for row in rows if row.get("trading_date_et") == trading_date_et]
    counts = Counter(row["event"] for row in rows)
    data_issues = counts["DATA_NOT_READY"] + counts["STALE_DATA"]
    execution_drift = len(reconciliation.get("unexpected_broker_symbols", [])) + len(reconciliation.get("missing_broker_symbols", []))
    classification = "PARITY_OK"
    if execution_drift: classification = "EXECUTION_DRIFT"
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
