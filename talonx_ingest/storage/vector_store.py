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
