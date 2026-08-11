"""
talonx_core.store
----------------------
Durable persistence for TickerCorrelator state, backed by SQLite (stdlib
sqlite3 -- no new dependency, same choice talonx_ingest.storage.ledger
makes for its own local state). Deliberately NOT shared code with that
ledger -- talonx_core stays self-contained at the code level (see
config.py) -- but it follows the same conventions: one connection per
process, `check_same_thread` left at its default (True), so calls are
made synchronously from the event loop thread rather than offloaded via
asyncio.to_thread (which would hand the connection to a DIFFERENT worker
thread and break that check). These are fast, local, single-row writes,
so blocking the loop for them is negligible -- same tradeoff the ledger
already makes.

One row per ticker, upserted on every update -- this mirrors TickerState
exactly (only the FRESHEST signal/report/alert-time per ticker ever
matters, never history), so there's no append-only log to prune or
reconcile. Each upsert touches only its own columns (via SQLite's
`ON CONFLICT ... DO UPDATE SET`, not `INSERT OR REPLACE`, which would
blow away the other half of the row) -- saving a signal must never erase
an already-stored report for that ticker, or vice versa.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from talonx_core.schemas import AlertAction, QuantSignal, ResearchReport
from talonx_core.state import TickerCorrelator

logger = logging.getLogger("talonx_core.store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticker_state (
    ticker              TEXT PRIMARY KEY,
    signal_json         TEXT,
    signal_at           TEXT,
    report_json         TEXT,
    report_at           TEXT,
    last_alert_at       TEXT,
    last_alert_action   TEXT,
    last_alert_price    REAL
);

CREATE TABLE IF NOT EXISTS suppression_counts (
    date         TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    reason       TEXT NOT NULL,
    count        INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (date, ticker, reason)
)
"""


class TickerStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Adds columns introduced after this table's first release, if a
        pre-existing file doesn't have them yet -- same idempotent
        PRAGMA-table_info-guarded ALTER TABLE pattern as
        talonx_watchlist/store.py, safe to run every startup."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(ticker_state)").fetchall()}
        if "last_alert_action" not in cols:
            self._conn.execute("ALTER TABLE ticker_state ADD COLUMN last_alert_action TEXT")
        if "last_alert_price" not in cols:
            self._conn.execute("ALTER TABLE ticker_state ADD COLUMN last_alert_price REAL")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TickerStateStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def save_signal(self, ticker: str, signal: QuantSignal, received_at: datetime) -> None:
        self._conn.execute(
            """
            INSERT INTO ticker_state (ticker, signal_json, signal_at)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                signal_json = excluded.signal_json,
                signal_at = excluded.signal_at
            """,
            (ticker.upper(), signal.model_dump_json(), received_at.isoformat()),
        )
        self._conn.commit()

    def save_report(self, ticker: str, report: ResearchReport, received_at: datetime) -> None:
        self._conn.execute(
            """
            INSERT INTO ticker_state (ticker, report_json, report_at)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                report_json = excluded.report_json,
                report_at = excluded.report_at
            """,
            (ticker.upper(), report.model_dump_json(), received_at.isoformat()),
        )
        self._conn.commit()

    def save_alert(
        self, ticker: str, when: datetime, action: AlertAction, price: float
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO ticker_state (ticker, last_alert_at, last_alert_action, last_alert_price)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                last_alert_at = excluded.last_alert_at,
                last_alert_action = excluded.last_alert_action,
                last_alert_price = excluded.last_alert_price
            """,
            (ticker.upper(), when.isoformat(), action.value, price),
        )
        self._conn.commit()

    def record_suppressed(self, ticker: str, reason: str, when: datetime) -> None:
        """Daily upserted counter, NOT one row per event -- evaluate()
        can be called on every single signal/report tick for a ticker
        stuck in one suppressed state (e.g. a sustained cooldown), and an
        EOD report only ever needs "suppressed N times today by reason
        X" aggregated, not an unbounded event log. Bucketed by `when`'s
        UTC calendar date, matching every other timestamp in this store
        (UTC ISO strings)."""
        date = when.date().isoformat()
        self._conn.execute(
            """
            INSERT INTO suppression_counts (date, ticker, reason, count, last_seen_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(date, ticker, reason) DO UPDATE SET
                count = count + 1,
                last_seen_at = excluded.last_seen_at
            """,
            (date, ticker.upper(), reason, when.isoformat()),
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

    def load_into(self, correlator: TickerCorrelator) -> int:
        """
        Rehydrates a TickerCorrelator from disk -- called once at startup.
        Returns how many tickers had persisted state to load. A row with
        only a signal (or only a report) is loaded partially, same as it
        would exist in memory if the process had never restarted.
        """
        cursor = self._conn.execute(
            "SELECT ticker, signal_json, signal_at, report_json, report_at, "
            "last_alert_at, last_alert_action, last_alert_price FROM ticker_state"
        )
        rows = cursor.fetchall()
        for (
            ticker, signal_json, signal_at, report_json, report_at,
            last_alert_at, last_alert_action, last_alert_price,
        ) in rows:
            state = correlator.get_or_create(ticker)
            if signal_json:
                state.latest_signal = QuantSignal.model_validate_json(signal_json)
                state.latest_signal_at = datetime.fromisoformat(signal_at)
            if report_json:
                state.latest_report = ResearchReport.model_validate_json(report_json)
                state.latest_report_at = datetime.fromisoformat(report_at)
            if last_alert_at:
                state.last_alert_at = datetime.fromisoformat(last_alert_at)
            if last_alert_action:
                state.last_alert_action = AlertAction(last_alert_action)
            if last_alert_price is not None:
                state.last_alert_price = last_alert_price
        if rows:
            logger.info("Rehydrated %d ticker(s) from %s", len(rows), self.path)
        return len(rows)
