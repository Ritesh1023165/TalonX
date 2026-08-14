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
    buf.add_bar("AAPL", NOW, open_=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0)

    bar = buf.get_bars("AAPL")[0]
    assert bar == {
        "timestamp": NOW, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0,
    }
