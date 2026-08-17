"""
talonx_quant.fundamentals
------------------------------
Pure factor-scoring functions for Phase 2's LONG_TERM pipeline -- no I/O,
same testability philosophy as talonx_quant.indicators/strategy for the
intraday side. Each function takes FinancialStatementFacts (this
module's own trimmed mirror, see schemas.py) and returns a single score,
or None when the fields it needs aren't available (a partial XBRL
extraction, not an error -- see edgar/financials.py's own docstring on
why some fiscal years/fields come back missing).

Two of these formulas are ADAPTED from their textbook definitions
because the fields this project's SEC XBRL extraction produces don't
include everything the "real" formula wants (no current assets/current
liabilities/total liabilities breakdown, just the handful of concepts
edgar/financials.py extracts) -- each substitution is called out
explicitly in that function's docstring, not silently approximated.
"""
from __future__ import annotations

from talonx_quant.schemas import FinancialStatementFacts

# US federal statutory corporate tax rate -- used as NOPAT's assumed tax
# rate since this project's XBRL extraction doesn't pull an
# effective-tax-rate figure per company/year. Same "documented assumed
# constant" treatment as talonx_core's TALONX_CORE_LT_ASSUMED_WACC.
_ASSUMED_TAX_RATE = 0.21


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def compute_roic(facts: FinancialStatementFacts, tax_rate: float = _ASSUMED_TAX_RATE) -> float | None:
    """ROIC = NOPAT / (Total Debt + Total Equity - Cash), per the spec.
    NOPAT = Operating Income * (1 - tax_rate) -- an assumed flat tax
    rate stands in for an effective-tax-rate figure this project doesn't
    extract per company/year."""
    if facts.operating_income is None or facts.total_debt is None or facts.total_equity is None \
            or facts.cash_and_equivalents is None:
        return None
    invested_capital = facts.total_debt + facts.total_equity - facts.cash_and_equivalents
    if invested_capital <= 0:
        return None
    nopat = facts.operating_income * (1 - tax_rate)
    return nopat / invested_capital


def compute_piotroski_f_score(current: FinancialStatementFacts, prior: FinancialStatementFacts) -> int:
    """
    0-9 integer score, one point per check, missing data conservatively
    scores 0 (not awarded) rather than raising. ADAPTED from the
    textbook 9-signal Piotroski F-Score: the original's current-ratio
    and gross-margin checks need current assets/current liabilities/COGS,
    none of which this project's XBRL extraction pulls -- replaced below
    with the closest available signal in the same profitability/leverage/
    efficiency spirit (documented per check, not silently swapped).

    1. Positive net income
    2. Positive operating cash flow
    3. Net income increased year over year
    4. Quality of earnings -- operating cash flow exceeds net income
       (earnings backed by real cash, not just accruals)
    5. Leverage (debt/equity) decreased year over year
    6. No share dilution -- shares outstanding did not increase
    7. Operating margin (operating income / revenue) increased year over year
    8. Revenue increased year over year
       (ADAPTED -- textbook check is asset turnover, needs total assets
       history; revenue growth is used as the closest efficiency/growth
       proxy available)
    9. Positive free cash flow (operating cash flow - capex > 0)
       (ADAPTED -- textbook check is current-ratio improvement, needs
       current assets/liabilities; FCF positivity is used instead as a
       liquidity/self-funding signal)
    """
    score = 0

    if current.net_income is not None and current.net_income > 0:
        score += 1
    if current.operating_cash_flow is not None and current.operating_cash_flow > 0:
        score += 1
    if current.net_income is not None and prior.net_income is not None and current.net_income > prior.net_income:
        score += 1
    if current.operating_cash_flow is not None and current.net_income is not None \
            and current.operating_cash_flow > current.net_income:
        score += 1

    current_leverage = _safe_ratio(current.total_debt, current.total_equity)
    prior_leverage = _safe_ratio(prior.total_debt, prior.total_equity)
    if current_leverage is not None and prior_leverage is not None and current_leverage < prior_leverage:
        score += 1

    if current.shares_outstanding is not None and prior.shares_outstanding is not None \
            and current.shares_outstanding <= prior.shares_outstanding:
        score += 1

    current_margin = _safe_ratio(current.operating_income, current.revenue)
    prior_margin = _safe_ratio(prior.operating_income, prior.revenue)
    if current_margin is not None and prior_margin is not None and current_margin > prior_margin:
        score += 1

    if current.revenue is not None and prior.revenue is not None and current.revenue > prior.revenue:
        score += 1

    if current.operating_cash_flow is not None and current.capex is not None \
            and (current.operating_cash_flow - current.capex) > 0:
        score += 1

    return score


