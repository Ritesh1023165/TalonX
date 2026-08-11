"""
tests/test_eod_report.py
------------------------------
Tests generate_eod_report.build_report()/render_markdown() against
seeded tmp_path stores (AuditStore, PaperTradingStore,
TickerWatchlistStore) -- no CLI, no real filesystem output beyond the
stores themselves. Covers exactly the scenario this feature exists for:
a ticker with a full BUY->SELL cycle vs. a ticker whose alerts were all
ignored for lack of an open position (the GOOGL/IBM/MSTR case), plus a
ticker with no alerts at all and the day-boundary edge.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from generate_eod_report import build_report, render_markdown
from talonx_brain.store import BrainStatsStore
from talonx_core.store import TickerStateStore
from talonx_dispatch.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    ResearchVerdict,
    SignalDirection,
    TriggeringSignalRef,
)
from talonx_dispatch.store import AuditStore
from talonx_paper.schemas import AlertAction as PaperAlertAction
from talonx_paper.store import PaperTradingStore
from talonx_quant.store import QuantStateStore
from talonx_watchlist.store import TickerWatchlistStore

TZ = "America/New_York"
# Noon Eastern, safely inside 2026-08-11's local calendar day regardless
# of DST bookkeeping.
NOON_ET = datetime(2026, 8, 11, 16, 0, 0, tzinfo=timezone.utc)


def _alert(ticker: str, action: AlertAction, correlated_at: datetime = NOON_ET) -> ActionableAlert:
    return ActionableAlert(
        ticker=ticker,
        action=action,
        severity=AlertSeverity.WARNING,
        rationale="rationale text",
        quant_direction=SignalDirection.BULLISH,
        research_verdict=ResearchVerdict.BULLISH,
        research_confidence=0.75,
        triggering_signal=TriggeringSignalRef(
            ticker=ticker, signal_type="rsi_oversold_volume_surge",
            direction=SignalDirection.BULLISH, message="msg", price=100.0, bar_timestamp=correlated_at,
        ),
        research_summary="summary",
        model_used="gemini-flash-latest",
        signal_received_at=correlated_at,
        report_received_at=correlated_at,
        correlated_at=correlated_at,
        published_at=correlated_at,
    )


def _stores(tmp_path):
    audit = AuditStore(tmp_path / "audit.db")
    paper = PaperTradingStore(tmp_path / "paper.db")
    watchlist = TickerWatchlistStore(tmp_path / "watchlist.db")
    return audit, paper, watchlist


def test_ticker_with_a_full_trade_cycle(tmp_path):
    audit, paper, watchlist = _stores(tmp_path)
    watchlist.add_ticker("MSFT", "Microsoft Corporation")
    watchlist.set_paper_trading("MSFT", True)
    audit.record_alert(_alert("MSFT", AlertAction.CONFIRMED_BULLISH))
    audit.record_alert(_alert("MSFT", AlertAction.CONTRADICTED))
    paper.execute_buy("MSFT", shares=5.0, price=100.0, cost=500.0, timestamp=NOON_ET)
    paper.execute_sell("MSFT", exit_price=110.0, timestamp=NOON_ET, triggering_action=PaperAlertAction.CONTRADICTED)

    report = build_report("2026-08-11", audit, paper, watchlist, tz_name=TZ)

    section = next(s for s in report.ticker_sections if s.ticker == "MSFT")
    assert section.paper_trading_enabled is True
    assert len(section.trades) == 2
    assert "BUY" in section.verdict and "SELL" in section.verdict
    assert report.total_trades_executed == 2


def test_ticker_with_only_ignored_alerts_explains_why(tmp_path):
    """The GOOGL/IBM/MSTR case: alerts fired, paper trading is enabled,
    but every alert was a SELL trigger with no position ever opened."""
    audit, paper, watchlist = _stores(tmp_path)
    watchlist.add_ticker("GOOGL", "Alphabet Inc.")
    watchlist.set_paper_trading("GOOGL", True)
    audit.record_alert(_alert("GOOGL", AlertAction.CONFIRMED_BEARISH))
    audit.record_alert(_alert("GOOGL", AlertAction.CONTRADICTED))
    paper.record_ignored("GOOGL", "NO_ACTIVE_POSITION", PaperAlertAction.CONFIRMED_BEARISH, 100.0, NOON_ET)
    paper.record_ignored("GOOGL", "NO_ACTIVE_POSITION", PaperAlertAction.CONTRADICTED, 101.0, NOON_ET)

    report = build_report("2026-08-11", audit, paper, watchlist, tz_name=TZ)

    section = next(s for s in report.ticker_sections if s.ticker == "GOOGL")
    assert section.trades == []
    assert section.ignored_counts == {"NO_ACTIVE_POSITION": 2}
    assert "No trade today" in section.verdict
    assert "NO_ACTIVE_POSITION" in section.verdict
    assert report.total_trades_ignored == 2


def test_ticker_with_no_alerts_at_all(tmp_path):
    audit, paper, watchlist = _stores(tmp_path)
    watchlist.add_ticker("IBM", "IBM Corp")
    watchlist.set_paper_trading("IBM", True)

    report = build_report("2026-08-11", audit, paper, watchlist, tz_name=TZ)

    section = next(s for s in report.ticker_sections if s.ticker == "IBM")
    assert section.verdict == "No alerts today."


def test_ticker_without_paper_trading_enabled(tmp_path):
    audit, paper, watchlist = _stores(tmp_path)
    watchlist.add_ticker("AAPL", "Apple Inc.")
    audit.record_alert(_alert("AAPL", AlertAction.CONFIRMED_BULLISH))

    report = build_report("2026-08-11", audit, paper, watchlist, tz_name=TZ)

    section = next(s for s in report.ticker_sections if s.ticker == "AAPL")
    assert section.paper_trading_enabled is False
    assert section.verdict == "Paper trading not enabled for this ticker."


def test_day_boundary_excludes_alerts_from_adjacent_days(tmp_path):
    audit, paper, watchlist = _stores(tmp_path)
    watchlist.add_ticker("MSFT", "Microsoft Corporation")
    # 2026-08-11 local (America/New_York, EDT = UTC-4) is [2026-08-11T04:00,
    # 2026-08-12T04:00) UTC. Every real timestamp in this codebase is
    # UTC-aware (datetime.now(timezone.utc)) -- the stores compare raw ISO
    # strings, which only sorts correctly when every stored offset is
    # consistently +00:00, so these boundary probes stay in UTC too rather
    # than a fixed local offset.
    before = datetime(2026, 8, 11, 3, 59, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 12, 4, 0, 1, tzinfo=timezone.utc)
    audit.record_alert(_alert("MSFT", AlertAction.CONFIRMED_BULLISH, correlated_at=before))
    audit.record_alert(_alert("MSFT", AlertAction.CONFIRMED_BULLISH, correlated_at=after))

    report = build_report("2026-08-11", audit, paper, watchlist, tz_name=TZ)

    assert report.total_alerts == 0


# --- Phase 2: signal funnel + LLM/cache economics --------------------------

def test_phase2_unavailable_when_no_stats_stores_given(tmp_path):
    audit, paper, watchlist = _stores(tmp_path)
    watchlist.add_ticker("MSFT", "Microsoft Corporation")

    report = build_report("2026-08-11", audit, paper, watchlist, tz_name=TZ)

    assert report.phase2_available is False
    text = render_markdown(report)
    assert "Not available" in text


def test_phase2_populates_the_signal_funnel_and_llm_economics(tmp_path):
    audit, paper, watchlist = _stores(tmp_path)
    watchlist.add_ticker("GOOGL", "Alphabet Inc.")
    watchlist.set_paper_trading("GOOGL", True)
    audit.record_alert(_alert("GOOGL", AlertAction.CONFIRMED_BEARISH))

    core_store = TickerStateStore(tmp_path / "core_state.db")
    quant_store = QuantStateStore(tmp_path / "quant.db")
    brain_store = BrainStatsStore(tmp_path / "brain.db")
    try:
        quant_store.record_suppressed("GOOGL", "THROTTLE", 2, NOON_ET)
        core_store.record_suppressed("GOOGL", "COOLDOWN", NOON_ET)
        brain_store.record_report("GOOGL", "cache_hit", NOON_ET)
        brain_store.record_report("GOOGL", "llm_call", NOON_ET)

        report = build_report(
            "2026-08-11", audit, paper, watchlist, tz_name=TZ,
            core_store=core_store, quant_store=quant_store, brain_store=brain_store,
        )
    finally:
        core_store.close()
        quant_store.close()
        brain_store.close()

    assert report.phase2_available is True
    section = next(s for s in report.ticker_sections if s.ticker == "GOOGL")
    assert section.quant_suppressed == {"THROTTLE": 2}
    assert section.core_suppressed == {"COOLDOWN": 1}
    assert section.brain_categories == {"cache_hit": 1, "llm_call": 1}

    text = render_markdown(report)
    assert "talonx_quant suppressed: THROTTLE x2" in text
    assert "talonx_core suppressed: COOLDOWN x1" in text
    assert "## LLM / cache economics" in text
    assert "cache_hit: 1" in text
    assert "llm_call: 1" in text


def test_phase2_ticker_only_present_in_a_stats_store_still_gets_a_section(tmp_path):
    """A ticker that talonx_quant suppressed signals for but that never
    reached an alert (and isn't even on the watchlist yet) should still
    surface -- not be silently dropped from the report."""
    audit, paper, watchlist = _stores(tmp_path)

    quant_store = QuantStateStore(tmp_path / "quant.db")
    try:
        quant_store.record_suppressed("ORPHAN", "COOLDOWN", 5, NOON_ET)
        report = build_report(
            "2026-08-11", audit, paper, watchlist, tz_name=TZ, quant_store=quant_store,
        )
    finally:
        quant_store.close()

    section = next(s for s in report.ticker_sections if s.ticker == "ORPHAN")
    assert section.quant_suppressed == {"COOLDOWN": 5}


def test_render_markdown_includes_key_sections(tmp_path):
    audit, paper, watchlist = _stores(tmp_path)
    watchlist.add_ticker("MSFT", "Microsoft Corporation")
    watchlist.set_paper_trading("MSFT", True)
    audit.record_alert(_alert("MSFT", AlertAction.CONFIRMED_BULLISH))

    report = build_report("2026-08-11", audit, paper, watchlist, tz_name=TZ)
    text = render_markdown(report)

    assert "# TalonX End-of-Day Report -- 2026-08-11" in text
    assert "## Executive summary" in text
    assert "## Per-ticker breakdown" in text
    assert "### MSFT" in text
    assert "## Alert log appendix" in text
