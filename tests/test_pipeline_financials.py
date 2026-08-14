"""
tests/test_pipeline_financials.py
------------------------------------------
Tests pipeline.ingest_long_term_financials -- Phase 2's structured-
financials ingestion path, parallel to test_pipeline_ledger_integration.py's
coverage of the text-ingestion path. EdgarClient and the publisher are
mocked; the ledger is real sqlite3 (tmp_path-backed), same "exercise
local disk I/O for real, mock the external services" boundary the rest
of this project's pipeline/consumer tests use.

Requires pytest-asyncio (see requirements-dev.txt).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from talonx_ingest.edgar.client import EdgarClientError
from talonx_ingest.pipeline import ingest_long_term_financials
from talonx_ingest.storage.ledger import IngestionLedger


def _raw_facts(*fiscal_years: int) -> dict:
    return {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"fy": fy, "val": float(fy) * 1_000_000_000, "form": "10-K", "fp": "FY", "filed": f"{fy}-11-01"}
                            for fy in fiscal_years
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"fy": fy, "val": float(fy) * 100_000_000, "form": "10-K", "fp": "FY", "filed": f"{fy}-11-01"}
                            for fy in fiscal_years
                        ]
                    }
                },
            }
        },
    }


@pytest.fixture
def mocked_deps(company, ledger_path):
    edgar_client = AsyncMock()
    edgar_client.resolve_ticker.return_value = company
    edgar_client.get_company_facts.return_value = _raw_facts(2023, 2024, 2025)

    publisher = AsyncMock()
    ledger = IngestionLedger(ledger_path)
    yield {"edgar_client": edgar_client, "publisher": publisher, "ledger": ledger, "company": company}
    ledger.close()


@pytest.mark.asyncio
async def test_fresh_ticker_publishes_and_marks_the_ledger(mocked_deps):
    written = await ingest_long_term_financials(
        "AAPL", mocked_deps["edgar_client"], mocked_deps["ledger"], mocked_deps["publisher"],
    )

    assert written == 1
    mocked_deps["publisher"].publish_fundamentals_ingested.assert_awaited_once()
    event = mocked_deps["publisher"].publish_fundamentals_ingested.await_args.args[0]
    assert event.ticker == "AAPL"
    assert len(event.facts) == 3
    assert mocked_deps["ledger"].latest_ingested_fiscal_year(mocked_deps["company"].cik) == 2025


@pytest.mark.asyncio
async def test_already_up_to_date_ticker_is_not_republished(mocked_deps):
    mocked_deps["ledger"].mark_financials_ingested("AAPL", mocked_deps["company"].cik, [2025])

    written = await ingest_long_term_financials(
        "AAPL", mocked_deps["edgar_client"], mocked_deps["ledger"], mocked_deps["publisher"],
    )

    assert written == 0
    mocked_deps["publisher"].publish_fundamentals_ingested.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_new_fiscal_year_since_last_ingest_republishes(mocked_deps):
    mocked_deps["ledger"].mark_financials_ingested("AAPL", mocked_deps["company"].cik, [2023, 2024])

    written = await ingest_long_term_financials(
        "AAPL", mocked_deps["edgar_client"], mocked_deps["ledger"], mocked_deps["publisher"],
    )

    assert written == 1  # FY2025 is new since the ledger's last-known FY2024


@pytest.mark.asyncio
async def test_unresolvable_ticker_is_skipped(mocked_deps):
    mocked_deps["edgar_client"].resolve_ticker.side_effect = EdgarClientError("not found")

    written = await ingest_long_term_financials(
        "ZZZZ", mocked_deps["edgar_client"], mocked_deps["ledger"], mocked_deps["publisher"],
    )

    assert written == 0
    mocked_deps["publisher"].publish_fundamentals_ingested.assert_not_awaited()


@pytest.mark.asyncio
async def test_company_facts_fetch_failure_is_skipped(mocked_deps):
    mocked_deps["edgar_client"].get_company_facts.side_effect = EdgarClientError("500")

    written = await ingest_long_term_financials(
        "AAPL", mocked_deps["edgar_client"], mocked_deps["ledger"], mocked_deps["publisher"],
    )

    assert written == 0


@pytest.mark.asyncio
async def test_no_usable_facts_is_skipped_without_error(mocked_deps):
    mocked_deps["edgar_client"].get_company_facts.return_value = {"cik": 320193, "facts": {}}

    written = await ingest_long_term_financials(
        "AAPL", mocked_deps["edgar_client"], mocked_deps["ledger"], mocked_deps["publisher"],
    )

    assert written == 0
    mocked_deps["publisher"].publish_fundamentals_ingested.assert_not_awaited()


# --- force=True (reconciliation for a lost NewFundamentalsIngestedEvent) --

@pytest.mark.asyncio
async def test_force_republishes_an_already_up_to_date_ticker(mocked_deps):
    """The exact scenario force exists for: the ledger says FY2025 is
    already ingested (a past attempt got far enough to fetch from EDGAR
    and mark the ledger), but FundamentalScanner never actually received
    the event -- force=True must re-fetch and re-publish anyway, not
    trust the ledger's watermark as proof of successful delivery."""
    mocked_deps["ledger"].mark_financials_ingested("AAPL", mocked_deps["company"].cik, [2025])

    written = await ingest_long_term_financials(
        "AAPL", mocked_deps["edgar_client"], mocked_deps["ledger"], mocked_deps["publisher"], force=True,
    )

    assert written == 1
    mocked_deps["publisher"].publish_fundamentals_ingested.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_still_skips_if_facts_cannot_be_resolved(mocked_deps):
    """force bypasses the LEDGER skip only -- it's not a bypass for
    genuine upstream failures (unresolvable ticker, fetch error, no
    usable facts), which must still return 0."""
    mocked_deps["edgar_client"].resolve_ticker.side_effect = EdgarClientError("not found")

    written = await ingest_long_term_financials(
        "ZZZZ", mocked_deps["edgar_client"], mocked_deps["ledger"], mocked_deps["publisher"], force=True,
    )

    assert written == 0
    mocked_deps["publisher"].publish_fundamentals_ingested.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_still_marks_the_ledger(mocked_deps):
    """A forced re-publish still updates the ledger's watermark -- a
    no-op given the fiscal year is already there, but this keeps the
    ledger consistent rather than special-casing it."""
    mocked_deps["ledger"].mark_financials_ingested("AAPL", mocked_deps["company"].cik, [2025])

    await ingest_long_term_financials(
        "AAPL", mocked_deps["edgar_client"], mocked_deps["ledger"], mocked_deps["publisher"], force=True,
    )

    assert mocked_deps["ledger"].latest_ingested_fiscal_year(mocked_deps["company"].cik) == 2025
