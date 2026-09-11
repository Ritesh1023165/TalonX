"""Task 87B FC_04 -- symbol ownership / exclusion observability.

The intentional 43->42 pre-market narrowing (a symbol owned by
EarningsFastTrackPoller is left out of PreMarketPoller to avoid
double-publishing its ticks) is UNCHANGED. This proves the poller now
makes that exclusion self-explanatory: configured count, selected count,
excluded symbol(s) + reason + alternate owner, and no accidental
watchlist mutation.

TEST_FIXTURE_ONLY.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from run_talonx import PreMarketPoller


def _store(active):
    s = MagicMock()
    s.list_active_symbols.return_value = list(active)
    return s


CONFIGURED_43 = [f"S{i:02d}" for i in range(42)] + ["DELL"]


def test_configured_selected_excluded_with_reason_and_owner():
    poller = PreMarketPoller(
        _store(CONFIGURED_43), AsyncMock(), 300.0,
        active_earnings_symbols_fn=lambda: {"DELL"},
    )
    selected, excluded = poller._select()
    assert len(CONFIGURED_43) == 43
    assert len(selected) == 42
    assert "DELL" not in selected
    assert excluded == {"DELL": "EARNINGS_FAST_TRACK"}  # reason names the alternate owning poller


def test_zero_exclusions_when_no_earnings_window_symbol():
    poller = PreMarketPoller(_store(CONFIGURED_43), AsyncMock(), 300.0,
                             active_earnings_symbols_fn=lambda: set())
    selected, excluded = poller._select()
    assert len(selected) == 43 and excluded == {}


def test_exclusion_is_dynamic_multiple_symbols():
    poller = PreMarketPoller(_store(CONFIGURED_43), AsyncMock(), 300.0,
                             active_earnings_symbols_fn=lambda: {"DELL", "S00", "S01"})
    selected, excluded = poller._select()
    assert len(selected) == 40
    assert set(excluded) == {"DELL", "S00", "S01"}
    assert all(r == "EARNINGS_FAST_TRACK" for r in excluded.values())


def test_earnings_symbol_not_on_watchlist_is_not_reported_as_excluded():
    poller = PreMarketPoller(_store(CONFIGURED_43), AsyncMock(), 300.0,
                             active_earnings_symbols_fn=lambda: {"NOT_ON_LIST"})
    selected, excluded = poller._select()
    assert len(selected) == 43 and excluded == {}


@pytest.mark.asyncio
async def test_poll_once_logs_attributed_line_and_never_mutates_watchlist(caplog, monkeypatch):
    import run_talonx as rt

    store = _store(CONFIGURED_43)
    poller = PreMarketPoller(store, AsyncMock(), 300.0, active_earnings_symbols_fn=lambda: {"DELL"})
    monkeypatch.setattr(rt, "fetch_watchlist_quotes", lambda syms, warn: [])

    with caplog.at_level("INFO", logger="run_talonx"):
        await poller._poll_once()

    line = "\n".join(r.message for r in caplog.records)
    assert "configured=43" in line and "selected=42" in line
    assert "DELL:EARNINGS_FAST_TRACK" in line
    assert "not dropped" in line
    # last_selection is queryable for status inspection without a cycle
    assert poller.last_selection[1] == {"DELL": "EARNINGS_FAST_TRACK"}
    # no add_ticker / remove_ticker / set_* ever called on the store
    for bad in ("add_ticker", "remove_ticker", "set_paper_trading_enabled", "update_ticker"):
        assert not getattr(store, bad).called
