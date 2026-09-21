"""
tests/test_intelligence_edgar_client_passthrough.py
--------------------------------------------------
Task 96A -- the two raw passthroughs added to EdgarClient for the event
layer. Mock the network boundary (_get), matching test_edgar_client.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from talonx_ingest.config import EdgarConfig
from talonx_ingest.edgar.client import EdgarClient
from talonx_ingest.edgar.models import CompanyRef


@pytest.mark.asyncio
async def test_get_submissions_by_company_ref():
    client = EdgarClient(EdgarConfig())
    client._get = AsyncMock(return_value={"cik": 320193, "filings": {"recent": {}}})
    company = CompanyRef(ticker="AAPL", cik="0000320193", name="Apple Inc.")

    result = await client.get_submissions(company)

    client._get.assert_awaited_once_with(
        "https://data.sec.gov/submissions/CIK0000320193.json", as_json=True
    )
    assert result["cik"] == 320193


@pytest.mark.asyncio
async def test_get_submissions_by_bare_cik():
    client = EdgarClient(EdgarConfig())
    client._get = AsyncMock(return_value={})
    await client.get_submissions("320193")
    client._get.assert_awaited_once_with(
        "https://data.sec.gov/submissions/CIK0000320193.json", as_json=True
    )


@pytest.mark.asyncio
async def test_fetch_filing_index_url():
    client = EdgarClient(EdgarConfig())
    client._get = AsyncMock(return_value={"directory": {"item": []}})

    await client.fetch_filing_index("0000320193", "0000320193-26-000070")

    client._get.assert_awaited_once_with(
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000070/index.json",
        as_json=True,
    )


@pytest.mark.asyncio
async def test_existing_get_recent_filings_still_ignores_8k_by_default():
    """Regression guard: the new methods must not change get_recent_filings."""
    client = EdgarClient(EdgarConfig())
    client._get = AsyncMock(
        return_value={
            "filings": {
                "recent": {
                    "form": ["10-K", "8-K", "10-Q"],
                    "accessionNumber": ["0001", "0002", "0003"],
                    "filingDate": ["2026-03-01", "2026-08-13", "2026-08-14"],
                    "reportDate": ["2025-12-31", "", "2026-06-30"],
                    "primaryDocument": ["a.htm", "b.htm", "c.htm"],
                    "primaryDocDescription": ["10-K", "8-K", "10-Q"],
                }
            }
        }
    )
    company = CompanyRef(ticker="AAPL", cik="0000320193", name="Apple Inc.")
    results = await client.get_recent_filings(company)
    assert {f.form_type for f in results} == {"10-K", "10-Q"}
