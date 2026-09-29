"""
Dynamic Tradable Universe SHADOW collector (2026-09-29). MEASUREMENT ONLY.

Runs beside the unchanged full-universe production engine and records what a Core(1200) + Event-Tier universe WOULD
have had active, without influencing production in any way:

* production stores (market.db, opportunity.db, operator_control.db, V2 logs) are opened ``mode=ro``;
* the only writable store is ``results/dtu_shadow/shadow.db``;
* no notification code is imported; nothing is sent anywhere;
* the provider fetch universe, discovery, promotion, Lab and V2 are untouched.

Per trading window:
  SNAPSHOT (once, D-1 data)  structural bucket, price, ADV20, daily coverage (market.db daily), D-1 RTH 1-min coverage
                             + range proxy and a sampled NBBO spread (Alpaca SIP, <= 60 req/min), V1 floor eligibility,
                             ADV20 rank, Core(1200), V2/operator forced-active flags, shadow_state + reason.
  SWEEP (every 60 s in PREMARKET/REGULAR/AFTER_HOURS)
                             Alpaca ``/v2/stocks/snapshots?feed=delayed_sip`` for every structurally eligible symbol
                             (~6 requests). gap = latestTrade.p / V1 prev_close (from market.db daily: V1's own
                             reference close, NOT the snapshot's daily bars) - 1, only for a latestTrade inside the
                             window and <= 45 min older than the SIP as-of (V1's stale gate). Records first crossings of
                             |gap| >= 2/3/5/10 %, GAP_TRIGGER promotions (>= 3 %), sweep cost, effective-active size.
  SEC 8-K (every 300 s)      EDGAR "current events" atom feed for 8-K (1 request) -> SEC_8K promotions (TTL 3 sessions).
  PROTECTION (every sweep)   production's open candidate identities (read-only) -> OPEN_CANDIDATE_PROTECTION.
  VERIFY (every 5th sweep)   a fixed sample: snapshot fields next to V1's aggregate last bar and reference close, so the
                             snapshot field contract can be verified per phase (dtu_eval.verify_contract).
Form 4: DISABLED -- open-market purchase codes are not available universe-wide without parsing every filing.
usage: python -m talonx_shadow.dtu run | snapshot [WINDOW_ID]
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / "results" / "opportunity"
OUT = REPO / "results" / "dtu_shadow"
UTC = timezone.utc
CORE_SIZE = 1200
V1_PRICE, V1_ADV = 1.0, 1_000_000.0
GAP_TRIGGER_PCT = 3.0
CROSS_THRESHOLDS = (2.0, 3.0, 5.0, 10.0)
STALE_MIN = 45
SWEEP_EVERY_S = 60
EDGAR_EVERY_S = 300
VERIFY_EVERY_N = 5
VERIFY_SAMPLE = 150
SNAP_URL = "https://data.alpaca.markets/v2/stocks/snapshots"
EDGAR_8K = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include"
            "&start=0&count=100&output=atom")
ACTIVE_STATES = ("WATCH", "BULLISH_SETUP", "BEARISH_SETUP")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS snapshots (snapshot_id TEXT PRIMARY KEY, window_id TEXT, reference_session TEXT,
    built_utc TEXT, n INTEGER, core_size INTEGER, cost_json TEXT);
CREATE TABLE IF NOT EXISTS snapshot (snapshot_id TEXT, window_id TEXT, symbol TEXT, exchange TEXT, security_type TEXT,
    cik TEXT, price REAL, prev_close_v1 REAL, adv20 REAL, adv20_sh REAL, daily_coverage REAL, bar_coverage REAL,
    range_bps REAL, spread_bps REAL, half_spread_bps REAL, structurally_eligible INTEGER, structural_reason TEXT,
    v1_floor_eligible INTEGER, core_rank INTEGER, is_shadow_core INTEGER, is_v2_forced_active INTEGER,
    is_operator_forced_active INTEGER, shadow_state TEXT, reason TEXT, snapshot_as_of TEXT,
    PRIMARY KEY (snapshot_id, symbol));
CREATE INDEX IF NOT EXISTS ix_snap_window ON snapshot(window_id);
CREATE TABLE IF NOT EXISTS sweeps (id INTEGER PRIMARY KEY AUTOINCREMENT, window_id TEXT, at_utc TEXT, phase TEXT,
    sip_as_of TEXT, requests INTEGER, duration_s REAL, symbols_checked INTEGER, usable INTEGER, stale_excluded INTEGER,
    gap_promotions_new INTEGER, sec8k_promotions_new INTEGER, protection_new INTEGER, protected_now INTEGER,
    effective_active INTEGER, errors TEXT);
CREATE TABLE IF NOT EXISTS promotions (window_id TEXT, symbol TEXT, reason TEXT, first_at_utc TEXT, sweep_id INTEGER,
    detail_json TEXT, PRIMARY KEY (window_id, symbol, reason));
CREATE TABLE IF NOT EXISTS first_cross (window_id TEXT, symbol TEXT, threshold REAL, at_utc TEXT, gap_pct REAL,
    trade_utc TEXT, PRIMARY KEY (window_id, symbol, threshold));
CREATE TABLE IF NOT EXISTS edgar_8k (accession TEXT PRIMARY KEY, cik TEXT, form TEXT, updated_utc TEXT, symbol TEXT,
    seen_utc TEXT);
CREATE TABLE IF NOT EXISTS edgar_polls (id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT, ok INTEGER, entries INTEGER,
    new INTEGER, duration_s REAL, error TEXT);
CREATE TABLE IF NOT EXISTS verify (sweep_id INTEGER, at_utc TEXT, phase TEXT, symbol TEXT, lt_p REAL, lt_t TEXT,
    prev_c REAL, prev_t TEXT, daily_c REAL, daily_t TEXT, minute_c REAL, minute_t TEXT, v1_prev_close REAL,
    agg_last_c REAL, agg_last_t TEXT, ing_as_of TEXT, PRIMARY KEY (sweep_id, symbol));
"""


