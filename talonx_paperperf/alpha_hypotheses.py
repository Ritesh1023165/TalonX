"""
Alternative CAUSAL entry hypotheses on the PAPER_SIGNAL population (research only; offline; no live change, no send).

Population: every CONTROL Signal of the given windows (signal_forensics datasets). T0 = actionable entry bar (first
1-min SIP bar at/after the Telegram SENT time). All rules decide ONLY from bars that have COMPLETED before the entry
(a bar's high/low/close/volume is known at bar end); entries fill at the next bar's OPEN, or at a stop LEVEL for
breakouts (buy-stop: max(bar open, level)). Exits: +15 / +30 / +60 min from the ACTUAL simulated entry (close of the last
bar completed by entry+h) and the session close; a horizon ending after the regular close is unresolved.
Cost: identical to the forensic -- max(V2 20 bps round trip, measured spread at T0). Long only; H4 is a
COUNTERFACTUAL_SHORT reversion REFERENCE (sign-flipped long return), never a trading instruction.

  H0  CONTROL            long at T0 open
  H1  PULLBACK(d, conf)  within 60 min: running high since T0 falls back >= d % (a completed bar's low); then
                         conf=PRIOR_HIGH: a completed bar closes above the previous bar's high -> long next open
                         conf=RECLAIM:    a completed bar closes above the pre-pullback running high -> long next open
                         d in {0.5, 1.0, 1.5, 2.0}
  H2  BREAKOUT(ref)      within 60 min, buy-stop above ref: T0_BAR = T0 bar high (from T0+1); RANGE5 = high of the first
                         5 post-T0 bars (from T0+5)
  H3  RVOL(k)            volume of the first 5 post-T0 bars vs 5 x mean 1-min volume of the 30 min before T0 >= k ->
                         long at T0+5 open; k in {1.5, 2.0, 3.0}
  H4  REVERSION_REF      counterfactual short at T0 open (research reference only)
H5 / H6 / DTU / liquidity / gap buckets are CONDITIONINGS of H0 (explanatory, not filters).
usage: python -m talonx_paperperf.alpha_hypotheses WINDOW_ID [WINDOW_ID ...]
"""
from __future__ import annotations

import collections as C
import gzip
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from talonx_paperperf import signal_forensics as F  # noqa: E402

OUT = REPO / "results" / "alpha_research"
UTC = timezone.utc
HS = ("15", "30", "60", "close")
WINDOW_MIN = 60
PULLBACKS = (0.5, 1.0, 1.5, 2.0)
RVOLS = (1.5, 2.0, 3.0)


def ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def iso(t):
    return t.astimezone(UTC).isoformat()


# ============================================================================================================ bars
def bars_for(wid: str, rows: list[dict]) -> dict[str, list[dict]]:
    p = OUT / f"bars_{wid}.json.gz"
    if p.exists():
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    from talonx_opportunity.phases import trading_window
    from datetime import date
    w = trading_window(date.fromisoformat(wid))
    start = min(ts(r["act_entry_utc"]) for r in rows if r.get("act_entry_utc")) - timedelta(minutes=40)
    bars, _ = F.fetch_bars([r["symbol"] for r in rows], start, w.close_utc - timedelta(seconds=1))
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(bars, fh)
    return bars


class Path_:
    """Bars of one symbol from T0 (regular session only) + the 30 min before T0."""
    def __init__(self, bars: list[dict], t0: datetime, close_utc: datetime):
        self.close = close_utc
        self.pre = [b for b in bars if t0 - timedelta(minutes=30) <= ts(b["t"]) < t0]
        self.post = [b for b in bars if t0 <= ts(b["t"]) < close_utc]

    def exits(self, te: datetime, pe: float, sign: float = 1.0) -> dict:
        """Returns for an entry at time te / price pe (sign -1 = counterfactual short)."""
        after = [b for b in self.post if ts(b["t"]) >= te]
        out = {}
        for h in ("15", "30", "60"):
            end = te + timedelta(minutes=int(h))
            if end > self.close:
                out[h] = None
                continue
            px = None
            for b in after:
                if ts(b["t"]) + timedelta(minutes=1) <= end:
                    px = float(b["c"])
            out[h] = None if px is None else sign * (px / pe - 1.0)
        out["close"] = sign * (float(after[-1]["c"]) / pe - 1.0) if after else None
        hi = max((float(b["h"]) for b in after), default=None)
        lo = min((float(b["l"]) for b in after), default=None)
        out["mfe"] = None if hi is None else (hi / pe - 1 if sign > 0 else 1 - lo / pe)
        out["mae"] = None if lo is None else (lo / pe - 1 if sign > 0 else 1 - hi / pe)
        return out


