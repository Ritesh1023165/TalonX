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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from talonx_ingest.config import settings
from talonx_ingest.intelligence.delivery.config import (
    DELIVERY_STORE_SCHEMA_VERSION,
    MAX_SEND_ATTEMPTS,
)
from talonx_ingest.intelligence.delivery.render_model import TelegramIntelligenceMessage

STATE_PENDING = "PENDING"
STATE_IN_FLIGHT = "IN_FLIGHT"    # claimed by a drainer, request about to cross /
                                # crossing the network. A restart / competing
                                # drainer that finds one recovers it to AMBIGUOUS
                                # (never blindly re-sends).
STATE_SENT = "SENT"
STATE_FAILED = "FAILED"
STATE_SUPPRESSED = "SUPPRESSED"
STATE_EXPIRED = "EXPIRED"        # D5: a PENDING row older than its route cutoff --
                                # terminal, never deleted, never sent
STATE_AMBIGUOUS = "AMBIGUOUS"    # a send whose outcome could not be confirmed --
                                # durable, NOT auto-retried, needs a human decision

# Task 136B: the per-row freshness-decision outcome -- see
# DeliveryOutbox._expire_row_if_stale's own docstring for the full
# rationale. Deliberately NOT reusing the delivery `state` vocabulary
# above as the disposition constants (OK/EXPIRED/UNQUALIFIED/DEFER):
# UNQUALIFIED and EXPIRED both land the row in an existing `state`
# (SUPPRESSED / EXPIRED respectively), but the CALLER-facing distinction
# ("was there evidence this was actually old, or just no evidence at
# all") matters even though the two share no meaningfully different
# downstream handling today.
_FRESH_OK = "OK"                  # valid basis, within cutoff -- may send
_FRESH_EXPIRED = "EXPIRED"        # valid basis, over cutoff -- terminal
_FRESH_UNQUALIFIED = "UNQUALIFIED"  # no usable source-time evidence -- terminal
_FRESH_DEFER = "DEFER"            # lookup itself failed -- transient, retry later

# Task 137 (revised, Task 138): a bounded backoff applied to a DEFER'd
# row's own next_retry_at_utc -- see _expire_row_if_stale's DEFER branch.
# Without this, a row whose lookup keeps failing sorts in the EXACT SAME
# position every cycle (band, then enqueue_time ASC) and a bounded
# per-cycle `pending()` selection (`LIMIT`) can be filled ENTIRELY by such
# rows, never reaching a genuinely eligible row sitting behind them -- a
# starvation gap distinct from (and not covered by) "a DEFER'd row does
# not stop the REST of an already-selected batch", which was already
# correctly handled.
#
# Task 138 correction: a FIXED 30s backoff (the original Task 137 fix)
# is NOT sufficient at the real production cycle interval (~3-4 minutes,
# confirmed via poll-cycle logs) whenever the bulk expire_stale() sweep
# cannot reach the failing row within its own bound (e.g. permanently
# consumed by other still-fresh, still-PENDING rows ahead of it in
# enqueue order -- the same structural gap Task 136A closed for the
# EXPIRED case, now shown to recur for DEFER). Reproduced directly: a
# fixed 30s backoff against a 210s cycle gap, with a bounded sweep that
# never reaches the failing rows, starves a valid row behind them across
# 20 consecutive realistic cycles (~66 minutes) with zero progress. Fixed
# with a genuine per-row, EXPONENTIALLY GROWING, CAPPED backoff (the same
# principle already used for send-attempt retries in `mark_failed`/
# `backoff_seconds()` elsewhere in this codebase, not a new or arbitrary
# mechanism) keyed to a dedicated `defer_count` column (NOT the unrelated
# `attempts` send-counter) -- so a row that keeps failing is excluded for
# a growing window that eventually exceeds any realistic cycle interval,
# guaranteeing eventual progress without an unbounded scan and without
# picking one arbitrary long sleep value. `defer_count` resets to 0 the
# moment the row reaches any non-DEFER outcome (OK/EXPIRED/UNQUALIFIED).
_DEFER_BACKOFF_BASE_SECONDS = 30.0
_DEFER_BACKOFF_CAP_SECONDS = 3600.0


def _defer_backoff_seconds(defer_count: int) -> float:
    """Exponential, capped -- ``defer_count`` is 1-based (this DEFER is
    the Nth consecutive one for this row)."""
    return min(_DEFER_BACKOFF_CAP_SECONDS,
              _DEFER_BACKOFF_BASE_SECONDS * (2 ** max(0, defer_count - 1)))


