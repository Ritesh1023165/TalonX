"""Task 69Q Part 7A -- observational PRE-MARKET RADAR.

Canonical pre-market start is 04:00 America/New_York (PERMANENT PRODUCT
TARGET #1/#2 -- see results/task69q_evidence_upgrade/premarket_radar_
contract.json). This module deliberately has NO import of talonx_piv.broker
or talonx_piv.lifecycle -- structurally, nothing here can ever submit an
order; a WATCH observation is informational only (PERMANENT PRODUCT TARGET
#8). It reuses only data already available from Alpaca's snapshot endpoint
(previous session close, latest price, volume) -- no new strategy, no new
threshold tuned from any single day's outcome, no confidence percentages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PREMARKET_START = time(4, 0)
REGULAR_OPEN = time(9, 30)

# Not a validated strategy threshold -- purely a label boundary so the radar
# doesn't chatter about noise-level moves. Never tuned from observed outcomes.
GAP_WATCH_THRESHOLD_PCT = 1.0


def is_premarket(now_et: datetime) -> bool:
    """now_et must already be tz-aware and in America/New_York."""
    t = now_et.astimezone(ET).time()
    return PREMARKET_START <= t < REGULAR_OPEN and now_et.astimezone(ET).weekday() < 5


@dataclass(frozen=True)
class RadarObservation:
    symbol: str
    data_status: str  # "READY" | "DATA_NOT_READY"
    bias: str | None = None  # "BULLISH" | "BEARISH" | None (no gap, or DATA_NOT_READY)
    gap_pct: float | None = None
    reason_codes: tuple[str, ...] = ()


def classify(
    symbol: str, prev_close: float | None, latest_price: float | None,
    latest_volume: float | None = None, gap_watch_threshold_pct: float = GAP_WATCH_THRESHOLD_PCT,
) -> RadarObservation:
    if prev_close is None or latest_price is None or prev_close == 0:
        return RadarObservation(symbol=symbol, data_status="DATA_NOT_READY", reason_codes=("PREMARKET_DATA_UNAVAILABLE",))
    gap_pct = (latest_price - prev_close) / prev_close * 100.0
    reasons: list[str] = []
    bias = None
    if gap_pct >= gap_watch_threshold_pct:
        bias, reasons = "BULLISH", ["PREMARKET_GAP_UP"]
    elif gap_pct <= -gap_watch_threshold_pct:
        bias, reasons = "BEARISH", ["PREMARKET_GAP_DOWN"]
    if latest_volume is not None and latest_volume == 0:
        reasons.append("PREMARKET_LIQUIDITY_UNAVAILABLE")
    return RadarObservation(
        symbol=symbol, data_status="READY", bias=bias, gap_pct=round(gap_pct, 3), reason_codes=tuple(reasons),
    )


class PremarketRadarEngine:
    """Stateful only to suppress repeat notifications for an unchanged bias
    (Part 7C: 'avoid repetitive unchanged alerts'). evaluate() is pure aside
    from that dedup state -- no I/O, no broker/lifecycle access at all."""

    def __init__(self) -> None:
        self._last_bias: dict[str, str | None] = {}

    @property
    def watch_count(self) -> int:
        return sum(1 for bias in self._last_bias.values() if bias is not None)

    def evaluate(self, observations: list[RadarObservation]) -> list[dict[str, Any]]:
        """Returns a list of plain dicts describing only the TRANSITIONS
        worth notifying on (new WATCH bias, bias change, or WATCH clearing)
        -- the caller (session_runner.py) turns these into PivEvents. Never
        returns anything for an unchanged bias."""
        transitions: list[dict[str, Any]] = []
        for obs in observations:
            if obs.data_status != "READY":
                continue
            previous = self._last_bias.get(obs.symbol)
            if obs.bias == previous:
                continue
            self._last_bias[obs.symbol] = obs.bias
            if obs.bias is None:
                transitions.append({"symbol": obs.symbol, "event": "PREMARKET_WATCH_CLEARED"})
            else:
                transitions.append({
                    "symbol": obs.symbol, "event": "PREMARKET_WATCH", "bias": obs.bias,
                    "gap_pct": obs.gap_pct, "reason_codes": obs.reason_codes,
                })
        return transitions
