"""
talonx_ingest.intelligence.store
================================
``EventStore`` -- the persistent, idempotent home for classified
disclosure events.

Storage model
-------------
The store adds its own tables to the **same SQLite file** the existing
``IngestionLedger`` uses (``settings.ledger.path``). It is strictly
ADDITIVE: it runs ``CREATE TABLE IF NOT EXISTS`` for its own tables and
never touches ``ingested_filings`` / ``ingested_news_articles`` /
``ingested_financials`` or their rows. A DB that predates this module
opens cleanly and keeps every existing row (see the migration test).

Tables
------
``schema_meta``          key/value; holds ``event_store_schema_version``
``text_events``          one row per (accession, event_type); PK ``event_id``
``text_event_items``     every raw item code, keyed by (accession, item_code)
``text_event_exhibits``  filing documents, keyed by (accession, filename)
``event_evidence``       provenance, keyed by (event_id, transform)
``source_freshness``     one row per source; poll recency + status

Idempotency
-----------
``upsert_event`` is safe to call repeatedly with the same event: the
``text_events`` row is inserted once (``INSERT ... ON CONFLICT DO
NOTHING``), item/exhibit rows use ``INSERT OR IGNORE``, and evidence rows
use ``INSERT OR REPLACE`` so provenance can be refined without creating
duplicates. See ``idempotency_design.md``.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import date, datetime, timezone
from pathlib import Path

from talonx_ingest.config import settings
from talonx_ingest.intelligence.config import EVENT_STORE_SCHEMA_VERSION
from talonx_ingest.intelligence.domain import (
    EventType,
    EvidenceRecord,
    ExhibitRef,
    FreshnessStatus,
    SessionBucket,
    SourceType,
    TextEvent,
)
from talonx_ingest.intelligence.freshness import compute_status  # noqa: F401 (re-export convenience)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS text_events (
    event_id             TEXT PRIMARY KEY,
    schema_version       TEXT NOT NULL,
    symbol               TEXT NOT NULL,
    company_name         TEXT NOT NULL,
    source_type          TEXT NOT NULL,
    source_record_id     TEXT NOT NULL,
    event_type           TEXT NOT NULL,
    form_type            TEXT NOT NULL,
    accession            TEXT NOT NULL,
    accepted_at_utc      TEXT,
    filing_date          TEXT,
    report_period_end    TEXT,
    session_bucket       TEXT NOT NULL,
    session_reason       TEXT,
    primary_document     TEXT,
    primary_document_url TEXT,
    filing_index_url     TEXT,
    source_url           TEXT,
    source_hash          TEXT,
    is_amendment         INTEGER NOT NULL DEFAULT 0,
    amends_accession     TEXT,
    ingested_at_utc      TEXT NOT NULL,
    freshness_status     TEXT NOT NULL,
    data_quality_flags   TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_text_events_symbol       ON text_events (symbol);
CREATE INDEX IF NOT EXISTS idx_text_events_accession    ON text_events (accession);
CREATE INDEX IF NOT EXISTS idx_text_events_type         ON text_events (event_type);
CREATE INDEX IF NOT EXISTS idx_text_events_accepted     ON text_events (accepted_at_utc);
CREATE INDEX IF NOT EXISTS idx_text_events_symbol_time  ON text_events (symbol, accepted_at_utc);

CREATE TABLE IF NOT EXISTS text_event_items (
    accession  TEXT NOT NULL,
    item_code  TEXT NOT NULL,
    PRIMARY KEY (accession, item_code)
);

CREATE TABLE IF NOT EXISTS text_event_exhibits (
    accession     TEXT NOT NULL,
    filename      TEXT NOT NULL,
    source_url    TEXT NOT NULL,
    sequence      INTEGER,
    document_type TEXT,
    description   TEXT,
    PRIMARY KEY (accession, filename)
);

CREATE TABLE IF NOT EXISTS event_evidence (
    event_id        TEXT NOT NULL,
    transform       TEXT NOT NULL,
    source_provider TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_url      TEXT,
    exact_timestamp TEXT,
    retrieved_at    TEXT NOT NULL,
    input_hash      TEXT,
    notes           TEXT,
    PRIMARY KEY (event_id, transform)
);

CREATE TABLE IF NOT EXISTS source_freshness (
    source_type             TEXT PRIMARY KEY,
    last_poll_attempt_utc   TEXT,
    last_poll_success_utc   TEXT,
    latest_source_event_utc TEXT,
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'UNKNOWN',
    updated_at_utc          TEXT NOT NULL
);
"""


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


