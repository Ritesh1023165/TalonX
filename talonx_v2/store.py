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
-- Task 117 overnight: a durable, idempotent PRE-OPEN entry intent.  It is
-- created when a cluster fires and its eligible entry session has NOT started,
-- so an actionable alert can be sent BEFORE that session's open.  It carries NO
-- economic weight of its own -- the fill still runs through the unchanged frozen
-- pipeline at the eligible-entry-session OPEN; the intent only records that the
-- decision existed earlier and links the later fill to it.
CREATE TABLE IF NOT EXISTS pending_entry_intents (
    intent_id             TEXT PRIMARY KEY,
    episode_id            TEXT NOT NULL UNIQUE,
    symbol                TEXT NOT NULL,
    issuer_cik            TEXT,
    strategy_version      TEXT NOT NULL,
    activation_filing_date TEXT,
    target_entry_session  TEXT NOT NULL,
    planned_exit_session  TEXT,
    decision_action       TEXT NOT NULL,
    decision_rationale    TEXT,
    horizon_trading_days  INTEGER NOT NULL,
    liquidity_ok          INTEGER,
    liquidity_median_dv   REAL,
    liquidity_last_close  REAL,
    status                TEXT NOT NULL,          -- PENDING | FILLED | EXPIRED_STALE | SUPERSEDED
    created_at_utc        TEXT NOT NULL,
    updated_at_utc        TEXT NOT NULL,
    filled_position_id    INTEGER,
    fill_entry_session    TEXT,
    fill_price            REAL,
    reconciled_at_utc     TEXT,
    detail                TEXT
);
-- Task 117 overnight: durable V2 official-alert outbox.  Written by the service,
-- drained by a delivery worker that asks OfficialExternalRouter and hands the
-- payload to an injected transport.  Explicit SENT/HELD/FAILED/PENDING/AMBIGUOUS.
CREATE TABLE IF NOT EXISTS v2_alert_outbox (
    event_id              TEXT PRIMARY KEY,
    episode_id            TEXT NOT NULL,
    intent_id             TEXT,
    position_id           INTEGER,
    kind                  TEXT NOT NULL,          -- ENTRY_INTENT | ENTRY_FILL | EXIT_FILL | ENTRY_STALE
    action                TEXT NOT NULL,          -- BUY | SELL | INFO
    symbol                TEXT NOT NULL,
    strategy_version      TEXT NOT NULL,
    horizon_trading_days  INTEGER,
    dedup_key             TEXT NOT NULL,
    payload_text          TEXT NOT NULL,
    provenance_json       TEXT NOT NULL,
    state                 TEXT NOT NULL,          -- PENDING | SENT | HELD | FAILED | AMBIGUOUS | RETRY | EXPIRED
    attempts              INTEGER NOT NULL DEFAULT 0,
    next_attempt_utc      TEXT,
    last_error            TEXT,
    transport_ref         TEXT,
    -- Task 117 deployment-readiness: an actionable-instruction alert (PLANNED
    -- BUY / ENTRY_INTENT) is only deliverable BEFORE this instant; past it the
    -- worker marks it EXPIRED so a queued instruction never emerges after the
    -- open as fresh.  NULL for pure notifications (ENTRY_FILL / EXIT_FILL / ...).
    deliver_by_utc        TEXT,
    created_at_utc        TEXT NOT NULL,
    updated_at_utc        TEXT NOT NULL,
    sent_at_utc           TEXT
);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _utcnow() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()


