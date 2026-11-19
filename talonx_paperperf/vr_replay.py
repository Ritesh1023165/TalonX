"""
VR_PAPER_V1 replay over recorded PAPER_SIGNALs (READ-ONLY; outputs results/vr_paper/). Streams, never mixed:
  CONTROL_FIXED_30M             the forensic's actionable +30m (unchanged reference) and a VR-entry +30m
  CONTROL_VR_LIFECYCLE          paper_mode VIRTUAL_REALTIME, V1 stop/target/flatten lifecycle
  CONTROL_ACTIONABLE_LIFECYCLE  paper_mode ACTIONABLE, same levels, entry after the Telegram send
  PULLBACK_CONFIRMATION_V1      6 pre-declared variants (VR), SHADOW
  MEAN_REVERSION_REFERENCE      RESEARCH_SHORT_REFERENCE lifecycle (VR, BEARISH V1 geometry) + fixed-horizon
                                reversion statistics by gap bucket -- never actionable advice, no live shorts
usage: python -m talonx_paperperf.vr_replay WID [WID ...]
"""
from __future__ import annotations

import collections as C
import gzip
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from talonx_paperperf import signal_forensics as F  # noqa: E402
from talonx_paperperf import vr_paper as V  # noqa: E402

OUT = REPO / "results" / "vr_paper"


def load_bars(wid: str, syms: list[str]):
    from talonx_opportunity.phases import trading_window
    w = trading_window(date.fromisoformat(wid))
    pw = trading_window(w.reference_session)
    p = OUT / f"bars_{wid}.json.gz"
    if p.exists():
        cache = json.load(gzip.open(p, "rt", encoding="utf-8"))
        _, data = F.fetch_bars(["SPY"], w.open_utc, w.open_utc + timedelta(minutes=1))
    else:
        cur, data = F.fetch_bars(syms, w.premarket_start_utc, w.close_utc)
        prev, _ = F.fetch_bars(syms, pw.open_utc, pw.close_utc - timedelta(seconds=1))
        cache = {"cur": cur, "prev": prev}
        OUT.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wt", encoding="utf-8") as fh:
            json.dump(cache, fh)
    return w, pw, cache, data


def fwd(clock: V.VirtualClock, t, px, mins):
    b = [x for x in clock.bars_from(t, t + timedelta(minutes=mins))]
    return None if not b else float(b[-1]["c"]) / px - 1.0


def path_stats(clock, entry_t, entry_px, stop, target, flat) -> dict:
    """Times (min from the VR entry) to MFE / MAE / first 0.5% & 1% pullback / first recovery / target / stop, over
    the whole remaining session (not truncated by the exit) -- descriptive."""
    bars = clock.bars_from(entry_t, flat)
    if not bars:
        return {}
    m = lambda b: (V.ts(b["t"]) - entry_t).total_seconds() / 60  # noqa: E731
    hi = max(bars, key=lambda b: float(b["h"]))
    lo = min(bars, key=lambda b: float(b["l"]))
    out = {"t_mfe": m(hi), "t_mae": m(lo)}
    peak = entry_px
    for d, k in ((0.005, "t_pullback_0_5"), (0.01, "t_pullback_1_0")):
        peak = entry_px
        for b in bars:
            if float(b["l"]) <= peak * (1 - d):
                out[k] = m(b)
                break
            peak = max(peak, float(b["h"]))
    if "t_pullback_0_5" in out:
        for b in bars:
            if m(b) > out["t_pullback_0_5"] and float(b["h"]) >= entry_px * 1.005:
                out["t_recovery_after_0_5"] = m(b)
                break
    for lvl, k, cmp in ((target, "t_target", lambda b: float(b["h"]) >= target),
                        (stop, "t_stop", lambda b: float(b["l"]) <= stop)):
        for b in bars:
            if cmp(b):
                out[k] = m(b)
                break
    return out


