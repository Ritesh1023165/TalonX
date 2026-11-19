"""
VR_PAPER_V1 -- virtual-realtime intraday PAPER lifecycle for Opportunity-Engine PAPER_SIGNALs (research; no broker).

Two result streams, never mixed (paper_mode):
  VIRTUAL_REALTIME  the delayed market-data timestamp IS the clock. At virtual time T only bars that CLOSED at or
                    before T are visible (VirtualClock). Decision time M = the Signal's data_as_of_utc (every bar the
                    engine used closed at or before it). Entry = OPEN of the first 1-min bar starting at/after M
                    (the next executable price after the decision; never a bar that was already closed).
  ACTIONABLE        entry = OPEN of the first 1-min bar starting at/after the Telegram SENT time (the forensic's
                    actionable rule, unchanged). Same stop/target levels (captured at the Signal, V1 semantics).

AUTHORITATIVE CONTRACT CHECK (2026-09-30): the Opportunity Engine has NO stop / target / position lifecycle (its
outcome model is fixed-horizon: +30m CONFIRMED/FAILED). The only intraday paper lifecycle in TalonX is the Original V1
(archived baseline) Quant -> paper engine. This baseline REUSES it, unmodified, and labels itself RESEARCH_BASELINE:
  stop / target  talonx_quant.strategy.calculate_trade_geometry with QuantConfig defaults: stop = prior-session S1
                 pivot if below price else price - 1.5 x ATR; target = prior-session R1 pivot if above price else
                 price + 2.0 x ATR. ATR = pandas_ta ATR(14) (Wilder) on the 1-min bars visible at M (spanning the
                 pre-open like V1). Pivots = classic P/R1/S1 from the prior REGULAR session's 1-min high/low/close.
  RRR            reported (reward/risk to the structural target); V1's >= 1.5 R:R gate is a V1 SIGNAL gate and is NOT
                 applied -- CONTROL eligibility is never altered.
  time exit      V1 EOD flatten 15:50 ET -> SESSION_CLOSE at the close of the last bar ending by 15:50 ET. No other
                 authoritative intraday time exit exists (TIME_EXIT unused).
  fills          bar-based: stop checked before target within a bar (V1 tiebreak); fill at the level, or at the bar
                 OPEN if the bar opened beyond it (gap). Entry-bar high/low count after the open fill.
  cost           max(V2 friction 20 bps, measured SIP NBBO spread at the entry time) -- the profitability contract.
  capital        $100k, $10k per position (fractional shares, as talonx_paper.engine.calculate_buy), max 10 open,
                 cash reserved at entry and released at exit; no leverage.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
VR_PAPER_VERSION = "VR_PAPER_V1"
POLICY = {
    "version": VR_PAPER_VERSION, "label": "RESEARCH_BASELINE (no authoritative Opportunity-Engine lifecycle exists)",
    "geometry": "talonx_quant.strategy.calculate_trade_geometry, QuantConfig defaults (atr_stop 1.5, atr_reward 2.0)",
    "atr": "pandas_ta atr(length=14) on visible 1-min bars", "pivots": "prior regular session classic P/R1/S1",
    "vr_decision_time": "signal data_as_of_utc", "vr_entry": "open of first 1-min bar starting >= decision time",
    "actionable_entry": "open of first 1-min bar starting >= ceil_minute(Telegram sent)",
    "entry_window_min": 10, "premarket_decision": "entry deferred to the first regular-session bar",
    "flatten_et": "15:50", "intrabar": "stop before target; fill at level or gap open",
    "cost": "max(20 bps, measured entry spread)", "capital": {"start": 100_000, "position": 10_000, "max_open": 10},
    "pullback_v1": {"depths_pct": [0.5, 1.0, 1.5], "confirmations": ["RECLAIM_PRIOR_BAR_HIGH", "CLOSE_ABOVE_SMA5"],
                    "watch_min": 60},
    "reversion_v1": {"gap_buckets_pct": [[3, 5], [5, 10], [10, 20], [20, 1e9]], "horizons_min": [15, 30, 60],
                     "label": "RESEARCH_SHORT_REFERENCE", "short_geometry": "calculate_trade_geometry BEARISH"},
}


def policy_fingerprint() -> str:
    return hashlib.sha256(json.dumps(POLICY, sort_keys=True).encode()).hexdigest()[:16]


def ts(s) -> datetime:
    return s if isinstance(s, datetime) else datetime.fromisoformat(str(s).replace("Z", "+00:00"))


# ============================================================================================================ clock
class VirtualClock:
    """Causal view of one symbol's 1-min bars: at virtual time T only bars with start + 1 min <= T exist."""

    def __init__(self, bars: list[dict]):
        self.bars = sorted(bars, key=lambda b: ts(b["t"]))
        self._ends = [ts(b["t"]) + timedelta(minutes=1) for b in self.bars]
        self._starts = [ts(b["t"]) for b in self.bars]

    def visible(self, T: datetime) -> list[dict]:
        return self.bars[:bisect.bisect_right(self._ends, T)]

    def next_bar_starting_at_or_after(self, T: datetime, within_min: int | None = None) -> dict | None:
        i = bisect.bisect_left(self._starts, T)
        if i >= len(self.bars):
            return None
        if within_min is not None and self._starts[i] >= T + timedelta(minutes=within_min):
            return None
        return self.bars[i]

    def bars_from(self, start: datetime, end: datetime) -> list[dict]:
        """Bars that START in [start, end) -- used only AFTER entry, advancing the clock bar by bar."""
        i, j = bisect.bisect_left(self._starts, start), bisect.bisect_left(self._starts, end)
        return self.bars[i:j]