# ============================================================================================================ rules
def h0(p: Path_):
    return (ts(p.post[0]["t"]), float(p.post[0]["o"])) if p.post else None


def h1(p: Path_, depth: float, conf: str):
    run_hi, pulled, pre_hi = None, False, None
    post = p.post
    t0 = ts(post[0]["t"]) if post else None
    for i, b in enumerate(post):
        if ts(b["t"]) >= t0 + timedelta(minutes=WINDOW_MIN) or i + 1 >= len(post):
            return None
        h, low, c = float(b["h"]), float(b["l"]), float(b["c"])
        if not pulled:
            run_hi = h if run_hi is None else max(run_hi, h)
            if low <= run_hi * (1 - depth / 100):
                pulled, pre_hi = True, run_hi
            continue
        prev_hi = float(post[i - 1]["h"])
        if (conf == "PRIOR_HIGH" and c > prev_hi) or (conf == "RECLAIM" and c > pre_hi):
            nb = post[i + 1]                                   # decided at this bar's END -> next bar open
            return ts(nb["t"]), float(nb["o"])
    return None


def h2(p: Path_, ref: str):
    post = p.post
    if not post:
        return None
    t0 = ts(post[0]["t"])
    if ref == "T0_BAR":
        level, start = float(post[0]["h"]), 1
    else:
        if len(post) < 6:
            return None
        level, start = max(float(b["h"]) for b in post[:5]), 5
    for b in post[start:]:
        if ts(b["t"]) >= t0 + timedelta(minutes=WINDOW_MIN):
            return None
        if float(b["h"]) > level:                              # buy-stop fills at the level (or the open if gapped)
            return ts(b["t"]), max(float(b["o"]), level)
    return None


def h3(p: Path_, k: float):
    if len(p.post) < 6 or len(p.pre) < 10:
        return None
    base = statistics.mean(float(b["v"]) for b in p.pre)
    if base <= 0:
        return None
    rv = sum(float(b["v"]) for b in p.post[:5]) / (5 * base)
    return (ts(p.post[5]["t"]), float(p.post[5]["o"]), rv) if rv >= k else None


# ============================================================================================================ run
def simulate(rows: list[dict], bars: dict[str, list[dict]], close_utc_of) -> dict[str, list[dict]]:
    variants = {"H0_CONTROL": ("long", lambda p: h0(p))}
    for d in PULLBACKS:
        for c in ("PRIOR_HIGH", "RECLAIM"):
            variants[f"H1_PULLBACK_{d}_{c}"] = ("long", lambda p, d=d, c=c: h1(p, d, c))
    variants["H2_BREAKOUT_T0_BAR"] = ("long", lambda p: h2(p, "T0_BAR"))
    variants["H2_BREAKOUT_RANGE5"] = ("long", lambda p: h2(p, "RANGE5"))
    for k in RVOLS:
        variants[f"H3_RVOL_{k}"] = ("long", lambda p, k=k: (lambda r: r[:2] if r else None)(h3(p, k)))
    variants["H4_REVERSION_REF"] = ("short", lambda p: h0(p))
    out = {v: [] for v in variants}
    for r in rows:
        if not r.get("act_entry_utc"):
            continue
        p = Path_(bars.get(r["symbol"], []), ts(r["act_entry_utc"]), close_utc_of(r["window_id"]))
        for name, (side, fn) in variants.items():
            e = fn(p)
            rec = {k: r.get(k) for k in ("symbol", "window_id", "score", "spread_bps", "adv20_usd", "gap_pct",
                                          "catalyst", "catalyst_type", "shadow_state", "reference_price",
                                          "rvol_adv_fraction", "dtu_boundary")}
            rec["cost_frac"], rec["entered"] = r["cost_frac"], e is not None
            if e is not None:
                te, pe = e
                x = p.exits(te, pe, -1.0 if side == "short" else 1.0)
                rec.update({"act_entry_utc": iso(te), "entry_price": pe, "entry_delay_min": round(
                    (te - ts(r["act_entry_utc"])).total_seconds() / 60, 1), "act_mfe": x["mfe"], "act_mae": x["mae"]},
                           **{f"act_r{h}": x[h] for h in HS})
            out[name].append(rec)
    return out


