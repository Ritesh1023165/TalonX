"""
talonx_brain.store
-----------------------
Durable persistence for research-report category counts, backed by
SQLite (stdlib sqlite3 -- no new dependency). Cache-hit/miss/degraded/
LLM-call stats were previously only computable LIVE from Redis pub/sub
messages by dashboard.py's _categorize_report -- in-memory, resets on
restart, and unrecoverable after the fact. This closes that gap so an
EOD report can show "how many LLM calls / cache hits happened today"
without a dashboard process having been running continuously to observe
them.

One table, daily upserted counters keyed (date, ticker, category) --
same shape and rationale as talonx_core/talonx_quant's suppression_counts:
a report is published on essentially every QuantSignal received, so an
EOD report only ever needs "N cache hits today", not an unbounded
per-report log.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS report_counts (
    date         TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    category     TEXT NOT NULL,
    count        INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (date, ticker, category)
)
"""


class BrainStatsStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "BrainStatsStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def record_report(self, ticker: str, category: str, when: datetime) -> None:
        date = when.date().isoformat()
        self._conn.execute(
            """
            INSERT INTO report_counts (date, ticker, category, count, last_seen_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(date, ticker, category) DO UPDATE SET
                count = count + 1,
                last_seen_at = excluded.last_seen_at
            """,
            (date, ticker.upper(), category, when.isoformat()),
        )
        self._conn.commit()

    def report_counts_for_date(self, date_str: str) -> list[dict]:
        cursor = self._conn.execute(
            "SELECT date, ticker, category, count, last_seen_at FROM report_counts WHERE date = ? "
            "ORDER BY ticker, category",
            (date_str,),
        )
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