# ============================================================================================================ geometry
def prior_pivots(prev_session_bars: list[dict], prev_open: datetime, prev_close: datetime):
    from talonx_quant.indicators import DailyPivots
    rth = [b for b in prev_session_bars if prev_open <= ts(b["t"]) < prev_close]
    if not rth:
        return None
    h, lo, c = max(float(b["h"]) for b in rth), min(float(b["l"]) for b in rth), float(rth[-1]["c"])
    p = (h + lo + c) / 3.0
    return DailyPivots(pivot=p, resistance=2 * p - lo, support=2 * p - h)


def atr14(visible: list[dict]) -> float | None:
    import pandas as pd
    import pandas_ta  # noqa: F401  (registers df.ta)
    from talonx_quant.config import QuantConfig
    n = QuantConfig().atr_period
    tail = visible[-(n * 20):]
    if len(tail) <= n:
        return None
    df = pd.DataFrame({"high": [float(b["h"]) for b in tail], "low": [float(b["l"]) for b in tail],
                       "close": [float(b["c"]) for b in tail]})
    s = df.ta.atr(length=n)
    v = None if s is None else s.dropna()
    return float(v.iloc[-1]) if v is not None and len(v) else None


def geometry(price: float, visible: list[dict], pivots, direction: str = "LONG") -> dict | None:
    from talonx_quant.config import QuantConfig
    from talonx_quant.schemas import SignalDirection
    from talonx_quant.strategy import calculate_trade_geometry
    atr = atr14(visible)
    g = calculate_trade_geometry(price, atr, SignalDirection.BULLISH if direction == "LONG" else SignalDirection.BEARISH,
                                 None if pivots is None else pivots.resistance,
                                 None if pivots is None else pivots.support, QuantConfig())
    if g is None:
        return None
    return {"stop": g.stop_price, "target": g.target_price, "rrr": g.risk_reward_ratio, "atr": atr,
            "geometry_path": g.geometry_path, "risk": g.risk}


# ============================================================================================================ lifecycle
def flatten_utc(session_close_utc: datetime) -> datetime:
    d = session_close_utc.astimezone(ET).date()
    f = datetime(d.year, d.month, d.day, 15, 50, tzinfo=ET).astimezone(UTC)
    return min(f, session_close_utc)


@dataclass
class Trade:
    symbol: str
    paper_mode: str
    direction: str
    entry_t: datetime
    entry_px: float
    stop: float
    target: float


