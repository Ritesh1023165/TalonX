"""
talonx_ingest.intelligence.service.checkpoint_store
==================================================
``BackfillCheckpointStore`` — resumable state for the bounded historical
backfill (``BACKFILL_ARCHITECTURE.md`` Phase 5).

Additive table ``intel_backfill_checkpoint`` in the SAME SQLite file the
96A ``EventStore`` uses (``settings.ledger.path``). ``CREATE TABLE IF NOT
EXISTS`` only; no existing table is touched.

One row per ``(symbol, source, form)`` unit of work:

| source              | forms                | meaning                          |
|---------------------|----------------------|----------------------------------|
| ``edgar_submissions`` | ``8-K`` ``10-Q`` ``10-K`` | filing history via submissions feed |
| ``edgar_form4_xml``   | ``4`` (``3`` ``5``)  | per-filing ownership XML          |

Restart contract: a unit with ``completed=1`` is skipped; an incomplete
unit resumes from ``earliest_processed_date`` / ``last_accession``. Progress
is committed after every batch so a kill mid-symbol never loses ground.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from talonx_ingest.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_backfill_checkpoint (
    symbol                  TEXT NOT NULL,
    source                  TEXT NOT NULL,
    form                    TEXT NOT NULL,
    cik                     TEXT,
    history_start           TEXT,           -- bounded lower date for this run
    earliest_processed_date TEXT,           -- oldest filing date handled so far
    latest_processed_date   TEXT,           -- newest filing date handled so far
    last_accession          TEXT,
    filings_seen            INTEGER NOT NULL DEFAULT 0,
    events_written          INTEGER NOT NULL DEFAULT 0,
    completed               INTEGER NOT NULL DEFAULT 0,
    attempts                INTEGER NOT NULL DEFAULT 0,
    last_attempt_utc        TEXT,
    last_success_utc        TEXT,
    error_state             TEXT,
    updated_at_utc          TEXT NOT NULL,
    PRIMARY KEY (symbol, source, form)
);
CREATE INDEX IF NOT EXISTS idx_intel_backfill_completed
    ON intel_backfill_checkpoint (completed);
"""

_SCHEMA_VERSION = 1


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        d = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


@dataclass(frozen=True)
class BackfillCheckpoint:
    symbol: str
    source: str
    form: str
    cik: str | None
    history_start: str | None
    earliest_processed_date: str | None
    latest_processed_date: str | None
    last_accession: str | None
    filings_seen: int
    events_written: int
    completed: bool
    attempts: int
    last_attempt_utc: str | None
    last_success_utc: str | None
    error_state: str | None
    updated_at_utc: str | None


class BackfillCheckpointStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else Path(settings.ledger.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES "
            "('intel_backfill_checkpoint_schema_version', ?) ON CONFLICT(key) DO NOTHING",
            (str(_SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "BackfillCheckpointStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    def get(self, symbol: str, source: str, form: str) -> BackfillCheckpoint | None:
        r = self._conn.execute(
            "SELECT * FROM intel_backfill_checkpoint WHERE symbol=? AND source=? AND form=?",
            (symbol.upper(), source, form),
        ).fetchone()
        return self._row(r) if r else None

    def ensure(
        self,
        symbol: str,
        source: str,
        form: str,
        *,
        cik: str | None = None,
        history_start: date | str | None = None,
    ) -> BackfillCheckpoint:
        existing = self.get(symbol, source, form)
        if existing is not None:
            return existing
        now = _iso(datetime.now(timezone.utc))
        self._conn.execute(
            """
            INSERT INTO intel_backfill_checkpoint
                (symbol, source, form, cik, history_start, updated_at_utc)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(symbol, source, form) DO NOTHING
            """,
            (symbol.upper(), source, form, cik, _iso(history_start), now),
        )
        self._conn.commit()
        return self.get(symbol, source, form)  # type: ignore[return-value]

    def record_attempt(self, symbol: str, source: str, form: str) -> None:
        now = _iso(datetime.now(timezone.utc))
        self._conn.execute(
            """
            UPDATE intel_backfill_checkpoint
               SET attempts = attempts + 1, last_attempt_utc = ?, updated_at_utc = ?
             WHERE symbol=? AND source=? AND form=?
            """,
            (now, now, symbol.upper(), source, form),
        )
        self._conn.commit()

    def record_progress(
        self,
        symbol: str,
        source: str,
        form: str,
        *,
        earliest_processed_date: date | str | None = None,
        latest_processed_date: date | str | None = None,
        last_accession: str | None = None,
        filings_seen_delta: int = 0,
        events_written_delta: int = 0,
        completed: bool | None = None,
        error_state: str | None = None,
        clear_error: bool = False,
    ) -> None:
        now = _iso(datetime.now(timezone.utc))
        cur = self.get(symbol, source, form)
        if cur is None:
            self.ensure(symbol, source, form)
            cur = self.get(symbol, source, form)
        assert cur is not None

        # earliest = min(existing, new); latest = max(existing, new)
        new_earliest = _min_iso(cur.earliest_processed_date, _iso(earliest_processed_date))
        new_latest = _max_iso(cur.latest_processed_date, _iso(latest_processed_date))
        new_completed = cur.completed if completed is None else bool(completed)
        new_error = None if clear_error else (error_state if error_state is not None else cur.error_state)
        last_success = now if (error_state is None) else cur.last_success_utc
        if error_state is not None and not clear_error:
            last_success = cur.last_success_utc

        self._conn.execute(
            """
            UPDATE intel_backfill_checkpoint
               SET earliest_processed_date = ?,
                   latest_processed_date   = ?,
                   last_accession          = COALESCE(?, last_accession),
                   filings_seen            = filings_seen + ?,
                   events_written          = events_written + ?,
                   completed               = ?,
                   error_state             = ?,
                   last_success_utc        = ?,
                   updated_at_utc          = ?
             WHERE symbol=? AND source=? AND form=?
            """,
            (
                new_earliest, new_latest, last_accession,
                int(filings_seen_delta), int(events_written_delta),
                1 if new_completed else 0, new_error, last_success, now,
                symbol.upper(), source, form,
            ),
        )
        self._conn.commit()

    def mark_completed(self, symbol: str, source: str, form: str) -> None:
        self.record_progress(symbol, source, form, completed=True, clear_error=True)

    def mark_error(self, symbol: str, source: str, form: str, error_state: str) -> None:
        self.record_progress(symbol, source, form, error_state=error_state[:500])

    # ------------------------------------------------------------------
    def pending_units(
        self, units: list[tuple[str, str, str]]
    ) -> list[tuple[str, str, str]]:
        """Filter ``(symbol, source, form)`` triples to those not yet
        ``completed`` — the resume set."""
        out = []
        for sym, src, form in units:
            cp = self.get(sym, src, form)
            if cp is None or not cp.completed:
                out.append((sym, src, form))
        return out

    def all(self) -> list[BackfillCheckpoint]:
        rows = self._conn.execute(
            "SELECT * FROM intel_backfill_checkpoint ORDER BY symbol, source, form"
        ).fetchall()
        return [self._row(r) for r in rows]

    def summary(self) -> dict:
        rows = self.all()
        return {
            "units": len(rows),
            "completed": sum(1 for r in rows if r.completed),
            "pending": sum(1 for r in rows if not r.completed),
            "with_error": sum(1 for r in rows if r.error_state),
            "filings_seen": sum(r.filings_seen for r in rows),
            "events_written": sum(r.events_written for r in rows),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _row(r: sqlite3.Row) -> BackfillCheckpoint:
        return BackfillCheckpoint(
            symbol=r["symbol"],
            source=r["source"],
            form=r["form"],
            cik=r["cik"],
            history_start=r["history_start"],
            earliest_processed_date=r["earliest_processed_date"],
            latest_processed_date=r["latest_processed_date"],
            last_accession=r["last_accession"],
            filings_seen=r["filings_seen"],
            events_written=r["events_written"],
            completed=bool(r["completed"]),
            attempts=r["attempts"],
            last_attempt_utc=r["last_attempt_utc"],
            last_success_utc=r["last_success_utc"],
            error_state=r["error_state"],
            updated_at_utc=r["updated_at_utc"],
        )


def _min_iso(a: str | None, b: str | None) -> str | None:
    vals = [x for x in (a, b) if x]
    return min(vals) if vals else None


def _max_iso(a: str | None, b: str | None) -> str | None:
    vals = [x for x in (a, b) if x]
    return max(vals) if vals else None
