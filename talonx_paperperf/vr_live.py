"""
VR_PAPER_V1 live tracker -- a SEPARATE, independently restartable research process (not a supervised Opportunity
Engine component: it never touches runtime.py hashes, discovery, ingestion, promotion, notifier or V2).

  reads     promotion.db PROMOTED_SIGNAL rows (read-only) through its own durable cursor; Telegram SENT times from
            promotion_signal_notifications.db (read-only); market.db DTU state (read-only); Alpaca SIP 1-min bars
  writes    results/vr_paper/vr_live.db (trades, cursor, heartbeat, capital, meta) and its OWN outbox
            results/vr_paper/vr_paper_notifications.db -> drained to the RESEARCH (Lab) destination only when
            TALONX_VR_DELIVER=1. Telegram: VIRTUAL_REALTIME ENTRY / EXIT only (plain text, tagged #VR_PAPER).
  clock     virtual time T = wall clock - 16 min (the SIP delay); only bars that CLOSED by T are ever used.
  modes     VIRTUAL_REALTIME and ACTIONABLE, separate capital books ($100k, $10k per position, max 10 open each).
  recovery  every state transition is durable; alerts are idempotent by event id (VR_ENTRY:/VR_EXIT:<trade_id>),
            so a restart restores OPEN positions and never replays a completed trade or re-sends an alert.
If this process dies, Signals are unaffected (it is read-only on every production store).

ENTRY CONTROL (2026-10-07, owner decision; enforces results/vr_paper/ARM_INTERRUPTION_2026-10-07.json in code).
  ``results/vr_paper/entry_control.json`` {"entries_blocked": true, "boundary_utc": ...} closes BOTH arms to new
  entries: Signals decided at/after the boundary never become trades (the cursor still advances, so a later
  rollback cannot replay them), and no PAPER_ENTRY_PENDING row whose Signal is at/after the boundary can open.
  OPEN positions keep being managed to exit. A malformed / unreadable control blocks ALL new entries (fail safe)
  and is reported in the heartbeat. No control file = the original (uninterrupted) behaviour.
  ACTIONABLE: a Signal SENT at or after its session's flatten (15:50 ET) is SENT_AFTER_FLATTEN (never enters).
usage: python -m talonx_paperperf.vr_live run [--once] [--until YYYY-MM-DD]  |  eod WINDOW_ID
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from talonx_paperperf import vr_paper as V  # noqa: E402

UTC = timezone.utc
LIVE = REPO / "results" / "opportunity"
OUT = REPO / "results" / "vr_paper"
SIP_DELAY = timedelta(minutes=16)
MODES = ("VIRTUAL_REALTIME", "ACTIONABLE")
START_CASH, POS_USD, MAX_OPEN = 100_000.0, 10_000.0, 10
PRODUCER = "VR_PAPER"
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS cursor (name TEXT PRIMARY KEY, last_decision_utc TEXT, last_promotion_id TEXT);
CREATE TABLE IF NOT EXISTS heartbeat (component TEXT PRIMARY KEY, at_utc TEXT, virtual_time_utc TEXT, detail_json TEXT);
CREATE TABLE IF NOT EXISTS capital (paper_mode TEXT, window_id TEXT, cash REAL, PRIMARY KEY (paper_mode, window_id));
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY, promotion_id TEXT, candidate_id TEXT, window_id TEXT, symbol TEXT, direction TEXT,
    paper_mode TEXT, state TEXT, skip_reason TEXT, score REAL, signal_market_time TEXT, signal_wall_time TEXT,
    entry_market_time TEXT, entry_price REAL, stop_price REAL, target_price REAL, rrr REAL, atr REAL,
    geometry_path TEXT, exit_market_time TEXT, exit_price REAL, exit_reason TEXT, gross_return REAL, cost REAL,
    net_return REAL, mfe REAL, mae REAL, holding_seconds INTEGER, holding_bars INTEGER, dtu_state TEXT,
    spread_bps REAL, version TEXT, policy_fp TEXT, created_utc TEXT, updated_utc TEXT);
"""


