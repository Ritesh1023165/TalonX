"""
talonx_ingest.intelligence.delivery.outbox
==========================================
``DeliveryOutbox`` — the durable, restart-safe outbox for Telegram
intelligence delivery.

Additive tables in the SAME SQLite file the 96A–96E stores use
(``settings.ledger.path``). ``CREATE TABLE IF NOT EXISTS`` only; no
existing table or row is touched. It is **not** ``dispatch_audit.db`` and
it never touches the quant ``alerts`` table.

Lifecycle of one row (``delivery_id`` PK):

    enqueue()  -> PENDING            (persist BEFORE any send attempt)
    mark_sent()   PENDING -> SENT    (idempotent; a re-send is suppressed)
    mark_failed() PENDING -> PENDING (attempts++, next_retry_at set) or
                             FAILED  (terminal, attempts >= MAX)
    mark_suppressed() any -> SUPPRESSED  (dedup / no-op update)

``enqueue`` is idempotent on ``delivery_id``: the same card rendered by the
same layout version is one logical delivery. Repeated ingestion of the
same event never produces a second PENDING row.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from talonx_ingest.config import settings
from talonx_ingest.intelligence.delivery.config import (
    DELIVERY_STORE_SCHEMA_VERSION,
    MAX_SEND_ATTEMPTS,
)
from talonx_ingest.intelligence.delivery.render_model import TelegramIntelligenceMessage

STATE_PENDING = "PENDING"
STATE_SENT = "SENT"
STATE_FAILED = "FAILED"
STATE_SUPPRESSED = "SUPPRESSED"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intelligence_delivery (
    delivery_id       TEXT PRIMARY KEY,
    card_id           TEXT NOT NULL,
    event_id          TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    channel           TEXT NOT NULL,
    render_version    TEXT NOT NULL,
    band              TEXT,
    tier              TEXT NOT NULL,
    route             TEXT NOT NULL,
    state             TEXT NOT NULL,
    disposition       TEXT NOT NULL DEFAULT 'NEW',   -- NEW | UPDATE
    text              TEXT NOT NULL,
    parse_mode        TEXT NOT NULL,
    content_hash      TEXT NOT NULL,
    prev_content_hash TEXT,
    truncated         INTEGER NOT NULL DEFAULT 0,
    dropped_sections  TEXT NOT NULL DEFAULT '[]',
    evidence_urls     TEXT NOT NULL DEFAULT '[]',
    attempts          INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT,
    enqueued_at_utc   TEXT NOT NULL,
    updated_at_utc    TEXT NOT NULL,
    sent_at_utc       TEXT,
    next_retry_at_utc TEXT,
    suppress_reason   TEXT
);
CREATE INDEX IF NOT EXISTS idx_id_state   ON intelligence_delivery (state);
CREATE INDEX IF NOT EXISTS idx_id_card    ON intelligence_delivery (card_id);
CREATE INDEX IF NOT EXISTS idx_id_symbol  ON intelligence_delivery (symbol);
CREATE INDEX IF NOT EXISTS idx_id_route   ON intelligence_delivery (route, state);

CREATE TABLE IF NOT EXISTS intelligence_delivery_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id    TEXT NOT NULL,
    at_utc         TEXT NOT NULL,
    kind           TEXT NOT NULL,     -- ENQUEUE | SENT | RETRY | FAILED | SUPPRESSED | UPDATE
    detail         TEXT
);
CREATE INDEX IF NOT EXISTS idx_idlog_delivery ON intelligence_delivery_log (delivery_id);
"""


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(v)


def _dt(raw) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class DeliveryRow:
    delivery_id: str
    card_id: str
    event_id: str
    symbol: str
    channel: str
    render_version: str
    band: str | None
    tier: str
    route: str
    state: str
    disposition: str
    text: str
    parse_mode: str
    content_hash: str
    prev_content_hash: str | None
    truncated: bool
    dropped_sections: tuple[str, ...]
    evidence_urls: tuple[str, ...]
    attempts: int
    last_error: str | None
    enqueued_at_utc: datetime | None
    updated_at_utc: datetime | None
    sent_at_utc: datetime | None
    next_retry_at_utc: datetime | None
    suppress_reason: str | None


