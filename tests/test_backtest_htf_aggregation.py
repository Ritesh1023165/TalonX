"""
tests/test_backtest_htf_aggregation.py
-------------------------------------------
talonx_quant.aggregation.HtfBarAggregator -- the shared bucketing logic
consumer.py (live) and talonx_backtest.engine (historical replay) both
use to build 15-minute bars from 1-minute updates. Covers the HTF
boundary requirement (spec section 17): a bucket is not finalized/
visible until a bar from the NEXT bucket arrives, so its own close can
never leak into a signal evaluated before that boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_quant.aggregation import HtfBarAggregator


def _dt(minute: int) -> datetime:
    return datetime(2026, 1, 5, 14, minute, 0, tzinfo=timezone.utc)


def test_bucket_not_finalized_until_next_bucket_starts():
    agg = HtfBarAggregator(interval_minutes=15)

    # 14:00-14:14 all belong to the SAME 15m bucket (14:00).
    for minute in range(0, 15):
        finalized = agg.update("AAPL", _dt(minute), open_=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0)
        assert finalized is None, f"bucket finalized early at minute {minute}"


def test_bucket_finalizes_on_first_bar_of_next_bucket():
    agg = HtfBarAggregator(interval_minutes=15)
    for minute in range(0, 15):
        agg.update("AAPL", _dt(minute), open_=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0)

    # 14:15 is the first tick of the NEXT bucket -- this is what finalizes 14:00.
    finalized = agg.update("AAPL", _dt(15), open_=105.0, high=106.0, low=104.0, close=105.5, volume=500.0)
    assert finalized is not None
    assert finalized["timestamp"] == _dt(0)
    assert finalized["open"] == 100.0
    assert finalized["close"] == 100.5  # the LAST close of the 14:00-14:14 bucket, not 14:15's


def test_finalized_ohlc_aggregates_correctly_across_the_bucket():
    agg = HtfBarAggregator(interval_minutes=15)
    prices = [(100.0, 101.0, 99.5, 100.2), (100.2, 103.0, 100.0, 102.0), (102.0, 102.5, 97.0, 98.0)]
    for i, (o, h, l, c) in enumerate(prices):
        agg.update("AAPL", _dt(i), open_=o, high=h, low=l, close=c, volume=100.0)

    finalized = agg.update("AAPL", _dt(15), open_=99.0, high=99.5, low=98.5, close=99.0, volume=50.0)
    assert finalized["open"] == 100.0    # first bar's open
    assert finalized["high"] == 103.0    # max high across the bucket
    assert finalized["low"] == 97.0      # min low across the bucket
    assert finalized["close"] == 98.0    # last bar's close
    assert finalized["volume"] == 300.0  # summed


def test_rth_only_drops_a_finalized_pre_market_bucket():
    # 06:00-06:14 ET is pre-market -- with rth_only=True this bucket must
    # be dropped (finalized=None) rather than handed to the caller, even
    # though the NEXT bucket's arrival is what triggers finalization.
    agg = HtfBarAggregator(interval_minutes=15, rth_only=True)
    et_premarket_minute = datetime(2026, 1, 5, 11, 0, tzinfo=timezone.utc)  # 06:00 ET (UTC-5 in Jan)
    for m in range(15):
        agg.update("AAPL", et_premarket_minute.replace(minute=m % 60), open_=1, high=1, low=1, close=1, volume=1)
    finalized = agg.update("AAPL", datetime(2026, 1, 5, 11, 15, tzinfo=timezone.utc), open_=1, high=1, low=1, close=1, volume=1)
    assert finalized is None


def test_two_symbols_are_bucketed_independently():
    agg = HtfBarAggregator(interval_minutes=15)
    agg.update("AAPL", _dt(0), open_=100, high=100, low=100, close=100, volume=10)
    agg.update("MSFT", _dt(0), open_=200, high=200, low=200, close=200, volume=20)

    finalized_aapl = agg.update("AAPL", _dt(15), open_=1, high=1, low=1, close=1, volume=1)
    assert finalized_aapl["close"] == 100

    # MSFT's bucket must be untouched by AAPL's finalization.
    finalized_msft = agg.update("MSFT", _dt(15), open_=2, high=2, low=2, close=2, volume=2)
    assert finalized_msft["close"] == 200