def summarize(recs: list[dict]) -> dict:
    ent = [r for r in recs if r["entered"]]
    g = F.stats([r.get("act_r30") for r in ent])
    n = F.stats([F.net(r, "act", "30") for r in ent])
    port = F.portfolio(ent, "30") if ent else {}
    conc = F.concentration(ent, "30") if n.get("n") else {}
    return {"signals": len(recs), "entries": len(ent), "no_entry": len(recs) - len(ent),
            "entry_rate": round(len(ent) / len(recs), 3) if recs else None,
            "gross_30m": g, "net_30m": n, "median_net_30m": n.get("median_pct"),
            "gross_by_h": {h: F.stats([r.get(f"act_r{h}") for r in ent]).get("mean_pct") for h in HS},
            "net_by_h": {h: F.stats([F.net(r, "act", h) for r in ent]).get("mean_pct") for h in HS},
            "mfe": F.stats([r.get("act_mfe") for r in ent]), "mae": F.stats([r.get("act_mae") for r in ent]),
            "pnl_30m": port.get("NET_PNL"), "max_dd_30m": port.get("MAX_DRAWDOWN"),
            "top3_pp": conc.get("top_3_contribution_pct_points"),
            "mean_without_best3": conc.get("mean_without_best_3_pct"),
            "entry_delay_median_min": statistics.median([r["entry_delay_min"] for r in ent]) if ent else None}


def buckets(recs: list[dict], key) -> dict:
    g = C.defaultdict(list)
    for r in recs:
        if r["entered"]:
            g[key(r)].append(r)
    return {k: {"n": len(v), "gross_30m": F.stats([x.get("act_r30") for x in v]).get("mean_pct"),
                "net_30m": F.stats([F.net(x, "act", "30") for x in v]).get("mean_pct"),
                "median_gross_30m": F.stats([x.get("act_r30") for x in v]).get("median_pct"),
                "win": F.stats([F.net(x, "act", "30") for x in v]).get("win_rate")} for k, v in sorted(g.items())}


def tod(r):
    t = ts(r["act_entry_utc"])
    m = t.hour * 60 + t.minute - (13 * 60 + 30)
    return "1_opening_hour" if m < 60 else "2_late_morning" if m < 150 else "3_midday" if m < 270 else "4_late_session"


def cat(r):
    c = (r.get("catalyst") or "").lower()
    if c in ("", "none found"):
        return "none"
    if "8-k" in c and (r.get("catalyst_type") == "8-K_ONLY"):
        return "8-K_only"
    if "6-k" in c:
        return "6-K"
    if "insider" in c or ": 4" in c or ", 4" in c:
        return "form4/insider"
    return "other_sec"


def gapb(r):
    g = abs(r.get("gap_pct") or 0)
    return "a_<3" if g < 3 else "b_3-5" if g < 5 else "c_5-10" if g < 10 else "d_10-20" if g < 20 else "e_20+"


def paths(bars, rows, close_utc_of) -> dict:
    """H0 path ordering over the first 60 min after T0 and to the close."""
    first, t_mfe, t_mae, pb, resume = C.Counter(), [], [], [], C.Counter()
    for r in rows:
        if not r.get("act_entry_utc"):
            continue
        p = Path_(bars.get(r["symbol"], []), ts(r["act_entry_utc"]), close_utc_of(r["window_id"]))
        if not p.post:
            continue
        t0, e = ts(p.post[0]["t"]), float(p.post[0]["o"])
        win = [b for b in p.post if ts(b["t"]) < t0 + timedelta(minutes=WINDOW_MIN)]
        hi_b = max(win, key=lambda b: float(b["h"]))
        lo_b = min(win, key=lambda b: float(b["l"]))
        mfe, mae = float(hi_b["h"]) / e - 1, float(lo_b["l"]) / e - 1
        t_mfe.append((ts(hi_b["t"]) - t0).total_seconds() / 60)
        t_mae.append((ts(lo_b["t"]) - t0).total_seconds() / 60)
        first["MFE_FIRST" if hi_b["t"] < lo_b["t"] else "MAE_FIRST" if lo_b["t"] < hi_b["t"] else "SAME_BAR"] += 1
        run_hi, depth, pre = None, 0.0, None
        for b in win:
            run_hi = float(b["h"]) if run_hi is None else max(run_hi, float(b["h"]))
            d = 1 - float(b["l"]) / run_hi
            if d > depth:
                depth, pre = d, run_hi
        pb.append(100 * depth)
        for dd in PULLBACKS:
            if depth * 100 >= dd:
                idx = next(i for i, b in enumerate(win) if 1 - float(b["l"]) / max(float(x["h"]) for x in win[:i + 1])
                           >= dd / 100)
                later = win[idx + 1:]
                resume[f"pb{dd}_n"] += 1
                resume[f"pb{dd}_resumed_above_prior_high"] += any(float(b["h"]) > max(float(x["h"]) for x in win[:idx + 1])
                                                                  for b in later)
    n = sum(first.values())
    return {"n": n, "first_extreme_in_60m": dict(first),
            "minutes_to_MFE_median": statistics.median(t_mfe) if t_mfe else None,
            "minutes_to_MAE_median": statistics.median(t_mae) if t_mae else None,
            "max_pullback_60m_median_pct": round(statistics.median(pb), 3) if pb else None,
            "pullback_rates": {f"ge_{d}%": round(resume[f"pb{d}_n"] / n, 3) if n else None for d in PULLBACKS},
            "resumption_after_pullback": {f"{d}%": round(resume[f"pb{d}_resumed_above_prior_high"] /
                                                        resume[f"pb{d}_n"], 3) if resume[f"pb{d}_n"] else None
                                          for d in PULLBACKS}}


