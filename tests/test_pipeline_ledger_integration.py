"""
tests/test_pipeline_ledger_integration.py
----------------------------------------------
Tests the interaction between pipeline.ingest_ticker, the ledger, and the
vector store -- specifically the safety property that matters most for
incremental ingestion: a filing is ONLY marked complete in the ledger
after ALL of its chunks are successfully written. A partial upsert must
leave it eligible for retry, not falsely marked done.

EdgarClient, DocumentChunker, and VectorStore are mocked here -- this
test is about the orchestration logic in ingest_ticker(), not about
network I/O, real chunking, or real embeddings (those are covered by
their own test files / by running the real pipeline).

Requires pytest-asyncio (see requirements-dev.txt) for the @pytest.mark.asyncio
tests below.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_ingest.edgar.models import FilingDocument
from talonx_ingest.pipeline import ingest_ticker
from talonx_ingest.storage.ledger import IngestionLedger
from tests.conftest import make_filing


@pytest.fixture
def mocked_deps(company, ledger_path):
    filing = make_filing(company, "0000320193-24-000123")

    edgar_client = AsyncMock()
    edgar_client.resolve_ticker.return_value = company
    edgar_client.get_recent_filings.return_value = [filing]
    edgar_client.fetch_documents.return_value = [
        FilingDocument(metadata=filing, raw_html="<html><body><p>text</p></body></html>")
    ]

    chunker = MagicMock()
    fake_chunks = [MagicMock(chunk_id=f"c{i}") for i in range(3)]
    chunker.chunk_document.return_value = fake_chunks

    vector_store = MagicMock()
    publisher = AsyncMock()

    ledger = IngestionLedger(ledger_path)
    yield {
        "filing": filing,
        "edgar_client": edgar_client,
        "chunker": chunker,
        "vector_store": vector_store,
        "publisher": publisher,
        "ledger": ledger,
    }
    ledger.close()


@pytest.mark.asyncio
async def test_partial_upsert_does_not_mark_ledger_complete(mocked_deps):
    mocked_deps["vector_store"].upsert_chunks.return_value = 2  # 2 of 3 chunks

    written = await ingest_ticker(
        "AAPL",
        mocked_deps["edgar_client"],
        mocked_deps["chunker"],
        mocked_deps["vector_store"],
        mocked_deps["ledger"],
        mocked_deps["publisher"],
    )

    assert written == 0
    assert mocked_deps["ledger"].is_ingested(mocked_deps["filing"].accession_number) is False


@pytest.mark.asyncio
async def test_successful_upsert_marks_ledger_complete(mocked_deps):
    mocked_deps["vector_store"].upsert_chunks.return_value = 3  # all chunks

    written = await ingest_ticker(
        "AAPL",
        mocked_deps["edgar_client"],
        mocked_deps["chunker"],
        mocked_deps["vector_store"],
        mocked_deps["ledger"],
        mocked_deps["publisher"],
    )

    assert written == 3
    assert mocked_deps["ledger"].is_ingested(mocked_deps["filing"].accession_number) is True
    mocked_deps["publisher"].publish_filing_ingested.assert_awaited_once()


@pytest.mark.asyncio
async def test_already_ingested_filing_is_not_refetched(mocked_deps):
    mocked_deps["vector_store"].upsert_chunks.return_value = 3
    mocked_deps["ledger"].mark_ingested(mocked_deps["filing"], chunk_count=3)

    written = await ingest_ticker(
        "AAPL",
        mocked_deps["edgar_client"],
        mocked_deps["chunker"],
        mocked_deps["vector_store"],
        mocked_deps["ledger"],
        mocked_deps["publisher"],
    )

    assert written == 0
    mocked_deps["edgar_client"].fetch_documents.assert_not_called()


@pytest.mark.asyncio
async def test_force_refresh_bypasses_ledger(mocked_deps):
    mocked_deps["vector_store"].upsert_chunks.return_value = 3
    mocked_deps["ledger"].mark_ingested(mocked_deps["filing"], chunk_count=3)

    written = await ingest_ticker(
        "AAPL",
        mocked_deps["edgar_client"],
        mocked_deps["chunker"],
        mocked_deps["vector_store"],
        mocked_deps["ledger"],
        mocked_deps["publisher"],
        force_refresh=True,
    )

    assert written == 3
    mocked_deps["edgar_client"].fetch_documents.assert_called_once()
