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
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT, session_date TEXT, pid INTEGER, started_utc TEXT, mode TEXT,
    config_fingerprint TEXT, delivery_json TEXT, ended_utc TEXT, end_state TEXT);
"""
# additive columns for DBs created before the hardening pass (idempotent)
_MIGRATIONS = (
    ("alerts", "delivery_state", "TEXT"),          # RECORDED_NOT_DELIVERED | SUPPRESSED | PENDING | SENT | FAILED | ...
    ("alerts", "delivery_updated_utc", "TEXT"),
)


class ResearchStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.path, timeout=10.0)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(_SCHEMA)
        for table, col, typ in _MIGRATIONS:
            cols = {r[1] for r in self._con.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self._con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
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

    def persist_decision(self, alert: dict, candidate: dict) -> None:
        """Alert row + candidate row in ONE transaction (all or nothing)."""
        acols, ccols = list(alert), list(candidate)
        enc = lambda v: json.dumps(v) if isinstance(v, (dict, list)) else v  # noqa: E731
        with self.tx() as c:
            c.execute(f"INSERT OR IGNORE INTO alerts ({','.join(acols)}) VALUES ({','.join('?' * len(acols))})",
                      [enc(alert[k]) for k in acols])
            c.execute(f"INSERT INTO candidates ({','.join(ccols)}) VALUES ({','.join('?' * len(ccols))}) "
                      f"ON CONFLICT(candidate_id) DO UPDATE SET "
                      + ",".join(f"{k}=excluded.{k}" for k in ccols if k != "candidate_id"),
                      [candidate[k] for k in ccols])

    def set_routed(self, alert_id: str, routed: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE alerts SET routed=? WHERE alert_id=?", (routed, alert_id))

    def set_delivery_state(self, alert_id: str, state: str, at_utc: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE alerts SET delivery_state=?, delivery_updated_utc=? WHERE alert_id=?",
                      (state, at_utc, alert_id))
            if state == "SENT":
                c.execute("UPDATE candidates SET delivered=1 WHERE candidate_id="
                          "(SELECT candidate_id FROM alerts WHERE alert_id=?)", (alert_id,))

    def start_run(self, session_date: str, pid: int, started_utc: str, mode: str, fp: str, delivery: dict) -> int:
        with self.tx() as c:
            cur = c.execute("INSERT INTO runs (session_date, pid, started_utc, mode, config_fingerprint, delivery_json)"
                            " VALUES (?,?,?,?,?,?)", (session_date, pid, started_utc, mode, fp, json.dumps(delivery)))
            return int(cur.lastrowid)

    def end_run(self, run_id: int, ended_utc: str, end_state: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE runs SET ended_utc=?, end_state=? WHERE run_id=?", (ended_utc, end_state, run_id))

    def runs_for(self, session_date: str) -> list[dict]:
        return [dict(r) for r in self._con.execute("SELECT * FROM runs WHERE session_date=? ORDER BY run_id",
                                                   (session_date,))]

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
