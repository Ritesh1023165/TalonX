"""
Dynamic Tradable Universe SHADOW evaluator (2026-09-29). READ-ONLY: production stores and shadow.db are opened
``mode=ro``; output is JSON / CSV under results/dtu_shadow/eval/.

For one trading window it answers, for EVERY production event, whether a Core(N) + Event-Tier universe would have had
the symbol active when production decided it, and how late:

  SAME_SCAN       active (Core / forced / promoted) at or before the production decision time
  ONE_SCAN_LATE   promoted after the decision but no later than the next production scan
  TWO_PLUS_LATE   promoted later than that, still inside the window
  MISSED          never active in the window

Protection is computed two ways and BOTH are reported:
  PROD      production's open candidate for the symbol protects it (the task's rule; optimistic because under a
            reduced universe that identity might never have been created)
  POLICY    only identities whose own NEW event was captured under the same policy protect (non-circular)
Assumption (stated, not proven): an event recovered N scans late would still have occurred at that later scan.
usage: python -m talonx_shadow.dtu_eval WINDOW_ID [--from ISO]   -> results/dtu_shadow/eval/<window>.json
"""
from __future__ import annotations

import bisect
import collections as C
import csv
import json
import sqlite3
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from talonx_opportunity.phases import trading_window  # noqa: E402
from talonx_shadow.dtu import LIVE, OUT, ACTIVE_STATES, shadow_db  # noqa: E402

UTC = timezone.utc
CORES = (500, 750, 1000, 1200, 1500, 2000)
PRIMARY = 1200
SETUP_STATES = ("BULLISH_SETUP", "BEARISH_SETUP")
MISSED, SAME, ONE, TWO = "MISSED", "SAME_SCAN", "ONE_SCAN_LATE", "TWO_PLUS_LATE"


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def q(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))], 3) if xs else None


def sessions_before(d: date, n: int) -> list[date]:
    out, x = [], d
    while len(out) < n:
        x -= timedelta(days=1)
        try:
            if x.weekday() < 5 and trading_window(x) is not None:
                out.append(x)
        except ValueError:
            pass
    return out


