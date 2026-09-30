"""
RELATIVE STRENGTH & MARKET CONTEXT ALPHA STUDY -- RS_ALPHA_V1 (PRE-REGISTERED, FROZEN 2026-09-30, BEFORE ANY OUTCOME).

Pre-registration: docs/research/preregistration/2026-10-01_relative_strength_alpha_study.md
Everything in this module is FROZEN by that registration commit: the hypothesis, the population rules, the SIC ->
benchmark mapping, the causal alignment rules, the six variants, the gates and the Phase B selection. A change is a
NEW hypothesis version with a new fingerprint (tests pin both SPEC_FINGERPRINT and MAPPING_HASH).

Pure logic only (no I/O): the Phase A runner (talonx_paperperf/rs_phase_a.py) wires stores and bars into these
functions. Research only -- no live change, no Telegram, no orders.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import statistics
from datetime import datetime, timedelta

# ============================================================================================================ identity
HYPOTHESIS_VERSION = "RS_ALPHA_V1"
HYPOTHESIS = ("Stocks exhibiting causal idiosyncratic outperformance versus market and sector benchmarks at "
              "candidate/event time have higher subsequent return expectancy than otherwise similar opportunities.")
MECHANISM_CLAIM = "NONE (relative strength is treated as predictive information, not proof of mechanism)"
PHASE_A_SESSIONS = ("2026-09-28", "2026-09-29")          # discovery data; 2026-09-30 is NOT used
PHASE_B_START = "2026-10-01"
PHASE_B_MIN_SESSIONS = 10

# ============================================================================================================ population
POPULATION = {
    "source": "opportunity.db candidate_events (discovery output, UPSTREAM of promotion; not PAPER_SIGNAL)",
    "event_types": ["NEW", "UPGRADE", "MATERIAL_UPDATE"],
    "to_states": ["WATCH", "BULLISH_SETUP", "BEARISH_SETUP"],      # every direction; the outcome is long-only
    "t0": "candidate_events.at_utc (event decision time)",
    "dtu_states": ["ACTIVE_CORE", "EVENT_PROMOTED"],                # at t0; anything else is OUT_OF_DTU
    "dtu_core_n": 1200,
    "dtu_gap_trigger_abs_pct": 3.0,
    "dtu_sec_8k_ttl_sessions": 3,
    "rth_only": "primary lookback start (endpoint - 15 min) >= regular open; entry + 30 min <= regular close",
    "primary_observation": "FIRST qualifying event per (symbol, session) by (t0, seq); later same-session events are "
                           "descriptive only and never independent primary trades",
}
DTU_RECONSTRUCTION = {
    "2026-09-28": {"core": "universe_snapshot_2026-09-28.csv (D-1 = 2026-09-25): top 1200 by adv20_usd among "
                           "v1_floor_eligible (ties by symbol)",
                   "gap": "first scan observation (near_misses SCORED + candidate_events gap_pct) with |gap| >= 3% "
                          "at decision time <= t0 (DTU study replay; TTL rest of window)",
                   "sec_8k": "8-K* filed on a session d < D with idx(D) - idx(d) < 3 (EDGAR daily index, D-1 batch); "
                             "same-day 8-Ks are NOT reconstructable intraday -> reported coverage gap"},
    "2026-09-29": {"core": "results/dtu_shadow/shadow.db snapshot is_shadow_core=1 (built from D-1 = 2026-09-28)",
                   "gap": "shadow promotions GAP_TRIGGER first_at_utc <= t0 (live delayed_sip sweep)",
                   "sec_8k": "shadow promotions SEC_8K first_at_utc <= t0 + D-1 batch carry-in as above"},
    "forbidden": "no 2026-09-30+ state classifies 2026-09-28/29",
}

# ============================================================================================================ benchmarks
SECTOR_MAPPING_VERSION = "SIC_ETF_MAP_V1"
SECTOR_MAP = (                                   # (sic_lo, sic_hi inclusive, ETF); ranges never overlap
    (1000, 1499, "XLE"),
    (2830, 2836, "XBI"),
    (2900, 2999, "XLE"),
    (3570, 3579, "XLK"),
    (3600, 3699, "XLI"),
    (3700, 3799, "XLI"),
    (3840, 3851, "XLV"),
    (6000, 6799, "XLF"),
    (7370, 7379, "XLK"),
)
DEFAULT_BENCHMARK = "SPY"                        # every unmapped / unknown SIC
SIC_SOURCE = "EDGAR submissions JSON (data.sec.gov/submissions/CIK##########.json 'sic'), CIK from market.db universe"
BENCHMARK_HIERARCHY = {"PRIMARY": "SECTOR_ETF (deterministic SIC map)", "SECONDARY": "SPY",
                       "DIAGNOSTIC": ["QQQ", "DTU_CORE_EW (D-1 frozen Core membership only)"]}
ETFS = tuple(sorted({e for *_, e in SECTOR_MAP} | {"SPY", "QQQ"}))


def sector_benchmark(sic) -> str:
    """One SIC -> exactly one benchmark; no dynamic choice. Unknown / unparseable -> SPY."""
    try:
        s = int(str(sic).strip())
    except (TypeError, ValueError):
        return DEFAULT_BENCHMARK
    for lo, hi, etf in SECTOR_MAP:
        if lo <= s <= hi:
            return etf
    return DEFAULT_BENCHMARK


def mapping_artifact() -> dict:
    return {"version": SECTOR_MAPPING_VERSION, "default": DEFAULT_BENCHMARK,
            "ranges": [{"sic_lo": lo, "sic_hi": hi, "benchmark": e} for lo, hi, e in SECTOR_MAP]}


def mapping_hash() -> str:
    return hashlib.sha256(json.dumps(mapping_artifact(), sort_keys=True).encode()).hexdigest()[:16]


# ============================================================================================================ causality
FEATURE_VIEWS = {
    "ENGINE_VIEW": "PRIMARY. endpoint = event data_as_of_utc (the 15-min delayed SIP the engine saw; TalonX's data "
                   "contract). The only view an unpaid live implementation could compute.",
    "WALLCLOCK_VIEW": "DIAGNOSTIC ONLY (never gates, never promotes). endpoint = t0; needs real-time data.",
}
LOOKBACKS_MIN = (5, 15, 30)
PRIMARY_LOOKBACK_MIN = 15
STALE_MAX_MIN = 5                     # a price is the close of the last 1-min bar CLOSED by x, and that bar closed >= x-5m
ALIGNMENT = ("stock endpoint E* = close time of the stock's last bar closed by the view endpoint; stock start S* = close "
             "time of the stock's last bar closed by E*-L; every benchmark is priced at bars closed by E* and by S* "
             "(never newer than the stock bar); missing / stale (> 5 min) -> the feature is MISSING, never filled")
RVOL_DEF = "RVOL_15m = stock volume of bars closing in (E*-15m, E*] / (D-1 ADV20 shares x 15/390)"
SPREAD_ELIGIBILITY_DEF = ("RS-5 spread-to-price = median SIP NBBO (ask-bid)/mid in [E*-w, E*], w in (2, 30, 300) s "
                          "(backward-looking); unmeasured -> fails RS-5")


def _t(s) -> datetime:
    return s if isinstance(s, datetime) else datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def _end(b: dict) -> datetime:
    return _t(b["t"]) + timedelta(minutes=1)


def price_closed_by(bars: list[dict], x: datetime, stale_min: int = STALE_MAX_MIN):
    """(close, bar_close_time) of the last 1-min bar that CLOSED at or before x (bar start + 1 min <= x) and closed
    no earlier than x - stale_min; else (None, None). bars: [{'t': start (iso or datetime), 'c': close}] sorted by t."""
    i = bisect.bisect_right(bars, x, key=_end) - 1
    if i < 0:
        return None, None
    end = _end(bars[i])
    if end < x - timedelta(minutes=stale_min):
        return None, None
    return float(bars[i]["c"]), end


def aligned_return(stock_bars: list[dict], bench: dict[str, list[dict]], endpoint: datetime, lookback_min: int,
                   session_open: datetime) -> dict | None:
    """Stock return over its own last causal interval [S*, E*] and every benchmark over the SAME interval.
    None when the stock cannot be priced causally or the lookback leaves the regular session."""
    pe, e_star = price_closed_by(stock_bars, endpoint)
    if pe is None:
        return None
    s_target = e_star - timedelta(minutes=lookback_min)
    if s_target < session_open:
        return None
    ps, s_star = price_closed_by(stock_bars, s_target)
    if ps is None or ps <= 0:
        return None
    out = {"e_star": e_star, "s_star": s_star, "stock": pe / ps - 1.0, "bench": {}}
    for name, bb in bench.items():
        b1, t1 = price_closed_by(bb, e_star)
        b0, t0 = price_closed_by(bb, s_star)
        out["bench"][name] = (b1 / b0 - 1.0) if b1 is not None and b0 else None
        assert t1 is None or t1 <= e_star        # a benchmark bar is never newer than the stock bar
    return out


def core_index_return(core_bars: dict[str, list[dict]], s_star: datetime, e_star: datetime) -> tuple[float | None, float]:
    """Equal-weight return of the D-1 frozen Core over [S*, E*]: constituents with valid causal prices at BOTH
    endpoints only (no forward fill). Returns (return, coverage fraction of the membership)."""
    if not core_bars:
        return None, 0.0
    rs = []
    for bars in core_bars.values():
        p1, _ = price_closed_by(bars, e_star)
        p0, _ = price_closed_by(bars, s_star)
        if p1 is not None and p0:
            rs.append(p1 / p0 - 1.0)
    cov = len(rs) / len(core_bars)
    return (statistics.mean(rs) if rs else None), cov


def rs_features(al: dict, sector_etf: str) -> dict:
    """sector_excess = R_stock - R_sectorETF; market_excess = R_stock - R_SPY; rs_ratio = (1+R_stock)/(1+R_sector).
    No beta adjustment in Phase A."""
    r = al["stock"]
    sec, spy, qqq = al["bench"].get(sector_etf), al["bench"].get("SPY"), al["bench"].get("QQQ")
    core = al["bench"].get("DTU_CORE_EW")
    return {"stock_ret": r, "sector_ret": sec, "spy_ret": spy,
            "sector_excess": None if sec is None else r - sec,
            "market_excess": None if spy is None else r - spy,
            "qqq_excess": None if qqq is None else r - qqq,
            "core_excess": None if core is None else r - core,
            "rs_ratio": None if sec is None or sec <= -1 else (1.0 + r) / (1.0 + sec)}


def rvol_15m(stock_bars: list[dict], e_star: datetime, adv20_sh) -> float | None:
    if not adv20_sh or adv20_sh <= 0:
        return None
    lo = e_star - timedelta(minutes=15)
    v = sum(float(b.get("v") or 0) for b in stock_bars if lo < _t(b["t"]) + timedelta(minutes=1) <= e_star)
    return v / (float(adv20_sh) * 15.0 / 390.0)


# ============================================================================================================ outcome / cost
ENTRY = "open of the first 1-min SIP bar starting in [ceil_minute(t0), +10 min) (the forensic's actionable rule)"
PRIMARY_EXIT = "+30m"                               # close of the last bar completed by entry + 30 min
DESCRIPTIVE_EXITS = ("+15m", "+60m", "session_close")
COST_MODEL_VERSION = "PAPERPERF_FORENSIC_COST_V1"
COST_MODEL = {"formula": "round_trip_cost = max(friction_bps, measured_entry_spread_bps) / 1e4",
              "friction_bps": 20.0, "friction_source": "talonx_v2/config.py friction_bps (V2 research friction)",
              "spread": "median SIP NBBO quoted spread (bps of mid) in [entry, entry + w], w in (2, 30, 300) s -- "
                        "talonx_paperperf.signal_forensics.quote_spread",
              "quote_windows_s": [2, 30, 300], "unmeasured": "friction only, flagged COST_PARTIAL"}


def cost_frac(spread_bps) -> float:
    return max(COST_MODEL["friction_bps"], spread_bps if spread_bps is not None else 0.0) / 1e4


def cost_model_hash() -> str:
    return hashlib.sha256(json.dumps({"v": COST_MODEL_VERSION, **COST_MODEL}, sort_keys=True).encode()).hexdigest()[:16]


# ============================================================================================================ observations
def primary_observations(events: list[dict]) -> list[dict]:
    """events: qualifying rows with symbol, session, t0, seq. First per (symbol, session) by (t0, seq)."""
    first: dict[tuple, dict] = {}
    for e in sorted(events, key=lambda e: (e["session"], e["symbol"], str(e["t0"]), e.get("seq") or 0)):
        first.setdefault((e["symbol"], e["session"]), e)
    return sorted(first.values(), key=lambda e: (e["session"], str(e["t0"]), e["symbol"]))


def core_membership(d1_rows: list[dict], n: int = POPULATION["dtu_core_n"]) -> set[str]:
    """D-1 FROZEN Core: top n by adv20_usd among V1-floor-eligible rows of the D-1 snapshot (ties by symbol).
    Built once per session before the open; nothing observed on the session day can enter."""
    ok = [r for r in d1_rows if r.get("v1_floor_eligible") and r.get("adv20_usd") is not None]
    ok.sort(key=lambda r: (-float(r["adv20_usd"]), r["symbol"]))
    return {r["symbol"] for r in ok[:n]}


def dtu_state_at(symbol: str, t0: str, core: set[str], promotions: dict[str, list[tuple[str, str | None, str]]]) -> str:
    """ACTIVE_CORE | EVENT_PROMOTED:<reason> | OUT_OF_DTU. promotions: symbol -> [(start_utc, expires_utc|None,
    reason)]; a promotion counts only if it started at or before t0 and had not expired."""
    if symbol in core:
        return "ACTIVE_CORE"
    for a, b, why in sorted(promotions.get(symbol, ())):
        if str(a) <= str(t0) and (b is None or str(t0) < str(b)):
            return f"EVENT_PROMOTED:{why}"
    return "OUT_OF_DTU"


# ============================================================================================================ variants
VARIANTS = (
    {"id": "RS-1", "name": "MARKET EXCESS", "long_candidate": True, "complexity": 1,
     "rule": [("market_excess", ">=", 0.015)]},
    {"id": "RS-2", "name": "SECTOR EXCESS", "long_candidate": True, "complexity": 1,
     "rule": [("sector_excess", ">=", 0.015)]},
    {"id": "RS-3", "name": "DIVERGENT ALPHA", "long_candidate": True, "complexity": 2,
     "rule": [("stock_ret", ">=", 0.020), ("spy_ret", "<=", 0.0)]},
    {"id": "RS-4", "name": "VOLUME-CONFIRMED SECTOR RS", "long_candidate": True, "complexity": 2,
     "rule": [("sector_excess", ">=", 0.015), ("rvol_15m", ">=", 2.0)]},
    {"id": "RS-5", "name": "LOW-FRICTION SECTOR RS", "long_candidate": True, "complexity": 2,
     "rule": [("sector_excess", ">=", 0.015), ("spread_to_price", "<=", 0.010)]},
    {"id": "RS-6", "name": "DIAGNOSTIC REVERSION (COUNTERFACTUAL ONLY)", "long_candidate": False, "complexity": 1,
     "rule": [("sector_excess", "<=", -0.020)]},
)
VARIANT_FEATURES_LOOKBACK_MIN = 15                  # every rule feature is the 15-min ENGINE_VIEW feature


def variant_pass(v: dict, feat: dict) -> bool:
    """A missing feature is UNKNOWN_DATA and never passes."""
    for k, op, thr in v["rule"]:
        x = feat.get(k)
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return False
        if op == ">=" and not x >= thr:
            return False
        if op == "<=" and not x <= thr:
            return False
    return True


# ============================================================================================================ metrics
POSITION_USD = 10_000.0


def metrics(trades: list[tuple[float, float]]) -> dict:
    """trades: [(gross_frac, net_frac)] at the PRIMARY exit. PF / win rate on NET (the forensic's convention)."""
    n = len(trades)
    if n == 0:
        return {"n": 0}
    g = [t[0] for t in trades]
    x = [t[1] for t in trades]
    wins, losses = [v for v in x if v > 0], [v for v in x if v <= 0]
    tot_g = sum(g)
    srt = sorted(range(n), key=lambda i: g[i], reverse=True)
    rest = [i for i in range(n) if i not in set(srt[:3])]
    top1 = g[srt[0]]
    return {"n": n, "gross_mean": statistics.mean(g), "gross_median": statistics.median(g),
            "net_mean": statistics.mean(x), "net_median": statistics.median(x),
            "win_rate": len(wins) / n,
            "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else (math.inf if wins else None),
            "gross_pnl_usd": POSITION_USD * tot_g, "net_pnl_usd": POSITION_USD * sum(x),
            "top1_share_of_gross": (top1 / tot_g) if tot_g > 0 else None,
            "top3_share_of_gross": (sum(g[i] for i in srt[:3]) / tot_g) if tot_g > 0 else None,
            "top3_removed_gross_mean": statistics.mean(g[i] for i in rest) if rest else None,
            "top3_removed_net_mean": statistics.mean(x[i] for i in rest) if rest else None}


def spearman(xs: list[float], ys: list[float]) -> float | None:
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    if len(xs) < 3:
        return None
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


# ============================================================================================================ quintiles
QUINTILE_KEY = "sector_excess"                      # 15-min ENGINE_VIEW primary RS
QUINTILE_RULE = ("primary observations with a valid 15-min sector_excess AND a resolved +30m outcome, sorted by "
                 "(sector_excess, session, symbol); quintile = floor(5 * rank / N) + 1 (Q1 lowest RS)")
GRADIENT_GATE = ("PASS iff ALL: (1) Spearman(quintile number, quintile mean +30m gross) > 0; (2) Q5 mean gross > Q1 "
                 "mean gross; (3) Q5 mean net > 0. Literal monotonicity is NOT required.")


def assign_quintiles(obs: list[dict], key: str = QUINTILE_KEY) -> dict[int, list[dict]]:
    xs = sorted((o for o in obs if o.get(key) is not None), key=lambda o: (o[key], o["session"], o["symbol"]))
    n = len(xs)
    q: dict[int, list[dict]] = {k: [] for k in range(1, 6)}
    for i, o in enumerate(xs):
        q[min(5, 5 * i // n + 1)].append(o)
    return q


def gradient_gate(qstats: dict[int, dict]) -> dict:
    if any(qstats.get(k, {}).get("n", 0) == 0 for k in range(1, 6)):
        return {"spearman": None, "q5_minus_q1_gross": None, "pass": False, "reason": "EMPTY_QUINTILE"}
    means = [qstats[k]["gross_mean"] for k in range(1, 6)]
    rho = spearman([1, 2, 3, 4, 5], means)
    d = qstats[5]["gross_mean"] - qstats[1]["gross_mean"]
    ok = rho is not None and rho > 0 and d > 0 and qstats[5]["net_mean"] > 0
    return {"spearman": rho, "q5_minus_q1_gross": d, "q5_net": qstats[5]["net_mean"], "pass": ok,
            "conditions": {"spearman_gt_0": rho is not None and rho > 0, "q5_gt_q1_gross": d > 0,
                           "q5_net_gt_0": qstats[5]["net_mean"] > 0}}


# ============================================================================================================ score test
SCORE_BANDS = ((0, 50), (50, 60), (60, 70), (70, 80), (80, 1000))   # candidate_events.score at t0
SCORE_TEST = ("within each band: HIGH_RS = sector_excess >= band median, LOW_RS = below; delta = mean +30m gross HIGH "
              "- LOW; bands need >= 10 per side. Weighted delta = sum(n_b * delta_b) / sum(n_b). OLS gross30 ~ 1 + "
              "z(score) + z(sector_excess): t of the RS coefficient. YES iff weighted delta > 0 AND t >= 2; NO "
              "(REDUNDANT_FEATURE) iff weighted delta <= 0 OR t < 1; else INCONCLUSIVE; < 2 usable bands -> "
              "INCONCLUSIVE.")
SCORE_MIN_PER_SIDE = 10


def _ols_t(y: list[float], cols: list[list[float]], j: int) -> float | None:
    """t-stat of coefficient j of y ~ 1 + cols (classic OLS SE). Small dense solve; no external dependency."""
    n, k = len(y), len(cols) + 1
    if n <= k + 1:
        return None
    X = [[1.0] + [c[i] for c in cols] for i in range(n)]
    XtX = [[sum(X[r][a] * X[r][b] for r in range(n)) for b in range(k)] for a in range(k)]
    Xty = [sum(X[r][a] * y[r] for r in range(n)) for a in range(k)]
    # invert XtX (Gauss-Jordan)
    A = [row[:] + [1.0 if i == j2 else 0.0 for j2 in range(k)] for i, row in enumerate(XtX)]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(A[r][c]))
        if abs(A[p][c]) < 1e-12:
            return None
        A[c], A[p] = A[p], A[c]
        pv = A[c][c]
        A[c] = [v / pv for v in A[c]]
        for r in range(k):
            if r != c:
                f = A[r][c]
                A[r] = [a - f * b for a, b in zip(A[r], A[c])]
    inv = [row[k:] for row in A]
    beta = [sum(inv[a][b] * Xty[b] for b in range(k)) for a in range(k)]
    resid = [y[i] - sum(beta[a] * X[i][a] for a in range(k)) for i in range(n)]
    s2 = sum(r * r for r in resid) / (n - k)
    se = math.sqrt(s2 * inv[j + 1][j + 1]) if s2 * inv[j + 1][j + 1] > 0 else None
    return beta[j + 1] / se if se else None


def _z(v: list[float]) -> list[float]:
    m, s = statistics.mean(v), statistics.pstdev(v)
    return [(x - m) / s if s else 0.0 for x in v]


def incremental_to_score(obs: list[dict]) -> dict:
    """obs: primary observations with score, sector_excess, gross30."""
    rows = [o for o in obs if o.get("score") is not None and o.get("sector_excess") is not None
            and o.get("gross30") is not None]
    bands, num, den = [], 0.0, 0
    for lo, hi in SCORE_BANDS:
        b = [o for o in rows if lo <= o["score"] < hi]
        if not b:
            continue
        med = statistics.median(o["sector_excess"] for o in b)
        hi_rs = [o["gross30"] for o in b if o["sector_excess"] >= med]
        lo_rs = [o["gross30"] for o in b if o["sector_excess"] < med]
        usable = len(hi_rs) >= SCORE_MIN_PER_SIDE and len(lo_rs) >= SCORE_MIN_PER_SIDE
        d = (statistics.mean(hi_rs) - statistics.mean(lo_rs)) if hi_rs and lo_rs else None
        bands.append({"score_band": f"[{lo},{hi if hi < 1000 else 'max'})", "high_RS_n": len(hi_rs),
                      "low_RS_n": len(lo_rs), "high_RS_forward_return": statistics.mean(hi_rs) if hi_rs else None,
                      "low_RS_forward_return": statistics.mean(lo_rs) if lo_rs else None, "delta": d,
                      "usable": usable})
        if usable:
            num += (len(hi_rs) + len(lo_rs)) * d
            den += len(hi_rs) + len(lo_rs)
    wd = num / den if den else None
    t = _ols_t([o["gross30"] for o in rows], [_z([o["score"] for o in rows]), _z([o["sector_excess"] for o in rows])],
               1) if len(rows) > 5 else None
    n_usable = sum(1 for b in bands if b["usable"])
    if n_usable < 2 or wd is None or t is None:
        ans = "INCONCLUSIVE"
    elif wd > 0 and t >= 2.0:
        ans = "YES"
    elif wd <= 0 or t < 1.0:
        ans = "NO"
    else:
        ans = "INCONCLUSIVE"
    return {"bands": bands, "weighted_delta": wd, "ols_t_rs_given_score": t, "usable_bands": n_usable,
            "answer": ans, "flag": "REDUNDANT_FEATURE" if ans == "NO" else None}


# ============================================================================================================ gates
MIN_N = 40
MAX_TOP1_SHARE = 0.20
STRONG_GROSS_MIN = 0.0035                          # +0.35 % -- REQUIRED for Phase B in this study


def minimum_gate(m: dict, gradient_pass: bool) -> dict:
    c = {"gross_gt_0": (m.get("gross_mean") or 0) > 0,
         "net_gt_0": (m.get("net_mean") or 0) > 0,
         "pf_gt_1": m.get("profit_factor") is not None and m["profit_factor"] > 1.0,
         "n_ge_40": m.get("n", 0) >= MIN_N,
         "top1_le_20pct": m.get("top1_share_of_gross") is not None and m["top1_share_of_gross"] <= MAX_TOP1_SHARE,
         "positive_after_top3_removed": (m.get("top3_removed_net_mean") or 0) > 0,
         "quintile_gradient_pass": bool(gradient_pass)}
    return {"pass": all(c.values()), "conditions": c}


def strong_gate(m: dict, gradient_pass: bool) -> dict:
    mg = minimum_gate(m, gradient_pass)
    ok = mg["pass"] and (m.get("gross_mean") or 0) >= STRONG_GROSS_MIN
    return {"pass": ok, "minimum": mg["pass"], "gross_ge_035": (m.get("gross_mean") or 0) >= STRONG_GROSS_MIN}


def classify_variant(v: dict, m: dict, gradient_pass: bool) -> str:
    if not v["long_candidate"]:
        return "DIAGNOSTIC_ONLY"
    s = strong_gate(m, gradient_pass)
    if s["pass"]:
        return "PASSES_STRONG_GATE"
    if s["minimum"]:
        return "INTERESTING_BUT_INSUFFICIENT"     # gross > 0 but < +0.35 %: never forward-registered
    return "FAILS_MINIMUM"


def select_phase_b(results: list[dict]) -> tuple[str | None, str]:
    """results: [{'variant': VARIANTS item, 'metrics': ..., 'status': classify_variant(...)}]. At most ONE: long
    candidates passing the strong gate, by (net desc, N desc, top-3 share asc, complexity asc, id)."""
    ok = [r for r in results if r["variant"]["long_candidate"] and r["status"] == "PASSES_STRONG_GATE"]
    if not ok:
        return None, "NO_VARIANT_PASSES_THE_STRONG_GATE"
    ok.sort(key=lambda r: (-r["metrics"]["net_mean"], -r["metrics"]["n"],
                           r["metrics"]["top3_share_of_gross"] if r["metrics"]["top3_share_of_gross"] is not None
                           else math.inf, r["variant"]["complexity"], r["variant"]["id"]))
    w = ok[0]
    why = (f"{w['variant']['id']}: highest net expectancy among {len(ok)} strong-gate variant(s)"
           if len(ok) > 1 else f"{w['variant']['id']}: the only variant passing the strong gate")
    return w["variant"]["id"], why


# ============================================================================================================ verdict
MIN_QUINTILE_OBS = 250                              # < 50 per quintile -> INCONCLUSIVE
MIN_BENCHMARK_COVERAGE = 0.90


def verdict(n_quintile_obs: int, bench_coverage: float, gradient_pass: bool, statuses: dict[str, str],
            phase_b: str | None) -> str:
    if n_quintile_obs < MIN_QUINTILE_OBS or bench_coverage < MIN_BENCHMARK_COVERAGE:
        return "INCONCLUSIVE"
    if phase_b:
        return "PROMOTE_TO_FORWARD"
    if gradient_pass and any(s == "INTERESTING_BUT_INSUFFICIENT" for s in statuses.values()):
        return "INCONCLUSIVE"
    return "UNSUPPORTED"


# ============================================================================================================ fingerprint
def spec() -> dict:
    return {"hypothesis_version": HYPOTHESIS_VERSION, "hypothesis": HYPOTHESIS, "mechanism": MECHANISM_CLAIM,
            "phase_a_sessions": PHASE_A_SESSIONS, "phase_b": {"start": PHASE_B_START, "min_sessions": PHASE_B_MIN_SESSIONS},
            "population": POPULATION, "dtu_reconstruction": DTU_RECONSTRUCTION,
            "mapping": mapping_artifact(), "mapping_hash": mapping_hash(), "sic_source": SIC_SOURCE,
            "benchmarks": BENCHMARK_HIERARCHY, "views": FEATURE_VIEWS, "lookbacks": LOOKBACKS_MIN,
            "primary_lookback": PRIMARY_LOOKBACK_MIN, "stale_max_min": STALE_MAX_MIN, "alignment": ALIGNMENT,
            "rvol": RVOL_DEF, "spread_eligibility": SPREAD_ELIGIBILITY_DEF, "entry": ENTRY,
            "primary_exit": PRIMARY_EXIT, "descriptive_exits": DESCRIPTIVE_EXITS,
            "cost_model_version": COST_MODEL_VERSION, "cost_model": COST_MODEL, "variants": VARIANTS,
            "quintile": {"key": QUINTILE_KEY, "rule": QUINTILE_RULE, "gate": GRADIENT_GATE},
            "score_test": {"bands": SCORE_BANDS, "rule": SCORE_TEST},
            "gates": {"min_n": MIN_N, "max_top1_share": MAX_TOP1_SHARE, "strong_gross_min": STRONG_GROSS_MIN},
            "verdict": {"min_quintile_obs": MIN_QUINTILE_OBS, "min_benchmark_coverage": MIN_BENCHMARK_COVERAGE}}


def spec_fingerprint() -> str:
    return hashlib.sha256(json.dumps(spec(), sort_keys=True, default=list).encode()).hexdigest()[:16]
