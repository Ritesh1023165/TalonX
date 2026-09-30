"""
RS_ALPHA_V1 Phase A runner (READ-ONLY on production stores). Wires stores, SIP bars, quotes and EDGAR SIC metadata
into the FROZEN definitions of talonx_paperperf/rs_study.py (pre-registered at 296e54d). Nothing here defines a
threshold, benchmark, lookback, gate or selection rule.

Outputs: results/rs_study/  (bars / SIC / quote caches, population_<wid>.json, phase_a.json)
usage: python -m talonx_paperperf.rs_phase_a population WID [WID ...]   # no outcome, no RS
       python -m talonx_paperperf.rs_phase_a fetch WID [WID ...]        # bars + SIC caches
       python -m talonx_paperperf.rs_phase_a run WID [WID ...]          # Phase A evaluation
"""
from __future__ import annotations

import collections as C
import csv
import gzip
import json
import os
import sqlite3
import statistics
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from talonx_paperperf import rs_study as R  # noqa: E402

LIVE = REPO / "results" / "opportunity"
OUT = REPO / "results" / "rs_study"
STUDY = REPO / "docs" / "research" / "evidence" / "2026-09-29_dynamic_tradable_universe"
SHADOW = REPO / "results" / "dtu_shadow" / "shadow.db"
EDGAR_INDEX = REPO / "results" / "dtu_2026-09-29" / "edgar_index.json"
UTC = timezone.utc


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def ts(s) -> datetime:
    return s if isinstance(s, datetime) else datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def window(wid: str):
    from talonx_opportunity.phases import trading_window
    return trading_window(date.fromisoformat(wid))


# ============================================================================================================ DTU state
def sessions_back(D: date, k: int) -> list[str]:
    from talonx_opportunity.phases import trading_window
    out, d = [], D
    while len(out) < k:
        try:
            if d.weekday() < 5 and trading_window(d) is not None:
                out.append(d.isoformat())
        except ValueError:
            pass
        d -= timedelta(days=1)
    return out                                      # [D, D-1, D-2, ...]


def d1_8k_carry_in(wid: str, cik_to_sym: dict[str, str]) -> dict[str, list]:
    """D-1 batch: 8-K* filed on an EARLIER session within the 3-session TTL (DTU_V1 forms: startswith '8-K')."""
    back = sessions_back(date.fromisoformat(wid), R.POPULATION["dtu_sec_8k_ttl_sessions"])[1:]
    ed = json.loads(EDGAR_INDEX.read_text(encoding="utf-8"))
    out = C.defaultdict(list)
    for r in ed["rows"]:
        if r["form"].startswith("8-K") and r["date"] in back and r["cik"] in cik_to_sym:
            out[cik_to_sym[r["cik"]]].append((f"{wid}T00:00:00+00:00", None, "SEC_8K_D1_CARRY_IN"))
    return out, sorted(ed["days"])