# ============================================================================================================ inputs
class Window:
    def __init__(self, wid: str, since: str | None = None):
        self.wid = wid
        self.w = trading_window(date.fromisoformat(wid))
        sh = ro(shadow_db())
        sid = sh.execute("SELECT snapshot_id FROM snapshots WHERE window_id=?", (wid,)).fetchone()
        if sid is None:
            raise SystemExit(f"no shadow snapshot for {wid}")
        self.snap = {r["symbol"]: dict(r) for r in sh.execute("SELECT * FROM snapshot WHERE snapshot_id=?", (sid[0],))}
        self.sweeps = [dict(r) for r in sh.execute("SELECT * FROM sweeps WHERE window_id=? ORDER BY id", (wid,))]
        self.since = since or (self.sweeps[0]["at_utc"] if self.sweeps else None)
        self.prom = C.defaultdict(dict)            # symbol -> reason -> first_at
        for r in sh.execute("SELECT symbol, reason, first_at_utc FROM promotions WHERE window_id=?", (wid,)):
            self.prom[r[0]][r[1]] = r[2]
        # 8-K TTL 3 sessions: filings seen in this window or the previous 2 sessions' windows
        prev = [d.isoformat() for d in sessions_before(self.w.session, 2)]
        self.k8 = C.defaultdict(list)
        for r in sh.execute("SELECT symbol, seen_utc FROM edgar_8k WHERE symbol IS NOT NULL"):
            self.k8[r[0]].append(r[1])
        self.k8_windows = set(prev + [wid])
        self.cross = C.defaultdict(dict)
        for r in sh.execute("SELECT symbol, threshold, at_utc FROM first_cross WHERE window_id=?", (wid,)):
            self.cross[r[0]][r[1]] = r[2]
        self.edgar_polls = [dict(r) for r in sh.execute("SELECT * FROM edgar_polls WHERE at_utc >= ? AND at_utc < ?",
                                                        (iso_(self.w.premarket_start_utc),
                                                         iso_(self.w.after_hours_end_utc)))]
        o = ro(LIVE / "opportunity.db")
        self.scans = [dict(r) for r in o.execute("SELECT decision_utc, phase, state, duration_s, funnel_json FROM scans "
                                                 "WHERE window_id=? AND state='SCANNED' ORDER BY decision_utc", (wid,))]
        self.scan_times = [s["decision_utc"] for s in self.scans]
        self.events = [dict(r) for r in o.execute(
            "SELECT seq, event_id, candidate_id, symbol, at_utc, event_type, from_state, to_state, classification, "
            "score, gap_pct FROM candidate_events WHERE window_id=? ORDER BY seq", (wid,))]
        self.spans = {}
        for r in o.execute("SELECT candidate_id, symbol, at_utc, event_type FROM candidate_events ORDER BY seq"):
            if r[3] == "NEW":
                self.spans[r[0]] = [r[1], r[2], None]
            elif r[3] in ("INVALIDATED", "EXPIRED") and r[0] in self.spans:
                self.spans[r[0]][2] = r[2]
        self.near = C.defaultdict(lambda: C.defaultdict(set))
        for r in o.execute("SELECT decision_utc, symbol, cls FROM near_misses WHERE window_id=?", (wid,)):
            self.near[r[0]]["ALL"].add(r[1])
            if r[2] == "SCORED":
                self.near[r[0]]["SCORED"].add(r[1])
        pr = ro(LIVE / "promotion.db")
        self.signals = [dict(r) for r in pr.execute(
            "SELECT p.*, o.ret_15m_pct, o.ret_30m_pct, o.ret_1h_pct, o.close_ret_pct, o.status AS outcome_status "
            "FROM promotions p LEFT JOIN paper_outcomes o USING(promotion_id) WHERE p.window_id=? AND "
            "p.state='PROMOTED_SIGNAL'", (wid,))]
        n = ro(LIVE / "notification.db")
        lab = ro(LIVE / "opportunity_research_notifications.db")
        sent = {r[0]: r[1] for r in lab.execute("SELECT event_id, sent_at_utc FROM ops_notification_outbox "
                                                "WHERE state='SENT'")}
        cols = {r[1] for r in n.execute("PRAGMA table_info(decisions)")}
        rr = "route_reason" if "route_reason" in cols else "NULL"
        at = {e["event_id"]: e["at_utc"] for e in self.events}
        self.lab = [dict(r) | {"at_utc": at.get(r["event_id"], r["decided_utc"])} for r in n.execute(
            f"SELECT event_id, symbol, event_type, classification, decided_utc, {rr} AS route_reason FROM decisions "
            "WHERE window_id=? AND outbox_event_id IS NOT NULL", (wid,)) if r["event_id"] in sent]
        m = ro(LIVE / "market.db")
        self.aggs = {r["symbol"]: json.loads(r["agg_json"]) for r in
                     m.execute("SELECT symbol, agg_json FROM aggregates WHERE window_id=?", (wid,))}
        from talonx_shadow.dtu import forced_active
        v2, _ = forced_active()
        self.v2 = v2
        try:
            v2db = ro(REPO / "v2_release_rc1.db")
            self.v2_events = [dict(r) for r in v2db.execute(
                "SELECT symbol, eligible_entry_session, disposition FROM processed_episodes WHERE eligible_entry_session=?",
                (self.w.session.isoformat(),))]
        except sqlite3.Error:
            self.v2_events = []

    def in_scope(self, t: str) -> bool:
        return self.since is None or t >= self.since


def iso_(t):
    return t.astimezone(UTC).isoformat()


