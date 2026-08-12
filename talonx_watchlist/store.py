"""
talonx_watchlist.store
---------------------------
The ticker watchlist: which symbols the running pipeline should be
streaming market data (and periodically ingesting filings/news) for.

SQLite (stdlib, no new dependency), same choice talonx_core.store and
talonx_dispatch.store make for their own local state. TWO SEPARATE
PROCESSES share this file -- run_talonx.py (reads, to decide what to
stream) and the Streamlit dashboard (reads AND writes, via the add/remove
UI) -- so this follows talonx_dispatch.store's precedent exactly: WAL
journal mode for smoother concurrent read-while-write, and
check_same_thread=False, since a writer living inside Streamlit's
per-session execution model needs that same relaxation app.py's own
audit-store connection already requires (see talonx_dispatch/store.py's
docstring for why).

One row per ticker, no history -- add/remove are the only two operations
that matter, there's nothing here that benefits from being an append-only
log. `status` ('active'/'paused') lets a ticker stop being streamed/
ingested WITHOUT losing its row -- pausing is a plain UPDATE, not a
delete+re-add, so name/exchange/added_at survive a pause/resume cycle.

Schema evolved after this table already had real, deployed rows (a user's
actual watchlist.db) -- __init__ runs an idempotent PRAGMA-table_info-
guarded ALTER TABLE migration rather than assuming a fresh CREATE TABLE
is enough, so an existing file with only the original (symbol, name,
added_at) columns upgrades in place instead of erroring.

check_same_thread=False only disables Python's same-thread ASSERTION, not
actual thread-safety -- app.py caches this store via `@st.cache_resource`
and Streamlit can run more than one session's script concurrently on
different threads, so a plain `threading.Lock` around every public
method's body makes each call atomic with respect to the others (see
talonx_dispatch/store.py's docstring, which hit a real crash from this
exact gap before this store got the same fix preemptively).
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickers (
    symbol                              TEXT PRIMARY KEY,
    name                                TEXT NOT NULL,
    exchange                            TEXT NOT NULL DEFAULT '',
    status                              TEXT NOT NULL DEFAULT 'active',
    paper_trading_enabled               INTEGER NOT NULL DEFAULT 0,
    paper_trading_enabled_long_term     INTEGER NOT NULL DEFAULT 0,
    strategy_horizon                    TEXT NOT NULL DEFAULT 'INTRADAY',
    added_at                            TEXT NOT NULL
);

-- Event-Driven Earnings Radar: one row per LONG_TERM/DUAL_HORIZON ticker's
-- NEXT known earnings date, kept here rather than in a talonx_ingest ledger
-- since this table is per-ticker control-plane METADATA, the same domain
-- `tickers` above already owns -- other modules (talonx_paper, talonx_dispatch)
-- already depend on this store directly rather than through a Redis wire
-- contract, same precedent this table's own additions follow.
CREATE TABLE IF NOT EXISTS upcoming_earnings (
    ticker              TEXT PRIMARY KEY,
    earnings_date       TEXT NOT NULL,
    session             TEXT NOT NULL DEFAULT 'UNSPECIFIED',
    reporting_period    TEXT NOT NULL DEFAULT '',
    heads_up_sent       INTEGER NOT NULL DEFAULT 0,
    last_updated        TEXT NOT NULL
)
"""

_VALID_HORIZONS = ("INTRADAY", "LONG_TERM", "DUAL_HORIZON")


class TickerWatchlistStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # executescript(), not execute() -- _SCHEMA now holds TWO CREATE
        # TABLE statements (tickers, upcoming_earnings); execute() only
        # ever runs a single statement. Same executescript() choice
        # talonx_dispatch/store.py already makes for its own multi-table
        # schema string.
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()
        self._lock = threading.Lock()

    def _migrate(self) -> None:
        """Adds columns introduced after this table's first release, if a
        pre-existing file doesn't have them yet. Safe to run every startup
        -- each ALTER is guarded by a check against the current columns."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(tickers)").fetchall()}
        if "exchange" not in cols:
            self._conn.execute("ALTER TABLE tickers ADD COLUMN exchange TEXT NOT NULL DEFAULT ''")
        if "status" not in cols:
            self._conn.execute("ALTER TABLE tickers ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        if "paper_trading_enabled" not in cols:
            self._conn.execute(
                "ALTER TABLE tickers ADD COLUMN paper_trading_enabled INTEGER NOT NULL DEFAULT 0"
            )
        if "paper_trading_enabled_long_term" not in cols:
            self._conn.execute(
                "ALTER TABLE tickers ADD COLUMN paper_trading_enabled_long_term INTEGER NOT NULL DEFAULT 0"
            )
        if "strategy_horizon" not in cols:
            self._conn.execute(
                "ALTER TABLE tickers ADD COLUMN strategy_horizon TEXT NOT NULL DEFAULT 'INTRADAY'"
            )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TickerWatchlistStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def list_tickers(self) -> list[dict]:
        """All tracked tickers, regardless of status -- the UI's data
        source (it needs to show paused tickers too, not just active ones)."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT symbol, name, exchange, status, paper_trading_enabled, "
                "paper_trading_enabled_long_term, strategy_horizon, added_at "
                "FROM tickers ORDER BY symbol"
            )
            return [
                {
                    "symbol": symbol, "name": name, "exchange": exchange, "status": status,
                    "paper_trading_enabled": bool(paper_trading_enabled),
                    "paper_trading_enabled_long_term": bool(paper_trading_enabled_long_term),
                    "strategy_horizon": strategy_horizon, "added_at": added_at,
                }
                for symbol, name, exchange, status, paper_trading_enabled,
                    paper_trading_enabled_long_term, strategy_horizon, added_at
                in cursor.fetchall()
            ]

    def get_ticker(self, symbol: str) -> dict | None:
        """Single-ticker lookup, None if untracked -- e.g. talonx_dispatch's
        Telegram formatter needs one ticker's company name without pulling
        the whole watchlist."""
        with self._lock:
            row = self._conn.execute(
                "SELECT symbol, name, exchange, status, paper_trading_enabled, "
                "paper_trading_enabled_long_term, strategy_horizon, added_at "
                "FROM tickers WHERE symbol = ?",
                (symbol.strip().upper(),),
            ).fetchone()
        if row is None:
            return None
        (symbol, name, exchange, status, paper_trading_enabled,
            paper_trading_enabled_long_term, strategy_horizon, added_at) = row
        return {
            "symbol": symbol, "name": name, "exchange": exchange, "status": status,
            "paper_trading_enabled": bool(paper_trading_enabled),
            "paper_trading_enabled_long_term": bool(paper_trading_enabled_long_term),
            "strategy_horizon": strategy_horizon, "added_at": added_at,
        }

    def list_symbols(self) -> list[str]:
        """All tracked symbols, regardless of status."""
        return [row["symbol"] for row in self.list_tickers()]

    def list_active_symbols(self) -> list[str]:
        """Only symbols with status='active' -- what market data streaming
        and periodic ingestion should actually process. A paused ticker
        keeps its row (name/exchange/added_at) but drops out of this list."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT symbol FROM tickers WHERE status = 'active' ORDER BY symbol"
            )
            return [row[0] for row in cursor.fetchall()]

    def add_ticker(
        self, symbol: str, name: str, exchange: str = "", status: str = "active",
        strategy_horizon: str = "INTRADAY",
    ) -> None:
        symbol = symbol.strip().upper()
        name = name.strip()
        exchange = exchange.strip()
        if not symbol:
            raise ValueError("Ticker symbol cannot be empty")
        if status not in ("active", "paused"):
            raise ValueError(f"Invalid status: {status!r}")
        if strategy_horizon not in _VALID_HORIZONS:
            raise ValueError(f"Invalid strategy_horizon: {strategy_horizon!r}")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO tickers (symbol, name, exchange, status, strategy_horizon, added_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET name = excluded.name, exchange = excluded.exchange
                """,
                (
                    symbol, name or symbol, exchange, status, strategy_horizon,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()

    def remove_ticker(self, symbol: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM tickers WHERE symbol = ?", (symbol.strip().upper(),)
            )
            self._conn.commit()

    def pause_ticker(self, symbol: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tickers SET status = 'paused' WHERE symbol = ?", (symbol.strip().upper(),)
            )
            self._conn.commit()

    def resume_ticker(self, symbol: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tickers SET status = 'active' WHERE symbol = ?", (symbol.strip().upper(),)
            )
            self._conn.commit()

    def set_paper_trading(self, symbol: str, enabled: bool) -> None:
        """The INTRADAY 'configure which ticker can be used [for paper
        trading]' control -- talonx_paper.consumer.PaperTradingEngine
        checks list_paper_trading_symbols() before ever deciding a trade
        for a ticker. Independent of set_paper_trading_long_term() below
        -- a DUAL_HORIZON ticker can have one enabled without the other,
        since the two engines trade against separate cash pools/positions
        (see talonx_paper/store.py)."""
        with self._lock:
            self._conn.execute(
                "UPDATE tickers SET paper_trading_enabled = ? WHERE symbol = ?",
                (1 if enabled else 0, symbol.strip().upper()),
            )
            self._conn.commit()

    def list_paper_trading_symbols(self) -> list[str]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT symbol FROM tickers WHERE paper_trading_enabled = 1 ORDER BY symbol"
            )
            return [row[0] for row in cursor.fetchall()]

    def set_paper_trading_long_term(self, symbol: str, enabled: bool) -> None:
        """LONG_TERM sibling to set_paper_trading() above -- a SEPARATE
        flag, not a re-use of the intraday one, so a DUAL_HORIZON ticker's
        two paper-trading engines can be toggled independently.
        talonx_paper.consumer.LongTermPaperEngine checks
        list_paper_trading_long_term_symbols() before ever deciding a
        trade for a ticker."""
        with self._lock:
            self._conn.execute(
                "UPDATE tickers SET paper_trading_enabled_long_term = ? WHERE symbol = ?",
                (1 if enabled else 0, symbol.strip().upper()),
            )
            self._conn.commit()

    def list_paper_trading_long_term_symbols(self) -> list[str]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT symbol FROM tickers WHERE paper_trading_enabled_long_term = 1 ORDER BY symbol"
            )
            return [row[0] for row in cursor.fetchall()]

    def set_strategy_horizon(self, symbol: str, horizon: str) -> None:
        """Phase 2's per-ticker routing control: which of the intraday
        technical pipeline, the long-term fundamentals pipeline, or both,
        this ticker feeds. Every module that routes on horizon (market
        data cadence, talonx_quant's two scanners, talonx_ingest's
        filing-text vs. financials paths) reads this via list_by_horizon
        rather than caching it locally, so a horizon change here takes
        effect without restarting backend services."""
        if horizon not in _VALID_HORIZONS:
            raise ValueError(f"Invalid strategy_horizon: {horizon!r}")
        with self._lock:
            self._conn.execute(
                "UPDATE tickers SET strategy_horizon = ? WHERE symbol = ?",
                (horizon, symbol.strip().upper()),
            )
            self._conn.commit()

    def list_by_horizon(self, horizon: str) -> list[str]:
        """Symbols tagged exactly `horizon`, PLUS any DUAL_HORIZON ticker
        (which feeds both pipelines) -- so calling this with "INTRADAY"
        and "LONG_TERM" together always covers every DUAL_HORIZON symbol
        twice, once per pipeline, never zero times. Regardless of status
        ('active'/'paused') -- same "list_tickers shows everything,
        list_active_symbols is the filtered one" split this store already
        uses elsewhere; callers that also care about active/paused
        combine this with list_active_symbols()."""
        if horizon not in _VALID_HORIZONS:
            raise ValueError(f"Invalid strategy_horizon: {horizon!r}")
        with self._lock:
            if horizon == "DUAL_HORIZON":
                cursor = self._conn.execute(
                    "SELECT symbol FROM tickers WHERE strategy_horizon = 'DUAL_HORIZON' ORDER BY symbol"
                )
            else:
                cursor = self._conn.execute(
                    "SELECT symbol FROM tickers WHERE strategy_horizon = ? OR strategy_horizon = 'DUAL_HORIZON' "
                    "ORDER BY symbol",
                    (horizon,),
                )
            return [row[0] for row in cursor.fetchall()]

    def ensure_seeded(self, default_symbol: str, default_name: str, default_exchange: str = "") -> bool:
        """
        Seeds the watchlist with one default ticker, but ONLY if the table
        is currently empty -- meant to cover the fresh-install case (no
        watchlist.db yet, or one that's never had a row). If a user later
        removes every ticker on purpose and restarts the app, this will
        reseed the default rather than leaving it empty; accepted as the
        simplest faithful reading of "fresh start defaults to one ticker."
        Returns True if it seeded, False if the watchlist already had rows.
        """
        if self.list_tickers():
            return False
        self.add_ticker(default_symbol, default_name, default_exchange)
        return True

    # ------------------------------------------------------------------
    # Event-Driven Earnings Radar -- upcoming_earnings
    # ------------------------------------------------------------------

    def upsert_upcoming_earnings(
        self, ticker: str, earnings_date: str, session: str = "UNSPECIFIED", reporting_period: str = "",
    ) -> None:
        """One row per ticker -- a fresh sync overwrites the prior date
        rather than appending, since only the NEXT known earnings date
        matters (no history kept here). Resets heads_up_sent back to 0
        whenever the date itself actually changes (a rescheduled report
        needs its own T-48h alert), but leaves it alone on a no-op
        re-sync of the SAME date -- see the ON CONFLICT clause below."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO upcoming_earnings (ticker, earnings_date, session, reporting_period, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    earnings_date = excluded.earnings_date,
                    session = excluded.session,
                    reporting_period = excluded.reporting_period,
                    last_updated = excluded.last_updated,
                    heads_up_sent = CASE
                        WHEN upcoming_earnings.earnings_date != excluded.earnings_date THEN 0
                        ELSE upcoming_earnings.heads_up_sent
                    END
                """,
                (
                    ticker.strip().upper(), earnings_date, session, reporting_period,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()

    def get_upcoming_earnings(self, ticker: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT ticker, earnings_date, session, reporting_period, heads_up_sent, last_updated "
                "FROM upcoming_earnings WHERE ticker = ?",
                (ticker.strip().upper(),),
            ).fetchone()
        if row is None:
            return None
        ticker, earnings_date, session, reporting_period, heads_up_sent, last_updated = row
        return {
            "ticker": ticker, "earnings_date": earnings_date, "session": session,
            "reporting_period": reporting_period, "heads_up_sent": bool(heads_up_sent),
            "last_updated": last_updated,
        }

    def list_upcoming_earnings(self) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT ticker, earnings_date, session, reporting_period, heads_up_sent, last_updated "
                "FROM upcoming_earnings ORDER BY earnings_date"
            )
            return [
                {
                    "ticker": ticker, "earnings_date": earnings_date, "session": session,
                    "reporting_period": reporting_period, "heads_up_sent": bool(heads_up_sent),
                    "last_updated": last_updated,
                }
                for ticker, earnings_date, session, reporting_period, heads_up_sent, last_updated
                in cursor.fetchall()
            ]

    def mark_heads_up_sent(self, ticker: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE upcoming_earnings SET heads_up_sent = 1 WHERE ticker = ?",
                (ticker.strip().upper(),),
            )
            self._conn.commit()
