"""
tests/test_run_talonx_watchlist.py
----------------------------------------
Tests run_talonx.py's pure `_diff_symbols` helper, used by
WatchlistDrivenMarketData to decide when a ticker add/remove should
restart the market data stream. Deliberately not testing
WatchlistDrivenMarketData.run() itself here -- that's an asyncio
orchestration loop wrapping MarketDataManager.stream() (network I/O),
better exercised via the project's manual end-to-end testing scripts
(send_test_signal.py) than mocked in isolation.
"""
from __future__ import annotations

from run_talonx import _diff_symbols


def test_diff_symbols_no_change():
    added, removed = _diff_symbols({"AAPL", "MSFT"}, {"AAPL", "MSFT"})

    assert added == set()
    assert removed == set()


def test_diff_symbols_detects_addition():
    added, removed = _diff_symbols({"MSFT"}, {"MSFT", "NVDA"})

    assert added == {"NVDA"}
    assert removed == set()


def test_diff_symbols_detects_removal():
    added, removed = _diff_symbols({"MSFT", "NVDA"}, {"MSFT"})

    assert added == set()
    assert removed == {"NVDA"}


def test_diff_symbols_detects_both():
    added, removed = _diff_symbols({"AAPL", "MSFT"}, {"MSFT", "NVDA"})

    assert added == {"NVDA"}
    assert removed == {"AAPL"}


def test_diff_symbols_from_empty():
    added, removed = _diff_symbols(set(), {"MSFT"})

    assert added == {"MSFT"}
    assert removed == set()


def test_diff_symbols_to_empty():
    added, removed = _diff_symbols({"MSFT"}, set())

    assert added == set()
    assert removed == {"MSFT"}
