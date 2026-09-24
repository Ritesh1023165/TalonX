"""
opportunity.db -- the durable, UNCAPPED candidate store. Single writer: DISCOVERY. Everyone else reads ``mode=ro``.

candidates        one row per identity (``<first window>:<SYMBOL>:<GAP_UP|GAP_DOWN>``); current lifecycle state,
                  first/last seen, phase, scores, reference, provenance, config identity. No notification state is
                  ever written here (that lives in notification.db) -- detection cannot depend on Telegram.
candidate_events  append-only lifecycle stream (monotonic ``seq``): NEW / UPGRADE / MATERIAL_UPDATE / INVALIDATED /
                  EXPIRED / REFERENCE_ROLLED. Every downstream component (evaluators, notifier) consumes it through its
                  own durable cursor, so each can restart independently without losing or duplicating work.
scans             one row per discovery evaluation (phase, capability, provider state, funnel, as-of).
symbol_latest     the latest observation per symbol (incl. rejection reason) -- "why was X not a candidate?"
near_misses       observations with |gap| >= the WATCH gap that were NOT alert-worthy (bounded forensic trail).
"""
from __future__ import annotations

from pathlib import Path

from talonx_opportunity.db import connect, j, root_dir, unj

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY, window_id TEXT, symbol TEXT, family TEXT, direction TEXT, state TEXT,
    classification TEXT, first_seen_utc TEXT, first_seen_phase TEXT, first_data_as_of_utc TEXT,
    last_updated_utc TEXT, last_phase TEXT, last_observed_utc TEXT, last_active_window_id TEXT,
    last_event_utc TEXT, last_event_score REAL, last_event_gap REAL,
    first_score REAL, last_score REAL, max_score REAL, first_gap_pct REAL, last_gap_pct REAL,
    ref_price REAL, prev_close REAL, reference_session TEXT, horizons_json TEXT, catalyst TEXT,
    liquidity_json TEXT, provenance_json TEXT, config_version TEXT, config_fp TEXT, in_v2_scope INTEGER,
    closed_reason TEXT);
CREATE INDEX IF NOT EXISTS ix_cand_state ON candidates(state);
CREATE INDEX IF NOT EXISTS ix_cand_sym ON candidates(symbol);
CREATE TABLE IF NOT EXISTS candidate_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, candidate_id TEXT, window_id TEXT, symbol TEXT,
    at_utc TEXT, data_as_of_utc TEXT, phase TEXT, event_type TEXT, from_state TEXT, to_state TEXT,
    classification TEXT, score REAL, gap_pct REAL, last_price REAL, reason TEXT, features_json TEXT,
    score_json TEXT, catalyst TEXT, provenance_json TEXT, config_fp TEXT);
CREATE TABLE IF NOT EXISTS scans (
    scan_id TEXT PRIMARY KEY, window_id TEXT, decision_utc TEXT, data_as_of_utc TEXT, phase TEXT, state TEXT,
    capability_json TEXT, funnel_json TEXT, duration_s REAL, config_fp TEXT);
CREATE TABLE IF NOT EXISTS symbol_latest (
    window_id TEXT, symbol TEXT, decision_utc TEXT, phase TEXT, cls TEXT, gap_pct REAL, score REAL,
    PRIMARY KEY (window_id, symbol));
CREATE TABLE IF NOT EXISTS near_misses (
    window_id TEXT, decision_utc TEXT, symbol TEXT, phase TEXT, cls TEXT, gap_pct REAL, score REAL,
    PRIMARY KEY (window_id, decision_utc, symbol));
"""

ACTIVE = ("WATCH", "BULLISH_SETUP", "BEARISH_SETUP")
CLOSED_STATES = ("INVALIDATED", "EXPIRED")
VOCAB = {"WATCH": "WATCH", "BULLISH_SETUP": "BULLISH", "BEARISH_SETUP": "BEARISH", "INVALIDATED": "INVALIDATED",
         "EXPIRED": "EXPIRED"}


def opportunity_db(root=None) -> Path:
    return root_dir(root) / "opportunity.db"


class OpportunityStore:
    def __init__(self, root=None, *, readonly: bool = False):
        self.con = connect(opportunity_db(root), readonly=readonly, schema=None if readonly else SCHEMA)

    def active_candidates(self) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM candidates WHERE state NOT IN ('INVALIDATED','EXPIRED') ORDER BY first_seen_utc")]

    def candidate(self, cid: str) -> dict | None:
        r = self.con.execute("SELECT * FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        return dict(r) if r else None

    def candidates(self, window_id: str | None = None) -> list[dict]:
        if window_id:
            return [dict(r) for r in self.con.execute(
                "SELECT * FROM candidates WHERE window_id=? OR last_active_window_id=? ORDER BY first_seen_utc",
                (window_id, window_id))]
        return [dict(r) for r in self.con.execute("SELECT * FROM candidates ORDER BY first_seen_utc")]

    def events_after(self, seq: int, limit: int = 500) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM candidate_events WHERE seq > ? ORDER BY seq LIMIT ?", (seq, limit))]

    def max_seq(self) -> int:
        return int(self.con.execute("SELECT COALESCE(MAX(seq),0) FROM candidate_events").fetchone()[0])

    def upsert_candidate(self, row: dict) -> None:
        cols = list(row)
        self.con.execute(f"INSERT INTO candidates ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                         f"ON CONFLICT(candidate_id) DO UPDATE SET "
                         + ",".join(f"{c}=excluded.{c}" for c in cols if c != "candidate_id"),
                         [row[c] for c in cols])

    def add_event(self, ev: dict) -> None:
        cols = list(ev)
        self.con.execute(f"INSERT OR IGNORE INTO candidate_events ({','.join(cols)}) VALUES "
                         f"({','.join('?' * len(cols))})", [ev[c] for c in cols])

    def add_scan(self, scan: dict) -> None:
        self.con.execute("INSERT OR REPLACE INTO scans VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (scan["scan_id"], scan["window_id"], scan["decision_utc"], scan.get("data_as_of_utc"),
                          scan["phase"], scan["state"], j(scan.get("capability")), j(scan.get("funnel")),
                          scan.get("duration_s"), scan.get("config_fp")))

    def last_scan(self) -> dict | None:
        r = self.con.execute("SELECT * FROM scans ORDER BY decision_utc DESC LIMIT 1").fetchone()
        if not r:
            return None
        d = dict(r)
        d["funnel"], d["capability"] = unj(d.pop("funnel_json"), {}), unj(d.pop("capability_json"), {})
        return d

    def commit(self) -> None:
        self.con.commit()

    def close(self) -> None:
        self.con.close()