# ============================================================================================================ policy
class Policy:
    def __init__(self, W: Window, core_n: int, protection: str):
        self.W, self.n, self.protection = W, core_n, protection
        self.policy_prot = C.defaultdict(list)       # symbol -> [(start, end)] for POLICY protection
        if protection == "POLICY":
            for e in sorted((e for e in W.events if e["event_type"] == "NEW"), key=lambda e: (e["at_utc"], e["seq"])):
                st, _, _ = self.status(e["symbol"], e["at_utc"])
                if st != MISSED:
                    sym, a, b = W.spans[e["candidate_id"]]
                    self.policy_prot[sym].append((a, b))

    def base(self, sym: str) -> str | None:
        x = self.W.snap.get(sym)
        if not x:
            return None
        if x["is_operator_forced_active"]:
            return "OPERATOR_FORCED"
        if x["is_v2_forced_active"]:
            return "V2_FORCED"
        if x["core_rank"] and x["core_rank"] <= self.n:
            return "CORE"
        return None

    def promotions(self, sym: str, t: str) -> list[tuple[str, str]]:
        """(time, reason) of every promotion of ``sym`` relevant at/after ``t`` (earliest first)."""
        x = self.W.snap.get(sym) or {}
        out = []
        p = self.W.prom.get(sym, {})
        if "GAP_TRIGGER" in p and x.get("v1_floor_eligible"):
            out.append((p["GAP_TRIGGER"], "GAP_TRIGGER"))
        if "SEC_8K" in p and x.get("v1_floor_eligible"):
            out.append((p["SEC_8K"], "SEC_8K"))
        if self.protection == "PROD" and "OPEN_CANDIDATE_PROTECTION" in p:
            out.append((p["OPEN_CANDIDATE_PROTECTION"], "OPEN_CANDIDATE_PROTECTION"))
        if self.protection == "POLICY":
            for a, b in self.policy_prot.get(sym, ()):
                if b is None or b >= t:
                    out.append((a, "OPEN_CANDIDATE_PROTECTION"))
        return sorted(out)

    def status(self, sym: str, t: str) -> tuple[str, str | None, str | None]:
        b = self.base(sym)
        if b:
            return SAME, b, None
        pr = self.promotions(sym, t)
        # protection must predate the event (an identity cannot protect its own creation); triggers may coincide
        before = [p for p in pr if (p[1] != "OPEN_CANDIDATE_PROTECTION" and p[0] <= t) or
                  (p[1] == "OPEN_CANDIDATE_PROTECTION" and p[0] < t)]
        if before:
            return SAME, before[0][1], before[0][0]
        after = [p for p in pr if p[0] > t]
        if not after:
            return MISSED, None, None
        p_t, reason = after[0]
        st = self.W.scan_times
        i = bisect.bisect_right(st, t)                     # next production scan after t
        return (ONE if i < len(st) and p_t <= st[i] else TWO), reason, p_t

    def active_at(self, t: str) -> set[str]:
        out = set()
        for s, x in self.W.snap.items():
            if self.base(s):
                out.add(s)
        for s, p in self.W.prom.items():
            for reason, at in p.items():
                if reason == "OPEN_CANDIDATE_PROTECTION" and self.protection != "PROD":
                    continue
                if at <= t and (reason != "GAP_TRIGGER" or (self.W.snap.get(s) or {}).get("v1_floor_eligible")):
                    out.add(s)
        if self.protection == "POLICY":
            for s, iv in self.policy_prot.items():
                if any(a < t and (b is None or b >= t) for a, b in iv):
                    out.add(s)
        return out


# ============================================================================================================ evaluation
def populations(W: Window) -> dict[str, list[dict]]:
    ev = [e for e in W.events if W.in_scope(e["at_utc"])]
    setups, seen = [], set()
    for e in ev:
        if e["event_type"] in ("NEW", "UPGRADE") and e["to_state"] in SETUP_STATES and e["candidate_id"] not in seen:
            seen.add(e["candidate_id"])
            setups.append(e)
    sig = [dict(s, at_utc=s["event_utc"]) for s in W.signals if W.in_scope(s["event_utc"])]
    movers = []
    for s, x in W.snap.items():
        a = W.aggs.get(s)
        if not x["v1_floor_eligible"] or not a or not a.get("last_c") or not x["prev_close_v1"]:
            continue
        mv = (a["last_c"] / x["prev_close_v1"] - 1) * 100
        if abs(mv) >= 10:
            t = W.cross.get(s, {}).get(10.0) or (a.get("last_t") or "").replace("Z", "+00:00")
            if t and W.in_scope(t):
                movers.append({"symbol": s, "at_utc": t, "move_pct": round(mv, 2),
                               "engine_emitted": any(e["symbol"] == s for e in W.events)})
    return {"new_identities": [e for e in ev if e["event_type"] == "NEW"],
            "new_watch": [e for e in ev if e["event_type"] == "NEW" and e["to_state"] == "WATCH"],
            "setups": setups, "signals": sig, "signals_80": [s for s in sig if (s["score"] or 0) >= 80],
            "movers": movers, "lab": [x for x in W.lab if W.in_scope(x["at_utc"])],
            "v2_symbol_events": [e for e in ev if e["symbol"] in W.v2]}


