"""Task 99A S4/S5 -- isolated, additive persistence for restored alerts and
experimental paper trades.

Own SQLite file (default ``~/.talonx/experimental/exp_alerts.db``), WAL +
``threading.Lock``, ``CREATE TABLE IF NOT EXISTS`` only -- same convention as
every other store in this repo. Never opens the CONTROL / PIV / dispatch /
paper databases. Deterministic string primary keys (``D…`` / ``X…`` / ``R…`` /
``E…``) so an idempotent re-insert is a no-op and Telegram never double-sends.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DDL = """
CREATE TABLE IF NOT EXISTS directional_alerts (
    alert_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    profile TEXT NOT NULL,
    horizon TEXT,
    setup_type TEXT,
    setup_score INTEGER,
    session TEXT,
    price REAL,
    trade_gate_status TEXT,
    trade_gate_reject_reason TEXT,
    risk_reward_ratio REAL,
    stop_price REAL,
    target_price REAL,
    geometry_path TEXT,
    message TEXT,
    evidence TEXT,
    bar_timestamp TEXT,
    generated_at TEXT,
    sent INTEGER NOT NULL DEFAULT 0,
    send_error TEXT,
    suppressed_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experimental_trades (
    trade_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    profile TEXT NOT NULL,
    side TEXT NOT NULL,
    entry REAL, exit REAL, stop REAL, target REAL, quantity REAL,
    exit_reason TEXT,
    gross_pnl REAL, est_costs REAL, net_pnl REAL, r_multiple REAL, mfe REAL, mae REAL,
    admitted_by TEXT,
    opened_at TEXT, closed_at TEXT,
    sent INTEGER NOT NULL DEFAULT 0,
    send_error TEXT,
    suppressed_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS radar_alerts (
    radar_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    company TEXT,
    reporting_when TEXT,
    current_price REAL,
    holding_status TEXT,
    context TEXT,
    sent INTEGER NOT NULL DEFAULT 0,
    send_error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_updates (
    event_id TEXT PRIMARY KEY,
    source_event_id TEXT,
    symbol TEXT NOT NULL,
    company TEXT,
    event_type TEXT,
    accepted_at TEXT,
    session_bucket TEXT,
    current_price REAL,
    material_changes TEXT,
    insider_context TEXT,
    significance_band TEXT,
    significance_reasons TEXT,
    accession TEXT,
    evidence_url TEXT,
    sent INTEGER NOT NULL DEFAULT 0,
    send_error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dispatch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT,
    at TEXT NOT NULL
);
"""

_PK = {
    "directional_alerts": "alert_id",
    "experimental_trades": "trade_id",
    "radar_alerts": "radar_id",
    "event_updates": "event_id",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExperimentalAlertStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_DDL)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # writes (all idempotent on the deterministic PK)
    # ------------------------------------------------------------------
    def record_directional(self, alert: Any) -> bool:
        d = alert if isinstance(alert, dict) else alert.model_dump(mode="json")
        row = {
            "alert_id": d["alert_id"], "symbol": d["symbol"], "direction": str(d["direction"]),
            "profile": d["profile"], "horizon": d.get("horizon", "INTRADAY_SHORT"),
            "setup_type": d.get("setup_type"), "setup_score": d.get("setup_score"),
            "session": str(d.get("session")), "price": d.get("price"),
            "trade_gate_status": str(d.get("trade_gate_status")),
            "trade_gate_reject_reason": d.get("trade_gate_reject_reason"),
            "risk_reward_ratio": d.get("risk_reward_ratio"), "stop_price": d.get("stop_price"),
            "target_price": d.get("target_price"), "geometry_path": d.get("geometry_path"),
            "message": d.get("message"),
            "evidence": json.dumps(d.get("evidence") or {}),
            "bar_timestamp": str(d.get("bar_timestamp")), "generated_at": str(d.get("generated_at")),
            "created_at": _now(),
        }
        return self._insert_or_ignore("directional_alerts", row)

    def record_trade(self, trade: dict) -> bool:
        row = {k: trade.get(k) for k in (
            "trade_id", "symbol", "profile", "side", "entry", "exit", "stop", "target",
            "quantity", "exit_reason", "gross_pnl", "est_costs", "net_pnl", "r_multiple",
            "mfe", "mae", "admitted_by", "opened_at", "closed_at",
        )}
        row["profile"] = row.get("profile") or "EXPERIMENTAL_RELAXED_V1"
        row["created_at"] = _now()
        return self._insert_or_ignore("experimental_trades", row)

    def update_trade(self, trade_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE experimental_trades SET {sets} WHERE trade_id=?",
                (*fields.values(), trade_id),
            )
            self._conn.commit()

    def record_radar(self, row: dict) -> bool:
        r = {k: row.get(k) for k in (
            "radar_id", "symbol", "company", "reporting_when", "current_price",
            "holding_status", "context",
        )}
        r["created_at"] = _now()
        return self._insert_or_ignore("radar_alerts", r)

    def record_event_update(self, row: dict) -> bool:
        r = {k: row.get(k) for k in (
            "event_id", "source_event_id", "symbol", "company", "event_type", "accepted_at",
            "session_bucket", "current_price", "insider_context", "significance_band",
            "accession", "evidence_url",
        )}
        r["material_changes"] = json.dumps(row.get("material_changes") or [])
        r["significance_reasons"] = json.dumps(row.get("significance_reasons") or [])
        r["created_at"] = _now()
        return self._insert_or_ignore("event_updates", r)

    def _insert_or_ignore(self, table: str, row: dict) -> bool:
        cols = ", ".join(row)
        ph = ", ".join("?" * len(row))
        with self._lock:
            cur = self._conn.execute(
                f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({ph})", tuple(row.values())
            )
            self._conn.commit()
            return cur.rowcount == 1

    # ------------------------------------------------------------------
    # delivery bookkeeping
    # ------------------------------------------------------------------
    def mark_sent(self, table: str, public_id: str) -> None:
        self._set(table, public_id, sent=1, send_error=None)
        self.log(public_id, table, "SENT")

    def mark_send_error(self, table: str, public_id: str, err: str) -> None:
        self._set(table, public_id, send_error=err)
        self.log(public_id, table, "SEND_ERROR", err)

    def mark_suppressed(self, table: str, public_id: str, reason: str) -> None:
        self._set(table, public_id, suppressed_reason=reason)
        self.log(public_id, table, "SUPPRESSED", reason)

    def _set(self, table: str, public_id: str, **fields: Any) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE {table} SET {sets} WHERE {_PK[table]}=?",
                (*fields.values(), public_id),
            )
            self._conn.commit()

    def log(self, public_id: str, kind: str, event: str, detail: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO dispatch_log (public_id, kind, event, detail, at) VALUES (?,?,?,?,?)",
                (public_id, kind, event, detail, _now()),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def get_directional(self, alert_id: str) -> dict | None:
        return self._one("directional_alerts", alert_id)

    def get_trade(self, trade_id: str) -> dict | None:
        return self._one("experimental_trades", trade_id)

    def get_radar(self, radar_id: str) -> dict | None:
        return self._one("radar_alerts", radar_id)

    def get_event_update(self, event_id: str) -> dict | None:
        row = self._one("event_updates", event_id)
        if not row:
            return row
        for k in ("material_changes", "significance_reasons"):
            if isinstance(row.get(k), str):
                try:
                    row[k] = json.loads(row[k])
                except ValueError:
                    row[k] = []
        return row

    def _one(self, table: str, pk: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute(f"SELECT * FROM {table} WHERE {_PK[table]}=?", (pk,))
            r = cur.fetchone()
        return dict(r) if r is not None else None

    def pending(self, table: str) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                f"SELECT * FROM {table} WHERE sent=0 AND COALESCE(suppressed_reason,'')=''"
                if table in ("directional_alerts", "experimental_trades")
                else f"SELECT * FROM {table} WHERE sent=0"
            )
            return [dict(r) for r in cur.fetchall()]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        with self._lock:
            for t in _PK:
                out[t] = self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                out[f"{t}_sent"] = self._conn.execute(f"SELECT COUNT(*) FROM {t} WHERE sent=1").fetchone()[0]
        return out

    def dispatch_log(self, limit: int = 200) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM dispatch_log ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in cur.fetchall()]

    def purge_older_than(self, cutoff: datetime) -> int:
        iso = cutoff.astimezone(timezone.utc).isoformat()
        n = 0
        with self._lock:
            for t in _PK:
                n += self._conn.execute(f"DELETE FROM {t} WHERE created_at < ?", (iso,)).rowcount
            self._conn.execute("DELETE FROM dispatch_log WHERE at < ?", (iso,))
            self._conn.commit()
        return n
