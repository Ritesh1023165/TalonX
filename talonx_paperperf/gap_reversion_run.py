"""
LARGE_GAP_REVERSION_V1 runner (READ-ONLY research; outputs results/gap_reversion/). Wires free Alpaca SIP daily /
1-min bars + quotes, Alpaca asset flags and the EDGAR daily form index into the FROZEN rules of gap_reversion.py
(pre-registered at 7b06ff3). Defines no threshold, entry, exit or gate.
usage: python -m talonx_paperperf.gap_reversion_run daily | candidates | minute | evaluate | edgar | report
"""
from __future__ import annotations

import collections as C
import gzip
import json
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from talonx_paperperf import gap_reversion as G  # noqa: E402

OUT = REPO / "results" / "gap_reversion"
UTC = timezone.utc
H0, H1 = G.SPEC["periods"]["HISTORICAL"]
CLUE = G.SPEC["periods"]["CLUE_EXCLUDED"]


def J(p):
    return json.load(gzip.open(p, "rt", encoding="utf-8")) if str(p).endswith(".gz") else json.loads(Path(p).read_text())


def W(p, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh)


def data_client(per_min=150):
    """Alpaca SIP client with RAW (unadjusted) bars, as pre-registered."""
    import dataclasses
    from talonx_paperperf.rs_phase_a import _alpaca
    d = _alpaca(per_min)
    d.cfg = dataclasses.replace(d.cfg, adjustment="raw")
    return d


def universe() -> tuple[list[str], dict]:
    import sqlite3
    m = sqlite3.connect(f"file:{REPO / 'results/opportunity/market.db'}?mode=ro", uri=True)
    mem = json.loads(m.execute("SELECT members_json FROM universe WHERE window_id='2026-09-30'").fetchone()[0])
    el = [x for x in mem if x.get("status") == "ELIGIBLE"]
    return sorted(x["symbol"] for x in el), {x["symbol"]: x.get("cik") for x in el}