@dataclass
class EnqueueResult:
    row: DeliveryRow
    created: bool                 # a brand-new PENDING row
    disposition: str             # NEW | UPDATE | SUPPRESSED
    reason: str


class DeliveryOutbox:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else Path(settings.ledger.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES "
            "('intelligence_delivery_schema_version', ?) ON CONFLICT(key) DO NOTHING",
            (str(DELIVERY_STORE_SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DeliveryOutbox":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def schema_version(self) -> int:
        r = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key='intelligence_delivery_schema_version'"
        ).fetchone()
        return int(r[0]) if r else 0

    # ------------------------------------------------------------------
    def _log(self, delivery_id: str, kind: str, detail: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO intelligence_delivery_log (delivery_id, at_utc, kind, detail) "
            "VALUES (?,?,?,?)",
            (delivery_id, _iso(datetime.now(timezone.utc)), kind, detail),
        )

    def get(self, delivery_id: str) -> DeliveryRow | None:
        r = self._conn.execute(
            "SELECT * FROM intelligence_delivery WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
        return self._row(r) if r else None

    def logs(self, delivery_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT at_utc, kind, detail FROM intelligence_delivery_log "
            "WHERE delivery_id = ? ORDER BY id",
            (delivery_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # enqueue — persist BEFORE send. Idempotent on delivery_id.
    # ------------------------------------------------------------------
    def enqueue(
        self,
        message: TelegramIntelligenceMessage,
        *,
        delivery_id: str,
        disposition: str = "NEW",
        reason: str = "",
        now: datetime | None = None,
    ) -> EnqueueResult:
        now = now or datetime.now(timezone.utc)
        existing = self.get(delivery_id)

        if existing is None:
            self._conn.execute(
                """
                INSERT INTO intelligence_delivery (
                    delivery_id, card_id, event_id, symbol, channel, render_version,
                    band, tier, route, state, disposition, text, parse_mode, content_hash,
                    prev_content_hash, truncated, dropped_sections, evidence_urls,
                    attempts, enqueued_at_utc, updated_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    delivery_id, message.card_id, message.event_id, message.symbol.upper(),
                    delivery_id.split(":", 1)[0], message.render_version,
                    message.band.value if message.band else None,
                    message.tier, message.route, STATE_PENDING, disposition,
                    message.text, message.parse_mode, message.content_hash,
                    None, 1 if message.truncated else 0,
                    json.dumps(list(message.dropped_sections)),
                    json.dumps(list(message.evidence_urls)),
                    0, _iso(now), _iso(now),
                ),
            )
            self._log(delivery_id, "ENQUEUE", f"disposition={disposition} reason={reason}")
            self._conn.commit()
            return EnqueueResult(self.get(delivery_id), True, "NEW", reason or "first render")

        # already have a row for this delivery_id
        if existing.state == STATE_PENDING:
            if existing.content_hash == message.content_hash:
                return EnqueueResult(existing, False, "SUPPRESSED", "identical text still pending")
            # pending row not sent yet -> just refresh its text in place
            self._conn.execute(
                "UPDATE intelligence_delivery SET text=?, content_hash=?, truncated=?, "
                "dropped_sections=?, evidence_urls=?, band=?, tier=?, route=?, updated_at_utc=? "
                "WHERE delivery_id=?",
                (
                    message.text, message.content_hash, 1 if message.truncated else 0,
                    json.dumps(list(message.dropped_sections)),
                    json.dumps(list(message.evidence_urls)),
                    message.band.value if message.band else None,
                    message.tier, message.route, _iso(now), delivery_id,
                ),
            )
            self._log(delivery_id, "ENQUEUE", "refreshed pending text before send")
            self._conn.commit()
            return EnqueueResult(self.get(delivery_id), False, "NEW", "pending text refreshed")

        if existing.state == STATE_SENT:
            if existing.content_hash == message.content_hash:
                return EnqueueResult(existing, False, "SUPPRESSED", "already sent, unchanged")
            if disposition != "UPDATE":
                return EnqueueResult(existing, False, "SUPPRESSED", "already sent; caller did not request UPDATE")
            # an approved update: re-open the row as PENDING with an UPDATE disposition
            self._conn.execute(
                "UPDATE intelligence_delivery SET state=?, disposition='UPDATE', text=?, "
                "content_hash=?, prev_content_hash=?, truncated=?, dropped_sections=?, "
                "evidence_urls=?, band=?, tier=?, route=?, attempts=0, last_error=NULL, "
                "next_retry_at_utc=NULL, updated_at_utc=? WHERE delivery_id=?",
                (
                    STATE_PENDING, message.text, message.content_hash, existing.content_hash,
                    1 if message.truncated else 0,
                    json.dumps(list(message.dropped_sections)),
                    json.dumps(list(message.evidence_urls)),
                    message.band.value if message.band else None,
                    message.tier, message.route, _iso(now), delivery_id,
                ),
            )
            self._log(delivery_id, "UPDATE", reason or "approved update")
            self._conn.commit()
            return EnqueueResult(self.get(delivery_id), False, "UPDATE", reason or "approved update")

        if existing.state in (STATE_FAILED, STATE_SUPPRESSED):
            # allow a fresh attempt on an explicit re-enqueue
            self._conn.execute(
                "UPDATE intelligence_delivery SET state=?, text=?, content_hash=?, truncated=?, "
                "dropped_sections=?, evidence_urls=?, band=?, tier=?, route=?, attempts=0, "
                "last_error=NULL, next_retry_at_utc=NULL, suppress_reason=NULL, updated_at_utc=? "
                "WHERE delivery_id=?",
                (
                    STATE_PENDING, message.text, message.content_hash,
                    1 if message.truncated else 0,
                    json.dumps(list(message.dropped_sections)),
                    json.dumps(list(message.evidence_urls)),
                    message.band.value if message.band else None,
                    message.tier, message.route, _iso(now), delivery_id,
                ),
            )
            self._log(delivery_id, "ENQUEUE", f"re-opened from {existing.state}")
            self._conn.commit()
            return EnqueueResult(self.get(delivery_id), False, "NEW", f"re-opened from {existing.state}")

        return EnqueueResult(existing, False, "SUPPRESSED", f"unhandled state {existing.state}")

    # ------------------------------------------------------------------
    def mark_suppressed(self, delivery_id: str, reason: str) -> None:
        self._conn.execute(
            "UPDATE intelligence_delivery SET state=?, suppress_reason=?, updated_at_utc=? "
            "WHERE delivery_id=?",
            (STATE_SUPPRESSED, reason, _iso(datetime.now(timezone.utc)), delivery_id),
        )
        self._log(delivery_id, "SUPPRESSED", reason)
        self._conn.commit()

    def mark_sent(self, delivery_id: str, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._conn.execute(
            "UPDATE intelligence_delivery SET state=?, sent_at_utc=?, last_error=NULL, "
            "next_retry_at_utc=NULL, updated_at_utc=? WHERE delivery_id=? AND state=?",
            (STATE_SENT, _iso(now), _iso(now), delivery_id, STATE_PENDING),
        )
        self._log(delivery_id, "SENT", None)
        self._conn.commit()

    def mark_failed(
        self, delivery_id: str, error: str, *, retry_after_seconds: float | None = None,
        permanent: bool = False, now: datetime | None = None,
    ) -> str:
        """Records a failed attempt. Returns the new state (PENDING for a
        retry, FAILED when the attempt budget is spent or ``permanent``)."""
        now = now or datetime.now(timezone.utc)
        row = self.get(delivery_id)
        if row is None:
            return "UNKNOWN"
        attempts = row.attempts + 1
        if permanent or attempts >= MAX_SEND_ATTEMPTS:
            self._conn.execute(
                "UPDATE intelligence_delivery SET state=?, attempts=?, last_error=?, "
                "next_retry_at_utc=NULL, updated_at_utc=? WHERE delivery_id=?",
                (STATE_FAILED, attempts, error[:500], _iso(now), delivery_id),
            )
            self._log(delivery_id, "FAILED", error[:200])
            self._conn.commit()
            return STATE_FAILED
        nxt = None
        if retry_after_seconds is not None:
            from datetime import timedelta

            nxt = _iso(now + timedelta(seconds=max(0.0, retry_after_seconds)))
        self._conn.execute(
            "UPDATE intelligence_delivery SET attempts=?, last_error=?, next_retry_at_utc=?, "
            "updated_at_utc=? WHERE delivery_id=?",
            (attempts, error[:500], nxt, _iso(now), delivery_id),
        )
        self._log(delivery_id, "RETRY", f"attempt {attempts}: {error[:150]}")
        self._conn.commit()
        return STATE_PENDING

    # ------------------------------------------------------------------
    def pending(
        self, *, route: str | None = None, now: datetime | None = None, limit: int | None = None
    ) -> list[DeliveryRow]:
        """PENDING rows whose ``next_retry_at_utc`` is due, ordered for
        delivery: band priority (CRITICAL first), then enqueue time."""
        now = now or datetime.now(timezone.utc)
        where = ["state = ?"]
        params: list = [STATE_PENDING]
        if route is not None:
            where.append("route = ?")
            params.append(route)
        where.append("(next_retry_at_utc IS NULL OR next_retry_at_utc <= ?)")
        params.append(_iso(now))
        sql = (
            "SELECT * FROM intelligence_delivery WHERE " + " AND ".join(where)
            + " ORDER BY CASE band WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 "
            "WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END, enqueued_at_utc ASC, delivery_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._row(r) for r in self._conn.execute(sql, params).fetchall()]

    def counts_by_state(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT state, COUNT(*) c FROM intelligence_delivery GROUP BY state"
        ).fetchall()
        return {r["state"]: r["c"] for r in rows}

    def query(
        self, *, symbol: str | None = None, state: str | None = None, card_id: str | None = None,
        limit: int | None = None,
    ) -> list[DeliveryRow]:
        where: list[str] = []
        params: list = []
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())
        if state:
            where.append("state = ?")
            params.append(state)
        if card_id:
            where.append("card_id = ?")
            params.append(card_id)
        sql = "SELECT * FROM intelligence_delivery"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY enqueued_at_utc DESC, delivery_id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._row(r) for r in self._conn.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------
    def _row(self, r: sqlite3.Row) -> DeliveryRow:
        return DeliveryRow(
            delivery_id=r["delivery_id"],
            card_id=r["card_id"],
            event_id=r["event_id"],
            symbol=r["symbol"],
            channel=r["channel"],
            render_version=r["render_version"],
            band=r["band"],
            tier=r["tier"],
            route=r["route"],
            state=r["state"],
            disposition=r["disposition"],
            text=r["text"],
            parse_mode=r["parse_mode"],
            content_hash=r["content_hash"],
            prev_content_hash=r["prev_content_hash"],
            truncated=bool(r["truncated"]),
            dropped_sections=tuple(json.loads(r["dropped_sections"] or "[]")),
            evidence_urls=tuple(json.loads(r["evidence_urls"] or "[]")),
            attempts=r["attempts"],
            last_error=r["last_error"],
            enqueued_at_utc=_dt(r["enqueued_at_utc"]),
            updated_at_utc=_dt(r["updated_at_utc"]),
            sent_at_utc=_dt(r["sent_at_utc"]),
            next_retry_at_utc=_dt(r["next_retry_at_utc"]),
            suppress_reason=r["suppress_reason"],
        )
