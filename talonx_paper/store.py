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

from talonx_paper.engine import calculate_sell_pnl
from talonx_paper.schemas import AlertAction, OrderType, PaperTradeExecution

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
"""


class PaperTradingStore:
    def __init__(
        self,
        path: str | Path,
        default_initial_balance: float = 10000.0,
        default_trade_allocation_usd: float = 2500.0,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()
        self._ensure_portfolio_row(default_initial_balance, default_trade_allocation_usd)

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
