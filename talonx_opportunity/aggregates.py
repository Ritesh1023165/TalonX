"""
Bounded-memory, window-to-date per-symbol aggregates + an EXACT equivalent of V1 ``features.compute``.

All-day discovery over ~5.6k symbols cannot keep every 1-minute bar in memory. The V1 features use only order-free
reductions of the pre-market bars (count, sum volume, sum dollar volume, sum trades, max high, min low) plus the LAST
bar (time + close). ``SymbolAggregate`` keeps exactly those, so ``features_from_aggregate`` reproduces
``talonx_premarket.features.compute`` bit-for-bit for the same bars (proven in tests), with the V1 bar-validity
filter applied on ingest. Sums use CPython's own float ``sum()`` algorithm (Neumaier, CPython >= 3.12), so they
are bit-identical to V1's ``sum(...)`` over the same bars in chronological order.
"""
from __future__ import annotations

import math
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

from talonx_premarket.alpaca_data import parse_ts
from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig
from talonx_premarket.features import Features, _bar_ok, session_date

assert sys.version_info >= (3, 12), "float sum() equivalence assumes CPython >= 3.12"


def _neumaier_add(s: float, c: float, x: float) -> tuple[float, float]:
    """One step of CPython's float ``sum()`` (Neumaier compensated summation, CPython >= 3.12)."""
    t = s + x
    if abs(s) >= abs(x):
        c += (s - t) + x
    else:
        c += (x - t) + s
    return t, c


def _neumaier_result(s: float, c: float) -> float:
    return s + c if c and math.isfinite(c) else s


@dataclass
class SymbolAggregate:
    symbol: str
    window_id: str
    bars: int = 0
    volume_s: float = 0.0          # running Neumaier sum + compensation, finalised exactly like builtin sum()
    volume_c: float = 0.0
    dollars_s: float = 0.0
    dollars_c: float = 0.0
    trades: int = 0
    high: float | None = None
    low: float | None = None
    first_t: str | None = None
    last_t: str | None = None
    last_c: float | None = None

    def add(self, rows: list[dict]) -> int:
        """Fold new (never previously folded) bars in. Returns the number accepted (V1 validity filter)."""
        n = 0
        for b in rows:
            if not _bar_ok(b):
                continue
            n += 1
            self.bars += 1
            self.volume_s, self.volume_c = _neumaier_add(self.volume_s, self.volume_c, float(b["v"]))
            self.dollars_s, self.dollars_c = _neumaier_add(self.dollars_s, self.dollars_c,
                                                           float(b["v"]) * float(b.get("vw") or b["c"]))
            self.trades += int(b.get("n") or 0)
            self.high = float(b["h"]) if self.high is None else max(self.high, float(b["h"]))
            self.low = float(b["l"]) if self.low is None else min(self.low, float(b["l"]))
            if self.first_t is None or b["t"] < self.first_t:
                self.first_t = b["t"]
            if self.last_t is None or b["t"] >= self.last_t:
                self.last_t, self.last_c = b["t"], float(b["c"])
        return n

    @property
    def volume(self) -> float:
        return _neumaier_result(self.volume_s, self.volume_c)

    @property
    def dollars(self) -> float:
        return _neumaier_result(self.dollars_s, self.dollars_c)

    def as_dict(self) -> dict:
        return asdict(self)


def features_from_aggregate(symbol: str, daily: list[dict], agg: SymbolAggregate | None, *, prev_session: date,
                            data_as_of: datetime, cfg: PremarketConfig = PREMARKET_RESEARCH_V1
                            ) -> tuple[Features | None, str]:
    """Same contract, reasons and arithmetic as ``talonx_premarket.features.compute``."""
    daily = [b for b in daily if _bar_ok(b) and session_date(b) <= prev_session]
    if len(daily) < cfg.min_daily_sessions:
        return None, "INSUFFICIENT_DAILY_HISTORY"
    daily = sorted(daily, key=lambda b: b["t"])
    last = daily[-1]
    if session_date(last) != prev_session:
        return None, "MISSING_PREVIOUS_SESSION_BAR"
    if agg is None or agg.bars == 0:
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

    last_price = float(agg.last_c)
    last_end = parse_ts(agg.last_t) + timedelta(minutes=1)
    staleness = (data_as_of - last_end).total_seconds() / 60.0
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
        last_price=last_price, last_bar_utc=agg.last_t, staleness_min=round(staleness, 2),
        pm_high=agg.high, pm_low=agg.low, pm_volume=agg.volume, pm_dollars=agg.dollars, pm_bars=agg.bars,
        pm_trades=agg.trades, gap_pct=gap, activity_adv_fraction=(agg.volume / adv_sh) if adv_sh > 0 else 0.0,
        range_position=pos, range_distance_pct=dist,
    ), ""
