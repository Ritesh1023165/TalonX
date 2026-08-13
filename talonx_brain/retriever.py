"""
talonx_brain.retriever
---------------------------
RAG context retrieval from Module 1's two ChromaDB collections:
sec_filings (structured filing text) and news_feed (recent news/social
article text). Both are read through talonx_ingest's own VectorStore
wrapper -- same reasoning as before: retrieval must run through the exact
embedding function and persist directory Module 1 used to write each
store, or similarity scores are meaningless. There's no separate copy of
either collection's name/persist-dir/embedding-model here; the news store
is constructed with `collection_name=ingest_settings.news.vector_collection_name`,
so it too can never drift out of sync with what Module 1 actually wrote.

Queries both collections per signal (news optionally, via
TALONX_BRAIN_INCLUDE_NEWS) and returns a combined citation list --
filings first, then news -- rather than cross-collection re-ranking by
distance. Cosine distance is comparable WITHIN a collection (same
embedding model, same query), but filing text and news text have very
different length/style profiles, so distances across collections aren't
apples-to-apples enough to trust a merged sort.
"""
from __future__ import annotations

import logging

from talonx_ingest.config import settings as ingest_settings
from talonx_ingest.storage.vector_store import VectorStore, get_vector_store

from talonx_brain.config import BrainConfig
from talonx_brain.schemas import Citation, CitationSourceType

logger = logging.getLogger("talonx_brain.retriever")


class ContextRetriever:
    def __init__(
        self,
        config: BrainConfig | None = None,
        filings_store: VectorStore | None = None,
        news_store: VectorStore | None = None,
    ):
        self.config = config or BrainConfig()
        # get_vector_store(): process-wide cache keyed by collection name --
        # run_talonx.py runs this ResearchAgent in the SAME process as
        # talonx_ingest's own run_ingestion()/EarningsFastTrackPoller, which
        # already populate this cache for the default "sec_filings"
        # collection; reusing it here means the embedding model is shared
        # rather than a second full copy sitting resident in memory.
        self._filings_store = filings_store or get_vector_store()
        # Lazily constructed (see _get_news_store) so a real Chroma client
        # for news_feed isn't built when include_news_context is False, or
        # in tests that only care about filings.
        self._news_store = news_store

    def _get_news_store(self) -> VectorStore:
        if self._news_store is None:
            self._news_store = get_vector_store(
                collection_name=ingest_settings.news.vector_collection_name
            )
        return self._news_store

    def retrieve(
        self, ticker: str, query_text: str, n_results: int | None = None,
        form_type: str | list[str] | None = None,
    ) -> list[Citation]:
        """`form_type` (e.g. "10-K") is Phase 2's LONG_TERM path narrowing
        retrieval to annual-report text specifically, skipping 10-Qs --
        chunker.py already writes form_type into every filing chunk's
        metadata, so this is a plain equality filter Chroma already
        supports; the intraday path leaves it None (no filter, matches
        every form type, exactly today's behavior).

        Also accepts a LIST of form types (e.g. ["10-K", "10-Q", "8-K"])
        -- the Event-Driven Earnings Radar's post-earnings recalculation
        needs the freshly-ingested 8-K/10-Q chunks alongside the prior
        10-K's full-year context, not just one form type in isolation.
        Chroma's `$in` operator handles this the same way `$and` handles
        the two-field case below."""
        n = n_results or self.config.retrieval_top_k
        # Chroma's `where` rejects a raw multi-key dict ({"a": x, "b": y})
        # -- combining two field filters requires the explicit "$and"
        # operator form. Single-field filters (the intraday path, and the
        # news query below) stay a plain dict, which Chroma does accept.
        if form_type is None:
            where = {"ticker": ticker.upper()}
        elif isinstance(form_type, list):
            where = {"$and": [{"ticker": ticker.upper()}, {"form_type": {"$in": form_type}}]}
        else:
            where = {"$and": [{"ticker": ticker.upper()}, {"form_type": form_type}]}
        filing_results = self._filings_store.query(
            query_text=query_text, n_results=n, where=where
        )
        citations = _to_citations(
            filing_results, CitationSourceType.FILING, self.config.excerpt_max_chars
        )

        if self.config.include_news_context and self.config.news_retrieval_top_k > 0:
            news_results = self._get_news_store().query(
                query_text=query_text,
                n_results=self.config.news_retrieval_top_k,
                where={"ticker": ticker.upper()},
            )
            citations.extend(
                _to_citations(
                    news_results, CitationSourceType.NEWS, self.config.excerpt_max_chars
                )
            )

        if not citations:
            logger.info("No filing or news context found for %s", ticker)
        return citations


def _to_citations(
    results: dict, source_type: CitationSourceType, excerpt_max_chars: int
) -> list[Citation]:
    # chromadb's query() returns one list-of-lists per field, outer index
    # aligned to the batch of query_texts (always length 1 here).
    ids = (results.get("ids") or [[]])[0]
    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]

    citations: list[Citation] = []
    for i, chunk_id in enumerate(ids):
        meta = metadatas[i] or {}
        excerpt = _truncate(documents[i], excerpt_max_chars)
        distance = distances[i] if i < len(distances) else None

        if source_type == CitationSourceType.NEWS:
            citations.append(
                Citation(
                    chunk_id=chunk_id,
                    excerpt=excerpt,
                    source_type=source_type,
                    article_title=meta.get("title"),
                    article_url=meta.get("url"),
                    article_source=meta.get("source"),
                    published_at=meta.get("published_at"),
                    relevance_distance=distance,
                )
            )
        else:
            citations.append(
                Citation(
                    chunk_id=chunk_id,
                    excerpt=excerpt,
                    source_type=source_type,
                    source_document=meta.get("source_document", "unknown"),
                    form_type=meta.get("form_type"),
                    filing_date=meta.get("filing_date"),
                    accession_number=meta.get("accession_number"),
                    relevance_distance=distance,
                )
            )
    return citations


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
