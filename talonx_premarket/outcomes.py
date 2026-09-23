"""
Post-open confirmation and outcome measurement -- HINDSIGHT / EVALUATION ONLY.

Nothing here feeds back into candidate creation, scoring or alert decisions (the engine calls it
only for already-alerted candidates, after the regular open). Measurements are relative to the
alert reference price (the last pre-market price when the candidate was first alerted) and are
direction-adjusted for GAP_DOWN candidates (a fall is favourable).

Horizons (from 1Min SIP regular-session bars): OPEN (first RTH bar open), +30M and +1H (close of
the bar ending at open+30m / open+60m), CLOSE (last RTH bar close), MFE / MAE over the session.

Status (confirmation horizon = 30 min):
  OUTCOME_PENDING      -- the +30M bar is not yet available
  INVALIDATED          -- the gap fully filled inside the first 30 min (price crossed the previous close)
  CONFIRMED            -- +30M price is on the setup's side of the reference price
  FAILED_CONFIRMATION  -- otherwise
"""
from __future__ import annotations

from datetime import datetime, timedelta

from talonx_premarket.alpaca_data import parse_ts

OUTCOME_PENDING = "OUTCOME_PENDING"
CONFIRMED = "CONFIRMED"
FAILED_CONFIRMATION = "FAILED_CONFIRMATION"
INVALIDATED = "INVALIDATED"


def _ret(px: float | None, ref: float, sign: int) -> float | None:
    return None if px is None else round(sign * (px / ref - 1.0) * 100.0, 3)


def _close_at(bars: list[dict], end: datetime) -> float | None:
    """Close of the last bar that ENDS at or before ``end``."""
    px = None
    for b in bars:
        if parse_ts(b["t"]) + timedelta(minutes=1) <= end:
            px = float(b["c"])
    return px


def measure(*, family: str, ref_price: float, prev_close: float, rth_bars: list[dict], open_utc: datetime,
            close_utc: datetime, confirm_min: int = 30) -> dict:
    sign = 1 if family == "GAP_UP" else -1
    bars = sorted((b for b in rth_bars if open_utc <= parse_ts(b["t"]) < close_utc), key=lambda b: b["t"])
    if not bars:
        return {"status": OUTCOME_PENDING, "detail": "no regular-session bars yet"}
    open_px = float(bars[0]["o"])
    t30, t60 = open_utc + timedelta(minutes=confirm_min), open_utc + timedelta(minutes=60)
    last_end = parse_ts(bars[-1]["t"]) + timedelta(minutes=1)
    px30 = _close_at(bars, t30) if last_end >= t30 else None
    px60 = _close_at(bars, t60) if last_end >= t60 else None
    session_done = last_end >= close_utc
    close_px = float(bars[-1]["c"]) if session_done else None
    hi = max(float(b["h"]) for b in bars)
    lo = min(float(b["l"]) for b in bars)
    fav, adv = (hi, lo) if sign > 0 else (lo, hi)
    first30 = [b for b in bars if parse_ts(b["t"]) < t30]
    if px30 is None:
        status = OUTCOME_PENDING
    else:
        filled = (min(float(b["l"]) for b in first30) <= prev_close) if sign > 0 else \
                 (max(float(b["h"]) for b in first30) >= prev_close)
        if filled:
            status = INVALIDATED
        elif sign * (px30 - ref_price) >= 0:
            status = CONFIRMED
        else:
            status = FAILED_CONFIRMATION
    return {
        "status": status, "open_px": open_px, "px_30m": px30, "px_1h": px60, "close_px": close_px,
        "open_ret_pct": _ret(open_px, ref_price, sign), "ret_30m_pct": _ret(px30, ref_price, sign),
        "ret_1h_pct": _ret(px60, ref_price, sign), "close_ret_pct": _ret(close_px, ref_price, sign),
        "mfe_pct": _ret(fav, ref_price, sign), "mae_pct": _ret(adv, ref_price, sign),
        "session_complete": session_done,
    }