def ts(s):
    return V.ts(s)


ENTRY_CONTROL = "entry_control.json"


def entry_control(root: Path = OUT) -> dict:
    """{"state": OPEN | BLOCKED | MALFORMED_BLOCKING, "boundary_utc": datetime|None, "detail": str}."""
    f = root / ENTRY_CONTROL
    if not f.exists():
        return {"state": "OPEN", "boundary_utc": None, "detail": "no entry control"}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not isinstance(d.get("entries_blocked"), bool):
            raise ValueError("entries_blocked must be a boolean")
        if not d["entries_blocked"]:
            return {"state": "OPEN", "boundary_utc": None, "detail": "entries_blocked=false"}
        b = ts(d["boundary_utc"])
        if b.tzinfo is None:
            raise ValueError("boundary_utc must be timezone-aware")
        return {"state": "BLOCKED", "boundary_utc": b, "detail": d.get("record", "")}
    except Exception as exc:  # noqa: BLE001 -- fail safe: unreadable control blocks every new entry, loudly
        return {"state": "MALFORMED_BLOCKING", "boundary_utc": None, "detail": f"{type(exc).__name__}: {exc}"[:200]}


def entry_blocked(ctl: dict, decision_utc: str | None) -> bool:
    if ctl["state"] == "MALFORMED_BLOCKING":
        return True
    if ctl["state"] == "BLOCKED":
        return decision_utc is None or ts(decision_utc) >= ctl["boundary_utc"]
    return False


def iso(t):
    return t.astimezone(UTC).isoformat()


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def universe_segment(wid: str, live: Path = LIVE) -> str:
    """The Opportunity Engine universe policy that produced this window's Signals. Windows of different policies are
    separate segments of this tracker and are never pooled as one unchanged experiment (2026-10-04 live floor)."""
    try:
        r = ro(live / "market.db").execute("SELECT policy_fp FROM dtu_snapshots WHERE window_id=?", (wid,)).fetchone()
    except sqlite3.Error:
        r = None
    if r is None:
        return "UNKNOWN_NO_DTU_SNAPSHOT"
    from talonx_opportunity import universe_tiers as U
    return {p.fingerprint(): n for n, p in U.POLICIES.items()}.get(r[0], f"UNKNOWN_POLICY_{r[0]}")



def trade_id(promotion_id: str, mode: str) -> str:
    return hashlib.sha256(f"{V.VR_PAPER_VERSION}|{promotion_id}|{mode}".encode()).hexdigest()[:16]


# ============================================================================================================ render
def render_entry(t: dict, wall_received: str | None) -> str:
    rrr = f"{t['rrr']:.2f}" if t.get("rrr") else "n/a (ATR target)"
    lines = ["🧪 TALONX PAPER — VIRTUAL REALTIME", "", "#VR_PAPER #INTRADAY #ENTRY", "",
             f"🟢 {t['symbol']} · LONG", f"Entry ${t['entry_price']:.2f}",
             f"Virtual market time {ts(t['entry_market_time']).strftime('%H:%MZ')}"]
    if wall_received:
        lines.append(f"Feed received ~{ts(wall_received).strftime('%H:%MZ')}")
    if t.get("score") is not None:
        lines.append(f"Score {t['score']:.1f}")
    lines += ["", f"Stop ${t['stop_price']:.2f}", f"Target ${t['target_price']:.2f}", f"RRR {rrr}", "",
              "SIMULATED · no broker order", "Delayed feed treated as virtual realtime"]
    return "\n".join(lines)


EXIT_TAG = {"TARGET_HIT": "#TARGET", "STOP_HIT": "#STOP", "SESSION_CLOSE": "#SESSION_CLOSE", "TIME_EXIT": "#TIME_EXIT"}


