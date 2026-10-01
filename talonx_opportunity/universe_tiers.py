"""
DYNAMIC TRADABLE UNIVERSE (DTU_V1, 2026-09-30) -- which structurally eligible symbols receive FULL processing
(1-min bar ingestion, features, scoring, SEC lookups, lifecycle). Selection only: scoring, classification, lifecycle,
Signal promotion, Lab routing and the forward-alpha experiment are untouched.

Mode ``TALONX_DTU_MODE``: OFF (default) = exact identity (every eligible symbol, as before; this is the rollback);
ACTIVE = the effective active set below. Owner: DATA_INGESTION (single writer of market.db) builds the D-1 snapshot,
runs the lightweight event sweep, keeps durable promotions and resolves the active set BEFORE any fetch batch; DISCOVERY
reads that set (market.db, read-only) BEFORE features / scoring / SEC lookups.

States (every non-active symbol has an auditable reason):
  ACTIVE_CORE         V1-floor eligible, top CORE_SIZE by D-1 ADV20 (D-1 daily bars only; causal)
  EVENT_ELIGIBLE      V1-floor eligible, outside the Core (NOT excluded: promotable by a trigger)
  EVENT_PROMOTED      EVENT_ELIGIBLE with a live promotion (durable, reason + expiry)
  AUTO_EXCLUDED       structurally eligible but below V1's own hard floors (price < $1 or ADV20 < $1M at D-1): V1
                      can never create a candidate from it
  OPERATOR_ADDED      operator universe add (Sentinel) or V2 execution scope
  OPERATOR_EXCLUDED   operator exclusion (wins over automation, but never over position/intent safety)
Protection (keeps an otherwise inactive symbol ACTIVE; overrides demotion):
  V2 open position / pending entry intent (until resolved) -- overrides even OPERATOR_EXCLUDED
  open BULLISH/BEARISH setup identity (until invalidated / expired)
  PAPER_SIGNAL promoted this window (its INTRADAY/SAME_DAY evaluation horizon runs to the window's close)
  WATCH identity created in THIS window: rest of this window only (short, explicit; never carried to the next window)
Triggers (only study-supported sources): GAP (|latestTrade / V1 prev close - 1| >= 3 %, delayed_sip snapshot sweep,
V1 45-min stale gate; TTL = rest of window) and SEC_8K (EDGAR current-events feed; TTL 3 sessions, PROVISIONAL).
Relative-volume and Form 4 triggers are NOT implemented (no study evidence / no purchase codes universe-wide).
Fail-safe: DTU ACTIVE with a missing / stale / corrupt snapshot (or any resolution error) -> FULL eligible universe,
recorded as a fallback with its reason (never a silent partial universe).

DTU_V2 LIVE FLOOR (owner decision 2026-10-04; tradability / workload, NOT evidence of profitability). DTU_V1 plus two
inclusive floors every symbol must meet to be ADMISSIBLE as a new opportunity (Core / event tier):
  * as-traded close of the reference session D-1 (the previous completed XNYS regular session) >= USD 5;
  * ADV20 >= USD 20M, ADV20 = mean over the 20 completed XNYS sessions ending at D-1 of (close x volume) per session.
Data: Alpaca SIP ``1Day`` bars with ``adjustment=raw`` (as-traded; never mixed with the split-adjusted ``daily`` table),
fetched once per window by DATA_INGESTION into ``dtu_live_daily`` (end = session D 00:00 UTC - 1 s: no bar of D, no
partial session, no lookahead). Bar ``c`` = official consolidated regular-session close, ``v`` = Alpaca's consolidated
daily volume. All 20 sessions must have a valid bar (c > 0, v >= 0); otherwise an explicit LIVE_DATA_* reason. A failing
symbol is AUTO_EXCLUDED with its reason (data quality first, then price / liquidity / both). Management is unchanged:
V2 positions / intents, V2 execution scope, operator adds and open-candidate protections keep the symbol FETCHED, but
discovery never creates a NEW identity for a symbol outside the window's qualifying set (fail closed without a
snapshot of the active policy). ``TALONX_DTU_POLICY=DTU_V1`` is the rollback (bit-identical V1 fingerprint).
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODE_ENV = "TALONX_DTU_MODE"
OFF, ACTIVE = "OFF", "ACTIVE"
UTC = timezone.utc

CORE, EVENT_ELIGIBLE, EVENT_PROMOTED = "ACTIVE_CORE", "EVENT_ELIGIBLE", "EVENT_PROMOTED"
AUTO_EXCLUDED, OPERATOR_ADDED, OPERATOR_EXCLUDED, STRUCTURAL = ("AUTO_EXCLUDED", "OPERATOR_ADDED",
                                                                "OPERATOR_EXCLUDED", "STRUCTURALLY_EXCLUDED")
GAP, SEC_8K = "GAP_TRIGGER", "SEC_8K"
P_POSITION, P_SETUP, P_SIGNAL, P_WATCH = ("PROTECT_V2_POSITION_OR_INTENT", "PROTECT_OPEN_SETUP",
                                          "PROTECT_PAPER_SIGNAL_HORIZON", "PROTECT_WATCH_THIS_WINDOW")


@dataclass(frozen=True)
class DTUPolicy:
    version: str = "DTU_V1"
    core_size: int = 1200
    v1_min_price: float = 1.0                  # = PREMARKET_RESEARCH_V1.min_prev_close (no new floor)
    v1_min_adv20_usd: float = 1_000_000.0      # = PREMARKET_RESEARCH_V1.min_adv_dollar_20d
    gap_trigger_pct: float = 3.0
    gap_ttl: str = "REST_OF_WINDOW"
    stale_min: int = 45                        # V1 max_premarket_staleness_min
    sec_8k_ttl_sessions: int = 3               # PROVISIONAL (study architecture; not yet approved)
    watch_protection: str = "REST_OF_CREATION_WINDOW"
    sweep_every_s: int = 60
    edgar_every_s: int = 300
    snapshot_basis: str = "D-1 daily bars (market.db daily) -> price, ADV20; V1 floors; ADV20 rank"

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


DTU_V1 = DTUPolicy()


@dataclass(frozen=True)
class LiveFloorPolicy(DTUPolicy):
    """DTU_V1 + the owner's live-universe floors (both inclusive). A subclass, so DTU_V1's fingerprint is unchanged."""
    version: str = "DTU_V2_LIVE_FLOOR"
    live_min_close_usd: float = 5.0
    live_min_adv20_usd: float = 20_000_000.0
    live_sessions: int = 20
    live_basis: str = ("Alpaca SIP 1Day adjustment=raw: as-traded official close of D-1; ADV20 = mean(close x volume) "
                       "over the 20 completed XNYS sessions ending at D-1, all 20 required; floors inclusive")


DTU_V2 = LiveFloorPolicy()
POLICY_ENV = "TALONX_DTU_POLICY"
POLICIES = {"DTU_V1": DTU_V1, "DTU_V2": DTU_V2}
DEFAULT_POLICY = "DTU_V2"

# live-floor reason codes (mutually exclusive; data quality is decided first, then the two thresholds)
L_PRICE, L_LIQ, L_BOTH = "LIVE_BELOW_CLOSE_5", "LIVE_BELOW_ADV20_20M", "LIVE_BELOW_CLOSE_5_AND_ADV20_20M"
D_FETCH, D_NONE, D_STALE, D_INSUFF, D_INVALID = ("LIVE_DATA_FETCH_FAILED", "LIVE_DATA_NO_HISTORY",
                                                 "LIVE_DATA_STALE_NO_D1_BAR", "LIVE_DATA_INSUFFICIENT",
                                                 "LIVE_DATA_INVALID_BAR")


def policy_from_env(env=None) -> DTUPolicy:
    name = str((env if env is not None else os.environ).get(POLICY_ENV, DEFAULT_POLICY)).strip().upper() \
        or DEFAULT_POLICY
    if name not in POLICIES:
        raise SystemExit(f"{POLICY_ENV}={name!r}: allowed {' | '.join(POLICIES)}")
    return POLICIES[name]


def has_live_floor(policy: DTUPolicy) -> bool:
    return isinstance(policy, LiveFloorPolicy)


def completed_sessions(reference_session: str, n: int) -> list[str]:
    """The ``n`` completed XNYS sessions ending at (and including) ``reference_session`` (early closes included)."""
    from talonx_premarket.session import _xnys
    return [d.date().isoformat() for d in _xnys().sessions_window(reference_session, -n)]


def live_eligibility(bars: list[dict] | None, sessions: list[str], policy: LiveFloorPolicy
                     ) -> tuple[float | None, float | None, int, str]:
    """(as-traded D-1 close, ADV20, valid observations, reason) -- reason '' = passes both floors. ``sessions`` are the
    required completed sessions (oldest .. D-1); a bar dated outside them (a later / partial / non-session bar) is
    ignored, so nothing after D-1 can leak in."""
    want = set(sessions)
    by = {str(b.get("t", ""))[:10]: b for b in (bars or []) if str(b.get("t", ""))[:10] in want}
    if not by:
        return None, None, 0, D_NONE
    dv: dict[str, float] = {}
    for d, b in by.items():
        try:
            c, v = float(b["c"]), float(b["v"])
        except (KeyError, TypeError, ValueError):
            return None, None, 0, f"{D_INVALID}:{d}"
        if not (math.isfinite(c) and math.isfinite(v) and c > 0 and v >= 0):
            return None, None, 0, f"{D_INVALID}:{d}"
        dv[d] = c * v
    ref = sessions[-1]
    if ref not in dv:
        return None, None, len(dv), D_STALE
    close = float(by[ref]["c"])
    if len(dv) < policy.live_sessions:
        return close, None, len(dv), f"{D_INSUFF}_{len(dv)}_OF_{policy.live_sessions}"
    adv = sum(dv.values()) / len(dv)
    low_p, low_l = close < policy.live_min_close_usd, adv < policy.live_min_adv20_usd
    return close, adv, len(dv), (L_BOTH if low_p and low_l else L_PRICE if low_p else L_LIQ if low_l else "")


def floor_category(state: str, reason: str) -> str:
    """Mutually exclusive report bucket of one snapshot row."""
    if state in (CORE, EVENT_ELIGIBLE):
        return "QUALIFYING"
    if state == STRUCTURAL:
        return "STRUCTURAL"
    r = reason or ""
    if r.startswith("LIVE_DATA_"):
        return "DATA_QUALITY"
    return {L_PRICE: "PRICE_ONLY", L_LIQ: "LIQUIDITY_ONLY", L_BOTH: "PRICE_AND_LIQUIDITY"}.get(r, "RETAINED_V1_RULE")


def mode(env=None) -> str:
    m = str((env if env is not None else os.environ).get(MODE_ENV, OFF)).strip().upper() or OFF
    if m not in (OFF, ACTIVE):
        raise SystemExit(f"{MODE_ENV}={m!r}: allowed OFF | ACTIVE")
    return m


SCHEMA = """
CREATE TABLE IF NOT EXISTS dtu_snapshots (window_id TEXT PRIMARY KEY, snapshot_version TEXT, reference_session TEXT,
    created_utc TEXT, core_size INTEGER, counts_json TEXT, policy_fp TEXT);
