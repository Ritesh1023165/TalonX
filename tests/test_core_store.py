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
    FundamentalFactorSignal,
    LongTermResearchReport,
    MoatRating,
    QuantSignal,
    ResearchReport,
    ResearchVerdict,
    SignalDirection,
    SignalType,
)
from talonx_core.state import LongTermTickerCorrelator, TickerCorrelator
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


# --- Phase 2 LONG_TERM path -------------------------------------------------

def _fundamental_signal() -> FundamentalFactorSignal:
    return FundamentalFactorSignal(
        ticker="AAPL", fiscal_year=2025, roic=0.20, piotroski_f_score=8,
        fcf_yield=0.05, altman_z_score=5.0, debt_to_ebitda_proxy=2.0,
        price=100.0, message="ROIC clears threshold", computed_at=NOW,
    )


def _long_term_report() -> LongTermResearchReport:
    return LongTermResearchReport(
        ticker="AAPL", triggering_signal=_fundamental_signal(), moat_rating=MoatRating.WIDE,
        capital_allocation_assessment="disciplined", dcf_fair_value_per_share=120.0,
        quality_score=8, summary="Durable compounder.", model_used="gemini-flash-latest",
        generated_at=NOW, published_at=NOW,
    )


def test_load_into_long_term_empty_store_loads_nothing(tmp_path):
    store = TickerStateStore(tmp_path / "core_state.db")
    correlator = LongTermTickerCorrelator()
    assert store.load_into_long_term(correlator) == 0
    store.close()


def test_save_fundamental_signal_then_load_rehydrates_it(tmp_path):
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_fundamental_signal("AAPL", _fundamental_signal(), NOW)

    correlator = LongTermTickerCorrelator()
    with TickerStateStore(path) as store:
        loaded = store.load_into_long_term(correlator)

    assert loaded == 1
    state = correlator.get_or_create("AAPL")
    assert state.fundamental_signal == _fundamental_signal()
    assert state.fundamental_signal_at == NOW
    assert state.longterm_report is None


def test_long_term_signal_and_report_dont_clobber_each_other(tmp_path):
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_fundamental_signal("AAPL", _fundamental_signal(), NOW)
        store.save_long_term_report("AAPL", _long_term_report(), NOW + timedelta(seconds=30))

    correlator = LongTermTickerCorrelator()
    with TickerStateStore(path) as store:
        store.load_into_long_term(correlator)

    state = correlator.get_or_create("AAPL")
    assert state.fundamental_signal is not None
    assert state.longterm_report is not None


def test_save_long_term_alert_then_load_rehydrates_cooldown(tmp_path):
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_long_term_alert("AAPL", NOW, AlertAction.HIGH_CONVICTION_BUY, 100.0)

    correlator = LongTermTickerCorrelator()
    with TickerStateStore(path) as store:
        store.load_into_long_term(correlator)

    state = correlator.get_or_create("AAPL")
    assert state.last_alert_at == NOW
    assert state.last_alert_action == AlertAction.HIGH_CONVICTION_BUY
    assert state.last_alert_price == 100.0


def test_intraday_and_long_term_state_are_fully_independent_tables(tmp_path):
    """The core DUAL_HORIZON safety property: saving both an intraday and
    a long-term state for the SAME ticker must never collide."""
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_signal("AAPL", _signal(), NOW)
        store.save_fundamental_signal("AAPL", _fundamental_signal(), NOW)

    intraday = TickerCorrelator()
    long_term = LongTermTickerCorrelator()
    with TickerStateStore(path) as store:
        store.load_into(intraday)
        store.load_into_long_term(long_term)

    assert intraday.get_or_create("AAPL").latest_signal.ticker == "AAPL"
    assert long_term.get_or_create("AAPL").fundamental_signal.ticker == "AAPL"


def test_fundamental_stop_state_persists_across_restart(tmp_path):
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_long_term_fundamental_stop_state("AAPL", 2, MoatRating.NARROW)

    correlator = LongTermTickerCorrelator()
    with TickerStateStore(path) as store:
        store.load_into_long_term(correlator)

    state = correlator.get_or_create("AAPL")
    assert state.roic_below_wacc_streak == 2
    assert state.previous_moat_rating == MoatRating.NARROW


def test_fundamental_stop_state_defaults_when_never_saved(tmp_path):
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_fundamental_signal("AAPL", _fundamental_signal(), NOW)

    correlator = LongTermTickerCorrelator()
    with TickerStateStore(path) as store:
        store.load_into_long_term(correlator)

    state = correlator.get_or_create("AAPL")
    assert state.roic_below_wacc_streak == 0
    assert state.previous_moat_rating is None


