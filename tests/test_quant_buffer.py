"""
tests/test_quant_buffer.py
------------------------------
Tests talonx_quant.buffer.RollingBarBuffer.get_bars -- the buffer-
persistence checkpoint's source (see QuantScanner._checkpoint_all_buffers),
returning the buffer's raw internal bar dicts in chronological order.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_quant.buffer import RollingBarBuffer

NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)


def test_get_bars_returns_empty_list_for_unknown_symbol():
    buf = RollingBarBuffer(max_bars_per_symbol=10)
    assert buf.get_bars("AAPL") == []


def test_get_bars_returns_bars_in_chronological_order():
    buf = RollingBarBuffer(max_bars_per_symbol=10)
    for i in range(3):
        buf.add_bar("AAPL", NOW.replace(minute=i), 100.0, 101.0, 99.0, 100.5, 1000.0)

    bars = buf.get_bars("AAPL")
    assert [b["timestamp"].minute for b in bars] == [0, 1, 2]


def test_get_bars_is_case_insensitive_on_symbol():
    buf = RollingBarBuffer(max_bars_per_symbol=10)
    buf.add_bar("aapl", NOW, 100.0, 101.0, 99.0, 100.5, 1000.0)

    assert len(buf.get_bars("AAPL")) == 1
    assert len(buf.get_bars("aapl")) == 1


def test_get_bars_reflects_maxlen_eviction():
    buf = RollingBarBuffer(max_bars_per_symbol=2)
    for i in range(3):
        buf.add_bar("AAPL", NOW.replace(minute=i), 100.0, 101.0, 99.0, 100.5, 1000.0)

    bars = buf.get_bars("AAPL")
    assert len(bars) == 2
    assert [b["timestamp"].minute for b in bars] == [1, 2]  # oldest (minute=0) evicted


def test_get_bars_returns_the_exact_field_shape_add_bar_stored():
    buf = RollingBarBuffer(max_bars_per_symbol=10)
    buf.add_bar("AAPL", NOW, open_=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0, session="regular")

    bar = buf.get_bars("AAPL")[0]
    assert bar == {
        "timestamp": NOW, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0,
        "session": "regular",
    }


# --- Session tagging (Requirement 3) --------------------------------------

def test_add_bar_derives_session_when_not_given():
    # 16:00 UTC = 12:00 ET (EDT, UTC-4) -- regular session.
    regular_ts = NOW.replace(hour=16)
    buf = RollingBarBuffer(max_bars_per_symbol=10)
    buf.add_bar("AAPL", regular_ts, 100.0, 101.0, 99.0, 100.5, 1000.0)

    assert buf.get_bars("AAPL")[0]["session"] == "regular"


def test_add_bar_derives_pre_market_session():
    pre_market_ts = NOW.replace(hour=9)  # 09:00 UTC = 05:00 ET -- pre-market
    buf = RollingBarBuffer(max_bars_per_symbol=10)
    buf.add_bar("AAPL", pre_market_ts, 100.0, 101.0, 99.0, 100.5, 1000.0)

    assert buf.get_bars("AAPL")[0]["session"] == "pre_market"


def test_add_bar_honors_an_explicit_session_override():
    buf = RollingBarBuffer(max_bars_per_symbol=10)
    buf.add_bar("AAPL", NOW, 100.0, 101.0, 99.0, 100.5, 1000.0, session="closed")

    assert buf.get_bars("AAPL")[0]["session"] == "closed"


# --- Concurrent-writer race regression (live tick vs. historical pre-seed) -
#
# Found live: consumer.py's live-tick accumulator and the historical
# pre-seed path (preseed.py, via an awaited yfinance call) write to the
# SAME buffer for the SAME symbol from two independent async tasks. A
# pre-seed batch can resume AFTER more live ticks have landed and then
# insert an OLDER timestamp a live tick already wrote -- exercised here by
# adding bars deliberately OUT OF CHRONOLOGICAL ORDER, not just by
# re-adding the tail.

def test_add_bar_out_of_order_upserts_instead_of_duplicating():
    buf = RollingBarBuffer(max_bars_per_symbol=10)
    buf.add_bar("AAPL", NOW.replace(minute=5), 1.0, 1.0, 1.0, 100.0, 1.0)  # "live" bar lands first
    # A "pre-seed" batch then writes an OLDER timestamp for the same
    # minute -- must UPDATE minute=5 in place, not append a duplicate.
    buf.add_bar("AAPL", NOW.replace(minute=3), 1.0, 1.0, 1.0, 50.0, 1.0)
    buf.add_bar("AAPL", NOW.replace(minute=5), 1.0, 1.0, 1.0, 999.0, 1.0)  # re-targets minute=5

    bars = buf.get_bars("AAPL")
    assert [b["timestamp"].minute for b in bars] == [3, 5]  # no duplicate minute=5 row
    assert next(b for b in bars if b["timestamp"].minute == 5)["close"] == 999.0


def test_get_dataframe_never_has_a_duplicate_index_under_out_of_order_writes():
    """Regression for the actual production failure: a duplicate-valued
    DataFrame index crashes pandas_ta with "cannot reindex on an axis
    with duplicate labels" the moment an indicator is computed."""
    buf = RollingBarBuffer(max_bars_per_symbol=10)
    buf.add_bar("AAPL", NOW.replace(minute=5), 1.0, 1.0, 1.0, 100.0, 1.0)
    buf.add_bar("AAPL", NOW.replace(minute=3), 1.0, 1.0, 1.0, 50.0, 1.0)
    buf.add_bar("AAPL", NOW.replace(minute=4), 1.0, 1.0, 1.0, 75.0, 1.0)

    df = buf.get_dataframe("AAPL")
    assert df.index.is_unique
    assert len(df) == 3


def test_eviction_is_by_oldest_timestamp_not_insertion_order():
    """A pre-seed batch can insert older timestamps AFTER newer live
    bars already exist -- eviction at capacity must still drop the
    chronologically oldest bar, not the first one INSERTED."""
    buf = RollingBarBuffer(max_bars_per_symbol=2)
    buf.add_bar("AAPL", NOW.replace(minute=5), 1.0, 1.0, 1.0, 1.0, 1.0)  # inserted first, but NEWEST
    buf.add_bar("AAPL", NOW.replace(minute=1), 1.0, 1.0, 1.0, 1.0, 1.0)  # inserted second, but OLDEST
    buf.add_bar("AAPL", NOW.replace(minute=3), 1.0, 1.0, 1.0, 1.0, 1.0)  # pushes buffer over capacity

    bars = buf.get_bars("AAPL")
    assert [b["timestamp"].minute for b in bars] == [3, 5]  # minute=1 (oldest) evicted, not minute=5