CREATE TABLE IF NOT EXISTS dtu_snapshot (window_id TEXT, symbol TEXT, state TEXT, reason TEXT, core_rank INTEGER,
    price REAL, prev_close REAL, adv20 REAL, cik TEXT, snapshot_version TEXT, PRIMARY KEY (window_id, symbol));
CREATE TABLE IF NOT EXISTS dtu_promotions (window_id TEXT, symbol TEXT, reason TEXT, started_utc TEXT,
    expires_utc TEXT, source_event_id TEXT, snapshot_version TEXT, state_version TEXT, detail_json TEXT,
    PRIMARY KEY (window_id, symbol, reason));
CREATE TABLE IF NOT EXISTS dtu_active (window_id TEXT, cycle_utc TEXT, n_active INTEGER, counts_json TEXT,
    symbols_json TEXT, fallback_reason TEXT, policy_fp TEXT, PRIMARY KEY (window_id, cycle_utc));
CREATE TABLE IF NOT EXISTS dtu_transitions (id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT, window_id TEXT,
    symbol TEXT, from_state TEXT, to_state TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS dtu_sweeps (id INTEGER PRIMARY KEY AUTOINCREMENT, window_id TEXT, at_utc TEXT,
    symbols INTEGER, requests INTEGER, duration_s REAL, usable INTEGER, gap_promotions INTEGER,
    sec8k_promotions INTEGER, errors TEXT);
CREATE TABLE IF NOT EXISTS dtu_edgar (accession TEXT PRIMARY KEY, cik TEXT, symbol TEXT, updated_utc TEXT,
    seen_utc TEXT);
CREATE TABLE IF NOT EXISTS dtu_live_daily (window_id TEXT, symbol TEXT, bars_json TEXT, PRIMARY KEY (window_id, symbol));
CREATE TABLE IF NOT EXISTS dtu_live_daily_state (window_id TEXT PRIMARY KEY, fetched_utc TEXT, sessions_json TEXT,
    start_utc TEXT, end_utc TEXT, failed_json TEXT, requests INTEGER, source TEXT);
"""


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


# ============================================================================================================ pure
def classify_members(members: list[dict], daily: dict[str, list[dict]], reference_session: str,
                     policy: DTUPolicy = DTU_V1, *, live: dict[str, list[dict]] | None = None,
                     live_failed: set[str] | frozenset = frozenset(), sessions: list[str] | None = None) -> list[dict]:
    """D-1 snapshot rows (deterministic): structural bucket, V1 floors, ADV20 rank, Core. Uses only daily bars dated
    <= the reference session (causal). A live-floor policy additionally needs ``live`` (as-traded raw daily bars),
    ``live_failed`` (symbols whose raw fetch failed) and ``sessions`` (the required completed sessions ending at D-1);
    its rows carry price / adv20 = the as-traded live values (prev_close stays the V1 reference close: gap basis)."""
    floor = has_live_floor(policy)
    if floor and (live is None or not sessions or len(sessions) != policy.live_sessions
                  or sessions[-1] != reference_session):
        raise ValueError("live-floor policy needs live bars and the completed sessions ending at the reference session")
    rows = []
    for m in members:
        s = m["symbol"]
        bars = sorted((b for b in daily.get(s, []) if str(b["t"])[:10] <= reference_session), key=lambda b: b["t"])
        last20 = bars[-20:]
        prev_close = float(bars[-1]["c"]) if bars and str(bars[-1]["t"])[:10] == reference_session else None
        price = float(bars[-1]["c"]) if bars else None
        adv = sum(float(b["v"]) * float(b["c"]) for b in last20) / len(last20) if last20 else None
        lprice = ladv = None
        lreason = ""
        if floor and m.get("status") == "ELIGIBLE":
            if s in live_failed:
                lreason = D_FETCH
            else:
                lprice, ladv, _, lreason = live_eligibility(live.get(s), sessions, policy)
        if m.get("status") != "ELIGIBLE":
            st, why = STRUCTURAL, f"STRUCTURAL:{m.get('reason') or 'EXCLUDED'}"
        elif lreason:                                  # live floor: data quality, then price / liquidity / both
            st, why, price, adv = AUTO_EXCLUDED, lreason, lprice, ladv
        elif price is None or adv is None:
            st, why = AUTO_EXCLUDED, "NO_D1_DAILY_HISTORY"
        elif price < policy.v1_min_price:
            st, why = AUTO_EXCLUDED, "BELOW_V1_PRICE_FLOOR"
        elif adv < policy.v1_min_adv20_usd:
            st, why = AUTO_EXCLUDED, "BELOW_V1_ADV20_FLOOR"
        else:
            st, why = EVENT_ELIGIBLE, ""
            if floor:                                  # rank / display on the as-traded live values
                price, adv = lprice, ladv
        rows.append({"symbol": s, "state": st, "reason": why, "price": price, "prev_close": prev_close, "adv20": adv,
                     "cik": m.get("cik"), "core_rank": None})
    ranked = sorted((r for r in rows if r["state"] == EVENT_ELIGIBLE), key=lambda r: (-r["adv20"], r["symbol"]))
    for i, r in enumerate(ranked, 1):
        r["core_rank"] = i
        if i <= policy.core_size:
            r["state"], r["reason"] = CORE, f"ADV20_RANK_{i}"
        else:
            r["reason"] = f"ADV20_RANK_{i}_OUTSIDE_CORE_{policy.core_size}"
    return rows


def resolve(snapshot: dict[str, dict], *, now: str, promotions: list[dict], operator_added: set[str],
            operator_excluded: set[str], v2_forced: set[str], positions: set[str], protections: dict[str, str]
            ) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """Effective active set (sorted, deterministic) + state/reason for EVERY snapshot symbol.
    Precedence: position/intent safety > OPERATOR_EXCLUDED > OPERATOR_ADDED / V2 scope > structural > lifecycle
    protection of an AUTO_EXCLUDED symbol (keeps it FETCHED for management; admission is decided by discovery) >
    floors > CORE > live promotion > lifecycle protection > EVENT_ELIGIBLE."""
    live = {}
    for p in promotions:
        if p["started_utc"] <= now and (p["expires_utc"] is None or now < p["expires_utc"]):
            live.setdefault(p["symbol"], p["reason"])
    out: dict[str, tuple[str, str]] = {}
    for s, r in snapshot.items():
        if s in positions:
            out[s] = (OPERATOR_ADDED if s in operator_added else r["state"] if r["state"] == CORE else EVENT_PROMOTED,
                      P_POSITION)
        elif s in operator_excluded:
            out[s] = (OPERATOR_EXCLUDED, "OPERATOR_EXCLUDED")
        elif s in operator_added or s in v2_forced:
            out[s] = (OPERATOR_ADDED, "OPERATOR_ADDED" if s in operator_added else "V2_EXECUTION_SCOPE")
        elif r["state"] == AUTO_EXCLUDED and s in protections:
            out[s] = (EVENT_PROMOTED, protections[s])  # open identity keeps its data; admission is decided upstream
        elif r["state"] in (STRUCTURAL, AUTO_EXCLUDED):
            out[s] = (r["state"], r["reason"])
        elif r["state"] == CORE:
            out[s] = (CORE, r["reason"])
        elif s in live:
            out[s] = (EVENT_PROMOTED, live[s])
        elif s in protections:
            out[s] = (EVENT_PROMOTED, protections[s])
        else:
            out[s] = (EVENT_ELIGIBLE, r["reason"])
    for s in operator_added - set(snapshot):                  # operator adds outside the base universe
        if s not in operator_excluded:
            out[s] = (OPERATOR_ADDED, "OPERATOR_ADDED_OUTSIDE_BASE")
    active = sorted(s for s, (st, _) in out.items() if st in (CORE, EVENT_PROMOTED, OPERATOR_ADDED))
    return active, out


def gap_pct(trade: dict | None, prev_close: float | None, window_start: datetime, sip_as_of: datetime,
            stale_min: int = DTU_V1.stale_min) -> float | None:
    if not trade or not trade.get("p") or not trade.get("t") or not prev_close:
        return None
    t = ts(trade["t"])
    if t < window_start or (sip_as_of - t) > timedelta(minutes=stale_min):
        return None
    return (float(trade["p"]) / float(prev_close) - 1.0) * 100.0


# ============================================================================================================ store
class DTU:
    """Owned by DATA_INGESTION. ``con`` is ingestion's market.db connection (single writer)."""

    def __init__(self, con: sqlite3.Connection, *, root=None, policy: DTUPolicy = DTU_V1, headers=None, sec_ua=None,
                 snapshot_fetch=None, edgar_fetch=None, clock=None, readers=None, live_fetch=None, limiter=None):
        self.con, self.root, self.policy = con, root, policy
        self.con.executescript(SCHEMA)
        self.headers, self.sec_ua = headers, sec_ua
        self._snapshot_fetch, self._edgar_fetch = snapshot_fetch, edgar_fetch
        self._live_fetch, self._limiter = live_fetch, limiter
        self.clock = clock or (lambda: datetime.now(UTC))
        self.readers = readers or {}
        self._last_sweep = self._last_edgar = 0.0
        self._last_fetch: list[str] | None = None
        self.last: dict = {}

    # -- live-floor inputs (as-traded daily bars; DTU_V2) -------------------------------------------------------
    def ensure_live_daily(self, w, symbols: list[str], now: datetime) -> dict:
        """Once per window: as-traded (adjustment=raw) SIP 1Day bars of the required completed sessions for
        ``symbols``; a failed batch is retried on the next call (its symbols stay pending). Never a bar of D."""
        wid = w.window_id
        st = self.con.execute("SELECT failed_json FROM dtu_live_daily_state WHERE window_id=?", (wid,)).fetchone()
        pending = set(json.loads(st[0] or "[]")) if st else set(symbols)
        if st is not None and not pending:
            return {"complete": True, "fetched": 0}
        sessions = completed_sessions(w.reference_session.isoformat(), self.policy.live_sessions)
        start = datetime.fromisoformat(sessions[0]).replace(tzinfo=UTC)
        from talonx_premarket.alpaca_data import data_as_of
        end = min(datetime.combine(w.session, datetime.min.time(), UTC), data_as_of(now)) - timedelta(seconds=1)
        bars, failed, nreq, src = self._fetch_live(sorted(pending), start, end)
        with self.con:
            for s in sorted(pending - failed):
                self.con.execute("INSERT OR REPLACE INTO dtu_live_daily VALUES (?,?,?)",
                                 (wid, s, json.dumps(bars.get(s, []))))
            prev = self.con.execute("SELECT requests FROM dtu_live_daily_state WHERE window_id=?", (wid,)).fetchone()
            self.con.execute("INSERT OR REPLACE INTO dtu_live_daily_state VALUES (?,?,?,?,?,?,?,?)",
                             (wid, iso(self.clock()), json.dumps(sessions), iso(start), iso(end),
                              json.dumps(sorted(failed)), (prev[0] if prev else 0) + nreq, src))
        return {"complete": not failed, "fetched": len(pending - failed), "failed": len(failed), "requests": nreq}

    def _fetch_live(self, symbols: list[str], start: datetime, end: datetime) -> tuple[dict, set, int, str]:
        if self._live_fetch is not None:
            return self._live_fetch(symbols, start, end)
        import dataclasses
        from talonx_premarket.alpaca_data import AlpacaData, RateLimiter
        from talonx_premarket.config import PREMARKET_RESEARCH_V1
        cfg = dataclasses.replace(PREMARKET_RESEARCH_V1, adjustment="raw")     # as-traded; feed stays SIP
        data = AlpacaData(key_id=(self.headers or {}).get("APCA-API-KEY-ID", ""),
                          secret=(self.headers or {}).get("APCA-API-SECRET-KEY", ""), cfg=cfg,
                          limiter=self._limiter or RateLimiter(40))
        res = data.bars_ex(symbols, timeframe="1Day", start=start, end=end)
        return res.bars, set(res.failed), data.requests, f"alpaca {cfg.feed} 1Day adjustment={cfg.adjustment}"

    def live_inputs(self, wid: str) -> tuple[dict[str, list[dict]], set[str], list[str]] | None:
        st = self.con.execute("SELECT sessions_json, failed_json FROM dtu_live_daily_state WHERE window_id=?",
                              (wid,)).fetchone()
        if st is None:
            return None
        live = {r[0]: json.loads(r[1]) for r in self.con.execute(
            "SELECT symbol, bars_json FROM dtu_live_daily WHERE window_id=?", (wid,))}
        return live, set(json.loads(st[1] or "[]")), json.loads(st[0])

    # -- snapshot -----------------------------------------------------------------------------------------------
    def ensure_snapshot(self, w, members: list[dict], daily: dict[str, list[dict]]) -> dict[str, dict]:
        wid = w.window_id
        have = self.con.execute("SELECT policy_fp, snapshot_version FROM dtu_snapshots WHERE window_id=?",
                                (wid,)).fetchone()
        if have is not None and have[0] != self.policy.fingerprint():
            # policy changed inside a window (deploy / rollback): rebuild under the running policy, recorded
            with self.con:
                self.con.execute("DELETE FROM dtu_snapshot WHERE window_id=?", (wid,))
                self.con.execute("DELETE FROM dtu_snapshots WHERE window_id=?", (wid,))
                self.con.execute("INSERT INTO dtu_transitions (at_utc, window_id, symbol, from_state, to_state, "
                                 "reason) VALUES (?,?,?,?,?,?)", (iso(self.clock()), wid, "*", have[1],
                                                                  self.policy.version, "SNAPSHOT_REBUILT_POLICY_CHANGE"))
            have = None
        if have is None:
            ref = w.reference_session.isoformat()
            kw = {}
            if has_live_floor(self.policy):
                inp = self.live_inputs(wid)
                if inp is None:
                    raise RuntimeError("LIVE_DAILY_NOT_FETCHED")
                kw = {"live": inp[0], "live_failed": inp[1], "sessions": inp[2]}
            rows = classify_members(members, daily, ref, self.policy, **kw)
            ver = f"{wid}@{ref}#{self.policy.fingerprint()}"
            counts = {}
            for r in rows:
                counts[r["state"]] = counts.get(r["state"], 0) + 1
            with self.con:
                self.con.executemany("INSERT OR REPLACE INTO dtu_snapshot VALUES (?,?,?,?,?,?,?,?,?,?)",
                                     [(wid, r["symbol"], r["state"], r["reason"], r["core_rank"], r["price"],
                                       r["prev_close"], r["adv20"], r["cik"], ver) for r in rows])
                self.con.execute("INSERT OR REPLACE INTO dtu_snapshots VALUES (?,?,?,?,?,?,?)",
                                 (wid, ver, ref, iso(self.clock()), self.policy.core_size, json.dumps(counts),
                                  self.policy.fingerprint()))
        return self.snapshot(wid)

    def snapshot(self, wid: str) -> dict[str, dict]:
        cols = ("symbol", "state", "reason", "core_rank", "price", "prev_close", "adv20", "cik", "snapshot_version")
        return {r[0]: dict(zip(cols, r)) for r in self.con.execute(
            f"SELECT {','.join(cols)} FROM dtu_snapshot WHERE window_id=?", (wid,))}

    # -- promotions -----------------------------------------------------------------------------------------------
    def promote(self, w, symbol: str, reason: str, *, expires_utc: str | None, source_event_id: str | None,
                snapshot_version: str, detail: dict | None = None) -> bool:
        now = iso(self.clock())
        with self.con:
            n = self.con.execute("INSERT OR IGNORE INTO dtu_promotions VALUES (?,?,?,?,?,?,?,?,?)",
                                 (w.window_id, symbol, reason, now, expires_utc, source_event_id, snapshot_version,
                                  self.policy.version, json.dumps(detail or {}))).rowcount
            if n:
                self.con.execute("INSERT INTO dtu_transitions (at_utc, window_id, symbol, from_state, to_state, "
                                 "reason) VALUES (?,?,?,?,?,?)", (now, w.window_id, symbol, EVENT_ELIGIBLE,
                                                                  EVENT_PROMOTED, reason))
        return bool(n)

    def promotions(self, w) -> list[dict]:
        """This window's promotions + SEC_8K promotions of earlier windows whose TTL has not expired."""
        cols = ("window_id", "symbol", "reason", "started_utc", "expires_utc")
        now = iso(self.clock())
        return [dict(zip(cols, r)) for r in self.con.execute(
            f"SELECT {','.join(cols)} FROM dtu_promotions WHERE window_id=? OR (expires_utc IS NOT NULL AND "
            "expires_utc > ?)", (w.window_id, now))]

    # -- sweep (lightweight: snapshots for EVENT_ELIGIBLE symbols only) ------------------------------------------
    def sweep(self, w, snap: dict[str, dict], sip_as_of: datetime) -> dict:
        now = self.clock()
        if time.monotonic() - self._last_sweep < self.policy.sweep_every_s:
            return {"skipped": True}
        self._last_sweep = time.monotonic()
        pool = sorted(s for s, r in snap.items() if r["state"] == EVENT_ELIGIBLE)
        t0 = time.monotonic()
        trades, nreq, errs = self._fetch_snapshots(pool)
        usable = new = 0
        exp = iso(w.after_hours_end_utc)
        for s in pool:
            g = gap_pct(trades.get(s), snap[s]["prev_close"], w.premarket_start_utc, sip_as_of, self.policy.stale_min)
            if g is None:
                continue
            usable += 1
            if abs(g) >= self.policy.gap_trigger_pct:
                new += self.promote(w, s, GAP, expires_utc=exp, source_event_id=None,
                                    snapshot_version=snap[s]["snapshot_version"],
                                    detail={"gap_pct": round(g, 3), "trade_utc": (trades.get(s) or {}).get("t")})
        k8 = self._edgar(w, snap)
        rec = {"symbols": len(pool), "requests": nreq, "duration_s": round(time.monotonic() - t0, 3), "usable": usable,
               "gap_promotions": new, "sec8k_promotions": k8, "errors": errs}
        with self.con:
            self.con.execute("INSERT INTO dtu_sweeps (window_id, at_utc, symbols, requests, duration_s, usable, "
                             "gap_promotions, sec8k_promotions, errors) VALUES (?,?,?,?,?,?,?,?,?)",
                             (w.window_id, iso(now), len(pool), nreq, rec["duration_s"], usable, new, k8,
                              json.dumps(errs) if errs else None))
        return rec

    def _fetch_snapshots(self, symbols: list[str]) -> tuple[dict, int, list[str]]:
        if self._snapshot_fetch is not None:
            return self._snapshot_fetch(symbols)
        out, n, errs = {}, 0, []
        for i in range(0, len(symbols), 1000):
            u = "https://data.alpaca.markets/v2/stocks/snapshots?" + urllib.parse.urlencode(
                {"symbols": ",".join(symbols[i:i + 1000]), "feed": "delayed_sip"})
            n += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers=self.headers or {}), timeout=60) as r:
                    for s, v in json.loads(r.read()).items():
                        out[s] = (v or {}).get("latestTrade")
            except Exception as exc:  # noqa: BLE001 -- a failed batch only means no promotions from it this cycle
                errs.append(f"batch@{i}: {type(exc).__name__}: {str(exc)[:120]}")
        return out, n, errs

    def _edgar(self, w, snap: dict[str, dict]) -> int:
        if time.monotonic() - self._last_edgar < self.policy.edgar_every_s:
            return 0
        self._last_edgar = time.monotonic()
        entries = self._edgar_fetch() if self._edgar_fetch is not None else self._edgar_http()
        cik_sym = {r["cik"]: s for s, r in snap.items() if r.get("cik") and r["state"] == EVENT_ELIGIBLE}
        from talonx_opportunity.phases import trading_window
        expires = self._sessions_ahead(w.session, self.policy.sec_8k_ttl_sessions, trading_window)
        new = 0
        for e in entries:
            sym = cik_sym.get(e["cik"])
            with self.con:
                fresh = self.con.execute("INSERT OR IGNORE INTO dtu_edgar VALUES (?,?,?,?,?)",
                                         (e["accession"], e["cik"], sym, e["updated_utc"],
                                          iso(self.clock()))).rowcount
            if fresh and sym:
                new += self.promote(w, sym, SEC_8K, expires_utc=expires, source_event_id=e["accession"],
                                    snapshot_version=snap[sym]["snapshot_version"], detail={"form": e["form"]})
        return new

    @staticmethod
    def _sessions_ahead(session, n: int, trading_window) -> str:
        d, left = session, n - 1
        while left > 0:
            d += timedelta(days=1)
            try:
                if d.weekday() < 5 and trading_window(d) is not None:
                    left -= 1
            except ValueError:
                pass
        return iso(trading_window(d).after_hours_end_utc)

    def _edgar_http(self) -> list[dict]:
        url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include"
               "&start=0&count=100&output=atom")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.sec_ua or ""})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 -- no promotion this cycle; recorded by the empty result
            return []
        out = []
        for ent in re.findall(r"<entry>(.*?)</entry>", text, re.S):
            title = re.search(r"<title>(.*?)</title>", ent, re.S)
            upd = re.search(r"<updated>(.*?)</updated>", ent)
            acc = re.search(r"accession-number=([0-9-]+)", ent)
            cik = re.search(r"\((\d{10})\)", title.group(1) if title else "")
            form = title.group(1).split(" - ")[0].strip() if title else ""
            if acc and cik and upd and form.startswith("8-K"):
                out.append({"accession": acc.group(1), "cik": cik.group(1), "form": form,
                            "updated_utc": iso(ts(upd.group(1)))})
        return out

    # -- protections (read-only readers of other components' stores) --------------------------------------------
    def protections(self, w) -> tuple[dict[str, str], set[str]]:
        now = iso(self.clock())
        prot: dict[str, str] = {}
        for sym, state, first_seen, wid in self._reader("open_candidates", w):
            if state in ("BULLISH_SETUP", "BEARISH_SETUP"):
                prot.setdefault(sym, P_SETUP)
            elif state == "WATCH" and wid == w.window_id and now < iso(w.after_hours_end_utc):
                prot.setdefault(sym, P_WATCH)
        for sym in self._reader("signals_today", w):
            prot[sym] = P_SIGNAL
        return prot, set(self._reader("positions", w))

    def report(self, w, members: list[dict], daily: dict[str, list[dict]], *, v2_scope: set[str],
               operator_added: set[str] = frozenset(), previous_policy: DTUPolicy | None = DTU_V1) -> dict:
        """The window's auditable universe report (built snapshot vs the previous policy on the same window data)."""
        snap = self.snapshot(w.window_id)
        prev = None
        if previous_policy is not None and previous_policy.fingerprint() != self.policy.fingerprint():
            prev = {r["symbol"]: r for r in classify_members(members, daily, w.reference_session.isoformat(),
                                                             previous_policy)}
        prot, positions = self.protections(w)
        protected = {}
        for s in sorted((set(prot) | positions | set(v2_scope) | set(operator_added)) - {"__V2_UNREADABLE__"}):
            protected[s] = (P_POSITION if s in positions else "V2_EXECUTION_SCOPE" if s in v2_scope
                            else "OPERATOR_ADDED" if s in operator_added else prot[s])
        meta = report_meta(self.con, w, self.policy, previous_policy if prev is not None else None)
        meta["v2_positions_readable"] = "__V2_UNREADABLE__" not in positions
        return window_report(snap, meta, prev, protected)

    def _reader(self, name: str, w):
        if name in self.readers:
            return self.readers[name](w)
        from talonx_opportunity.db import root_dir
        r = root_dir(self.root)

        def ro(p: Path):
            return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10) if p.exists() else None
        if name == "open_candidates":
            c = ro(r / "opportunity.db")
            return c.execute("SELECT symbol, state, first_seen_utc, window_id FROM candidates WHERE state IN "
                             "('WATCH','BULLISH_SETUP','BEARISH_SETUP')").fetchall() if c else []
        if name == "signals_today":
            c = ro(r / "promotion.db")
            return [x[0] for x in c.execute("SELECT symbol FROM promotions WHERE window_id=? AND state IN "
                                            "('PROMOTED_SIGNAL','QUEUED')", (w.window_id,))] if c else []
        if name == "positions":
            from talonx_opportunity.db import REPO_ROOT
            c = ro(Path(os.environ.get("TALONX_V2_DB_PATH") or REPO_ROOT / "v2_release_rc1.db"))
            if c is None:
                return []
            out = set()
            for tbl, where in (("positions", "1=1"), ("pending_entry_intents", "1=1")):
                try:
                    cols = {x[1] for x in c.execute(f"PRAGMA table_info({tbl})")}
                    q = f"SELECT symbol FROM {tbl} WHERE {where}"
                    if "status" in cols:
                        q += " AND UPPER(status) NOT IN ('CLOSED','EXITED','CANCELLED','CANCELED','RESOLVED','EXPIRED')"
                    out |= {x[0] for x in c.execute(q)}
                except sqlite3.Error:
                    out.add("__V2_UNREADABLE__")        # fail-safe: surfaced by the caller as a fallback
            return out
        raise KeyError(name)

    # -- one ingestion cycle ------------------------------------------------------------------------------------
    def active_symbols(self, w, base: list[str], *, members: list[dict], daily: dict[str, list[dict]],
                       sip_as_of: datetime, operator_added: set[str], operator_excluded: set[str],
                       v2_forced: set[str], defer_write: bool = False) -> tuple[list[str], dict]:
        """Effective fetch list for this cycle (a subset of ``base`` + operator adds). Any error -> FULL ``base``.
        ``defer_write`` (2026-10-01, P0 consistent snapshots): the dtu_active row is NOT committed here; it is kept in
        ``pending_active`` for the caller (ingestion) to write inside the SAME transaction as the cycle's aggregates
        and as_of, then ``confirm_pending()`` after that commit. The resolution itself is unchanged."""
        now = self.clock()
        try:
            snap = self.ensure_snapshot(w, members, daily)
            if not snap:
                raise RuntimeError("SNAPSHOT_EMPTY")
            if len(snap) < 0.9 * len(members):
                raise RuntimeError(f"SNAPSHOT_CORRUPT ({len(snap)} rows vs {len(members)} members)")
            sweep = self.sweep(w, snap, sip_as_of)
            prot, positions = self.protections(w)
            if "__V2_UNREADABLE__" in positions:
                raise RuntimeError("V2_POSITIONS_UNREADABLE")
            now = self.clock()                        # AFTER the sweep: promotions made this cycle are live
            active, states = resolve(snap, now=iso(now), promotions=self.promotions(w),
                                     operator_added=operator_added, operator_excluded=operator_excluded,
                                     v2_forced=v2_forced, positions=positions, protections=prot)
            base_set = set(base)
            fetch = [s for s in base if s in set(active)] + [s for s in active if s not in base_set
                                                             and states[s][0] == OPERATOR_ADDED]
            counts = {}
            for st, why in states.values():
                counts[st] = counts.get(st, 0) + 1
            counts.update(effective_active=len(fetch), protected=sum(1 for st, why in states.values()
                                                                     if why.startswith("PROTECT_")))
            fb = None
        except Exception as exc:  # noqa: BLE001 -- fail SAFE: the full eligible universe, recorded
            fetch, counts, sweep, fb = list(base), {"effective_active": len(base)}, {}, \
                f"{type(exc).__name__}: {str(exc)[:200]}"
        changed = fetch != self._last_fetch                  # the symbol list is stored only when it changes
        row = (w.window_id, iso(now), len(fetch), json.dumps(counts), json.dumps(fetch) if changed else None, fb,
               self.policy.fingerprint())
        if defer_write:
            self.pending_active = (row, list(fetch))        # written + confirmed by the caller's cycle transaction
        else:
            self._last_fetch = list(fetch)
            with self.con:
                self.con.execute("INSERT OR REPLACE INTO dtu_active VALUES (?,?,?,?,?,?,?)", row)
        self.last = {"mode": ACTIVE, "window_id": w.window_id, "effective_active": len(fetch), "counts": counts,
                     "fallback": fb, "sweep": sweep}
        return fetch, self.last


    pending_active: tuple | None = None

    def write_pending(self) -> str | None:
        """Write the deferred dtu_active row on the caller's OPEN transaction (no commit). Returns its cycle_utc."""
        if self.pending_active is None:
            return None
        row, _ = self.pending_active
        self.con.execute("INSERT OR REPLACE INTO dtu_active VALUES (?,?,?,?,?,?,?)", row)
        return row[1]

    def confirm_pending(self) -> None:
        """After the caller's commit: the stored symbol list is now the one to diff against."""
        if self.pending_active is not None:
            self._last_fetch = list(self.pending_active[1])
            self.pending_active = None

    def discard_pending(self) -> None:
        self.pending_active = None