def run_exit(tr: Trade, clock: VirtualClock, flat: datetime) -> dict:
    """Advance the virtual clock bar by bar from the entry bar; first touch wins (stop before target)."""
    sgn = 1 if tr.direction == "LONG" else -1
    hi_ext, lo_ext = tr.entry_px, tr.entry_px
    path = clock.bars_from(tr.entry_t, flat)
    for k, b in enumerate(path):
        o, h, lo, c = (float(b[x]) for x in ("o", "h", "l", "c"))
        if k == 0:
            o = tr.entry_px                              # entry filled at this bar's open
        hi_ext, lo_ext = max(hi_ext, h), min(lo_ext, lo)
        if sgn > 0:
            if lo <= tr.stop:
                px = min(o, tr.stop) if o <= tr.stop else tr.stop
                return _exit(tr, b, px, "STOP_HIT", hi_ext, lo_ext, k + 1)
            if h >= tr.target:
                px = max(o, tr.target) if o >= tr.target else tr.target
                return _exit(tr, b, px, "TARGET_HIT", hi_ext, lo_ext, k + 1)
        else:
            if h >= tr.stop:
                px = max(o, tr.stop) if o >= tr.stop else tr.stop
                return _exit(tr, b, px, "STOP_HIT", hi_ext, lo_ext, k + 1)
            if lo <= tr.target:
                px = min(o, tr.target) if o <= tr.target else tr.target
                return _exit(tr, b, px, "TARGET_HIT", hi_ext, lo_ext, k + 1)
    if not path:
        return {"exit_reason": "NO_BARS"}
    last = path[-1]
    return _exit(tr, last, float(last["c"]), "SESSION_CLOSE", hi_ext, lo_ext, len(path))


def _exit(tr: Trade, bar: dict, px: float, why: str, hi: float, lo: float, nbars: int) -> dict:
    sgn = 1 if tr.direction == "LONG" else -1
    t = ts(bar["t"]) + timedelta(minutes=1)            # intrabar fills are timed at the bar's end (conservative)
    return {"exit_t": t, "exit_px": px, "exit_reason": why, "gross": sgn * (px / tr.entry_px - 1.0),
            "mfe": (hi / tr.entry_px - 1.0) if sgn > 0 else (1.0 - lo / tr.entry_px),
            "mae": (lo / tr.entry_px - 1.0) if sgn > 0 else (1.0 - hi / tr.entry_px),
            "holding_bars": nbars, "holding_s": int((t - tr.entry_t).total_seconds())}


def open_trade(symbol: str, mode: str, clock: VirtualClock, decision_t: datetime, decision_px: float, pivots,
               session_open: datetime, flat: datetime, direction: str = "LONG", entry_after: datetime | None = None,
               levels: dict | None = None) -> dict:
    """Geometry from bars visible at decision_t (unless `levels` supplied), entry at the next bar open at/after
    `entry_after` (default decision_t; deferred to the regular open when earlier)."""
    g = levels or geometry(decision_px, clock.visible(decision_t), pivots, direction)
    if g is None:
        return {"status": "NO_GEOMETRY"}
    at = max(entry_after or decision_t, session_open)
    eb = clock.next_bar_starting_at_or_after(at, POLICY["entry_window_min"])
    if eb is None or ts(eb["t"]) >= flat:
        return {"status": "NO_ENTRY_BAR", **g}
    tr = Trade(symbol, mode, direction, ts(eb["t"]), float(eb["o"]), g["stop"], g["target"])
    return {"status": "OPENED", "entry_t": tr.entry_t, "entry_px": tr.entry_px, **g, **run_exit(tr, clock, flat)}


