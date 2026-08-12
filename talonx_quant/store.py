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
);

-- Event-Driven Earnings Radar: the last successfully-computed factor
-- set per ticker, persisted (not just kept in-memory) so a process
-- restart between a ticker's last real 10-Q ingestion and its next
-- earnings date doesn't silently disable the fast 8-K-triggered
-- republish path (Requirement 7 Stage 1) until the next 10-Q lands.
-- Written on EVERY successful factor computation in
-- fundamental_consumer.py, regardless of whether ROIC/F-Score cleared
-- the publish threshold -- UNDER_PERFORM_REBALANCE needs below-
-- threshold factors to be available too.
CREATE TABLE IF NOT EXISTS latest_fundamental_factors (
    ticker               TEXT PRIMARY KEY,
    fiscal_year          INTEGER NOT NULL,
    roic                 REAL,
    piotroski_f_score    INTEGER,
    fcf_yield            REAL,
    altman_z_score       REAL,
    debt_to_ebitda_proxy REAL,
    computed_at          TEXT NOT NULL
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

    def save_latest_factors(
        self, ticker: str, fiscal_year: int, roic: float | None, piotroski_f_score: int | None,
        fcf_yield: float | None, altman_z_score: float | None, debt_to_ebitda_proxy: float | None,
        computed_at: datetime,
    ) -> None:
        """One row per ticker -- overwrites the prior computation, since
        only the LATEST factors matter for an earnings-triggered
        republish (no history kept here; that's what fiscal_year on the
        republished signal itself communicates downstream)."""
        self._conn.execute(
            """
            INSERT INTO latest_fundamental_factors (
                ticker, fiscal_year, roic, piotroski_f_score, fcf_yield,
                altman_z_score, debt_to_ebitda_proxy, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                fiscal_year = excluded.fiscal_year,
                roic = excluded.roic,
                piotroski_f_score = excluded.piotroski_f_score,
                fcf_yield = excluded.fcf_yield,
                altman_z_score = excluded.altman_z_score,
                debt_to_ebitda_proxy = excluded.debt_to_ebitda_proxy,
                computed_at = excluded.computed_at
            """,
            (
                ticker.upper(), fiscal_year, roic, piotroski_f_score, fcf_yield,
                altman_z_score, debt_to_ebitda_proxy, computed_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_latest_factors(self, ticker: str) -> dict | None:
        cursor = self._conn.execute(
            "SELECT ticker, fiscal_year, roic, piotroski_f_score, fcf_yield, "
            "altman_z_score, debt_to_ebitda_proxy, computed_at "
            "FROM latest_fundamental_factors WHERE ticker = ?",
            (ticker.upper(),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [d[0] for d in cursor.description]
        return dict(zip(columns, row))
