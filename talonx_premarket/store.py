"""
The research lane's own SQLite store (``premarket_research.db``). Never a V2 ledger, never a
V2 outbox. Tables: scans (funnel per scan), candidates (dedup state per identity), alerts
(every alert event, delivered or not), outcomes (post-open tracking).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    scan_id TEXT PRIMARY KEY, session_date TEXT, decision_utc TEXT, data_as_of_utc TEXT, phase TEXT,
    mode TEXT, config_fingerprint TEXT, funnel_json TEXT, duration_s REAL, requests INTEGER, errors_json TEXT);
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY, session_date TEXT, symbol TEXT, family TEXT, state TEXT,
    first_alert_utc TEXT, last_alert_utc TEXT, last_alert_score REAL, last_alert_gap REAL,
    ref_price REAL, prev_close REAL, delivered INTEGER DEFAULT 0, updated_utc TEXT);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY, candidate_id TEXT, session_date TEXT, symbol TEXT, alert_type TEXT,
    decision_utc TEXT, data_as_of_utc TEXT, score REAL, gap_pct REAL, ref_price REAL, text TEXT,
    features_json TEXT, score_json TEXT, catalyst TEXT, routed TEXT, mode TEXT);
CREATE TABLE IF NOT EXISTS outcomes (
    candidate_id TEXT PRIMARY KEY, session_date TEXT, symbol TEXT, family TEXT, ref_price REAL,
    status TEXT, open_px REAL, px_30m REAL, px_1h REAL, close_px REAL, mfe_pct REAL, mae_pct REAL,
    open_ret_pct REAL, ret_30m_pct REAL, ret_1h_pct REAL, close_ret_pct REAL, updated_utc TEXT, detail_json TEXT);
"""


class ResearchStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.path, timeout=10.0)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(_SCHEMA)
        self._con.commit()

    @contextmanager
    def tx(self):
        try:
            yield self._con
            self._con.commit()
        except Exception:
            self._con.rollback()
            raise

    def close(self) -> None:
        self._con.close()

    # -- candidates ------------------------------------------------------------------
    def get_candidate(self, cid: str) -> dict | None:
        r = self._con.execute("SELECT * FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        return dict(r) if r else None

    def candidates_for(self, session_date: str) -> list[dict]:
        return [dict(r) for r in self._con.execute(
            "SELECT * FROM candidates WHERE session_date=? ORDER BY first_alert_utc, symbol", (session_date,))]

    def upsert_candidate(self, row: dict) -> None:
        cols = list(row)
        with self.tx() as c:
            c.execute(f"INSERT INTO candidates ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                      f"ON CONFLICT(candidate_id) DO UPDATE SET "
                      + ",".join(f"{k}=excluded.{k}" for k in cols if k != "candidate_id"),
                      [row[k] for k in cols])

    def count_new_alerts(self, session_date: str) -> int:
        return int(self._con.execute("SELECT COUNT(*) FROM candidates WHERE session_date=? AND first_alert_utc "
                                     "IS NOT NULL", (session_date,)).fetchone()[0])

    # -- alerts / scans / outcomes ------------------------------------------------------
    def add_alert(self, row: dict) -> None:
        cols = list(row)
        with self.tx() as c:
            c.execute(f"INSERT OR IGNORE INTO alerts ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [row[k] if not isinstance(row[k], (dict, list)) else json.dumps(row[k]) for k in cols])

    def alerts_for(self, session_date: str) -> list[dict]:
        return [dict(r) for r in self._con.execute(
            "SELECT * FROM alerts WHERE session_date=? ORDER BY decision_utc, symbol", (session_date,))]

    def add_scan(self, row: dict) -> None:
        cols = list(row)
        with self.tx() as c:
            c.execute(f"INSERT OR REPLACE INTO scans ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [json.dumps(row[k]) if isinstance(row[k], (dict, list)) else row[k] for k in cols])

    def scans_for(self, session_date: str) -> list[dict]:
        return [dict(r) for r in self._con.execute(
            "SELECT * FROM scans WHERE session_date=? ORDER BY decision_utc", (session_date,))]

    def upsert_outcome(self, row: dict) -> None:
        cols = list(row)
        with self.tx() as c:
            c.execute(f"INSERT OR REPLACE INTO outcomes ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [json.dumps(row[k]) if isinstance(row[k], (dict, list)) else row[k] for k in cols])

    def outcomes_for(self, session_date: str) -> list[dict]:
        return [dict(r) for r in self._con.execute(
            "SELECT * FROM outcomes WHERE session_date=? ORDER BY symbol", (session_date,))]