def compute_fcf_yield(facts: FinancialStatementFacts, market_price: float) -> float | None:
    """FCF Yield = (Operating Cash Flow - CapEx) / Enterprise Value, per
    the spec. Enterprise Value = Market Cap + Total Debt - Cash."""
    if facts.operating_cash_flow is None or facts.capex is None or facts.shares_outstanding is None \
            or facts.total_debt is None or facts.cash_and_equivalents is None:
        return None
    if market_price <= 0:
        return None
    fcf = facts.operating_cash_flow - facts.capex
    market_cap = market_price * facts.shares_outstanding
    enterprise_value = market_cap + facts.total_debt - facts.cash_and_equivalents
    if enterprise_value <= 0:
        return None
    return fcf / enterprise_value


def compute_debt_to_ebitda_proxy(facts: FinancialStatementFacts) -> float | None:
    """Debt / EBITDA -- talonx_core's fundamental-stop rule needs this
    (spec: "Debt-to-EBITDA exceeds 4.0x"), but this project's XBRL
    extraction doesn't pull depreciation & amortization anywhere, so
    there's no real EBITDA to divide by. ADAPTED: operating_income
    stands in for EBITDA (the same EBIT proxy already used in
    compute_altman_z_score's component C) -- this UNDERSTATES the true
    ratio (real EBITDA = operating income + D&A is always >= operating
    income for a company with any depreciable assets), so this proxy is
    conservative in the "looks more leveraged than it really is"
    direction, not the dangerous "looks safer than it really is" one."""
    if facts.total_debt is None or facts.operating_income is None or facts.operating_income <= 0:
        return None
    return facts.total_debt / facts.operating_income


def compute_altman_z_score(facts: FinancialStatementFacts, market_price: float) -> float | None:
    """
    Z = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E, the standard public-company
    Altman Z-Score formula. TWO of the five components are ADAPTED
    because this project's XBRL extraction doesn't pull current assets/
    current liabilities/total liabilities:

      A = Cash & Equivalents / Total Assets
          (ADAPTED -- textbook is Working Capital / Total Assets; cash is
          working capital's most liquid component and stands in as a
          liquidity proxy)
      B = Retained Earnings / Total Assets           (exact)
      C = Operating Income / Total Assets             (EBIT proxy, exact enough --
          operating income excludes only non-operating items EBIT also excludes)
      D = Market Value of Equity / Total Debt
          (ADAPTED -- textbook denominator is Total Liabilities; total_debt
          understates it, since real total liabilities also include
          accounts payable/accrued/deferred revenue, but captures the
          same leverage dimension the ratio is meant to measure)
      E = Revenue / Total Assets                       (exact)

    Returns None if total_debt is zero (component D is undefined for a
    debt-free company under this proxy) or any required field is missing.
    """
    required = (
        facts.cash_and_equivalents, facts.total_assets, facts.retained_earnings,
        facts.operating_income, facts.total_debt, facts.revenue, facts.shares_outstanding,
    )
    if any(field is None for field in required):
        return None
    if facts.total_assets <= 0 or facts.total_debt <= 0 or market_price <= 0:
        return None

    a = facts.cash_and_equivalents / facts.total_assets
    b = facts.retained_earnings / facts.total_assets
    c = facts.operating_income / facts.total_assets
    market_value_equity = market_price * facts.shares_outstanding
    d = market_value_equity / facts.total_debt
    e = facts.revenue / facts.total_assets

    return 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e
