"""
talonx_dispatch.store
--------------------------
The audit trail: a durable, append-mostly SQLite log of every
ActionableAlert this module has ever seen -- the FIRST durable historical
record of alerts anywhere in the TalonX pipeline (talonx:alerts:dispatch
itself is Redis Pub/Sub, which is not durable; talonx_core's own state
store tracks correlator state, not a log of published alerts).

SQLite (stdlib, no new dependency), same choice
talonx_ingest.storage.ledger and talonx_core.store make for their own
local persistence. One row per alert, written by consumer.py
(DispatchAgent) and read by app.py (the Streamlit dashboard) -- TWO
SEPARATE PROCESSES sharing one file, not one connection, so this is
standard SQLite multi-process access (safe via file locking) rather than
anything unusual. WAL journal mode is enabled for smoother concurrent
read-while-write behavior between them.

`check_same_thread` defaults to True (matching the ledger/core_state
precedent -- see their own docstrings on why NOT to hand a connection to
asyncio.to_thread). app.py is the one exception: Streamlit's execution
model can run a session's script on a different thread than the one that
created a `@st.cache_resource`-cached object, so app.py explicitly passes
`check_same_thread=False` for ITS OWN connection. consumer.py's
connection (single asyncio process, single thread) keeps the default.

`check_same_thread=False` only disables Python's same-thread ASSERTION --
it does NOT make one sqlite3.Connection safe for concurrent use from
multiple threads. app.py's connection is cached via `@st.cache_resource`
and Streamlit can genuinely run more than one session's script
concurrently on different threads (multiple browser tabs, or an
autorefresh tick overlapping a still-rendering previous run) -- without
serializing access, two threads' `execute()` calls on the SAME connection
can interleave and produce exactly the kind of "impossible" result
`watchlist_summary()` used to be able to hit (a per-ticker detail lookup
racing another thread's query and coming back empty for a ticker the
aggregate query just returned). A plain `threading.Lock` around every
public method's body closes that gap by making method calls atomic with
respect to each other, at negligible cost -- these are fast, local,
single-connection SQLite calls, not something worth finer-grained locking.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from talonx_dispatch.schemas import ActionableAlert, LongTermActionableAlert

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT NOT NULL,
    action              TEXT NOT NULL,
    severity            TEXT NOT NULL,
    rationale           TEXT NOT NULL,
    quant_direction     TEXT NOT NULL,
    research_verdict    TEXT NOT NULL,
    research_confidence REAL NOT NULL,
    signal_type         TEXT NOT NULL,
    price               REAL NOT NULL,
    research_summary    TEXT NOT NULL,
    key_findings_json    TEXT NOT NULL,
    risk_factors_json    TEXT NOT NULL,
    model_used          TEXT NOT NULL,
    correlated_at       TEXT NOT NULL,
    received_at         TEXT NOT NULL,
    telegram_sent       INTEGER NOT NULL DEFAULT 0,
    telegram_sent_at    TEXT,
    telegram_error      TEXT,
    suppress_reason     TEXT,
    rsi                 REAL,
    macd                REAL,
    macd_signal_line    REAL,
    volume_surge_ratio  REAL,
    atr                 REAL,
    stop_price          REAL,
    target_price        REAL,
    trend_aligned       INTEGER,
    htf_sma_200         REAL,
    session             TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alerts (ticker);
CREATE INDEX IF NOT EXISTS idx_alerts_correlated_at ON alerts (correlated_at);

-- Phase 2 LONG_TERM path -- a SEPARATE table, not a horizon column on
-- `alerts` above: the field sets genuinely differ (quality/moat/fair-
-- value vs. quant-direction/research-verdict/confidence), so a shared
-- table would need a pile of nullable columns instead of a clean schema.
CREATE TABLE IF NOT EXISTS long_term_alerts (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                          TEXT NOT NULL,
    action                          TEXT NOT NULL,
    severity                        TEXT NOT NULL,
    rationale                       TEXT NOT NULL,
    summary                         TEXT NOT NULL DEFAULT '',
    quality_score                   INTEGER NOT NULL,
    moat_rating                     TEXT NOT NULL,
    market_price                    REAL NOT NULL,
    intrinsic_fair_value            REAL NOT NULL,
    margin_of_safety_pct            REAL NOT NULL,
    capital_allocation_assessment   TEXT NOT NULL,
    key_findings_json               TEXT NOT NULL,
    risk_factors_json               TEXT NOT NULL,
    model_used                      TEXT NOT NULL,
    correlated_at                   TEXT NOT NULL,
    received_at                     TEXT NOT NULL,
    telegram_sent                   INTEGER NOT NULL DEFAULT 0,
    telegram_sent_at                TEXT,
    telegram_error                  TEXT,
    suppress_reason                 TEXT,
    is_earnings_related             INTEGER NOT NULL DEFAULT 0,
    previous_fair_value             REAL,
    previous_margin_of_safety_pct   REAL,
    guidance_revision_notes         TEXT,
    revenue_eps_surprise            TEXT
);
CREATE INDEX IF NOT EXISTS idx_long_term_alerts_ticker ON long_term_alerts (ticker);
CREATE INDEX IF NOT EXISTS idx_long_term_alerts_correlated_at ON long_term_alerts (correlated_at);
"""


