"""
tests/test_quant_fundamentals.py
---------------------------------------
Tests talonx_quant.fundamentals -- pure factor-scoring math for Phase 2's
LONG_TERM pipeline (ROIC, Piotroski F-Score, FCF Yield, Altman Z-Score).
Worked-example numbers, same testability philosophy as
test_quant_strategy.py/test_core_decision.py for this project's other
pure decision/math functions.
"""
from __future__ import annotations

from talonx_quant.fundamentals import (
    compute_altman_z_score,
    compute_debt_to_ebitda_proxy,
    compute_fcf_yield,
    compute_piotroski_f_score,
    compute_roic,
)
from talonx_quant.schemas import FinancialStatementFacts


def _facts(**overrides) -> FinancialStatementFacts:
    defaults = dict(ticker="AAPL", cik="0000320193", fiscal_year=2025)
    defaults.update(overrides)
    return FinancialStatementFacts(**defaults)


# --- compute_roic ------------------------------------------------------------

def test_compute_roic_worked_example():
    facts = _facts(operating_income=100.0, total_debt=200.0, total_equity=300.0, cash_and_equivalents=50.0)
    roic = compute_roic(facts, tax_rate=0.21)
    # NOPAT = 100 * 0.79 = 79; invested capital = 200+300-50 = 450
    assert round(roic, 4) == round(79.0 / 450.0, 4)


def test_compute_roic_returns_none_when_a_required_field_is_missing():
    facts = _facts(operating_income=100.0, total_debt=200.0)  # no equity/cash
    assert compute_roic(facts) is None


def test_compute_roic_returns_none_for_non_positive_invested_capital():
    facts = _facts(operating_income=100.0, total_debt=10.0, total_equity=10.0, cash_and_equivalents=50.0)
    assert compute_roic(facts) is None


# --- compute_piotroski_f_score -----------------------------------------------

def test_piotroski_perfect_score():
    prior = _facts(
        fiscal_year=2024, net_income=50.0, operating_cash_flow=40.0, total_debt=200.0, total_equity=300.0,
        shares_outstanding=1000.0, operating_income=80.0, revenue=700.0, capex=30.0,
    )
    current = _facts(
        fiscal_year=2025, net_income=70.0, operating_cash_flow=90.0, total_debt=150.0, total_equity=350.0,
        shares_outstanding=1000.0, operating_income=120.0, revenue=800.0, capex=30.0,
    )
    # 1. net_income>0 Y  2. OCF>0 Y  3. NI up (70>50) Y  4. OCF>NI (90>70) Y
    # 5. leverage down (150/350=0.4286 < 200/300=0.6667) Y  6. no dilution (equal) Y
    # 7. margin up (120/800=0.15 > 80/700=0.1143) Y  8. revenue up (800>700) Y
    # 9. FCF positive (90-30=60>0) Y
    assert compute_piotroski_f_score(current, prior) == 9


def test_piotroski_zero_score():
    prior = _facts(
        fiscal_year=2024, net_income=100.0, operating_cash_flow=100.0, total_debt=50.0, total_equity=500.0,
        shares_outstanding=1000.0, operating_income=100.0, revenue=1000.0, capex=10.0,
    )
    current = _facts(
        fiscal_year=2025, net_income=-10.0, operating_cash_flow=-5.0, total_debt=400.0, total_equity=200.0,
        shares_outstanding=1500.0, operating_income=40.0, revenue=900.0, capex=50.0,
    )
    # net loss, negative OCF, NI down, leverage way up, diluted, margin
    # down, revenue down, FCF negative -- every check fails EXCEPT #4
    # (OCF exceeds NI, -5 > -10 -- still true even though both are
    # negative; a smaller cash loss than accrued loss is a genuine,
    # if modest, quality-of-earnings signal even in a bad year).
    assert compute_piotroski_f_score(current, prior) == 1


def test_piotroski_missing_prior_data_scores_conservatively_not_a_crash():
    prior = _facts(fiscal_year=2024)  # nothing populated
    current = _facts(fiscal_year=2025, net_income=50.0, operating_cash_flow=60.0, capex=10.0)
    # Only the checks computable from CURRENT-year data alone can pass
    # (positive NI, positive OCF, OCF>NI, positive FCF) -- every check
    # that needs a YoY comparison against `prior` is skipped since prior
    # has nothing populated.
    score = compute_piotroski_f_score(current, prior)
    assert score == 4


# --- compute_fcf_yield --------------------------------------------------------

def test_compute_fcf_yield_worked_example():
    facts = _facts(
        operating_cash_flow=150.0, capex=50.0, shares_outstanding=1000.0,
        total_debt=200.0, cash_and_equivalents=50.0,
    )
    yield_ = compute_fcf_yield(facts, market_price=10.0)
    # FCF = 100; EV = 10*1000 + 200 - 50 = 10150
    assert round(yield_, 6) == round(100.0 / 10150.0, 6)


def test_compute_fcf_yield_returns_none_for_non_positive_price():
    facts = _facts(operating_cash_flow=150.0, capex=50.0, shares_outstanding=1000.0, total_debt=200.0, cash_and_equivalents=50.0)
    assert compute_fcf_yield(facts, market_price=0.0) is None


def test_compute_fcf_yield_returns_none_when_missing_fields():
    facts = _facts(operating_cash_flow=150.0)
    assert compute_fcf_yield(facts, market_price=10.0) is None


# --- compute_altman_z_score ----------------------------------------------------

def test_compute_altman_z_score_worked_example():
    facts = _facts(
        cash_and_equivalents=50.0, total_assets=1000.0, retained_earnings=200.0,
        operating_income=100.0, total_debt=300.0, revenue=800.0, shares_outstanding=100.0,
    )
    z = compute_altman_z_score(facts, market_price=20.0)
    # A=0.05 B=0.2 C=0.1 D=2000/300=6.6667 E=0.8
    # Z = 1.2*0.05 + 1.4*0.2 + 3.3*0.1 + 0.6*6.6667 + 1.0*0.8 = 5.47
    assert round(z, 2) == 5.47


def test_compute_altman_z_score_returns_none_for_debt_free_company():
    facts = _facts(
        cash_and_equivalents=50.0, total_assets=1000.0, retained_earnings=200.0,
        operating_income=100.0, total_debt=0.0, revenue=800.0, shares_outstanding=100.0,
    )
    assert compute_altman_z_score(facts, market_price=20.0) is None


def test_compute_altman_z_score_returns_none_when_missing_fields():
    facts = _facts(total_assets=1000.0)
    assert compute_altman_z_score(facts, market_price=20.0) is None


# --- compute_debt_to_ebitda_proxy ---------------------------------------------

def test_compute_debt_to_ebitda_proxy_worked_example():
    facts = _facts(total_debt=400.0, operating_income=100.0)
    assert compute_debt_to_ebitda_proxy(facts) == 4.0


def test_compute_debt_to_ebitda_proxy_returns_none_for_non_positive_operating_income():
    facts = _facts(total_debt=400.0, operating_income=0.0)
    assert compute_debt_to_ebitda_proxy(facts) is None

    facts = _facts(total_debt=400.0, operating_income=-10.0)
    assert compute_debt_to_ebitda_proxy(facts) is None


def test_compute_debt_to_ebitda_proxy_returns_none_when_missing_fields():
    facts = _facts(total_debt=400.0)
    assert compute_debt_to_ebitda_proxy(facts) is None
