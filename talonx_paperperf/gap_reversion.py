"""
LARGE_GAP_REVERSION_V1 -- PRE-REGISTERED research hypothesis (FROZEN 2026-09-30, before any outcome of this study).

Pre-registration: docs/research/preregistration/2026-09-30_large_gap_reversion_v1.md. Everything below is frozen by
that commit; a change is a NEW version with a new fingerprint (a test pins SPEC_FINGERPRINT).

RESEARCH_SHORT_REFERENCE = TRUE on every record. Price research only: no broker, no short orders, no Signal alerts,
no production change. Borrow availability / fees are NOT modelled (no free point-in-time source).
Pure logic only; the runner is talonx_paperperf/gap_reversion_run.py.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
HYPOTHESIS_ID = "LARGE_GAP_REVERSION"
VERSION = "LARGE_GAP_REVERSION_V1"
HYPOTHESIS = ("Stocks with a large positive opening gap (>= +10 % at the first regular-session print vs the prior "
              "regular-session close) mean-revert over the following 30 minutes after the open, rather than continue.")
RESEARCH_SHORT_REFERENCE = True

SPEC = {
    "hypothesis_id": HYPOTHESIS_ID, "version": VERSION, "hypothesis": HYPOTHESIS,
    "direction": "SHORT_REFERENCE (research only; return = -(exit/entry - 1))",
    "universe": "market.db universe ELIGIBLE members of window 2026-09-30 (structural US common-stock filter; "
                "currently listed -> SURVIVORSHIP CAVEAT, delisted names absent)",
    "periods": {"HISTORICAL": ["2024-01-02", "2026-09-25"], "HISTORICAL_HALVES_SPLIT": "2025-05-15",
                "CLUE_EXCLUDED": ["2026-09-28", "2026-09-29"], "FORWARD": "2026-09-30 onwards (shadow tracker)"},
    "floors_d_minus_1": {"min_close": 1.0, "min_adv20_usd": 1_000_000.0,
                         "note": "V1 hard floors (Opportunity Engine can see the name); ADV20 = mean(close*volume) of "
                                 "the 20 sessions ending D-1 (raw daily bars)"},
    "exclusions": ["SPLIT_DAY: raw/split-adjusted daily close ratio changes between D-1 and D by > 1 %",
                   "NO_OPEN_BAR: no 1-min bar starting exactly at the regular open",
                   "NO_PRIOR_CLOSE: no regular-session 1-min bar on D-1 in the last 30 minutes before its close",
                   "NO_ENTRY_BAR: no 1-min bar starting in [open+1m, open+10m)"],
    "gap": "gap = open(first regular 1-min bar, start == session open) / prior_close - 1; prior_close = close of the "
           "last 1-min bar STARTING before D-1's regular close (within its last 30 min). RAW (unadjusted) SIP bars.",
    "primary_population": "gap >= +10 %",
    "descriptive_buckets_pct": [[3, 5], [5, 10], [10, 20], [20, None]],
    "descriptive_sampling": "3-10 % buckets: deterministic 10 % sample (sha256(symbol|date) mod 10 == 0); >= 10 %: all",
    "entry_A_primary": "decision when the open bar has CLOSED (open + 1 min); entry = OPEN of the first 1-min bar "
                       "starting in [open+1m, open+10m)",
    "entry_B_confirmation": "scan CLOSED bars from open+1m; first bar whose close < the previous bar's low, among bars "
                            "starting < open+60m; entry = OPEN of the next bar (within 10 min)",
    "exits": {"primary": "+30m", "descriptive": ["+15m", "+60m", "session_close"],
              "rule": "close of the last 1-min bar completed by entry + h (never after the regular close); session "
                      "close = close of the last regular-session bar"},
    "cost": "STANDARD_TALONX: round trip = max(20 bps, measured SIP NBBO median quoted spread at entry, windows "
            "2/30/300 s) -- signal_forensics.quote_spread; unmeasured -> 20 bps flagged COST_PARTIAL. Borrow NOT "
            "modelled.",
    "lifecycle": "NOT the primary test: no authoritative short lifecycle exists in TalonX (V1 bearish geometry is a "
                 "long-contract artefact); not run in V1",
    "statistics": "n, mean, median, sd, se, t; bootstrap 95 % CI of the mean (10,000 resamples, seed 20260930) both "
                  "i.i.d. and DAY-CLUSTERED (resample event days)",
    "adequate_n": 200,
    "gates": {
        "PRICE_EDGE_PROMISING": "A +30m on the HISTORICAL period with n >= 200 AND gross mean > 0 AND standard net mean "
                                "> 0 AND PF(net) > 1 AND net mean after removing the best 3 > 0 AND net mean > 0 in "
                                "BOTH chronological halves AND net mean > 0 in >= 2 of the 3 calendar years",
        "UNSUPPORTED": "n >= 200 AND (gross mean <= 0 OR net mean <= 0 OR PF(net) <= 1)",
        "INCONCLUSIVE_FORWARD_TEST_REQUIRED": "anything else (small n, or positive but failing consistency / "
                                              "concentration)",
        "no_rescue": "no new threshold / score / time-of-day / catalyst filter from the same data",
    },
    "portfolio": "RESEARCH_SHORT_PORTFOLIO: $100k, $10k notional, max 10 concurrent, no leverage, A +30m exits, "
                 "standard net; borrow feasibility NOT implied",
    "dtu": "causal D-1: ACTIVE_CORE if ADV20 rank <= 1200 among floor-eligible names; else EVENT_PROMOTED_BY_GAP "
           "(a >= 10 % gapper crosses DTU_V1's 3 % trigger); V2 scope names OPERATOR_PROTECTED",
    "shortability": "Alpaca /v2/assets shortable / easy_to_borrow flags (CURRENT snapshot, not point-in-time) -> "
                    "SHORTABILITY_KNOWN_CURRENT or SHORTABILITY_UNKNOWN; no paid borrow data",
    "deployability": "NOT_ASSESSED in V1 (price edge only)",
}


def spec_fingerprint() -> str:
    return hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()[:16]


def _ts(s) -> datetime:
    return s if isinstance(s, datetime) else datetime.fromisoformat(str(s).replace("Z", "+00:00"))


# ============================================================================================================ gap
def prior_close(prev_bars: list[dict], prev_close_utc: datetime) -> float | None:
    rth = [b for b in prev_bars if prev_close_utc - timedelta(minutes=30) <= _ts(b["t"]) < prev_close_utc]
    return float(sorted(rth, key=lambda b: _ts(b["t"]))[-1]["c"]) if rth else None


def open_bar(bars: list[dict], open_utc: datetime) -> dict | None:
    return next((b for b in bars if _ts(b["t"]) == open_utc), None)


def gap(open_px: float | None, prev_close_px: float | None) -> float | None:
    if not open_px or not prev_close_px:
        return None
    return open_px / prev_close_px - 1.0


def in_sample(symbol: str, day: str, g: float) -> bool:
    """>= 10 %: always; 3-10 %: the frozen deterministic 10 % sample; < 3 %: never."""
    if g >= 0.10:
        return True
    if g >= 0.03:
        return int(hashlib.sha256(f"{symbol}|{day}".encode()).hexdigest(), 16) % 10 == 0
    return False


def bucket(g: float) -> str:
    for lo, hi in SPEC["descriptive_buckets_pct"]:
        if g * 100 >= lo and (hi is None or g * 100 < hi):
            return f"{lo}-{hi if hi else 'inf'}%"
    return "<3%"


def split_day(raw_prev: float, adj_prev: float, raw_d: float, adj_d: float) -> bool:
    try:
        return abs((raw_prev / adj_prev) / (raw_d / adj_d) - 1.0) > 0.01
    except ZeroDivisionError:
        return True


# ============================================================================================================ entries
def entry_A(bars: list[dict], open_utc: datetime) -> dict | None:
    lo, hi = open_utc + timedelta(minutes=1), open_utc + timedelta(minutes=10)
    return next((b for b in sorted(bars, key=lambda b: _ts(b["t"])) if lo <= _ts(b["t"]) < hi), None)


def entry_B(bars: list[dict], open_utc: datetime) -> dict | None:
    """First CLOSED bar (from open+1m, starting < open+60m) with close < previous bar's low -> next bar's open."""
    xs = sorted((b for b in bars if _ts(b["t"]) >= open_utc), key=lambda b: _ts(b["t"]))
    for i in range(1, len(xs)):
        b, prev = xs[i], xs[i - 1]
        if _ts(b["t"]) < open_utc + timedelta(minutes=1):
            continue
        if _ts(b["t"]) >= open_utc + timedelta(minutes=60):
            return None
        if float(b["c"]) < float(prev["l"]):
            done = _ts(b["t"]) + timedelta(minutes=1)
            return next((x for x in xs[i + 1:] if done <= _ts(x["t"]) < done + timedelta(minutes=10)), None)
    return None


def short_outcomes(bars: list[dict], entry_bar: dict, close_utc: datetime) -> dict:
    """Short-reference returns from the entry bar's open: +15/+30/+60 (close of the last bar completed by entry+h),
    session close; MFE/MAE for the short (favourable = price down) over the whole remaining session."""
    et, ep = _ts(entry_bar["t"]), float(entry_bar["o"])
    after = sorted((b for b in bars if et <= _ts(b["t"]) < close_utc), key=lambda b: _ts(b["t"]))
    out = {"entry_utc": et.isoformat(), "entry_px": ep}
    for h in (15, 30, 60):
        end = et + timedelta(minutes=h)
        px = None
        if end <= close_utc:
            for b in after:
                if _ts(b["t"]) + timedelta(minutes=1) <= end:
                    px = float(b["c"])
        out[f"r{h}"] = None if px is None else -(px / ep - 1.0)
    out["rclose"] = -(float(after[-1]["c"]) / ep - 1.0) if after else None
    if after:
        lo, hi = min(float(b["l"]) for b in after), max(float(b["h"]) for b in after)
        out["mfe_short"], out["mae_short"] = 1.0 - lo / ep, -(hi / ep - 1.0)
        peak, t_ext = ep, None
        for b in after:
            if float(b["h"]) > peak:
                peak, t_ext = float(b["h"]), (_ts(b["t"]) - et).total_seconds() / 60
        out["max_extension_above_entry"] = peak / ep - 1.0
        for d in (0.01, 0.02):
            hit = next((b for b in after if float(b["l"]) <= ep * (1 - d)), None)
            out[f"t_retrace_{int(d * 100)}pct_min"] = None if hit is None else (_ts(hit["t"]) - et).total_seconds() / 60
        first60 = [b for b in after if _ts(b["t"]) < et + timedelta(minutes=60)]
        out["continued_higher_first"] = bool(first60) and max(float(b["h"]) for b in first60) >= ep * 1.01 and (
            out["t_retrace_1pct_min"] is None or next(
                (i for i, b in enumerate(first60) if float(b["h"]) >= ep * 1.01), 10**9) <
            next((i for i, b in enumerate(first60) if float(b["l"]) <= ep * 0.99), 10**9))
    return out


# ============================================================================================================ stats
def describe(xs: list[float], seed: int = 20260930, groups: list | None = None) -> dict:
    xs2 = [x for x in xs if x is not None]
    n = len(xs2)
    if n < 2:
        return {"n": n}
    mu, sd = statistics.mean(xs2), statistics.stdev(xs2)
    se = sd / math.sqrt(n)
    rnd = random.Random(seed)
    boots = sorted(statistics.mean(rnd.choices(xs2, k=n)) for _ in range(10_000))
    out = {"n": n, "mean": mu, "median": statistics.median(xs2), "sd": sd, "se": se, "t": mu / se if se else None,
           "ci95_iid": [boots[249], boots[9749]]}
    if groups is not None:
        by = {}
        for x, g in zip(xs, groups):
            if x is not None:
                by.setdefault(g, []).append(x)
        keys = sorted(by)
        cb = []
        for _ in range(2_000):
            pick = rnd.choices(keys, k=len(keys))
            v = [x for k in pick for x in by[k]]
            cb.append(statistics.mean(v))
        cb.sort()
        out["ci95_day_clustered"] = [cb[49], cb[1949]]
    return out


def pf(xs: list[float]) -> float | None:
    w = [x for x in xs if x > 0]
    lo = [x for x in xs if x <= 0]
    return sum(w) / -sum(lo) if lo and sum(lo) < 0 else (math.inf if w else None)


def concentration(xs: list[float]) -> dict:
    s = sorted(xs, reverse=True)
    tot = sum(s)
    out = {"total": tot}
    for k in (1, 3, 5):
        out[f"top{k}_contribution"] = sum(s[:k])
        out[f"mean_without_best_{k}"] = (tot - sum(s[:k])) / (len(s) - k) if len(s) > k else None
    return out


def verdict(rows: list[dict], split: str = SPEC["periods"]["HISTORICAL_HALVES_SPLIT"]) -> dict:
    """rows: primary events (A, +30m) with 'day', 'gross30', 'net30' on the HISTORICAL period."""
    ok = [r for r in rows if r.get("net30") is not None]
    n = len(ok)
    g = [r["gross30"] for r in ok]
    x = [r["net30"] for r in ok]
    if n < SPEC["adequate_n"]:
        return {"verdict": "INCONCLUSIVE_FORWARD_TEST_REQUIRED", "reason": f"n={n} < {SPEC['adequate_n']}"}
    gm, nm, p = statistics.mean(g), statistics.mean(x), pf(x)
    if gm <= 0 or nm <= 0 or (p is not None and p <= 1):
        return {"verdict": "UNSUPPORTED", "reason": f"gross {gm:.5f} net {nm:.5f} PF {p}"}
    c = concentration(x)
    h1 = [r["net30"] for r in ok if r["day"] < split]
    h2 = [r["net30"] for r in ok if r["day"] >= split]
    yrs = {}
    for r in ok:
        yrs.setdefault(r["day"][:4], []).append(r["net30"])
    pos_years = sum(1 for v in yrs.values() if statistics.mean(v) > 0)
    cond = {"without_best_3_positive": (c["mean_without_best_3"] or 0) > 0,
            "both_halves_positive": bool(h1) and bool(h2) and statistics.mean(h1) > 0 and statistics.mean(h2) > 0,
            "years_positive_ge_2": pos_years >= 2}
    return {"verdict": "PRICE_EDGE_PROMISING" if all(cond.values()) else "INCONCLUSIVE_FORWARD_TEST_REQUIRED",
            "conditions": cond}
