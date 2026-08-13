"""
talonx_paper.store
-----------------------
SQLite-backed paper trading ledger (stdlib sqlite3, no new dependency --
same choice every other store in this project makes; a Postgres ledger
was considered and deliberately dropped in favor of this, to match
talonx_core.store/talonx_dispatch.store/talonx_watchlist.store exactly
rather than introducing a second database technology for one module).

Four tables:
  - portfolio_state: single row (id=1) -- cash, allocation setting,
    cumulative realized PnL, win/loss counts. total_realized_pnl_pct and
    win_rate_pct are DERIVED on read (get_portfolio_summary), not stored,
    so they can never drift from the numbers they're computed from.
  - positions: one row per OPEN position, keyed by ticker. A ticker's
    ABSENCE from this table IS "flat" -- no separate status column
    needed, mirrors talonx_watchlist's "row presence is the state" style
    where that's simpler than an extra flag.
  - trade_history: append-only log of every EXECUTED (non-ignored)
    trade -- powers the dashboard's closed-trades table, CSV export, and
    equity-curve chart.
  - latest_prices: one row per ticker, updated on every market tick this
    module sees. Exists because the Streamlit dashboard is a SEPARATE
    process with no access to this module's in-memory price cache, and
    needs a durable, cross-process-readable source for marking open
    positions to market.
  - ignored_decisions: append-only log of every alert that arrived but
    did NOT result in a trade (NO_ACTIVE_POSITION, POSITION_ALREADY_OPEN,
    INSUFFICIENT_CASH, DEGRADED_NOT_TRADABLE). Previously this was only a
    logger.info/.warning line in consumer.py -- unrecoverable after the
    fact, which is exactly what made "why didn't ticker X trade today"
    require a manual log/CSV analysis instead of a query. Powers the EOD
    report's per-ticker "ignored" breakdown.

Same threading.Lock-around-every-public-method pattern every store built
this session uses (WAL mode + check_same_thread=False, since app.py
caches this via @st.cache_resource and Streamlit can run a cached
resource across threads).

execute_buy/execute_sell are OPERATION-shaped, not raw CRUD -- each one
updates positions + portfolio_state + inserts into trade_history
atomically (one lock, one commit), so callers (consumer.py) never have
to hand-coordinate a multi-table write themselves.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from talonx_paper.engine import calculate_average_cost_basis, calculate_partial_sell_pnl, calculate_sell_pnl
from talonx_paper.schemas import AlertAction, LongTermOrderType, LongTermTradeExecution, OrderType, PaperTradeExecution

_SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_state (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    initial_balance         REAL NOT NULL,
    current_cash            REAL NOT NULL,
    trade_allocation_usd    REAL NOT NULL,
    total_realized_pnl_usd  REAL NOT NULL DEFAULT 0,
    win_count               INTEGER NOT NULL DEFAULT 0,
    loss_count              INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS positions (
    ticker          TEXT PRIMARY KEY,
    shares          REAL NOT NULL,
    entry_price     REAL NOT NULL,
    entry_timestamp TEXT NOT NULL,
    cost_basis      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_history (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                  TEXT NOT NULL,
    order_type              TEXT NOT NULL,
    execution_price         REAL NOT NULL,
    shares                  REAL NOT NULL,
    position_cost           REAL NOT NULL,
    entry_price             REAL,
    realized_pnl_usd        REAL,
    realized_pnl_pct        REAL,
    portfolio_cash_after    REAL NOT NULL,
    timestamp               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trade_history_timestamp ON trade_history (timestamp);

CREATE TABLE IF NOT EXISTS latest_prices (
    ticker      TEXT PRIMARY KEY,
    price       REAL NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ignored_decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT NOT NULL,
    reason              TEXT NOT NULL,
    triggering_action   TEXT NOT NULL,
    price               REAL NOT NULL,
    horizon             TEXT NOT NULL DEFAULT 'intraday',
    timestamp           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ignored_decisions_timestamp ON ignored_decisions (timestamp);

-- ------------------------------------------------------------------
-- Phase 2 LONG_TERM path -- a SEPARATE cash pool/ledger, not a horizon
-- column threaded through the tables above: portfolio_state's PK is a
-- literal singleton row (CHECK id=1), which can't represent two
-- independent cash pools, and positions' one-row-per-ticker PK can't
-- hold a simultaneous intraday AND long-term position for the same
-- DUAL_HORIZON ticker. Shares latest_prices above (a price is a price
-- regardless of horizon).
-- ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS long_term_portfolio_state (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    initial_balance         REAL NOT NULL,
    current_cash            REAL NOT NULL,
    dca_contribution_usd    REAL NOT NULL,
    total_realized_pnl_usd  REAL NOT NULL DEFAULT 0,
    win_count               INTEGER NOT NULL DEFAULT 0,
    loss_count              INTEGER NOT NULL DEFAULT 0
);

-- One row per OPEN long-term position, keyed by ticker (same "absence
-- means flat" convention as `positions` above). Unlike the intraday
-- table, avg_cost_basis is a WEIGHTED AVERAGE across possibly-many DCA
-- buys, not a single-lot entry_price -- and total_contributed_usd is a
-- LIFETIME cumulative counter (every dollar ever put in, initial buy +
-- every DCA add), never reduced by a partial sell -- it answers "how
-- much have I actually invested," a different question from "what's my
-- current cost basis."
CREATE TABLE IF NOT EXISTS long_term_positions (
    ticker                  TEXT PRIMARY KEY,
    total_shares            REAL NOT NULL,
    avg_cost_basis          REAL NOT NULL,
    first_entry_at          TEXT NOT NULL,
    total_contributed_usd   REAL NOT NULL
);

-- Append-only, ALL long-term order types (BUY/SELL/DCA_CONTRIBUTION) in
-- one unified ledger -- unlike the intraday split of trade_history vs.
-- a separate contributions log, "total DCA contributed" is just
-- SUM(contribution_cost) WHERE order_type='DCA_CONTRIBUTION' against
-- this one table, so a second redundant table isn't needed.
CREATE TABLE IF NOT EXISTS long_term_trade_history (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                  TEXT NOT NULL,
    order_type              TEXT NOT NULL,
    execution_price         REAL NOT NULL,
    shares                  REAL NOT NULL,
    contribution_cost       REAL NOT NULL,
    avg_cost_basis_after    REAL,
    total_shares_after      REAL,
    realized_pnl_usd        REAL,
    realized_pnl_pct        REAL,
    holding_period_days     INTEGER,
    portfolio_cash_after    REAL NOT NULL,
    triggering_action       TEXT NOT NULL,
    timestamp               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lt_trade_history_timestamp ON long_term_trade_history (timestamp);
"""


