"""
tests/test_edgar_financials.py
-------------------------------------
Tests talonx_ingest.edgar.financials.parse_company_facts -- turning a raw
SEC XBRL "company facts" JSON payload into structured
FinancialStatementFacts rows. No network I/O -- a hand-built fixture
shaped like a real companyfacts response (a subset of concepts/years,
matching the real API's nesting), covering: the concept-tag fallback
chain, annual-only (10-K/FY) filtering, most-recent-filed-wins on a
restated year, the current+noncurrent debt sum, missing-field tolerance,
and the "drop a year with neither revenue nor net_income" rule.
"""
from __future__ import annotations

from talonx_ingest.edgar.financials import FinancialStatementFacts, parse_company_facts


def _usd_facts(*entries: tuple[int, float, str, str]) -> dict:
    """entries: (fiscal_year, value, form, filed_date) -- fp defaults to FY."""
    return {
        "units": {
            "USD": [
                {"fy": fy, "val": val, "form": form, "fp": "FY", "filed": filed}
                for fy, val, form, filed in entries
            ]
        }
    }


def _shares_facts(*entries: tuple[int, float, str, str]) -> dict:
    return {
        "units": {
            "shares": [
                {"fy": fy, "val": val, "form": form, "fp": "FY", "filed": filed}
                for fy, val, form, filed in entries
            ]
        }
    }


def _raw(us_gaap: dict) -> dict:
    return {"cik": 320193, "entityName": "Apple Inc.", "facts": {"us-gaap": us_gaap}}


