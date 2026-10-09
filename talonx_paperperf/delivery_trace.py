"""
Delivery trace for Telegram research alerts (POST_DELIVERY_ALERT_MARKOUT_V1 support) -- NOT WIRED / NOT DEPLOYED.

``TracedTransport`` wraps the existing Telegram client and is passed as ``client=`` to the UNCHANGED
``talonx_ops.notify.worker.drain`` (which already accepts an injected client). It changes no routing, no retry policy
and no deduplication: it awaits the real ``client.send(text, parse_mode=...)`` exactly once and returns its result.
Around that call it records, in its OWN sidecar store (never the outbox):
  attempt_id, payload_sha256 (join key to the outbox payload), send_start_utc, response_utc (local, aware),
  Telegram message_id and server date (from the returned Message), chat_ref (sha256 prefix -- the raw chat id is never
  stored), hidden client retries counted from the client's own retry warnings (network / rate-limit / definite), and
  the exception class when the send fails.
A returned message_id confirms THAT message only; a hidden network-error retry before it means an earlier request may
also have been delivered -> the study classifies such a send AMBIGUOUS.

Activation (owner decision, outside this package): pass ``client=TracedTransport(telegram_client_for(TRADE_EVENT),
TraceStore(path))`` in ``talonx_opportunity.promotion.Promoter._drain_signal``; that is a declared promotion
deployment. Until then the study's delivery_trace_policy decides how missing traces are treated.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
CLIENT_LOGGER = "talonx_dispatch.telegram_client"
SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (attempt_id TEXT PRIMARY KEY, payload_sha256 TEXT, send_start_utc TEXT,
    response_utc TEXT, outcome TEXT, error_class TEXT, message_id INTEGER, server_date_utc TEXT, chat_ref TEXT,
    network_retries INTEGER, rate_limit_retries INTEGER, definite_error_retries INTEGER);
CREATE INDEX IF NOT EXISTS idx_traces_payload ON traces(payload_sha256);
"""


def payload_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TraceStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path, timeout=30)
        self.con.executescript(SCHEMA)

    def add(self, row: dict) -> None:
        with self.con:
            self.con.execute("INSERT INTO traces VALUES (:attempt_id,:payload_sha256,:send_start_utc,:response_utc,"
                             ":outcome,:error_class,:message_id,:server_date_utc,:chat_ref,:network_retries,"
                             ":rate_limit_retries,:definite_error_retries)", row)


class _RetryCounter(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.network = self.rate = self.definite = 0

    def emit(self, record):
        msg = record.getMessage()
        if msg.startswith("Telegram network error"):
            self.network += 1
        elif msg.startswith("Telegram rate limit hit"):
            self.rate += 1
        elif msg.startswith("Telegram send error"):
            self.definite += 1


class TracedTransport:
    """Duck-types the Telegram client for ``worker._send_sync`` (``is_configured`` + async ``send``)."""

    def __init__(self, client, store: TraceStore, *, clock=None):
        self._client, self._store = client, store
        self._clock = clock or (lambda: datetime.now(UTC))
        self.config = getattr(client, "config", None)

    @property
    def is_configured(self) -> bool:
        return bool(getattr(self._client, "is_configured", True))

    async def send(self, text: str, parse_mode=None, **kw):
        counter = _RetryCounter()
        log = logging.getLogger(CLIENT_LOGGER)
        log.addHandler(counter)
        start = self._clock()
        row = {"attempt_id": uuid.uuid4().hex, "payload_sha256": payload_hash(text), "send_start_utc": start.isoformat(),
               "response_utc": None, "outcome": None, "error_class": None, "message_id": None,
               "server_date_utc": None, "chat_ref": None}
        try:
            msg = await self._client.send(text, parse_mode=parse_mode, **kw)
            row["response_utc"] = self._clock().isoformat()
            row["outcome"] = "API_ACCEPTED" if msg is not None else "NO_MESSAGE_RETURNED"
            if msg is not None:
                row["message_id"] = getattr(msg, "message_id", None)
                d = getattr(msg, "date", None)
                row["server_date_utc"] = d.astimezone(UTC).isoformat() if isinstance(d, datetime) and d.tzinfo else None
                chat = getattr(getattr(msg, "chat", None), "id", None)
                row["chat_ref"] = hashlib.sha256(str(chat).encode()).hexdigest()[:12] if chat is not None else None
            return msg
        except Exception as exc:
            row["response_utc"] = self._clock().isoformat()
            row["outcome"], row["error_class"] = "SEND_FAILED", type(exc).__name__
            raise
        finally:
            log.removeHandler(counter)
            row.update(network_retries=counter.network, rate_limit_retries=counter.rate,
                       definite_error_retries=counter.definite)
            try:
                self._store.add(row)
            except Exception:  # noqa: BLE001 -- tracing must never affect delivery
                pass


def make_trace_lookup(outbox_path: Path, trace_path: Path):
    """event_id -> study trace dict (read-only on both stores), or None when no API_ACCEPTED trace exists."""
    def lookup(event_id: str):
        if not Path(trace_path).exists() or not Path(outbox_path).exists():
            return None
        ob = sqlite3.connect(f"file:{outbox_path}?mode=ro", uri=True)
        tr = sqlite3.connect(f"file:{trace_path}?mode=ro", uri=True)
        try:
            r = ob.execute("SELECT payload_text FROM ops_notification_outbox WHERE event_id=?", (event_id,)).fetchone()
            if r is None:
                return None
            rows = tr.execute("SELECT send_start_utc, response_utc, outcome, error_class, message_id, server_date_utc, "
                              "network_retries FROM traces WHERE payload_sha256=? ORDER BY send_start_utc",
                              (payload_hash(r[0]),)).fetchall()
        finally:
            ob.close()
            tr.close()
        ok = [x for x in rows if x[2] == "API_ACCEPTED"]
        if not ok:
            return None
        last = ok[-1]
        prior_failed_ambiguous = any(x[2] == "SEND_FAILED" for x in rows if x[0] < last[0])
        return {"send_start_utc": last[0], "response_utc": last[1], "message_id_present": last[4] is not None,
                "server_date_utc": last[5], "hidden_retries": sum(x[6] or 0 for x in rows),
                "ambiguous_prior_attempt": prior_failed_ambiguous or len(ok) > 1, "attempt_rows": len(rows)}
    return lookup