def latest_active(con: sqlite3.Connection, window_id: str) -> dict | None:
    """Discovery's read of the active set ingestion resolved last for this window (None = not available)."""
    try:
        last = con.execute("SELECT cycle_utc, fallback_reason, counts_json FROM dtu_active WHERE window_id=? "
                           "ORDER BY cycle_utc DESC LIMIT 1", (window_id,)).fetchone()
        sym = con.execute("SELECT symbols_json FROM dtu_active WHERE window_id=? AND symbols_json IS NOT NULL "
                          "ORDER BY cycle_utc DESC LIMIT 1", (window_id,)).fetchone()
    except sqlite3.Error:
        return None
    if last is None or sym is None:
        return None
    return {"cycle_utc": last[0], "symbols": set(json.loads(sym[0])), "fallback": last[1],
            "counts": json.loads(last[2] or "{}")}


# ============================================================================================================ admission
def read_admission(root, window_id: str, policy: DTUPolicy) -> set[str] | None:
    """Discovery's admission set for a live-floor policy: the window's qualifying symbols (Core + event tier) of a
    snapshot built under ``policy``. None = no such snapshot (the caller fails CLOSED: no new identity)."""
    from talonx_opportunity.db import root_dir
    p = root_dir(root) / "market.db"
    if not p.exists():
        return None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    try:
        r = con.execute("SELECT policy_fp FROM dtu_snapshots WHERE window_id=?", (window_id,)).fetchone()
        if r is None or r[0] != policy.fingerprint():
            return None
        return {x[0] for x in con.execute("SELECT symbol FROM dtu_snapshot WHERE window_id=? AND state IN (?,?)",
                                          (window_id, CORE, EVENT_ELIGIBLE))}
    except sqlite3.Error:
        return None
    finally:
        con.close()