def test_fundamental_stop_state_persists_last_streak_fiscal_year_and_previous_fair_value(tmp_path):
    """Restart-survival fix: these two fields are captured on
    LongTermTickerState at the SAME moments as roic_below_wacc_streak/
    previous_moat_rating, but were originally never persisted -- a
    restart between two same-fiscal-year signal arrivals (e.g. an
    Earnings Radar Stage-1 8-K republish reusing a cached ROIC) would
    silently reset last_streak_fiscal_year to None, defeating the
    dedupe guard in LongTermTickerCorrelator.update_signal and risking a
    false UNDER_PERFORM_REBALANCE trip from double-counting one real
    data point."""
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        store.save_long_term_fundamental_stop_state(
            "AAPL", 2, MoatRating.NARROW, last_streak_fiscal_year=2025, previous_fair_value=210.0,
        )

    correlator = LongTermTickerCorrelator()
    with TickerStateStore(path) as store:
        store.load_into_long_term(correlator)

    state = correlator.get_or_create("AAPL")
    assert state.last_streak_fiscal_year == 2025
    assert state.previous_fair_value == 210.0


def test_fundamental_stop_state_dedupe_guard_survives_a_restart():
    """End-to-end: without the fix, update_signal() re-processing the
    SAME fiscal year after a simulated restart would double-bump the
    streak (2 instead of 1) because last_streak_fiscal_year reset to
    None. With state correctly rehydrated, the dedupe guard holds."""
    correlator = LongTermTickerCorrelator()
    signal = FundamentalFactorSignal(
        ticker="AAPL", fiscal_year=2025, roic=0.05, piotroski_f_score=8,  # roic below assumed WACC
        fcf_yield=0.05, altman_z_score=5.0, debt_to_ebitda_proxy=2.0,
        price=100.0, message="ROIC below WACC", computed_at=NOW,
    )
    correlator.update_signal(signal, wacc=0.10)
    state = correlator.get_or_create("AAPL")
    assert state.roic_below_wacc_streak == 1
    assert state.last_streak_fiscal_year == 2025

    # Simulate a restart: rehydrate a FRESH correlator from exactly what
    # would have been persisted (last_streak_fiscal_year included).
    fresh_correlator = LongTermTickerCorrelator()
    fresh_state = fresh_correlator.get_or_create("AAPL")
    fresh_state.roic_below_wacc_streak = state.roic_below_wacc_streak
    fresh_state.last_streak_fiscal_year = state.last_streak_fiscal_year

    # The SAME fiscal year's signal republished (Earnings Radar Stage 1)
    # after the "restart" -- must be deduped, not double-counted.
    fresh_correlator.update_signal(signal, wacc=0.10)
    assert fresh_correlator.get_or_create("AAPL").roic_below_wacc_streak == 1


# --- suppression_counts horizon dimension + migration -----------------------

def test_record_suppressed_defaults_to_intraday_horizon(tmp_path):
    with TickerStateStore(tmp_path / "core_state.db") as store:
        store.record_suppressed("AAPL", "COOLDOWN", NOW)
        assert store.suppression_counts_for_date("2026-08-07")[0]["horizon"] == "intraday"


def test_intraday_and_long_term_suppression_counts_stay_separate(tmp_path):
    with TickerStateStore(tmp_path / "core_state.db") as store:
        store.record_suppressed("AAPL", "COOLDOWN", NOW, horizon="intraday")
        store.record_suppressed("AAPL", "COOLDOWN", NOW, horizon="long_term")

        rows = {r["horizon"]: r["count"] for r in store.suppression_counts_for_date("2026-08-07")}
        assert rows == {"intraday": 1, "long_term": 1}


def test_migrates_a_pre_existing_suppression_counts_table_without_horizon(tmp_path):
    """Same rebuild-migration regression coverage as
    test_brain_store.py's report_counts test -- a pre-Phase-2
    suppression_counts table has a narrower 3-column PRIMARY KEY that
    would otherwise reject a DUAL_HORIZON ticker's second, long_term row
    for the same date/ticker/reason."""
    import sqlite3

    db_path = tmp_path / "legacy_core_state.db"
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
        "CREATE TABLE ticker_state (ticker TEXT PRIMARY KEY, signal_json TEXT, signal_at TEXT, "
        "report_json TEXT, report_at TEXT, last_alert_at TEXT, last_alert_action TEXT, last_alert_price REAL)"
    )
    legacy_conn.execute(
        "CREATE TABLE suppression_counts (date TEXT NOT NULL, ticker TEXT NOT NULL, reason TEXT NOT NULL, "
        "count INTEGER NOT NULL DEFAULT 0, last_seen_at TEXT NOT NULL, PRIMARY KEY (date, ticker, reason))"
    )
    legacy_conn.execute(
        "INSERT INTO suppression_counts (date, ticker, reason, count, last_seen_at) "
        "VALUES ('2026-08-07', 'AAPL', 'COOLDOWN', 5, ?)",
        (NOW.isoformat(),),
    )
    legacy_conn.commit()
    legacy_conn.close()

    with TickerStateStore(db_path) as store:
        rows = store.suppression_counts_for_date("2026-08-07")
        assert len(rows) == 1
        assert rows[0]["horizon"] == "intraday"
        assert rows[0]["count"] == 5

        store.record_suppressed("AAPL", "COOLDOWN", NOW, horizon="long_term")
        rows = {r["horizon"]: r["count"] for r in store.suppression_counts_for_date("2026-08-07")}
        assert rows == {"intraday": 5, "long_term": 1}