def replay_window(wid: str) -> list[dict]:
    fr = json.loads((REPO / "results" / "profitability" / f"{wid}.json").read_text(encoding="utf-8"))["rows"]
    w, pw, cache, data = load_bars(wid, sorted({r["symbol"] for r in fr}))
    flat = V.flatten_utc(w.close_utc)
    qp = OUT / f"quotes_{wid}.json"
    qc = json.loads(qp.read_text(encoding="utf-8")) if qp.exists() else {}
    out = []
    for r in fr:
        sym = r["symbol"]
        clock = V.VirtualClock(cache["cur"].get(sym, []))
        piv = V.prior_pivots(cache["prev"].get(sym, []), pw.open_utc, pw.close_utc)
        M, px = V.ts(r["data_as_of_utc"]), float(r["reference_price"])
        base = {"window_id": wid, "promotion_id": r["promotion_id"], "symbol": sym, "score": r["score"],
                "gap_pct": r.get("gap_pct"), "adv20_usd": r.get("adv20_usd"), "dtu_state": r.get("shadow_state"),
                "signal_market_time": M.isoformat(), "signal_wall_time": r.get("sent_at_utc"),
                "fixed30_actionable_gross": r.get("act_r30"), "fixed30_actionable_net":
                    None if r.get("act_r30") is None else r["act_r30"] - r["cost_frac"],
                "actionable_spread_bps": r.get("spread_bps")}
        streams = {}
        vr = V.open_trade(sym, "VIRTUAL_REALTIME", clock, M, px, piv, w.open_utc, flat)
        if vr["status"] == "OPENED":
            k = f"{sym}|{vr['entry_t'].isoformat()}"
            if k not in qc:
                qc[k] = F.quote_spread(data, sym, vr["entry_t"])[0]
            vr["spread_bps"] = qc[k]
            vr["cost"] = V_cost(qc[k])
            vr["net"] = vr["gross"] - vr["cost"] if vr.get("gross") is not None else None
            base["vr_fixed30_gross"] = fwd(clock, vr["entry_t"], vr["entry_px"], 30)
            base["vr_fixed30_net"] = None if base["vr_fixed30_gross"] is None else base["vr_fixed30_gross"] - vr["cost"]
            base["path"] = path_stats(clock, vr["entry_t"], vr["entry_px"], vr["stop"], vr["target"], flat)
            base["reversion_fwd"] = {h: fwd(clock, vr["entry_t"], vr["entry_px"], h) for h in (15, 30, 60)}
            lv = {k2: vr[k2] for k2 in ("stop", "target", "rrr", "atr", "geometry_path", "risk")}
            if r.get("sent_at_utc"):
                ac = V.open_trade(sym, "ACTIONABLE", clock, M, px, piv, w.open_utc, flat,
                                  entry_after=F.ceil_min(V.ts(r["sent_at_utc"])), levels=lv)
                if ac["status"] == "OPENED":
                    ac["cost"] = V_cost(r.get("spread_bps"))
                    ac["net"] = ac["gross"] - ac["cost"]
                streams["CONTROL_ACTIONABLE_LIFECYCLE"] = ac
            sh = V.open_trade(sym, "VIRTUAL_REALTIME", clock, M, px, piv, w.open_utc, flat, direction="SHORT")
            if sh["status"] == "OPENED":
                sh["cost"] = vr["cost"] if sh["entry_t"] == vr["entry_t"] else V_cost(qc.get(k))
                sh["net"] = sh["gross"] - sh["cost"]
            streams["MEAN_REVERSION_REFERENCE (RESEARCH_SHORT_REFERENCE)"] = sh
        streams["CONTROL_VR_LIFECYCLE"] = vr
        for d in V.POLICY["pullback_v1"]["depths_pct"]:
            for cf in V.POLICY["pullback_v1"]["confirmations"]:
                name = f"PULLBACK_CONFIRMATION_V1 {d}% {cf}"
                pe = V.pullback_entry(clock, M, px, d / 100, cf, w.open_utc, flat)
                if pe is None:
                    streams[name] = {"status": "NO_PULLBACK_ENTRY"}
                    continue
                t_dec, px_dec = pe
                tr = V.open_trade(sym, "VIRTUAL_REALTIME", clock, t_dec, px_dec, piv, w.open_utc, flat)
                if tr["status"] == "OPENED":
                    k = f"{sym}|{tr['entry_t'].isoformat()}"
                    if k not in qc:
                        qc[k] = F.quote_spread(data, sym, tr["entry_t"])[0]
                    tr["cost"] = V_cost(qc[k])
                    tr["net"] = tr["gross"] - tr["cost"]
                streams[name] = tr
        base["streams"] = streams
        out.append(base)
        if len(out) % 50 == 0:
            qp.write_text(json.dumps(qc), encoding="utf-8")
    qp.write_text(json.dumps(qc), encoding="utf-8")
    return out


