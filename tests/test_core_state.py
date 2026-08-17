"""
tests/test_core_state.py
------------------------------
Direct tests of talonx_core.state.LongTermTickerCorrelator -- specifically
update_signal's fiscal-year streak dedupe and update_report's
previous_fair_value capture, both added for the Event-Driven Earnings
Radar. Pure in-memory logic, no I/O.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_core.schemas import FundamentalFactorSignal, LongTermResearchReport, MoatRating
from talonx_core.state import LongTermTickerCorrelator

NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)


def _signal(fiscal_year: int = 2025, roic: float = 0.05, is_earnings_related: bool = False) -> FundamentalFactorSignal:
    return FundamentalFactorSignal(
        ticker="AAPL", fiscal_year=fiscal_year, roic=roic, piotroski_f_score=8,
        fcf_yield=0.05, altman_z_score=5.0, debt_to_ebitda_proxy=2.0,
        price=100.0, message="test signal", computed_at=NOW,
        is_earnings_related=is_earnings_related,
    )


def _report(fair_value: float = 100.0) -> LongTermResearchReport:
    return LongTermResearchReport(
        ticker="AAPL", triggering_signal=_signal(),
        moat_rating=MoatRating.WIDE, capital_allocation_assessment="disciplined",
        dcf_fair_value_per_share=fair_value, quality_score=8,
        summary="Durable compounder.", model_used="gemini-flash-latest",
        generated_at=NOW, published_at=NOW,
    )


# --- update_signal: fiscal-year streak dedupe -------------------------------

def test_streak_increments_on_a_genuinely_new_fiscal_year_below_wacc():
    correlator = LongTermTickerCorrelator()
    correlator.update_signal(_signal(fiscal_year=2024, roic=0.05), wacc=0.09)
    correlator.update_signal(_signal(fiscal_year=2025, roic=0.05), wacc=0.09)

    assert correlator.get_or_create("AAPL").roic_below_wacc_streak == 2


def test_streak_does_not_double_count_a_republish_of_the_same_fiscal_year():
    """Event-Driven Earnings Radar regression: a Stage 1 (8-K) republish
    reuses the SAME cached ROIC already counted once at its original
    publish -- without the dedupe, republishing it would increment the
    streak a second time for one underlying data point."""
    correlator = LongTermTickerCorrelator()
    correlator.update_signal(_signal(fiscal_year=2025, roic=0.05), wacc=0.09)
    # Same fiscal year republished (e.g. the earnings-triggered path) --
    # must NOT bump the streak again.
    correlator.update_signal(_signal(fiscal_year=2025, roic=0.05, is_earnings_related=True), wacc=0.09)

    assert correlator.get_or_create("AAPL").roic_below_wacc_streak == 1


def test_streak_resets_when_a_new_fiscal_year_clears_wacc():
    correlator = LongTermTickerCorrelator()
    correlator.update_signal(_signal(fiscal_year=2024, roic=0.05), wacc=0.09)
    correlator.update_signal(_signal(fiscal_year=2025, roic=0.20), wacc=0.09)

    assert correlator.get_or_create("AAPL").roic_below_wacc_streak == 0


def test_streak_tracking_is_per_ticker():
    correlator = LongTermTickerCorrelator()
    aapl_signal = _signal(fiscal_year=2025, roic=0.05).model_copy(update={"ticker": "AAPL"})
    msft_signal = _signal(fiscal_year=2025, roic=0.05).model_copy(update={"ticker": "MSFT"})
    correlator.update_signal(aapl_signal, wacc=0.09)
    correlator.update_signal(msft_signal, wacc=0.09)

    assert correlator.get_or_create("AAPL").roic_below_wacc_streak == 1
    assert correlator.get_or_create("MSFT").roic_below_wacc_streak == 1


# --- update_report: previous_fair_value capture -----------------------------

def test_previous_fair_value_is_none_before_any_second_report():
    correlator = LongTermTickerCorrelator()
    correlator.update_report(_report(fair_value=100.0))

    assert correlator.get_or_create("AAPL").previous_fair_value is None


def test_previous_fair_value_captures_the_outgoing_reports_value():
    correlator = LongTermTickerCorrelator()
    correlator.update_report(_report(fair_value=210.0))
    correlator.update_report(_report(fair_value=225.0))

    state = correlator.get_or_create("AAPL")
    assert state.previous_fair_value == 210.0
    assert state.longterm_report.dcf_fair_value_per_share == 225.0


def test_previous_moat_rating_and_previous_fair_value_captured_together():
    correlator = LongTermTickerCorrelator()
    old = _report(fair_value=210.0).model_copy(update={"moat_rating": MoatRating.NARROW})
    new = _report(fair_value=225.0).model_copy(update={"moat_rating": MoatRating.WIDE})
    correlator.update_report(old)
    correlator.update_report(new)

    state = correlator.get_or_create("AAPL")
    assert state.previous_moat_rating == MoatRating.NARROW
    assert state.previous_fair_value == 210.0