# ============================================================================================================ report
CATEGORIES = ("QUALIFYING", "PRICE_ONLY", "LIQUIDITY_ONLY", "PRICE_AND_LIQUIDITY", "DATA_QUALITY", "RETAINED_V1_RULE",
              "STRUCTURAL")
REPORT_FIELDS = ["symbol", "state", "reason", "category", "change", "close_usd", "adv20_usd", "core_rank",
                 "previous_state", "previous_reason", "protected"]
# Subscriptions that never depend on the Opportunity Engine universe (each fetches its own data).
INDEPENDENT_SUBSCRIPTIONS = {
    "SPY": "DATA_INGESTION capability probe (1-min SIP; fetched directly, not from the universe)",
    "OE outcome tracker": "fetches its own 1-min bars for every live candidate (universe-independent)",
    "V2 companion / V2 forward tracker": "own Form 4 / price path (separate lane)",
    "VR paper tracker": "own 1-min bars for its open paper positions (reads PAPER_SIGNALs)",
    "DTU shadow collector": "own snapshot from market.db universe + split-adjusted daily (unchanged tables)",
    "sector / benchmark ETFs": "never Opportunity Engine candidates (STRUCTURALLY_EXCLUDED); no OE subscription to keep"}


def window_report(snapshot: dict[str, dict], meta: dict, previous: dict[str, dict] | None = None,
                  protected: dict[str, str] | None = None) -> dict:
    """Auditable universe summary. ``snapshot``/``previous``: symbol -> row (state, reason, price, adv20, core_rank);
    ``previous`` = the previous policy on the SAME window data. Categories are mutually exclusive (floor_category);
    every count reconciles to the per-symbol list."""
    protected = protected or {}
    rows, cat, chg = [], dict.fromkeys(CATEGORIES, 0), {}
    for s in sorted(snapshot):
        r = snapshot[s]
        c = floor_category(r["state"], r["reason"])
        p = (previous or {}).get(s)
        was = p is not None and p["state"] in (CORE, EVENT_ELIGIBLE)
        q = c == "QUALIFYING"
        ch = "RETAINED" if was and q else "ADDED" if q else "REMOVED" if was else "EXCLUDED_BEFORE_AND_AFTER"
        cat[c] += 1
        chg[ch] = chg.get(ch, 0) + 1
        rows.append({"symbol": s, "state": r["state"], "reason": r["reason"], "category": c, "change": ch,
                     "close_usd": r.get("price"), "adv20_usd": r.get("adv20"), "core_rank": r.get("core_rank"),
                     "previous_state": p["state"] if p else None, "previous_reason": p["reason"] if p else None,
                     "protected": protected.get(s, "")})
    removed = [x for x in rows if x["change"] == "REMOVED"]
    rem_cat = {k: sum(1 for x in removed if x["category"] == k) for k in CATEGORIES if k != "QUALIFYING"}
    prev_pool = sum(1 for p in (previous or {}).values() if p["state"] in (CORE, EVENT_ELIGIBLE)) if previous else None
    counts = {"universe_members": len(rows), "categories": cat, "qualifying": cat["QUALIFYING"],
              "core": sum(1 for x in rows if x["state"] == CORE),
              "event_eligible": sum(1 for x in rows if x["state"] == EVENT_ELIGIBLE),
              "previous_pool": prev_pool,
              "previous_core": sum(1 for p in (previous or {}).values() if p["state"] == CORE) if previous else None,
              "retained": chg.get("RETAINED", 0), "added": chg.get("ADDED", 0), "removed": chg.get("REMOVED", 0),
              "removed_by_category": rem_cat,
              "excluded_by_category": {k: v for k, v in cat.items() if k not in ("QUALIFYING", "STRUCTURAL")},
              "protected_not_qualifying": sum(1 for s in protected
                                              if floor_category(snapshot.get(s, {}).get("state", ""),
                                                                snapshot.get(s, {}).get("reason", "")) != "QUALIFYING"),
              "protected_total": len(protected)}
    recon = {"categories_sum_to_members": sum(cat.values()) == len(rows),
             "qualifying_eq_core_plus_event": cat["QUALIFYING"] == counts["core"] + counts["event_eligible"],
             "qualifying_eq_retained_plus_added": previous is None or cat["QUALIFYING"] == counts["retained"] +
             counts["added"],
             "previous_eq_retained_plus_removed": previous is None or prev_pool == counts["retained"] +
             counts["removed"],
             "removed_by_category_sums": sum(rem_cat.values()) == counts["removed"]}
    return {"meta": meta, "counts": counts, "reconciliation": recon, "reconciled": all(recon.values()),
            "protected": dict(sorted(protected.items())), "independent_subscriptions": INDEPENDENT_SUBSCRIPTIONS,
            "rows": rows}


