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

from talonx_core.schemas import (
    AlertAction,
    QuantSignal,
    ResearchReport,
    ResearchVerdict,
    SignalDirection,
    SignalType,
)
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
        store.save_alert("AAPL", NOW + timedelta(seconds=5), AlertAction.CONFIRMED_BULLISH, 200.0)

    correlator = TickerCorrelator()
    with TickerStateStore(path) as store:
        store.load_into(correlator)

    state = correlator.get_or_create("AAPL")
    assert state.last_alert_at == NOW + timedelta(seconds=5)
    assert state.last_alert_action == AlertAction.CONFIRMED_BULLISH
    assert state.last_alert_price == 200.0


def test_migrates_a_pre_existing_ticker_state_db_without_alert_action_price(tmp_path):
    """Regression coverage for the ALTER TABLE migration, same pattern as
    talonx_watchlist/store.py's equivalent test -- a pre-existing
    core_state.db from before last_alert_action/last_alert_price existed
    must upgrade in place, not error."""
    import sqlite3

    path = tmp_path / "legacy_core_state.db"
    legacy_conn = sqlite3.connect(path)
    legacy_conn.execute(
        "CREATE TABLE ticker_state (ticker TEXT PRIMARY KEY, signal_json TEXT, "
        "signal_at TEXT, report_json TEXT, report_at TEXT, last_alert_at TEXT)"
    )
    legacy_conn.execute(
        "INSERT INTO ticker_state (ticker, last_alert_at) VALUES ('AAPL', ?)",
        (NOW.isoformat(),),
    )
    legacy_conn.commit()
    legacy_conn.close()

    with TickerStateStore(path) as store:
        correlator = TickerCorrelator()
        store.load_into(correlator)
        state = correlator.get_or_create("AAPL")
        assert state.last_alert_at == NOW
        assert state.last_alert_action is None
        assert state.last_alert_price is None

        # And the migrated store is fully usable afterward.
        store.save_alert("AAPL", NOW, AlertAction.CONTRADICTED, 150.0)


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


# --- Suppression counts (the EOD report's signal-funnel section) ----------

def test_record_suppressed_creates_a_counter_row(tmp_path):
    with TickerStateStore(tmp_path / "core_state.db") as store:
        store.record_suppressed("AAPL", "COOLDOWN", NOW)
        rows = store.suppression_counts_for_date("2026-08-07")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"
        assert rows[0]["reason"] == "COOLDOWN"
        assert rows[0]["count"] == 1


def test_record_suppressed_increments_the_same_day_ticker_reason_bucket(tmp_path):
    with TickerStateStore(tmp_path / "core_state.db") as store:
        store.record_suppressed("AAPL", "COOLDOWN", NOW)
        store.record_suppressed("AAPL", "COOLDOWN", NOW + timedelta(minutes=5))
        rows = store.suppression_counts_for_date("2026-08-07")
        assert len(rows) == 1
        assert rows[0]["count"] == 2


def test_record_suppressed_keeps_different_reasons_separate(tmp_path):
    with TickerStateStore(tmp_path / "core_state.db") as store:
        store.record_suppressed("AAPL", "COOLDOWN", NOW)
        store.record_suppressed("AAPL", "LOW_CONFIDENCE", NOW)
        rows = {r["reason"]: r["count"] for r in store.suppression_counts_for_date("2026-08-07")}
        assert rows == {"COOLDOWN": 1, "LOW_CONFIDENCE": 1}


def test_suppression_counts_for_date_excludes_other_days(tmp_path):
    with TickerStateStore(tmp_path / "core_state.db") as store:
        store.record_suppressed("AAPL", "COOLDOWN", NOW)
        store.record_suppressed("AAPL", "COOLDOWN", NOW + timedelta(days=1))
        assert len(store.suppression_counts_for_date("2026-08-07")) == 1
        assert len(store.suppression_counts_for_date("2026-08-08")) == 1


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