def dtu_inputs(wid: str) -> dict:
    """Core (D-1 frozen), promotions {symbol: [(start, expires, reason)]}, adv20 shares, source + coverage notes."""
    m = ro(LIVE / "market.db")
    uni = json.loads(m.execute("SELECT members_json FROM universe WHERE window_id=?", (wid,)).fetchone()[0])
    cik_to_sym = {x["cik"]: x["symbol"] for x in uni if x.get("cik") and x["status"] == "ELIGIBLE"}
    sym_cik = {x["symbol"]: x.get("cik") for x in uni}
    prom = C.defaultdict(list)
    carry, edgar_days = d1_8k_carry_in(wid, cik_to_sym)
    for s, v in carry.items():
        prom[s].extend(v)
    notes = {"edgar_index_days_available": edgar_days[-5:]}
    if wid == "2026-09-28":
        rows = []
        with open(STUDY / "universe_snapshot_2026-09-28.csv", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows.append({"symbol": r["symbol"], "v1_floor_eligible": r["v1_floor_eligible"] in ("1", "True", "true"),
                             "adv20_usd": float(r["adv20_usd"]) if r["adv20_usd"] else None,
                             "adv20_sh": float(r["adv20_sh"]) if r["adv20_sh"] else None})
        core = R.core_membership(rows)
        advsh = {r["symbol"]: r["adv20_sh"] for r in rows}
        o = ro(LIVE / "opportunity.db")
        gaps = C.defaultdict(list)
        for q in ("SELECT symbol, decision_utc, gap_pct FROM near_misses WHERE window_id=? AND cls='SCORED'",
                  "SELECT symbol, at_utc, gap_pct FROM candidate_events WHERE window_id=? AND gap_pct IS NOT NULL"):
            for s, t, g in o.execute(q, (wid,)):
                if g is not None and abs(g) >= R.POPULATION["dtu_gap_trigger_abs_pct"]:
                    gaps[s].append(t)
        for s, ts_ in gaps.items():
            prom[s].append((min(ts_), None, "GAP_TRIGGER_REPLAY"))
        notes.update({"core_source": "universe_snapshot_2026-09-28.csv (D-1 2026-09-25)",
                      "gap_source": "scan-observation replay (DTU study)",
                      "sec_8k_same_day": "NOT_RECONSTRUCTABLE (coverage gap)"})
    else:
        sh = ro(SHADOW)
        snap = [dict(r) for r in sh.execute("SELECT symbol, is_shadow_core, adv20, adv20_sh, core_rank, "
                                            "v1_floor_eligible FROM snapshot WHERE window_id=?", (wid,))]
        if not snap:
            raise SystemExit(f"no shadow snapshot for {wid}")
        core = {r["symbol"] for r in snap if r["is_shadow_core"]}
        advsh = {r["symbol"]: r["adv20_sh"] for r in snap}
        for s, why, t in sh.execute("SELECT symbol, reason, first_at_utc FROM promotions WHERE window_id=? AND reason "
                                    "IN ('GAP_TRIGGER','SEC_8K')", (wid,)):
            prom[s].append((t, None, why))
        notes.update({"core_source": "shadow snapshot is_shadow_core (D-1 2026-09-28)",
                      "gap_source": "shadow GAP_TRIGGER promotions", "sec_8k_same_day": "shadow SEC_8K promotions",
                      "shadow_first_sweep": sh.execute("SELECT MIN(at_utc) FROM sweeps WHERE window_id=?",
                                                       (wid,)).fetchone()[0]})
    return {"core": core, "prom": prom, "advsh": advsh, "sym_cik": sym_cik, "notes": notes}


# ============================================================================================================ population
def population(wid: str) -> dict:
    """Qualifying-candidate events (no RS, no outcome): DTU state at t0 + RTH timing. RS computability is applied in
    `run` (the frozen rule lets an event fall through to the symbol's next qualifying event)."""
    w = window(wid)
    D = dtu_inputs(wid)
    o = ro(LIVE / "opportunity.db")
    P = R.POPULATION
    q = (f"SELECT seq, event_id, candidate_id, symbol, at_utc, data_as_of_utc, event_type, to_state, score, gap_pct, "
         f"catalyst FROM candidate_events WHERE window_id=? AND event_type IN ({','.join('?' * len(P['event_types']))}) "
         f"AND to_state IN ({','.join('?' * len(P['to_states']))}) ORDER BY seq")
    rows = [dict(r) for r in o.execute(q, (wid, *P["event_types"], *P["to_states"]))]
    cnt = C.Counter()
    out = []
    for e in rows:
        t0, asof = ts(e["at_utc"]), ts(e["data_as_of_utc"])
        entry_min = t0.replace(second=0, microsecond=0) + (timedelta(minutes=1) if t0.second or t0.microsecond
                                                           else timedelta(0))
        if asof - timedelta(minutes=R.PRIMARY_LOOKBACK_MIN) < w.open_utc or entry_min + timedelta(minutes=30) > w.close_utc:
            cnt["OUTSIDE_RTH_WINDOW"] += 1
            continue
        st = R.dtu_state_at(e["symbol"], e["at_utc"], D["core"], D["prom"])
        if st == "OUT_OF_DTU":
            cnt["OUT_OF_DTU"] += 1
            continue
        cnt["IN_DTU"] += 1
        e.update({"session": wid, "t0": e["at_utc"], "dtu_state": st})
        out.append(e)
    res = {"window_id": wid, "events_considered": len(rows), "counts": dict(cnt), "dtu_notes": D["notes"],
           "core_n": len(D["core"]), "qualifying_events": out}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"population_{wid}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res


# ============================================================================================================ data
def _alpaca(per_minute: int = 100):
    from talonx_premarket import __main__ as M
    from talonx_premarket.alpaca_data import AlpacaData, RateLimiter
    M._env()
    b = M._data()
    return AlpacaData(key_id=b._headers["APCA-API-KEY-ID"], secret=b._headers["APCA-API-SECRET-KEY"],
                      limiter=RateLimiter(per_minute))


def bars_path(wid):
    return OUT / f"bars_{wid}.json.gz"


def fetch(wid: str) -> None:
    pop = json.loads((OUT / f"population_{wid}.json").read_text(encoding="utf-8"))
    D = dtu_inputs(wid)
    syms = sorted({e["symbol"] for e in pop["qualifying_events"]} | set(D["core"]) | set(R.ETFS))
    p = bars_path(wid)
    have = json.load(gzip.open(p, "rt", encoding="utf-8")) if p.exists() else {}
    need = [s for s in syms if s not in have]
    if need:
        w = window(wid)
        data = _alpaca()
        t = time.time()
        res = data.bars_ex(need, timeframe="1Min", start=w.open_utc - timedelta(minutes=60), end=w.close_utc)
        for s in need:
            have[s] = sorted(res.bars.get(s, []), key=lambda b: b["t"])
        with gzip.open(p, "wt", encoding="utf-8") as fh:
            json.dump(have, fh)
        print(json.dumps({"window": wid, "fetched": len(need), "failed": sorted(res.failed)[:20],
                          "n_failed": len(res.failed), "s": round(time.time() - t, 1)}))
    # SIC (static EDGAR metadata; not outcome data)
    sp = OUT / "sic_cache.json"
    sic = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    from talonx_premarket import __main__ as M
    M._env()
    ua = os.environ.get("TALONX_SEC_USER_AGENT", "").strip()
    ciks = sorted({D["sym_cik"].get(e["symbol"]) for e in pop["qualifying_events"]} - {None} - set(sic))
    for i, cik in enumerate(ciks):
        url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.loads(r.read().decode("utf-8"))
            sic[cik] = {"sic": j.get("sic"), "desc": j.get("sicDescription")}
        except Exception as ex:  # noqa: BLE001 -- unknown SIC -> SPY by the frozen rule
            sic[cik] = {"sic": None, "error": str(ex)[:80]}
        time.sleep(0.25)
        if i % 200 == 199:
            sp.write_text(json.dumps(sic), encoding="utf-8")
    sp.write_text(json.dumps(sic), encoding="utf-8")
    print(json.dumps({"window": wid, "sic_cache": len(sic), "new_ciks": len(ciks)}))


# ============================================================================================================ quotes
def backward_spread(data, sym: str, at: datetime):
    """RS-5 eligibility spread: median SIP NBBO (ask-bid)/mid in [at - w, at], w widening (frozen, backward-looking)."""
    from talonx_premarket.alpaca_data import iso as aiso
    for w in R.COST_MODEL["quote_windows_s"]:
        try:
            j = data._call("https://data.alpaca.markets/v2/stocks/quotes",
                           {"symbols": sym, "start": aiso(at - timedelta(seconds=w)), "end": aiso(at), "feed": "sip",
                            "limit": "1000"})
        except Exception:  # noqa: BLE001
            return None
        xs = []
        for q in (j.get("quotes") or {}).get(sym, []):
            bp, ap = float(q.get("bp") or 0), float(q.get("ap") or 0)
            if bp > 0 and ap > bp:
                xs.append((ap - bp) / ((ap + bp) / 2))
        if xs:
            return statistics.median(xs)
    return None


# ============================================================================================================ run
def _prep_bars(raw: dict) -> dict:
    return {s: [{"t": ts(b["t"]), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b.get("v", 0)} for b in v]
            for s, v in raw.items()}


def features_for(e, bars, core_bars, D, sic_etf, view, cache):
    w = cache["w"]
    end = ts(e["data_as_of_utc"]) if view == "ENGINE_VIEW" else ts(e["t0"])
    sb = bars.get(e["symbol"], [])
    etf = sic_etf
    bench = {k: bars.get(k, []) for k in {etf, "SPY", "QQQ"}}
    out = {}
    for L in R.LOOKBACKS_MIN:
        al = R.aligned_return(sb, bench, end, L, w.open_utc)
        if al is None:
            out[L] = None
            continue
        key = (al["s_star"], al["e_star"])
        if key not in cache["core"]:
            cache["core"][key] = R.core_index_return(core_bars, *key)
        al["bench"]["DTU_CORE_EW"], cov = cache["core"][key]
        f = R.rs_features(al, etf)
        f.update({"e_star": al["e_star"].isoformat(), "s_star": al["s_star"].isoformat(), "core_coverage": cov})
        if L == R.PRIMARY_LOOKBACK_MIN:
            f["rvol_15m"] = R.rvol_15m(sb, al["e_star"], D["advsh"].get(e["symbol"]))
        out[L] = f
    return out


def evaluate_window(wid: str, data) -> dict:
    from talonx_paperperf import signal_forensics as F
    w = window(wid)
    pop = json.loads((OUT / f"population_{wid}.json").read_text(encoding="utf-8"))
    D = dtu_inputs(wid)
    raw = json.load(gzip.open(bars_path(wid), "rt", encoding="utf-8"))
    bars = _prep_bars(raw)
    core_bars = {s: bars.get(s, []) for s in D["core"]}
    sic = json.loads((OUT / "sic_cache.json").read_text(encoding="utf-8"))
    qc = OUT / f"quotes_{wid}.json"
    qcache = json.loads(qc.read_text(encoding="utf-8")) if qc.exists() else {}
    cache = {"w": w, "core": {}}
    evs = sorted(pop["qualifying_events"], key=lambda e: (e["symbol"], e["t0"], e["seq"]))
    by_sym = C.defaultdict(list)
    for e in evs:
        by_sym[e["symbol"]].append(e)
    rows, insufficient, descriptive_events = [], 0, 0
    for sym, lst in by_sym.items():
        cik = D["sym_cik"].get(sym)
        s = (sic.get(cik) or {}).get("sic") if cik else None
        etf = R.sector_benchmark(s)
        chosen = None
        for e in lst:                                       # first qualifying = first with causal 15-min sector RS
            fe = features_for(e, bars, core_bars, D, etf, "ENGINE_VIEW", cache)
            f15 = fe.get(R.PRIMARY_LOOKBACK_MIN)
            if f15 is None or f15.get("sector_excess") is None:
                insufficient += 1
                continue
            chosen = (e, fe)
            break
        if chosen is None:
            continue
        descriptive_events += len(lst) - 1
        e, fe = chosen
        f15 = fe[R.PRIMARY_LOOKBACK_MIN]
        r = {"session": wid, "symbol": sym, "first_candidate_event_id": e["event_id"], "t0": e["t0"], "seq": e["seq"],
             "data_as_of_utc": e["data_as_of_utc"], "to_state": e["to_state"], "event_type": e["event_type"],
             "score": e["score"], "dtu_state": e["dtu_state"], "sic": s, "benchmark": etf,
             **{k: f15.get(k) for k in ("stock_ret", "sector_ret", "spy_ret", "sector_excess", "market_excess",
                                        "qqq_excess", "core_excess", "rs_ratio", "rvol_15m", "core_coverage",
                                        "e_star", "s_star")},
             "diag_lookbacks": {str(L): (None if fe[L] is None else {k: fe[L].get(k) for k in
                                                                     ("sector_excess", "market_excess")})
                                for L in R.LOOKBACKS_MIN if L != R.PRIMARY_LOOKBACK_MIN}}
        fw = features_for(e, bars, core_bars, D, etf, "WALLCLOCK_VIEW", cache).get(R.PRIMARY_LOOKBACK_MIN)
        r["wallclock_sector_excess"] = fw.get("sector_excess") if fw else None
        # actionable entry (forensic rule) + outcomes
        t0 = ts(e["t0"])
        et = F.ceil_min(t0)
        sb = raw.get(sym, [])
        eb = next((x for x in sb if et <= ts(x["t"]) < et + timedelta(minutes=10)), None)
        if eb is not None and ts(eb["t"]) < w.close_utc:
            ep, et = float(eb["o"]), ts(eb["t"])
            r["entry_utc"], r["entry_price"] = et.isoformat(), ep
            oc = F.outcome(sb, et, ep, w.close_utc, w.close_utc)
            for h in ("15", "30", "60"):
                r[f"gross{h}"] = oc.get(f"r{h}")
            r["gross_close"], r["mfe"], r["mae"] = oc.get("rclose"), oc.get("mfe"), oc.get("mae")
            k = f"{sym}|{et.isoformat()}"
            if k not in qcache:
                sp, nq, win = F.quote_spread(data, sym, et)
                qcache[k] = [sp, nq, win]
            r["spread_bps"] = qcache[k][0]
            r["cost_basis"] = "MAX(V2_FRICTION_20BPS, MEASURED_SPREAD)" if r["spread_bps"] is not None else "COST_PARTIAL"
            r["cost_frac"] = R.cost_frac(r["spread_bps"])
            for h in ("15", "30", "60", "_close"):
                g = r.get(f"gross{h}")
                r[f"net{h}"] = None if g is None else g - r["cost_frac"]
        # RS-5 eligibility spread (backward, at E*), only where RS-2's condition holds
        if (r["sector_excess"] or 0) >= 0.015:
            k = f"B|{sym}|{r['e_star']}"
            if k not in qcache:
                qcache[k] = backward_spread(data, sym, ts(r["e_star"]))
            r["spread_to_price"] = qcache[k]
        rows.append(r)
        if len(rows) % 100 == 0:
            qc.write_text(json.dumps(qcache), encoding="utf-8")
    qc.write_text(json.dumps(qcache), encoding="utf-8")
    ev_core = [c for c in cache["core"].values() if c[0] is not None]
    return {"window_id": wid, "population": {k: v for k, v in pop.items() if k != "qualifying_events"},
            "qualifying_events": len(evs), "symbols_with_qualifying_events": len(by_sym),
            "insufficient_bars_events": insufficient, "descriptive_later_events": descriptive_events,
            "core_index_coverage_mean": statistics.mean(c[1] for c in ev_core) if ev_core else None,
            "core_index_coverage_min": min(c[1] for c in ev_core) if ev_core else None,
            "core_bars_present": sum(1 for s in D["core"] if bars.get(s)), "core_n": len(D["core"]), "rows": rows}


def pct(x, d=3):
    return None if x is None else round(100 * x, d)


def summarize_metrics(m: dict) -> dict:
    if not m.get("n"):
        return {"n": 0}
    out = {"n": m["n"]}
    for k in ("gross_mean", "gross_median", "net_mean", "net_median", "top3_removed_gross_mean", "top3_removed_net_mean"):
        out[k + "_pct"] = pct(m[k])
    out["win_rate"] = round(m["win_rate"], 3)
    out["profit_factor"] = None if m["profit_factor"] is None else round(m["profit_factor"], 3)
    for k in ("top1_share_of_gross", "top3_share_of_gross"):
        out[k] = None if m[k] is None else round(m[k], 3)
    out["gross_pnl_usd"], out["net_pnl_usd"] = round(m["gross_pnl_usd"], 2), round(m["net_pnl_usd"], 2)
    return out


def analyse(rows: list[dict], wids: list[str]) -> dict:
    ok = [r for r in rows if r.get("gross30") is not None and r.get("net30") is not None]
    res = {"PRIMARY_OBSERVATIONS": len(rows), "UNIQUE_SYMBOL_SESSIONS": len({(r["symbol"], r["session"]) for r in rows}),
           "RESOLVED_+30M": len(ok),
           "DTU_CORE_OBSERVATIONS": sum(1 for r in rows if r["dtu_state"] == "ACTIVE_CORE"),
           "DTU_EVENT_PROMOTED_OBSERVATIONS": sum(1 for r in rows if r["dtu_state"].startswith("EVENT_PROMOTED")),
           "event_promoted_by_reason": dict(C.Counter(r["dtu_state"] for r in rows if r["dtu_state"] != "ACTIVE_CORE")),
           "benchmark_mix": dict(C.Counter(r["benchmark"] for r in rows).most_common()),
           "sic_known": sum(1 for r in rows if r["sic"]),
           "cost_partial": sum(1 for r in ok if r["spread_bps"] is None)}
    need = [r for r in rows]
    have = [r for r in need if r.get("spy_ret") is not None and r.get("sector_ret") is not None]
    res["BENCHMARK_DATA_COVERAGE"] = round(len(have) / len(need), 4) if need else 0.0
    # quintiles
    q = R.assign_quintiles(ok)
    qs = {k: R.metrics([(o["gross30"], o["net30"]) for o in v]) for k, v in q.items()}
    gate = R.gradient_gate(qs)
    res["QUINTILES"] = {f"Q{k}": {**summarize_metrics(qs[k]),
                                  "rs_range_pct": [pct(min(o['sector_excess'] for o in q[k])),
                                                   pct(max(o['sector_excess'] for o in q[k]))] if q[k] else None}
                        for k in range(1, 6)}
    res["QUINTILE_GRADIENT"] = {"spearman": gate["spearman"], "q5_minus_q1_gross_pct": pct(gate["q5_minus_q1_gross"]),
                                "q5_net_pct": pct(gate.get("q5_net")), "pass": gate["pass"],
                                "conditions": gate.get("conditions")}
    # descriptive horizons per quintile
    res["QUINTILES_OTHER_HORIZONS_GROSS_pct"] = {
        f"Q{k}": {h: pct(statistics.mean(x)) if (x := [o[f"gross{h}"] for o in q[k] if o.get(f"gross{h}") is not None])
                  else None for h in ("15", "60", "_close")} for k in range(1, 6)}
    # diagnostics: other views / benchmarks as quintile keys (never gate)
    diag = {}
    for name, key in (("WALLCLOCK_VIEW_sector_excess", "wallclock_sector_excess"), ("SPY_market_excess", "market_excess"),
                      ("QQQ_excess", "qqq_excess"), ("DTU_CORE_EW_excess", "core_excess")):
        qq = R.assign_quintiles([o for o in ok if o.get(key) is not None], key=key)
        mm = {k: R.metrics([(o["gross30"], o["net30"]) for o in v]) for k, v in qq.items()}
        gg = R.gradient_gate(mm)
        diag[name] = {"q_gross_pct": [pct(mm[k].get("gross_mean")) for k in range(1, 6)],
                      "q_n": [mm[k].get("n", 0) for k in range(1, 6)], "spearman": gg["spearman"],
                      "q5_minus_q1_gross_pct": pct(gg["q5_minus_q1_gross"])}
    res["DIAGNOSTIC_QUINTILES (non-gating)"] = diag
    # per-session split of the primary quintile gradient
    res["PER_SESSION_Q5_MINUS_Q1_GROSS_pct"] = {}
    for wid in wids:
        qq = R.assign_quintiles([o for o in ok if o["session"] == wid])
        mm = {k: R.metrics([(o["gross30"], o["net30"]) for o in v]) for k, v in qq.items()}
        res["PER_SESSION_Q5_MINUS_Q1_GROSS_pct"][wid] = {
            "q_gross_pct": [pct(mm[k].get("gross_mean")) for k in range(1, 6)],
            "q5_minus_q1": pct(R.gradient_gate(mm)["q5_minus_q1_gross"])}
    # score independence
    inc = R.incremental_to_score(ok)
    res["RS_INCREMENTAL_TO_SCORE"] = {"answer": inc["answer"], "flag": inc["flag"],
                                      "weighted_delta_pct": pct(inc["weighted_delta"]),
                                      "ols_t_rs_given_score": None if inc["ols_t_rs_given_score"] is None
                                      else round(inc["ols_t_rs_given_score"], 2),
                                      "bands": [{**b, "high_RS_forward_return": pct(b["high_RS_forward_return"]),
                                                 "low_RS_forward_return": pct(b["low_RS_forward_return"]),
                                                 "delta": pct(b["delta"])} for b in inc["bands"]]}
    # variants
    results, vout = [], {}
    for v in R.VARIANTS:
        sel = [o for o in ok if R.variant_pass(v, o)]
        m = R.metrics([(o["gross30"], o["net30"]) for o in sel])
        st = R.classify_variant(v, m, gate["pass"]) if m.get("n") else ("DIAGNOSTIC_ONLY" if not v["long_candidate"]
                                                                          else "FAILS_MINIMUM")
        mg = R.minimum_gate(m, gate["pass"]) if m.get("n") else {"conditions": {}}
        results.append({"variant": v, "metrics": m, "status": st})
        vout[v["id"]] = {"name": v["name"], **summarize_metrics(m), "status": st,
                         "minimum_gate_conditions": mg["conditions"],
                         "by_session_n_gross_pct": {w: [len(x := [o for o in sel if o["session"] == w]),
                                                        pct(statistics.mean(o["gross30"] for o in x)) if x else None]
                                                    for w in wids},
                         "by_dtu": {k: [len(x := [o for o in sel if o["dtu_state"].startswith(k)]),
                                        pct(statistics.mean(o["gross30"] for o in x)) if x else None]
                                    for k in ("ACTIVE_CORE", "EVENT_PROMOTED")},
                         "other_horizons_gross_pct": {h: pct(statistics.mean(x)) if (
                             x := [o[f"gross{h}"] for o in sel if o.get(f"gross{h}") is not None]) else None
                             for h in ("15", "60", "_close")}}
    res["VARIANTS"] = vout
    res["PHASE_A_VARIANTS_PASSING_MINIMUM"] = [r["variant"]["id"] for r in results if r["variant"]["long_candidate"]
                                               and r["status"] in ("PASSES_STRONG_GATE", "INTERESTING_BUT_INSUFFICIENT")]
    res["PHASE_A_VARIANTS_PASSING_STRONG_GATE"] = [r["variant"]["id"] for r in results
                                                   if r["status"] == "PASSES_STRONG_GATE"]
    pb, why = R.select_phase_b(results)
    res["PHASE_B_CANDIDATE"], res["PHASE_B_SELECTION_REASON"] = pb, why
    long_ok = [r for r in results if r["variant"]["long_candidate"] and r["metrics"].get("n")]
    best = max(long_ok, key=lambda r: (r["metrics"]["net_mean"], r["metrics"]["n"])) if long_ok else None
    res["BEST_LONG_VARIANT"] = best["variant"]["id"] if best else None
    res["CURRENT_VERDICT"] = R.verdict(len(ok), res["BENCHMARK_DATA_COVERAGE"], gate["pass"],
                                       {r["variant"]["id"]: r["status"] for r in results}, pb)
    # whole population reference
    res["ALL_PRIMARY_OBSERVATIONS_+30M"] = summarize_metrics(R.metrics([(o["gross30"], o["net30"]) for o in ok]))
    return res


def run(wids: list[str]) -> dict:
    data = _alpaca()
    per = {w: evaluate_window(w, data) for w in wids}
    rows = [r for w in wids for r in per[w]["rows"]]
    res = {"hypothesis_version": R.HYPOTHESIS_VERSION, "spec_fingerprint": R.spec_fingerprint(),
           "mapping_version": R.SECTOR_MAPPING_VERSION, "mapping_hash": R.mapping_hash(),
           "cost_model_version": R.COST_MODEL_VERSION, "cost_model_hash": R.cost_model_hash(),
           "generated_utc": datetime.now(UTC).isoformat(), "sessions": wids,
           "per_window": {w: {k: v for k, v in per[w].items() if k != "rows"} for w in wids},
           "CORE_INDEX_COVERAGE": {w: [per[w]["core_index_coverage_mean"], per[w]["core_index_coverage_min"]]
                                   for w in wids},
           **analyse(rows, wids), "rows": rows}
    (OUT / "phase_a.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res


def main(argv):
    cmd, wids = argv[0], argv[1:]
    if cmd == "population":
        for w in wids:
            p = population(w)
            print(json.dumps({"window": w, "events_considered": p["events_considered"], "counts": p["counts"],
                              "core_n": p["core_n"], "symbols": len({e["symbol"] for e in p["qualifying_events"]}),
                              "notes": p["dtu_notes"]}, default=str))
    elif cmd == "fetch":
        for w in wids:
            fetch(w)
    elif cmd == "run":
        res = run(wids)
        print(json.dumps({k: v for k, v in res.items() if k not in ("rows",)}, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