# ============================================================================================================ shadow hypotheses
def pullback_entry(clock: VirtualClock, decision_t: datetime, decision_px: float, depth: float, confirm: str,
                   session_open: datetime, flat: datetime) -> tuple[datetime, float] | None:
    """Causal: walk closed bars after the decision; track the running peak (from the decision price); once a low is
    `depth` below the peak, wait for a confirming CLOSED bar; entry = the NEXT bar's open (returned as its start)."""
    start = max(decision_t, session_open)
    bars = clock.bars_from(start, min(flat, start + timedelta(minutes=POLICY["pullback_v1"]["watch_min"])))
    peak, pulled, prev, closes = decision_px, False, None, [float(b["c"]) for b in clock.visible(start)][-5:]
    for b in bars:
        h, lo, c = float(b["h"]), float(b["l"]), float(b["c"])
        closes = (closes + [c])[-5:]
        if not pulled:
            if lo <= peak * (1 - depth):
                pulled = True
            peak = max(peak, h)
        else:
            ok = (confirm == "RECLAIM_PRIOR_BAR_HIGH" and prev is not None and c > float(prev["h"])) or \
                 (confirm == "CLOSE_ABOVE_SMA5" and len(closes) == 5 and c > statistics.mean(closes))
            if ok:
                return ts(b["t"]) + timedelta(minutes=1), c          # decision at this bar's close
        prev = b
    return None


# ============================================================================================================ metrics
def metrics(rows: list[dict], gkey="gross", nkey="net") -> dict:
    g = [r[gkey] for r in rows if r.get(gkey) is not None]
    n = [r[nkey] for r in rows if r.get(nkey) is not None]
    if not n:
        return {"n": 0}
    w, lo = [x for x in n if x > 0], [x for x in n if x <= 0]
    return {"n": len(n), "gross_mean_pct": round(100 * statistics.mean(g), 3),
            "net_mean_pct": round(100 * statistics.mean(n), 3), "net_median_pct": round(100 * statistics.median(n), 3),
            "win_rate": round(len(w) / len(n), 3),
            "profit_factor": round(sum(w) / -sum(lo), 3) if lo and sum(lo) < 0 else None,
            "mfe_mean_pct": round(100 * statistics.mean(r["mfe"] for r in rows if r.get("mfe") is not None), 3)
            if any(r.get("mfe") is not None for r in rows) else None,
            "mae_mean_pct": round(100 * statistics.mean(r["mae"] for r in rows if r.get("mae") is not None), 3)
            if any(r.get("mae") is not None for r in rows) else None}


def portfolio(rows: list[dict], start=100_000.0, pos=10_000.0, max_open=10) -> dict:
    """Chronological by entry; cash reserved at entry, released (with P&L, net of cost) at exit. Never > 100 %."""
    ev = []
    for i, r in enumerate(rows):
        if r.get("net") is None:
            continue
        ev.append((ts(r["entry_t"]), 1, i))
        ev.append((ts(r["exit_t"]), 0, i))
    ev.sort()
    cash, open_, taken, skipped, eq, peak, mdd, util = start, set(), [], 0, start, start, 0.0, []
    for t, kind, i in ev:
        r = rows[i]
        if kind == 1:
            if len(open_) >= max_open or cash < pos:
                skipped += 1
                continue
            cash -= pos
            open_.add(i)
            util.append(len(open_) * pos / (cash + len(open_) * pos))
        elif i in open_:
            open_.discard(i)
            cash += pos * (1 + r["net"])
            taken.append(pos * r["net"])
            eq = cash + len(open_) * pos
            peak, mdd = max(peak, eq), min(mdd, eq / max(peak, eq) - 1.0)
        assert cash >= -1e-6 and len(open_) <= max_open
    g = sum(pos * rows[i]["gross"] for i in range(len(rows)) if rows[i].get("net") is not None) if rows else 0
    w, lo = [x for x in taken if x > 0], [x for x in taken if x <= 0]
    return {"trades_taken": len(taken), "skipped_capacity": skipped, "net_pnl_usd": round(sum(taken), 2),
            "ending_capital": round(cash, 2), "max_drawdown_pct_realized": round(100 * mdd, 2),
            "profit_factor": round(sum(w) / -sum(lo), 3) if lo and sum(lo) < 0 else None,
            "capital_utilization_mean": round(statistics.mean(util), 3) if util else 0.0,
            "gross_pnl_all_signals_usd": round(g, 2)}
