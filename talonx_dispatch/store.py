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
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from talonx_dispatch.schemas import ActionableAlert

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
    telegram_error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alerts (ticker);
CREATE INDEX IF NOT EXISTS idx_alerts_correlated_at ON alerts (correlated_at);
"""


class AuditStore:
    def __init__(self, path: str | Path, check_same_thread: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=check_same_thread)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "AuditStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def record_alert(self, alert: ActionableAlert) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO alerts (
                ticker, action, severity, rationale, quant_direction,
                research_verdict, research_confidence, signal_type, price,
                research_summary, key_findings_json, risk_factors_json,
                model_used, correlated_at, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.ticker.upper(),
                alert.action.value,
                alert.severity.value,
                alert.rationale,
                alert.quant_direction.value,
                alert.research_verdict.value,
                alert.research_confidence,
                alert.triggering_signal.signal_type,
                alert.triggering_signal.price,
                alert.research_summary,
                json.dumps(alert.key_findings),
                json.dumps(alert.risk_factors),
                alert.model_used,
                alert.correlated_at.isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def mark_telegram_sent(self, alert_id: int, sent_at: datetime | None = None) -> None:
        self._conn.execute(
            "UPDATE alerts SET telegram_sent = 1, telegram_sent_at = ?, telegram_error = NULL WHERE id = ?",
            ((sent_at or datetime.now(timezone.utc)).isoformat(), alert_id),
        )
        self._conn.commit()

    def mark_telegram_failed(self, alert_id: int, error: str) -> None:
        self._conn.execute(
            "UPDATE alerts SET telegram_error = ? WHERE id = ?",
            (error[:500], alert_id),
        )
        self._conn.commit()

    def recent(self, limit: int = 200) -> list[dict]:
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
        for row in tickers:
            latest = self._conn.execute(
                "SELECT action, severity FROM alerts WHERE ticker = ? "
                "ORDER BY correlated_at DESC, id DESC LIMIT 1",
                (row["ticker"],),
            ).fetchone()
            row["last_action"] = latest["action"]
            row["last_severity"] = latest["severity"]
        return tickers

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["key_findings"] = json.loads(d.pop("key_findings_json"))
    d["risk_factors"] = json.loads(d.pop("risk_factors_json"))
    d["telegram_sent"] = bool(d["telegram_sent"])
    return d