def fetch_daily(data, syms, adjustment, start="2023-11-01", end="2026-09-29") -> dict:
    import re
    out = {}
    for i in range(0, len(syms), 100):
        batch = list(syms[i:i + 100])
        got = {s: [] for s in batch}
        token = None
        while True:
            p = {"symbols": ",".join(batch), "timeframe": "1Day", "start": start, "end": end, "feed": "sip",
                 "adjustment": adjustment, "limit": "10000"}
            if token:
                p["page_token"] = token
            try:
                j = data._call("https://data.alpaca.markets/v2/stocks/bars", p)
            except RuntimeError as ex:
                m = re.search(r"invalid symbol: \W*([A-Za-z0-9.\-]+)", str(ex))
                if not m or m.group(1) not in batch:
                    raise
                batch.remove(m.group(1))
                got = {s: [] for s in batch}
                token = None
                continue
            for s, bars in (j.get("bars") or {}).items():
                got.setdefault(s, []).extend([b["t"][:10], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in bars)
            token = j.get("next_page_token")
            if not token:
                break
        out.update(got)
        if (i // 100) % 10 == 0:
            print(json.dumps({"daily": adjustment, "done": i + len(batch), "of": len(syms)}), flush=True)
    return out


def step_daily():
    syms, _ = universe()
    data = data_client()
    for adj in ("raw", "split"):
        p = OUT / f"daily_{adj}.json.gz"
        if not p.exists():
            W(p, fetch_daily(data, syms + ["SPY"], adj))


def sessions() -> list[str]:
    raw = J(OUT / "daily_raw.json.gz")
    return sorted({b[0] for b in raw["SPY"]})


def step_candidates():
    """Superset of events (no outcome read): D-1 floors, raw daily OPEN >= 1.08 x prior close (>= 10 % class), or the
    frozen 10 % hash sample with open >= 1.025 x (3-10 % class). The frozen gap is then computed on 1-min bars."""
    raw, spl = J(OUT / "daily_raw.json.gz"), J(OUT / "daily_split.json.gz")
    sess = sessions()
    wanted = [d for d in sess if (H0 <= d <= H1) or d in CLUE or d >= "2026-09-30"]
    cands = C.defaultdict(list)
    for s, bars in raw.items():
        if s == "SPY" or len(bars) < 21:
            continue
        idx = {b[0]: k for k, b in enumerate(bars)}
        sidx = {b[0]: b for b in spl.get(s, [])}
        for d in wanted:
            k = idx.get(d)
            if k is None or k < 20 or bars[k - 1][0] != sess[sess.index(d) - 1]:
                continue
            prev, cur = bars[k - 1], bars[k]
            adv = statistics.mean(b[4] * b[5] for b in bars[k - 20:k])
            if prev[4] < G.SPEC["floors_d_minus_1"]["min_close"] or adv < G.SPEC["floors_d_minus_1"]["min_adv20_usd"]:
                continue
            up = cur[1] / prev[4]          # daily open == first regular print (checked: 227/232 exact, rest < 1 %)
            if up >= 1.08 or (up >= 1.025 and G.in_sample(s, d, 0.05)):
                sp, sc = sidx.get(prev[0]), sidx.get(d)
                split = sp is None or sc is None or G.split_day(prev[4], sp[4], cur[4], sc[4])
                cands[d].append({"symbol": s, "adv20": adv, "prev_daily_close": prev[4], "split_day": split})
    W(OUT / "candidates.json.gz", cands)
    print(json.dumps({"days": len(cands), "candidates": sum(len(v) for v in cands.values()),
                      "hi_class_superset": sum(1 for v in cands.values() for x in v)}))


def step_minute():
    from talonx_opportunity.phases import trading_window
    cands = J(OUT / "candidates.json.gz")
    data = data_client()
    sess = sessions()
    d_out = OUT / "minute"
    d_out.mkdir(parents=True, exist_ok=True)
    for d in sorted(cands):
        p = d_out / f"{d}.json.gz"
        if p.exists():
            continue
        syms = sorted({c["symbol"] for c in cands[d]})
        w = trading_window(date.fromisoformat(d))
        pw = trading_window(date.fromisoformat(sess[sess.index(d) - 1]))
        cur = data.bars_ex(syms, timeframe="1Min", start=w.open_utc, end=w.close_utc - timedelta(seconds=1))
        prv = data.bars_ex(syms, timeframe="1Min", start=pw.close_utc - timedelta(minutes=30),
                           end=pw.close_utc - timedelta(seconds=1))
        W(p, {"cur": cur.bars, "prev": prv.bars, "failed": sorted(set(cur.failed) | set(prv.failed)),
              "open": w.open_utc.isoformat(), "close": w.close_utc.isoformat(), "prev_close": pw.close_utc.isoformat()})
        print(json.dumps({"day": d, "symbols": len(syms)}), flush=True)


def step_evaluate():
    """Frozen gap / exclusions / entries A,B / short-reference outcomes; quote spread at each entry (cached)."""
    from talonx_paperperf import signal_forensics as F
    cands = J(OUT / "candidates.json.gz")
    data = data_client(150)
    qp = OUT / "quotes.json"
    qc = json.loads(qp.read_text()) if qp.exists() else {}
    rows = []
    for n_day, d in enumerate(sorted(cands)):
        p = OUT / "minute" / f"{d}.json.gz"
        if not p.exists():
            continue
        M = J(p)
        op, cl, pcl = (datetime.fromisoformat(M[k]) for k in ("open", "close", "prev_close"))
        for c in cands[d]:
            s = c["symbol"]
            bars = sorted(M["cur"].get(s, []), key=lambda b: b["t"])
            pc = G.prior_close(M["prev"].get(s, []), pcl)
            ob = G.open_bar(bars, op)
            r = {"day": d, "symbol": s, "adv20": c["adv20"], "research_short_reference": True,
                 "period": "HISTORICAL" if H0 <= d <= H1 else "CLUE" if d in CLUE else "FORWARD"}
            if c["split_day"]:
                r["status"] = "SPLIT_DAY"
            elif pc is None:
                r["status"] = "NO_PRIOR_CLOSE"
            elif ob is None:
                r["status"] = "NO_OPEN_BAR"
            else:
                g = G.gap(float(ob["o"]), pc)
                r.update({"gap": g, "prior_close": pc, "open_px": float(ob["o"])})
                if g < 0.03 or not G.in_sample(s, d, g):
                    continue                                    # not in the frozen population / sample
                r["bucket"] = G.bucket(g)
                for tag, eb in (("A", G.entry_A(bars, op)), ("B", G.entry_B(bars, op) if g >= 0.10 else None)):
                    if eb is None:
                        r[f"{tag}_status"] = "NO_ENTRY_BAR" if tag == "A" else "NO_CONFIRMATION"
                        continue
                    o = G.short_outcomes(bars, eb, cl)
                    k = f"{s}|{o['entry_utc']}"
                    if k not in qc:
                        qc[k] = F.quote_spread(data, s, datetime.fromisoformat(o["entry_utc"]))[0]
                    cost = max(20.0, qc[k] or 0.0) / 1e4
                    r[tag] = {**o, "spread_bps": qc[k], "cost": cost, "cost_partial": qc[k] is None,
                              **{f"net{h}": (None if o.get(f"r{h}") is None else o[f"r{h}"] - cost)
                                 for h in ("15", "30", "60", "close")}}
                r["status"] = "EVALUATED" if "A" in r else "NO_ENTRY_BAR"
            rows.append(r)
        if n_day % 10 == 0:
            qp.write_text(json.dumps(qc))
            print(json.dumps({"day": d, "rows": len(rows)}), flush=True)
    qp.write_text(json.dumps(qc))
    W(OUT / "events.json.gz", rows)


def step_edgar():
    """EDGAR daily form index for every evaluated >= 10 % event day and its D-1 (8-K / Form 4 by issuer CIK)."""
    import urllib.request
    import re
    from talonx_premarket import __main__ as M
    M._env()
    import os
    ua = os.environ.get("TALONX_SEC_USER_AGENT", "")
    rows = J(OUT / "events.json.gz")
    sess = sessions()
    days = sorted({d for r in rows if r.get("gap", 0) >= 0.10 for d in (r["day"], sess[sess.index(r["day"]) - 1])})
    p = OUT / "edgar_index.json"
    have = json.loads(p.read_text()) if p.exists() else {}
    row_re = re.compile(r"^(?P<form>\S+(?: \S+)?)\s{2,}.+?\s{2,}(?P<cik>\d{1,10})\s{2,}(?P<date>\d{8})\s{2,}edgar/")
    for d in days:
        if d in have:
            continue
        dd = date.fromisoformat(d)
        url = f"https://www.sec.gov/Archives/edgar/daily-index/{dd.year}/QTR{(dd.month - 1) // 3 + 1}/form.{dd:%Y%m%d}.idx"
        try:
            t = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua}), timeout=30).read().decode(
                "utf-8", "replace")
            have[d] = [[m["form"], m["cik"].zfill(10)] for line in t.splitlines() if (m := row_re.match(line))
                       and m["form"] in ("8-K", "8-K/A", "6-K", "4", "4/A")]
        except Exception as ex:  # noqa: BLE001
            have[d] = {"error": str(ex)[:80]}
        time.sleep(0.7)
        p.write_text(json.dumps(have))
    print(json.dumps({"edgar_days": len(have)}))