def shadow_db() -> Path:
    return OUT / "shadow.db"


def connect_rw() -> sqlite3.Connection:
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(shadow_db(), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    return c


def ro(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ------------------------------------------------------------------------------------------------------ credentials
def _env():
    sys.path.insert(0, str(REPO))
    from talonx_premarket import __main__ as M
    M._env()
    return M


def alpaca_headers() -> dict:
    return dict(_env()._data()._headers)


def sec_ua() -> str:
    return _env()._sec()._ua


def forced_active() -> tuple[set[str], set[str]]:
    """(V2-forced, operator-forced). V2 = the companion's execution scope + every V2 episode symbol."""
    M = _env()
    v2 = set(M._v2_scope(None))
    try:
        v2 |= {r[0] for r in ro(REPO / "v2_release_rc1.db").execute("SELECT DISTINCT symbol FROM processed_episodes")}
    except sqlite3.Error:
        pass
    op = set()
    try:
        op = {r[0] for r in ro(REPO / "operator_control.db").execute(
            "SELECT symbol FROM operator_universe WHERE status='ADDED'")}
    except sqlite3.Error:
        pass
    return v2, op


# ------------------------------------------------------------------------------------------------------ snapshot
def _fetch_d1_extras(syms: list[str], ref: date) -> tuple[dict, dict, dict]:
    """D-1 RTH 1-min coverage / range and a sampled NBBO spread (one instant, widening windows). <= 60 req/min."""
    sys.path.insert(0, str(REPO / "docs" / "research" / "evidence" / "2026-09-29_dynamic_tradable_universe" / "tools"))
    import fetch_d1_features as F  # the study's own fetcher (same definitions)
    from talonx_premarket.alpaca_data import AlpacaData, RateLimiter
    h = alpaca_headers()
    data = AlpacaData(key_id=h["APCA-API-KEY-ID"], secret=h["APCA-API-SECRET-KEY"], limiter=RateLimiter(60))
    t0, r0 = time.monotonic(), data.requests
    bars = F.rth_bars(data, syms, ref.isoformat())
    cost = {"bars_requests": data.requests - r0, "bars_s": round(time.monotonic() - t0, 1)}
    t1, r1 = time.monotonic(), data.requests
    at = datetime.combine(ref, datetime.min.time(), UTC) + timedelta(hours=18)      # 14:00 ET, D-1
    spreads, todo = {}, list(syms)
    for w in F.QUOTE_WINDOWS_S:
        if not todo:
            break
        got, _ = F.quotes(data, todo, at, at + timedelta(seconds=w))
        for s, xs in got.items():
            spreads[s] = round(statistics.median(xs), 2)
        todo = [s for s in todo if s not in got]
    cost.update(quote_requests=data.requests - r1, quote_s=round(time.monotonic() - t1, 1),
                spread_measured=len(spreads), errors=data.errors[-5:])
    return bars, spreads, cost


def build_snapshot(window_id: str, *, extras: bool = True) -> dict:
    from talonx_opportunity.phases import trading_window
    w = trading_window(date.fromisoformat(window_id))
    m = ro(LIVE / "market.db")
    row = m.execute("SELECT members_json FROM universe WHERE window_id=?", (window_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"no production universe for {window_id} yet")
    members = json.loads(row[0])
    daily = {r["symbol"]: json.loads(r["bars_json"]) for r in
             m.execute("SELECT symbol, bars_json FROM daily WHERE window_id=?", (window_id,))}
    ref = w.reference_session
    sessions = sorted({b["t"][:10] for bars in daily.values() for b in bars if b["t"][:10] <= ref.isoformat()})[-20:]
    v2, op = forced_active()
    rows = []
    for mm in members:
        s = mm["symbol"]
        bars = sorted((b for b in daily.get(s, []) if b["t"][:10] <= ref.isoformat()), key=lambda b: b["t"])
        last20 = bars[-20:]
        prev_close = float(bars[-1]["c"]) if bars and bars[-1]["t"][:10] == ref.isoformat() else None
        price = float(bars[-1]["c"]) if bars else None
        adv = sum(float(b["v"]) * float(b["c"]) for b in last20) / len(last20) if last20 else None
        advsh = sum(float(b["v"]) for b in last20) / len(last20) if last20 else None
        dcov = round(len({b["t"][:10] for b in last20} & set(sessions)) / max(1, len(sessions)), 3) if last20 else None
        elig = mm["status"] == "ELIGIBLE"
        v1 = bool(elig and price is not None and price >= V1_PRICE and (adv or 0) >= V1_ADV)
        rows.append({"symbol": s, "exchange": mm.get("exchange"), "cik": mm.get("cik"),
                     "security_type": "COMMON_OR_ADR" if elig else (mm.get("reason") or "EXCLUDED"),
                     "price": price, "prev_close_v1": prev_close, "adv20": adv, "adv20_sh": advsh, "daily_coverage": dcov,
                     "structurally_eligible": int(elig), "structural_reason": "" if elig else mm.get("reason"),
                     "v1_floor_eligible": int(v1)})
    ranked = sorted((r for r in rows if r["v1_floor_eligible"]), key=lambda r: (-r["adv20"], r["symbol"]))
    for i, r in enumerate(ranked, 1):
        r["core_rank"] = i
    bars_x, spreads, cost = ({}, {}, {"extras": "skipped"})
    if extras:
        bars_x, spreads, cost = _fetch_d1_extras(sorted(r["symbol"] for r in rows if r["structurally_eligible"]), ref)
    sid = f"{window_id}@{ref.isoformat()}"
    now = iso(datetime.now(UTC))
    for r in rows:
        b = bars_x.get(r["symbol"]) or {}
        r["bar_coverage"], r["range_bps"] = b.get("rth_coverage"), b.get("range_bps_med")
        r["spread_bps"] = spreads.get(r["symbol"])
        r["half_spread_bps"] = r["spread_bps"] / 2 if r["spread_bps"] is not None else None
        r["core_rank"] = r.get("core_rank")
        r["is_shadow_core"] = int(bool(r["core_rank"]) and r["core_rank"] <= CORE_SIZE)
        r["is_v2_forced_active"] = int(r["symbol"] in v2)
        r["is_operator_forced_active"] = int(r["symbol"] in op)
        if not r["structurally_eligible"]:
            st, why = "SHADOW_INACTIVE", f"STRUCTURAL:{r['structural_reason']}"
        elif r["is_operator_forced_active"] or r["is_v2_forced_active"]:
            st, why = "SHADOW_FORCED_ACTIVE", "OPERATOR_FORCED" if r["is_operator_forced_active"] else "V2_FORCED"
        elif not r["v1_floor_eligible"]:
            st, why = "SHADOW_INACTIVE", ("BELOW_V1_PRICE_FLOOR" if (r["price"] or 0) < V1_PRICE
                                          else "BELOW_V1_ADV20_FLOOR")
        elif r["is_shadow_core"]:
            st, why = "SHADOW_CORE", f"ADV20_RANK_{r['core_rank']}"
        else:
            st, why = "SHADOW_EVENT_ELIGIBLE", f"ADV20_RANK_{r['core_rank']}_OUTSIDE_CORE_{CORE_SIZE}"
        r.update(shadow_state=st, reason=why)
    c = connect_rw()
    cols = ("symbol", "exchange", "security_type", "cik", "price", "prev_close_v1", "adv20", "adv20_sh",
            "daily_coverage", "bar_coverage", "range_bps", "spread_bps", "half_spread_bps", "structurally_eligible",
            "structural_reason", "v1_floor_eligible", "core_rank", "is_shadow_core", "is_v2_forced_active",
            "is_operator_forced_active", "shadow_state", "reason")
    with c:
        c.execute("DELETE FROM snapshot WHERE snapshot_id=?", (sid,))
        c.executemany(f"INSERT INTO snapshot (snapshot_id, window_id, {','.join(cols)}, snapshot_as_of) VALUES "
                      f"(?,?,{','.join('?' * len(cols))},?)",
                      [(sid, window_id, *[r.get(k) for k in cols], now) for r in rows])
        c.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?)",
                  (sid, window_id, ref.isoformat(), now, len(rows), CORE_SIZE, json.dumps(cost)))
    return {"snapshot_id": sid, "rows": len(rows), "v1_eligible": len(ranked), "cost": cost}


# ------------------------------------------------------------------------------------------------------ sweep
def gap_from_trade(lt: dict, prev_close_v1: float | None, pm_start: datetime, sip_as_of: datetime) -> float | None:
    """|gap| input for the sweep: latestTrade price vs V1's OWN reference close. None when unusable: no trade / no
    reference close / trade before this window's 04:00 ET start / trade older than V1's 45-min stale gate."""
    if not lt or not lt.get("p") or not lt.get("t") or not prev_close_v1:
        return None
    t = ts(lt["t"])
    if t < pm_start or (sip_as_of - t) > timedelta(minutes=STALE_MIN):
        return None
    return (float(lt["p"]) / float(prev_close_v1) - 1.0) * 100.0


class Collector:
    def __init__(self):
        self.c = connect_rw()
        self.h = alpaca_headers()
        self.ua = sec_ua()
        self.window_id = None
        self.snap: dict[str, sqlite3.Row] = {}
        self.eligible: list[str] = []
        self.cik_sym: dict[str, str] = {}
        self.sweeps_in_window = 0
        self.last_edgar = 0.0

    def ensure_window(self, window_id: str) -> bool:
        if self.window_id == window_id and self.snap:
            return True
        r = self.c.execute("SELECT snapshot_id FROM snapshots WHERE window_id=?", (window_id,)).fetchone()
        if r is None:
            try:
                build_snapshot(window_id, extras=os.environ.get("DTU_SNAPSHOT_EXTRAS", "1") == "1")
            except RuntimeError:
                return False
            r = self.c.execute("SELECT snapshot_id FROM snapshots WHERE window_id=?", (window_id,)).fetchone()
        rows = self.c.execute("SELECT * FROM snapshot WHERE snapshot_id=?", (r[0],)).fetchall()
        self.snap = {x["symbol"]: x for x in rows}
        self.eligible = sorted(s for s, x in self.snap.items() if x["structurally_eligible"])
        self.cik_sym = {x["cik"]: s for s, x in self.snap.items() if x["cik"] and x["structurally_eligible"]}
        self.window_id = window_id
        self.sweeps_in_window = self.c.execute("SELECT COUNT(*) FROM sweeps WHERE window_id=?",
                                               (window_id,)).fetchone()[0]
        return True

    def _snapshots(self, syms: list[str]) -> tuple[dict, int, list[str]]:
        out, n, errs = {}, 0, []
        for i in range(0, len(syms), 1000):
            u = SNAP_URL + "?" + urllib.parse.urlencode({"symbols": ",".join(syms[i:i + 1000]), "feed": "delayed_sip"})
            n += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers=self.h), timeout=60) as r:
                    out.update(json.loads(r.read()))
            except Exception as exc:  # noqa: BLE001 -- recorded; never retried into production's rate budget
                errs.append(f"batch@{i}: {type(exc).__name__}: {str(exc)[:120]}")
        return out, n, errs

    def _protection(self, window_id: str, now: datetime, sweep_id: int) -> tuple[int, int]:
        """Production's open candidate identities (read-only) -> OPEN_CANDIDATE_PROTECTION (first time seen)."""
        o = ro(LIVE / "opportunity.db")
        rows = o.execute("SELECT candidate_id, symbol, first_seen_utc, state FROM candidates WHERE state IN "
                         "('WATCH','BULLISH_SETUP','BEARISH_SETUP')").fetchall()
        new = 0
        with self.c:
            for r in rows:
                cur = self.c.execute("INSERT OR IGNORE INTO promotions VALUES (?,?,?,?,?,?)",
                                     (window_id, r["symbol"], "OPEN_CANDIDATE_PROTECTION", iso(now), sweep_id,
                                      json.dumps({"candidate_id": r["candidate_id"],
                                                  "prod_first_seen_utc": r["first_seen_utc"], "state": r["state"]})))
                new += cur.rowcount
        return new, len({r["symbol"] for r in rows})

    def _edgar(self, window_id: str, now: datetime, sweep_id: int) -> int:
        if time.monotonic() - self.last_edgar < EDGAR_EVERY_S:
            return 0
        self.last_edgar = time.monotonic()
        t0, new, entries, err = time.monotonic(), 0, 0, None
        try:
            req = urllib.request.Request(EDGAR_8K, headers={"User-Agent": self.ua})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", "replace")
            for ent in re.findall(r"<entry>(.*?)</entry>", text, re.S):
                entries += 1
                title = re.search(r"<title>(.*?)</title>", ent, re.S)
                upd = re.search(r"<updated>(.*?)</updated>", ent)
                acc = re.search(r"accession-number=([0-9-]+)", ent)
                cik = re.search(r"\((\d{10})\)", title.group(1) if title else "")
                form = (title.group(1).split(" - ")[0].strip() if title else "")
                if not (acc and cik and upd) or not form.startswith("8-K"):
                    continue
                sym = self.cik_sym.get(cik.group(1))
                u = ts(upd.group(1)).astimezone(UTC)
                with self.c:
                    cur = self.c.execute("INSERT OR IGNORE INTO edgar_8k VALUES (?,?,?,?,?,?)",
                                         (acc.group(1), cik.group(1), form, iso(u), sym, iso(now)))
                    if cur.rowcount and sym:
                        new += self.c.execute("INSERT OR IGNORE INTO promotions VALUES (?,?,?,?,?,?)",
                                              (window_id, sym, "SEC_8K", iso(now), sweep_id,
                                               json.dumps({"accession": acc.group(1), "form": form,
                                                           "updated_utc": iso(u)}))).rowcount
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {str(exc)[:160]}"
        with self.c:
            self.c.execute("INSERT INTO edgar_polls (at_utc, ok, entries, new, duration_s, error) VALUES (?,?,?,?,?,?)",
                           (iso(now), int(err is None), entries, new, round(time.monotonic() - t0, 2), err))
        return new

    def sweep(self, now: datetime) -> dict | None:
        from talonx_opportunity.phases import phase_at
        from talonx_premarket.alpaca_data import data_as_of
        phase, w = phase_at(now)
        if w is None or phase not in ("PREMARKET", "REGULAR", "AFTER_HOURS"):
            return None
        if not self.ensure_window(w.window_id):
            return None
        sip_as_of = data_as_of(now)
        t0 = time.monotonic()
        snaps, nreq, errs = self._snapshots(self.eligible)
        dur = time.monotonic() - t0
        with self.c:
            cur = self.c.execute("INSERT INTO sweeps (window_id, at_utc, phase, sip_as_of, requests, duration_s, "
                                 "symbols_checked) VALUES (?,?,?,?,?,?,?)",
                                 (w.window_id, iso(now), phase, iso(sip_as_of), nreq, round(dur, 3), len(self.eligible)))
            sid = cur.lastrowid
        usable = stale = gap_new = 0
        pm_start = w.premarket_start_utc
        cross_rows, promo_rows = [], []
        for s in self.eligible:
            sn = snaps.get(s) or {}
            lt = sn.get("latestTrade") or {}
            x = self.snap[s]
            g = gap_from_trade(lt, x["prev_close_v1"], pm_start, sip_as_of)
            if g is None:
                stale += int(bool(lt.get("t")) and bool(x["prev_close_v1"]))
                continue
            usable += 1
            for th in CROSS_THRESHOLDS:
                if abs(g) >= th:
                    cross_rows.append((w.window_id, s, th, iso(now), round(g, 3), lt["t"]))
            if abs(g) >= GAP_TRIGGER_PCT and x["v1_floor_eligible"]:
                promo_rows.append((w.window_id, s, "GAP_TRIGGER", iso(now), sid,
                                   json.dumps({"gap_pct": round(g, 3), "trade_utc": lt["t"],
                                               "core_rank": x["core_rank"]})))
        with self.c:
            self.c.executemany("INSERT OR IGNORE INTO first_cross VALUES (?,?,?,?,?,?)", cross_rows)
            for pr in promo_rows:
                gap_new += self.c.execute("INSERT OR IGNORE INTO promotions VALUES (?,?,?,?,?,?)", pr).rowcount
        prot_new, prot_now = self._protection(w.window_id, now, sid)
        k8 = self._edgar(w.window_id, now, sid)
        eff = self.effective_active(w.window_id)
        with self.c:
            self.c.execute("UPDATE sweeps SET usable=?, stale_excluded=?, gap_promotions_new=?, sec8k_promotions_new=?, "
                           "protection_new=?, protected_now=?, effective_active=?, errors=? WHERE id=?",
                           (usable, stale, gap_new, k8, prot_new, prot_now, eff, json.dumps(errs) if errs else None,
                            sid))
        self.sweeps_in_window += 1
        if self.sweeps_in_window % VERIFY_EVERY_N == 1:
            self._verify(sid, now, phase, snaps)
        return {"sweep": sid, "phase": phase, "requests": nreq, "s": round(dur, 2), "usable": usable, "gap_new": gap_new,
                "8k_new": k8, "effective_active": eff}

    def effective_active(self, window_id: str) -> int:
        """Core(1200) + forced + every symbol promoted so far this window (gap / 8-K / production-open protection)."""
        base = {s for s, x in self.snap.items() if x["is_shadow_core"] or x["is_v2_forced_active"]
                or x["is_operator_forced_active"]}
        prom = {r[0] for r in self.c.execute("SELECT DISTINCT symbol FROM promotions WHERE window_id=?", (window_id,))}
        return len(base | prom)

    def _verify(self, sid: int, now: datetime, phase: str, snaps: dict) -> None:
        """Fixed sample: snapshot fields beside V1's own aggregate last bar + reference close (read-only)."""
        sample = [s for s in self.eligible if self.snap[s]["v1_floor_eligible"]][:: max(1, len(self.eligible)
                                                                                           // VERIFY_SAMPLE)]
        m = ro(LIVE / "market.db")
        ing = m.execute("SELECT as_of_utc FROM ingestion_state WHERE window_id=?", (self.window_id,)).fetchone()
        aggs = {r["symbol"]: json.loads(r["agg_json"]) for r in m.execute(
            f"SELECT symbol, agg_json FROM aggregates WHERE window_id=? AND symbol IN ({','.join('?' * len(sample))})",
            (self.window_id, *sample))}
        rows = []
        for s in sample:
            sn = snaps.get(s) or {}
            lt, pb, db, mb = (sn.get("latestTrade") or {}, sn.get("prevDailyBar") or {}, sn.get("dailyBar") or {},
                              sn.get("minuteBar") or {})
            a = aggs.get(s) or {}
            rows.append((sid, iso(now), phase, s, lt.get("p"), lt.get("t"), pb.get("c"), pb.get("t"), db.get("c"),
                         db.get("t"), mb.get("c"), mb.get("t"), self.snap[s]["prev_close_v1"], a.get("last_c"),
                         a.get("last_t"), ing[0] if ing else None))
        with self.c:
            self.c.executemany("INSERT OR IGNORE INTO verify VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def run_forever() -> None:
    col = Collector()
    with col.c:
        col.c.execute("INSERT OR REPLACE INTO meta VALUES ('started_utc', ?)", (iso(datetime.now(UTC)),))
        col.c.execute("INSERT OR REPLACE INTO meta VALUES ('pid', ?)", (str(os.getpid()),))
    while True:
        t = time.monotonic()
        now = datetime.now(UTC)
        try:
            r = col.sweep(now)
            if r:
                print(json.dumps({"at": iso(now), **r}), flush=True)
        except Exception as exc:  # noqa: BLE001 -- the shadow must never crash-loop; log and continue
            print(json.dumps({"at": iso(now), "error": f"{type(exc).__name__}: {str(exc)[:300]}"}), flush=True)
        time.sleep(max(1.0, SWEEP_EVERY_S - (time.monotonic() - t)))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "snapshot":
        print(json.dumps(build_snapshot(a[1] if len(a) > 1 else datetime.now(UTC).date().isoformat())))
    else:
        run_forever()