def main(wids: list[str]) -> dict:
    from talonx_opportunity.phases import trading_window
    from datetime import date
    rows, bars = [], {}
    for w in wids:
        rs = json.loads((F.OUT / f"{w}.json").read_text(encoding="utf-8"))["rows"]
        rows += rs
        for s, b in bars_for(w, rs).items():
            bars.setdefault(s, [])
            bars[s] += b
    close_of = {w: trading_window(date.fromisoformat(w)).close_utc for w in wids}
    sims = simulate(rows, bars, lambda w: close_of[w])
    res = {"windows": wids, "signals": len(rows), "hypotheses": {k: summarize(v) for k, v in sims.items()}}
    h0 = sims["H0_CONTROL"]
    res["H5_time_of_day"] = buckets(h0, tod)
    res["H6_catalyst"] = buckets(h0, cat)
    res["dtu_state"] = {name: buckets(v, lambda r: str(r.get("shadow_state")).split(":")[0])
                        for name, v in sims.items() if name in ("H0_CONTROL", "H4_REVERSION_REF", "H2_BREAKOUT_RANGE5",
                                                                "H1_PULLBACK_1.0_PRIOR_HIGH")}
    res["gap_buckets"] = {"H0": buckets(h0, gapb), "H4_REVERSION_REF": buckets(sims["H4_REVERSION_REF"], gapb),
                          "H0_mfe_mae": {k: {"mfe": F.stats([r["act_mfe"] for r in v if r["entered"]]).get("mean_pct"),
                                             "mae": F.stats([r["act_mae"] for r in v if r["entered"]]).get("mean_pct")}
                                         for k, v in C.defaultdict(list, {g: [r for r in h0 if gapb(r) == g]
                                                                          for g in {gapb(r) for r in h0}}).items()}}
    res["spread"] = buckets(h0, lambda r: F.bucket(r, "spread"))
    res["adv"] = buckets(h0, lambda r: F.bucket(r, "adv"))
    res["price"] = buckets(h0, lambda r: F.bucket(r, "price"))
    res["low_price_wide_spread_reversion"] = buckets(sims["H4_REVERSION_REF"], lambda r: (
        "lowprice_or_wide" if (r.get("reference_price") or 0) < 5 or (r.get("spread_bps") or 999) > 50 else "other"))
    res["paths"] = paths(bars, rows, lambda w: close_of[w])
    OUT.mkdir(parents=True, exist_ok=True)
    tag = "_".join(wids)
    (OUT / f"alpha_{tag}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res


if __name__ == "__main__":
    r = main(sys.argv[1:])
    for k, v in r["hypotheses"].items():
        print(f"{k:28s} n={v['entries']:3d}/{v['signals']} gross30 {v['gross_30m'].get('mean_pct')} net30 "
              f"{v['net_30m'].get('mean_pct')} med {v['median_net_30m']} win {v['net_30m'].get('win_rate')} pf "
              f"{v['net_30m'].get('profit_factor')} pnl {v['pnl_30m']} dd {v['max_dd_30m']} top3 {v['top3_pp']} "
              f"wo3 {v['mean_without_best3']} delay {v['entry_delay_median_min']}")