def classify(pol: Policy, rows: list[dict]) -> tuple[dict, list[dict]]:
    counts = C.Counter()
    detail = []
    for r in rows:
        st, why, p_t = pol.status(r["symbol"], r["at_utc"])
        counts[st] += 1
        detail.append({**{k: r.get(k) for k in ("symbol", "at_utc", "event_type", "to_state", "score", "move_pct")},
                       "shadow": st, "reason": why, "promotion_time": p_t,
                       "latency_s": round((ts(p_t) - ts(r["at_utc"])).total_seconds()) if p_t and p_t > r["at_utc"] else 0})
    n = len(rows)
    captured = n - counts[MISSED]
    return {"total": n, "captured": captured, "capture_pct": pct(captured, n), SAME: counts[SAME], ONE: counts[ONE],
            TWO: counts[TWO], MISSED: counts[MISSED]}, detail


def workload(W: Window, pol: Policy) -> dict:
    eligible = sum(1 for x in W.snap.values() if x["structurally_eligible"])
    sizes, aw_s, sc_s, aw_f, sc_f, meas = [], 0, 0, 0, 0, 0
    ever: set[str] = set()
    timeline = C.defaultdict(list)
    for cid, (sym, a, b) in W.spans.items():
        timeline[sym].append((a, b))
    for sc in W.scans:
        t = sc["decision_utc"]
        if not W.in_scope(t):
            continue
        act = pol.active_at(t)
        ever |= act
        sizes.append(len(act))
        open_syms = {s for s, iv in timeline.items() if any(a <= t and (b is None or b > t) for a, b in iv)}
        aw = open_syms - W.near[t]["ALL"]
        aw_f += len(aw)
        sc_f += len(W.near[t]["SCORED"])
        aw_s += len(aw & act)
        sc_s += len(W.near[t]["SCORED"] & act)
        f = json.loads(sc["funnel_json"] or "{}")
        meas += (f.get("sec_cache") or {}).get("lookups") or 0
    bars_full = sum(a.get("bars", 0) for s, a in W.aggs.items())
    bars_sh = sum(W.aggs.get(s, {}).get("bars", 0) for s in ever)
    recon = aw_f + sc_f
    return {"FULL_BAR_SYMBOLS": eligible, "SHADOW_BAR_SYMBOLS_EVER_ACTIVE": len(ever),
            "FULL_EXPECTED_BAR_ROWS": bars_full, "SHADOW_EXPECTED_BAR_ROWS": bars_sh,
            "BAR_REDUCTION_PERCENT": pct(bars_full - bars_sh, bars_full),
            "FULL_INDICATOR_SYMBOLS": eligible,
            "SHADOW_INDICATOR_SYMBOLS_MEDIAN": statistics.median(sizes) if sizes else None,
            "SHADOW_INDICATOR_SYMBOLS_PEAK": max(sizes) if sizes else None,
            "INDICATOR_WORK_REDUCTION_PERCENT": pct(eligible - statistics.median(sizes), eligible) if sizes else None,
            "FULL_SEC_LOOKUPS_MEASURED": meas, "FULL_SEC_LOOKUPS_RECONSTRUCTED": recon,
            "SHADOW_EXPECTED_SEC_LOOKUPS": aw_s + sc_s,
            "SEC_REDUCTION_PERCENT": pct(recon - (aw_s + sc_s), recon),
            "reconstruction_vs_measured": round(recon / meas, 3) if meas else None}


def sec_observability(W: Window) -> dict:
    rows = []
    for sc in W.scans:
        f = (json.loads(sc["funnel_json"] or "{}").get("sec_cache") or {})
        if "max_served_age_raw" in f and W.in_scope(sc["decision_utc"]):
            rows.append(f)
    if not rows:
        return {"scans_with_raw_metrics": 0}
    ages = [r["max_served_age_raw"] for r in rows if r.get("max_served_age_raw") is not None]
    reasons = C.Counter()
    for r in rows:
        reasons.update(r.get("stale_fallback_reasons") or {})
    return {"scans_with_raw_metrics": len(rows), "max_served_age_raw": max(ages) if ages else None,
            "p95_of_scan_p95_raw": q([r["served_age_p95_raw"] for r in rows if r.get("served_age_p95_raw") is not None], .95),
            "p99_of_scan_p99_raw": q([r["served_age_p99_raw"] for r in rows if r.get("served_age_p99_raw") is not None], .99),
            "count_age_ge_590": sum(r.get("count_age_ge_590", 0) for r in rows),
            "count_age_ge_595": sum(r.get("count_age_ge_595", 0) for r in rows),
            "count_age_ge_600": sum(r.get("count_age_ge_600", 0) for r in rows),
            "stale_fallback_count": sum(r.get("stale_fallback_count", 0) for r in rows),
            "stale_fallback_reasons": dict(reasons), "no_data_count": sum(r.get("no_data_count", 0) for r in rows),
            "sync_refresh_count": sum(r.get("sync_refresh_count", 0) for r in rows),
            "cache_fresh_count": sum(r.get("cache_fresh_count", 0) for r in rows),
            "sec_request_rate_max": max(r.get("sec_request_rate_per_s") or 0 for r in rows),
            "sec_request_rate_median": statistics.median(r.get("sec_request_rate_per_s") or 0 for r in rows)}