class EventStore:
    """Not thread-safe (one ``sqlite3.Connection``); safe from many asyncio
    tasks on one loop, matching ``IngestionLedger``'s contract."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else Path(settings.ledger.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('event_store_schema_version', ?) "
            "ON CONFLICT(key) DO NOTHING",
            (str(EVENT_STORE_SCHEMA_VERSION),),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def schema_version(self) -> int:
        cur = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'event_store_schema_version'"
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------
    def upsert_event(self, event: TextEvent) -> bool:
        """Insert the event if new. Returns ``True`` on a fresh insert,
        ``False`` if the ``event_id`` was already present. Item, exhibit and
        evidence rows are reconciled on every call (idempotent)."""
        cur = self._conn.execute(
            """
            INSERT INTO text_events (
                event_id, schema_version, symbol, company_name, source_type,
                source_record_id, event_type, form_type, accession, accepted_at_utc,
                filing_date, report_period_end, session_bucket, session_reason,
                primary_document, primary_document_url, filing_index_url, source_url,
                source_hash, is_amendment, amends_accession, ingested_at_utc,
                freshness_status, data_quality_flags
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(event_id) DO NOTHING
            """,
            (
                event.event_id,
                event.schema_version,
                event.symbol,
                event.company_name,
                event.source_type.value,
                event.source_record_id,
                event.event_type.value,
                event.form_type,
                event.accession,
                _iso(event.accepted_at_utc),
                _iso(event.filing_date),
                _iso(event.report_period_end),
                event.session_bucket.value,
                event.session_reason,
                event.primary_document,
                event.primary_document_url,
                event.filing_index_url,
                event.filing_index_url,  # source_url column == the filing index
                event.source_hash,
                1 if event.is_amendment else 0,
                event.amends_accession,
                _iso(event.ingested_at_utc),
                event.freshness.value,
                json.dumps(list(event.data_quality_flags)),
            ),
        )
        inserted = cur.rowcount == 1

        self._conn.executemany(
            "INSERT OR IGNORE INTO text_event_items (accession, item_code) VALUES (?, ?)",
            [(event.accession, code) for code in event.filing_items],
        )
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO text_event_exhibits
                (accession, filename, source_url, sequence, document_type, description)
            VALUES (?,?,?,?,?,?)
            """,
            [
                (
                    event.accession,
                    ex.filename,
                    ex.source_url,
                    ex.sequence,
                    ex.document_type,
                    ex.description,
                )
                for ex in event.exhibits
            ],
        )
        for ev in event.evidence:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO event_evidence
                    (event_id, transform, source_provider, source_record_id, source_url,
                     exact_timestamp, retrieved_at, input_hash, notes)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.event_id,
                    ev.transform,
                    ev.source_provider.value,
                    ev.source_record_id,
                    ev.source_url,
                    _iso(ev.exact_timestamp),
                    _iso(ev.retrieved_at),
                    ev.input_hash,
                    ev.notes,
                ),
            )
        self._conn.commit()
        return inserted

    def upsert_events(self, events: Iterable[TextEvent]) -> int:
        """Bulk helper. Returns the count of fresh inserts."""
        return sum(1 for e in events if self.upsert_event(e))

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def has_event(self, event_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM text_events WHERE event_id = ?", (event_id,)
        )
        return cur.fetchone() is not None

    def get_event(self, event_id: str) -> TextEvent | None:
        cur = self._conn.execute(
            "SELECT * FROM text_events WHERE event_id = ?", (event_id,)
        )
        row = cur.fetchone()
        return self._row_to_event(row) if row else None

    def get_items(self, accession: str) -> list[str]:
        cur = self._conn.execute(
            "SELECT item_code FROM text_event_items WHERE accession = ? ORDER BY item_code",
            (accession,),
        )
        return [r[0] for r in cur.fetchall()]

    def get_exhibits(self, accession: str) -> list[ExhibitRef]:
        cur = self._conn.execute(
            "SELECT filename, source_url, sequence, document_type, description "
            "FROM text_event_exhibits WHERE accession = ? ORDER BY sequence, filename",
            (accession,),
        )
        return [
            ExhibitRef(
                filename=r["filename"],
                source_url=r["source_url"],
                sequence=r["sequence"],
                document_type=r["document_type"],
                description=r["description"],
            )
            for r in cur.fetchall()
        ]

    def get_evidence(self, event_id: str) -> list[EvidenceRecord]:
        cur = self._conn.execute(
            "SELECT * FROM event_evidence WHERE event_id = ? ORDER BY transform", (event_id,)
        )
        out: list[EvidenceRecord] = []
        for r in cur.fetchall():
            out.append(
                EvidenceRecord(
                    source_provider=SourceType(r["source_provider"]),
                    source_record_id=r["source_record_id"],
                    source_url=r["source_url"],
                    exact_timestamp=_parse_dt(r["exact_timestamp"]),
                    retrieved_at=_parse_dt(r["retrieved_at"]),
                    transform=r["transform"],
                    input_hash=r["input_hash"],
                    notes=r["notes"],
                )
            )
        return out

    def query_events(
        self,
        *,
        symbol: str | None = None,
        event_type: EventType | str | None = None,
        form_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        newest_first: bool = True,
    ) -> list[TextEvent]:
        where: list[str] = []
        params: list[object] = []
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())
        if event_type is not None:
            where.append("event_type = ?")
            params.append(
                event_type.value if isinstance(event_type, EventType) else str(event_type)
            )
        if form_type:
            where.append("form_type = ?")
            params.append(form_type)
        if since is not None:
            where.append("accepted_at_utc >= ?")
            params.append(_iso(since))
        if until is not None:
            where.append("accepted_at_utc <= ?")
            params.append(_iso(until))
        sql = "SELECT * FROM text_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY accepted_at_utc " + ("DESC" if newest_first else "ASC")
        sql += ", event_id " + ("DESC" if newest_first else "ASC")
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        cur = self._conn.execute(sql, params)
        return [self._row_to_event(r) for r in cur.fetchall()]

    def count_events(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM text_events").fetchone()[0]

    # ------------------------------------------------------------------
    # source freshness (used by SourceFreshnessTracker)
    # ------------------------------------------------------------------
    def _read_freshness_row(self, source_type: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM source_freshness WHERE source_type = ?", (source_type,)
        ).fetchone()

    def _write_freshness_row(
        self,
        *,
        source_type: str,
        last_poll_attempt_utc: datetime | None,
        last_poll_success_utc: datetime | None,
        latest_source_event_utc: datetime | None,
        consecutive_failures: int,
        status: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO source_freshness (
                source_type, last_poll_attempt_utc, last_poll_success_utc,
                latest_source_event_utc, consecutive_failures, status, updated_at_utc
            ) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(source_type) DO UPDATE SET
                last_poll_attempt_utc   = excluded.last_poll_attempt_utc,
                last_poll_success_utc   = excluded.last_poll_success_utc,
                latest_source_event_utc = excluded.latest_source_event_utc,
                consecutive_failures    = excluded.consecutive_failures,
                status                  = excluded.status,
                updated_at_utc          = excluded.updated_at_utc
            """,
            (
                source_type,
                _iso(last_poll_attempt_utc),
                _iso(last_poll_success_utc),
                _iso(latest_source_event_utc),
                int(consecutive_failures),
                status,
                _iso(datetime.now(timezone.utc)),
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # row hydration
    # ------------------------------------------------------------------
    def _row_to_event(self, row: sqlite3.Row) -> TextEvent:
        accession = row["accession"]
        try:
            flags = tuple(json.loads(row["data_quality_flags"] or "[]"))
        except (ValueError, TypeError):
            flags = ()
        return TextEvent(
            event_id=row["event_id"],
            schema_version=row["schema_version"],
            symbol=row["symbol"],
            company_name=row["company_name"],
            source_type=SourceType(row["source_type"]),
            source_record_id=row["source_record_id"],
            event_type=EventType(row["event_type"]),
            form_type=row["form_type"],
            filing_items=tuple(self.get_items(accession)),
            accession=accession,
            accepted_at_utc=_parse_dt(row["accepted_at_utc"]),
            filing_date=_parse_date(row["filing_date"]),
            report_period_end=_parse_date(row["report_period_end"]),
            session_bucket=SessionBucket(row["session_bucket"]),
            session_reason=row["session_reason"],
            primary_document=row["primary_document"],
            primary_document_url=row["primary_document_url"],
            filing_index_url=row["filing_index_url"],
            exhibits=tuple(self.get_exhibits(accession)),
            is_amendment=bool(row["is_amendment"]),
            amends_accession=row["amends_accession"],
            source_hash=row["source_hash"],
            ingested_at_utc=_parse_dt(row["ingested_at_utc"]),
            freshness=FreshnessStatus(row["freshness_status"]),
            data_quality_flags=flags,
            evidence=tuple(self.get_evidence(row["event_id"])),
        )
