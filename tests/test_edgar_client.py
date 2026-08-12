"""
tests/test_edgar_client.py
---------------------------------
Tests talonx_ingest.edgar.client.EdgarClient.get_company_facts -- the
Phase 2 structured-financials fetch. `_get()` itself (auth/rate-limit/
retry/error handling) is exercised generically by every other EDGAR
endpoint this client already calls; this just confirms get_company_facts
builds the right URL and passes through `_get()`'s result, matching the
existing convention (mock the network boundary, not re-test `_get()`'s
own retry logic here).
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