def watch_fate(W: Window, pol: Policy) -> dict:
    nw = [e for e in W.events if e["event_type"] == "NEW" and e["to_state"] == "WATCH" and W.in_scope(e["at_utc"])]
    later = C.defaultdict(set)
    for e in W.events:
        if e["to_state"] in SETUP_STATES:
            later[e["candidate_id"]].add("SETUP")
    sig_c = {s["candidate_id"] for s in W.signals}
    lost = [e for e in nw if pol.status(e["symbol"], e["at_utc"])[0] == MISSED]
    return {"PRODUCTION_NEW_WATCH": len(nw), "SHADOW_NEW_WATCH": len(nw) - len(lost),
            "WATCH_CAPTURE_PERCENT": pct(len(nw) - len(lost), len(nw)),
            "lost_later_setup": sum(1 for e in lost if "SETUP" in later[e["candidate_id"]]),
            "lost_later_signal": sum(1 for e in lost if e["candidate_id"] in sig_c),
            "lost_never_mattered": sum(1 for e in lost if "SETUP" not in later[e["candidate_id"]]
                                       and e["candidate_id"] not in sig_c)}


def false_positives(W: Window, movers: list[dict]) -> dict:
    ev_syms = {e["symbol"] for e in W.events}
    mv = {m["symbol"] for m in movers}
    gp = [s for s, p in W.prom.items() if "GAP_TRIGGER" in p and (W.snap.get(s) or {}).get("v1_floor_eligible")
          and not (W.snap[s]["core_rank"] and W.snap[s]["core_rank"] <= PRIMARY)]
    useful = [s for s in gp if s in ev_syms or s in mv]
    return {"GAP_PROMOTED_TOTAL": len(gp), "GAP_PROMOTED_USEFUL": len(useful),
            "GAP_PROMOTED_NO_EVENT": len(gp) - len(useful), "useful_pct": pct(len(useful), len(gp))}


def rollover(W: Window) -> dict:
    inv = sorted((x for x in W.lab if x["event_type"] == "INVALIDATED"), key=lambda x: x["at_utc"])
    if not W.scan_times or not inv:
        return {"ROLLOVER_INVALIDATION_COUNT": 0}
    start = W.scan_times[0]
    burst = [x for x in inv if ts(x["at_utc"]) <= ts(start) + timedelta(minutes=30)]
    return {"ROLLOVER_INVALIDATION_COUNT": len(burst),
            "ROLLOVER_BURST_DURATION_S": round((ts(burst[-1]["at_utc"]) - ts(burst[0]["at_utc"])).total_seconds())
            if burst else 0, "UNIQUE_SYMBOLS": len({x["symbol"] for x in burst}),
            "PREVIOUSLY_SENT_SETUP": sum(1 for x in burst if x.get("route_reason") == "SENT_SETUP_INVALIDATED"),
            "first_scan_utc": start, "window_invalidations_total": len(inv)}


def spread_cost(W: Window) -> dict:
    buckets = {"<=25": [], "25-50": [], "50-100": [], ">100": [], "unmeasured": []}
    for s in W.signals:
        sp = (W.snap.get(s["symbol"]) or {}).get("spread_bps")
        k = "unmeasured" if sp is None else "<=25" if sp <= 25 else "25-50" if sp <= 50 else "50-100" if sp <= 100 \
            else ">100"
        buckets[k].append(s)
    out = {}
    for k, xs in buckets.items():
        def m(f):
            v = [x[f] for x in xs if x.get(f) is not None]
            return round(statistics.mean(v), 3) if v else None
        out[k] = {"n": len(xs), "mean_ret_15m": m("ret_15m_pct"), "mean_ret_30m": m("ret_30m_pct"),
                  "mean_ret_1h": m("ret_1h_pct"), "mean_close": m("close_ret_pct"),
                  "median_half_spread_bps": statistics.median([W.snap[x["symbol"]]["spread_bps"] / 2 for x in xs])
                  if xs and k != "unmeasured" else None}
    return {"basis": "D-1 sampled NBBO spread (snapshot); paper outcomes; descriptive, no edge claim", **out}


