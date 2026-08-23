"""Deterministic post-session PIV report schema."""

from __future__ import annotations
from collections import Counter
import json
from pathlib import Path

ANOMALY_CLASSES = (
    "PARITY_OK", "ENGINE_DEFECT", "DATA_ISSUE", "EXECUTION_DRIFT",
    "STRATEGY_BEHAVIOR_EXPECTED", "REVIEW_REQUIRED",
)


def build_session_report(event_path: Path, reconciliation: dict) -> dict:
    rows = []
    if event_path.exists():
        rows = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    counts = Counter(row["event"] for row in rows)
    data_issues = counts["DATA_NOT_READY"] + counts["STALE_DATA"]
    execution_drift = len(reconciliation.get("unexpected_broker_symbols", [])) + len(reconciliation.get("missing_broker_symbols", []))
    classification = "PARITY_OK"
    if execution_drift: classification = "EXECUTION_DRIFT"
    elif data_issues: classification = "DATA_ISSUE"
    elif counts["BROKER_ERROR"]: classification = "REVIEW_REQUIRED"
    return {
        "classification": classification,
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
    }
