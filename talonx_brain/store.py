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
    horizon      TEXT NOT NULL DEFAULT 'intraday',
    count        INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (date, ticker, category, horizon)
)
"""


class BrainStatsStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Adds `horizon` (Phase 2) to a pre-existing report_counts table
        that predates it. Unlike every other store's idempotent
        ALTER-TABLE-ADD-COLUMN migration, this one REBUILDS the table --
        a plain column add would leave the OLD 3-column PRIMARY KEY
        (date, ticker, category) in place underneath, which would still
        reject two different-horizon rows for the same date/ticker/
        category (a real possibility once a DUAL_HORIZON ticker records
        both an intraday and a long_term report on the same day). Every
        pre-Phase-2 row is 'intraday' by definition (that's all that
        existed), so the backfill is unambiguous."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(report_counts)").fetchall()}
        if "horizon" not in cols:
            self._conn.executescript(
                """
                ALTER TABLE report_counts RENAME TO report_counts_old;
                CREATE TABLE report_counts (
                    date         TEXT NOT NULL,
                    ticker       TEXT NOT NULL,
                    category     TEXT NOT NULL,
                    horizon      TEXT NOT NULL DEFAULT 'intraday',
                    count        INTEGER NOT NULL DEFAULT 0,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (date, ticker, category, horizon)
                );
                INSERT INTO report_counts (date, ticker, category, horizon, count, last_seen_at)
                    SELECT date, ticker, category, 'intraday', count, last_seen_at FROM report_counts_old;
                DROP TABLE report_counts_old;
                """
            )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "BrainStatsStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def record_report(self, ticker: str, category: str, when: datetime, horizon: str = "intraday") -> None:
        date = when.date().isoformat()
        self._conn.execute(
            """
            INSERT INTO report_counts (date, ticker, category, horizon, count, last_seen_at)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(date, ticker, category, horizon) DO UPDATE SET
                count = count + 1,
                last_seen_at = excluded.last_seen_at
            """,
            (date, ticker.upper(), category, horizon, when.isoformat()),
        )
        self._conn.commit()

    def report_counts_for_date(self, date_str: str) -> list[dict]:
        cursor = self._conn.execute(
            "SELECT date, ticker, category, horizon, count, last_seen_at FROM report_counts WHERE date = ? "
            "ORDER BY ticker, category",
            (date_str,),
        )
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
