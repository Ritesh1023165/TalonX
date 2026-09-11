"""
talonx_quant.aggregation
----------------------------
Pure, stateful bar-bucketing logic factored out of consumer.py's own
_update_htf_buffer so it can be shared, unchanged, by two callers:

  1. consumer.py (live): floor-buckets incoming 1-min BAR events into
     coarser (default 15-min) HTF bars.
  2. talonx_backtest's replay engine: floor-buckets historical 1-min
     OHLCV rows into the same HTF bars, so a backtest's HTF-derived
     inputs (compute_htf_trend, compute_daily_pivots) are built from
     EXACTLY the same bucketing math the live system uses -- not a
     second, independently-maintained implementation that could drift
     from this one over time.

This module has no Redis/async/buffer dependency of its own -- it only
knows how to accumulate and finalize a bucket; the caller decides what
to do with a finalized bucket (e.g. write it into a RollingBarBuffer).
"""
from __future__ import annotations

from datetime import datetime

from talonx_quant.session import get_session


class HtfBarAggregator:
    """Incrementally rolls up sub-interval bar updates into coarser bars,
    floor-bucketed by `interval_minutes`. A bucket is finalized (returned
    from `update`) only once an update belonging to the NEXT bucket
    arrives -- the currently-forming bucket is never emitted early or
    partial, matching consumer.py's original Closed-Bar semantics for
    the HTF buffer.
    """

    __slots__ = ("interval_minutes", "rth_only", "_accumulators")

    def __init__(self, interval_minutes: int, rth_only: bool = False):
        self.interval_minutes = interval_minutes
        self.rth_only = rth_only
        self._accumulators: dict[str, dict] = {}

    def reset(self, symbol: str) -> None:
        """Task 44: discards any in-flight (not-yet-finalized) accumulator
        for `symbol`, without touching other symbols or emitting a
        (necessarily partial) finalized bucket for the discarded one.
        Exists specifically for a caller about to re-feed a KNOWN-clean,
        full historical range (e.g. a warmup bootstrap) that must not be
        allowed to accumulate on top of whatever partial bucket state
        already existed for that symbol -- update()'s own += accumulation
        has no way to distinguish "one more legitimate live tick for the
        bucket already forming" from "a bootstrap re-feed that happens to
        overlap it," so the caller must explicitly clear first."""
        self._accumulators.pop(symbol.upper(), None)

    def update(
        self,
        symbol: str,
        timestamp: datetime,
        open_: float | None,
        high: float | None,
        low: float | None,
        close: float | None,
        volume: float | None,
    ) -> dict | None:
        """Feed one sub-interval bar update for `symbol`. Returns the
        finalized bucket dict (timestamp/open/high/low/close/volume) if
        this update closed out a PREVIOUS bucket, else None.

        Session-aware buffering: when `rth_only` is set, a finalized
        bucket that falls outside regular trading hours is silently
        dropped (returns None for that finalization) -- mirrors
        consumer.py's original `rth_only_htf_sma` behavior.
        """
        symbol = symbol.upper()
        interval = self.interval_minutes
        bucket_start = timestamp.replace(
            minute=(timestamp.minute // interval) * interval, second=0, microsecond=0
        )

        acc = self._accumulators.get(symbol)
        finalized = None
        if acc is not None and acc["bucket_start"] != bucket_start:
            if not self.rth_only or get_session(acc["bucket_start"]) == "regular":
                finalized = {
                    "timestamp": acc["bucket_start"],
                    "open": acc["open"],
                    "high": acc["high"],
                    "low": acc["low"],
                    "close": acc["close"],
                    "volume": acc["volume"],
                }
            acc = None

        if acc is None:
            acc = {
                "bucket_start": bucket_start,
                "open": open_, "high": high, "low": low,
                "close": close, "volume": volume or 0.0,
            }
        else:
            if high is not None:
                acc["high"] = high if acc["high"] is None else max(acc["high"], high)
            if low is not None:
                acc["low"] = low if acc["low"] is None else min(acc["low"], low)
            if close is not None:
                acc["close"] = close
            acc["volume"] = (acc["volume"] or 0.0) + (volume or 0.0)
        self._accumulators[symbol] = acc
        return finalized
