"""Authoritative local PIV telemetry with best-effort Telegram fan-out."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

EVENT_TYPES = (
    "STARTUP", "PREFLIGHT_PASS", "PREFLIGHT_FAIL", "PAPER_SESSION_STARTED",
    "MARKET_DATA_READY", "DATA_NOT_READY", "SIGNAL", "ORDER_INTENT",
    "PAPER_ORDER_SUBMITTED", "PAPER_ORDER_ACCEPTED", "PAPER_ORDER_REJECTED",
    "PAPER_ORDER_CANCELLED", "PARTIAL_FILL", "FILLED", "POSITION_OPENED",
    "STOP_TRIGGERED", "EXIT_TRIGGERED", "EXIT_REQUESTED", "EXIT_FILLED",
    "POSITION_CLOSED", "EOD_FLATTEN", "STALE_DATA", "BROKER_ERROR",
    "KILL_SWITCH", "SESSION_SUMMARY",
)


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

    @classmethod
    def build(cls, event: str, **fields: object) -> "PivEvent":
        if event not in EVENT_TYPES:
            raise ValueError(f"unsupported PIV event: {event}")
        return cls(event=event, timestamp=datetime.now(timezone.utc).isoformat(), **fields)


class EventBus:
    """Local telemetry is authoritative; Telegram can never alter processing."""

    def __init__(
        self, path: Path, telegram_send: Callable[[str], bool] | None = None,
        feed_mode: str = "RESEARCH_SIP",
    ) -> None:
        self.path = path
        self.telegram_send = telegram_send
        self.feed_mode = feed_mode
        self._telegram_seen: set[str] = set()
        self.telegram_attempts = 0
        self.telegram_failures = 0

    @staticmethod
    def _key(event: PivEvent) -> str:
        return "|".join(str(x or "") for x in (
            event.event, event.correlation_id, event.broker_order_id, event.status, event.reason,
        ))

    @staticmethod
    def format_telegram(event: PivEvent) -> str:
        fields = ["PAPER / NO REAL CAPITAL", event.timestamp, event.event]
        if event.feed_mode is not None:
            fields.append(f"feed_mode={event.feed_mode}")
        for name in ("symbol", "correlation_id", "price", "quantity", "reason", "status"):
            value = getattr(event, name)
            if value is not None:
                fields.append(f"{name}={value}")
        return " | ".join(fields)

    def emit(self, event: PivEvent) -> bool:
        if event.feed_mode is None:
            event = replace(event, feed_mode=self.feed_mode)
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
        try:
            if not self.telegram_send(self.format_telegram(event)):
                self.telegram_failures += 1
                return False
        except Exception:
            self.telegram_failures += 1
            return False
        return True