def test_parses_a_simple_two_year_history():
    raw = _raw({
        "Revenues": _usd_facts((2025, 400_000_000_000, "10-K", "2025-11-01"), (2024, 380_000_000_000, "10-K", "2024-11-01")),
        "NetIncomeLoss": _usd_facts((2025, 95_000_000_000, "10-K", "2025-11-01"), (2024, 90_000_000_000, "10-K", "2024-11-01")),
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert len(rows) == 2
    assert rows[0].fiscal_year == 2025  # most recent first
    assert rows[0].revenue == 400_000_000_000
    assert rows[0].net_income == 95_000_000_000
    assert rows[1].fiscal_year == 2024


def test_falls_back_to_the_next_concept_when_the_first_is_absent():
    # No "Revenues" tag at all -- only the ASC-606-era alternative.
    raw = _raw({
        "RevenueFromContractWithCustomerExcludingAssessedTax": _usd_facts(
            (2025, 400_000_000_000, "10-K", "2025-11-01"),
        ),
        "NetIncomeLoss": _usd_facts((2025, 95_000_000_000, "10-K", "2025-11-01")),
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert rows[0].revenue == 400_000_000_000


def test_ignores_non_annual_and_non_10k_entries():
    raw = _raw({
        "Revenues": {
            "units": {
                "USD": [
                    {"fy": 2025, "val": 400_000_000_000, "form": "10-K", "fp": "FY", "filed": "2025-11-01"},
                    {"fy": 2025, "val": 100_000_000_000, "form": "10-Q", "fp": "Q1", "filed": "2025-02-01"},  # quarterly, skip
                    {"fy": 2025, "val": 400_000_000_000, "form": "10-K/A", "fp": "FY", "filed": "2025-12-01"},  # amendment form, skip
                ]
            }
        },
        "NetIncomeLoss": _usd_facts((2025, 95_000_000_000, "10-K", "2025-11-01")),
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert len(rows) == 1
    assert rows[0].revenue == 400_000_000_000


def test_accepts_20f_and_40f_as_annual_report_forms():
    """Regression coverage for a bug caught live: BABA (Alibaba, a
    foreign private issuer) files its annual report as Form 20-F, not
    10-K -- restricting the annual-form filter to "10-K" alone silently
    discarded BABA's real, complete FY-period data (358 us-gaap concepts
    with genuine annual facts, all tagged under form "20-F")."""
    raw = _raw({
        "Revenues": _usd_facts((2025, 130_000_000_000, "20-F", "2025-07-01")),
        "NetIncomeLoss": _usd_facts((2025, 12_000_000_000, "20-F", "2025-07-01")),
    })
    rows = parse_company_facts(raw, ticker="BABA", cik="0001577552")

    assert len(rows) == 1
    assert rows[0].revenue == 130_000_000_000


def test_accepts_40f_as_an_annual_report_form():
    raw = _raw({
        "Revenues": _usd_facts((2025, 50_000_000_000, "40-F", "2025-03-01")),
        "NetIncomeLoss": _usd_facts((2025, 5_000_000_000, "40-F", "2025-03-01")),
    })
    rows = parse_company_facts(raw, ticker="SHOP", cik="0001594805")

    assert len(rows) == 1
    assert rows[0].revenue == 50_000_000_000


def test_ignores_a_10q_entry_even_when_it_claims_fp_fy():
    """The non-annual-form entries a 20-F/40-F filer would ALSO have
    (their own quarterly reports) must still be rejected -- accepting
    more annual forms must not accidentally widen the quarterly filter."""
    raw = _raw({
        "Revenues": _usd_facts(
            (2025, 130_000_000_000, "20-F", "2025-07-01"),
        ),
        "NetIncomeLoss": _usd_facts((2025, 12_000_000_000, "20-F", "2025-07-01")),
    })
    raw["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        {"fy": 2025, "val": 30_000_000_000, "form": "6-K", "fp": "Q2", "filed": "2025-04-01"},
    )
    rows = parse_company_facts(raw, ticker="BABA", cik="0001577552")

    assert len(rows) == 1
    assert rows[0].revenue == 130_000_000_000  # the annual figure, not the 6-K interim one


def test_restated_year_uses_the_most_recently_filed_value():
    raw = _raw({
        "Revenues": _usd_facts(
            (2024, 380_000_000_000, "10-K", "2024-11-01"),   # original
            (2024, 385_000_000_000, "10-K", "2025-02-15"),   # later restatement, wins
        ),
        "NetIncomeLoss": _usd_facts((2024, 90_000_000_000, "10-K", "2024-11-01")),
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert rows[0].revenue == 385_000_000_000


def test_total_debt_sums_current_and_noncurrent():
    raw = _raw({
        "Revenues": _usd_facts((2025, 400_000_000_000, "10-K", "2025-11-01")),
        "NetIncomeLoss": _usd_facts((2025, 95_000_000_000, "10-K", "2025-11-01")),
        "LongTermDebtNoncurrent": _usd_facts((2025, 80_000_000_000, "10-K", "2025-11-01")),
        "LongTermDebtCurrent": _usd_facts((2025, 10_000_000_000, "10-K", "2025-11-01")),
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert rows[0].total_debt == 90_000_000_000


def test_total_debt_falls_back_to_a_single_long_term_debt_tag():
    raw = _raw({
        "Revenues": _usd_facts((2025, 400_000_000_000, "10-K", "2025-11-01")),
        "NetIncomeLoss": _usd_facts((2025, 95_000_000_000, "10-K", "2025-11-01")),
        "LongTermDebt": _usd_facts((2025, 88_000_000_000, "10-K", "2025-11-01")),
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert rows[0].total_debt == 88_000_000_000


def test_shares_outstanding_is_read_from_the_shares_unit():
    raw = _raw({
        "Revenues": _usd_facts((2025, 400_000_000_000, "10-K", "2025-11-01")),
        "NetIncomeLoss": _usd_facts((2025, 95_000_000_000, "10-K", "2025-11-01")),
        "CommonStockSharesOutstanding": _shares_facts((2025, 15_000_000_000, "10-K", "2025-11-01")),
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert rows[0].shares_outstanding == 15_000_000_000


def test_missing_fields_are_none_not_dropped():
    raw = _raw({
        "Revenues": _usd_facts((2025, 400_000_000_000, "10-K", "2025-11-01")),
        "NetIncomeLoss": _usd_facts((2025, 95_000_000_000, "10-K", "2025-11-01")),
        # No operating_income, capex, debt, cash, equity, or shares tagged at all.
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert len(rows) == 1
    assert rows[0].operating_income is None
    assert rows[0].capex is None
    assert rows[0].total_debt is None


def test_year_with_neither_revenue_nor_net_income_is_dropped():
    raw = _raw({
        "Revenues": _usd_facts((2025, 400_000_000_000, "10-K", "2025-11-01")),
        "NetIncomeLoss": _usd_facts((2025, 95_000_000_000, "10-K", "2025-11-01")),
        # A stray year that only has a capex figure, nothing else -- too
        # little to be a usable row.
        "PaymentsToAcquirePropertyPlantAndEquipment": _usd_facts((2020, 5_000_000_000, "10-K", "2020-11-01")),
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert len(rows) == 1
    assert rows[0].fiscal_year == 2025


def test_caps_at_ten_most_recent_fiscal_years():
    entries = [(year, float(year) * 1_000_000_000, "10-K", f"{year}-11-01") for year in range(2010, 2026)]
    raw = _raw({
        "Revenues": _usd_facts(*entries),
        "NetIncomeLoss": _usd_facts(*entries),
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert len(rows) == 10
    assert rows[0].fiscal_year == 2025
    assert rows[-1].fiscal_year == 2016


def test_total_assets_and_retained_earnings_are_parsed():
    raw = _raw({
        "Revenues": _usd_facts((2025, 400_000_000_000, "10-K", "2025-11-01")),
        "NetIncomeLoss": _usd_facts((2025, 95_000_000_000, "10-K", "2025-11-01")),
        "Assets": _usd_facts((2025, 350_000_000_000, "10-K", "2025-11-01")),
        "RetainedEarningsAccumulatedDeficit": _usd_facts((2025, 5_000_000_000, "10-K", "2025-11-01")),
    })
    rows = parse_company_facts(raw, ticker="AAPL", cik="0000320193")

    assert rows[0].total_assets == 350_000_000_000
    assert rows[0].retained_earnings == 5_000_000_000


def test_no_us_gaap_facts_returns_empty_list():
    raw = {"cik": 320193, "entityName": "Apple Inc.", "facts": {}}
    assert parse_company_facts(raw, ticker="AAPL", cik="0000320193") == []


def test_rows_carry_the_caller_supplied_ticker_and_cik():
    raw = _raw({
        "Revenues": _usd_facts((2025, 400_000_000_000, "10-K", "2025-11-01")),
        "NetIncomeLoss": _usd_facts((2025, 95_000_000_000, "10-K", "2025-11-01")),
    })
    rows = parse_company_facts(raw, ticker="aapl", cik="0000320193")

    assert rows[0].ticker == "AAPL"
    assert rows[0].cik == "0000320193"


def test_financial_statement_facts_serializes_to_json():
    facts = FinancialStatementFacts(ticker="AAPL", cik="0000320193", fiscal_year=2025, revenue=1.0)
    assert facts.model_dump_json()