def render_exit(t: dict) -> str:
    held = int((t["holding_seconds"] or 0) // 60)
    return "\n".join(["🧪 TALONX PAPER — EXIT", "",
                      f"#VR_PAPER #INTRADAY #EXIT {EXIT_TAG.get(t['exit_reason'], '#' + t['exit_reason'])}", "",
                      t["symbol"], f"Entry ${t['entry_price']:.2f}", f"Exit ${t['exit_price']:.2f}",
                      f"Net {100 * t['net_return']:+.2f}%", f"Held {held}m", "", "SIMULATED · no broker order"])


# ============================================================================================================ tracker
class VRLive:
    def __init__(self, root: Path = OUT, *, live: Path = LIVE, bars_fn=None, spread_fn=None, now_fn=None,
                 deliver: bool = False, drain_fn=None, dtu_fn=None, skip_backlog: bool = False):
        self.dtu_fn, self.skip_backlog = dtu_fn, skip_backlog
        root.mkdir(parents=True, exist_ok=True)
        self.root, self.live = root, live
        self.con = sqlite3.connect(root / "vr_live.db", timeout=30)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO meta VALUES ('VR_PAPER_VERSION', ?)", (V.VR_PAPER_VERSION,))
            self.con.execute("INSERT OR REPLACE INTO meta VALUES ('VR_PAPER_POLICY_FINGERPRINT', ?)",
                             (V.policy_fingerprint(),))
        from talonx_ops.notify.outbox import NotifyStore
        self.outbox = NotifyStore(str(root / "vr_paper_notifications.db"))
        self.bars_fn, self.spread_fn = bars_fn, spread_fn
        self.now_fn = now_fn or (lambda: datetime.now(UTC))
        self.deliver, self.drain_fn = deliver, drain_fn
        self._prev_cache: dict = {}

    # -- inputs (read-only) ------------------------------------------------------------------------------------------
    def new_signals(self, wid: str) -> list[dict]:
        r = self.con.execute("SELECT last_decision_utc, last_promotion_id FROM cursor WHERE name=?", (wid,)).fetchone()
        last = (r["last_decision_utc"], r["last_promotion_id"]) if r else ("", "")
        p = ro(self.live / "promotion.db")
        rows = [dict(x) for x in p.execute(
            "SELECT promotion_id, candidate_id, symbol, direction, score, data_as_of_utc, event_utc, decision_utc, "
            "reference_price, signal_event_id FROM promotions WHERE window_id=? AND state='PROMOTED_SIGNAL' "
            "ORDER BY decision_utc, promotion_id", (wid,))]
        return [x for x in rows if (x["decision_utc"], x["promotion_id"]) > last]

    def sent_time(self, sig: dict) -> str | None:
        try:
            ob = ro(self.live / "promotion_signal_notifications.db")
            r = ob.execute("SELECT sent_at_utc FROM ops_notification_outbox WHERE event_id=? AND state='SENT'",
                           (sig["signal_event_id"] or sig["promotion_id"],)).fetchone()
            return r[0] if r else None
        except sqlite3.Error:
            return None

    def dtu_state(self, wid: str, sig: dict) -> str | None:
        if self.dtu_fn is not None:
            return self.dtu_fn(wid, sig)
        try:
            from talonx_paperperf.signal_forensics import production_dtu_state
            return production_dtu_state(wid, [{"promotion_id": sig["promotion_id"], "symbol": sig["symbol"],
                                               "event_utc": sig["event_utc"]}]).get(sig["promotion_id"])
        except Exception:  # noqa: BLE001 -- descriptive field only
            return None

    # -- state ---------------------------------------------------------------------------------------------------------
    def cash(self, mode: str, wid: str) -> float:
        r = self.con.execute("SELECT cash FROM capital WHERE paper_mode=? AND window_id=?", (mode, wid)).fetchone()
        return float(r[0]) if r else START_CASH

    def n_open(self, mode: str, wid: str) -> int:
        return self.con.execute("SELECT COUNT(*) FROM trades WHERE paper_mode=? AND window_id=? AND state='OPEN'",
                                (mode, wid)).fetchone()[0]

    def _set_cash(self, mode, wid, v):
        self.con.execute("INSERT OR REPLACE INTO capital VALUES (?,?,?)", (mode, wid, v))

    def ingest(self, wid: str) -> int:
        sigs = self.new_signals(wid)
        ctl = entry_control(self.root)
        if ctl["state"] != "OPEN":
            blocked = [s for s in sigs if entry_blocked(ctl, s["decision_utc"])]
            if blocked:
                # never become trades; the cursor advances past them so a rollback of the control cannot replay them
                key = f"entry_control_blocked:{wid}"
                r = self.con.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
                prev = json.loads(r[0]) if r else {"signals": 0}
                with self.con:
                    self.con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(
                        {"signals": prev["signals"] + len(blocked), "control": ctl["state"],
                         "through": blocked[-1]["decision_utc"]})))
                    self.con.execute("INSERT OR REPLACE INTO cursor VALUES (?,?,?)",
                                     (wid, sigs[-1]["decision_utc"], sigs[-1]["promotion_id"]))
                sigs = [s for s in sigs if s not in blocked]
                if not sigs:
                    return 0
        fresh = self.con.execute("SELECT 1 FROM cursor WHERE name=?", (wid,)).fetchone() is None
        if fresh and self.skip_backlog and sigs:
            # first start inside a running session: Signals decided before the tracker existed are NOT replayed live
            # (no stale ENTRY flood); the EOD replay covers them. Recorded, never silent.
            with self.con:
                self.con.execute("INSERT OR REPLACE INTO cursor VALUES (?,?,?)",
                                 (wid, sigs[-1]["decision_utc"], sigs[-1]["promotion_id"]))
                self.con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                                 (f"backlog_skipped:{wid}", json.dumps({"signals": len(sigs), "through":
                                                                        sigs[-1]["decision_utc"]})))
            return 0
        with self.con:
            for s in sigs:
                for mode in MODES:
                    self.con.execute(
                        "INSERT OR IGNORE INTO trades (trade_id, promotion_id, candidate_id, window_id, symbol, "
                        "direction, paper_mode, state, score, signal_market_time, version, policy_fp, created_utc, "
                        "updated_utc) VALUES (?,?,?,?,?,?,?, 'PAPER_ENTRY_PENDING', ?,?,?,?,?,?)",
                        (trade_id(s["promotion_id"], mode), s["promotion_id"], s["candidate_id"], wid, s["symbol"],
                         "LONG", mode, s["score"], s["data_as_of_utc"], V.VR_PAPER_VERSION, V.policy_fingerprint(),
                         iso(self.now_fn()), iso(self.now_fn())))
            if sigs:
                self.con.execute("INSERT OR REPLACE INTO cursor VALUES (?,?,?)",
                                 (wid, sigs[-1]["decision_utc"], sigs[-1]["promotion_id"]))
        return len(sigs)

    # -- one cycle -------------------------------------------------------------------------------------------------
    def tick(self, wid: str, window, prev_window) -> dict:
        now = self.now_fn()
        T = now - SIP_DELAY                                   # the virtual market clock
        n_new = self.ingest(wid)
        if n_new and self.con.execute("SELECT 1 FROM meta WHERE k=?", (f"universe_segment:{wid}",)).fetchone() is None:
            with self.con:                                    # recorded once per window (segmentation, never pooled)
                self.con.execute("INSERT OR IGNORE INTO meta VALUES (?,?)",
                                 (f"universe_segment:{wid}", universe_segment(wid, self.live)))
        live = [dict(r) for r in self.con.execute(
            "SELECT * FROM trades WHERE window_id=? AND state IN ('PAPER_ENTRY_PENDING','OPEN') ORDER BY "
            "signal_market_time, trade_id", (wid,))]
        syms = sorted({t["symbol"] for t in live})
        bars = self.bars_fn(syms, window.premarket_start_utc, min(T, window.close_utc)) if syms else {}
        prev = self._prev_bars(syms, prev_window)
        flat = V.flatten_utc(window.close_utc)
        p = ro(self.live / "promotion.db")
        opened = exited = 0
        for t in live:
            clock = V.VirtualClock([b for b in bars.get(t["symbol"], []) if ts(b["t"]) + timedelta(minutes=1) <= T])
            if t["state"] == "PAPER_ENTRY_PENDING":
                o = self._try_open(t, clock, T, p, window, prev_window, prev, flat, wid)
                opened += o
                if o:                                         # catch up on bars already closed after the entry
                    t = dict(self.con.execute("SELECT * FROM trades WHERE trade_id=?", (t["trade_id"],)).fetchone())
                    exited += self._try_exit(t, clock, T, flat, wid)
            else:
                exited += self._try_exit(t, clock, T, flat, wid)
        ctl = entry_control(self.root)
        self.heartbeat(T, {"window": wid, "new_signals": n_new, "opened": opened, "exited": exited,
                           "open_vr": self.n_open("VIRTUAL_REALTIME", wid), "open_act": self.n_open("ACTIONABLE", wid),
                           "entry_control": ctl["state"], "entry_boundary_utc": iso(ctl["boundary_utc"])
                           if ctl["boundary_utc"] else None, "entry_control_detail": ctl["detail"]})
        d = self.drain()
        return {"virtual_time": iso(T), "new": n_new, "opened": opened, "exited": exited, "drain": d}

    def _prev_bars(self, syms, pw):
        need = [s for s in syms if s not in self._prev_cache]
        if need:
            got = self.bars_fn(need, pw.open_utc, pw.close_utc - timedelta(seconds=1))
            for s in need:
                self._prev_cache[s] = got.get(s, [])
        return self._prev_cache

    def _try_open(self, t, clock, T, p, window, pw, prev, flat, wid) -> int:
        sig = dict(p.execute("SELECT * FROM promotions WHERE promotion_id=?", (t["promotion_id"],)).fetchone())
        if entry_blocked(entry_control(self.root), sig.get("decision_utc")):
            return 0                                          # interrupted arm: stays pending, never opens
        M = ts(sig["data_as_of_utc"])
        after = M
        wall = self.sent_time(sig)
        if t["paper_mode"] == "ACTIONABLE":
            if not wall:
                if T > flat:
                    self._skip(t, "NEVER_SENT_BEFORE_FLATTEN")
                return 0
            if ts(wall) >= flat:                              # sent at/after this session's flatten: no entry
                self._skip(t, "SENT_AFTER_FLATTEN")
                return 0
            from talonx_paperperf.signal_forensics import ceil_min
            after = ceil_min(ts(wall))
        if T < max(after, window.open_utc) + timedelta(minutes=1):
            return 0                                          # the entry bar has not closed on the virtual clock
        piv = V.prior_pivots(prev.get(t["symbol"], []), pw.open_utc, pw.close_utc)
        g = V.geometry(float(sig["reference_price"]), clock.visible(M), piv)
        if g is None:
            self._skip(t, "NO_GEOMETRY")
            return 0
        eb = clock.next_bar_starting_at_or_after(max(after, window.open_utc), V.POLICY["entry_window_min"])
        if eb is None or ts(eb["t"]) >= flat:
            if T >= max(after, window.open_utc) + timedelta(minutes=V.POLICY["entry_window_min"] + 1) or T >= flat:
                self._skip(t, "NO_ENTRY_BAR")
            return 0
        if self.n_open(t["paper_mode"], wid) >= MAX_OPEN:
            self._skip(t, "CAPACITY_MAX_10_OPEN")
            return 0
        cash = self.cash(t["paper_mode"], wid)
        if cash < POS_USD:
            self._skip(t, "INSUFFICIENT_CASH")
            return 0
        et, ep = ts(eb["t"]), float(eb["o"])
        sp = self.spread_fn(t["symbol"], et) if self.spread_fn else None
        with self.con:
            self._set_cash(t["paper_mode"], wid, cash - POS_USD)
            self.con.execute(
                "UPDATE trades SET state='OPEN', signal_wall_time=?, entry_market_time=?, entry_price=?, stop_price=?, "
                "target_price=?, rrr=?, atr=?, geometry_path=?, spread_bps=?, cost=?, dtu_state=?, updated_utc=? "
                "WHERE trade_id=? AND state='PAPER_ENTRY_PENDING'",
                (wall, iso(et), ep, g["stop"], g["target"], g["rrr"], g["atr"], g["geometry_path"], sp,
                 max(20.0, sp or 0.0) / 1e4, self.dtu_state(wid, sig), iso(self.now_fn()), t["trade_id"]))
        if t["paper_mode"] == "VIRTUAL_REALTIME":
            row = dict(self.con.execute("SELECT * FROM trades WHERE trade_id=?", (t["trade_id"],)).fetchone())
            self._alert(f"VR_ENTRY:{t['trade_id']}", "VR_PAPER_ENTRY", render_entry(row, wall), row)
        return 1

    def _try_exit(self, t, clock, T, flat, wid) -> int:
        tr = V.Trade(t["symbol"], t["paper_mode"], "LONG", ts(t["entry_market_time"]), t["entry_price"],
                     t["stop_price"], t["target_price"])
        r = V.run_exit(tr, clock, min(T, flat))
        if r.get("exit_reason") in (None, "NO_BARS"):
            return 0
        if r["exit_reason"] == "SESSION_CLOSE" and T < flat:
            return 0                                          # still open: no level touched yet, flatten not reached
        net = r["gross"] - t["cost"]
        with self.con:
            cur = self.con.execute(
                "UPDATE trades SET state='EXITED', exit_market_time=?, exit_price=?, exit_reason=?, gross_return=?, "
                "net_return=?, mfe=?, mae=?, holding_seconds=?, holding_bars=?, updated_utc=? WHERE trade_id=? AND "
                "state='OPEN'", (iso(r["exit_t"]), r["exit_px"], r["exit_reason"], r["gross"], net, r["mfe"], r["mae"],
                                 r["holding_s"], r["holding_bars"], iso(self.now_fn()), t["trade_id"]))
            if cur.rowcount:
                self._set_cash(t["paper_mode"], wid, self.cash(t["paper_mode"], wid) + POS_USD * (1 + net))
        if cur.rowcount and t["paper_mode"] == "VIRTUAL_REALTIME":
            row = dict(self.con.execute("SELECT * FROM trades WHERE trade_id=?", (t["trade_id"],)).fetchone())
            self._alert(f"VR_EXIT:{t['trade_id']}", "VR_PAPER_EXIT", render_exit(row), row)
        return 1 if cur.rowcount else 0

    def _skip(self, t, why):
        with self.con:
            self.con.execute("UPDATE trades SET state='SKIPPED', skip_reason=?, updated_utc=? WHERE trade_id=? AND "
                             "state='PAPER_ENTRY_PENDING'", (why, iso(self.now_fn()), t["trade_id"]))

    def _alert(self, event_id, event_type, text, row):
        from talonx_ops.notify import RESEARCH
        self.outbox.enqueue(event_id=event_id, destination=RESEARCH, event_type=event_type, producer=PRODUCER,
                            dedup_key=event_id, payload_text=text,
                            provenance={"lane": "VR_PAPER", "paper_mode": row["paper_mode"], "simulated": True,
                                        "version": V.VR_PAPER_VERSION, "policy_fp": V.policy_fingerprint(),
                                        "trade_id": row["trade_id"], "not_a_trade_event": True})

    def drain(self):
        if not self.deliver:
            return None
        if self.drain_fn:
            return self.drain_fn(self.outbox)
        from talonx_ops.notify import RESEARCH
        from talonx_ops.notify.worker import drain
        return drain(self.outbox, destination=RESEARCH)

    def heartbeat(self, T, detail):
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO heartbeat VALUES ('vr_paper', ?, ?, ?)",
                             (iso(self.now_fn()), iso(T), json.dumps(detail)))


