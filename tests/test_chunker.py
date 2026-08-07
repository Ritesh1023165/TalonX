"""
tests/test_chunker.py
------------------------
Tests processing.chunker.DocumentChunker -- both the filing-specific
chunk_document() and the generic chunk_text() it's built on (the latter
is what news.pipeline reuses).
"""
from __future__ import annotations

from talonx_ingest.config import ChunkingConfig
from talonx_ingest.edgar.models import FilingDocument
from talonx_ingest.processing.chunker import DocumentChunker
from tests.conftest import make_filing


def make_chunker(chunk_size=50, chunk_overlap=0, min_chunk_chars=5) -> DocumentChunker:
    cfg = ChunkingConfig(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, min_chunk_chars=min_chunk_chars
    )
    return DocumentChunker(cfg)


def test_chunk_text_splits_long_text():
    chunker = make_chunker(chunk_size=50)
    long_text = "A" * 120
    chunks = chunker.chunk_text(long_text, id_prefix="article-abc123", base_metadata={"ticker": "AAPL"})
    assert len(chunks) == 3
    assert chunks[0].metadata["ticker"] == "AAPL"
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[2].metadata["total_chunks"] == 3


def test_chunk_text_empty_input_returns_no_chunks():
    chunker = make_chunker()
    assert chunker.chunk_text("", id_prefix="x", base_metadata={}) == []
    assert chunker.chunk_text("   ", id_prefix="x", base_metadata={}) == []


def test_chunk_text_below_min_chars_is_filtered():
    chunker = make_chunker(min_chunk_chars=10)
    assert chunker.chunk_text("short", id_prefix="y", base_metadata={}) == []


def test_chunk_ids_are_deterministic():
    """Same input + same id_prefix must always produce the same chunk_id --
    this is what makes Chroma's upsert idempotent across retries."""
    chunker = make_chunker(chunk_size=50)
    text = "B" * 60
    chunks1 = chunker.chunk_text(text, id_prefix="stable-id", base_metadata={})
    chunks2 = chunker.chunk_text(text, id_prefix="stable-id", base_metadata={})
    assert [c.chunk_id for c in chunks1] == [c.chunk_id for c in chunks2]


def test_chunk_ids_differ_for_different_prefixes():
    chunker = make_chunker(chunk_size=50)
    text = "C" * 60
    chunks_a = chunker.chunk_text(text, id_prefix="prefix-a", base_metadata={})
    chunks_b = chunker.chunk_text(text, id_prefix="prefix-b", base_metadata={})
    ids_a = {c.chunk_id for c in chunks_a}
    ids_b = {c.chunk_id for c in chunks_b}
    assert ids_a.isdisjoint(ids_b)


def test_chunk_document_uses_filing_metadata(company):
    chunker = make_chunker(chunk_size=50)
    filing = make_filing(company, accession_number="0000320193-24-000001")
    doc = FilingDocument(metadata=filing, cleaned_text="D" * 120)

    chunks = chunker.chunk_document(doc)

    assert len(chunks) == 3
    assert chunks[0].metadata["ticker"] == "AAPL"
    assert chunks[0].metadata["accession_number"] == "0000320193-24-000001"
    assert chunks[0].metadata["form_type"] == "10-K"


def test_chunk_document_not_ready_returns_no_chunks(company):
    chunker = make_chunker()
    filing = make_filing(company, accession_number="0000320193-24-000002")
    doc = FilingDocument(metadata=filing, fetch_error="network timeout")  # not ready

    assert chunker.chunk_document(doc) == []


def test_chunk_documents_aggregates_across_multiple_filings(company):
    chunker = make_chunker(chunk_size=50)
    filing1 = make_filing(company, accession_number="acc-1")
    filing2 = make_filing(company, accession_number="acc-2")
    docs = [
        FilingDocument(metadata=filing1, cleaned_text="E" * 60),
        FilingDocument(metadata=filing2, cleaned_text="F" * 60),
    ]

    all_chunks = chunker.chunk_documents(docs)

    accession_numbers = {c.metadata["accession_number"] for c in all_chunks}
    assert accession_numbers == {"acc-1", "acc-2"}