# ============================================================================================================ report
def _pct(v):
    return None if v is None else round(100 * v, 3)


def _stat_block(rows, key, tag="A"):
    xs = [(r[tag].get(key), r["day"]) for r in rows if r.get(tag) and r[tag].get(key) is not None]
    d = G.describe([x for x, _ in xs], groups=[g for _, g in xs])
    return {k: (round(v, 2) if k == "t" and v is not None else _pct(v) if isinstance(v, float)
                else [_pct(y) for y in v] if isinstance(v, list) else v) for k, v in d.items()}


def _mini(rows, tag="A"):
    x = [r[tag]["net30"] for r in rows if r.get(tag) and r[tag].get("net30") is not None]
    g = [r[tag]["r30"] for r in rows if r.get(tag) and r[tag].get("net30") is not None]
    if not x:
        return {"n": 0}
    p = G.pf(x)
    return {"n": len(x), "gross30_pct": _pct(statistics.mean(g)), "net30_pct": _pct(statistics.mean(x)),
            "win_net": round(sum(1 for v in x if v > 0) / len(x), 3), "pf_net": None if p is None else round(p, 3)}


def _dtu_and_regime(rows):
    raw = J(OUT / "daily_raw.json.gz")
    sess = sessions()
    need = {sess[sess.index(r["day"]) - 1] for r in rows}
    pos = {s: {b[0]: k for k, b in enumerate(bars)} for s, bars in raw.items() if s != "SPY"}
    ranks = {}
    for d1 in need:                                               # causal D-1 ADV20 rank among floor-eligible names
        advs = []
        for s, bars in raw.items():
            k = pos.get(s, {}).get(d1)
            if k is None or k < 19 or bars[k][4] < 1.0:
                continue
            a = statistics.mean(b[4] * b[5] for b in bars[k - 19:k + 1])
            if a >= 1e6:
                advs.append((a, s))
        advs.sort(reverse=True)
        ranks[d1] = {s: i + 1 for i, (_, s) in enumerate(advs)}
    spy = {b[0]: b for b in raw["SPY"]}
    sd = sorted(spy)
    si = {d: i for i, d in enumerate(sd)}
    rets = {sd[i]: spy[sd[i]][4] / spy[sd[i - 1]][4] - 1 for i in range(1, len(sd))}
    vols = {sd[i]: statistics.pstdev(rets[x] for x in sd[i - 20:i]) for i in range(21, len(sd))}
    med_vol = statistics.median(vols.values())
    from talonx_premarket import __main__ as M
    M._env()
    scope = set(M._v2_scope(None))
    for r in rows:
        d1 = sess[sess.index(r["day"]) - 1]
        rk = ranks[d1].get(r["symbol"])
        r["dtu"] = ("OPERATOR_PROTECTED" if r["symbol"] in scope else "ACTIVE_CORE" if rk and rk <= 1200
                    else "EVENT_PROMOTED_BY_GAP")
        i = si[d1]
        r["spy_above_200d"] = (spy[d1][4] > statistics.mean(spy[x][4] for x in sd[i - 199:i + 1])) if i >= 199 else None
        r["spy_day_up"] = rets.get(r["day"], 0) > 0
        r["high_vol"] = vols.get(d1, med_vol) > med_vol


