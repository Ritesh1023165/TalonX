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
"""
from __future__ import annotations

import hashlib
import json
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
"""


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


# ============================================================================================================ pure
def classify_members(members: list[dict], daily: dict[str, list[dict]], reference_session: str,
                     policy: DTUPolicy = DTU_V1) -> list[dict]:
    """D-1 snapshot rows (deterministic): structural bucket, V1 floors, ADV20 rank, Core. Uses only daily bars dated
    <= the reference session (causal)."""
    rows = []
    for m in members:
        s = m["symbol"]
        bars = sorted((b for b in daily.get(s, []) if str(b["t"])[:10] <= reference_session), key=lambda b: b["t"])
        last20 = bars[-20:]
        prev_close = float(bars[-1]["c"]) if bars and str(bars[-1]["t"])[:10] == reference_session else None
        price = float(bars[-1]["c"]) if bars else None
        adv = sum(float(b["v"]) * float(b["c"]) for b in last20) / len(last20) if last20 else None
        if m.get("status") != "ELIGIBLE":
            st, why = STRUCTURAL, f"STRUCTURAL:{m.get('reason') or 'EXCLUDED'}"
        elif price is None or adv is None:
            st, why = AUTO_EXCLUDED, "NO_D1_DAILY_HISTORY"
        elif price < policy.v1_min_price:
            st, why = AUTO_EXCLUDED, "BELOW_V1_PRICE_FLOOR"
        elif adv < policy.v1_min_adv20_usd:
            st, why = AUTO_EXCLUDED, "BELOW_V1_ADV20_FLOOR"
        else:
            st, why = EVENT_ELIGIBLE, ""
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
    Precedence: position/intent safety > OPERATOR_EXCLUDED > OPERATOR_ADDED / V2 scope > structural / floors >
    CORE > live promotion > lifecycle protection > EVENT_ELIGIBLE."""
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
                 snapshot_fetch=None, edgar_fetch=None, clock=None, readers=None):
        self.con, self.root, self.policy = con, root, policy
        self.con.executescript(SCHEMA)
        self.headers, self.sec_ua = headers, sec_ua
        self._snapshot_fetch, self._edgar_fetch = snapshot_fetch, edgar_fetch
        self.clock = clock or (lambda: datetime.now(UTC))
        self.readers = readers or {}
        self._last_sweep = self._last_edgar = 0.0
        self._last_fetch: list[str] | None = None
        self.last: dict = {}

    # -- snapshot -----------------------------------------------------------------------------------------------
    def ensure_snapshot(self, w, members: list[dict], daily: dict[str, list[dict]]) -> dict[str, dict]:
        wid = w.window_id
        if self.con.execute("SELECT 1 FROM dtu_snapshots WHERE window_id=?", (wid,)).fetchone() is None:
            ref = w.reference_session.isoformat()
            rows = classify_members(members, daily, ref, self.policy)
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
                       v2_forced: set[str]) -> tuple[list[str], dict]:
        """Effective fetch list for this cycle (a subset of ``base`` + operator adds). Any error -> FULL ``base``."""
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
        self._last_fetch = list(fetch)
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO dtu_active VALUES (?,?,?,?,?,?,?)",
                             (w.window_id, iso(now), len(fetch), json.dumps(counts),
                              json.dumps(fetch) if changed else None, fb, self.policy.fingerprint()))
        self.last = {"mode": ACTIVE, "window_id": w.window_id, "effective_active": len(fetch), "counts": counts,
                     "fallback": fb, "sweep": sweep}
        return fetch, self.last


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
