"""Task 83-R1 §4 -- per-pipeline transport (Pub/Sub) health state machine.

``CollectorService`` owns one ``TransportHealth`` per observed pipeline
(Original / PIV), updates it as subscriptions connect / fail / reconnect /
receive messages, and passes a THREAD-SAFE SNAPSHOT (a plain dict copy)
into every ``ComparisonCollector.collect_once`` pass.

A failed subscription becomes ``DISCONNECTED`` -- never ``NOT_RUN`` (which
means "no attempt was ever made"). One pipeline's disconnection never
changes the other's health.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any

# states
NOT_RUN = "NOT_RUN"          # no connection attempt has been made
RUNNING = "RUNNING"          # connected + subscribed + recently heard from (or just connected)
STALE = "STALE"             # connected + subscribed but no message within the staleness bound
DISCONNECTED = "DISCONNECTED"  # a connection/subscription attempt failed or dropped

_STALE_SECONDS_DEFAULT = 120.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TransportHealth:
    pipeline: str
    stale_seconds: float = _STALE_SECONDS_DEFAULT
    connection_attempted: bool = False
    connected: bool = False
    subscribed_channels: tuple[str, ...] = ()
    last_message_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error: str | None = None
    reconnect_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _now: Any = field(default=_utcnow, repr=False)

    # --- transitions (called from the subscribe coroutine) ---

    def mark_attempt(self) -> None:
        with self._lock:
            self.connection_attempted = True

    def mark_connected(self, channels: tuple[str, ...]) -> None:
        with self._lock:
            was_down = self.connection_attempted and not self.connected
            self.connected = True
            self.subscribed_channels = tuple(channels)
            self.last_heartbeat_at = self._now().isoformat()
            self.last_error = None
            if was_down:
                self.reconnect_count += 1

    def mark_message(self) -> None:
        with self._lock:
            now = self._now().isoformat()
            self.last_message_at = now
            self.last_heartbeat_at = now

    def mark_heartbeat(self) -> None:
        with self._lock:
            self.last_heartbeat_at = self._now().isoformat()

    def mark_error(self, error: str) -> None:
        with self._lock:
            self.connection_attempted = True
            self.connected = False
            self.last_error = str(error)[:500]

    # --- derived state ---

    def _state(self) -> str:
        if not self.connection_attempted:
            return NOT_RUN
        if not self.connected:
            return DISCONNECTED
        ref = self.last_message_at or self.last_heartbeat_at
        if ref is not None:
            try:
                age = (self._now() - datetime.fromisoformat(ref)).total_seconds()
                if age > self.stale_seconds:
                    return STALE
            except ValueError:
                pass
        return RUNNING

    def snapshot(self) -> dict[str, Any]:
        """A plain, immutable dict copy -- safe to hand to another thread."""
        with self._lock:
            return {
                "pipeline": self.pipeline,
                "state": self._state(),
                "connection_attempted": self.connection_attempted,
                "connected": self.connected,
                "subscribed_channels": list(self.subscribed_channels),
                "last_message_at": self.last_message_at,
                "last_heartbeat_at": self.last_heartbeat_at,
                "last_error": self.last_error,
                "reconnect_count": self.reconnect_count,
            }


def merged_snapshot(*healths: TransportHealth) -> dict[str, Any]:
    return {h.pipeline: h.snapshot() for h in healths}