class V2Store:
    def __init__(self, path: str = "v2_lane.db", starting_cash: float = 100_000.0):
        self.path = path
        self._starting_cash = starting_cash
        Path(path).parent.mkdir(parents=True, exist_ok=True) if "/" in path or "\\" in path else None
        # Task 131 Remediation Directive 4: a reentrant "active transaction"
        # slot. When None (the default, unchanged for every pre-existing
        # caller), _conn() opens/commits/closes its OWN connection per
        # call, exactly as before. When set (only inside the transaction()
        # context manager below), every nested _conn() call reuses the
        # SAME connection/transaction instead of opening a new one --
        # letting a sequence of otherwise-independent store method calls
        # (insert_open_position + set_cash + append_trade + ...) commit
        # together, atomically, as one unit.
        self._active_conn: sqlite3.Connection | None = None
        self._active_conn_depth: int = 0
        self._init()

    @contextmanager
    def _conn(self):
        if self._active_conn is not None:
            # reentrant: already inside an outer transaction() block --
            # reuse it, and let the OUTER block own commit/close.
            yield self._active_conn
            return
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            yield c
            c.commit()
        finally:
            c.close()

    @contextmanager
    def transaction(self):
        """Task 131 Remediation Directive 2/4: wrap a SEQUENCE of store
        method calls -- AND/OR further nested ``with store.transaction():``
        blocks -- in one explicit, atomic SQLite transaction (WAL mode
        active, via the same ``_conn()`` every method already uses).
        Every nested ``store.<method>(...)`` call inside this block
        commits together, as one unit, on exit -- or none of them do, if
        an exception propagates (the connection is closed WITHOUT a
        commit, so SQLite's own implicit ROLLBACK-on-close-without-commit
        applies; nothing partially written survives a crash mid-
        transaction).

        REENTRANT (depth-counted): a caller may open ``with store.
        transaction():`` around a SEQUENCE that itself calls a function
        which ALSO opens ``with store.transaction():`` internally (e.g.
        ``talonx_v2.paper.enter_position``) -- the inner call transparently
        joins the SAME outer connection/transaction rather than raising or
        opening a second one. Only the OUTERMOST block actually commits/
        closes; an exception at ANY depth propagates up and the entire
        nested sequence is rolled back together (nothing commits)."""
        if self._active_conn is not None:
            # already inside an outer transaction() block -- join it. Only
            # the OUTERMOST context actually commits/closes/resets state.
            self._active_conn_depth += 1
            try:
                yield self._active_conn
            finally:
                self._active_conn_depth -= 1
            return
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        self._active_conn = c
        self._active_conn_depth = 1
        try:
            yield c
            c.commit()
        finally:
            self._active_conn = None
            self._active_conn_depth = 0
            c.close()

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)
            # additive, idempotent column migration for an outbox table that was
            # created by an earlier build (Task 117 deployment-readiness).
            cols = {r[1] for r in c.execute("PRAGMA table_info(v2_alert_outbox)")}
            if cols and "deliver_by_utc" not in cols:
                c.execute("ALTER TABLE v2_alert_outbox ADD COLUMN deliver_by_utc TEXT")
            row = c.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()
            if row is None:
                c.execute("INSERT INTO portfolio (id, cash) VALUES (1, ?)", (self._starting_cash,))
            # Task 131 Directive 2: WAL is already requested on every connection
            # (``_conn`` above); this is a one-time, loud verification that the
            # filesystem/driver actually honoured it, rather than silently
            # falling back to a lock-prone rollback-journal mode (a real risk on
            # some network filesystems). ":memory:" databases (used by a few
            # unit tests) cannot use WAL at all -- exempted explicitly, not
            # silently ignored.
            if self.path != ":memory:":
                mode = c.execute("PRAGMA journal_mode").fetchone()[0]
                if str(mode).lower() != "wal":
                    raise RuntimeError(
                        f"V2Store REFUSING to proceed: journal_mode={mode!r} at {self.path!r}, "
                        "expected 'wal' -- durable crash-resilience requires WAL")

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

    # ---- pre-open entry intents (Task 117 overnight) ----
    @staticmethod
    def _intent_id(episode_id: str, target_entry_session: str) -> str:
        import hashlib
        return hashlib.sha256(f"{episode_id}|{target_entry_session}".encode()).hexdigest()[:16]

    def upsert_entry_intent(self, ep, decision, liquidity, *, horizon: int,
                            planned_exit_session: str = "") -> dict:
        """Create (idempotently) a PENDING pre-open entry intent for ``ep``.
        Never overwrites a FILLED/EXPIRED/SUPERSEDED terminal state."""
        tes = ep.eligible_entry_session.isoformat()
        iid = self._intent_id(ep.episode_id, tes)
        with self._conn() as c:
            row = c.execute("SELECT status FROM pending_entry_intents WHERE episode_id=?",
                            (ep.episode_id,)).fetchone()
            if row is not None:
                return self.entry_intent(ep.episode_id)  # already present -- idempotent
            c.execute(
                """INSERT INTO pending_entry_intents
                   (intent_id, episode_id, symbol, issuer_cik, strategy_version,
                    activation_filing_date, target_entry_session, planned_exit_session,
                    decision_action, decision_rationale, horizon_trading_days,
                    liquidity_ok, liquidity_median_dv, liquidity_last_close,
                    status, created_at_utc, updated_at_utc)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING', ?, ?)""",
                (iid, ep.episode_id, ep.symbol.upper(), ep.issuer_cik,
                 decision.strategy_version, ep.activation_filing_date.isoformat(), tes,
                 planned_exit_session, decision.action.value, decision.rationale[:400],
                 int(horizon), 1 if liquidity.ok else 0, liquidity.median_dollar_volume,
                 liquidity.last_close, _utcnow(), _utcnow()),
            )
        return self.entry_intent(ep.episode_id)

    def entry_intent(self, episode_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM pending_entry_intents WHERE episode_id=?",
                          (episode_id,)).fetchone()
            return dict(r) if r else None

    def pending_entry_intents(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM pending_entry_intents WHERE status='PENDING' "
                "ORDER BY target_entry_session, symbol")]

    def all_entry_intents(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM pending_entry_intents ORDER BY created_at_utc")]

    def mark_entry_intent(self, intent_id: str, status: str, *, position_id: int | None = None,
                          fill_price: float | None = None, fill_session: str = "",
                          detail: str = "") -> None:
        with self._conn() as c:
            c.execute(
                """UPDATE pending_entry_intents SET status=?, filled_position_id=?,
                     fill_price=?, fill_entry_session=?, reconciled_at_utc=?, updated_at_utc=?,
                     detail=? WHERE intent_id=? AND status='PENDING'""",
                (status, position_id, fill_price, fill_session, _utcnow(), _utcnow(),
                 detail[:400], intent_id),
            )

    # ---- V2 alert outbox (Task 117 overnight) ----
    def enqueue_alert(self, *, event_id: str, episode_id: str, kind: str, action: str,
                      symbol: str, strategy_version: str, dedup_key: str, payload_text: str,
                      provenance: dict, horizon_trading_days: int | None = None,
                      intent_id: str | None = None, position_id: int | None = None,
                      deliver_by_utc: str | None = None) -> bool:
        """Idempotent enqueue.  Returns True if a new row was written.

        ``deliver_by_utc`` -- for an actionable-instruction alert (ENTRY_INTENT):
        the instant after which the instruction is no longer actionable; the
        delivery worker EXPIRES it rather than sending it late as fresh.
        """
        with self._conn() as c:
            exists = c.execute("SELECT 1 FROM v2_alert_outbox WHERE event_id=?",
                               (event_id,)).fetchone() is not None
            if exists:
                return False
            c.execute(
                """INSERT INTO v2_alert_outbox
                   (event_id, episode_id, intent_id, position_id, kind, action, symbol,
                    strategy_version, horizon_trading_days, dedup_key, payload_text,
                    provenance_json, state, attempts, deliver_by_utc, created_at_utc, updated_at_utc)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING', 0, ?, ?, ?)""",
                (event_id, episode_id, intent_id, position_id, kind, action, symbol.upper(),
                 strategy_version, horizon_trading_days, dedup_key, payload_text,
                 json.dumps(provenance, default=str), deliver_by_utc, _utcnow(), _utcnow()),
            )
            return True

    def outbox_due(self, *, now_iso: str) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM v2_alert_outbox WHERE state IN ('PENDING','RETRY') "
                "AND (next_attempt_utc IS NULL OR next_attempt_utc <= ?) "
                "ORDER BY created_at_utc", (now_iso,))]

    def all_outbox(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM v2_alert_outbox ORDER BY created_at_utc")]

    def update_outbox(self, event_id: str, *, state: str, attempts: int | None = None,
                      next_attempt_utc: str | None = None, last_error: str | None = None,
                      transport_ref: str | None = None, sent: bool = False) -> None:
        with self._conn() as c:
            c.execute(
                """UPDATE v2_alert_outbox SET state=?,
                     attempts=COALESCE(?, attempts),
                     next_attempt_utc=?, last_error=?, transport_ref=COALESCE(?, transport_ref),
                     updated_at_utc=?, sent_at_utc=CASE WHEN ? THEN ? ELSE sent_at_utc END
                   WHERE event_id=?""",
                (state, attempts, next_attempt_utc, last_error, transport_ref, _utcnow(),
                 1 if sent else 0, _utcnow() if sent else None, event_id),
            )
