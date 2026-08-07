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

from talonx_core.schemas import QuantSignal, ResearchReport
from talonx_core.state import TickerCorrelator

logger = logging.getLogger("talonx_core.store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticker_state (
    ticker         TEXT PRIMARY KEY,
    signal_json    TEXT,
    signal_at      TEXT,
    report_json    TEXT,
    report_at      TEXT,
    last_alert_at  TEXT
)
"""


class TickerStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

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

    def save_alert_time(self, ticker: str, when: datetime) -> None:
        self._conn.execute(
            """
            INSERT INTO ticker_state (ticker, last_alert_at)
            VALUES (?, ?)
            ON CONFLICT(ticker) DO UPDATE SET last_alert_at = excluded.last_alert_at
            """,
            (ticker.upper(), when.isoformat()),
        )
        self._conn.commit()

    def load_into(self, correlator: TickerCorrelator) -> int:
        """
        Rehydrates a TickerCorrelator from disk -- called once at startup.
        Returns how many tickers had persisted state to load. A row with
        only a signal (or only a report) is loaded partially, same as it
        would exist in memory if the process had never restarted.
        """
        cursor = self._conn.execute(
            "SELECT ticker, signal_json, signal_at, report_json, report_at, last_alert_at "
            "FROM ticker_state"
        )
        rows = cursor.fetchall()
        for ticker, signal_json, signal_at, report_json, report_at, last_alert_at in rows:
            state = correlator.get_or_create(ticker)
            if signal_json:
                state.latest_signal = QuantSignal.model_validate_json(signal_json)
                state.latest_signal_at = datetime.fromisoformat(signal_at)
            if report_json:
                state.latest_report = ResearchReport.model_validate_json(report_json)
                state.latest_report_at = datetime.fromisoformat(report_at)
            if last_alert_at:
                state.last_alert_at = datetime.fromisoformat(last_alert_at)
        if rows:
            logger.info("Rehydrated %d ticker(s) from %s", len(rows), self.path)
        return len(rows)
