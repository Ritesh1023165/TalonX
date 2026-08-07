"""
tests/test_core_store.py
-----------------------------
Tests talonx_core.store.TickerStateStore -- the SQLite-backed correlator
persistence layer. Uses real sqlite3 (stdlib, no mocking needed), same
approach as tests/test_ledger.py for talonx_ingest's own SQLite store.

The core claim under test is the one that matters: state survives a
process restart (test_state_persists_across_reopen and
test_correlator_rehydrates_a_partial_pair_after_restart) -- that's the
whole reason this module exists (see talonx_core/config.py's
`enable_persistence` docstring).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_core.schemas import QuantSignal, ResearchReport, ResearchVerdict, SignalDirection, SignalType
from talonx_core.state import TickerCorrelator
from talonx_core.store import TickerStateStore

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def _signal() -> QuantSignal:
    return QuantSignal(
        ticker="AAPL",
        signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE,
        direction=SignalDirection.BULLISH,
        message="RSI oversold with volume surge",
        price=200.0,
        bar_timestamp=NOW - timedelta(minutes=1),
    )


def _report() -> ResearchReport:
    return ResearchReport(
        ticker="AAPL",
        triggering_signal=_signal(),
        verdict=ResearchVerdict.BULLISH,
        confidence=0.8,
        summary="Fundamentals support the move.",
        model_used="gemini-flash-latest",
        generated_at=NOW,
        published_at=NOW,
    )


def test_load_into_empty_store_loads_nothing(tmp_path):
    store = TickerStateStore(tmp_path / "core_state.db")
    correlator = TickerCorrelator()
    assert store.load_into(correlator) == 0
    store.close()


def test_save_signal_then_load_into_rehydrates_it(tmp_path):
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_signal("AAPL", _signal(), NOW)

    correlator = TickerCorrelator()
    with TickerStateStore(path) as store:
        loaded = store.load_into(correlator)

    assert loaded == 1
    state = correlator.get_or_create("AAPL")
    assert state.latest_signal == _signal()
    assert state.latest_signal_at == NOW
    assert state.latest_report is None


def test_save_signal_and_report_separately_dont_clobber_each_other(tmp_path):
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_signal("AAPL", _signal(), NOW)
        store.save_report("AAPL", _report(), NOW + timedelta(seconds=30))

    correlator = TickerCorrelator()
    with TickerStateStore(path) as store:
        store.load_into(correlator)

    state = correlator.get_or_create("AAPL")
    assert state.latest_signal is not None
    assert state.latest_report is not None
    assert state.latest_report_at == NOW + timedelta(seconds=30)


def test_save_alert_time_then_load_into_rehydrates_cooldown(tmp_path):
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_signal("AAPL", _signal(), NOW)
        store.save_alert_time("AAPL", NOW + timedelta(seconds=5))

    correlator = TickerCorrelator()
    with TickerStateStore(path) as store:
        store.load_into(correlator)

    state = correlator.get_or_create("AAPL")
    assert state.last_alert_at == NOW + timedelta(seconds=5)


def test_state_persists_across_reopen(tmp_path):
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_signal("AAPL", _signal(), NOW)

    # Reopen as a fresh connection (simulating a process restart) -- must survive.
    correlator = TickerCorrelator()
    with TickerStateStore(path) as store2:
        loaded = store2.load_into(correlator)

    assert loaded == 1
    assert correlator.get_or_create("AAPL").latest_signal == _signal()


def test_correlator_rehydrates_a_partial_pair_after_restart(tmp_path):
    """
    The exact scenario this feature exists for: a QuantSignal arrives,
    talonx_core writes it through, then the process restarts BEFORE the
    matching ResearchReport shows up. On restart, the signal must still
    be there waiting -- not silently lost.
    """
    path = tmp_path / "core_state.db"

    # "Before restart": signal arrives, gets persisted.
    with TickerStateStore(path) as store:
        store.save_signal("AAPL", _signal(), NOW)

    # "After restart": fresh process, fresh correlator, rehydrated from disk.
    correlator = TickerCorrelator()
    with TickerStateStore(path) as store:
        store.load_into(correlator)

    state = correlator.get_or_create("AAPL")
    assert state.latest_signal is not None  # would be None without persistence
    assert state.latest_report is None  # report genuinely hasn't arrived yet


def test_multiple_tickers_are_independent(tmp_path):
    path = tmp_path / "core_state.db"
    aapl_signal = _signal()
    nvda_signal = QuantSignal(
        ticker="NVDA",
        signal_type=SignalType.MACD_BULLISH_CROSS,
        direction=SignalDirection.BULLISH,
        message="MACD cross",
        price=900.0,
        bar_timestamp=NOW,
    )
    with TickerStateStore(path) as store:
        store.save_signal("AAPL", aapl_signal, NOW)
        store.save_signal("NVDA", nvda_signal, NOW)

    correlator = TickerCorrelator()
    with TickerStateStore(path) as store:
        loaded = store.load_into(correlator)

    assert loaded == 2
    assert correlator.get_or_create("AAPL").latest_signal.ticker == "AAPL"
    assert correlator.get_or_create("NVDA").latest_signal.ticker == "NVDA"
