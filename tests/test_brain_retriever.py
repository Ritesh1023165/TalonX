"""
tests/test_brain_retriever.py
----------------------------------
Tests talonx_brain.retriever -- the transform from a chromadb query()
result into Citation objects (for both the sec_filings and news_feed
collections), and that ticker scoping/top-k/the news toggle are passed
through correctly. The VectorStore itself is faked (not a real ChromaDB
instance): this is about talonx_brain's own logic, not chromadb's, same
mocking boundary the rest of the project's test suite uses for external
dependencies.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from talonx_brain.config import BrainConfig
from talonx_brain.retriever import ContextRetriever, _to_citations
from talonx_brain.schemas import CitationSourceType


def _filing_chroma_result(n: int) -> dict:
    return {
        "ids": [[f"acc-{i:05d}-hash" for i in range(n)]],
        "documents": [[f"chunk text {i}" for i in range(n)]],
        "metadatas": [
            [
                {
                    "ticker": "AAPL",
                    "form_type": "10-K",
                    "filing_date": "2025-11-01",
                    "accession_number": "0000320193-25-000123",
                    "source_document": "aapl-20250928.htm",
                }
                for _ in range(n)
            ]
        ],
        "distances": [[0.1 * i for i in range(n)]],
    }


def _news_chroma_result(n: int) -> dict:
    return {
        "ids": [[f"article-{i:05d}-hash" for i in range(n)]],
        "documents": [[f"Apple announces thing {i}\n\nSummary text {i}" for i in range(n)]],
        "metadatas": [
            [
                {
                    "ticker": "AAPL",
                    "title": f"Apple announces thing {i}",
                    "url": f"https://example.com/article-{i}",
                    "source": "rss:finance.yahoo.com",
                    "published_at": "2026-08-01T00:00:00+00:00",
                }
                for i in range(n)
            ]
        ],
        "distances": [[0.2 * i for i in range(n)]],
    }


def test_to_citations_maps_filing_result_fields():
    citations = _to_citations(_filing_chroma_result(2), CitationSourceType.FILING, excerpt_max_chars=600)
    assert len(citations) == 2
    assert citations[0].chunk_id == "acc-00000-hash"
    assert citations[0].source_type == CitationSourceType.FILING
    assert citations[0].form_type == "10-K"
    assert citations[0].accession_number == "0000320193-25-000123"
    assert citations[1].relevance_distance == 0.1
    # News-only fields stay unset for a filing citation.
    assert citations[0].article_title is None


def test_to_citations_maps_news_result_fields():
    citations = _to_citations(_news_chroma_result(2), CitationSourceType.NEWS, excerpt_max_chars=600)
    assert len(citations) == 2
    assert citations[0].source_type == CitationSourceType.NEWS
    assert citations[0].article_title == "Apple announces thing 0"
    assert citations[0].article_url == "https://example.com/article-0"
    assert citations[0].article_source == "rss:finance.yahoo.com"
    # Filing-only fields stay unset for a news citation.
    assert citations[0].form_type is None


def test_to_citations_truncates_long_excerpts():
    result = _filing_chroma_result(1)
    result["documents"] = [["x" * 1000]]
    citations = _to_citations(result, CitationSourceType.FILING, excerpt_max_chars=50)
    assert len(citations[0].excerpt) == 50
    assert citations[0].excerpt.endswith("…")


def test_to_citations_handles_empty_result():
    empty = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    assert _to_citations(empty, CitationSourceType.FILING, excerpt_max_chars=600) == []


def test_context_retriever_combines_filings_and_news_by_default():
    fake_filings = MagicMock()
    fake_filings.query.return_value = _filing_chroma_result(2)
    fake_news = MagicMock()
    fake_news.query.return_value = _news_chroma_result(1)

    retriever = ContextRetriever(
        config=BrainConfig(), filings_store=fake_filings, news_store=fake_news
    )
    citations = retriever.retrieve("aapl", "supply chain risk")

    assert len(citations) == 3
    assert [c.source_type for c in citations] == [
        CitationSourceType.FILING, CitationSourceType.FILING, CitationSourceType.NEWS,
    ]
    fake_filings.query.assert_called_once_with(
        query_text="supply chain risk", n_results=6, where={"ticker": "AAPL"}
    )
    fake_news.query.assert_called_once_with(
        query_text="supply chain risk", n_results=3, where={"ticker": "AAPL"}
    )


def test_context_retriever_skips_news_when_disabled():
    fake_filings = MagicMock()
    fake_filings.query.return_value = _filing_chroma_result(1)
    fake_news = MagicMock()

    config = BrainConfig(include_news_context=False)
    retriever = ContextRetriever(config=config, filings_store=fake_filings, news_store=fake_news)
    citations = retriever.retrieve("AAPL", "query")

    assert len(citations) == 1
    assert citations[0].source_type == CitationSourceType.FILING
    fake_news.query.assert_not_called()


def test_context_retriever_respects_news_top_k_override():
    fake_filings = MagicMock()
    fake_filings.query.return_value = _filing_chroma_result(0)
    fake_news = MagicMock()
    fake_news.query.return_value = _news_chroma_result(0)

    config = BrainConfig(news_retrieval_top_k=2)
    retriever = ContextRetriever(config=config, filings_store=fake_filings, news_store=fake_news)
    retriever.retrieve("AAPL", "query")

    assert fake_news.query.call_args.kwargs["n_results"] == 2


def test_context_retriever_form_type_filter_uses_and_operator():
    """Phase 2's LONG_TERM path passes form_type="10-K" to narrow
    retrieval to annual-report text. Chroma's `where` REJECTS a raw
    multi-key dict ({"ticker": x, "form_type": y}) -- combining two field
    filters requires the explicit "$and" operator form, or Chroma raises
    ValueError("Expected where to have exactly one operator..."). Caught
    live (a real ChromaDB call, not the mocked VectorStore this test file
    otherwise uses) during the Phase 2 end-to-end smoke test -- this
    locks the fix in since every OTHER test here mocks .query() and would
    never have caught an invalid where-clause shape on its own."""
    fake_filings = MagicMock()
    fake_filings.query.return_value = _filing_chroma_result(0)
    fake_news = MagicMock()
    fake_news.query.return_value = _news_chroma_result(0)

    retriever = ContextRetriever(
        config=BrainConfig(), filings_store=fake_filings, news_store=fake_news
    )
    retriever.retrieve("MSFT", "moat and capital allocation", form_type="10-K")

    fake_filings.query.assert_called_once_with(
        query_text="moat and capital allocation", n_results=6,
        where={"$and": [{"ticker": "MSFT"}, {"form_type": "10-K"}]},
    )


def test_context_retriever_form_type_list_uses_in_operator():
    """Event-Driven Earnings Radar: an earnings-triggered regeneration
    passes form_type=["10-K", "10-Q", "8-K"] so retrieval can see the
    freshly-ingested earnings filing alongside the prior annual-report
    context, not just one form type in isolation."""
    fake_filings = MagicMock()
    fake_filings.query.return_value = _filing_chroma_result(0)
    fake_news = MagicMock()
    fake_news.query.return_value = _news_chroma_result(0)

    retriever = ContextRetriever(
        config=BrainConfig(), filings_store=fake_filings, news_store=fake_news
    )
    retriever.retrieve("MSFT", "guidance revision", form_type=["10-K", "10-Q", "8-K"])

    fake_filings.query.assert_called_once_with(
        query_text="guidance revision", n_results=6,
        where={"$and": [{"ticker": "MSFT"}, {"form_type": {"$in": ["10-K", "10-Q", "8-K"]}}]},
    )


def test_context_retriever_n_results_override_applies_to_filings_only():
    fake_filings = MagicMock()
    fake_filings.query.return_value = _filing_chroma_result(0)
    fake_news = MagicMock()
    fake_news.query.return_value = _news_chroma_result(0)

    retriever = ContextRetriever(config=BrainConfig(), filings_store=fake_filings, news_store=fake_news)
    retriever.retrieve("AAPL", "query", n_results=10)

    assert fake_filings.query.call_args.kwargs["n_results"] == 10
    # News top-k is independently configured, unaffected by the filings override.
    assert fake_news.query.call_args.kwargs["n_results"] == 3
