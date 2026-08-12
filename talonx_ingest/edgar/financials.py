"""
talonx_ingest.edgar.financials
--------------------------------
Structured (numeric) financial statement extraction, via SEC's XBRL
"company facts" API -- NOT the raw 10-K/HTML text path (edgar/client.py's
get_recent_filings/fetch_documents), which stays purely
unstructured-text-for-RAG as it always has been. This is a second,
parallel data source off the SAME EdgarClient, feeding Phase 2's
LONG_TERM fundamentals pipeline (talonx_quant's ROIC/Piotroski/FCF-Yield/
Altman-Z scoring) rather than ChromaDB.

Company facts (https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json)
returns EVERY XBRL concept a company has ever tagged, across every filing.
Concept tag names are NOT standardized across companies/eras (e.g. revenue
might be tagged `Revenues` or `RevenueFromContractWithCustomerExcludingAssessedTax`
depending on when/how a company adopted ASC 606) -- `_FIELD_CONCEPTS` below
is a fallback chain per field, tried in order, first match wins per fiscal
year. This is a best-effort mapping, not a guarantee every company/year
has every field -- callers should expect partial `FinancialStatementFacts`
rows (missing fields are None) and treat downstream factor math
accordingly (see talonx_quant.fundamentals).

Only ANNUAL (10-K, fiscal_period="FY") facts are extracted -- multi-year
trailing averages (the spec's "5-year average ROIC") are computed
downstream in talonx_quant, this module's job stops at "parse the raw
numbers out."
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class FinancialStatementFacts(BaseModel):
    """One fiscal year's worth of parsed financial statement numbers for
    one company. Fields are None when that concept tag wasn't found for
    that fiscal year under any of its fallback names -- a partial row,
    not an error."""

    ticker: str
    cik: str
    fiscal_year: int
    fiscal_period: str = "FY"
    revenue: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    total_equity: float | None = None
    total_assets: float | None = None
    retained_earnings: float | None = None
    shares_outstanding: float | None = None


# Fallback chains: XBRL concept tag naming varies by company/era. Tried in
# order; the first concept present for a given fiscal year wins.
_FIELD_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    "cash_and_equivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "total_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "total_assets": ("Assets",),
    "retained_earnings": ("RetainedEarningsAccumulatedDeficit",),
}
# Total debt has no single standard tag -- summed from current + noncurrent
# long-term debt when both are present, per fiscal year.
_DEBT_NONCURRENT_CONCEPTS: tuple[str, ...] = ("LongTermDebtNoncurrent",)
_DEBT_CURRENT_CONCEPTS: tuple[str, ...] = ("LongTermDebtCurrent",)
_DEBT_FALLBACK_CONCEPTS: tuple[str, ...] = ("LongTermDebt",)
# Shares outstanding lives under a different XBRL unit ("shares", not "USD").
_SHARES_CONCEPTS: tuple[str, ...] = ("CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding")

_MAX_FISCAL_YEARS = 10


def _annual_values_by_year(concept_facts: dict, unit: str) -> dict[int, float]:
    """For one concept's `facts["us-gaap"][concept]` blob, return
    {fiscal_year: value} restricted to annual (fp="FY") 10-K facts under
    the given unit. When a fiscal year has more than one reported value
    (e.g. a restatement), the most recently FILED one wins."""
    by_year: dict[int, tuple[str, float]] = {}  # fy -> (filed_date, value)
    for entry in concept_facts.get("units", {}).get(unit, []):
        if entry.get("form") != "10-K" or entry.get("fp") != "FY":
            continue
        fy = entry.get("fy")
        val = entry.get("val")
        filed = entry.get("filed", "")
        if fy is None or val is None:
            continue
        existing = by_year.get(fy)
        if existing is None or filed > existing[0]:
            by_year[fy] = (filed, float(val))
    return {fy: val for fy, (_, val) in by_year.items()}


def _first_available(us_gaap: dict, concepts: tuple[str, ...], unit: str = "USD") -> dict[int, float]:
    for concept in concepts:
        facts = us_gaap.get(concept)
        if facts:
            values = _annual_values_by_year(facts, unit)
            if values:
                return values
    return {}


def parse_company_facts(raw_json: dict[str, Any], ticker: str, cik: str) -> list[FinancialStatementFacts]:
    """Parses a raw SEC XBRL company-facts JSON payload (as returned by
    EdgarClient.get_company_facts) into up to 10 years of annual
    FinancialStatementFacts, most recent first. A fiscal year with
    neither revenue nor net_income found under any fallback concept is
    dropped entirely (too little to be a usable row); every other
    missing field is left None rather than dropping the year."""
    us_gaap = raw_json.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return []

    per_field: dict[str, dict[int, float]] = {
        field: _first_available(us_gaap, concepts) for field, concepts in _FIELD_CONCEPTS.items()
    }

    debt_noncurrent = _first_available(us_gaap, _DEBT_NONCURRENT_CONCEPTS)
    debt_current = _first_available(us_gaap, _DEBT_CURRENT_CONCEPTS)
    if debt_noncurrent or debt_current:
        years = set(debt_noncurrent) | set(debt_current)
        per_field["total_debt"] = {
            fy: debt_noncurrent.get(fy, 0.0) + debt_current.get(fy, 0.0) for fy in years
        }
    else:
        per_field["total_debt"] = _first_available(us_gaap, _DEBT_FALLBACK_CONCEPTS)

    per_field["shares_outstanding"] = _first_available(us_gaap, _SHARES_CONCEPTS, unit="shares")

    all_years = {fy for values in per_field.values() for fy in values}
    rows = []
    for fy in all_years:
        if fy not in per_field["revenue"] and fy not in per_field["net_income"]:
            continue  # too little data to be a usable row
        rows.append(
            FinancialStatementFacts(
                ticker=ticker.upper(),
                cik=cik,
                fiscal_year=fy,
                revenue=per_field["revenue"].get(fy),
                operating_income=per_field["operating_income"].get(fy),
                net_income=per_field["net_income"].get(fy),
                operating_cash_flow=per_field["operating_cash_flow"].get(fy),
                capex=per_field["capex"].get(fy),
                total_debt=per_field["total_debt"].get(fy),
                cash_and_equivalents=per_field["cash_and_equivalents"].get(fy),
                total_equity=per_field["total_equity"].get(fy),
                total_assets=per_field["total_assets"].get(fy),
                retained_earnings=per_field["retained_earnings"].get(fy),
                shares_outstanding=per_field["shares_outstanding"].get(fy),
            )
        )

    rows.sort(key=lambda r: r.fiscal_year, reverse=True)
    return rows[:_MAX_FISCAL_YEARS]
