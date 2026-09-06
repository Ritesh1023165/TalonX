"""
talonx_v2.store -- V2 lane persistence (Phase 5, 12, 15)
======================================================
One SQLite file (``v2_lane.db`` by default).  Deterministic episode
identity + idempotent processing so a restart / replay / duplicate
filing can never create a repeated BUY.

Tables
------
processed_episodes  every episode_id ever seen + its disposition
positions           open + closed V2 paper positions (episode_id UNIQUE)
trades              append-only paper execution log
cooldowns           per-issuer re-entry cooldown-until session
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_episodes (
    episode_id            TEXT PRIMARY KEY,
    symbol                TEXT NOT NULL,
    issuer_cik            TEXT,
    activation_filing_date TEXT,
    eligible_entry_session TEXT,
    disposition           TEXT NOT NULL,          -- SIGNALLED | ENTERED | SKIPPED_<reason>
    detail                TEXT,
    first_seen_at         TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    position_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id            TEXT NOT NULL UNIQUE,
    symbol                TEXT NOT NULL,
    issuer_cik            TEXT,
    strategy_profile      TEXT NOT NULL DEFAULT 'INSIDER_BUY_CLUSTER_V2',
    strategy_version      TEXT NOT NULL DEFAULT 'INSIDER_BUY_CLUSTER_V2@1',
    status                TEXT NOT NULL,          -- OPEN | CLOSED
    entry_session         TEXT NOT NULL,
    target_exit_session   TEXT NOT NULL,
    entry_price           REAL,
    shares                REAL,
    position_cost         REAL,
    exit_session          TEXT,
    exit_price            REAL,
    realized_pnl_usd      REAL,
    realized_pnl_pct      REAL,
    trading_days_held     INTEGER,
    source_meta           TEXT,
    opened_at             TEXT NOT NULL,
    closed_at             TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    trade_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id            TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    action                TEXT NOT NULL,          -- BUY | SELL
    execution_price       REAL NOT NULL,
    shares                REAL NOT NULL,
    position_cost         REAL NOT NULL,
    entry_price           REAL,
    realized_pnl_usd      REAL,
    realized_pnl_pct      REAL,
    trading_days_held     INTEGER,
    portfolio_cash_after  REAL NOT NULL,
    executed_at           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cooldowns (
    issuer_key            TEXT PRIMARY KEY,       -- symbol
    cooldown_until_session TEXT NOT NULL,
    set_at                TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    cash    REAL NOT NULL
);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat()


class V2Store:
    def __init__(self, path: str = "v2_lane.db", starting_cash: float = 100_000.0):
        self.path = path
        self._starting_cash = starting_cash
        Path(path).parent.mkdir(parents=True, exist_ok=True) if "/" in path or "\\" in path else None
        self._init()

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            yield c
            c.commit()
        finally:
            c.close()

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)
            row = c.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()
            if row is None:
                c.execute("INSERT INTO portfolio (id, cash) VALUES (1, ?)", (self._starting_cash,))

    # ---- portfolio ----
    def cash(self) -> float:
        with self._conn() as c:
            return float(c.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()["cash"])

    def set_cash(self, v: float) -> None:
        with self._conn() as c:
            c.execute("UPDATE portfolio SET cash=? WHERE id=1", (v,))

    # ---- episode idempotency ----
    def episode_seen(self, episode_id: str) -> bool:
        with self._conn() as c:
            return c.execute(
                "SELECT 1 FROM processed_episodes WHERE episode_id=?", (episode_id,)
            ).fetchone() is not None

    def record_episode(self, ep, disposition: str, detail: str = "") -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO processed_episodes
                   (episode_id, symbol, issuer_cik, activation_filing_date,
                    eligible_entry_session, disposition, detail, first_seen_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(episode_id) DO UPDATE SET
                     disposition=excluded.disposition, detail=excluded.detail,
                     updated_at=excluded.updated_at""",
                (ep.episode_id, ep.symbol, ep.issuer_cik,
                 ep.activation_filing_date.isoformat(), ep.eligible_entry_session.isoformat(),
                 disposition, detail, _now(), _now()),
            )

    def record_disposition(self, *, episode_id: str, symbol: str, disposition: str,
                           detail: str = "", issuer_cik: str = "",
                           activation_filing_date: str = "",
                           eligible_entry_session: str = "") -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO processed_episodes
                   (episode_id, symbol, issuer_cik, activation_filing_date,
                    eligible_entry_session, disposition, detail, first_seen_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(episode_id) DO UPDATE SET
                     disposition=excluded.disposition, detail=excluded.detail,
                     updated_at=excluded.updated_at""",
                (episode_id, symbol.upper(), issuer_cik, activation_filing_date,
                 eligible_entry_session, disposition, detail, _now(), _now()),
            )

    def episode_disposition(self, episode_id: str) -> str | None:
        with self._conn() as c:
            r = c.execute("SELECT disposition FROM processed_episodes WHERE episode_id=?",
                          (episode_id,)).fetchone()
            return r["disposition"] if r else None

    # ---- positions ----
    def open_positions(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM positions WHERE status='OPEN' ORDER BY entry_session, symbol")]

    def all_positions(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM positions ORDER BY opened_at")]

    def position_for_symbol(self, symbol: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM positions WHERE symbol=? AND status='OPEN'",
                          (symbol.upper(),)).fetchone()
            return dict(r) if r else None

    def position_for_episode(self, episode_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM positions WHERE episode_id=?", (episode_id,)).fetchone()
            return dict(r) if r else None

    def n_open(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) n FROM positions WHERE status='OPEN'").fetchone()["n"])

    def insert_open_position(self, *, episode_id, symbol, issuer_cik, entry_session,
                             target_exit_session, entry_price, shares, position_cost,
                             source_meta: dict | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO positions
                   (episode_id, symbol, issuer_cik, status, entry_session, target_exit_session,
                    entry_price, shares, position_cost, source_meta, opened_at)
                   VALUES (?,?,?,'OPEN',?,?,?,?,?,?,?)""",
                (episode_id, symbol.upper(), issuer_cik,
                 entry_session.isoformat() if isinstance(entry_session, date) else str(entry_session),
                 target_exit_session.isoformat() if isinstance(target_exit_session, date) else str(target_exit_session),
                 entry_price, shares, position_cost,
                 json.dumps(source_meta or {}), _now()),
            )
            return int(cur.lastrowid)

    def mark_exit_unresolved(self, position_id: int, *, detail: str = "") -> None:
        """Explicit terminal-ish state: the +10-td exit bar and all
        fall-forward sessions were missing.  Not OPEN (stops retrying),
        not CLOSED (no realised P&L) -- loudly surfaced for the operator."""
        with self._conn() as c:
            c.execute(
                "UPDATE positions SET status='EXIT_UNRESOLVED', source_meta=?, closed_at=? "
                "WHERE position_id=? AND status='OPEN'",
                (json.dumps({"exit_unresolved": True, "detail": detail}), _now(), position_id),
            )

    def unresolved_positions(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM positions WHERE status='EXIT_UNRESOLVED' ORDER BY entry_session")]

    def close_position(self, *, position_id, exit_session, exit_price, realized_pnl_usd,
                       realized_pnl_pct, trading_days_held) -> None:
        with self._conn() as c:
            c.execute(
                """UPDATE positions SET status='CLOSED', exit_session=?, exit_price=?,
                     realized_pnl_usd=?, realized_pnl_pct=?, trading_days_held=?, closed_at=?
                   WHERE position_id=? AND status='OPEN'""",
                (exit_session.isoformat() if isinstance(exit_session, date) else str(exit_session),
                 exit_price, realized_pnl_usd, realized_pnl_pct, trading_days_held, _now(),
                 position_id),
            )

    # ---- trades ----
    def append_trade(self, *, episode_id, symbol, action, execution_price, shares,
                     position_cost, portfolio_cash_after, entry_price=None,
                     realized_pnl_usd=None, realized_pnl_pct=None, trading_days_held=None) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO trades
                   (episode_id, symbol, action, execution_price, shares, position_cost,
                    entry_price, realized_pnl_usd, realized_pnl_pct, trading_days_held,
                    portfolio_cash_after, executed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (episode_id, symbol.upper(), action, execution_price, shares, position_cost,
                 entry_price, realized_pnl_usd, realized_pnl_pct, trading_days_held,
                 portfolio_cash_after, _now()),
            )
            return int(cur.lastrowid)

    def trades(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM trades ORDER BY trade_id")]

    # ---- cooldowns ----
    def set_cooldown(self, symbol: str, until_session: date) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO cooldowns (issuer_key, cooldown_until_session, set_at)
                   VALUES (?,?,?)
                   ON CONFLICT(issuer_key) DO UPDATE SET
                     cooldown_until_session=excluded.cooldown_until_session, set_at=excluded.set_at""",
                (symbol.upper(), until_session.isoformat(), _now()),
            )

    def cooldown_until(self, symbol: str) -> date | None:
        with self._conn() as c:
            r = c.execute("SELECT cooldown_until_session FROM cooldowns WHERE issuer_key=?",
                          (symbol.upper(),)).fetchone()
            return date.fromisoformat(r["cooldown_until_session"]) if r else None
