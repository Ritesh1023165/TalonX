"""Authoritative local PIV telemetry with best-effort Telegram fan-out."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

EVENT_TYPES = (
    "STARTUP", "PREFLIGHT_PASS", "PREFLIGHT_FAIL", "PAPER_SESSION_STARTED",
    "MARKET_DATA_READY", "DATA_NOT_READY", "SIGNAL", "ORDER_INTENT",
    "PAPER_ORDER_SUBMITTED", "PAPER_ORDER_ACCEPTED", "PAPER_ORDER_REJECTED",
    "PAPER_ORDER_CANCELLED", "PARTIAL_FILL", "FILLED", "POSITION_OPENED",
    "STOP_TRIGGERED", "EXIT_TRIGGERED", "EXIT_REQUESTED", "EXIT_FILLED",
    "POSITION_CLOSED", "EOD_FLATTEN", "STALE_DATA", "BROKER_ERROR",
    # Task 71S: symbol-level and provider-level recovery, symmetric with
    # STALE_DATA and the BROKER_ERROR-tagged provider-degradation status
    # (see freshness.py / session_runner.py). Never alpha-relevant.
    "DATA_RECOVERED", "PROVIDER_RECOVERED",
    "KILL_SWITCH", "SESSION_SUMMARY",
    "SESSION_READINESS_STATE_RESTORED", "SESSION_READINESS_STATE_MISSING",
    "SESSION_READINESS_STATE_INVALID", "SESSION_READINESS_STATE_STALE",
    "RUNTIME_PARITY_PASS", "RUNTIME_PARITY_FAIL",
    # Task 69Q: informational, non-actionable notification classes -- see
    # results/task69q_evidence_upgrade/notification_contract.json and
    # premarket_radar_contract.json. None of these ever drives an order.
    "PREMARKET_WATCH", "PREMARKET_WATCH_CLEARED", "STATUS_HEARTBEAT",
    "EOD_SUMMARY",
    # Task 72O Stage 1 -- ordered, idempotent EOD reconciliation lifecycle
    # (see talonx_piv/eod_lifecycle.py). SESSION_COMPLETED is emitted only
    # after EOD_RECONCILIATION_PASSED; never on FAILED/INCONCLUSIVE.
    "EOD_STARTED", "EOD_CANCEL_REQUESTED", "EOD_FLATTEN_REQUESTED",
    "EOD_RECONCILIATION_STARTED", "EOD_RECONCILIATION_PASSED",
    "EOD_RECONCILIATION_FAILED", "SESSION_COMPLETED",
)

# Task 69Q Part 7: every event is classified into exactly one operator-facing
# notification category so natural strategy activity, PIV probe traffic, and
# purely-observational radar output are never visually or statistically
# conflated (Part 4/Part 7). Derived entirely from fields already carried by
# every event (event type + source) -- no new required field on callers.
NOTIFICATION_CLASSES = (
    "SYSTEM", "PREMARKET_RADAR", "NATURAL_SIGNAL", "PAPER_EXECUTION", "PIV_TEST", "EOD",
)

_EXECUTION_EVENTS = {
    "ORDER_INTENT", "PAPER_ORDER_SUBMITTED", "PAPER_ORDER_ACCEPTED", "PAPER_ORDER_REJECTED",
    "PAPER_ORDER_CANCELLED", "PARTIAL_FILL", "FILLED", "POSITION_OPENED", "STOP_TRIGGERED",
    "EXIT_TRIGGERED", "EXIT_REQUESTED", "EXIT_FILLED", "POSITION_CLOSED",
}
_SYSTEM_EVENTS = {
    "STARTUP", "PREFLIGHT_PASS", "PREFLIGHT_FAIL", "PAPER_SESSION_STARTED",
    "MARKET_DATA_READY", "DATA_NOT_READY", "STALE_DATA", "BROKER_ERROR", "KILL_SWITCH",
    "DATA_RECOVERED", "PROVIDER_RECOVERED",
    "SESSION_READINESS_STATE_RESTORED", "SESSION_READINESS_STATE_MISSING",
    "SESSION_READINESS_STATE_INVALID", "SESSION_READINESS_STATE_STALE",
    "RUNTIME_PARITY_PASS", "RUNTIME_PARITY_FAIL", "STATUS_HEARTBEAT",
}


def notification_class_for(event: str, source: str | None) -> str:
    """Pure classification -- see NOTIFICATION_CLASSES. `source` is the
    existing "STRATEGY" | "PIV_LIFECYCLE_PROBE" | "PREMARKET_RADAR" | None
    field every emitter already sets (or leaves unset for pure system
    events)."""
    if event in (
        "EOD_FLATTEN", "SESSION_SUMMARY", "EOD_SUMMARY", "EOD_STARTED",
        "EOD_CANCEL_REQUESTED", "EOD_FLATTEN_REQUESTED", "EOD_RECONCILIATION_STARTED",
        "EOD_RECONCILIATION_PASSED", "EOD_RECONCILIATION_FAILED", "SESSION_COMPLETED",
    ):
        return "EOD"
    if event in ("PREMARKET_WATCH", "PREMARKET_WATCH_CLEARED"):
        return "PREMARKET_RADAR"
    if event in _SYSTEM_EVENTS:
        return "SYSTEM"
    if event == "SIGNAL" and source == "STRATEGY":
        return "NATURAL_SIGNAL"
    if event in _EXECUTION_EVENTS:
        if source == "PIV_LIFECYCLE_PROBE":
            return "PIV_TEST"
        if source == "STRATEGY":
            return "PAPER_EXECUTION"
        return "PIV_TEST"
    if source == "PIV_LIFECYCLE_PROBE":
        return "PIV_TEST"
    return "SYSTEM"


def trading_date_for(timestamp_iso: str) -> str:
    """Canonical trading-date bucket for an event: the America/New_York
    calendar date of its (UTC) timestamp. Task 69Q Part 2 -- this is what
    lets a single append-only piv_events.jsonl be safely filtered per
    session/date without ever mixing e.g. 2026-08-24 and 2026-08-25."""
    return datetime.fromisoformat(timestamp_iso).astimezone(ET).date().isoformat()


@dataclass(frozen=True)
class PivEvent:
    event: str
    timestamp: str
    symbol: str | None = None
    correlation_id: str | None = None
    signal_id: str | None = None
    order_intent_id: str | None = None
    broker_order_id: str | None = None
    position_id: str | None = None
    price: float | None = None
    quantity: float | None = None
    reason: str | None = None
    status: str | None = None
    paper: bool = True
    real_capital: bool = False
    feed_mode: str | None = None
    source: str | None = None  # "STRATEGY" | "PIV_LIFECYCLE_PROBE" | "PREMARKET_RADAR" -- see decision_engine.py, lifecycle_probe.py, premarket_radar.py
    alpha_evidence: bool | None = None  # always False when set -- today's traffic is operational PIV test traffic only

    # Task 69Q Part 2 -- session/date identity, stamped by EventBus.emit if
    # not already set by the caller, so a single append-only piv_events.jsonl
    # can always be filtered to exactly one trading date/session.
    session_id: str | None = None
    trading_date_et: str | None = None
    # Task 69Q Part 7 -- see notification_class_for; auto-derived by
    # EventBus.emit if not explicitly set.
    notification_class: str | None = None

    # Task 69Q Part 6 -- execution economics, populated only where the data
    # legitimately exists (PaperLifecycle.apply_broker_update); never
    # fabricated (e.g. gross_r/net_r stay None for any position with no
    # defined stop_price -- see lifecycle.py).
    reference_price: float | None = None
    slippage_abs: float | None = None
    slippage_bps: float | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    estimated_transaction_cost: float | None = None
    holding_seconds: float | None = None
    gross_r: float | None = None
    net_r: float | None = None
    horizon: str | None = None
    strategy_id: str | None = None

    @classmethod
    def build(cls, event: str, **fields: object) -> "PivEvent":
        if event not in EVENT_TYPES:
            raise ValueError(f"unsupported PIV event: {event}")
        return cls(event=event, timestamp=datetime.now(timezone.utc).isoformat(), **fields)


class EventBus:
    """Local telemetry is authoritative; Telegram can never alter processing."""

    def __init__(
        self, path: Path, telegram_send: Callable[[str], bool] | None = None,
        feed_mode: str = "RESEARCH_SIP", session_id: str | None = None,
        telemetry_path: Path | None = None, trading_date_et: str | None = None,
    ) -> None:
        self.path = path
        self.telegram_send = telegram_send
        self.feed_mode = feed_mode
        self.session_id = session_id
        self._telegram_seen: set[str] = set()
        self.telegram_attempts = 0
        self.telegram_failures = 0
        self.telegram_successes = 0
        # Task 83-R1 §5: durable, session-scoped notification telemetry.
        # ``telemetry_path`` is the PIV state dir; None disables persistence
        # (in-memory counters only, unchanged behaviour for isolated tests).
        self._telemetry_dir = telemetry_path
        self._trading_date_et = trading_date_et
        if self._telemetry_dir is not None:
            from .notification_telemetry import merge_telemetry

            merge_telemetry(
                self._telemetry_dir,
                session_id=session_id, trading_date_et=trading_date_et,
                ownership={
                    "outbound_enabled": telegram_send is not None,
                    "sender_constructed": telegram_send is not None,
                },
            )

    @staticmethod
    def _key(event: PivEvent) -> str:
        return "|".join(str(x or "") for x in (
            event.event, event.correlation_id, event.broker_order_id, event.status, event.reason,
        ))

    @staticmethod
    def format_telegram(event: PivEvent) -> str:
        tag = f"[{event.notification_class}] " if event.notification_class else ""
        fields = [f"{tag}PAPER / NO REAL CAPITAL", event.timestamp, event.event]
        if event.feed_mode is not None:
            fields.append(f"feed_mode={event.feed_mode}")
        if event.source is not None:
            fields.append(f"source={event.source}")
        if event.alpha_evidence is not None:
            fields.append(f"alpha_evidence={event.alpha_evidence}")
        for name in ("symbol", "correlation_id", "price", "quantity", "reason", "status"):
            value = getattr(event, name)
            if value is not None:
                fields.append(f"{name}={value}")
        return " | ".join(fields)

    def emit(self, event: PivEvent) -> bool:
        if event.feed_mode is None:
            event = replace(event, feed_mode=self.feed_mode)
        if event.session_id is None and self.session_id is not None:
            event = replace(event, session_id=self.session_id)
        if event.trading_date_et is None:
            event = replace(event, trading_date_et=trading_date_for(event.timestamp))
        if event.notification_class is None:
            event = replace(event, notification_class=notification_class_for(event.event, event.source))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), sort_keys=True) + "\n")
        if not self.telegram_send:
            return True
        key = self._key(event)
        if key in self._telegram_seen:
            return True
        self._telegram_seen.add(key)
        self.telegram_attempts += 1
        outcome = "successes"
        try:
            if not self.telegram_send(self.format_telegram(event)):
                self.telegram_failures += 1
                outcome = "failures"
                return False
        except Exception:
            self.telegram_failures += 1
            outcome = "failures"
            return False
        finally:
            # persist at the ACTUAL send boundary -- an attempt that raises
            # or returns falsey is still recorded (§5.6).
            if self._telemetry_dir is not None:
                from .notification_telemetry import merge_telemetry

                merge_telemetry(
                    self._telemetry_dir,
                    session_id=self.session_id, trading_date_et=self._trading_date_et,
                    outbound_delta={"attempts": 1, outcome: 1},
                    outbound={"last_attempt_at": event.timestamp},
                )
        self.telegram_successes += 1
        return True