class AuditStore:
    def __init__(self, path: str | Path, check_same_thread: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=check_same_thread)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def _migrate(self) -> None:
        """This table's first schema evolution since its original release
        -- `summary` is a new column (the LLM's clean one-sentence
        write-up, separate from the more technical `rationale`; see
        talonx_core.schemas' LongTermActionableAlert.summary docstring).
        Same idempotent PRAGMA-table_info-guarded ALTER TABLE pattern
        talonx_watchlist/store.py and talonx_core/store.py already use,
        safe to run every startup. DEFAULT '' rather than NOT NULL alone
        -- SQLite requires a default when adding a NOT NULL column to a
        table that may already have rows; a pre-existing alert simply has
        no retroactive summary, not a migration failure.

        `suppress_reason` (Smart Dispatch Filtering) is the second
        evolution -- added to BOTH tables, same idempotent guard. NULL
        (not a NOT NULL/DEFAULT column) for a pre-existing row: unlike
        `summary`, which is always meaningful, "no push decision has been
        made for this old row" is a genuinely different state than any
        of the real suppress_reason values, so NULL is the correct
        semantics here, not an empty-string placeholder."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(long_term_alerts)").fetchall()}
        if "summary" not in cols:
            self._conn.execute("ALTER TABLE long_term_alerts ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
        if "suppress_reason" not in cols:
            self._conn.execute("ALTER TABLE long_term_alerts ADD COLUMN suppress_reason TEXT")
        # Event-Driven Earnings Radar (Requirement 8) -- same idempotent
        # guard, third evolution of this table. is_earnings_related
        # defaults to 0/False for a pre-existing row (it predates the
        # feature, so it genuinely wasn't); the rest stay NULL (no
        # "before" data exists for an old row either).
        if "is_earnings_related" not in cols:
            self._conn.execute(
                "ALTER TABLE long_term_alerts ADD COLUMN is_earnings_related INTEGER NOT NULL DEFAULT 0"
            )
        if "previous_fair_value" not in cols:
            self._conn.execute("ALTER TABLE long_term_alerts ADD COLUMN previous_fair_value REAL")
        if "previous_margin_of_safety_pct" not in cols:
            self._conn.execute("ALTER TABLE long_term_alerts ADD COLUMN previous_margin_of_safety_pct REAL")
        if "guidance_revision_notes" not in cols:
            self._conn.execute("ALTER TABLE long_term_alerts ADD COLUMN guidance_revision_notes TEXT")
        if "revenue_eps_surprise" not in cols:
            self._conn.execute("ALTER TABLE long_term_alerts ADD COLUMN revenue_eps_surprise TEXT")

        # `alerts` evolution: checking for the newest column ("rsi", the
        # Phase 2 technical-detail fields) alone is sufficient -- any
        # table missing it also predates suppress_reason, since both are
        # older than this check. Per project direction, this local audit
        # DB has no data worth preserving across the change: a stale
        # `alerts` table is dropped and recreated from _SCHEMA (which
        # already includes every column, suppress_reason included) rather
        # than ALTER TABLE'd column-by-column, same approach as
        # talonx_paper.store's `positions` table migration.
        alert_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(alerts)").fetchall()}
        if alert_cols and "rsi" not in alert_cols:
            self._conn.execute("DROP TABLE alerts")
            self._conn.executescript(_SCHEMA)

    def checkpoint(self) -> None:
        """Forces a WAL checkpoint (TRUNCATE mode). See
        talonx_paper.store.PaperTradingStore.checkpoint's docstring for
        the full rationale -- same passive-checkpoint-starvation risk
        applies to any WAL-mode store with a frequent writer (consumer.py)
        and a frequent separate-process reader (app.py's autorefresh),
        this store just sees far less write volume than PaperTradingStore
        so it's a lower-urgency instance of the same issue. Called
        periodically by run_talonx.py's periodic_wal_checkpoint_loop."""
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "AuditStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def record_alert(self, alert: ActionableAlert) -> int:
        sig = alert.triggering_signal
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO alerts (
                    ticker, action, severity, rationale, quant_direction,
                    research_verdict, research_confidence, signal_type, price,
                    research_summary, key_findings_json, risk_factors_json,
                    model_used, correlated_at, received_at,
                    rsi, macd, macd_signal_line, volume_surge_ratio, atr,
                    stop_price, target_price, trend_aligned, htf_sma_200, session
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.ticker.upper(),
                    alert.action.value,
                    alert.severity.value,
                    alert.rationale,
                    alert.quant_direction.value,
                    alert.research_verdict.value,
                    alert.research_confidence,
                    sig.signal_type,
                    sig.price,
                    alert.research_summary,
                    json.dumps(alert.key_findings),
                    json.dumps(alert.risk_factors),
                    alert.model_used,
                    alert.correlated_at.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    sig.rsi, sig.macd, sig.macd_signal_line, sig.volume_surge_ratio, sig.atr,
                    sig.stop_price, sig.target_price,
                    None if sig.trend_aligned is None else int(sig.trend_aligned),
                    sig.htf_sma_200, sig.session,
                ),
            )
            self._conn.commit()
            return cursor.lastrowid

    def mark_telegram_sent(self, alert_id: int, sent_at: datetime | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE alerts SET telegram_sent = 1, telegram_sent_at = ?, "
                "telegram_error = NULL, suppress_reason = 'NONE' WHERE id = ?",
                ((sent_at or datetime.now(timezone.utc)).isoformat(), alert_id),
            )
            self._conn.commit()

    def mark_telegram_failed(self, alert_id: int, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE alerts SET telegram_error = ?, suppress_reason = 'NONE' WHERE id = ?",
                (error[:500], alert_id),
            )
            self._conn.commit()

    def mark_suppressed(self, alert_id: int, reason: str) -> None:
        """Smart Dispatch Filtering: records WHY a Telegram push was
        withheld for this alert (ACTION_MUTED, CONFIDENCE_BELOW_GATE,
        PUSH_COOLDOWN_ACTIVE, PRICE_DELTA_TOO_LOW -- see consumer.py's
        _evaluate_push_eligibility). telegram_sent stays 0/False; the
        alert row itself was already written unconditionally by
        record_alert() before this filtering decision was even made."""
        with self._lock:
            self._conn.execute(
                "UPDATE alerts SET suppress_reason = ? WHERE id = ?",
                (reason, alert_id),
            )
            self._conn.commit()

    def count_alerts_today(self) -> tuple[int, int]:
        """`/ping`'s "Today's Signals Pushed" line -- (total_logs, pushed)
        across BOTH alerts and long_term_alerts for the current UTC
        calendar day. Reuses alerts_between/long_term_alerts_between
        rather than a raw COUNT query since the row count here is always
        small (a day's worth of alerts), and this keeps one indexed-
        column comparison convention instead of a second query shape."""
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        intraday = self.alerts_between(start, end)
        long_term = self.long_term_alerts_between(start, end)
        total = len(intraday) + len(long_term)
        pushed = sum(1 for r in intraday if r["telegram_sent"]) + sum(1 for r in long_term if r["telegram_sent"])
        return total, pushed

    def get_by_id(self, alert_id: int) -> dict | None:
        """Single-row fetch for telegram_listener.py's reply-with-ID
        lookup -- returns None if the id never existed, or has since
        been purged by purge_older_than()."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            return _row_to_dict(row) if row is not None else None

    def purge_older_than(self, cutoff: datetime) -> int:
        """Deletes every alert older than `cutoff` (compared against
        correlated_at) -- the audit trail's retention sweep
        (TALONX_DISPATCH_RETENTION_DAYS). Returns how many rows were
        deleted, purely for logging."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM alerts WHERE correlated_at < ?", (cutoff.isoformat(),)
            )
            self._conn.commit()
            return cursor.rowcount

    def alerts_between(self, start: datetime, end: datetime) -> list[dict]:
        """All alerts with start <= correlated_at < end -- the EOD report's
        date-window read, same indexed-column comparison purge_older_than
        already uses, just a SELECT instead of a DELETE."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM alerts WHERE correlated_at >= ? AND correlated_at < ? "
                "ORDER BY correlated_at, id",
                (start.isoformat(), end.isoformat()),
            )
            return [_row_to_dict(row) for row in cursor.fetchall()]

    def recent(self, limit: int = 200) -> list[dict]:
        with self._lock:
            # `id DESC` as a tiebreaker: correlated_at alone is ambiguous if
            # two alerts share the same wall-clock second (plausible under a
            # fast burst) -- id guarantees insertion order wins deterministically.
            cursor = self._conn.execute(
                "SELECT * FROM alerts ORDER BY correlated_at DESC, id DESC LIMIT ?", (limit,)
            )
            return [_row_to_dict(row) for row in cursor.fetchall()]

    def watchlist_summary(self) -> list[dict]:
        """
        One row per ticker: how many alerts, and the most recent
        action/severity/timestamp -- "which tickers are currently active"
        at a glance, sourced from the audit trail rather than a
        separately-maintained list (talonx_quant has no watchlist of its
        own yet -- see README §8 -- so this is derived data, not a
        configured list).
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT
                    ticker,
                    COUNT(*) AS alert_count,
                    MAX(correlated_at) AS last_seen
                FROM alerts
                GROUP BY ticker
                ORDER BY last_seen DESC
                """
            )
            tickers = [dict(row) for row in cursor.fetchall()]
            result = []
            for row in tickers:
                latest = self._conn.execute(
                    "SELECT action, severity FROM alerts WHERE ticker = ? "
                    "ORDER BY correlated_at DESC, id DESC LIMIT 1",
                    (row["ticker"],),
                ).fetchone()
                if latest is None:
                    # Shouldn't happen now that the whole method holds the
                    # lock (this row came from the SAME table moments ago)
                    # -- kept as a defensive guard rather than trusting that
                    # invariant to hold forever, so a future change here
                    # degrades to "skip this row" instead of crashing the
                    # whole dashboard render.
                    continue
                row["last_action"] = latest["action"]
                row["last_severity"] = latest["severity"]
                result.append(row)
            return result

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]

    # ------------------------------------------------------------------
    # Phase 2 LONG_TERM path -- same method shapes as the intraday ones
    # above, against long_term_alerts instead.
    # ------------------------------------------------------------------

    def record_long_term_alert(self, alert: LongTermActionableAlert) -> int:
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO long_term_alerts (
                    ticker, action, severity, rationale, summary, quality_score, moat_rating,
                    market_price, intrinsic_fair_value, margin_of_safety_pct,
                    capital_allocation_assessment, key_findings_json, risk_factors_json,
                    model_used, correlated_at, received_at, is_earnings_related,
                    previous_fair_value, previous_margin_of_safety_pct,
                    guidance_revision_notes, revenue_eps_surprise
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.ticker.upper(),
                    alert.action.value,
                    alert.severity.value,
                    alert.rationale,
                    alert.summary,
                    alert.quality_score,
                    alert.moat_rating.value,
                    alert.market_price,
                    alert.intrinsic_fair_value,
                    alert.margin_of_safety_pct,
                    alert.capital_allocation_assessment,
                    json.dumps(alert.key_findings),
                    json.dumps(alert.risk_factors),
                    alert.model_used,
                    alert.correlated_at.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    1 if alert.is_earnings_related else 0,
                    alert.previous_fair_value,
                    alert.previous_margin_of_safety_pct,
                    alert.guidance_revision_notes,
                    alert.revenue_eps_surprise,
                ),
            )
            self._conn.commit()
            return cursor.lastrowid

    def mark_long_term_telegram_sent(self, alert_id: int, sent_at: datetime | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE long_term_alerts SET telegram_sent = 1, telegram_sent_at = ?, "
                "telegram_error = NULL, suppress_reason = 'NONE' WHERE id = ?",
                ((sent_at or datetime.now(timezone.utc)).isoformat(), alert_id),
            )
            self._conn.commit()

    def mark_long_term_telegram_failed(self, alert_id: int, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE long_term_alerts SET telegram_error = ?, suppress_reason = 'NONE' WHERE id = ?",
                (error[:500], alert_id),
            )
            self._conn.commit()

    def mark_long_term_suppressed(self, alert_id: int, reason: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE long_term_alerts SET suppress_reason = ? WHERE id = ?",
                (reason, alert_id),
            )
            self._conn.commit()

    def get_long_term_by_id(self, alert_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM long_term_alerts WHERE id = ?", (alert_id,)).fetchone()
            return _long_term_row_to_dict(row) if row is not None else None

    def purge_long_term_older_than(self, cutoff: datetime) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM long_term_alerts WHERE correlated_at < ?", (cutoff.isoformat(),)
            )
            self._conn.commit()
            return cursor.rowcount

    def long_term_alerts_between(self, start: datetime, end: datetime) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM long_term_alerts WHERE correlated_at >= ? AND correlated_at < ? "
                "ORDER BY correlated_at, id",
                (start.isoformat(), end.isoformat()),
            )
            return [_long_term_row_to_dict(row) for row in cursor.fetchall()]

    def recent_long_term(self, limit: int = 200) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM long_term_alerts ORDER BY correlated_at DESC, id DESC LIMIT ?", (limit,)
            )
            return [_long_term_row_to_dict(row) for row in cursor.fetchall()]

    def count_long_term(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM long_term_alerts").fetchone()[0]


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["key_findings"] = json.loads(d.pop("key_findings_json"))
    d["risk_factors"] = json.loads(d.pop("risk_factors_json"))
    d["telegram_sent"] = bool(d["telegram_sent"])
    if "trend_aligned" in d and d["trend_aligned"] is not None:
        d["trend_aligned"] = bool(d["trend_aligned"])
    return d


def _long_term_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["key_findings"] = json.loads(d.pop("key_findings_json"))
    d["risk_factors"] = json.loads(d.pop("risk_factors_json"))
    d["telegram_sent"] = bool(d["telegram_sent"])
    d["is_earnings_related"] = bool(d["is_earnings_related"])
    return d
