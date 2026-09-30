"""
PAPER_SIGNAL profitability forensics (2026-09-30). READ-ONLY on production stores; outputs under results/profitability/.
No broker, no orders, no Telegram.

For every PROMOTED_SIGNAL of a trading window (long-only BULLISH):

  RESEARCH ENTRY    = the Signal's reference price at its data_as_of (what the engine saw, 15-min delayed SIP)
  ACTIONABLE ENTRY  = open of the first 1-min SIP bar starting at/after the Telegram SENT time (rounded up to the
                      minute) -- the first price the operator could realistically have traded after receiving it.
                      Never backdated to data_as_of.
  Horizons from each entry: +5 / +15 / +30 / +60 min (close of the last bar completed by entry+h) and session close
  (last regular-session bar). A horizon ending after the regular close is UNRESOLVED (never carried overnight).
  MFE / MAE: highs / lows from the entry bar to the close.

Costs (no new assumption):
  V2_FRICTION   20 bps round trip -- the project's documented research friction (talonx_v2/config.py friction_bps)
  SPREAD        measured SIP NBBO quoted spread at the actionable entry time, paid once in + once out = full spread
  PRIMARY NET   gross - max(V2_FRICTION, SPREAD); if the spread is unmeasured, V2_FRICTION only (flagged COST_PARTIAL)
Paper outcomes are descriptive. Two days cannot prove an edge.
usage: python -m talonx_paperperf.signal_forensics WINDOW_ID [--live]
       python -m talonx_paperperf.signal_forensics combine WINDOW_ID [WINDOW_ID ...]
"""
from __future__ import annotations