def _catalyst(rows):
    p = OUT / "edgar_index.json"
    if not p.exists():
        return
    idx = json.loads(p.read_text())
    sess = sessions()
    _, ciks = universe()
    for r in rows:
        cik = str(ciks.get(r["symbol"]) or "").zfill(10)
        forms = set()
        for d in (r["day"], sess[sess.index(r["day"]) - 1]):
            v = idx.get(d)
            if isinstance(v, list):
                forms |= {f for f, c in v if c == cik}
        r["catalyst"] = ("8-K" if forms & {"8-K", "8-K/A"} else "6-K" if "6-K" in forms else
                         "FORM4" if forms & {"4", "4/A"} else "NONE_KNOWN")


def _portfolio(rows):
    ev = []
    for r in rows:
        a = r.get("A")
        if a and a.get("net30") is not None:
            t = datetime.fromisoformat(a["entry_utc"])
            ev += [(t, 1, id(a), a), (t + timedelta(minutes=30), 0, id(a), a)]
    ev.sort(key=lambda x: (x[0], x[1]))
    cash, open_, pg, pn, taken, peak, mdd, util = 100_000.0, set(), 0.0, 0.0, 0, 100_000.0, 0.0, []
    for t, kind, k, a in ev:
        if kind == 1:
            if len(open_) < 10 and cash >= 10_000:
                cash -= 10_000
                open_.add(k)
                util.append(len(open_) / 10)
        elif k in open_:
            open_.discard(k)
            cash += 10_000 * (1 + a["net30"])
            pg, pn, taken = pg + 10_000 * a["r30"], pn + 10_000 * a["net30"], taken + 1
            eq = cash + 10_000 * len(open_)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
    return {"label": "RESEARCH_SHORT_PORTFOLIO (borrow NOT modelled; feasibility NOT implied)", "trades": taken,
            "gross_pnl_usd": round(pg, 2), "standard_net_pnl_usd": round(pn, 2), "ending_capital": round(cash, 2),
            "max_dd_pct_realized": round(100 * mdd, 2),
            "capital_utilization_mean": round(statistics.mean(util), 3) if util else 0}


