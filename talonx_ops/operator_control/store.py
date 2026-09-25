"""Durable operator state: operator_universe, symbol_exclusions, operator_audit (single SQLite file, WAL)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(?:[.\-][A-Z]{1,2})?$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS operator_universe (
    symbol TEXT PRIMARY KEY, status TEXT NOT NULL,           -- ACTIVE | REMOVED
    added_at TEXT, removed_at TEXT, changed_by TEXT, reason TEXT, source TEXT, activation TEXT, seq INTEGER
);
CREATE TABLE IF NOT EXISTS symbol_exclusions (
    symbol TEXT PRIMARY KEY, status TEXT NOT NULL,           -- EXCLUDED | RESTORED
    excluded_at TEXT, restored_at TEXT, changed_by TEXT, reason TEXT, activation TEXT, seq INTEGER
);
CREATE TABLE IF NOT EXISTS operator_audit (
    command_id TEXT PRIMARY KEY, at_utc TEXT, actor TEXT, chat TEXT, authorized INTEGER, command TEXT,
    symbol TEXT, before_state TEXT, after_state TEXT, mode TEXT, result TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def db_path(path=None) -> Path:
    return Path(path or os.environ.get("TALONX_OPERATOR_DB") or (REPO_ROOT / "operator_control.db"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_symbol(raw: str | None) -> tuple[str | None, str | None]:
    """(symbol, error). Trims + uppercases; keeps one '.'/'-' class suffix (BRK.B, BF-B); rejects anything else."""
    if raw is None or not str(raw).strip():
        return None, "missing symbol"
    s = str(raw).strip().upper().lstrip("$")
    if not SYMBOL_RE.match(s):
        return None, f"invalid symbol {s[:12]!r} (expected 1-5 letters, optional .X or -X class suffix)"
    return s, None


class OperatorStore:
    def __init__(self, path=None, *, readonly: bool = False):
        self.path = db_path(path)
        if readonly:
            self.con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5) if self.path.exists() else None
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.con = sqlite3.connect(self.path, timeout=10)
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.executescript(SCHEMA)
        if self.con is not None:
            self.con.row_factory = sqlite3.Row

    def _next_seq(self) -> int:
        r = self.con.execute("SELECT v FROM meta WHERE k='seq'").fetchone()
        n = int(r[0]) + 1 if r else 1
        self.con.execute("INSERT OR REPLACE INTO meta VALUES ('seq', ?)", (str(n),))
        return n

    # -- reads (safe on a missing / readonly store) --------------------------------------------------------------------
    def universe_row(self, sym: str) -> dict | None:
        if self.con is None:
            return None
        r = self.con.execute("SELECT * FROM operator_universe WHERE symbol=?", (sym,)).fetchone()
        return dict(r) if r else None

    def exclusion_row(self, sym: str) -> dict | None:
        if self.con is None:
            return None
        r = self.con.execute("SELECT * FROM symbol_exclusions WHERE symbol=?", (sym,)).fetchone()
        return dict(r) if r else None

    def added(self) -> set[str]:
        return set() if self.con is None else {r[0] for r in self.con.execute(
            "SELECT symbol FROM operator_universe WHERE status='ACTIVE'")}

    def removed(self) -> set[str]:
        return set() if self.con is None else {r[0] for r in self.con.execute(
            "SELECT symbol FROM operator_universe WHERE status='REMOVED'")}

    def excluded(self) -> set[str]:
        return set() if self.con is None else {r[0] for r in self.con.execute(
            "SELECT symbol FROM symbol_exclusions WHERE status='EXCLUDED'")}

    def exclusion_since(self, sym: str) -> str | None:
        r = self.exclusion_row(sym)
        return r["excluded_at"] if r and r["status"] == "EXCLUDED" else None

    # -- writes ---------------------------------------------------------------------------------------------------------
    def set_universe(self, sym: str, status: str, *, by: str, reason: str | None, activation: str) -> None:
        with self.con:
            prev = self.universe_row(sym)
            t = now_iso()
            self.con.execute(
                "INSERT OR REPLACE INTO operator_universe VALUES (?,?,?,?,?,?,?,?,?)",
                (sym, status, t if status == "ACTIVE" else (prev or {}).get("added_at"),
                 t if status == "REMOVED" else None, by, reason, "OPERATOR", activation, self._next_seq()))

    def set_exclusion(self, sym: str, status: str, *, by: str, reason: str | None, activation: str) -> None:
        with self.con:
            prev = self.exclusion_row(sym)
            t = now_iso()
            self.con.execute(
                "INSERT OR REPLACE INTO symbol_exclusions VALUES (?,?,?,?,?,?,?,?)",
                (sym, status, t if status == "EXCLUDED" else (prev or {}).get("excluded_at"),
                 t if status == "RESTORED" else None, by, reason, activation, self._next_seq()))

    def audit(self, *, actor: str, chat: str, authorized: bool, command: str, symbol: str | None,
              before: dict | None, after: dict | None, mode: str, result: str, reason: str = "") -> str:
        cid = uuid.uuid4().hex[:16]
        with self.con:
            self.con.execute("INSERT INTO operator_audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (cid, now_iso(), actor, chat, int(authorized), command[:200], symbol,
                              json.dumps(before, default=str) if before else None,
                              json.dumps(after, default=str) if after else None, mode, result, reason[:300]))
        return cid