import collections as C
import csv
import json
import math
import sqlite3
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
LIVE = REPO / "results" / "opportunity"
OUT = REPO / "results" / "profitability"
UTC = timezone.utc
HORIZONS = (5, 15, 30, 60)
V2_FRICTION_BPS = 20.0
START_CAPITAL, POSITION_USD = 100_000.0, 10_000.0      # V2-PAPER-RC1 campaign assumptions ($100k / $10k)
MAX_CONCURRENT = int(START_CAPITAL // POSITION_USD)
QUOTE_WINDOWS_S = (2, 30, 300)
SIP_DELAY = timedelta(minutes=16)


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def iso(t):
    return t.astimezone(UTC).isoformat()


def ceil_min(t: datetime) -> datetime:
    f = t.replace(second=0, microsecond=0)
    return f if f == t else f + timedelta(minutes=1)


# ============================================================================================================ inputs
def load_signals(wid: str) -> list[dict]:
    pr, ob, op = ro(LIVE / "promotion.db"), ro(LIVE / "promotion_signal_notifications.db"), ro(LIVE / "opportunity.db")
    sent = {r["event_id"]: dict(r) for r in ob.execute("SELECT event_id, state, sent_at_utc, created_at_utc "
                                                       "FROM ops_notification_outbox")}
    out = []
    for r in pr.execute("SELECT * FROM promotions WHERE window_id=? AND state='PROMOTED_SIGNAL' ORDER BY decision_utc",
                        (wid,)):
        s = dict(r)
        o = sent.get(s["signal_event_id"] or s["promotion_id"]) or {}
        s["send_state"], s["sent_at_utc"] = o.get("state"), o.get("sent_at_utc")
        c = op.execute("SELECT catalyst, liquidity_json, first_seen_phase FROM candidates WHERE candidate_id=?",
                       (s["candidate_id"],)).fetchone()
        e = op.execute("SELECT catalyst, features_json, score_json FROM candidate_events WHERE event_id=?",
                       (s["event_id"],)).fetchone()
        liq = json.loads(c["liquidity_json"] or "{}") if c else {}
        feats = json.loads(e["features_json"] or "{}") if e else {}
        s["catalyst"] = (e["catalyst"] if e and e["catalyst"] else (c["catalyst"] if c else None)) or "none found"
        s["adv20_usd"] = feats.get("adv20_dollars") or liq.get("adv20_dollars")
        s["gap_pct"] = feats.get("gap_pct")
        out.append(s)
    return out


def fetch_bars(symbols: list[str], start: datetime, end: datetime) -> dict[str, list[dict]]:
    from talonx_premarket import __main__ as M
    from talonx_premarket.alpaca_data import AlpacaData, RateLimiter
    M._env()
    b = M._data()
    data = AlpacaData(key_id=b._headers["APCA-API-KEY-ID"], secret=b._headers["APCA-API-SECRET-KEY"],
                      limiter=RateLimiter(60))
    res = data.bars_ex(sorted(set(symbols)), timeframe="1Min", start=start, end=end)
    if res.failed:
        print(json.dumps({"bar_fetch_failed": sorted(res.failed)}), file=sys.stderr)
    return {s: sorted(v, key=lambda x: x["t"]) for s, v in res.bars.items()}, data


def quote_spread(data, sym: str, at: datetime) -> tuple[float | None, int, int]:
    """Median SIP NBBO spread (bps of mid) in [at, at+w], widening w. Returns (bps, n_quotes, window_s)."""
    from talonx_premarket.alpaca_data import iso as aiso
    for w in QUOTE_WINDOWS_S:
        try:
            j = data._call("https://data.alpaca.markets/v2/stocks/quotes",
                           {"symbols": sym, "start": aiso(at), "end": aiso(at + timedelta(seconds=w)), "feed": "sip",
                            "limit": "1000"})
        except Exception:  # noqa: BLE001 -- unmeasured, never invented
            return None, 0, w
        xs = []
        for q in (j.get("quotes") or {}).get(sym, []):
            bp, ap = float(q.get("bp") or 0), float(q.get("ap") or 0)
            if bp > 0 and ap > bp:
                xs.append((ap - bp) / ((ap + bp) / 2) * 1e4)
        if xs:
            return round(statistics.median(xs), 2), len(xs), w
    return None, 0, QUOTE_WINDOWS_S[-1]


# ============================================================================================================ outcomes
def outcome(bars: list[dict], entry_t: datetime, entry_p: float, close_utc: datetime, resolve_until: datetime) -> dict:
    after = [b for b in bars if entry_t <= ts(b["t"]) < close_utc and ts(b["t"]) + timedelta(minutes=1) <= resolve_until]
    out = {}
    for h in HORIZONS:
        end = entry_t + timedelta(minutes=h)
        if end > close_utc:
            out[f"r{h}"], out[f"s{h}"] = None, "UNRESOLVED_AFTER_CLOSE"
            continue
        if end > resolve_until:
            out[f"r{h}"], out[f"s{h}"] = None, "PENDING"
            continue
        px = None
        for b in after:
            if ts(b["t"]) + timedelta(minutes=1) <= end:
                px = float(b["c"])
        out[f"r{h}"] = None if px is None else px / entry_p - 1.0
        out[f"s{h}"] = "OK" if px is not None else "NO_BAR"
    complete = resolve_until >= close_utc and bool(after)
    out["rclose"] = (float(after[-1]["c"]) / entry_p - 1.0) if complete else None
    out["sclose"] = "OK" if complete else ("PENDING" if resolve_until < close_utc else "NO_BAR")
    if after:
        out["mfe"] = max(float(b["h"]) for b in after) / entry_p - 1.0
        out["mae"] = min(float(b["l"]) for b in after) / entry_p - 1.0
    else:
        out["mfe"] = out["mae"] = None
    return out


def analyse_window(wid: str, live: bool = False) -> dict:
    from talonx_opportunity.phases import trading_window
    w = trading_window(date.fromisoformat(wid))
    now = datetime.now(UTC)
    resolve_until = min(w.close_utc, now - SIP_DELAY) if live else w.close_utc
    sigs = load_signals(wid)
    if not sigs:
        return {"window_id": wid, "signals": 0}
    start = min(ts(s["data_as_of_utc"]) for s in sigs) - timedelta(minutes=2)
    bars, data = fetch_bars([s["symbol"] for s in sigs], start, resolve_until - timedelta(seconds=1))
    shadow = shadow_status(wid, sigs)
    prev = {}
    pf = OUT / f"{wid}{'_live' if live else ''}.json"
    if pf.exists():                                    # reuse spreads already measured (no repeated quote requests)
        try:
            prev = {r["promotion_id"]: r for r in json.loads(pf.read_text(encoding="utf-8"))["rows"]
                    if r.get("spread_quotes")}
        except (ValueError, KeyError):
            prev = {}
    rows = []
    for s in sigs:
        b = bars.get(s["symbol"], [])
        ref_t, ref_p = ts(s["data_as_of_utc"]), float(s["reference_price"])
        sent = ts(s["sent_at_utc"]) if s["sent_at_utc"] else None
        r = {"window_id": wid, "promotion_id": s["promotion_id"], "symbol": s["symbol"], "score": s["score"],
             "direction": "LONG", "horizons": s["horizons_json"], "phase": s["processing_phase"],
             "data_as_of_utc": s["data_as_of_utc"], "event_utc": s["event_utc"], "queued_utc": s["queued_utc"],
             "decision_utc": s["decision_utc"], "sent_at_utc": s["sent_at_utc"], "reference_price": ref_p,
             "catalyst": s["catalyst"], "adv20_usd": s["adv20_usd"], "gap_pct": s["gap_pct"],
             "shadow_state": shadow.get(s["promotion_id"], "UNKNOWN")}
        # latency decomposition
        r["provider_delay_s"] = round((ts(s["event_utc"]) - ref_t).total_seconds())
        r["engine_to_queue_s"] = round((ts(s["queued_utc"]) - ts(s["event_utc"])).total_seconds())
        r["promotion_queue_delay_s"] = round((ts(s["decision_utc"]) - ts(s["queued_utc"])).total_seconds())
        r["telegram_delivery_s"] = round((sent - ts(s["decision_utc"])).total_seconds()) if sent else None
        r["data_as_of_to_send_s"] = round((sent - ref_t).total_seconds()) if sent else None
        # research entry
        for k, v in outcome(b, ref_t, ref_p, w.close_utc, resolve_until).items():
            r[f"res_{k}"] = v
        # actionable entry
        if sent and ceil_min(sent) < w.close_utc:
            et = ceil_min(sent)
            eb = next((x for x in b if et <= ts(x["t"]) < et + timedelta(minutes=10)), None)
            if eb is not None and ts(eb["t"]) + timedelta(minutes=1) <= resolve_until + timedelta(minutes=1):
                ep, et = float(eb["o"]), ts(eb["t"])
                r["act_entry_utc"], r["act_entry_price"] = iso(et), ep
                r["entry_drift_pct"] = (ep / ref_p - 1.0) * 100.0
                for k, v in outcome(b, et, ep, w.close_utc, resolve_until).items():
                    r[f"act_{k}"] = v
                if s["promotion_id"] in prev:
                    p_ = prev[s["promotion_id"]]
                    sp, nq, win = p_["spread_bps"], p_["spread_quotes"], p_["spread_window_s"]
                else:
                    sp, nq, win = quote_spread(data, s["symbol"], et)
                r["spread_bps"], r["spread_quotes"], r["spread_window_s"] = sp, nq, win
        rows.append(r)
    for r in rows:
        sp = r.get("spread_bps")
        r["cost_basis"] = "MAX(V2_FRICTION_20BPS, MEASURED_SPREAD)" if sp is not None else "V2_FRICTION_20BPS_ONLY"
        r["cost_frac"] = max(V2_FRICTION_BPS, sp if sp is not None else 0.0) / 1e4
    res = {"window_id": wid, "live": live, "resolve_until": iso(resolve_until), "signals": len(rows),
           "sent": sum(1 for s in sigs if s["send_state"] == "SENT"), "rows": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{wid}{'_live' if live else ''}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    with open(OUT / f"{wid}{'_live' if live else ''}_signals.csv", "w", newline="", encoding="utf-8") as fh:
        keys = sorted({k for r in rows for k in r})
        wr = csv.DictWriter(fh, fieldnames=keys)
        wr.writeheader()
        wr.writerows(rows)
    return res


def shadow_status(wid: str, sigs: list[dict]) -> dict[str, str]:
    """Dynamic Universe classification per Signal. 09-29 onwards: live shadow (Core 1200, POLICY protection);
    2026-09-28: the 09-29 study replay (E5, Core 1200)."""
    out = {}
    try:
        from talonx_shadow.dtu_eval import Policy, Window
        W = Window(wid, since="0000")
        pol = Policy(W, 1200, "POLICY")
        for s in sigs:
            st, why, _ = pol.status(s["symbol"], s["event_utc"])
            out[s["promotion_id"]] = ("ACTIVE_CORE" if why == "CORE" else "FORCED_ACTIVE" if why and "FORCED" in why
                                      else "MISSED" if st == "MISSED" else f"EVENT_PROMOTED:{why}")
        return out
    except SystemExit:
        pass
    p = REPO / "docs" / "research" / "evidence" / "2026-09-29_dynamic_tradable_universe" / "capture_rows.csv.gz"
    if p.exists():
        import gzip
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r["window"] == wid and r["population"] == "signals"
                    and r["policy"] == "E5_E4+PROTECT_ACTIVE" and r["core_n"] == "1200"]
        by = {(r["symbol"], r["at_utc"]): r for r in rows}
        for s in sigs:
            r = by.get((s["symbol"], s["event_utc"]))
            if r:
                st = r["status"]
                out[s["promotion_id"]] = ("ACTIVE_CORE" if st == "CORE" else "FORCED_ACTIVE" if st == "OPERATOR_ADDED"
                                          else "MISSED" if st == "MISSED" else f"EVENT_PROMOTED:{st}")
    return out


# ============================================================================================================ stats
def net(r: dict, prefix: str, h: str):
    g = r.get(f"{prefix}_r{h}")
    return None if g is None else g - r["cost_frac"]


def stats(xs: list[float]) -> dict:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    wins, losses = [x for x in xs if x > 0], [x for x in xs if x <= 0]
    return {"n": len(xs), "mean_pct": round(100 * statistics.mean(xs), 3), "median_pct": round(100 * statistics.median(xs), 3),
            "win_rate": round(len(wins) / len(xs), 3),
            "profit_factor": round(sum(wins) / -sum(losses), 3) if losses and sum(losses) < 0 else None,
            "sum_pct": round(100 * sum(xs), 2)}


def scorecard(rows: list[dict], prefix: str) -> dict:
    out = {"signals": len(rows)}
    for h in ("5", "15", "30", "60", "close"):
        g = [r.get(f"{prefix}_r{h}") for r in rows]
        out[f"+{h}"] = {"gross": stats(g), "net": stats([net(r, prefix, h) for r in rows]),
                        "unresolved": sum(1 for x in g if x is None)}
    out["mfe"] = stats([r.get(f"{prefix}_mfe") for r in rows])
    out["mae"] = stats([r.get(f"{prefix}_mae") for r in rows])
    return out


def portfolio(rows: list[dict], h: str, prefix: str = "act") -> dict:
    """$100k, $10k per position, <= 10 concurrent, chronological by entry; a trade is taken only if its exit horizon
    resolves (otherwise it cannot be evaluated and is counted as SKIPPED_UNRESOLVED)."""
    trades = []
    for r in rows:
        et = r.get("act_entry_utc") if prefix == "act" else r["data_as_of_utc"]
        if not et or r.get(f"{prefix}_r{h}") is None:
            continue
        et = ts(et)
        xt = datetime.combine(et.date(), datetime.min.time(), UTC) + timedelta(hours=20) if h == "close" \
            else et + timedelta(minutes=int(h))
        trades.append((et, xt, r))
    trades.sort(key=lambda x: x[0])
    open_, eq, peak, mdd, taken, skipped = [], START_CAPITAL, START_CAPITAL, 0.0, [], 0
    util = []
    for et, xt, r in trades:
        open_ = [o for o in open_ if o[1] > et]
        if len(open_) >= MAX_CONCURRENT:
            skipped += 1
            continue
        open_.append((et, xt))
        util.append(len(open_))
        g, n = r[f"{prefix}_r{h}"] * POSITION_USD, net(r, prefix, h) * POSITION_USD
        taken.append((xt, g, n, r["symbol"]))
    for xt, g, n, _ in sorted(taken):
        eq += n
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    nets = [t[2] for t in taken]
    wins, losses = [x for x in nets if x > 0], [x for x in nets if x <= 0]
    return {"STARTING_CAPITAL": START_CAPITAL, "POSITION_SIZE_RULE": f"${POSITION_USD:,.0f} equal-dollar",
            "MAX_CONCURRENT_POSITIONS": MAX_CONCURRENT, "trades": len(taken), "skipped_capacity": skipped,
            "MAX_CONCURRENT_EXPOSURE": max(util) if util else 0,
            "CAPITAL_UTILIZATION_mean_positions": round(statistics.mean(util), 2) if util else 0,
            "GROSS_PNL": round(sum(t[1] for t in taken), 2), "NET_PNL": round(sum(nets), 2),
            "ENDING_CAPITAL": round(START_CAPITAL + sum(nets), 2), "MAX_DRAWDOWN": round(mdd, 2),
            "WINNING_TRADES": len(wins), "LOSING_TRADES": len(losses),
            "WIN_RATE": round(len(wins) / len(nets), 3) if nets else None,
            "PROFIT_FACTOR": round(sum(wins) / -sum(losses), 3) if losses and sum(losses) < 0 else None,
            "EXPECTANCY_PER_TRADE": round(statistics.mean(nets), 2) if nets else None}


def concentration(rows: list[dict], h: str) -> dict:
    xs = sorted(((net(r, "act", h), r["symbol"], r["window_id"]) for r in rows if net(r, "act", h) is not None),
                reverse=True)
    if not xs:
        return {}
    tot = sum(x[0] for x in xs)
    out = {"total_net_pct_sum": round(100 * tot, 2), "best": (xs[0][1], xs[0][2], round(100 * xs[0][0], 2)),
           "worst": (xs[-1][1], xs[-1][2], round(100 * xs[-1][0], 2))}
    for k in (1, 3, 5):
        top = sum(x[0] for x in xs[:k])
        out[f"top_{k}_contribution_pct_points"] = round(100 * top, 2)
        out[f"total_without_best_{k}_pct_sum"] = round(100 * (tot - top), 2)
        out[f"mean_without_best_{k}_pct"] = round(100 * (tot - top) / (len(xs) - k), 3) if len(xs) > k else None
    out["top5_winners"] = [(s, w, round(100 * v, 2)) for v, s, w in xs[:5]]
    out["top5_losers"] = [(s, w, round(100 * v, 2)) for v, s, w in xs[-5:]]
    return out


def bucket(r: dict, kind: str) -> str:
    if kind == "score":
        s = r["score"] or 0
        return "<65" if s < 65 else "65-70" if s < 70 else "70-75" if s < 75 else "75-80" if s < 80 else "80-85" \
            if s < 85 else "85+"
    if kind == "price":
        p = r["reference_price"]
        return "<3" if p < 3 else "3-5" if p < 5 else "5-10" if p < 10 else "10-25" if p < 25 else "25-100" \
            if p < 100 else "100+"
    if kind == "spread":
        s = r.get("spread_bps")
        return "UNKNOWN" if s is None else "<=25" if s <= 25 else "25-50" if s <= 50 else "50-100" if s <= 100 \
            else ">100"
    if kind == "adv":
        a = r.get("adv20_usd")
        return "UNKNOWN" if a is None else "<5M" if a < 5e6 else "5-20M" if a < 2e7 else "20-100M" if a < 1e8 \
            else "100M+"
    if kind == "time":
        t = ts(r.get("act_entry_utc") or r["sent_at_utc"])
        m = t.hour * 60 + t.minute - (13 * 60 + 30)                     # minutes after 09:30 ET (EDT)
        return "opening_hour" if m < 60 else "midday" if m < 300 else "late_regular"
    if kind == "catalyst":
        c = (r.get("catalyst") or "").lower()
        return "8-K" if "8-k" in c else "form4/insider" if ("form 4" in c or "insider" in c) else \
            "none" if c in ("", "none found") else "other_sec"
    if kind == "shadow":
        s = r.get("shadow_state") or "UNKNOWN"
        return s.split(":")[0]
    raise ValueError(kind)


def strata(rows: list[dict]) -> dict:
    out = {}
    for kind in ("score", "price", "spread", "adv", "time", "catalyst", "shadow"):
        g = C.defaultdict(list)
        for r in rows:
            if r.get("act_entry_price"):
                g[bucket(r, kind)].append(r)
        out[kind] = {k: {"30m_net": stats([net(r, "act", "30") for r in v]),
                         "close_net": stats([net(r, "act", "close") for r in v])} for k, v in sorted(g.items())}
    return out


def delay_impact(rows: list[dict]) -> dict:
    d = [r["entry_drift_pct"] for r in rows if r.get("entry_drift_pct") is not None]
    ad = [abs(x) for x in d]
    lat = [r["data_as_of_to_send_s"] for r in rows if r.get("data_as_of_to_send_s") is not None]
    return {"n": len(d), "drift_median_pct": round(statistics.median(d), 3) if d else None,
            "drift_p90_pct": round(sorted(d)[int(.9 * (len(d) - 1))], 3) if d else None,
            "abs_le_0.5": round(sum(x <= .5 for x in ad) / len(ad), 3) if ad else None,
            "abs_le_1": round(sum(x <= 1 for x in ad) / len(ad), 3) if ad else None,
            "abs_le_2": round(sum(x <= 2 for x in ad) / len(ad), 3) if ad else None,
            "abs_gt_2": round(sum(x > 2 for x in ad) / len(ad), 3) if ad else None,
            "already_up_gt_1pct": round(sum(x > 1 for x in d) / len(d), 3) if d else None,
            "already_down_lt_-1pct": round(sum(x < -1 for x in d) / len(d), 3) if d else None,
            "data_as_of_to_send_median_s": statistics.median(lat) if lat else None,
            "data_as_of_to_send_p90_s": sorted(lat)[int(.9 * (len(lat) - 1))] if lat else None,
            "latency_components_median_s": {k: statistics.median([r[k] for r in rows if r.get(k) is not None])
                                            for k in ("provider_delay_s", "engine_to_queue_s",
                                                      "promotion_queue_delay_s", "telegram_delivery_s")}}


def dtu_compare(rows: list[dict]) -> dict:
    out = {}
    for h in ("30", "close"):
        full = [r for r in rows if net(r, "act", h) is not None]
        kept = [r for r in full if not str(r.get("shadow_state")).startswith(("MISSED", "UNKNOWN"))]
        dropped = [r for r in full if r not in kept]
        f = sum(net(r, "act", h) for r in full) * POSITION_USD
        k = sum(net(r, "act", h) for r in kept) * POSITION_USD
        out[h] = {"FULL_NET_PNL": round(f, 2), "DTU_NET_PNL": round(k, 2), "PNL_DIFFERENCE": round(k - f, 2),
                  "FULL_EXPECTANCY_pct": round(100 * f / POSITION_USD / len(full), 3) if full else None,
                  "DTU_EXPECTANCY_pct": round(100 * k / POSITION_USD / len(kept), 3) if kept else None,
                  "signals_full": len(full), "signals_retained": len(kept),
                  "unknown_shadow_state": sum(1 for r in full if str(r.get("shadow_state")).startswith("UNKNOWN")),
                  "removed_winning_pnl": round(sum(net(r, "act", h) for r in dropped if net(r, "act", h) > 0)
                                               * POSITION_USD, 2),
                  "removed_losing_pnl": round(sum(net(r, "act", h) for r in dropped if net(r, "act", h) <= 0)
                                              * POSITION_USD, 2),
                  "missed": [(r["symbol"], r["window_id"], round(100 * net(r, "act", h), 2)) for r in dropped]}
    return out


def report(rows: list[dict]) -> dict:
    res = {"RESEARCH": scorecard(rows, "res"), "ACTIONABLE": scorecard(rows, "act")}
    res["false_edge"] = {}
    for h in ("15", "30", "60", "close"):
        rs, ac = stats([net(r, "res", h) for r in rows]), stats([net(r, "act", h) for r in rows])
        flag = ("DELAY_ERASES_EDGE" if rs.get("mean_pct", 0) > 0 and ac.get("mean_pct", 0) <= 0 else
                "BOTH_NEGATIVE" if rs.get("mean_pct", 0) <= 0 and ac.get("mean_pct", 0) <= 0 else
                "BOTH_POSITIVE" if ac.get("mean_pct", 0) > 0 and rs.get("mean_pct", 0) > 0 else "ACTIONABLE_ONLY_POSITIVE")
        res["false_edge"][h] = {"research_net_mean": rs.get("mean_pct"), "actionable_net_mean": ac.get("mean_pct"),
                                "flag": flag}
    res["portfolio"] = {h: portfolio(rows, h) for h in ("15", "30", "60", "close")}
    res["concentration"] = {h: concentration(rows, h) for h in ("30", "close")}
    res["strata"] = strata(rows)
    res["delay_impact"] = delay_impact(rows)
    res["dtu"] = dtu_compare(rows)
    res["cost"] = {"V2_FRICTION_BPS": V2_FRICTION_BPS,
                   "spread_measured": sum(1 for r in rows if r.get("spread_bps") is not None),
                   "spread_unmeasured (V2 friction only)": sum(1 for r in rows if r.get("spread_bps") is None
                                                               and r.get("act_entry_price")),
                   "median_cost_bps": statistics.median(r["cost_frac"] * 1e4 for r in rows) if rows else None,
                   "spread_bps_median": statistics.median([r["spread_bps"] for r in rows if r.get("spread_bps")
                                                           is not None]) if rows else None}
    return res


def main(argv):
    if argv[0] == "combine":
        rows = []
        per = {}
        for wid in argv[1:]:
            d = json.loads((OUT / f"{wid}.json").read_text(encoding="utf-8"))
            rows += d["rows"]
            per[wid] = report(d["rows"])
        out = {"windows": argv[1:], "per_window": per, "combined": report(rows)}
        (OUT / "combined.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
        print(json.dumps({"combined_rows": len(rows)}))
        return
    live = "--live" in argv
    res = analyse_window(argv[0], live=live)
    rep = report(res["rows"]) if res.get("rows") else {}
    (OUT / f"{argv[0]}{'_live' if live else ''}_report.json").write_text(json.dumps(rep, indent=1, default=str),
                                                                          encoding="utf-8")
    a = rep.get("ACTIONABLE", {})
    print(json.dumps({"window": argv[0], "live": live, "signals": res["signals"], "resolve_until": res.get("resolve_until"),
                      **{f"act_{h}_net": a.get(f"+{h}", {}).get("net") for h in ("15", "30", "60", "close")}},
                     default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