def _shortability(syms):
    d = data_client()
    try:
        assets = d._call("https://paper-api.alpaca.markets/v2/assets", {"status": "all", "asset_class": "us_equity"})
    except Exception as ex:  # noqa: BLE001
        return {"overall": "UNKNOWN", "error": str(ex)[:120]}
    a = {x["symbol"]: x for x in assets}
    known = [s for s in syms if s in a]
    return {"basis": "Alpaca asset flags, CURRENT snapshot (not point-in-time); no borrow-fee data",
            "symbols": len(syms), "SHORTABILITY_KNOWN_CURRENT": len(known), "SHORTABILITY_UNKNOWN": len(syms) - len(known),
            "shortable_now": sum(1 for s in known if a[s].get("shortable")),
            "easy_to_borrow_now": sum(1 for s in known if a[s].get("easy_to_borrow")), "overall": "PARTIAL"}


def step_report():
    rows = J(OUT / "events.json.gz")
    ev = [r for r in rows if r.get("status") == "EVALUATED"]
    _dtu_and_regime(ev)
    _catalyst(ev)
    prim = [r for r in ev if r["gap"] >= 0.10]
    hist = [r for r in prim if r["period"] == "HISTORICAL"]
    vrows = [{"day": r["day"], "gross30": r["A"]["r30"], "net30": r["A"]["net30"]} for r in hist
             if r["A"].get("net30") is not None]
    x = [r["net30"] for r in vrows]
    split = G.SPEC["periods"]["HISTORICAL_HALVES_SPLIT"]
    res = {"version": G.VERSION, "fingerprint": G.spec_fingerprint(), "prereg_sha": "7b06ff3",
           "exclusions_10plus_or_unevaluated": dict(C.Counter(f"{r['period']}|{r.get('status')}" for r in rows
                                                               if r.get("status") != "EVALUATED")),
           "DATA_START": min(r["day"] for r in ev), "DATA_END": max(r["day"] for r in ev),
           "TOTAL_EVALUATED_EVENTS (incl. 3-10% sample)": len(ev), "GAP_10PLUS_EVENTS": len(prim),
           "HISTORICAL_10PLUS": len(hist), "UNIQUE_SYMBOLS_10PLUS": len({r["symbol"] for r in prim}),
           "SESSIONS_10PLUS": len({r["day"] for r in prim})}
    blk = {h: _stat_block(hist, h) for h in ("r15", "r30", "r60", "rclose", "net30")}
    blk.update({"win_rate_net30": round(sum(1 for v in x if v > 0) / len(x), 3),
                "pf_net30": round(G.pf(x), 3), "pf_gross30": round(G.pf([r["gross30"] for r in vrows]), 3),
                "mfe_short_mean_pct": _pct(statistics.mean(r["A"]["mfe_short"] for r in hist)),
                "mae_short_mean_pct": _pct(statistics.mean(r["A"]["mae_short"] for r in hist)),
                "cost_mean_pct": _pct(statistics.mean(r["A"]["cost"] for r in hist)),
                "cost_partial": sum(1 for r in hist if r["A"]["cost_partial"])})
    res["PRIMARY_A_HISTORICAL"] = blk
    res["CONCENTRATION_net30_pp"] = {k: _pct(v) for k, v in G.concentration(x).items()}
    res["VERDICT"] = G.verdict(vrows)
    res["CONFIRMATION_B_HISTORICAL"] = _mini(hist, "B")
    res["CLUE_2026-09-28_29"] = _mini([r for r in prim if r["period"] == "CLUE"])
    res["FORWARD_2026-09-30+"] = _mini([r for r in prim if r["period"] == "FORWARD"])
    res["GAP_BUCKETS (A; 3-10% = frozen 10% sample)"] = {
        b: {**_mini(sub), **{f"gross{h}_pct": _pct(statistics.mean(v)) if (v := [r["A"][f"r{h}"] for r in sub
                                                                                  if r["A"].get(f"r{h}") is not None])
                             else None for h in (15, 60)}}
        for b in sorted({r["bucket"] for r in ev}) for sub in [[r for r in ev if r["bucket"] == b]]}
    res["HALVES"] = {"H1": _mini([r for r in hist if r["day"] < split]), "H2": _mini([r for r in hist if r["day"] >= split])}
    res["BY_YEAR"] = {y: _mini([r for r in hist if r["day"][:4] == y]) for y in ("2024", "2025", "2026")}
    res["BY_MONTH_net30_pct"] = {m: _mini([r for r in hist if r["day"][:7] == m]).get("net30_pct")
                                 for m in sorted({r["day"][:7] for r in hist})}
    res["DTU (causal D-1)"] = {k: _mini([r for r in hist if r["dtu"] == k])
                               for k in ("ACTIVE_CORE", "EVENT_PROMOTED_BY_GAP", "OPERATOR_PROTECTED")}
    res["PRICE"] = {k: _mini([r for r in hist if lo <= r["open_px"] < hi])
                    for k, lo, hi in (("<3", 0, 3), ("3-5", 3, 5), ("5-10", 5, 10), ("10+", 10, 1e9))}
    res["SPREAD"] = {k: _mini([r for r in hist if r["A"]["spread_bps"] is not None and lo <= r["A"]["spread_bps"] < hi])
                     for k, lo, hi in (("<=25", 0, 25.0001), ("25-50", 25.0001, 50), ("50-100", 50, 100),
                                       (">100", 100, 1e9))}
    res["ADV"] = {k: _mini([r for r in hist if lo <= r["adv20"] < hi])
                  for k, lo, hi in (("<5M", 0, 5e6), ("5-20M", 5e6, 2e7), ("20-100M", 2e7, 1e8), (">100M", 1e8, 1e15))}
    res["REGIME"] = {"spy_above_200d": {str(k): _mini([r for r in hist if r["spy_above_200d"] == k]) for k in (True, False)},
                     "spy_day_up (same-day, descriptive)": {str(k): _mini([r for r in hist if r["spy_day_up"] == k])
                                                            for k in (True, False)},
                     "high_vol_20d": {str(k): _mini([r for r in hist if r["high_vol"] == k]) for k in (True, False)}}
    res["CATALYST (EDGAR index D-1 or D)"] = {k: _mini([r for r in hist if r.get("catalyst") == k])
                                             for k in ("8-K", "6-K", "FORM4", "NONE_KNOWN")}
    a = [r["A"] for r in hist]
    res["OPENING_PATH (A, >=10%, historical)"] = {
        "max_extension_above_entry_median_pct": _pct(statistics.median(z["max_extension_above_entry"] for z in a)),
        "t_retrace_1pct_median_min": statistics.median([z["t_retrace_1pct_min"] for z in a
                                                        if z["t_retrace_1pct_min"] is not None]),
        "t_retrace_2pct_median_min": statistics.median([z["t_retrace_2pct_min"] for z in a
                                                        if z["t_retrace_2pct_min"] is not None]),
        "share_retrace_1pct": round(sum(1 for z in a if z["t_retrace_1pct_min"] is not None) / len(a), 3),
        "share_retrace_2pct": round(sum(1 for z in a if z["t_retrace_2pct_min"] is not None) / len(a), 3),
        "share_continued_1pct_higher_first": round(sum(1 for z in a if z.get("continued_higher_first")) / len(a), 3),
        "share_never_2pct_revert": round(sum(1 for z in a if z["t_retrace_2pct_min"] is None) / len(a), 3)}
    m = _mini(hist)
    res["BASELINES_30m"] = {"zero": 0.0, "SHORT_REFERENCE_gross_pct": m["gross30_pct"],
                            "LONG_CONTINUATION_gross_pct (same events, same entry)": -m["gross30_pct"],
                            "LONG_CONTINUATION_net_pct": round(-m["gross30_pct"] - blk["cost_mean_pct"], 3)}
    res["PORTFOLIO"] = _portfolio(hist)
    res["SHORTABILITY"] = _shortability(sorted({r["symbol"] for r in prim}))
    (OUT / "report.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


def main(argv):
    {"daily": step_daily, "candidates": step_candidates, "minute": step_minute, "evaluate": step_evaluate,
     "edgar": step_edgar, "report": step_report}[argv[0]]()


if __name__ == "__main__":
    main(sys.argv[1:])
