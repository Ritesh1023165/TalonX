"""
talonx_ops.notify.outbox -- the durable outbox for OPERATIONS and
RESEARCH notifications (RI-2, RI2-H).
====================================================================
V2's own TRADE_EVENT notifications keep using their existing, already
production-proven ``v2_alert_outbox``/``deliver_outbox``
(``talonx_v2/store.py``, ``talonx_v2/delivery.py``) unchanged -- this
module is NOT a replacement for that, it is the equivalent durable
outbox for the genuinely NEW event classes RI-2 introduces (operational
health/incident notifications, research-lab audit records) that have no
existing home and are not tied to a specific V2 episode/position.

Same lifecycle shape as ``v2_alert_outbox`` (reused deliberately, not
reinvented, per RI2-H's own instruction not to invent new states where
equivalent ones already exist):

    PENDING --(send ok)--------> SENT
    PENDING --(router/dest HOLD)-> HELD
    PENDING --(transient fail)--> RETRY --(next attempt)--> PENDING-ish
    PENDING --(permanent/exhausted)-> FAILED
    PENDING --(deadline passed)--> EXPIRED
    PENDING --(unconfirmed outcome)-> AMBIGUOUS
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_notification_outbox (
    event_id         TEXT PRIMARY KEY,
    destination      TEXT NOT NULL,          -- TRADE_EVENT | OPERATIONS | RESEARCH
    event_type       TEXT NOT NULL,          -- e.g. ACCOUNT_BLOCK, EXIT_UNRESOLVED, RECONCILIATION_FAILURE, STARTUP, SHUTDOWN
    producer         TEXT NOT NULL,          -- the ONE authoritative producer module/component (RI2-O)
    dedup_key        TEXT NOT NULL,
    payload_text     TEXT NOT NULL,
    provenance_json  TEXT NOT NULL,
    state            TEXT NOT NULL,          -- PENDING | SENT | HELD | RETRY | FAILED | EXPIRED | AMBIGUOUS
    attempts         INTEGER NOT NULL DEFAULT 0,
    next_attempt_utc TEXT,
    last_error       TEXT,
    transport_ref    TEXT,
    deliver_by_utc   TEXT,                   -- optional actionable-notification deadline (mirrors v2_alert_outbox)
    created_at_utc   TEXT NOT NULL,
    updated_at_utc   TEXT NOT NULL,
    sent_at_utc      TEXT
);
CREATE INDEX IF NOT EXISTS idx_ops_outbox_destination_state
    ON ops_notification_outbox(destination, state);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class NotifyStore:
    """Mirrors V2Store's own outbox method shapes
    (enqueue/outbox_due/all_outbox/update_outbox) deliberately, so the
    SAME generic drain loop (``talonx_ops.notify.worker.drain``) can
    operate over either store via simple duck-typing -- no shared base
    class, no framework, just a matching small interface."""

    def __init__(self, path: str = "notifications.db", busy_timeout_ms: int = 30_000):
        self.path = path
        self._busy_timeout_ms = int(busy_timeout_ms)
        if "/" in path or "\\" in path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=self._busy_timeout_ms / 1000.0)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            yield c
            c.commit()
        finally:
            c.close()

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def enqueue(self, *, event_id: str, destination: str, event_type: str, producer: str,
               dedup_key: str, payload_text: str, provenance: dict,
               deliver_by_utc: str | None = None) -> bool:
        """Idempotent enqueue -- returns True iff a NEW row was written.
        Re-enqueuing the SAME event_id is a safe no-op (RI2-K: same
        business event processed twice -> at most one logical
        notification/outbox item)."""
        with self._conn() as c:
            exists = c.execute(
                "SELECT 1 FROM ops_notification_outbox WHERE event_id=?", (event_id,)
            ).fetchone() is not None
            if exists:
                return False
            c.execute(
                """INSERT INTO ops_notification_outbox
                   (event_id, destination, event_type, producer, dedup_key, payload_text,
                    provenance_json, state, attempts, deliver_by_utc, created_at_utc, updated_at_utc)
                   VALUES (?,?,?,?,?,?,?, 'PENDING', 0, ?, ?, ?)""",
                (event_id, destination, event_type, producer, dedup_key, payload_text,
                 json.dumps(provenance, default=str), deliver_by_utc, _utcnow(), _utcnow()),
            )
            return True

    def outbox_due(self, *, now_iso: str, destination: str | None = None) -> list[dict]:
        with self._conn() as c:
            if destination is not None:
                return [dict(r) for r in c.execute(
                    "SELECT * FROM ops_notification_outbox WHERE state IN ('PENDING','RETRY') "
                    "AND destination=? AND (next_attempt_utc IS NULL OR next_attempt_utc <= ?) "
                    "ORDER BY created_at_utc", (destination, now_iso))]
            return [dict(r) for r in c.execute(
                "SELECT * FROM ops_notification_outbox WHERE state IN ('PENDING','RETRY') "
                "AND (next_attempt_utc IS NULL OR next_attempt_utc <= ?) "
                "ORDER BY created_at_utc", (now_iso,))]

    def all_outbox(self, *, destination: str | None = None) -> list[dict]:
        with self._conn() as c:
            if destination is not None:
                return [dict(r) for r in c.execute(
                    "SELECT * FROM ops_notification_outbox WHERE destination=? "
                    "ORDER BY created_at_utc", (destination,))]
            return [dict(r) for r in c.execute(
                "SELECT * FROM ops_notification_outbox ORDER BY created_at_utc")]

    def update_outbox(self, event_id: str, *, state: str, attempts: int | None = None,
                      next_attempt_utc: str | None = None, last_error: str | None = None,
                      transport_ref: str | None = None, sent: bool = False) -> None:
        with self._conn() as c:
            c.execute(
                """UPDATE ops_notification_outbox SET state=?,
                     attempts=COALESCE(?, attempts),
                     next_attempt_utc=?, last_error=?, transport_ref=COALESCE(?, transport_ref),
                     updated_at_utc=?, sent_at_utc=CASE WHEN ? THEN ? ELSE sent_at_utc END
                   WHERE event_id=?""",
                (state, attempts, next_attempt_utc, last_error, transport_ref, _utcnow(),
                 1 if sent else 0, _utcnow() if sent else None, event_id),
            )

    def counts_by_state(self, *, destination: str | None = None) -> dict[str, int]:
        """RI2-N observability: PENDING/SENT/FAILED/EXPIRED/... counts."""
        with self._conn() as c:
            if destination is not None:
                rows = c.execute(
                    "SELECT state, COUNT(*) n FROM ops_notification_outbox "
                    "WHERE destination=? GROUP BY state", (destination,))
            else:
                rows = c.execute(
                    "SELECT state, COUNT(*) n FROM ops_notification_outbox GROUP BY state")
            return {r["state"]: r["n"] for r in rows}

    def last_sent(self, *, destination: str | None = None) -> dict | None:
        with self._conn() as c:
            if destination is not None:
                row = c.execute(
                    "SELECT * FROM ops_notification_outbox WHERE destination=? AND state='SENT' "
                    "ORDER BY sent_at_utc DESC LIMIT 1", (destination,)).fetchone()
            else:
                row = c.execute(
                    "SELECT * FROM ops_notification_outbox WHERE state='SENT' "
                    "ORDER BY sent_at_utc DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def last_failure(self, *, destination: str | None = None) -> dict | None:
        with self._conn() as c:
            if destination is not None:
                row = c.execute(
                    "SELECT * FROM ops_notification_outbox WHERE destination=? "
                    "AND state IN ('FAILED','AMBIGUOUS') ORDER BY updated_at_utc DESC LIMIT 1",
                    (destination,)).fetchone()
            else:
                row = c.execute(
                    "SELECT * FROM ops_notification_outbox WHERE state IN ('FAILED','AMBIGUOUS') "
                    "ORDER BY updated_at_utc DESC LIMIT 1").fetchone()
            return dict(row) if row else None