def summary_text(rep: dict, head: str = "⚙️ TALONX SENTINEL") -> str:
    """Concise daily universe summary (the Sentinel /universe summary head and style). Proposed text only."""
    m, c = rep["meta"], rep["counts"]
    e = c["excluded_by_category"]
    lines = [f"{head} — UNIVERSE ({m['window_id']})",
             f"Live floors {m['policy_version']}: close ≥ ${m['min_close_usd']:g} · ADV20 ≥ "
             f"${m['min_adv20_usd'] / 1e6:g}M (as of {m['reference_session']} close, {m['sessions_required']} "
             f"sessions)",
             f"Qualifying: {c['qualifying']} (Core {c['core']} · event-eligible {c['event_eligible']})"]
    if c["previous_pool"] is not None:
        lines.append(f"Previous ({m.get('previous_policy_version') or 'DTU_V1'}): {c['previous_pool']} · retained "
                     f"{c['retained']} · added {c['added']} · removed {c['removed']}")
    lines += [f"Excluded: price {e['PRICE_ONLY']} · liquidity {e['LIQUIDITY_ONLY']} · both "
              f"{e['PRICE_AND_LIQUIDITY']} · data {e['DATA_QUALITY']}"
              + (f" · V1 rule {e['RETAINED_V1_RULE']}" if e["RETAINED_V1_RULE"] else ""),
              f"Protected (fetched, not admissible): {c['protected_not_qualifying']}",
              f"Snapshot: {m['snapshot_version']}",
              "Tradability/workload filter only — not a profitability claim.",
              "Full list: /universe excluded file"]
    return "\n".join(lines)


