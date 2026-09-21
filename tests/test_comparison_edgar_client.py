"""
tests/test_comparison_edgar_client.py
-------------------------------------
Task 96C -- the two EdgarClient passthroughs added for the comparison
engine. Mock the network boundary (_get), matching test_edgar_client.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from talonx_ingest.config import EdgarConfig
from talonx_ingest.edgar.client import EdgarClient


@pytest.mark.asyncio
async def test_get_company_concept_url():
    client = EdgarClient(EdgarConfig())
    client._get = AsyncMock(return_value={"units": {}})
    await client.get_company_concept("0000320193", "us-gaap", "Revenues")
    client._get.assert_awaited_once_with(
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Revenues.json",
        as_json=True,
    )


@pytest.mark.asyncio
async def test_get_company_concept_accepts_int_cik():
    client = EdgarClient(EdgarConfig())
    client._get = AsyncMock(return_value={})
    await client.get_company_concept(320193, "dei", "EntityCommonStockSharesOutstanding")
    client._get.assert_awaited_once_with(
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/dei/"
        "EntityCommonStockSharesOutstanding.json",
        as_json=True,
    )


@pytest.mark.asyncio
async def test_fetch_document_passes_url_through():
    client = EdgarClient(EdgarConfig())
    client._get = AsyncMock(return_value="<html>ok</html>")
    out = await client.fetch_document("https://www.sec.gov/Archives/edgar/data/320193/x/a.htm")
    assert out == "<html>ok</html>"
    client._get.assert_awaited_once_with(
        "https://www.sec.gov/Archives/edgar/data/320193/x/a.htm", as_json=False
    )