def misses(W: Window, pol: Policy, pops: dict) -> list[dict]:
    out = []
    flag = {"signals": "MISSED_SIGNAL", "signals_80": "MISSED_80_PLUS_SIGNAL", "setups": "MISSED_SETUP",
            "movers": "MISSED_SIGNIFICANT_MOVER", "v2_symbol_events": "MISSED_V2"}
    for pop, fl in flag.items():
        for r in pops[pop]:
            st, why, p_t = pol.status(r["symbol"], r["at_utc"])
            if st != MISSED:
                continue
            x = W.snap.get(r["symbol"]) or {}
            trig = W.cross.get(r["symbol"], {})
            out.append({"FLAG": fl, "SYMBOL": r["symbol"], "DATE": W.wid, "TIME": r["at_utc"],
                        "PRODUCTION_STATE": r.get("to_state") or r.get("event_type") or pop,
                        "SCORE": r.get("score"), "PRICE": x.get("price"), "ADV20": x.get("adv20"),
                        "SPREAD_BPS": x.get("spread_bps"),
                        "PRODUCTION_OUTCOME": r.get("close_ret_pct", r.get("move_pct")),
                        "CORE_RANK": x.get("core_rank"), "WHY_NOT_CORE": x.get("reason"),
                        "EVENT_TRIGGER_AVAILABLE": bool(trig.get(3.0) or W.prom.get(r["symbol"])),
                        "EVENT_TRIGGER_TIME": trig.get(3.0),
                        "WHY_NOT_PROMOTED": ("below V1 floors" if not x.get("v1_floor_eligible") else
                                             "never >= 3% on a fresh delayed_sip trade" if not trig.get(3.0) else
                                             "promotion after window end"),
                        "SHADOW_RESULT": MISSED})
    return out


def evaluate(wid: str, since: str | None = None) -> dict:
    W = Window(wid, since)
    pops = populations(W)
    res = {"window_id": wid, "evaluated_from": W.since, "sweeps": len(W.sweeps), "scans": len(W.scans)}
    sw = [s for s in W.sweeps]
    res["event_sweep"] = {"sweeps": len(sw), "requests_per_sweep_median": statistics.median(s["requests"] for s in sw)
                          if sw else None, "EVENT_SWEEP_DURATION_MEDIAN_S": q([s["duration_s"] for s in sw], .5),
                          "EVENT_SWEEP_DURATION_P95_S": q([s["duration_s"] for s in sw], .95),
                          "symbols_checked_median": statistics.median(s["symbols_checked"] for s in sw) if sw else None,
                          "usable_median": statistics.median(s["usable"] or 0 for s in sw) if sw else None,
                          "gap_promotions": sum(s["gap_promotions_new"] or 0 for s in sw),
                          "sec8k_promotions": sum(s["sec8k_promotions_new"] or 0 for s in sw),
                          "protection_new": sum(s["protection_new"] or 0 for s in sw),
                          "errors": sum(1 for s in sw if s["errors"]),
                          "edgar_polls": len(W.edgar_polls), "edgar_poll_failures": sum(1 for p in W.edgar_polls
                                                                                        if not p["ok"])}
    snap = W.snap.values()
    res["universe"] = {"FULL_UNIVERSE": sum(1 for x in snap if x["structurally_eligible"]),
                       "EVENT_ELIGIBLE (V1 floors)": sum(1 for x in snap if x["v1_floor_eligible"]),
                       "SHADOW_CORE": sum(1 for x in snap if x["is_shadow_core"]),
                       "FORCED_ACTIVE": sum(1 for x in snap if x["is_v2_forced_active"] or x["is_operator_forced_active"]),
                       "EVENT_PROMOTED (non-core, ever)": sum(1 for s, p in W.prom.items()
                                                              if not (W.snap.get(s) or {}).get("is_shadow_core"))}
    res["policies"] = {}
    for prot in ("PROD", "POLICY"):
        for n in CORES:
            pol = Policy(W, n, prot)
            key = f"CORE_{n}|{prot}"
            r = {pop: classify(pol, rows)[0] for pop, rows in pops.items()}
            r["workload"] = workload(W, pol)
            res["policies"][key] = r
            if n == PRIMARY:
                r["watch_fate"] = watch_fate(W, pol)
                r["misses"] = misses(W, pol, pops)
                r["latency_detail"] = {pop: [d for d in classify(pol, rows)[1] if d["shadow"] in (ONE, TWO)]
                                       for pop, rows in pops.items() if pop in ("setups", "signals", "signals_80",
                                                                                 "movers")}
    res["false_positives"] = false_positives(W, pops["movers"])
    res["rollover"] = rollover(W)
    res["spread_cost"] = spread_cost(W)
    res["sec_observability"] = sec_observability(W)
    res["v2_episodes_in_session"] = W.v2_events
    return res