def write_report(rep: dict, out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    wid = rep["meta"]["window_id"]
    paths = {"json": out_dir / f"universe_{wid}.json", "csv": out_dir / f"universe_{wid}_members.csv",
             "summary": out_dir / f"universe_{wid}_summary.txt"}
    paths["json"].write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    with paths["csv"].open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
        w.writeheader()
        w.writerows(rep["rows"])
    paths["summary"].write_text(summary_text(rep) + "\n", encoding="utf-8")
    return {k: str(v) for k, v in paths.items()}


def report_meta(con: sqlite3.Connection, w, policy: DTUPolicy, previous_policy: DTUPolicy | None) -> dict:
    snap = con.execute("SELECT snapshot_version, reference_session, created_utc, policy_fp FROM dtu_snapshots WHERE "
                       "window_id=?", (w.window_id,)).fetchone()
    live = con.execute("SELECT fetched_utc, sessions_json, start_utc, end_utc, failed_json, requests, source FROM "
                       "dtu_live_daily_state WHERE window_id=?", (w.window_id,)).fetchone()
    return {"window_id": w.window_id, "reference_session": w.reference_session.isoformat(),
            "snapshot_version": snap[0] if snap else None, "snapshot_built_utc": snap[2] if snap else None,
            "snapshot_policy_fp": snap[3] if snap else None,
            "policy_version": policy.version, "policy_fp": policy.fingerprint(),
            "min_close_usd": getattr(policy, "live_min_close_usd", policy.v1_min_price),
            "min_adv20_usd": getattr(policy, "live_min_adv20_usd", policy.v1_min_adv20_usd),
            "sessions_required": getattr(policy, "live_sessions", 20),
            "sessions": json.loads(live[1]) if live else [],
            "basis": getattr(policy, "live_basis", policy.snapshot_basis),
            "data_source": live[6] if live else None, "data_fetched_utc": live[0] if live else None,
            "data_request_window_utc": [live[2], live[3]] if live else None,
            "data_as_of": f"{w.reference_session.isoformat()} regular-session close (D-1)",
            "fetch_failed_symbols": len(json.loads(live[4] or "[]")) if live else None,
            "data_requests": live[5] if live else None,
            "effective_from_utc": iso(w.start_utc), "effective_window": w.window_id,
            "previous_policy_version": previous_policy.version if previous_policy else None,
            "previous_policy_fp": previous_policy.fingerprint() if previous_policy else None}


def report_dir(root, window_id: str) -> Path:
    from talonx_opportunity.db import root_dir
    return root_dir(root) / "universe_reports" / window_id
