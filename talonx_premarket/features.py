"""
Explainable, causal pre-market features. Pure functions over already-causal inputs:

* ``daily``  -- completed daily bars for sessions BEFORE the scan day (split-adjusted)
* ``pm``     -- today's 1Min SIP bars already filtered to complete-as-of the data cut-off

No lookahead: nothing here reads a bar that ``alpaca_data.complete_bars_as_of`` removed.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from talonx_premarket.alpaca_data import parse_ts
from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig

NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Features:
    symbol: str
    data_as_of_utc: str
    prev_session: str
    prev_close: float
    prev_high: float
    prev_low: float
    atr20_pct: float
    adv20_shares: float
    adv20_dollars: float
    trend5_pct: float | None
    last_price: float
    last_bar_utc: str
    staleness_min: float
    pm_high: float
    pm_low: float
    pm_volume: float
    pm_dollars: float
    pm_bars: int
    pm_trades: int
    gap_pct: float
    activity_adv_fraction: float
    range_position: str          # ABOVE_PREV_HIGH | BELOW_PREV_LOW | INSIDE_PREV_RANGE
    range_distance_pct: float    # distance beyond the prev-day range in the gap direction (0 if inside)

    def as_dict(self) -> dict:
        return asdict(self)


def _finite(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _bar_ok(b: dict) -> bool:
    return all(_finite(b.get(k)) for k in ("o", "h", "l", "c", "v")) and float(b["c"]) > 0 and float(b["v"]) >= 0


def session_date(bar: dict) -> date:
    return parse_ts(bar["t"]).astimezone(NY).date()


def compute(symbol: str, daily: list[dict], pm: list[dict], *, prev_session: date, data_as_of: datetime,
            cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> tuple[Features | None, str]:
    """Returns (features, "") or (None, reason) -- reasons are HARD-gate data codes."""
    daily = [b for b in daily if _bar_ok(b) and session_date(b) <= prev_session]
    if len(daily) < cfg.min_daily_sessions:
        return None, "INSUFFICIENT_DAILY_HISTORY"
    daily = sorted(daily, key=lambda b: b["t"])
    last = daily[-1]
    if session_date(last) != prev_session:
        return None, "MISSING_PREVIOUS_SESSION_BAR"
    pm = sorted((b for b in pm if _bar_ok(b)), key=lambda b: b["t"])
    if not pm:
        return None, "NO_PREMARKET_PRINTS"
    prev_close = float(last["c"])
    window = daily[-20:]
    trs = []
    for i, b in enumerate(window):
        pc = float(window[i - 1]["c"]) if i > 0 else float(b["o"])
        trs.append(max(float(b["h"]) - float(b["l"]), abs(float(b["h"]) - pc), abs(float(b["l"]) - pc)))
    atr_pct = (sum(trs) / len(trs)) / prev_close * 100.0 if trs else float("nan")
    adv_sh = sum(float(b["v"]) for b in window) / len(window)
    adv_usd = sum(float(b["v"]) * float(b["c"]) for b in window) / len(window)
    trend5 = (prev_close / float(daily[-6]["c"]) - 1.0) * 100.0 if len(daily) >= 6 else None

    last_bar = pm[-1]
    last_price = float(last_bar["c"])
    last_end = parse_ts(last_bar["t"]) + timedelta(minutes=1)
    staleness = (data_as_of - last_end).total_seconds() / 60.0
    pm_vol = sum(float(b["v"]) for b in pm)
    pm_usd = sum(float(b["v"]) * float(b.get("vw") or b["c"]) for b in pm)
    gap = (last_price / prev_close - 1.0) * 100.0
    ph, pl = float(last["h"]), float(last["l"])
    if last_price > ph:
        pos, dist = "ABOVE_PREV_HIGH", (last_price / ph - 1.0) * 100.0
    elif last_price < pl:
        pos, dist = "BELOW_PREV_LOW", (1.0 - last_price / pl) * 100.0
    else:
        pos, dist = "INSIDE_PREV_RANGE", 0.0
    return Features(
        symbol=symbol, data_as_of_utc=data_as_of.astimezone(timezone.utc).isoformat(),
        prev_session=prev_session.isoformat(), prev_close=prev_close, prev_high=ph, prev_low=pl,
        atr20_pct=atr_pct, adv20_shares=adv_sh, adv20_dollars=adv_usd, trend5_pct=trend5,
        last_price=last_price, last_bar_utc=last_bar["t"], staleness_min=round(staleness, 2),
        pm_high=max(float(b["h"]) for b in pm), pm_low=min(float(b["l"]) for b in pm),
        pm_volume=pm_vol, pm_dollars=pm_usd, pm_bars=len(pm), pm_trades=int(sum(int(b.get("n") or 0) for b in pm)),
        gap_pct=gap, activity_adv_fraction=(pm_vol / adv_sh) if adv_sh > 0 else 0.0,
        range_position=pos, range_distance_pct=dist,
    ), ""