# ============================================================================================================ EOD
def eod(wid: str) -> dict:
    con = sqlite3.connect(OUT / "vr_live.db")
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM trades WHERE window_id=?", (wid,))]
    res = {"window_id": wid, "version": V.VR_PAPER_VERSION, "fingerprint": V.policy_fingerprint(),
           "oe_universe_segment": universe_segment(wid)}
    for mode in MODES:
        ex = [r for r in rows if r["paper_mode"] == mode and r["state"] == "EXITED"]
        m = V.metrics([{"gross": r["gross_return"], "net": r["net_return"], "mfe": r["mfe"], "mae": r["mae"]} for r in ex])
        m["portfolio"] = V.portfolio([{"entry_t": r["entry_market_time"], "exit_t": r["exit_market_time"],
                                       "gross": r["gross_return"], "net": r["net_return"]} for r in ex])
        m["states"] = {s: sum(1 for r in rows if r["paper_mode"] == mode and r["state"] == s)
                       for s in ("PAPER_ENTRY_PENDING", "OPEN", "EXITED", "SKIPPED")}
        m["skip_reasons"] = {k: sum(1 for r in rows if r["paper_mode"] == mode and r["skip_reason"] == k)
                             for k in {r["skip_reason"] for r in rows if r["skip_reason"]}}
        m["exit_reasons"] = {k: sum(1 for r in ex if r["exit_reason"] == k) for k in {r["exit_reason"] for r in ex}}
        m["by_dtu"] = {k: V.metrics([{"gross": r["gross_return"], "net": r["net_return"]} for r in ex
                                     if (r["dtu_state"] or "").startswith(k)]) for k in ("ACTIVE_CORE", "EVENT_PROMOTED",
                                                                                          "OPERATOR")}
        res[mode] = m
    v, a = res["VIRTUAL_REALTIME"], res["ACTIONABLE"]
    if v.get("n") and a.get("n"):
        res["DELAY_EFFECT (ACTIONABLE - VIRTUAL)"] = {k: round(a[k] - v[k], 3) for k in
                                                     ("gross_mean_pct", "net_mean_pct", "win_rate")}
        res["DELAY_EFFECT (ACTIONABLE - VIRTUAL)"]["net_pnl_usd"] = round(a["portfolio"]["net_pnl_usd"] -
                                                                         v["portfolio"]["net_pnl_usd"], 2)
    (OUT / f"eod_{wid}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res


def main(argv):
    from talonx_opportunity.phases import trading_window
    from talonx_paperperf import signal_forensics as F
    if argv[0] == "eod":
        print(json.dumps(eod(argv[1]), indent=1, default=str))
        return
    from talonx_premarket import __main__ as M
    M._env()                                                  # .env (incl. the RESEARCH destination aliases), as notifier
    once = "--once" in argv
    until = date.fromisoformat(argv[argv.index("--until") + 1]) if "--until" in argv else date(2026, 10, 16)
    data_holder = {}

    def bars_fn(syms, a, b):
        got, data = F.fetch_bars(syms, a, b)
        data_holder["d"] = data
        return got

    def spread_fn(sym, t):
        d = data_holder.get("d")
        return F.quote_spread(d, sym, t)[0] if d else None

    vr = VRLive(bars_fn=bars_fn, spread_fn=spread_fn, deliver=os.environ.get("TALONX_VR_DELIVER", "0") == "1",
                skip_backlog=True)
    while datetime.now(UTC).date() <= until:                  # explicit stop condition
        today = datetime.now(UTC).date()
        try:
            w = trading_window(today)
        except ValueError:
            w = None
        if w is not None and w.premarket_start_utc <= datetime.now(UTC) <= w.close_utc + SIP_DELAY + timedelta(minutes=5):
            try:
                out = vr.tick(today.isoformat(), w, trading_window(w.reference_session))
                print(json.dumps(out, default=str), flush=True)
            except Exception as ex:  # noqa: BLE001 -- keep the tracker alive; state is durable
                print(json.dumps({"tick_error": repr(ex)[:300], "at": iso(datetime.now(UTC))}), flush=True)
        if once:
            return
        time.sleep(60)


if __name__ == "__main__":
    main(sys.argv[1:])
