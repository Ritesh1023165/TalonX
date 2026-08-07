"""
talonx_ingest.processing.chunker
-----------------------------------
Splits cleaned filing text into embeddable chunks, tagging each chunk with
metadata (ticker, CIK, form type, filing/report date, accession number,
chunk index) so retrieval-time filtering (e.g. "only AAPL 10-Ks from the
last 2 quarters") is possible without re-parsing the vector store payloads.
"""
from __future__ import annotations

import hashlib
import logging

from langchain_text_splitters import RecursiveCharacterTextSplitter

from talonx_ingest.config import ChunkingConfig, settings
from talonx_ingest.edgar.models import FilingDocument, TextChunk

logger = logging.getLogger("talonx_ingest.processing.chunker")


class DocumentChunker:
    def __init__(self, config: ChunkingConfig | None = None):
        self.config = config or settings.chunking
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            separators=list(self.config.separators),
            length_function=len,
        )

    def chunk_document(self, document: FilingDocument) -> list[TextChunk]:
        if not document.is_ready_for_chunking:
            logger.warning(
                "Skipping chunking for %s (%s): not ready (error=%s)",
                document.metadata.company.ticker,
                document.metadata.accession_number,
                document.fetch_error,
            )
            return []

        meta = document.metadata
        base_metadata = {
            "ticker": meta.company.ticker,
            "cik": meta.company.cik,
            "company_name": meta.company.name,
            "form_type": meta.form_type,
            "accession_number": meta.accession_number,
            "filing_date": meta.filing_date.isoformat(),
            "report_date": meta.report_date.isoformat() if meta.report_date else None,
            "source_document": meta.primary_document,
        }

        chunks = self.chunk_text(
            text=document.cleaned_text,
            id_prefix=meta.accession_number,
            base_metadata=base_metadata,
        )
        logger.info(
            "Chunked %s %s (%s) into %d chunks",
            meta.company.ticker, meta.form_type, meta.accession_number, len(chunks),
        )
        return chunks

    def chunk_text(
        self, text: str, id_prefix: str, base_metadata: dict
    ) -> list[TextChunk]:
        """
        Generic text -> chunks, reusable for any source (filings, news
        articles, ...). `id_prefix` should be a stable, unique identifier
        for the source document (e.g. an accession number or an article
        hash) -- chunk IDs are derived from it plus the chunk index, so
        re-chunking the same source with the same settings always
        produces the same IDs (safe for Chroma's upsert semantics).
        """
        if not text or not text.strip():
            return []

        raw_chunks = self._splitter.split_text(text)

        chunks: list[TextChunk] = []
        for idx, chunk_text in enumerate(raw_chunks):
            stripped = chunk_text.strip()
            if len(stripped) < self.config.min_chunk_chars:
                continue

            chunk_id = self._make_chunk_id(id_prefix, idx)
            chunk_metadata = {
                **base_metadata,
                "chunk_index": idx,
                "total_chunks": len(raw_chunks),
            }
            chunks.append(
                TextChunk(chunk_id=chunk_id, text=stripped, metadata=chunk_metadata)
            )
        return chunks

    def chunk_documents(self, documents: list[FilingDocument]) -> list[TextChunk]:
        all_chunks: list[TextChunk] = []
        for doc in documents:
            all_chunks.extend(self.chunk_document(doc))
        return all_chunks

    @staticmethod
    def _make_chunk_id(id_prefix: str, index: int) -> str:
        digest_input = f"{id_prefix}:{index}".encode("utf-8")
        short_hash = hashlib.sha1(digest_input).hexdigest()[:10]
        return f"{id_prefix}-{index:05d}-{short_hash}"