def checkpoint(res: dict, prot: str = "PROD") -> str:
    p = res["policies"][f"CORE_{PRIMARY}|{prot}"]
    w = p["workload"]

    def c(k):
        x = p[k]
        return f"{x['capture_pct']}% ({x['captured']}/{x['total']})"
    lat = C.Counter()
    for k in ("setups", "signals", "signals_80", "movers"):
        for s in (SAME, ONE, TWO, MISSED):
            lat[s] += p[k][s]
    so = res["sec_observability"]
    miss = [f"{m['FLAG']}:{m['SYMBOL']}" for m in p.get("misses", [])]
    serious = [m for m in p.get("misses", []) if m["FLAG"] in ("MISSED_SIGNAL", "MISSED_80_PLUS_SIGNAL", "MISSED_V2")]
    return "\n".join([
        f"DATE: {res['window_id']} (evaluated from {res['evaluated_from']}, protection {prot})",
        f"CORE_SIZE: {PRIMARY}", f"EVENT_PROMOTED: {res['universe']['EVENT_PROMOTED (non-core, ever)']}",
        f"EFFECTIVE_ACTIVE_PEAK: {w['SHADOW_INDICATOR_SYMBOLS_PEAK']} (median {w['SHADOW_INDICATOR_SYMBOLS_MEDIAN']})",
        f"SETUP_CAPTURE: {c('setups')}", f"SIGNAL_CAPTURE: {c('signals')}", f"80_PLUS_CAPTURE: {c('signals_80')}",
        f"MOVER_CAPTURE: {c('movers')}", f"V2_CAPTURE: {c('v2_symbol_events')}", f"LAB_CAPTURE: {c('lab')}",
        f"SAME_SCAN: {lat[SAME]}  ONE_SCAN_LATE: {lat[ONE]}  TWO_PLUS_LATE: {lat[TWO]}  MISSED: {lat[MISSED]}",
        f"BAR_REDUCTION: {w['BAR_REDUCTION_PERCENT']}%  INDICATOR_REDUCTION: {w['INDICATOR_WORK_REDUCTION_PERCENT']}%  "
        f"SEC_REDUCTION: {w['SEC_REDUCTION_PERCENT']}% (reconstruction/measured {w['reconstruction_vs_measured']})",
        f"EVENT_SWEEP_TIME: median {res['event_sweep']['EVENT_SWEEP_DURATION_MEDIAN_S']}s p95 "
        f"{res['event_sweep']['EVENT_SWEEP_DURATION_P95_S']}s ({res['event_sweep']['requests_per_sweep_median']} req)",
        f"WATCH_CAPTURE: {p['watch_fate']['WATCH_CAPTURE_PERCENT']}%",
        f"SEC_MAX_AGE_RAW: {so.get('max_served_age_raw')}  SEC_STALE_FALLBACKS: {so.get('stale_fallback_count')}",
        f"IMPORTANT_MISSES: {miss[:30] or 'none'}",
        f"SHADOW_STATUS: {'INVESTIGATE' if serious else 'CONTINUE'}"])


def main(argv):
    wid = argv[0]
    since = argv[argv.index("--from") + 1] if "--from" in argv else None
    res = evaluate(wid, since)
    d = OUT / "eval"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{wid}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    ms = res["policies"][f"CORE_{PRIMARY}|PROD"]["misses"] + res["policies"][f"CORE_{PRIMARY}|POLICY"]["misses"]
    if ms:
        with open(d / f"{wid}_misses.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(ms[0]))
            w.writeheader()
            w.writerows(ms)
    print(checkpoint(res, "PROD"))
    print("--- POLICY-consistent protection ---")
    print(checkpoint(res, "POLICY"))


if __name__ == "__main__":
    main(sys.argv[1:])
