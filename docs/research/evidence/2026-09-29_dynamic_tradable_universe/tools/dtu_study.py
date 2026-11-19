"""Dynamic Tradable Universe (DTU) study -- READ-ONLY replay of real TalonX windows (2026-09-25 Fri, 2026-09-28 Mon).

Nothing here writes production state: every DB is opened ``mode=ro``; outputs go to OUT_DIR only.

Model (research, not a product rule):
  STRUCTURAL   universe.py bucket (ELIGIBLE vs EXCLUDED:<reason>) -- the 5,652 base is already the ELIGIBLE bucket
  D-1 FEATURES from data available before the session: prev close, ADV20 ($ and shares) and daily coverage (market.db
               daily, which ends at the reference session), D-1 RTH 1-min coverage + minute-range proxy
               (fetch_d1_features.py), sampled SIP quoted spread (D-1 where sampled; else same-day, labelled)
  CORE(N, F)   symbols passing floors F (price / ADV20 / coverage / spread), ranked by ADV20 $ desc, top N
  EVENT TIER   triggers that do NOT need the symbol to be scanned continuously:
                 FORM4_CLUSTER  >= 2 distinct Form 4 filings for the issuer (EDGAR daily index) within 10 sessions
                 FILING_8K      8-K / 8-K/A / 6-K filed within the TTL (2/3/5 sessions)
                 GAP_SNAPSHOT   |gap| >= G at a scan (a universe-wide price sweep; feasibility to verify), TTL = session
               Filing triggers are evaluated D-1 (filed <= D-1, a daily batch) or REALTIME (filed <= D, needs a live feed).
               Event-tier symbols must still pass V1's own hard floors (price >= $1, ADV20 >= $1M): below them V1 can never
               produce a candidate, so promoting them cannot recover anything.
  OPERATOR     OPERATOR_EXCLUDED > OPERATOR_ADDED (V2 execution scope + V2 episode symbols) > CORE > EVENT_PROMOTED.
Capture of an opportunity at time t: the symbol is OPERATOR_ADDED or CORE, or EVENT_PROMOTED before t
("recovered on time") / at the same scan ("recovered one scan late", 5 min), else MISSED.
MEASURED = counted from stored live data. ESTIMATED = derived through a stated model (scan time, SEC requests).
usage: python dtu_study.py OUT_DIR"""
from __future__ import annotations

import bisect
import collections as C
import csv
import gzip
import json
import sqlite3
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO))
from talonx_opportunity.phases import trading_window  # noqa: E402

