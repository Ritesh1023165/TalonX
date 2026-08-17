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
);

-- Buffer persistence: a periodic snapshot of RollingBarBuffer's
-- in-memory content (both the 1-min buffer and the 15-min HTF buffer),
-- so a restart doesn't force every symbol back through a full
-- min_bars_required/htf_sma_period re-warm-up from empty. buffer_type
-- is '1m' or '15m' -- two independent snapshots per symbol, since the
-- two buffers have different sizes, reload rules, and purposes (see
-- QuantScanner._load_buffers_from_store's gap-gating, 1m only).
-- `session` (pre_market/regular/closed, see session.py) was added for
-- Requirement 3's session-aware buffering -- see _migrate_bar_buffer_schema
-- below for how a pre-existing table without this column is handled.
CREATE TABLE IF NOT EXISTS bar_buffer (
    symbol      TEXT NOT NULL,
    buffer_type TEXT NOT NULL,
    ts          TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    session     TEXT,
    PRIMARY KEY (symbol, buffer_type, ts)
);
CREATE INDEX IF NOT EXISTS idx_bar_buffer_symbol_type ON bar_buffer (symbol, buffer_type)
"""


class QuantStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._migrate_bar_buffer_schema()
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _migrate_bar_buffer_schema(self) -> None:
        """bar_buffer gained a `session` column (Requirement 3). Unlike
        talonx_watchlist.store's ALTER-TABLE-ADD-COLUMN migrations, an
        in-place ALTER here would leave every pre-existing row's session
        NULL -- silently defeating the new RTH-only HTF filter for any
        bar checkpointed before this upgrade. bar_buffer is purely a
        checkpoint CACHE of RollingBarBuffer's in-memory state (see
        checkpoint_buffer's own docstring: a full delete-then-reinsert
        every checkpoint interval), so dropping a stale-schema table and
        letting it repopulate from live/pre-seeded data is safe -- it's
        not a real data loss, just a one-time warm-up reset."""
        table_exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bar_buffer'"
        ).fetchone()
        if not table_exists:
            return
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(bar_buffer)").fetchall()}
        if "session" not in cols:
            self._conn.execute("DROP INDEX IF EXISTS idx_bar_buffer_symbol_type")
            self._conn.execute("DROP TABLE IF EXISTS bar_buffer")
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

    def checkpoint_buffer(self, symbol: str, buffer_type: str, bars: list[dict]) -> None:
        """Replaces the persisted snapshot for (symbol, buffer_type) with
        `bars` -- a full overwrite, not an incremental sync. The in-memory
        RollingBarBuffer this mirrors is itself bounded (a deque with
        maxlen) and small (<=210 rows), so a full rewrite each checkpoint
        is cheap and can never accumulate rows the live buffer has
        already evicted."""
        symbol = symbol.upper()
        self._conn.execute(
            "DELETE FROM bar_buffer WHERE symbol = ? AND buffer_type = ?", (symbol, buffer_type)
        )
        self._conn.executemany(
            "INSERT INTO bar_buffer (symbol, buffer_type, ts, open, high, low, close, volume, session) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    symbol, buffer_type, bar["timestamp"].isoformat(),
                    bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"],
                    bar.get("session"),
                )
                for bar in bars
            ],
        )
        self._conn.commit()

    def load_buffer(self, symbol: str, buffer_type: str) -> list[dict]:
        """Returns bars in chronological order, `timestamp` as the raw
        ISO string as stored -- the caller (QuantScanner) parses it back
        into a datetime, same "this store doesn't know consumer.py's
        types" boundary every other read method here keeps."""
        cursor = self._conn.execute(
            "SELECT ts, open, high, low, close, volume, session FROM bar_buffer "
            "WHERE symbol = ? AND buffer_type = ? ORDER BY ts",
            (symbol.upper(), buffer_type),
        )
        return [
            {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v, "session": s}
            for ts, o, h, l, c, v, s in cursor.fetchall()
        ]

    def buffered_symbols(self, buffer_type: str) -> list[str]:
        cursor = self._conn.execute(
            "SELECT DISTINCT symbol FROM bar_buffer WHERE buffer_type = ? ORDER BY symbol",
            (buffer_type,),
        )
        return [row[0] for row in cursor.fetchall()]
