"""
tests/test_edgar_client.py
---------------------------------
Tests talonx_ingest.edgar.client.EdgarClient.get_company_facts -- the
Phase 2 structured-financials fetch -- and get_recent_filings's `forms`
override param, added for the Event-Driven Earnings Radar's fast-track
poller (needs to fetch 8-K/10-Q without touching the GLOBAL
target_forms, which stays 10-K/10-Q only for the regular periodic
ingestion loop). `_get()` itself (auth/rate-limit/retry/error handling)
is exercised generically by every other EDGAR endpoint this client
already calls; these tests confirm the right URL/filter is built and
`_get()`'s result is passed through, matching the existing convention
(mock the network boundary, not re-test `_get()`'s own retry logic here).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from talonx_ingest.config import EdgarConfig
from talonx_ingest.edgar.client import EdgarClient
from talonx_ingest.edgar.models import CompanyRef


@pytest.mark.asyncio
async def test_get_company_facts_requests_the_right_url():
    client = EdgarClient(EdgarConfig())
    client._get = AsyncMock(return_value={"cik": 320193, "facts": {}})
    company = CompanyRef(ticker="AAPL", cik="0000320193", name="Apple Inc.")

    result = await client.get_company_facts(company)

    client._get.assert_awaited_once_with(
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", as_json=True,
    )
    assert result == {"cik": 320193, "facts": {}}


def _submissions_payload() -> dict:
    return {
        "filings": {
            "recent": {
                "form": ["10-K", "8-K", "10-Q", "8-K"],
                "accessionNumber": ["0001", "0002", "0003", "0004"],
                "filingDate": ["2026-03-01", "2026-08-13", "2026-08-14", "2026-08-15"],
                "reportDate": ["2025-12-31", "", "2026-06-30", ""],
                "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm"],
                "primaryDocDescription": ["10-K", "8-K", "10-Q", "8-K"],
            }
        }
    }


@pytest.mark.asyncio
async def test_get_recent_filings_defaults_to_config_target_forms():
    client = EdgarClient(EdgarConfig())
    client._get = AsyncMock(return_value=_submissions_payload())
    company = CompanyRef(ticker="AAPL", cik="0000320193", name="Apple Inc.")

    results = await client.get_recent_filings(company)

    # config.target_forms defaults to ("10-K", "10-Q") -- the two 8-Ks
    # must NOT come back when forms isn't explicitly overridden.
    assert {f.form_type for f in results} == {"10-K", "10-Q"}


@pytest.mark.asyncio
async def test_get_recent_filings_forms_override_does_not_touch_config():
    client = EdgarClient(EdgarConfig())
    client._get = AsyncMock(return_value=_submissions_payload())
    company = CompanyRef(ticker="AAPL", cik="0000320193", name="Apple Inc.")

    results = await client.get_recent_filings(company, forms=("8-K",))

    assert {f.form_type for f in results} == {"8-K"}
    assert len(results) == 2  # both 8-Ks, not deduped/collapsed
    assert client.config.target_forms == ("10-K", "10-Q")  # global config untouched
