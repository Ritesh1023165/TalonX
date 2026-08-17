"""
tests/test_pipeline_earnings.py
--------------------------------------
Tests pipeline.ingest_earnings_filing -- the Event-Driven Earnings
Radar's fast-track ingestion (Requirement 6), parallel to
test_pipeline_ledger_integration.py's coverage of ingest_ticker().
EdgarClient/DocumentChunker/VectorStore/publisher are mocked; the ledger
is real sqlite3 (tmp_path-backed), same "exercise local disk I/O for
real, mock the external services" boundary this project's other pipeline
tests use. raw_html is REAL text run through the REAL clean_filing_html
(not mocked) since _contains_item_202's whole job is text-matching
against genuinely cleaned output.

Requires pytest-asyncio (see requirements-dev.txt).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_ingest.edgar.client import EdgarClientError
from talonx_ingest.edgar.models import FilingDocument
from talonx_ingest.pipeline import ingest_earnings_filing
from talonx_ingest.storage.ledger import IngestionLedger
from tests.conftest import make_filing

_8K_WITH_ITEM_202 = (
    "<html><body><p>Item 2.02 Results of Operations and Financial Condition</p>"
    "<p>On August 13, 2026, the Company issued a press release announcing "
    "financial results for the quarter.</p></body></html>"
)
_8K_WITHOUT_ITEM_202 = (
    "<html><body><p>Item 5.02 Departure of Directors or Certain Officers</p>"
    "<p>The Company announces the departure of its Chief Financial Officer.</p></body></html>"
)
_10Q_BODY = "<html><body><p>Quarterly Report on Form 10-Q</p><p>Financial statements follow.</p></body></html>"


@pytest.fixture
def mocked_deps(company, ledger_path):
    earnings_8k = make_filing(company, "0000320193-26-000101", form_type="8-K")
    quarterly_10q = make_filing(company, "0000320193-26-000102", form_type="10-Q")

    edgar_client = AsyncMock()
    edgar_client.resolve_ticker.return_value = company
    edgar_client.get_recent_filings.return_value = [earnings_8k, quarterly_10q]
    edgar_client.fetch_documents.return_value = [
        FilingDocument(metadata=earnings_8k, raw_html=_8K_WITH_ITEM_202),
        FilingDocument(metadata=quarterly_10q, raw_html=_10Q_BODY),
    ]

    chunker = MagicMock()
    chunker.chunk_document.return_value = [MagicMock(chunk_id=f"c{i}") for i in range(2)]

    vector_store = MagicMock()
    vector_store.upsert_chunks.return_value = 2  # all chunks, by default

    publisher = AsyncMock()

    ledger = IngestionLedger(ledger_path)
    yield {
        "company": company, "earnings_8k": earnings_8k, "quarterly_10q": quarterly_10q,
        "edgar_client": edgar_client, "chunker": chunker, "vector_store": vector_store,
        "publisher": publisher, "ledger": ledger,
    }
    ledger.close()


async def _run(mocked_deps):
    return await ingest_earnings_filing(
        "AAPL", mocked_deps["edgar_client"], mocked_deps["chunker"],
        mocked_deps["vector_store"], mocked_deps["ledger"], mocked_deps["publisher"],
    )


@pytest.mark.asyncio
async def test_requests_8k_and_10q_not_the_global_target_forms(mocked_deps):
    await _run(mocked_deps)

    mocked_deps["edgar_client"].get_recent_filings.assert_awaited_once_with(
        mocked_deps["company"], forms=("8-K", "10-Q"),
    )


@pytest.mark.asyncio
async def test_8k_with_item_202_is_flagged_earnings_related(mocked_deps):
    # Only the 8-K in play -- isolate to avoid the 10-Q also contributing True.
    mocked_deps["edgar_client"].get_recent_filings.return_value = [mocked_deps["earnings_8k"]]
    mocked_deps["edgar_client"].fetch_documents.return_value = [
        FilingDocument(metadata=mocked_deps["earnings_8k"], raw_html=_8K_WITH_ITEM_202)
    ]

    found = await _run(mocked_deps)

    assert found is True
    event = mocked_deps["publisher"].publish_filing_ingested.await_args.args[0]
    assert event.is_earnings_related is True
    assert event.form_type == "8-K"


@pytest.mark.asyncio
async def test_8k_without_item_202_is_ingested_but_not_earnings_related(mocked_deps):
    mocked_deps["edgar_client"].get_recent_filings.return_value = [mocked_deps["earnings_8k"]]
    mocked_deps["edgar_client"].fetch_documents.return_value = [
        FilingDocument(metadata=mocked_deps["earnings_8k"], raw_html=_8K_WITHOUT_ITEM_202)
    ]

    found = await _run(mocked_deps)

    assert found is False  # not earnings-related overall
    mocked_deps["publisher"].publish_filing_ingested.assert_awaited_once()  # but still ingested
    event = mocked_deps["publisher"].publish_filing_ingested.await_args.args[0]
    assert event.is_earnings_related is False
    assert mocked_deps["ledger"].is_ingested(mocked_deps["earnings_8k"].accession_number) is True


@pytest.mark.asyncio
async def test_10q_is_always_earnings_related_regardless_of_text(mocked_deps):
    mocked_deps["edgar_client"].get_recent_filings.return_value = [mocked_deps["quarterly_10q"]]
    mocked_deps["edgar_client"].fetch_documents.return_value = [
        FilingDocument(metadata=mocked_deps["quarterly_10q"], raw_html=_10Q_BODY)
    ]

    found = await _run(mocked_deps)

    assert found is True
    event = mocked_deps["publisher"].publish_filing_ingested.await_args.args[0]
    assert event.is_earnings_related is True
    assert event.form_type == "10-Q"


@pytest.mark.asyncio
async def test_mix_of_qualifying_and_non_qualifying_filings_returns_true(mocked_deps):
    # Default fixture has an 8-K WITH Item 2.02 and a 10-Q -- both qualify.
    found = await _run(mocked_deps)
    assert found is True
    assert mocked_deps["publisher"].publish_filing_ingested.await_count == 2


@pytest.mark.asyncio
async def test_partial_upsert_does_not_mark_ledger_complete(mocked_deps):
    mocked_deps["vector_store"].upsert_chunks.return_value = 1  # 1 of 2 chunks

    await _run(mocked_deps)

    assert mocked_deps["ledger"].is_ingested(mocked_deps["earnings_8k"].accession_number) is False
    mocked_deps["publisher"].publish_filing_ingested.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_ingested_filings_are_skipped(mocked_deps):
    mocked_deps["ledger"].mark_ingested(mocked_deps["earnings_8k"], chunk_count=2)
    mocked_deps["ledger"].mark_ingested(mocked_deps["quarterly_10q"], chunk_count=2)

    found = await _run(mocked_deps)

    assert found is False
    mocked_deps["publisher"].publish_filing_ingested.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_filings_found_returns_false(mocked_deps):
    mocked_deps["edgar_client"].get_recent_filings.return_value = []

    assert await _run(mocked_deps) is False


@pytest.mark.asyncio
async def test_ticker_resolution_failure_returns_false(mocked_deps):
    mocked_deps["edgar_client"].resolve_ticker.side_effect = EdgarClientError("not found")

    assert await _run(mocked_deps) is False
    mocked_deps["edgar_client"].get_recent_filings.assert_not_awaited()
