"""
talonx_quant.store
----------------------
Durable persistence for signal-suppression counts, backed by SQLite
(stdlib sqlite3 -- no new dependency, same choice every other local
store in this project makes). This module previously had no store.py
at all: cooldown/throttle suppression counts (consumer.py's
_signals_suppressed_cooldown/_throttle) were in-memory ints only,
reset on every restart and invisible to anything outside the process.

One table, daily upserted counters keyed (date, ticker, reason) -- same
shape and rationale as talonx_core.store's suppression_counts: a
cooldown/throttle event can suppress several signals across a single
flush, and an EOD report only ever needs "suppressed N times today",
not an unbounded per-event log.

Pure stdlib sqlite3, no cross-module imports -- keeps this module
self-contained at the code level, same convention config.py already
documents.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS suppression_counts (
    date         TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    reason       TEXT NOT NULL,
    count        INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (date, ticker, reason)
)
"""


class QuantStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "QuantStateStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def record_suppressed(self, ticker: str, reason: str, count: int, when: datetime) -> None:
        """`count` is not always 1 -- a single cooldown check can
        suppress several candidate signals at once, and a single
        throttle flush can drop several for the same ticker."""
        date = when.date().isoformat()
        self._conn.execute(
            """
            INSERT INTO suppression_counts (date, ticker, reason, count, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date, ticker, reason) DO UPDATE SET
                count = count + excluded.count,
                last_seen_at = excluded.last_seen_at
            """,
            (date, ticker.upper(), reason, count, when.isoformat()),
        )
        self._conn.commit()

    def suppression_counts_for_date(self, date_str: str) -> list[dict]:
        cursor = self._conn.execute(
            "SELECT date, ticker, reason, count, last_seen_at FROM suppression_counts WHERE date = ? "
            "ORDER BY ticker, reason",
            (date_str,),
        )
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