@dataclass
class _FreshnessOutcome:
    disposition: str          # one of _FRESH_OK / _FRESH_EXPIRED / _FRESH_UNQUALIFIED / _FRESH_DEFER
    reason: str | None = None  # populated for every disposition except _FRESH_OK


def _validate_source_time(evt: datetime, now: datetime) -> tuple[datetime | None, str | None]:
    """Task 136B: explicit validation for a source ``accepted_at_utc``
    returned by an ``event_time_lookup`` -- a timestamp is not
    automatically usable just because a value came back. Returns
    ``(evt, None)`` when usable, or ``(None, reason)`` when not -- never
    raises (a malformed/future timestamp is a data-quality fact to
    report, not a program error).

    - Timezone-naive: cannot be safely compared against a UTC ``now``
      (silently assuming a timezone here is exactly the kind of implicit
      behaviour Task 136B closes) -- rejected.
    - More than a small clock-skew tolerance (5 minutes) in the future:
      a source cannot publish something before it happens; treated as
      invalid rather than granting it "very fresh" status by trusting
      the number at face value.
    """
    if evt.tzinfo is None:
        return None, "source timestamp is timezone-naive (cannot be safely compared)"
    if evt > now + timedelta(minutes=5):
        return None, f"source timestamp {evt.isoformat()} is in the future relative to now"
    return evt, None


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
    attempt_id: str | None = None
    in_flight_since_utc: datetime | None = None
    transport_message_id: str | None = None


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
        # additive migration: durable in-flight claim + transport ack id
        _have = {r[1] for r in self._conn.execute("PRAGMA table_info(intelligence_delivery)")}
        for col, ddl in (
            ("attempt_id", "attempt_id TEXT"),
            ("in_flight_since_utc", "in_flight_since_utc TEXT"),
            ("transport_message_id", "transport_message_id TEXT"),
            # Task 138: consecutive-DEFER counter, distinct from the
            # send-attempt `attempts` column -- drives the exponential
            # backoff in _defer_backoff_seconds(). Default 0 for every
            # existing/new row (never deferred yet).
            ("defer_count", "defer_count INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in _have:
                self._conn.execute(f"ALTER TABLE intelligence_delivery ADD COLUMN {ddl}")
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

    def get_meta(self, key: str) -> str | None:
        r = self._conn.execute("SELECT value FROM schema_meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self._conn.commit()

    def digest_pending(self, *, now: datetime | None = None,
                       limit: int | None = None) -> list[DeliveryRow]:
        """PENDING rows on the DIGEST route (held for aggregation)."""
        return self.pending(route="DIGEST", now=now, limit=limit)

    def claim_digest_batch(self, delivery_ids: list[str], digest_id: str, *,
                           now: datetime | None = None) -> list[str]:
        """Atomically move a batch of PENDING DIGEST rows to IN_FLIGHT under one
        ``digest_id``. Returns the ids actually claimed (a competing digest run
        gets fewer / none)."""
        now = now or datetime.now(timezone.utc)
        claimed: list[str] = []
        for did in delivery_ids:
            cur = self._conn.execute(
                "UPDATE intelligence_delivery SET state=?, attempt_id=?, in_flight_since_utc=?, "
                "updated_at_utc=? WHERE delivery_id=? AND state=?",
                (STATE_IN_FLIGHT, digest_id, _iso(now), _iso(now), did, STATE_PENDING),
            )
            if cur.rowcount == 1:
                claimed.append(did)
                self._log(did, "IN_FLIGHT", f"digest {digest_id}")
        self._conn.commit()
        return claimed

    def mark_digest_sent(self, delivery_ids: list[str], digest_id: str, *,
                         message_id: str | int | None = None,
                         now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        for did in delivery_ids:
            self._conn.execute(
                "UPDATE intelligence_delivery SET state=?, sent_at_utc=?, last_error=NULL, "
                "next_retry_at_utc=NULL, in_flight_since_utc=NULL, "
                "transport_message_id=?, updated_at_utc=? WHERE delivery_id=? AND state=?",
                (STATE_SENT, _iso(now),
                 f"digest:{digest_id}" + (f":{message_id}" if message_id is not None else ""),
                 _iso(now), did, STATE_IN_FLIGHT),
            )
            self._log(did, "SENT", f"in digest {digest_id} (message_id={message_id})")
        self._conn.commit()

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
                "next_retry_at_utc=NULL, defer_count=0, updated_at_utc=? WHERE delivery_id=?",
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
                "last_error=NULL, next_retry_at_utc=NULL, defer_count=0, suppress_reason=NULL, "
                "updated_at_utc=? WHERE delivery_id=?",
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

    def claim_for_send(self, delivery_id: str, attempt_id: str, *,
                       now: datetime | None = None) -> bool:
        """Atomically move a due PENDING row to IN_FLIGHT and stamp it with this
        drainer's ``attempt_id``. Returns True iff THIS call won the claim -- a
        competing drainer (or a re-entrant call) gets False and must not send.
        Persist-before-network: the claim is committed before the transport is
        touched, so a crash mid-send leaves a recoverable IN_FLIGHT row.
        """
        now = now or datetime.now(timezone.utc)
        cur = self._conn.execute(
            "UPDATE intelligence_delivery SET state=?, attempt_id=?, in_flight_since_utc=?, "
            "updated_at_utc=? WHERE delivery_id=? AND state=? "
            "AND (next_retry_at_utc IS NULL OR next_retry_at_utc <= ?)",
            (STATE_IN_FLIGHT, attempt_id, _iso(now), _iso(now), delivery_id,
             STATE_PENDING, _iso(now)),
        )
        self._conn.commit()
        if cur.rowcount == 1:
            self._log(delivery_id, "IN_FLIGHT", f"claimed attempt {attempt_id}")
            return True
        return False

    def release_claim(self, delivery_id: str, attempt_id: str, *,
                      now: datetime | None = None) -> None:
        """A CLEAN transient failure before the request left the process --
        return the row to PENDING so a later cycle retries. Only our own claim."""
        now = now or datetime.now(timezone.utc)
        self._conn.execute(
            "UPDATE intelligence_delivery SET state=?, attempt_id=NULL, in_flight_since_utc=NULL, "
            "updated_at_utc=? WHERE delivery_id=? AND state=? AND attempt_id=?",
            (STATE_PENDING, _iso(now), delivery_id, STATE_IN_FLIGHT, attempt_id),
        )
        self._conn.commit()

    def recover_in_flight(self, *, now: datetime | None = None,
                          stale_after_seconds: float = 90.0) -> list[str]:
        """Any IN_FLIGHT row older than ``stale_after_seconds`` -> AMBIGUOUS.
        Called at drain start and on service open: a row stuck IN_FLIGHT means a
        drainer died / was cancelled / restarted DURING a send -- Telegram may or
        may not have the message, so it must NOT be blind-retried. Returns the
        ids recovered."""
        from datetime import timedelta

        now = now or datetime.now(timezone.utc)
        cutoff = _iso(now - timedelta(seconds=max(0.0, stale_after_seconds)))
        rows = self._conn.execute(
            "SELECT delivery_id FROM intelligence_delivery "
            "WHERE state=? AND (in_flight_since_utc IS NULL OR in_flight_since_utc <= ?)",
            (STATE_IN_FLIGHT, cutoff),
        ).fetchall()
        ids = [r["delivery_id"] for r in rows]
        for did in ids:
            self._conn.execute(
                "UPDATE intelligence_delivery SET state=?, last_error=?, "
                "next_retry_at_utc=NULL, updated_at_utc=? WHERE delivery_id=? AND state=?",
                (STATE_AMBIGUOUS,
                 "recovered from a stale IN_FLIGHT claim -- outcome unknown, not retried",
                 _iso(now), did, STATE_IN_FLIGHT),
            )
            self._log(did, "AMBIGUOUS", "recovered stale IN_FLIGHT claim")
        if ids:
            self._conn.commit()
        return ids

    def mark_sent(self, delivery_id: str, *, message_id: str | int | None = None,
                  now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._conn.execute(
            "UPDATE intelligence_delivery SET state=?, sent_at_utc=?, last_error=NULL, "
            "next_retry_at_utc=NULL, in_flight_since_utc=NULL, "
            "transport_message_id=COALESCE(?, transport_message_id), updated_at_utc=? "
            "WHERE delivery_id=? AND state IN (?, ?)",
            (STATE_SENT, _iso(now),
             (str(message_id) if message_id is not None else None),
             _iso(now), delivery_id, STATE_PENDING, STATE_IN_FLIGHT),
        )
        self._log(delivery_id, "SENT",
                  f"message_id={message_id}" if message_id is not None else None)
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
                "next_retry_at_utc=NULL, attempt_id=NULL, in_flight_since_utc=NULL, "
                "updated_at_utc=? WHERE delivery_id=?",
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
            "UPDATE intelligence_delivery SET state=?, attempts=?, last_error=?, next_retry_at_utc=?, "
            "attempt_id=NULL, in_flight_since_utc=NULL, updated_at_utc=? WHERE delivery_id=?",
            (STATE_PENDING, attempts, error[:500], nxt, _iso(now), delivery_id),
        )
        self._log(delivery_id, "RETRY", f"attempt {attempts}: {error[:150]}")
        self._conn.commit()
        return STATE_PENDING

    def mark_ambiguous(self, delivery_id: str, detail: str, *, now: datetime | None = None) -> str:
        """A send whose outcome the transport could not confirm (e.g. a timeout
        AFTER the request left, a 5xx with an unknown body). The row goes to a
        durable AMBIGUOUS state: it is NOT auto-retried (a blind retry could
        double-send) and NOT marked SENT. A human resolves it."""
        now = now or datetime.now(timezone.utc)
        self._conn.execute(
            "UPDATE intelligence_delivery SET state=?, last_error=?, next_retry_at_utc=NULL, "
            "in_flight_since_utc=NULL, updated_at_utc=? WHERE delivery_id=? AND state IN (?, ?)",
            (STATE_AMBIGUOUS, detail[:500], _iso(now), delivery_id,
             STATE_PENDING, STATE_IN_FLIGHT),
        )
        self._log(delivery_id, "AMBIGUOUS", detail[:200])
        self._conn.commit()
        return STATE_AMBIGUOUS

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

    def expire_stale(
        self, *, now: datetime | None = None,
        max_age_seconds: "dict[str, int] | int | None" = None,
        event_time_lookup=None,
        limit: int | None = None,
        unqualified_ids_out: "list[str] | None" = None,
    ) -> list[str]:
        """Move PENDING rows older than their per-route cutoff to EXPIRED.

        Task 136B: ``unqualified_ids_out``, if given, is extended in place
        with the delivery_ids this same sweep found UNQUALIFIED (moved to
        SUPPRESSED) -- an opt-in, backward-compatible way for a caller
        (``process_pending``/``process_digest``) to observe both
        dispositions from this ONE call without changing the return
        contract every existing caller/test already depends on (a bare
        ``list[str]`` of EXPIRED ids).

        Audit-preserving: a state transition with an ``EXPIRED`` log entry, not
        a delete. Idempotent. Returns the delivery_ids expired. ``max_age_seconds``
        is a ``{route: seconds}`` map (missing route -> default) or a single int
        for all routes; ``None`` uses ``config.CARD_MAX_AGE_SECONDS``.

        Freshness is measured from the **older** of (the public event time, if
        ``event_time_lookup(event_id)`` returns one) and the enqueue time -- so
        an old filing enqueued today does NOT count as fresh. The transition
        reason records which basis triggered it.

        Task 133: ``limit`` bounds how many PENDING rows this ONE call
        inspects (oldest ``enqueued_at_utc`` first -- the rows most likely
        to actually be stale). Without it, a large PENDING backlog makes
        this call scan EVERY pending row and -- when ``event_time_lookup``
        is given -- do one SEPARATE, SYNCHRONOUS database read per row
        (``deliver_cycle`` passes a lookup that queries the events store).
        That synchronous, unbounded loop runs inside an ``async def``
        caller with no ``await`` in it anywhere, so it cannot yield to the
        event loop -- ``asyncio.wait_for``'s timeout around the caller
        can never fire while it is running (confirmed live at ~4,000
        PENDING rows: the whole Intelligence process became unresponsive,
        holding its own write lock, for minutes). ``None`` preserves the
        exact prior unbounded behaviour for any existing caller/test that
        doesn't pass it -- callers with a large PENDING volume (see
        ``deliver_cycle``) MUST pass a bound. Full coverage is preserved
        across cycles, oldest-first, not silently narrowed: a row that
        isn't reached this cycle is reached on a later one, well within
        any real cutoff (default 24h; a several-hundred-row bound sweeps
        thousands of rows within tens of minutes at a several-minute
        cycle cadence)."""
        from datetime import timedelta

        from talonx_ingest.intelligence.delivery.config import (
            CARD_MAX_AGE_DEFAULT_SECONDS, CARD_MAX_AGE_SECONDS,
        )

        now = now or datetime.now(timezone.utc)
        if max_age_seconds is None:
            route_max = dict(CARD_MAX_AGE_SECONDS)
            default_max = CARD_MAX_AGE_DEFAULT_SECONDS
        elif isinstance(max_age_seconds, int):
            route_max, default_max = {}, max_age_seconds
        else:
            route_max = dict(max_age_seconds)
            default_max = CARD_MAX_AGE_DEFAULT_SECONDS

        expired: list[str] = []
        mutated = False   # Task 136B/137: EXPIRED, UNQUALIFIED or DEFER all mutate the row
        # Task 137: this sweep deliberately does NOT filter on next_retry_
        # at_utc the way pending() does. That column is shared with the
        # UNRELATED send-attempt backoff mark_failed() sets (a row simply
        # waiting for its NEXT SEND try, nothing to do with a lookup
        # failure) -- filtering the AGE sweep on it here would let a row
        # that is merely awaiting a send retry silently escape an
        # age-based expiry it genuinely still needs, conflating two
        # different backoffs that happen to share one column. The
        # per-row inline gate (expire_one_if_stale, used against
        # pending()'s own already-next_retry_at_utc-filtered selection)
        # is what actually protects the bounded SEND-selection path from
        # starvation; this bulk sweep still benefits indirectly, since it
        # writes the SAME DEFER backoff (see _expire_row_if_stale) if it
        # happens to reach a failing row first.
        sql = (
            "SELECT delivery_id, route, event_id, enqueued_at_utc FROM intelligence_delivery "
            "WHERE state = ? ORDER BY enqueued_at_utc ASC"
        )
        params: list = [STATE_PENDING]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        for r in rows:
            outcome = self._expire_row_if_stale(
                delivery_id=r["delivery_id"], route=r["route"], event_id=r["event_id"],
                enqueued_at_utc=r["enqueued_at_utc"], now=now,
                route_max=route_max, default_max=default_max,
                event_time_lookup=event_time_lookup,
            )
            # Task 136B: the bulk sweep's own return contract (list of
            # EXPIRED ids) is unchanged for backward compatibility -- an
            # UNQUALIFIED row is also mutated (to SUPPRESSED, a genuinely
            # different terminal disposition, see _expire_row_if_stale) but
            # is not counted in this list, since callers of the ORIGINAL
            # expire_stale() specifically track "expired by established
            # age", not "suppressed for missing evidence" (the per-row
            # inline gate in process_pending/process_digest is what
            # surfaces DrainResult.unqualified/.unqualified_ids). A DEFER
            # outcome (Task 137: now writes a bounded next_retry_at_utc
            # backoff, see _expire_row_if_stale) never changes `state` and
            # is not counted in either list -- it is neither verdict.
            if outcome.disposition == _FRESH_EXPIRED:
                expired.append(r["delivery_id"])
                mutated = True
            elif outcome.disposition == _FRESH_UNQUALIFIED:
                mutated = True
                if unqualified_ids_out is not None:
                    unqualified_ids_out.append(r["delivery_id"])
            elif outcome.disposition == _FRESH_DEFER:
                mutated = True
        if mutated:
            self._conn.commit()
        return expired

    def _expire_row_if_stale(
        self, *, delivery_id: str, route: str, event_id: str, enqueued_at_utc,
        now: datetime, route_max: dict, default_max: int, event_time_lookup,
    ) -> "_FreshnessOutcome":
        """Shared freshness-basis logic for exactly ONE row -- used by both
        the bulk ``expire_stale`` sweep above AND the per-row check
        immediately before a send (``expire_one_if_stale`` below), so the
        two can never disagree and a row cannot be sent just because the
        bulk sweep (bounded, enqueue-time-ordered) had not yet reached it
        while ``pending()`` (BAND-priority-ordered -- a HIGH-band
        historical card sorts ahead of hundreds of older-enqueued, lower-
        band rows) had already selected it for sending (Task 136A).

        Task 136B: distinguishes FOUR outcomes, not two --
          * OK           -- a valid source/enqueue basis, within cutoff.
          * EXPIRED       -- a valid basis, over cutoff (existing older-of-
                            source/enqueue policy, unchanged for this case).
          * UNQUALIFIED   -- no usable source-time evidence at all (the
                            lookup ran cleanly and found none, or found a
                            malformed/future timestamp) -- Task 136A's own
                            fix still silently fell back to enqueue time
                            alone here, which is exactly the gap this
                            closes: queue creation time is NEVER, on its
                            own, evidence of freshness for informational
                            delivery. Terminal -- moved to SUPPRESSED (an
                            existing state, distinct from EXPIRED, since
                            "no evidence of age" is not the same claim as
                            "proven old").
          * DEFER         -- the lookup itself raised (a transient failure,
                            e.g. a DB error) -- NOT a verdict on the event;
                            ``state`` stays PENDING (never terminal) so a
                            later pass can retry it. Task 137: a bounded,
                            fixed backoff (`_DEFER_BACKOFF_SECONDS`) is
                            written to ``next_retry_at_utc`` -- without it
                            the row sorts in the EXACT SAME position on
                            every subsequent call (band, then enqueue_time
                            ASC), and a bounded per-cycle `pending()`
                            selection can be filled ENTIRELY by rows stuck
                            this way, never reaching a genuinely eligible
                            row behind them. The backoff excludes it from
                            selection for a short, bounded window, not
                            forever -- a later successful lookup recovers
                            it exactly as before, no different terminal
                            state, no lost row.
        Task 136B, additionally: ``event_time_lookup`` being ``None``
        (no lookup CAPABILITY offered by this caller at all) is a
        different situation from a provided lookup finding nothing for
        THIS event -- the former is a caller-level choice to use
        enqueue-time-only cutoff semantics (the pre-event-time Task 117
        behaviour, still exercised directly by callers/tests that never
        pass ``event_time_lookup``), not a per-event "no publication
        evidence" verdict, so it is judged on ``enq`` alone rather than
        UNQUALIFIED.

        Mutates the row for EXPIRED/UNQUALIFIED (does NOT commit -- callers
        commit) and, as of Task 137, also for DEFER (only ``next_retry_at_
        utc``/``updated_at_utc``, never ``state`` -- callers must commit
        this case too now). OK never mutates. `enqueued_at_utc` may be a
        string (raw column) or a ``DeliveryRow``'s own datetime
        attribute."""
        enq = enqueued_at_utc if isinstance(enqueued_at_utc, datetime) else _dt(enqueued_at_utc)
        evt: datetime | None = None
        evt_invalid_reason: str | None = None
        if event_time_lookup is not None:
            try:
                raw_evt = event_time_lookup(event_id)
            except Exception as exc:  # noqa: BLE001 -- a lookup FAILURE is transient
                reason = f"event_time_lookup failed: {exc}"
                row_now = self._conn.execute(
                    "SELECT defer_count FROM intelligence_delivery WHERE delivery_id=?",
                    (delivery_id,),
                ).fetchone()
                prior_defers = int(row_now["defer_count"]) if row_now is not None else 0
                new_defer_count = prior_defers + 1
                backoff = _defer_backoff_seconds(new_defer_count)
                next_retry = now + timedelta(seconds=backoff)
                self._conn.execute(
                    "UPDATE intelligence_delivery SET next_retry_at_utc=?, updated_at_utc=?, "
                    "defer_count=? WHERE delivery_id=?",
                    (_iso(next_retry), _iso(now), new_defer_count, delivery_id),
                )
                self._log(delivery_id, "DEFERRED",
                          f"{reason} -- consecutive defer #{new_defer_count}, "
                          f"retry not before {next_retry.isoformat()} ({backoff:.0f}s backoff)")
                return _FreshnessOutcome(_FRESH_DEFER, reason)
            if raw_evt is not None:
                evt, evt_invalid_reason = _validate_source_time(raw_evt, now)

        if evt is None and event_time_lookup is not None:
            # A lookup capability WAS offered and ran cleanly, but found
            # nothing usable for this specific event (never returned, or
            # returned a malformed/future timestamp -- see
            # _validate_source_time). Queue-creation time (enq) is
            # deliberately NOT used as a substitute here -- that is the
            # exact defect this task closes.
            reason = evt_invalid_reason or "no publication/acceptance evidence available"
            return self._terminal_unqualified(delivery_id, now, reason)

        if evt is None and enq is None:
            # No lookup capability AND no enqueue time either -- truly
            # nothing to judge freshness by.
            return self._terminal_unqualified(
                delivery_id, now, "no enqueue time and no event_time_lookup provided")

        basis = min(enq, evt) if (enq is not None and evt is not None) else (evt or enq)
        which = "event_time" if basis == evt else "enqueue_time"
        cutoff_s = route_max.get(route, default_max)
        if now - basis <= timedelta(seconds=cutoff_s):
            return _FreshnessOutcome(_FRESH_OK, None)
        age_h = (now - basis).total_seconds() / 3600.0
        reason = (f"stale_card: {age_h:.1f}h old by {which} "
                  f"> {cutoff_s / 3600:.0f}h {route} cutoff")
        self._conn.execute(
            "UPDATE intelligence_delivery SET state=?, next_retry_at_utc=NULL, "
            "updated_at_utc=?, suppress_reason=?, defer_count=0 WHERE delivery_id=?",
            (STATE_EXPIRED, _iso(now), reason, delivery_id),
        )
        self._log(delivery_id, "EXPIRED", reason)
        return _FreshnessOutcome(_FRESH_EXPIRED, reason)

    def _terminal_unqualified(self, delivery_id: str, now: datetime, reason: str) -> "_FreshnessOutcome":
        """Task 136B: shared terminal-state write for the UNQUALIFIED
        disposition -- no usable source-time evidence at all. Moves the row
        to SUPPRESSED (an existing state, distinct from EXPIRED: "no
        evidence of age" is not the same claim as "proven old")."""
        self._conn.execute(
            "UPDATE intelligence_delivery SET state=?, next_retry_at_utc=NULL, "
            "updated_at_utc=?, suppress_reason=?, defer_count=0 WHERE delivery_id=?",
            (STATE_SUPPRESSED, _iso(now), f"unqualified: {reason}", delivery_id),
        )
        self._log(delivery_id, "SUPPRESSED", f"unqualified: {reason}")
        return _FreshnessOutcome(_FRESH_UNQUALIFIED, reason)

    def expire_one_if_stale(
        self, row, *, now: datetime | None = None,
        max_age_seconds: "dict[str, int] | int | None" = None,
        event_time_lookup=None,
    ) -> "_FreshnessOutcome":
        """Task 136A/136B/137: the per-row freshness gate applied
        immediately before a send (see ``process_pending``/``process_
        digest`` in pipeline.py) -- the actual enforcement point queue
        creation time cannot bypass, independent of whether a prior bulk
        ``expire_stale`` pass reached this specific row. ``row`` is a
        ``DeliveryRow`` (has ``.delivery_id``/``.route``/``.event_id``/
        ``.enqueued_at_utc``). Commits immediately for EXPIRED/UNQUALIFIED
        (unlike the bulk sweep, called one row at a time inline in the
        send loop) and, as of Task 137, for DEFER too (a bounded ``next_
        retry_at_utc`` backoff is written -- see ``_expire_row_if_stale``
        -- so a permanently-failing lookup cannot monopolize a bounded
        selection ``limit`` forever; ``state`` itself is never touched).
        Returns a ``_FreshnessOutcome`` -- callers must only send when
        ``.disposition == _FRESH_OK``."""
        from talonx_ingest.intelligence.delivery.config import (
            CARD_MAX_AGE_DEFAULT_SECONDS, CARD_MAX_AGE_SECONDS,
        )

        now = now or datetime.now(timezone.utc)
        if max_age_seconds is None:
            route_max, default_max = dict(CARD_MAX_AGE_SECONDS), CARD_MAX_AGE_DEFAULT_SECONDS
        elif isinstance(max_age_seconds, int):
            route_max, default_max = {}, max_age_seconds
        else:
            route_max, default_max = dict(max_age_seconds), CARD_MAX_AGE_DEFAULT_SECONDS
        outcome = self._expire_row_if_stale(
            delivery_id=row.delivery_id, route=row.route, event_id=row.event_id,
            enqueued_at_utc=row.enqueued_at_utc, now=now,
            route_max=route_max, default_max=default_max,
            event_time_lookup=event_time_lookup,
        )
        if outcome.disposition in (_FRESH_EXPIRED, _FRESH_UNQUALIFIED, _FRESH_DEFER):
            self._conn.commit()
        return outcome

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
            attempt_id=(r["attempt_id"] if "attempt_id" in r.keys() else None),
            in_flight_since_utc=(_dt(r["in_flight_since_utc"]) if "in_flight_since_utc" in r.keys() else None),
            transport_message_id=(r["transport_message_id"] if "transport_message_id" in r.keys() else None),
        )
