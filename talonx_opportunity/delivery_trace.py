"""
Delivery trace for Telegram research alerts (POST_DELIVERY_ALERT_MARKOUT_V1 support).

``TracedTransport`` wraps the existing Telegram client and is passed as ``client=`` to the UNCHANGED
``talonx_ops.notify.worker.drain`` (wired in ``talonx_opportunity.promotion.Promoter._drain_signal``, 2026-10-09). It
changes no routing, message content, retry policy or deduplication: it awaits the real ``client.send(text,
parse_mode=...)`` exactly once and returns its result. It records, in its OWN sidecar store (never the outbox):
  attempt_id (uuid of this worker attempt), payload_sha256 (join key to the outbox payload), send_start_utc /
  response_utc (local, aware), Telegram message_id and server date (from the returned Message), chat_ref (sha256 prefix
  -- the raw chat id is never stored), client-internal retries counted from the client's OWN retry warnings
  (network = ambiguous, rate-limit = rejected by Telegram, definite = Telegram error), the exception class on failure,
  and trace_state (TRACE_OK / TRACE_PARTIAL when the returned message lacked fields).
Instrumentation can never change delivery: every recording step is guarded; a failure AFTER a successful send is
swallowed (no exception, so no worker retry and no second send) and simply leaves that send untraced
(TRACE_MISSING for the study, which then excludes it under the REQUIRED policy).
A returned message_id confirms THAT message only; a client-internal network-error retry before it means an earlier
request may also have been delivered -> the study classifies such a send AMBIGUOUS. Historical sends are never traced.
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
    network_retries INTEGER, rate_limit_retries INTEGER, definite_error_retries INTEGER, trace_state TEXT,
    recorded_utc TEXT);
CREATE INDEX IF NOT EXISTS idx_traces_payload ON traces(payload_sha256);
"""


def payload_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TraceStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path, timeout=10)
        self.con.executescript(SCHEMA)

    def add(self, row: dict) -> None:
        with self.con:
            self.con.execute("INSERT INTO traces VALUES (:attempt_id,:payload_sha256,:send_start_utc,:response_utc,"
                             ":outcome,:error_class,:message_id,:server_date_utc,:chat_ref,:network_retries,"
                             ":rate_limit_retries,:definite_error_retries,:trace_state,:recorded_utc)", row)


class _RetryCounter(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.network = self.rate = self.definite = 0

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return
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

    def _begin(self, text: str):
        try:
            counter = _RetryCounter()
            logging.getLogger(CLIENT_LOGGER).addHandler(counter)
            return counter, {"attempt_id": uuid.uuid4().hex, "payload_sha256": payload_hash(text),
                             "send_start_utc": self._clock().isoformat()}
        except Exception:  # noqa: BLE001 -- never let tracing touch the send
            return None, None

    def _finish(self, counter, row, msg, exc) -> None:
        try:
            if counter is not None:
                logging.getLogger(CLIENT_LOGGER).removeHandler(counter)
            if row is None:
                return
            row.update(response_utc=self._clock().isoformat(), error_class=type(exc).__name__ if exc else None,
                       message_id=None, server_date_utc=None, chat_ref=None,
                       network_retries=counter.network if counter else None,
                       rate_limit_retries=counter.rate if counter else None,
                       definite_error_retries=counter.definite if counter else None)
            if exc is not None:
                row.update(outcome="SEND_FAILED", trace_state="TRACE_OK")
            elif msg is None:
                row.update(outcome="NO_MESSAGE_RETURNED", trace_state="TRACE_PARTIAL")
            else:
                row["outcome"] = "API_ACCEPTED"
                mid = getattr(msg, "message_id", None)
                row["message_id"] = mid if isinstance(mid, int) else None
                d = getattr(msg, "date", None)
                row["server_date_utc"] = (d.astimezone(UTC).isoformat()
                                          if isinstance(d, datetime) and d.tzinfo is not None else None)
                chat = getattr(getattr(msg, "chat", None), "id", None)
                row["chat_ref"] = hashlib.sha256(str(chat).encode()).hexdigest()[:12] if chat is not None else None
                row["trace_state"] = ("TRACE_OK" if row["message_id"] is not None and row["server_date_utc"]
                                      else "TRACE_PARTIAL")
            row["recorded_utc"] = datetime.now(UTC).isoformat()
            self._store.add(row)
        except Exception:  # noqa: BLE001 -- instrumentation failure: the send result stands, the trace is missing
            pass

    async def send(self, text: str, parse_mode=None, **kw):
        counter, row = self._begin(text)
        try:
            msg = await self._client.send(text, parse_mode=parse_mode, **kw)
        except Exception as exc:
            self._finish(counter, row, None, exc)
            raise
        self._finish(counter, row, msg, None)
        return msg


def make_trace_lookup(outbox_path: Path, trace_path: Path):
    """event_id -> study trace dict (read-only on both stores), or None (TRACE_MISSING) when no usable API_ACCEPTED
    trace exists. Several traces for one payload (worker retries) are all reported."""
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
                              "network_retries, trace_state FROM traces WHERE payload_sha256=? ORDER BY send_start_utc",
                              (payload_hash(r[0]),)).fetchall()
        finally:
            ob.close()
            tr.close()
        ok = [x for x in rows if x[2] == "API_ACCEPTED"]
        if not ok:
            return None
        last = ok[-1]
        if last[7] != "TRACE_OK" or last[6] is None:
            return {"trace_state": "TRACE_INVALID", "attempt_rows": len(rows)}
        return {"trace_state": "TRACE_OK", "send_start_utc": last[0], "response_utc": last[1],
                "message_id_present": last[4] is not None, "server_date_utc": last[5],
                "hidden_retries": sum(x[6] or 0 for x in rows),
                "ambiguous_prior_attempt": any(x[2] == "SEND_FAILED" for x in rows) or len(ok) > 1,
                "attempt_rows": len(rows)}
    return lookup
