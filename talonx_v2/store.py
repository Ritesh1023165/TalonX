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

from talonx_ops.account_blocks import SCHEMA as _ACCOUNT_BLOCKS_SCHEMA

# Package 2 Durable Account Blocks: this store's own account identity for
# every account_blocks/block_clearances row it writes or reads. V2 has
# exactly one logical account per ledger file, unlike talonx_paper's
# store (which shares one file across ORIGINAL_INTRADAY/ORIGINAL_LONGTERM).
V2_ACCOUNT_ID = "V2"

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
    closed_at             TEXT,
    entry_fee             REAL,     -- Package 4: position_cost = shares*entry_price + entry_fee
    exit_fee              REAL      -- Package 4: realized_pnl_usd = (shares*exit_price - exit_fee) - position_cost
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
    executed_at           TEXT NOT NULL,
    fee                   REAL      -- Package 4: entry_fee on a BUY row, exit_fee on a SELL row
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
-- RI-1 (V2 Release Integration Task RI-1): the canonical campaign identity
-- record -- ONE row per ledger file (same one-account-per-file model
-- `portfolio` and `V2_ACCOUNT_ID` already use), written EXACTLY ONCE at
-- first creation (see V2Store._init below), NEVER rewritten afterward.
-- Distinct from `portfolio.cash` (the MUTABLE live balance): this table is
-- the IMMUTABLE-after-creation identity + capitalization-authority record.
-- `starting_cash_usd` is the ACTUAL amount this campaign was seeded with
-- (authoritative for reconciliation) -- NULL only for a pre-RI-1 legacy
-- ledger file being opened for the first time under RI-1 code, whose true
-- historical seed amount cannot be safely reconstructed from the current
-- (already-traded) `portfolio.cash` balance (see cutover/legacy notes in
-- docs/research/evidence/v2_release_integration_ri1/README.md) -- never
-- fabricated. `config_fingerprint` LINKS to (does not equal) campaign
-- identity -- see that same evidence doc for the explicit distinction.
CREATE TABLE IF NOT EXISTS campaign (
    id                        INTEGER PRIMARY KEY CHECK (id = 1),
    campaign_id               TEXT NOT NULL,
    strategy                  TEXT NOT NULL,
    strategy_version          TEXT NOT NULL,
    execution_mode            TEXT NOT NULL,
    starting_cash_usd         REAL,
    per_position_allocation_usd REAL,
    config_fingerprint        TEXT,
    provenance                TEXT NOT NULL,   -- SEEDED_AT_CREATION | LEGACY_MIGRATED
    created_at_utc            TEXT NOT NULL
);
-- RI-1: durable, append-only audit record of every cutover classification
-- run against this ledger's PENDING intents (RI1-D/E) -- NOT itself the
-- source of idempotency (mark_entry_intent's own `WHERE status='PENDING'`
-- guard is), but the auditable "what happened, when" record RI1-L needs.
CREATE TABLE IF NOT EXISTS campaign_cutover_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    cutover_id        TEXT NOT NULL,
    executed_at_utc   TEXT NOT NULL,
    as_of_session     TEXT NOT NULL,
    cancelled_count   INTEGER NOT NULL,
    retained_count    INTEGER NOT NULL,
    expired_count     INTEGER NOT NULL,
    detail_json       TEXT NOT NULL
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
    detail                TEXT,
    source_event_ts_utc   TEXT,      -- Package 3 P3-F: provider/source timestamp (e.g. SEC EDGAR accepted_at_utc), where available
    receipt_ts_utc        TEXT       -- Package 3 P3-F: TalonX's OWN durable receipt timestamp (e.g. InsiderFiling.ingested_at_utc), where available
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
""" + _ACCOUNT_BLOCKS_SCHEMA


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _utcnow() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()


class V2Store:
    def __init__(self, path: str = "v2_lane.db", starting_cash: float = 100_000.0,
                 busy_timeout_ms: int = 30_000, *,
                 campaign_id: str = V2_ACCOUNT_ID, strategy: str = "INSIDER_BUY_CLUSTER_V2",
                 strategy_version: str = "INSIDER_BUY_CLUSTER_V2@1", execution_mode: str = "PAPER",
                 per_position_allocation_usd: float | None = None, config_fingerprint: str | None = None):
        self.path = path
        self._starting_cash = starting_cash
        # RI-1: campaign identity, threaded through to _init()'s seed-once
        # write below. Defaults reproduce the EXISTING, single, pre-RI-1
        # account's identity exactly (campaign_id == V2_ACCOUNT_ID == "V2")
        # -- opening the existing production v2_lane.db with no explicit
        # override is a complete no-op change vs pre-RI-1 behavior.
        self._campaign_id = campaign_id
        self._strategy = strategy
        self._strategy_version = strategy_version
        self._execution_mode = execution_mode
        self._per_position_allocation_usd = per_position_allocation_usd
        self._config_fingerprint = config_fingerprint
        self.account_id = campaign_id
        # how long a connection waits for a contended SQLite write lock
        # (PRAGMA busy_timeout, applied to every connection this store
        # opens) before raising sqlite3.OperationalError -- the "bounded"
        # in "bounded lock waiting." Overridable only for tests that need
        # to exercise the lock-TIMEOUT path itself in well under 30s; every
        # production caller keeps the 30s default unchanged.
        self._busy_timeout_ms = int(busy_timeout_ms)
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
        c = sqlite3.connect(self.path, timeout=self._busy_timeout_ms / 1000.0)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
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
        an exception propagates (explicit ``ROLLBACK`` -- see below).

        REENTRANT (depth-counted): a caller may open ``with store.
        transaction():`` around a SEQUENCE that itself calls a function
        which ALSO opens ``with store.transaction():`` internally (e.g.
        ``talonx_v2.paper.enter_position``) -- the inner call transparently
        joins the SAME outer connection/transaction rather than raising or
        opening a second one. Only the OUTERMOST block actually commits/
        closes; an exception at ANY depth propagates up and the entire
        nested sequence is rolled back together (nothing commits).

        CONCURRENT-ADMISSION FIX (Targeted Remediation, on top of the
        Final Remediation atomic-lifecycle work): the OUTERMOST block now
        acquires SQLite's RESERVED write lock via an explicit ``BEGIN
        IMMEDIATE`` the INSTANT the transaction opens -- before this
        block's own first read, not lazily at its first WRITE statement.
        Python's ``sqlite3`` module, left to its own default
        ``isolation_level`` handling, only ever issues an IMPLICIT
        ``BEGIN`` right before the first INSERT/UPDATE/DELETE -- a bare
        SELECT (e.g. ``_capacity_rejection_reason()``'s cash/slot reads)
        never acquires any lock at all. Two concurrent connections could
        therefore both run their own admission reads, both see the SAME
        pre-reservation capacity, and both proceed to write -- a classic
        time-of-check-to-time-of-use race that the Final Remediation
        pass's atomicity work (single-connection, single-process) never
        actually exercised. With an explicit ``BEGIN IMMEDIATE`` up
        front, a SECOND connection's own ``BEGIN IMMEDIATE`` instead
        BLOCKS (bounded by the same 30s ``busy_timeout`` already set
        below) until the FIRST connection's transaction commits or rolls
        back -- so by the time the second connection's own admission
        reads run, the first writer's reservation is already fully
        committed and visible. This requires ``isolation_level=None``
        (autocommit) on this connection so Python's own implicit
        transaction management never fights with the explicit
        ``BEGIN``/``COMMIT``/``ROLLBACK`` here. On lock failure (``BEGIN
        IMMEDIATE`` itself raises after exhausting busy_timeout), the
        connection is closed and the exception propagates BEFORE
        ``self._active_conn`` is ever set -- no partial reservation,
        alert, or economic mutation, and no nested call could have run
        yet either.

        Nested calls (this store already has an active outer connection)
        never re-acquire the lock -- it is already held by the outer
        block, held once, for the sequence's entire duration."""
        if self._active_conn is not None:
            # already inside an outer transaction() block -- join it. Only
            # the OUTERMOST context actually commits/closes/resets state,
            # and it already holds the write lock this whole nested call
            # runs under.
            self._active_conn_depth += 1
            try:
                yield self._active_conn
            finally:
                self._active_conn_depth -= 1
            return
        c = sqlite3.connect(self.path, timeout=self._busy_timeout_ms / 1000.0, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            # Acquire the write reservation NOW -- before this block's own
            # first read -- bounded by busy_timeout above. Raises
            # sqlite3.OperationalError on a genuine lock timeout; nothing
            # has been reserved/written/alerted at that point.
            c.execute("BEGIN IMMEDIATE")
        except Exception:
            c.close()
            raise
        self._active_conn = c
        self._active_conn_depth = 1
        try:
            yield c
            c.execute("COMMIT")
        except Exception:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass  # connection may already be unusable -- close() below still runs
            raise
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
            # Package 3 P3-F: additive audit columns for an intents table
            # that may have been created by an earlier build.
            intent_cols = {r[1] for r in c.execute("PRAGMA table_info(pending_entry_intents)")}
            if intent_cols and "source_event_ts_utc" not in intent_cols:
                c.execute("ALTER TABLE pending_entry_intents ADD COLUMN source_event_ts_utc TEXT")
            if intent_cols and "receipt_ts_utc" not in intent_cols:
                c.execute("ALTER TABLE pending_entry_intents ADD COLUMN receipt_ts_utc TEXT")
            # Package 4: additive fee-breakdown columns for a positions/
            # trades table that may have been created by an earlier build.
            pos_cols = {r[1] for r in c.execute("PRAGMA table_info(positions)")}
            if pos_cols and "entry_fee" not in pos_cols:
                c.execute("ALTER TABLE positions ADD COLUMN entry_fee REAL")
            if pos_cols and "exit_fee" not in pos_cols:
                c.execute("ALTER TABLE positions ADD COLUMN exit_fee REAL")
            trade_cols = {r[1] for r in c.execute("PRAGMA table_info(trades)")}
            if trade_cols and "fee" not in trade_cols:
                c.execute("ALTER TABLE trades ADD COLUMN fee REAL")
            row = c.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()
            portfolio_was_fresh = row is None
            if row is None:
                c.execute("INSERT INTO portfolio (id, cash) VALUES (1, ?)", (self._starting_cash,))
            # RI-1: seed the campaign identity record EXACTLY ONCE, the
            # SAME instant portfolio's own seed-once check runs (same
            # connection, same transaction -- both commit together or
            # neither does). A genuinely fresh ledger file (portfolio row
            # ALSO just created, above) is a NEW campaign: starting_cash_usd
            # is the actual amount just seeded, provenance SEEDED_AT_
            # CREATION. A ledger file that ALREADY had a portfolio row (this
            # V2Store build is opening it for the first time, but the file
            # itself predates RI-1) is a LEGACY campaign: starting_cash_usd
            # is left NULL -- the current `cash` balance already reflects
            # realized trading P&L, so the ORIGINAL seed amount cannot be
            # safely reconstructed from it alone (RI1-K: never fabricate
            # historical provenance). A caller migrating a KNOWN legacy
            # ledger with an independently-documented true starting amount
            # (e.g. the existing production account's own recorded
            # CAMPAIGN_STARTING_CASH) may backfill it explicitly via
            # `set_legacy_starting_cash()` below -- never inferred silently.
            camp_row = c.execute("SELECT campaign_id FROM campaign WHERE id=1").fetchone()
            if camp_row is None:
                c.execute(
                    """INSERT INTO campaign
                       (id, campaign_id, strategy, strategy_version, execution_mode,
                        starting_cash_usd, per_position_allocation_usd, config_fingerprint,
                        provenance, created_at_utc)
                       VALUES (1,?,?,?,?,?,?,?,?,?)""",
                    (self._campaign_id, self._strategy, self._strategy_version, self._execution_mode,
                     self._starting_cash if portfolio_was_fresh else None,
                     self._per_position_allocation_usd, self._config_fingerprint,
                     "SEEDED_AT_CREATION" if portfolio_was_fresh else "LEGACY_MIGRATED", _utcnow()),
                )
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

    # ---- campaign identity (RI-1) ----
    def campaign_identity(self) -> dict:
        """The immutable-after-creation campaign record. Always present
        after ``_init()`` -- every V2Store (new or pre-RI-1 legacy) gets
        exactly one row, seeded exactly once."""
        with self._conn() as c:
            r = c.execute("SELECT * FROM campaign WHERE id=1").fetchone()
            return dict(r)

    def campaign_starting_cash(self) -> float | None:
        """The AUTHORITATIVE starting-cash figure for this campaign, for
        reconciliation (RI1-C). None only for a legacy ledger whose true
        historical seed amount was never durably recorded before RI-1 and
        has not been explicitly backfilled -- callers (e.g.
        ``talonx_ops.prospective``) must fall back to their own
        previously-hardcoded constant in that case, never guess."""
        with self._conn() as c:
            r = c.execute("SELECT starting_cash_usd FROM campaign WHERE id=1").fetchone()
            return float(r["starting_cash_usd"]) if r and r["starting_cash_usd"] is not None else None

    def set_legacy_starting_cash(self, amount: float, *, evidence_ref: str) -> None:
        """Explicit, evidence-cited, ONE-TIME backfill for a LEGACY
        campaign's true historical starting cash (RI1-K) -- refuses to
        overwrite a value that is already known (SEEDED_AT_CREATION, or
        an already-backfilled legacy row), so this can never silently
        rewrite a real number. ``evidence_ref`` is recorded in
        `provenance` for audit (e.g. a citation to the specific
        documented constant/decision this value came from) -- this
        method NEVER infers the amount itself."""
        with self._conn() as c:
            row = c.execute("SELECT provenance, starting_cash_usd FROM campaign WHERE id=1").fetchone()
            if row is None:
                raise RuntimeError("campaign row missing -- V2Store not initialized")
            if row["provenance"] != "LEGACY_MIGRATED" or row["starting_cash_usd"] is not None:
                raise RuntimeError(
                    "refusing to overwrite an already-known campaign starting_cash_usd "
                    f"(provenance={row['provenance']!r}, starting_cash_usd={row['starting_cash_usd']!r})")
            c.execute(
                "UPDATE campaign SET starting_cash_usd=?, provenance=? WHERE id=1",
                (amount, f"LEGACY_MIGRATED_BACKFILLED:{evidence_ref}"),
            )

    def record_cutover(self, *, cutover_id: str, as_of_session: date, cancelled_count: int,
                       retained_count: int, expired_count: int, detail: dict) -> None:
        """Durable, append-only audit record of one cutover classification
        run (``talonx_v2.cutover``) against THIS campaign's PENDING
        intents. Not itself the source of idempotency (``mark_entry_
        intent``'s own guard is) -- purely the auditable "what happened,
        when" trail RI1-L needs. Appends one row per call, including
        repeat/duplicate invocations."""
        with self._conn() as c:
            c.execute(
                """INSERT INTO campaign_cutover_log
                   (cutover_id, executed_at_utc, as_of_session, cancelled_count,
                    retained_count, expired_count, detail_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (cutover_id, _utcnow(), as_of_session.isoformat(), cancelled_count,
                 retained_count, expired_count, json.dumps(detail)),
            )

    def cutover_log(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM campaign_cutover_log ORDER BY id")]

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
        """OPEN **or** EXIT_UNRESOLVED (Package 1 Settlement Integrity):
        an unresolved obligation in this symbol still economically owns
        it -- a second entry must never be silently admitted through a
        lookup that only sees OPEN. This is the symbol-ownership check
        only; it does NOT change ``open_positions()`` (still OPEN-only,
        the retryable/actionable set ``due_exits()`` relies on)."""
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM positions WHERE symbol=? AND status IN ('OPEN','EXIT_UNRESOLVED')",
                (symbol.upper(),)).fetchone()
            return dict(r) if r else None

    def position_for_episode(self, episode_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM positions WHERE episode_id=?", (episode_id,)).fetchone()
            return dict(r) if r else None

    def n_open(self) -> int:
        """Occupied capacity slots -- OPEN **or** EXIT_UNRESOLVED
        (Package 1 Settlement Integrity): an unresolved obligation still
        occupies its slot until an operator auditably resolves it; it
        must never silently free capacity for a new admission. This does
        NOT change ``open_positions()`` (still OPEN-only, the
        retryable/actionable set ``due_exits()`` relies on)."""
        with self._conn() as c:
            return int(c.execute(
                "SELECT COUNT(*) n FROM positions WHERE status IN ('OPEN','EXIT_UNRESOLVED')"
            ).fetchone()["n"])

    def insert_open_position(self, *, episode_id, symbol, issuer_cik, entry_session,
                             target_exit_session, entry_price, shares, position_cost,
                             source_meta: dict | None = None, entry_fee: float = 0.0) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO positions
                   (episode_id, symbol, issuer_cik, status, entry_session, target_exit_session,
                    entry_price, shares, position_cost, source_meta, opened_at, entry_fee)
                   VALUES (?,?,?,'OPEN',?,?,?,?,?,?,?,?)""",
                (episode_id, symbol.upper(), issuer_cik,
                 entry_session.isoformat() if isinstance(entry_session, date) else str(entry_session),
                 target_exit_session.isoformat() if isinstance(target_exit_session, date) else str(target_exit_session),
                 entry_price, shares, position_cost,
                 json.dumps(source_meta or {}), _now(), entry_fee),
            )
            return int(cur.lastrowid)

    def mark_exit_unresolved(self, position_id: int, *, detail: str = "") -> None:
        """Explicit terminal-ish state: the +10-td exit bar and all
        fall-forward sessions were missing.  Not OPEN (stops retrying),
        not CLOSED (no realised P&L) -- loudly surfaced for the operator.

        Package 2 Durable Account Blocks: in the SAME connection/commit
        as the status transition, durably records an EXIT_UNRESOLVED
        account_blocks row (idempotent -- see account_blocks.record_block)
        so this position's own unresolved obligation blocks NEW admissions
        account-wide until an operator auditably clears it (Session 8 §E /
        Session 11 §5's agreed containment policy, OPS-012)."""
        from talonx_ops import account_blocks
        with self._conn() as c:
            c.execute(
                "UPDATE positions SET status='EXIT_UNRESOLVED', source_meta=?, closed_at=? "
                "WHERE position_id=? AND status='OPEN'",
                (json.dumps({"exit_unresolved": True, "detail": detail}), _now(), position_id),
            )
            if c.execute("SELECT status FROM positions WHERE position_id=?",
                         (position_id,)).fetchone()["status"] == "EXIT_UNRESOLVED":
                account_blocks.record_block(
                    c, account_id=self.account_id, reason_type=account_blocks.REASON_EXIT_UNRESOLVED,
                    reference=str(position_id), detail=detail)

    def unresolved_positions(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM positions WHERE status='EXIT_UNRESOLVED' ORDER BY entry_session")]

    def close_position(self, *, position_id, exit_session, exit_price, realized_pnl_usd,
                       realized_pnl_pct, trading_days_held, exit_fee: float = 0.0) -> bool:
        """The ``WHERE status='OPEN'`` guard IS the authoritative,
        atomic eligibility check for this state transition (Package 1
        Settlement Integrity) -- it must run inside the same
        transaction as the caller's cash/trade/cooldown mutations, and
        the caller MUST use this return value (True = the transition
        just happened; False = the position was already CLOSED/
        EXIT_UNRESOLVED/otherwise not OPEN) to decide whether any
        further economic mutation is warranted. Returning ``None``
        unconditionally here was the root cause of a duplicate-
        settlement defect: a caller holding a stale snapshot of an
        already-closed position had no way to detect that this UPDATE
        was a no-op before it went on to credit cash and record a
        second SELL."""
        with self._conn() as c:
            cur = c.execute(
                """UPDATE positions SET status='CLOSED', exit_session=?, exit_price=?,
                     realized_pnl_usd=?, realized_pnl_pct=?, trading_days_held=?, closed_at=?,
                     exit_fee=?
                   WHERE position_id=? AND status='OPEN'""",
                (exit_session.isoformat() if isinstance(exit_session, date) else str(exit_session),
                 exit_price, realized_pnl_usd, realized_pnl_pct, trading_days_held, _now(),
                 exit_fee, position_id),
            )
            return cur.rowcount > 0

    # ---- trades ----
    def append_trade(self, *, episode_id, symbol, action, execution_price, shares,
                     position_cost, portfolio_cash_after, entry_price=None,
                     realized_pnl_usd=None, realized_pnl_pct=None, trading_days_held=None,
                     fee: float = 0.0) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO trades
                   (episode_id, symbol, action, execution_price, shares, position_cost,
                    entry_price, realized_pnl_usd, realized_pnl_pct, trading_days_held,
                    portfolio_cash_after, executed_at, fee)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (episode_id, symbol.upper(), action, execution_price, shares, position_cost,
                 entry_price, realized_pnl_usd, realized_pnl_pct, trading_days_held,
                 portfolio_cash_after, _now(), fee),
            )
            return int(cur.lastrowid)

    def trades(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM trades ORDER BY trade_id")]

    # ---- account blocks (Package 2 Durable Account Blocks) ----
    def blocked_reason(self) -> str | None:
        """The authoritative admission-gate check for THIS V2 account --
        None means no active block. Callers that need this to be the
        FINAL, race-free check (entry admission) must call
        ``account_blocks.blocked_reason`` directly against the active
        connection inside their own ``with store.transaction():`` block
        instead of this convenience wrapper (which opens/commits its own
        connection and is therefore only a point-in-time snapshot, not
        the serialized gate)."""
        from talonx_ops import account_blocks
        with self._conn() as c:
            return account_blocks.blocked_reason(c, self.account_id)

    def active_account_blocks(self) -> list[dict]:
        from talonx_ops import account_blocks
        with self._conn() as c:
            return [b.__dict__ for b in account_blocks.active_blocks(c, self.account_id)]

    def record_account_block(self, *, reason_type: str, reference: str, detail: str = "") -> str:
        from talonx_ops import account_blocks
        with self.transaction() as c:
            return account_blocks.record_block(
                c, account_id=self.account_id, reason_type=reason_type,
                reference=reference, detail=detail)

    def attempt_block_clearance(self, *, block_id: str, operator_id: str, reason: str,
                                evidence_ref: str, allow: bool, detail: str = "") -> dict:
        from talonx_ops import account_blocks
        with self.transaction() as c:
            return account_blocks.attempt_clearance(
                c, block_id_=block_id, operator_id=operator_id, reason=reason,
                evidence_ref=evidence_ref, allow=allow, detail=detail)

    def block_clearance_history(self, block_id: str) -> list[dict]:
        from talonx_ops import account_blocks
        with self._conn() as c:
            return account_blocks.clearance_history(c, block_id)

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
                            planned_exit_session: str = "",
                            source_event_ts_utc=None, receipt_ts_utc=None) -> dict:
        """Create (idempotently) a PENDING pre-open entry intent for ``ep``.
        Never overwrites a FILLED/EXPIRED/SUPERSEDED terminal state.

        Package 3 P3-F: ``source_event_ts_utc``/``receipt_ts_utc``, when
        supplied, durably capture -- at the EARLIEST point they are known
        (admission time, this call) -- the provider/source timestamp and
        TalonX's own durable receipt timestamp that justified admission,
        so a later audit can reconstruct WHY this trade was allowed
        without needing to re-query the (mutable, retention-bounded)
        upstream InsiderStore. Both optional/nullable -- absent for a
        date-only source (research parquet) or when the caller did not
        have this information available, never fabricated."""
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
                    status, created_at_utc, updated_at_utc,
                    source_event_ts_utc, receipt_ts_utc)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING', ?, ?, ?, ?)""",
                (iid, ep.episode_id, ep.symbol.upper(), ep.issuer_cik,
                 decision.strategy_version, ep.activation_filing_date.isoformat(), tes,
                 planned_exit_session, decision.action.value, decision.rationale[:400],
                 int(horizon), 1 if liquidity.ok else 0, liquidity.median_dollar_volume,
                 liquidity.last_close, _utcnow(), _utcnow(),
                 source_event_ts_utc.isoformat() if source_event_ts_utc else None,
                 receipt_ts_utc.isoformat() if receipt_ts_utc else None),
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