LIVE = REPO / "results" / "opportunity"
DTU = REPO / "results" / "dtu_2026-09-29"
UTC = timezone.utc
WINDOWS = ("2026-09-25", "2026-09-28")
D1_BARS = {"2026-09-25": "2026-09-24", "2026-09-28": "2026-09-25"}
SPREAD_DAY = {"2026-09-25": ("2026-09-25", "SAME_DAY_PROXY"), "2026-09-28": ("2026-09-25", "D-1")}
CORE_SIZES = (500, 750, 1000, 1200, 1500, 2000, 3000, None)          # None = full baseline
V1_PRICE, V1_ADV = 1.0, 1_000_000.0
PRICE_FLOORS, ADV_FLOORS = (1, 2, 3, 5), (5e5, 1e6, 2e6, 5e6, 1e7)
COVERAGE_FLOORS, SPREAD_CAPS = (0.8, 0.9, 0.95, 0.98), (None, 200, 100, 50)
ACTIVE = ("WATCH", "BULLISH_SETUP", "BEARISH_SETUP")
SETUP_STATES = ("BULLISH_SETUP", "BEARISH_SETUP")


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def gz(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


# ============================================================================================================ inputs
def load_window(wid: str, market, opp) -> dict:
    uni = json.loads(market.execute("SELECT members_json FROM universe WHERE window_id=?", (wid,)).fetchone()[0])
    daily = {r["symbol"]: json.loads(r["bars_json"]) for r in
             market.execute("SELECT symbol, bars_json FROM daily WHERE window_id=?", (wid,))}
    aggs = {r["symbol"]: json.loads(r["agg_json"]) for r in
            market.execute("SELECT symbol, agg_json FROM aggregates WHERE window_id=?", (wid,))}
    w = trading_window(date.fromisoformat(wid))
    return {"wid": wid, "w": w, "members": uni, "daily": daily, "aggs": aggs}


def d1_features(W: dict, rth: dict, spreads: dict, spread_basis: str) -> dict[str, dict]:
    ref = W["w"].reference_session.isoformat()
    sessions = sorted({b["t"][:10] for bars in W["daily"].values() for b in bars if b["t"][:10] <= ref})[-20:]
    out = {}
    for m in W["members"]:
        s = m["symbol"]
        f = {"symbol": s, "exchange": m["exchange"], "name": m["name"], "cik": m.get("cik"),
             "structural": "ELIGIBLE" if m["status"] == "ELIGIBLE" else m["reason"]}
        bars = sorted((b for b in W["daily"].get(s, []) if b["t"][:10] <= ref), key=lambda b: b["t"])
        last20 = bars[-20:]
        if last20:
            f["price"] = float(bars[-1]["c"])
            f["adv20_usd"] = sum(float(b["v"]) * float(b["c"]) for b in last20) / len(last20)
            f["adv20_sh"] = sum(float(b["v"]) for b in last20) / len(last20)
            f["daily_coverage"] = round(len({b["t"][:10] for b in last20} & set(sessions)) / max(1, len(sessions)), 3)
        r = rth.get(s) or {}
        f["rth_coverage_d1"] = r.get("rth_coverage")
        f["range_bps_d1"] = r.get("range_bps_med")
        sp = spreads.get(s)
        f["spread_bps"] = sp.get("spread_bps_med") if sp else None
        f["spread_basis"] = spread_basis if sp else "UNMEASURED"
        f["spread_to_price_cost_bps"] = f["spread_bps"] / 2 if f["spread_bps"] is not None else None   # half-spread
        out[s] = f
    return out


def passes(f: dict, price=V1_PRICE, adv=V1_ADV, cov=None, spread=None) -> bool:
    if f.get("structural") != "ELIGIBLE" or f.get("price") is None:
        return False
    if f["price"] < price or f.get("adv20_usd", 0) < adv:
        return False
    if cov is not None and (f.get("rth_coverage_d1") or 0) < cov:
        return False
    if spread is not None and (f.get("spread_bps") is None or f["spread_bps"] > spread):
        return False
    return True


def core(feats: dict, n, **floors) -> set[str]:
    ok = sorted((f for f in feats.values() if passes(f, **floors)), key=lambda f: (-f.get("adv20_usd", 0), f["symbol"]))
    return {f["symbol"] for f in (ok if n is None else ok[:n])}


# ============================================================================================================ events
def sessions_between(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        try:
            if d.weekday() < 5 and trading_window(d) is not None:
                out.append(d)
        except ValueError:                                  # not an XNYS session (holiday)
            pass
        d += timedelta(days=1)
    return out


def filing_events(edgar: dict, cik_to_sym: dict) -> dict[str, list[tuple[str, str, str]]]:
    ev = C.defaultdict(list)
    for r in edgar["rows"]:
        s = cik_to_sym.get(r["cik"])
        if s:
            kind = "FORM4" if r["form"] in ("4", "4/A") else "FILING_8K"
            ev[s].append((r["date"], kind, r["accession"]))
    return ev


def promoted_by_filings(W: dict, fev: dict, *, ttl_8k: int, form4_window: int = 10, form4_min: int = 2,
                        realtime: bool = False) -> dict[str, str]:
    """symbol -> trigger, for filings whose TTL covers session D. D-1 batch: filed <= D-1; REALTIME: filed <= D."""
    D = W["w"].session
    back = sessions_between(D - timedelta(days=30), D)
    cutoff = D if realtime else back[-2]
    idx = {d.isoformat(): i for i, d in enumerate(back)}
    iD = idx[D.isoformat()]
    out = {}
    for s, evs in fev.items():
        f4 = sorted({(d, a) for d, k, a in evs if k == "FORM4" and d <= cutoff.isoformat() and d in idx
                     and iD - idx[d] <= form4_window})
        if len({a for _, a in f4}) >= form4_min:
            out[s] = "FORM4_CLUSTER"
            continue
        if any(k == "FILING_8K" and d <= cutoff.isoformat() and d in idx and iD - idx[d] < ttl_8k for d, k, _ in evs):
            out[s] = "FILING_8K"
    return out


# ============================================================================================================ replay data
def replay_items(wid: str, opp, prom, notif, lab) -> dict:
    """Opportunity populations of one window (all MEASURED from live stores)."""
    evs = [dict(r) for r in opp.execute("SELECT seq, event_id, candidate_id, symbol, at_utc, event_type, to_state, "
                                        "classification, score, gap_pct, features_json, catalyst FROM candidate_events "
                                        "WHERE window_id=? ORDER BY seq", (wid,))]
    setups = {}
    for e in evs:
        if e["event_type"] in ("NEW", "UPGRADE") and e["to_state"] in SETUP_STATES and e["candidate_id"] not in setups:
            setups[e["candidate_id"]] = e
    signals = [dict(r) for r in prom.execute("SELECT p.*, o.status AS outcome_status, o.ret_30m_pct, o.close_ret_pct, "
                                             "o.mfe_pct, o.mae_pct FROM promotions p LEFT JOIN paper_outcomes o "
                                             "USING(promotion_id) WHERE p.window_id=? AND p.state='PROMOTED_SIGNAL'",
                                             (wid,))]
    sent = {r["event_id"] for r in lab.execute("SELECT event_id FROM ops_notification_outbox WHERE state='SENT'")}
    labev = [dict(r) for r in notif.execute("SELECT event_id, symbol, event_type, classification, decided_utc "
                                            "FROM decisions WHERE window_id=? AND outbox_event_id IS NOT NULL", (wid,))
             if r["event_id"] in sent]
    at = {e["event_id"]: e["at_utc"] for e in evs}
    for x in labev:
        x["at_utc"] = at.get(x["event_id"], x["decided_utc"])
    news = [e for e in evs if e["event_type"] == "NEW"]              # every new candidate identity (incl. WATCH)
    return {"events": evs, "setups": list(setups.values()), "signals": signals, "lab": labev, "candidates": news}


def first_gap_times(wid: str, opp) -> dict[str, list[tuple[str, float]]]:
    """symbol -> [(decision_utc, |gap|)] for every scan observation with |gap| >= 2 % that PASSED V1 hard gates
    (near_misses SCORED rows + candidate events). Used for the GAP_SNAPSHOT trigger time."""
    out = C.defaultdict(list)
    for r in opp.execute("SELECT symbol, decision_utc, gap_pct FROM near_misses WHERE window_id=? AND cls='SCORED'",
                         (wid,)):
        out[r[0]].append((r[1], abs(r[2] or 0)))
    for r in opp.execute("SELECT symbol, at_utc, gap_pct FROM candidate_events WHERE window_id=? AND gap_pct IS NOT NULL",
                         (wid,)):
        out[r[0]].append((r[1], abs(r[2] or 0)))
    for s in out:
        out[s].sort()
    return out


def gap_trigger_time(gaps: list[tuple[str, float]], g: float) -> str | None:
    for t, a in gaps:
        if a >= g:
            return t
    return None


# ============================================================================================================ SEC / scan load
def sec_load(wid: str, opp) -> dict:
    """Per scan: alert-worthy symbols (active identities not seen as a non-worthy observation) + scored near misses.
    Calibrated against the measured per-scan funnel (ALERT_WORTHY, sec lookups)."""
    scans = [dict(r) for r in opp.execute("SELECT decision_utc, duration_s, funnel_json FROM scans WHERE window_id=? "
                                          "AND state='SCANNED' ORDER BY decision_utc", (wid,))]
    allev = [dict(r) for r in opp.execute("SELECT candidate_id, symbol, at_utc, to_state FROM candidate_events "
                                          "ORDER BY seq")]
    timeline = C.defaultdict(list)
    for e in allev:
        timeline[e["candidate_id"]].append((e["at_utc"], e["to_state"], e["symbol"]))
    nm = C.defaultdict(lambda: C.defaultdict(set))
    for r in opp.execute("SELECT decision_utc, symbol, cls FROM near_misses WHERE window_id=?", (wid,)):
        nm[r[0]]["ALL"].add(r[1])
        if r[2] == "SCORED":
            nm[r[0]]["SCORED"].add(r[1])
    per_scan = []
    for sc in scans:
        t = sc["decision_utc"]
        active = set()
        for cid, tl in timeline.items():
            state, sym = None, None
            for at, st, sy in tl:
                if at <= t:
                    state, sym = st, sy
                else:
                    break
            if state in ACTIVE:
                active.add(sym)
        aw = active - nm[t]["ALL"]
        f = json.loads(sc["funnel_json"])
        per_scan.append({"t": t, "duration_s": sc["duration_s"], "aw": aw, "scored_nm": nm[t]["SCORED"],
                         "measured_aw": f.get("ALERT_WORTHY"), "measured_lookups": (f.get("sec_cache") or {}).get("lookups"),
                         "measured_requests": (f.get("sec_cache") or {}).get("sec_requests"),
                         "eligible": f.get("ELIGIBLE")})
    return {"scans": per_scan}


# ============================================================================================================ evaluation
def status_at(sym, t, *, core_set, added, excluded, prom_filing, gap_times, gap_g, protected=None):
    if sym in excluded:
        return "OPERATOR_EXCLUDED", None
    if sym in added:
        return "OPERATOR_ADDED", None
    if sym in core_set:
        return "CORE", None
    if protected is not None and any(a < t and (b is None or b >= t) for a, b in protected.get(sym, ())):
        return "PROTECTED_ACTIVE_IDENTITY", None             # an identity of this symbol is open (created before t)
    if sym in prom_filing:
        return "EVENT_RECOVERED", prom_filing[sym]
    if gap_g is not None:
        tt = gap_trigger_time(gap_times.get(sym, []), gap_g)
        if tt is not None and tt <= t:
            return ("EVENT_RECOVERED" if tt < t else "EVENT_RECOVERED_1_SCAN_LATE"), f"GAP_SNAPSHOT>={gap_g}%"
    return "MISSED", None


def evaluate(W, feats, items, gap_times, load, *, n, floors, event, added, excluded, fev, carried=frozenset(),
             captured_new=None):
    captured_new = set() if captured_new is None else captured_new
    core_set = core(feats, n, **floors)
    prom_filing = {}
    if event.get("filings"):
        prom_filing = promoted_by_filings(W, fev, ttl_8k=event.get("ttl_8k", 3), realtime=event.get("realtime", False))
        prom_filing = {s: k for s, k in prom_filing.items() if s not in core_set and passes(feats.get(s, {}))}
    g = event.get("gap")
    kw = dict(core_set=core_set, added=added, excluded=excluded, prom_filing=prom_filing, gap_times=gap_times, gap_g=g,
              protected=None)
    if event.get("protect_active"):
        # Protection is NOT circular: an identity protects its symbol only if its own creation (NEW) was captured
        # under this same policy -- in this window (chronological) or in the previous window's replay (``carried``).
        prot = C.defaultdict(list)
        for cid in carried:
            if cid in W["spans"]:
                sym, a, b = W["spans"][cid]
                prot[sym].append((a, b))
        kw["protected"] = prot
        for e in sorted(items["candidates"], key=lambda e: (e["at_utc"], e["seq"])):
            st, _ = status_at(e["symbol"], e["at_utc"], **kw)
            if st not in ("MISSED", "OPERATOR_EXCLUDED"):
                captured_new.add(e["candidate_id"])
                sym, a, b = W["spans"][e["candidate_id"]]
                prot[sym].append((a, b))

    def cap(rows, symk="symbol", tk="at_utc"):
        st = [status_at(r[symk], r[tk], **kw) for r in rows]
        ok = sum(1 for s, _ in st if s not in ("MISSED", "OPERATOR_EXCLUDED"))
        # protection only from identities whose creation was itself captured under this policy (see above)
        return ok, len(rows), st
    setups = items["setups"]
    sig = items["signals"]
    for x in sig:
        x["at_utc"] = x["event_utc"]
    hi_setups = [s for s in setups if (s["score"] or 0) >= 80]
    hi_sig = [s for s in sig if (s["score"] or 0) >= 80]
    res = {}
    for name, rows in (("setups", setups), ("signals", sig), ("candidates_all", [e for e in items["candidates"]]),
                       ("high_score_setups", hi_setups),
                       ("high_score_signals", hi_sig), ("lab_events", items["lab"])):
        ok, tot, st = cap(rows)
        res[name] = {"captured": ok, "total": tot, "pct": round(100 * ok / tot, 1) if tot else None,
                     "late_1_scan": sum(1 for s, _ in st if s == "EVENT_RECOVERED_1_SCAN_LATE"),
                     "event_recovered": sum(1 for s, _ in st if s.startswith("EVENT_RECOVERED"))}
        res[name]["_status"] = st
    # movers: V1-floor symbols with |window-to-date move| >= 10 % (measured from final aggregates vs prev close)
    movers = []
    for s, f in feats.items():
        a = W["aggs"].get(s)
        if not passes(f) or not a or not a.get("last_c") or not f.get("price"):
            continue
        mv = (a["last_c"] / f["price"] - 1) * 100
        if abs(mv) >= 10:
            tt = gap_trigger_time(gap_times.get(s, []), 10.0) or a.get("last_t")   # when it became a >=10 % mover
            movers.append({"symbol": s, "at_utc": tt if tt and "T" in tt else W["w"].close_utc.isoformat(),
                           "move_pct": round(mv, 1), "engine_emitted": s in W["event_symbols"]})
    ok, tot, st = cap(movers)
    lost_output = sum(1 for m, (st_, _) in zip(movers, st) if st_ in ("MISSED", "OPERATOR_EXCLUDED") and m["engine_emitted"])
    res["movers"] = {"captured": ok, "total": tot, "pct": round(100 * ok / tot, 1) if tot else None,
                     "missed_with_engine_output": lost_output,
                     "missed_without_engine_output": (tot - ok) - lost_output,
                     "event_recovered": sum(1 for s, _ in st if s.startswith("EVENT_RECOVERED")), "_status": st,
                     "_rows": movers}
    # effective active set and workload (per scan: core + added + filing-promoted + gap-promoted so far)
    base_active = core_set | (added - excluded) | set(prom_filing)
    aw_sub = scored_sub = aw_full = scored_full = 0
    eff_sizes = []
    for sc in load["scans"]:
        gp = set()
        if g is not None:
            gp = {s for s, gt in gap_times.items() if (x := gap_trigger_time(gt, g)) is not None and x <= sc["t"]
                  and passes(feats.get(s, {}))}
        act = base_active | gp
        eff_sizes.append(len(act))
        aw_sub += len(sc["aw"] & act)
        scored_sub += len(sc["scored_nm"] & act)
        aw_full += len(sc["aw"])
        scored_full += len(sc["scored_nm"])
    lookups_full = aw_full + scored_full
    lookups_sub = aw_sub + scored_sub
    bars_full = sum(a.get("bars", 0) for a in W["aggs"].values())
    bars_sub = sum(W["aggs"].get(s, {}).get("bars", 0) for s in base_active)
    eligible = sum(1 for f in feats.values() if f["structural"] == "ELIGIBLE")
    res["size"] = {"core": len(core_set), "operator_added": len(added), "filing_promoted": len(prom_filing),
                   "effective_active_max": max(eff_sizes) if eff_sizes else len(base_active),
                   "effective_active_mean": round(statistics.mean(eff_sizes), 1) if eff_sizes else len(base_active),
                   "eligible_base": eligible}
    res["load"] = {"sec_lookups_reconstructed_full": lookups_full, "sec_lookups_subset": lookups_sub,
                   "SEC_LOAD_REDUCTION_PCT": round(100 * (1 - lookups_sub / lookups_full), 1) if lookups_full else None,
                   "BAR_FETCH_REDUCTION_PCT (1-min bars, measured counts; excludes gap-promoted)":
                       round(100 * (1 - bars_sub / bars_full), 1) if bars_full else None,
                   "INDICATOR_WORK_REDUCTION_PCT (symbols evaluated per scan)":
                       round(100 * (1 - res["size"]["effective_active_mean"] / eligible), 1)}
    return res, core_set, prom_filing


def scan_model(load: dict) -> dict:
    """ESTIMATED scan time: duration = a*symbols_fraction + b*sec_lookups, least squares on the window's measured scans
    (symbols fraction is 1.0 in every live scan, so a is the intercept)."""
    xs = [(sc["measured_lookups"] or (len(sc["aw"]) + len(sc["scored_nm"])), sc["duration_s"]) for sc in load["scans"]
          if sc["duration_s"] is not None]
    n = len(xs)
    mx, my = sum(x for x, _ in xs) / n, sum(y for _, y in xs) / n
    b = sum((x - mx) * (y - my) for x, y in xs) / max(1e-9, sum((x - mx) ** 2 for x, _ in xs))
    a = my - b * mx
    ys = sorted(y for _, y in xs)
    return {"a_s": round(a, 2), "b_s_per_lookup": round(b, 4), "measured_p90_s": ys[int(0.9 * (n - 1))], "n": n,
            "measured_max_s": ys[-1]}


# ============================================================================================================ main
def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    market, opp, prom = ro(LIVE / "market.db"), ro(LIVE / "opportunity.db"), ro(LIVE / "promotion.db")
    notif, lab = ro(LIVE / "notification.db"), ro(LIVE / "opportunity_research_notifications.db")
    edgar = json.loads((DTU / "edgar_index.json").read_text(encoding="utf-8"))
    oc = ro(REPO / "operator_control.db")
    excluded = set()        # DRY_RUN: recorded exclusions are PENDING and never applied (reported, not used)
    pending = [dict(r) for r in oc.execute("SELECT symbol, status, activation FROM symbol_exclusions")]
    from talonx_premarket import __main__ as M
    v2_scope = set(M._v2_scope(None))
    v2_eps = {r[0] for r in ro(REPO / "v2_release_rc1.db").execute("SELECT DISTINCT symbol FROM processed_episodes")}
    added = v2_scope | v2_eps
    report = {"inputs": {"windows": WINDOWS, "operator_exclusions_recorded": pending,
                         "operator_exclusions_applied": sorted(excluded), "operator_added (V2 scope + episodes)": len(added),
                         "edgar_days": edgar["days"]}, "windows": {}}
    all_rows = []
    carried_by_key: dict[str, set] = {}                  # policy key (floors|policy|n) -> identities captured so far
    for wid in WINDOWS:
        W = load_window(wid, market, opp)
        rth = gz(DTU / f"rth_bars_{D1_BARS[wid]}.json.gz")
        sp_day, sp_basis = SPREAD_DAY[wid]
        spf = DTU / f"spreads_{sp_day}.json.gz"
        feats = d1_features(W, rth, gz(spf) if spf.exists() else {}, sp_basis)
        cik_to_sym = {m["cik"]: m["symbol"] for m in W["members"] if m.get("cik") and m["status"] == "ELIGIBLE"}
        fev = filing_events(edgar, cik_to_sym)
        items = replay_items(wid, opp, prom, notif, lab)
        spans = {}                                       # candidate_id -> [symbol, created, closed]
        for r in opp.execute("SELECT candidate_id, symbol, at_utc, event_type FROM candidate_events ORDER BY seq"):
            if r[3] == "NEW":
                spans[r[0]] = [r[1], r[2], None]
            elif r[3] in ("INVALIDATED", "EXPIRED") and r[0] in spans:
                spans[r[0]][2] = r[2]
        W["spans"] = spans
        W["event_symbols"] = {e["symbol"] for e in items["events"]}
        gaps = first_gap_times(wid, opp)
        load = sec_load(wid, opp)
        model = scan_model(load)
        base = [f for f in feats.values() if f["structural"] == "ELIGIBLE"]
        v1 = [f for f in base if passes(f)]
        wrep = {"structural": dict(C.Counter(f["structural"] for f in feats.values()).most_common()),
                "eligible_base": len(base), "passes_v1_floors (EVENT_ELIGIBLE pool)": len(v1),
                "feature_coverage": {k: sum(1 for f in base if f.get(k) is not None) for k in
                                     ("price", "adv20_usd", "rth_coverage_d1", "spread_bps", "range_bps_d1")},
                "spread_basis": sp_basis, "scan_model_ESTIMATED": model,
                "sec_reconstruction_check": {
                    "reconstructed_lookups_per_scan_mean": round(statistics.mean(len(s["aw"]) + len(s["scored_nm"])
                                                                                 for s in load["scans"]), 1),
                    "measured_lookups_per_scan_mean": round(statistics.mean(s["measured_lookups"] for s in load["scans"]
                                                                            if s["measured_lookups"] is not None), 1)
                    if any(s["measured_lookups"] is not None for s in load["scans"]) else None,
                    "reconstructed_aw_mean": round(statistics.mean(len(s["aw"]) for s in load["scans"]), 1),
                    "measured_aw_mean": round(statistics.mean(s["measured_aw"] for s in load["scans"]), 1)},
                "populations": {"setups": len(items["setups"]), "signals": len(items["signals"]),
                                "lab_events": len(items["lab"])}}
        # ---- tradability grid (counts only; no winner chosen)
        grid = []
        for p in PRICE_FLOORS:
            for a in ADV_FLOORS:
                for cv in (None,) + COVERAGE_FLOORS:
                    for spc in SPREAD_CAPS:
                        grid.append({"price": p, "adv": a, "coverage": cv, "spread_cap_bps": spc,
                                     "eligible": sum(1 for f in base if passes(f, price=p, adv=a, cov=cv, spread=spc))})
        wrep["tradability_grid"] = grid
        # ---- TTL study: extra active symbols per trigger policy (beyond each core)
        ttl = {}
        for rt in (False, True):
            for t8 in (2, 3, 5):
                pr = promoted_by_filings(W, fev, ttl_8k=t8, realtime=rt)
                pr = {s: k for s, k in pr.items() if passes(feats.get(s, {}))}
                ttl[f"{'REALTIME' if rt else 'D-1'}_8K_TTL{t8}"] = {"promoted_total": len(pr),
                                                                   "by_trigger": dict(C.Counter(pr.values()))}
        for g in (3, 5, 10):
            ttl[f"GAP_SNAPSHOT_{g}pct_session"] = {"promoted_total": sum(
                1 for s, gt in gaps.items() if gap_trigger_time(gt, g) and passes(feats.get(s, {})))}
        wrep["event_ttl_policies"] = ttl
        # ---- Pareto over core sizes x event policies (floors = V1 floors; grid variants below)
        policies = {"E0_CORE_ONLY": {}, "E1_FILINGS_D1": {"filings": True, "ttl_8k": 3},
                    "E2_FILINGS_REALTIME": {"filings": True, "ttl_8k": 3, "realtime": True},
                    "E3_FILINGS_RT+GAP5": {"filings": True, "ttl_8k": 3, "realtime": True, "gap": 5.0},
                    "E4_FILINGS_RT+GAP3": {"filings": True, "ttl_8k": 3, "realtime": True, "gap": 3.0},
                    "E5_E4+PROTECT_ACTIVE": {"filings": True, "ttl_8k": 3, "realtime": True, "gap": 3.0,
                                             "protect_active": True},
                    "E6_FILINGS_D1+GAP3+PROTECT": {"filings": True, "ttl_8k": 3, "gap": 3.0, "protect_active": True},
                    "E7_GAP3+PROTECT_ONLY": {"gap": 3.0, "protect_active": True}}
        floor_sets = {"V1_FLOORS": {}, "P3_ADV2M": {"price": 3, "adv": 2e6}, "P5_ADV5M_COV90": {"price": 5, "adv": 5e6,
                                                                                           "cov": 0.9}}
        par = {}
        for fname, fl in floor_sets.items():
            for pname, ev in policies.items():
                for n in CORE_SIZES:
                    key = f"{fname}|{pname}|{'FULL' if n is None else n}"
                    cap_new = set()
                    r, core_set, prf = evaluate(W, feats, items, gaps, load, n=n, floors=fl, event=ev, added=added,
                                                excluded=excluded, fev=fev, carried=carried_by_key.get(key, set()),
                                                captured_new=cap_new)
                    carried_by_key[key] = carried_by_key.get(key, set()) | cap_new
                    ns = max(1, len(load["scans"]))
                    lk_sub = r["load"]["sec_lookups_subset"] / ns
                    lk_full = r["load"]["sec_lookups_reconstructed_full"] / ns
                    frac = r["size"]["effective_active_mean"] / r["size"]["eligible_base"]
                    pred_full = model["a_s"] + model["b_s_per_lookup"] * lk_full
                    pred_sub = model["a_s"] * frac + model["b_s_per_lookup"] * lk_sub
                    r["load"]["ESTIMATED_SCAN_P90_S"] = round(model["measured_p90_s"] * pred_sub / max(1e-9, pred_full), 1)
                    r["load"]["sec_lookups_per_scan_subset"] = round(lk_sub, 1)
                    par[key] = r
                    if fname == "V1_FLOORS" and pname in ("E0_CORE_ONLY", "E3_FILINGS_RT+GAP5", "E5_E4+PROTECT_ACTIVE"):
                        for pop in ("signals", "setups", "lab_events", "movers"):
                            rows = {"signals": items["signals"], "setups": items["setups"], "lab_events": items["lab"],
                                    "movers": r["movers"]["_rows"]}[pop]
                            for row, (st, why) in zip(rows, r[pop]["_status"]):
                                f = feats.get(row["symbol"], {})
                                all_rows.append({"window": wid, "floors": fname, "policy": pname,
                                                 "core_n": "FULL" if n is None else n, "population": pop,
                                                 "symbol": row["symbol"], "at_utc": row.get("at_utc"),
                                                 "score": round(row.get("score") or 0, 1), "status": st, "trigger": why,
                                                 "detail": row.get("event_type") or row.get("move_pct"),
                                                 "engine_emitted": row.get("engine_emitted"),
                                                 "price": f.get("price"), "adv20_usd": round(f.get("adv20_usd") or 0),
                                                 "adv_rank": None, "rth_coverage_d1": f.get("rth_coverage_d1"),
                                                 "spread_bps": f.get("spread_bps"),
                                                 "ret_30m_pct": row.get("ret_30m_pct"),
                                                 "close_ret_pct": row.get("close_ret_pct"),
                                                 "outcome": row.get("outcome_status")})
        wrep["pareto"] = {k: {kk: ({x: y for x, y in vv.items() if not x.startswith("_")} if isinstance(vv, dict) else vv)
                              for kk, vv in v.items()} for k, v in par.items()}
        # ADV rank (within V1 floors) for miss reporting
        rank = {f["symbol"]: i + 1 for i, f in enumerate(sorted(v1, key=lambda f: (-f["adv20_usd"], f["symbol"])))}
        for row in all_rows:
            if row["window"] == wid:
                row["adv_rank"] = rank.get(row["symbol"])
        wrep["movers_list"] = par["V1_FLOORS|E0_CORE_ONLY|FULL"]["movers"]["_rows"]
        report["windows"][wid] = wrep
        # per-symbol snapshot prototype (the proposed D-1 artifact; research only)
        with open(out / f"universe_snapshot_{wid}.csv", "w", newline="", encoding="utf-8") as fh:
            cols = ["symbol", "exchange", "structural", "price", "adv20_usd", "adv20_sh", "daily_coverage",
                    "rth_coverage_d1", "range_bps_d1", "spread_bps", "spread_basis", "v1_floor_eligible", "adv_rank"]
            wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            wr.writeheader()
            for s in sorted(feats):
                f = dict(feats[s])
                f["v1_floor_eligible"] = passes(f)
                f["adv_rank"] = rank.get(s)
                wr.writerow(f)
    with open(out / "capture_rows.csv", "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(all_rows[0]))
        wr.writeheader()
        wr.writerows(all_rows)
    (out / "dtu_study.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print("ok", out)


if __name__ == "__main__":
    main(sys.argv[1])