class PaperTradingStore:
    def __init__(
        self,
        path: str | Path,
        default_initial_balance: float = 10000.0,
        default_trade_allocation_usd: float = 2500.0,
        default_long_term_initial_balance: float = 20000.0,
        default_dca_contribution_usd: float = 500.0,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()
        self._lock = threading.Lock()
        self._ensure_portfolio_row(default_initial_balance, default_trade_allocation_usd)
        self._ensure_long_term_portfolio_row(default_long_term_initial_balance, default_dca_contribution_usd)

    def _migrate(self) -> None:
        """Adds `horizon` (Phase 2) to a pre-existing ignored_decisions
        table that predates it -- plain ALTER TABLE ADD COLUMN is safe
        here (unlike talonx_brain/talonx_core's report_counts/
        suppression_counts tables), since this table's PK is just an
        AUTOINCREMENT id, not a composite key that a horizon dimension
        would need to widen."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(ignored_decisions)").fetchall()}
        if "horizon" not in cols:
            self._conn.execute(
                "ALTER TABLE ignored_decisions ADD COLUMN horizon TEXT NOT NULL DEFAULT 'intraday'"
            )

    def _ensure_portfolio_row(self, initial_balance: float, trade_allocation_usd: float) -> None:
        with self._lock:
            row = self._conn.execute("SELECT id FROM portfolio_state WHERE id = 1").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO portfolio_state (id, initial_balance, current_cash, trade_allocation_usd) "
                    "VALUES (1, ?, ?, ?)",
                    (initial_balance, initial_balance, trade_allocation_usd),
                )
                self._conn.commit()

    def _ensure_long_term_portfolio_row(self, initial_balance: float, dca_contribution_usd: float) -> None:
        with self._lock:
            row = self._conn.execute("SELECT id FROM long_term_portfolio_state WHERE id = 1").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO long_term_portfolio_state (id, initial_balance, current_cash, dca_contribution_usd) "
                    "VALUES (1, ?, ?, ?)",
                    (initial_balance, initial_balance, dca_contribution_usd),
                )
                self._conn.commit()

    def checkpoint(self) -> None:
        """Forces a WAL checkpoint (TRUNCATE mode -- also shrinks the
        -wal file back down, not just flushes it). SQLite's automatic
        "PASSIVE" checkpoint (the default, triggered at ~1000 WAL pages)
        silently SKIPS itself if any other connection has a read
        transaction open at that moment -- harmless occasionally, but
        this store's update_latest_price() commits on every single
        market tick across every tracked ticker, and a long-lived reader
        polling on a short interval (talonx_dispatch/app.py's Streamlit
        autorefresh, in another PROCESS -- a threading.Lock here doesn't
        apply across processes) can end up "in the way" often enough
        that the WAL never actually gets checkpointed, growing
        unbounded for as long as the process runs. Every read against a
        large uncheckpointed WAL gets progressively slower (SQLite has
        to reconstruct the current page state by scanning the whole
        WAL), which is what actually made the dashboard "hang" over a
        session -- not query complexity, not data volume (row counts
        stay tiny; this is write CHURN to the same handful of rows).
        Called periodically by run_talonx.py's periodic_wal_checkpoint_loop."""
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PaperTradingStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # --- Portfolio state -----------------------------------------------

    def get_portfolio_summary(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT initial_balance, current_cash, trade_allocation_usd, "
                "total_realized_pnl_usd, win_count, loss_count FROM portfolio_state WHERE id = 1"
            ).fetchone()
            open_count = self._conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]

        initial_balance, current_cash, trade_allocation_usd, total_pnl, win_count, loss_count = row
        closed = win_count + loss_count
        return {
            "initial_balance": initial_balance,
            "current_cash": current_cash,
            "trade_allocation_usd": trade_allocation_usd,
            "total_realized_pnl_usd": total_pnl,
            "total_realized_pnl_pct": (total_pnl / initial_balance * 100) if initial_balance else 0.0,
            "open_positions_count": open_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate_pct": (win_count / closed * 100) if closed else 0.0,
        }

    def update_trade_allocation(self, amount: float) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE portfolio_state SET trade_allocation_usd = ? WHERE id = 1", (amount,)
            )
            self._conn.commit()

    def reset_portfolio(self, initial_balance: float, trade_allocation_usd: float) -> None:
        """Requirement 5's reset -- clears all open positions and trade
        history, and restores cash to a fresh starting balance."""
        with self._lock:
            self._conn.execute("DELETE FROM positions")
            self._conn.execute("DELETE FROM trade_history")
            self._conn.execute(
                "UPDATE portfolio_state SET initial_balance = ?, current_cash = ?, "
                "trade_allocation_usd = ?, total_realized_pnl_usd = 0, win_count = 0, loss_count = 0 "
                "WHERE id = 1",
                (initial_balance, initial_balance, trade_allocation_usd),
            )
            self._conn.commit()

    # --- Positions -------------------------------------------------------

    def get_position(self, ticker: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT ticker, shares, entry_price, entry_timestamp, cost_basis "
                "FROM positions WHERE ticker = ?",
                (ticker.upper(),),
            ).fetchone()
        if row is None:
            return None
        ticker, shares, entry_price, entry_timestamp, cost_basis = row
        return {
            "ticker": ticker, "shares": shares, "entry_price": entry_price,
            "entry_timestamp": entry_timestamp, "cost_basis": cost_basis,
        }

    def get_open_positions(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ticker, shares, entry_price, entry_timestamp, cost_basis "
                "FROM positions ORDER BY ticker"
            ).fetchall()
        return [
            {
                "ticker": ticker, "shares": shares, "entry_price": entry_price,
                "entry_timestamp": entry_timestamp, "cost_basis": cost_basis,
            }
            for ticker, shares, entry_price, entry_timestamp, cost_basis in rows
        ]

    # --- Trade execution (atomic, multi-table) ----------------------------

    def execute_buy(
        self, ticker: str, shares: float, price: float, cost: float, timestamp: datetime,
    ) -> PaperTradeExecution:
        ticker = ticker.upper()
        with self._lock:
            current_cash = self._conn.execute(
                "SELECT current_cash FROM portfolio_state WHERE id = 1"
            ).fetchone()[0]
            new_cash = current_cash - cost
            self._conn.execute("UPDATE portfolio_state SET current_cash = ? WHERE id = 1", (new_cash,))
            self._conn.execute(
                "INSERT INTO positions (ticker, shares, entry_price, entry_timestamp, cost_basis) "
                "VALUES (?, ?, ?, ?, ?)",
                (ticker, shares, price, timestamp.isoformat(), cost),
            )
            cursor = self._conn.execute(
                "INSERT INTO trade_history "
                "(ticker, order_type, execution_price, shares, position_cost, portfolio_cash_after, timestamp) "
                "VALUES (?, 'BUY', ?, ?, ?, ?, ?)",
                (ticker, price, shares, cost, new_cash, timestamp.isoformat()),
            )
            trade_id = cursor.lastrowid
            session_pnl, initial_balance = self._conn.execute(
                "SELECT total_realized_pnl_usd, initial_balance FROM portfolio_state WHERE id = 1"
            ).fetchone()
            self._conn.commit()

        return PaperTradeExecution(
            trade_id=trade_id, ticker=ticker, order_type=OrderType.BUY,
            execution_price=price, shares=shares, position_cost=cost,
            portfolio_cash_after=new_cash, triggering_action=AlertAction.CONFIRMED_BULLISH,
            session_realized_pnl_usd=session_pnl,
            session_realized_pnl_pct=(session_pnl / initial_balance * 100) if initial_balance else 0.0,
            timestamp=timestamp,
        )

    def execute_sell(
        self, ticker: str, exit_price: float, timestamp: datetime, triggering_action: AlertAction,
    ) -> PaperTradeExecution | None:
        """Returns None if there's no open position for this ticker --
        defensive; engine.decide_trade should already have gated this,
        but the store never trusts a caller to have gotten that right."""
        ticker = ticker.upper()
        with self._lock:
            pos = self._conn.execute(
                "SELECT shares, entry_price, cost_basis FROM positions WHERE ticker = ?", (ticker,)
            ).fetchone()
            if pos is None:
                return None
            shares, entry_price, cost_basis = pos

            proceeds = shares * exit_price
            pnl_usd, pnl_pct = calculate_sell_pnl(shares, entry_price, exit_price)
            is_win = pnl_usd > 0

            current_cash, total_pnl, win_count, loss_count, initial_balance = self._conn.execute(
                "SELECT current_cash, total_realized_pnl_usd, win_count, loss_count, initial_balance "
                "FROM portfolio_state WHERE id = 1"
            ).fetchone()
            new_cash = current_cash + proceeds
            new_total_pnl = total_pnl + pnl_usd
            new_win = win_count + (1 if is_win else 0)
            new_loss = loss_count + (0 if is_win else 1)

            self._conn.execute(
                "UPDATE portfolio_state SET current_cash = ?, total_realized_pnl_usd = ?, "
                "win_count = ?, loss_count = ? WHERE id = 1",
                (new_cash, new_total_pnl, new_win, new_loss),
            )
            self._conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
            cursor = self._conn.execute(
                "INSERT INTO trade_history "
                "(ticker, order_type, execution_price, shares, position_cost, entry_price, "
                "realized_pnl_usd, realized_pnl_pct, portfolio_cash_after, timestamp) "
                "VALUES (?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, exit_price, shares, cost_basis, entry_price, pnl_usd, pnl_pct,
                 new_cash, timestamp.isoformat()),
            )
            trade_id = cursor.lastrowid
            self._conn.commit()

        return PaperTradeExecution(
            trade_id=trade_id, ticker=ticker, order_type=OrderType.SELL,
            execution_price=exit_price, shares=shares, position_cost=cost_basis,
            entry_price=entry_price, realized_pnl_usd=pnl_usd, realized_pnl_pct=pnl_pct,
            portfolio_cash_after=new_cash, triggering_action=triggering_action,
            session_realized_pnl_usd=new_total_pnl,
            session_realized_pnl_pct=(new_total_pnl / initial_balance * 100) if initial_balance else 0.0,
            timestamp=timestamp,
        )

    # --- Trade history -----------------------------------------------------

    def get_trade_history(self, limit: int = 500) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, ticker, order_type, execution_price, shares, position_cost, entry_price, "
                "realized_pnl_usd, realized_pnl_pct, portfolio_cash_after, timestamp "
                "FROM trade_history ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_trade_history_between(self, start: datetime, end: datetime) -> list[dict]:
        """All executed trades with start <= timestamp < end -- the EOD
        report's date-window equivalent of get_trade_history's LIMIT-based
        read."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, ticker, order_type, execution_price, shares, position_cost, entry_price, "
                "realized_pnl_usd, realized_pnl_pct, portfolio_cash_after, timestamp "
                "FROM trade_history WHERE timestamp >= ? AND timestamp < ? ORDER BY id",
                (start.isoformat(), end.isoformat()),
            )
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    # --- Ignored decisions (the "why didn't it trade" trail) ---------------

    def record_ignored(
        self, ticker: str, reason: str, triggering_action, price: float, timestamp: datetime,
        horizon: str = "intraday",
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ignored_decisions (ticker, reason, triggering_action, price, horizon, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ticker.upper(), reason,
                    triggering_action.value if hasattr(triggering_action, "value") else triggering_action,
                    price, horizon, timestamp.isoformat(),
                ),
            )
            self._conn.commit()

    def get_ignored_decisions_between(self, start: datetime, end: datetime) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, ticker, reason, triggering_action, price, horizon, timestamp FROM ignored_decisions "
                "WHERE timestamp >= ? AND timestamp < ? ORDER BY id",
                (start.isoformat(), end.isoformat()),
            )
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    # --- Live prices (for the dashboard's mark-to-market) -------------------

    def update_latest_price(self, ticker: str, price: float, updated_at: datetime) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO latest_prices (ticker, price, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET price = excluded.price, updated_at = excluded.updated_at",
                (ticker.upper(), price, updated_at.isoformat()),
            )
            self._conn.commit()

    def get_latest_prices(self) -> dict[str, float]:
        with self._lock:
            rows = self._conn.execute("SELECT ticker, price FROM latest_prices").fetchall()
        return {ticker: price for ticker, price in rows}

    # ------------------------------------------------------------------
    # Phase 2 LONG_TERM path
    # ------------------------------------------------------------------

    def get_long_term_portfolio_summary(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT initial_balance, current_cash, dca_contribution_usd, "
                "total_realized_pnl_usd, win_count, loss_count FROM long_term_portfolio_state WHERE id = 1"
            ).fetchone()
            open_count = self._conn.execute("SELECT COUNT(*) FROM long_term_positions").fetchone()[0]

        initial_balance, current_cash, dca_contribution_usd, total_pnl, win_count, loss_count = row
        closed = win_count + loss_count
        return {
            "initial_balance": initial_balance,
            "current_cash": current_cash,
            "dca_contribution_usd": dca_contribution_usd,
            "total_realized_pnl_usd": total_pnl,
            "total_realized_pnl_pct": (total_pnl / initial_balance * 100) if initial_balance else 0.0,
            "open_positions_count": open_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate_pct": (win_count / closed * 100) if closed else 0.0,
        }

    def update_dca_contribution_amount(self, amount: float) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE long_term_portfolio_state SET dca_contribution_usd = ? WHERE id = 1", (amount,)
            )
            self._conn.commit()

    def reset_long_term_portfolio(self, initial_balance: float, dca_contribution_usd: float) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM long_term_positions")
            self._conn.execute("DELETE FROM long_term_trade_history")
            self._conn.execute(
                "UPDATE long_term_portfolio_state SET initial_balance = ?, current_cash = ?, "
                "dca_contribution_usd = ?, total_realized_pnl_usd = 0, win_count = 0, loss_count = 0 "
                "WHERE id = 1",
                (initial_balance, initial_balance, dca_contribution_usd),
            )
            self._conn.commit()

    def get_long_term_position(self, ticker: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT ticker, total_shares, avg_cost_basis, first_entry_at, total_contributed_usd "
                "FROM long_term_positions WHERE ticker = ?",
                (ticker.upper(),),
            ).fetchone()
        if row is None:
            return None
        ticker, total_shares, avg_cost_basis, first_entry_at, total_contributed_usd = row
        return {
            "ticker": ticker, "total_shares": total_shares, "avg_cost_basis": avg_cost_basis,
            "first_entry_at": first_entry_at, "total_contributed_usd": total_contributed_usd,
        }

    def get_open_long_term_positions(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ticker, total_shares, avg_cost_basis, first_entry_at, total_contributed_usd "
                "FROM long_term_positions ORDER BY ticker"
            ).fetchall()
        return [
            {
                "ticker": ticker, "total_shares": total_shares, "avg_cost_basis": avg_cost_basis,
                "first_entry_at": first_entry_at, "total_contributed_usd": total_contributed_usd,
            }
            for ticker, total_shares, avg_cost_basis, first_entry_at, total_contributed_usd in rows
        ]

    def execute_long_term_buy(
        self, ticker: str, shares: float, price: float, cost: float, timestamp: datetime,
    ) -> LongTermTradeExecution:
        """Opens a NEW long-term position -- decide_long_term_trade only
        ever calls this when flat (HIGH_CONVICTION_BUY's own gate), so
        this always INSERTs, never needs to handle an existing row."""
        ticker = ticker.upper()
        with self._lock:
            current_cash = self._conn.execute(
                "SELECT current_cash FROM long_term_portfolio_state WHERE id = 1"
            ).fetchone()[0]
            new_cash = current_cash - cost
            self._conn.execute(
                "UPDATE long_term_portfolio_state SET current_cash = ? WHERE id = 1", (new_cash,)
            )
            self._conn.execute(
                "INSERT INTO long_term_positions "
                "(ticker, total_shares, avg_cost_basis, first_entry_at, total_contributed_usd) "
                "VALUES (?, ?, ?, ?, ?)",
                (ticker, shares, price, timestamp.isoformat(), cost),
            )
            cursor = self._conn.execute(
                "INSERT INTO long_term_trade_history "
                "(ticker, order_type, execution_price, shares, contribution_cost, avg_cost_basis_after, "
                "total_shares_after, portfolio_cash_after, triggering_action, timestamp) "
                "VALUES (?, 'BUY', ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, price, shares, cost, price, shares, new_cash,
                 AlertAction.HIGH_CONVICTION_BUY.value, timestamp.isoformat()),
            )
            trade_id = cursor.lastrowid
            self._conn.commit()

        return LongTermTradeExecution(
            trade_id=trade_id, ticker=ticker, order_type=LongTermOrderType.BUY,
            execution_price=price, shares=shares, contribution_cost=cost,
            avg_cost_basis_after=price, total_shares_after=shares,
            portfolio_cash_after=new_cash, triggering_action=AlertAction.HIGH_CONVICTION_BUY,
            timestamp=timestamp,
        )

    def execute_dca_contribution(
        self, ticker: str, contribution_usd: float, price: float, timestamp: datetime,
    ) -> LongTermTradeExecution | None:
        """Adds to an EXISTING position, recomputing the weighted average
        cost basis -- returns None if there's no open position for this
        ticker (defensive; the DCA loop only ever iterates currently-open
        positions, but the store never trusts a caller to have gotten
        that right, same posture execute_sell already takes)."""
        ticker = ticker.upper()
        with self._lock:
            pos = self._conn.execute(
                "SELECT total_shares, avg_cost_basis, total_contributed_usd FROM long_term_positions "
                "WHERE ticker = ?", (ticker,),
            ).fetchone()
            if pos is None:
                return None
            existing_shares, existing_avg_cost, existing_contributed = pos

            if price <= 0 or contribution_usd <= 0:
                return None
            new_shares = contribution_usd / price
            total_shares = existing_shares + new_shares
            new_avg_cost = calculate_average_cost_basis(existing_shares, existing_avg_cost, new_shares, price)
            new_contributed = existing_contributed + contribution_usd

            current_cash = self._conn.execute(
                "SELECT current_cash FROM long_term_portfolio_state WHERE id = 1"
            ).fetchone()[0]
            new_cash = current_cash - contribution_usd
            self._conn.execute(
                "UPDATE long_term_portfolio_state SET current_cash = ? WHERE id = 1", (new_cash,)
            )
            self._conn.execute(
                "UPDATE long_term_positions SET total_shares = ?, avg_cost_basis = ?, "
                "total_contributed_usd = ? WHERE ticker = ?",
                (total_shares, new_avg_cost, new_contributed, ticker),
            )
            cursor = self._conn.execute(
                "INSERT INTO long_term_trade_history "
                "(ticker, order_type, execution_price, shares, contribution_cost, avg_cost_basis_after, "
                "total_shares_after, portfolio_cash_after, triggering_action, timestamp) "
                "VALUES (?, 'DCA_CONTRIBUTION', ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, price, new_shares, contribution_usd, new_avg_cost, total_shares, new_cash,
                 AlertAction.DCA_CONTRIBUTION.value, timestamp.isoformat()),
            )
            trade_id = cursor.lastrowid
            self._conn.commit()

        return LongTermTradeExecution(
            trade_id=trade_id, ticker=ticker, order_type=LongTermOrderType.DCA_CONTRIBUTION,
            execution_price=price, shares=new_shares, contribution_cost=contribution_usd,
            avg_cost_basis_after=new_avg_cost, total_shares_after=total_shares,
            portfolio_cash_after=new_cash, triggering_action=AlertAction.DCA_CONTRIBUTION,
            timestamp=timestamp,
        )

    def execute_long_term_sell(
        self, ticker: str, trim_fraction: float, exit_price: float, timestamp: datetime,
        triggering_action: AlertAction,
    ) -> LongTermTradeExecution | None:
        """trim_fraction=1.0 is a full exit (UNDER_PERFORM_REBALANCE);
        anything less is a partial trim (TAKE_PROFIT_REBALANCE). Returns
        None if there's no open position -- same defensive posture as
        execute_dca_contribution above."""
        ticker = ticker.upper()
        with self._lock:
            pos = self._conn.execute(
                "SELECT total_shares, avg_cost_basis, first_entry_at, total_contributed_usd "
                "FROM long_term_positions WHERE ticker = ?", (ticker,),
            ).fetchone()
            if pos is None:
                return None
            total_shares, avg_cost_basis, first_entry_at, total_contributed = pos

            trim_fraction = min(max(trim_fraction, 0.0), 1.0)
            shares_to_sell = total_shares * trim_fraction
            remaining_shares = total_shares - shares_to_sell
            full_exit = remaining_shares <= 1e-9

            proceeds = shares_to_sell * exit_price
            pnl_usd, pnl_pct = calculate_partial_sell_pnl(shares_to_sell, avg_cost_basis, exit_price)
            is_win = pnl_usd > 0
            holding_period_days = (timestamp - datetime.fromisoformat(first_entry_at)).days

            current_cash, total_pnl, win_count, loss_count, initial_balance = self._conn.execute(
                "SELECT current_cash, total_realized_pnl_usd, win_count, loss_count, initial_balance "
                "FROM long_term_portfolio_state WHERE id = 1"
            ).fetchone()
            new_cash = current_cash + proceeds
            new_total_pnl = total_pnl + pnl_usd
            new_win = win_count + (1 if is_win else 0)
            new_loss = loss_count + (0 if is_win else 1)

            self._conn.execute(
                "UPDATE long_term_portfolio_state SET current_cash = ?, total_realized_pnl_usd = ?, "
                "win_count = ?, loss_count = ? WHERE id = 1",
                (new_cash, new_total_pnl, new_win, new_loss),
            )
            if full_exit:
                self._conn.execute("DELETE FROM long_term_positions WHERE ticker = ?", (ticker,))
                avg_cost_basis_after = None
                total_shares_after = None
            else:
                self._conn.execute(
                    "UPDATE long_term_positions SET total_shares = ? WHERE ticker = ?",
                    (remaining_shares, ticker),
                )
                avg_cost_basis_after = avg_cost_basis  # unchanged -- trimming doesn't alter the average
                total_shares_after = remaining_shares

            cursor = self._conn.execute(
                "INSERT INTO long_term_trade_history "
                "(ticker, order_type, execution_price, shares, contribution_cost, avg_cost_basis_after, "
                "total_shares_after, realized_pnl_usd, realized_pnl_pct, holding_period_days, "
                "portfolio_cash_after, triggering_action, timestamp) "
                "VALUES (?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, exit_price, shares_to_sell, proceeds, avg_cost_basis_after, total_shares_after,
                 pnl_usd, pnl_pct, holding_period_days, new_cash, triggering_action.value, timestamp.isoformat()),
            )
            trade_id = cursor.lastrowid
            self._conn.commit()

        return LongTermTradeExecution(
            trade_id=trade_id, ticker=ticker, order_type=LongTermOrderType.SELL,
            execution_price=exit_price, shares=shares_to_sell, contribution_cost=proceeds,
            avg_cost_basis_after=avg_cost_basis_after, total_shares_after=total_shares_after,
            realized_pnl_usd=pnl_usd, realized_pnl_pct=pnl_pct, holding_period_days=holding_period_days,
            portfolio_cash_after=new_cash, triggering_action=triggering_action, timestamp=timestamp,
        )

    def get_long_term_trade_history(self, limit: int = 500) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, ticker, order_type, execution_price, shares, contribution_cost, "
                "avg_cost_basis_after, total_shares_after, realized_pnl_usd, realized_pnl_pct, "
                "holding_period_days, portfolio_cash_after, triggering_action, timestamp "
                "FROM long_term_trade_history ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_long_term_trade_history_between(self, start: datetime, end: datetime) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, ticker, order_type, execution_price, shares, contribution_cost, "
                "avg_cost_basis_after, total_shares_after, realized_pnl_usd, realized_pnl_pct, "
                "holding_period_days, portfolio_cash_after, triggering_action, timestamp "
                "FROM long_term_trade_history WHERE timestamp >= ? AND timestamp < ? ORDER BY id",
                (start.isoformat(), end.isoformat()),
            )
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