def V_cost(spread_bps) -> float:
    return max(F.V2_FRICTION_BPS, spread_bps if spread_bps is not None else 0.0) / 1e4


def trades(rows, name):
    out = []
    for r in rows:
        s = r["streams"].get(name) or {}
        if s.get("status") == "OPENED" and s.get("net") is not None:
            out.append({**s, "dtu_state": r["dtu_state"], "symbol": r["symbol"], "gap_pct": r["gap_pct"],
                        "adv20_usd": r["adv20_usd"]})
    return out


def pct(x):
    return None if x is None else round(100 * x, 3)


def summarize(rows: list[dict]) -> dict:
    names = sorted({k for r in rows for k in r["streams"]})
    res = {"version": V.VR_PAPER_VERSION, "fingerprint": V.policy_fingerprint(), "signals": len(rows)}
    fx = [{"gross": r["fixed30_actionable_gross"], "net": r["fixed30_actionable_net"]} for r in rows
          if r.get("fixed30_actionable_net") is not None]
    fv = [{"gross": r["vr_fixed30_gross"], "net": r["vr_fixed30_net"]} for r in rows if r.get("vr_fixed30_net") is not None]
    table = {"CONTROL_FIXED_30M (actionable, forensic)": V.metrics(fx), "CONTROL_FIXED_30M (VR entry)": V.metrics(fv)}
    for n in names:
        t = trades(rows, n)
        m = V.metrics(t)
        m["portfolio"] = V.portfolio(t)
        m["exit_reasons"] = dict(C.Counter(x["exit_reason"] for x in t))
        m["not_opened"] = dict(C.Counter((r["streams"].get(n) or {}).get("status") for r in rows
                                         if (r["streams"].get(n) or {}).get("status") != "OPENED"))
        table[n] = m
    res["PRIMARY_COMPARISON"] = table
    vr, ac = table.get("CONTROL_VR_LIFECYCLE", {}), table.get("CONTROL_ACTIONABLE_LIFECYCLE", {})
    if vr.get("n") and ac.get("n"):
        res["DELAY_EFFECT (ACTIONABLE - VR)"] = {k: round(ac[k] - vr[k], 3) for k in
                                                ("gross_mean_pct", "net_mean_pct", "win_rate")}
        res["DELAY_EFFECT (ACTIONABLE - VR)"]["pnl_usd"] = round(ac["portfolio"]["net_pnl_usd"] -
                                                               vr["portfolio"]["net_pnl_usd"], 2)
    t = trades(rows, "CONTROL_VR_LIFECYCLE")
    res["CONTROL_VR_BY_DTU"] = {k: V.metrics([x for x in t if (x["dtu_state"] or "").startswith(k)])
                                for k in ("ACTIVE_CORE", "EVENT_PROMOTED", "FORCED_ACTIVE", "MISSED")}
    res["CONTROL_VR_BY_SPREAD"] = {b: V.metrics([x for x in t if x.get("spread_bps") is not None and lo <= x["spread_bps"] < hi])
                                   for b, lo, hi in (("<=25", 0, 25.0001), ("25-50", 25.0001, 50), ("50-100", 50, 100),
                                                     (">100", 100, 1e9))}
    res["CONTROL_VR_BY_ADV"] = {b: V.metrics([x for x in t if x.get("adv20_usd") is not None and lo <= x["adv20_usd"] < hi])
                                for b, lo, hi in (("<5M", 0, 5e6), ("5-20M", 5e6, 2e7), ("20-100M", 2e7, 1e8), (">=100M", 1e8, 1e15))}
    res["CONTROL_VR_BY_PRICE"] = {b: V.metrics([x for x in t if lo <= x["entry_px"] < hi])
                                  for b, lo, hi in (("<5", 0, 5), ("5-20", 5, 20), ("20-100", 20, 100), (">=100", 100, 1e9))}
    res["CONTROL_VR_RRR"] = {"median_rrr_structural": statistics.median([x["rrr"] for x in t if x.get("rrr")])
                             if any(x.get("rrr") for x in t) else None,
                             "geometry_paths": dict(C.Counter(x["geometry_path"] for x in t)),
                             "median_stop_dist_pct": pct(statistics.median(1 - x["stop"] / x["entry_px"] for x in t)),
                             "median_target_dist_pct": pct(statistics.median(x["target"] / x["entry_px"] - 1 for x in t))}
    ps = [r["path"] for r in rows if r.get("path")]
    res["ENTRY_PATH (min from VR entry, median; share reached)"] = {
        k: {"median_min": round(statistics.median(p[k] for p in ps if k in p), 1) if any(k in p for p in ps) else None,
            "share": round(sum(1 for p in ps if k in p) / len(ps), 3)}
        for k in ("t_mfe", "t_mae", "t_pullback_0_5", "t_pullback_1_0", "t_recovery_after_0_5", "t_target", "t_stop")}
    res["ENTRY_PATH"] = {"mfe_before_mae": sum(1 for p in ps if p["t_mfe"] < p["t_mae"]), "n": len(ps),
                         "target_before_stop": sum(1 for p in ps if "t_target" in p and ("t_stop" not in p or p["t_target"] < p["t_stop"])),
                         "stop_before_target": sum(1 for p in ps if "t_stop" in p and ("t_target" not in p or p["t_stop"] < p["t_target"]))}
    rv = {}
    for lo, hi in V.POLICY["reversion_v1"]["gap_buckets_pct"]:
        sub = [r for r in rows if r.get("reversion_fwd") and r.get("gap_pct") is not None and lo <= abs(r["gap_pct"]) < hi]
        d = {"n": len(sub)}
        for h in (15, 30, 60):
            xs = [r["reversion_fwd"][h] for r in sub if r["reversion_fwd"].get(h) is not None]
            if len(xs) >= 2:
                mu, sd = statistics.mean(xs), statistics.stdev(xs)
                d[f"long_ret_{h}m_mean_pct"] = pct(mu)
                d[f"t_stat_{h}m"] = round(mu / (sd / len(xs) ** 0.5), 2) if sd else None
        sh = [x for x in trades([r for r in sub], "MEAN_REVERSION_REFERENCE (RESEARCH_SHORT_REFERENCE)")]
        d["short_reference_lifecycle"] = V.metrics(sh)
        rv[f"{lo}-{hi if hi < 1e8 else 'inf'}%"] = d
    res["MEAN_REVERSION_BY_GAP (RESEARCH_SHORT_REFERENCE)"] = rv
    return res


def main(wids: list[str]) -> dict:
    rows = []
    for w in wids:
        rows += replay_window(w)
    res = summarize(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"replay_{'_'.join(wids)}.json").write_text(json.dumps({"summary": res, "rows": rows}, default=str,
                                                                    indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    main(sys.argv[1:])
