"""
talonx_ingest.storage.vector_store
-------------------------------------
Thin wrapper around a local, persistent ChromaDB collection. Keeps chunking
and embedding concerns separate from RAG retrieval (which lives in the
downstream qualitative-research module, not this one).

Default embedding function is Chroma's bundled sentence-transformers
(all-MiniLM-L6-v2) so the module works fully offline out of the box.
Swap `embedding_function` for an OpenAI/Gemini embedding wrapper later
without touching call sites.
"""
from __future__ import annotations

import logging
import threading

import chromadb
from chromadb.utils import embedding_functions

from talonx_ingest.config import VectorStoreConfig, settings
from talonx_ingest.edgar.models import TextChunk

logger = logging.getLogger("talonx_ingest.storage.vector_store")


class VectorStore:
    def __init__(
        self,
        config: VectorStoreConfig | None = None,
        collection_name: str | None = None,
    ):
        """
        `collection_name` overrides `config.collection_name` when provided --
        used to give news/social content its own collection (e.g.
        "news_feed") separate from SEC filings ("sec_filings"), while
        reusing the same persistent Chroma directory and embedding model.
        """
        self.config = config or settings.vector_store
        self._client = chromadb.PersistentClient(path=self.config.persist_directory)
        self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=self.config.embedding_model_name
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name or self.config.collection_name,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        # NOT thread-safe for genuinely concurrent access from two OS
        # threads -- see get_vector_store's docstring and
        # talonx_brain/consumer.py's _generate_fresh_report for why that
        # matters and how it's actually avoided (keeping every caller on
        # the single asyncio event-loop thread, not a threading.Lock here).
        # A threading.Lock was tried first (2026-08-13) and made it WORSE:
        # it stopped the crash but froze the entire process instead (every
        # asyncio task stalls once the single event-loop thread blocks on
        # a synchronous Lock.acquire() with no timeout) -- a silent total
        # hang, confirmed via the main log going dead across ALL tasks
        # (market data ticks included, a completely unrelated coroutine),
        # not just the one doing the upsert. Reverted in favor of removing
        # the cross-thread call at its source instead.

    def upsert_chunks(self, chunks: list[TextChunk]) -> int:
        """Batch-upsert chunks into the collection. Returns count written."""
        if not chunks:
            return 0

        batch_size = self.config.upsert_batch_size
        written = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            self._collection.upsert(
                ids=[c.chunk_id for c in batch],
                documents=[c.text for c in batch],
                metadatas=[_sanitize_metadata(c.metadata) for c in batch],
            )
            written += len(batch)
            logger.info(
                "Upserted batch of %d chunks (%d/%d)",
                len(batch), written, len(chunks),
            )

        return written

    def count(self) -> int:
        return self._collection.count()

    def query(
        self, query_text: str, n_results: int = 8, where: dict | None = None
    ) -> dict:
        """Convenience passthrough for ad-hoc retrieval/debugging."""
        return self._collection.query(
            query_texts=[query_text], n_results=n_results, where=where
        )

    def delete_by_ticker(self, ticker: str) -> None:
        """Useful for re-ingestion / backfill correction."""
        self._collection.delete(where={"ticker": ticker})


def _sanitize_metadata(metadata: dict) -> dict:
    """Chroma metadata values must be str/int/float/bool -- strip Nones."""
    return {k: v for k, v in metadata.items() if v is not None}


_vector_store_cache: dict[str, "VectorStore"] = {}
_cache_lock = threading.Lock()


def get_vector_store(
    config: VectorStoreConfig | None = None, collection_name: str | None = None,
) -> "VectorStore":
    """Process-wide cached VectorStore, keyed by resolved collection name.

    Constructing a VectorStore loads the sentence-transformers embedding
    model into memory (PyTorch weights + runtime init) -- a real, non-trivial
    allocation. Before this cache existed, every reactive ingestion trigger
    (run_talonx.py's WatchlistDrivenIngestion, firing once per newly added/
    resumed ticker) called `run_ingestion()` and `run_news_ingestion()` back
    to back, each building its own fresh VectorStore -- reloading the model
    from scratch twice per ticker event, for the life of the process, on top
    of whatever else was already resident. That repeated reload is what was
    tripping raw malloc failures under memory pressure. Callers that want a
    private (uncached) instance can still construct VectorStore(...) directly.

    _cache_lock only protects the dict lookup/insert (so two threads racing
    to populate the SAME not-yet-cached key can't each build and load their
    own throwaway model) -- narrow and low-risk, unlike locking the actual
    query/upsert calls themselves (tried and reverted -- see
    VectorStore.__init__'s docstring). The real hazard this cache creates
    -- one shared embedding model touched from more than one OS thread --
    is avoided by keeping every caller of a cached VectorStore on the
    single asyncio event-loop thread (no asyncio.to_thread around calls
    into it), not by locking here.
    """
    resolved_config = config or settings.vector_store
    key = collection_name or resolved_config.collection_name
    with _cache_lock:
        store = _vector_store_cache.get(key)
        if store is None:
            store = VectorStore(config=resolved_config, collection_name=collection_name)
            _vector_store_cache[key] = store
        return store
