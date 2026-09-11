"""Task 102 -- authoritative durable projection of the pre-market surface.

Task 100C found the pre-market movers (GAP_UP/GAP_DOWN, ABNORMAL_VOLUME,
BULLISH_WATCH/BEARISH_WATCH, coverage) were computed live by
``talonx_signals.run.ExperimentalLane.refresh_premarket()`` and held only in
memory -- no restart survival, no dashboard read after a lane restart.

This module is the smallest durable store for that state, in the same style as
``ExperimentalAlertStore``:

* own SQLite file (default ``~/.talonx/premarket/premarket_state.db``),
  WAL + ``threading.Lock`` + ``CREATE TABLE IF NOT EXISTS``.
* deterministic string PKs (``make_watch_id`` -> ``W`` + 16 hex) so re-running a
  refresh cycle is an idempotent upsert, never a duplicate.
* ``session_date`` (UTC date of ``bundle.as_of``) is both a column and part of
  every ``watch_id``'s hash input -> yesterday's ``GAP_UP MSFT`` can never
  appear as today's.
* ``read_only=True`` opens ``file:...?mode=ro`` and runs NO DDL -- the handle
  the dashboard read model uses.

It carries NO trading logic. The Experimental lane is the sole write owner; the
dashboard is a pure reader. A write failure is caught by the caller and never
affects a trading decision.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path.home() / ".talonx" / "premarket" / "premarket_state.db"

# Only these families are persisted -- the official pre-market classifications.
PERSISTED_KINDS = (
    "GAP_UP", "GAP_DOWN", "ABNORMAL_VOLUME", "BULLISH_WATCH", "BEARISH_WATCH",
    "RADAR", "EVENT_CONTEXT",
)

_DDL = """
CREATE TABLE IF NOT EXISTS premarket_sessions (
    session_date         TEXT PRIMARY KEY,
    generated_at         TEXT NOT NULL,
    last_updated_at      TEXT NOT NULL,
    watchlist_configured INTEGER,
    watchlist_active     INTEGER,
    watchlist_covered    INTEGER,
    notes_json           TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS premarket_events (
    watch_id          TEXT PRIMARY KEY,
    session_date      TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    kind              TEXT NOT NULL,
    bias              TEXT,
    reference_price   REAL,
    prev_close        REAL,
    gap_pct           REAL,
    relative_volume   REAL,
    detail            TEXT,
    reason_codes_json TEXT NOT NULL DEFAULT '[]',
    observed_at       TEXT,
    first_seen_at     TEXT NOT NULL,
    last_updated_at   TEXT NOT NULL,
    source            TEXT NOT NULL DEFAULT 'talonx_signals.premarket.PremarketWatchEngine',
    external_eligible INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'FRESH'
);
CREATE INDEX IF NOT EXISTS ix_pm_events_session ON premarket_events(session_date);
CREATE INDEX IF NOT EXISTS ix_pm_events_session_kind ON premarket_events(session_date, kind);
"""

# a session whose last write is older than this reads as STALE
SESSION_STALE_SECONDS = 45 * 60


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _session_date(dt: datetime) -> str:
    return _utc(dt).strftime("%Y-%m-%d")


def _age_seconds(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (_utc(now) - _utc(d)).total_seconds()
    except ValueError:
        return None


class PremarketStateStore:
    def __init__(self, db_path: str | Path | None = None, *, read_only: bool = False):
        self.db_path = str(db_path or _DEFAULT_PATH)
        self._read_only = read_only
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if read_only:
            if Path(self.db_path).exists():
                try:
                    self._conn = sqlite3.connect(
                        f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False, timeout=1.0
                    )
                    self._conn.row_factory = sqlite3.Row
                except sqlite3.Error:
                    self._conn = None
            return
        Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_DDL)
            self._conn.commit()

    # ------------------------------------------------------------------ write
    def upsert_bundle(self, bundle: Any, *, now: datetime | None = None) -> dict:
        """Persist a ``PremarketBundle`` (or an equivalent dict). Idempotent on
        each event's deterministic ``watch_id``. Returns a small summary."""
        if self._conn is None or self._read_only:
            raise RuntimeError("PremarketStateStore opened read-only")
        b = bundle if isinstance(bundle, dict) else bundle.model_dump(mode="json")
        as_of = b.get("as_of")
        as_of_dt = _utc(datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))) if as_of \
            else _utc(now or datetime.now(timezone.utc))
        sd = _session_date(as_of_dt)
        stamp = _utc(now or datetime.now(timezone.utc)).isoformat()

        families = ("radar", "gap_up", "gap_down", "abnormal_volume",
                    "bullish_watch", "bearish_watch", "event_context")
        events: list[dict] = []
        for fam in families:
            for w in (b.get(fam) or []):
                events.append(w if isinstance(w, dict) else w)

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO premarket_sessions
                    (session_date, generated_at, last_updated_at,
                     watchlist_configured, watchlist_active, watchlist_covered, notes_json)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(session_date) DO UPDATE SET
                    last_updated_at=excluded.last_updated_at,
                    watchlist_configured=excluded.watchlist_configured,
                    watchlist_active=excluded.watchlist_active,
                    watchlist_covered=excluded.watchlist_covered,
                    notes_json=excluded.notes_json
                """,
                (sd, stamp, stamp,
                 b.get("watchlist_configured"), b.get("watchlist_active"), b.get("watchlist_covered"),
                 json.dumps(list(b.get("notes") or []))),
            )
            n = 0
            for w in events:
                kind = str(w.get("kind") or "").split(".")[-1]
                if kind not in PERSISTED_KINDS:
                    continue
                wid = w.get("watch_id")
                if not wid:
                    continue
                # Task 104: PremarketWatch.relative_volume carries the RVOL
                # (== quant volume_surge_ratio) for ABNORMAL_VOLUME rows; NULL
                # for every other kind. Never fabricated -- absent stays NULL.
                rel_vol = w.get("relative_volume")
                self._conn.execute(
                    """
                    INSERT INTO premarket_events
                        (watch_id, session_date, symbol, kind, bias, reference_price, prev_close,
                         gap_pct, relative_volume, detail, reason_codes_json, observed_at,
                         first_seen_at, last_updated_at, source, external_eligible, status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,'FRESH')
                    ON CONFLICT(watch_id) DO UPDATE SET
                        reference_price=excluded.reference_price,
                        prev_close=excluded.prev_close,
                        gap_pct=excluded.gap_pct,
                        relative_volume=excluded.relative_volume,
                        detail=excluded.detail,
                        reason_codes_json=excluded.reason_codes_json,
                        observed_at=excluded.observed_at,
                        last_updated_at=excluded.last_updated_at,
                        status='FRESH'
                    """,
                    (wid, sd, str(w.get("symbol") or "").upper(), kind,
                     _bias_of(w), w.get("reference_price"), w.get("prev_close"),
                     w.get("gap_pct"), rel_vol, w.get("detail") or "",
                     json.dumps(list(w.get("reason_codes") or ())),
                     w.get("observed_at"), stamp, stamp,
                     w.get("source") or "talonx_signals.premarket.PremarketWatchEngine"),
                )
                n += 1
            self._conn.commit()
        return {"session_date": sd, "events_upserted": n, "sessions_touched": 1}

    def purge_sessions_before(self, session_date: str) -> int:
        """Opt-in only (mirrors ExperimentalAlertStore.purge_older_than). Not
        called by any default code path."""
        if self._conn is None or self._read_only:
            raise RuntimeError("read-only")
        with self._lock:
            c1 = self._conn.execute("DELETE FROM premarket_events WHERE session_date < ?", (session_date,)).rowcount
            self._conn.execute("DELETE FROM premarket_sessions WHERE session_date < ?", (session_date,))
            self._conn.commit()
        return c1

    # ------------------------------------------------------------------- read
    def current_session(self, now: datetime | None = None) -> dict:
        now = _utc(now or datetime.now(timezone.utc))
        today = _session_date(now)
        if self._conn is None:
            return {"status": "UNKNOWN", "session_date": None, "note": "premarket_state.db not present"}
        try:
            row = self._conn.execute(
                "SELECT * FROM premarket_sessions WHERE session_date=?", (today,)
            ).fetchone()
            if row is None:
                prev = self._conn.execute(
                    "SELECT session_date, last_updated_at FROM premarket_sessions "
                    "ORDER BY session_date DESC LIMIT 1"
                ).fetchone()
                return {
                    "status": "NO_SESSION_TODAY",
                    "session_date": None,
                    "today": today,
                    "last_session_date": prev["session_date"] if prev else None,
                    "note": "no pre-market session recorded for today (weekend / holiday / lane not run yet)",
                }
            age = _age_seconds(row["last_updated_at"], now)
            status = "ACTIVE" if (age is not None and age <= SESSION_STALE_SECONDS) else "STALE"
            return {
                "status": status,
                "session_date": row["session_date"],
                "generated_at": row["generated_at"],
                "last_updated_at": row["last_updated_at"],
                "last_updated_age_seconds": round(age) if age is not None else None,
                "watchlist_configured": row["watchlist_configured"],
                "watchlist_active": row["watchlist_active"],
                "watchlist_covered": row["watchlist_covered"],
                "notes": json.loads(row["notes_json"] or "[]"),
            }
        except sqlite3.Error as exc:
            return {"status": "UNKNOWN", "session_date": None, "note": f"read error: {exc!r}"}

    def events_for_session(self, session_date: str, *, limit_per_kind: int = 50) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        if self._conn is None or not session_date:
            return out
        try:
            rows = self._conn.execute(
                "SELECT * FROM premarket_events WHERE session_date=? ORDER BY kind, symbol", (session_date,)
            ).fetchall()
        except sqlite3.Error:
            return out
        for r in rows:
            d = dict(r)
            d["reason_codes"] = json.loads(d.pop("reason_codes_json", "[]") or "[]")
            out.setdefault(d["kind"], [])
            if len(out[d["kind"]]) < limit_per_kind:
                out[d["kind"]].append(d)
        return out

    def counts_for_session(self, session_date: str) -> dict[str, int]:
        if self._conn is None or not session_date:
            return {}
        try:
            rows = self._conn.execute(
                "SELECT kind, COUNT(*) n FROM premarket_events WHERE session_date=? GROUP BY kind",
                (session_date,),
            ).fetchall()
        except sqlite3.Error:
            return {}
        return {r["kind"]: int(r["n"]) for r in rows}

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None


def _bias_of(w: dict) -> str | None:
    kind = str(w.get("kind") or "").split(".")[-1]
    if kind in ("BULLISH_WATCH", "GAP_UP"):
        return "BULLISH"
    if kind in ("BEARISH_WATCH", "GAP_DOWN"):
        return "BEARISH"
    return w.get("bias")
