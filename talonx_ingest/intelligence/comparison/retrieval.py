"""
talonx_ingest.intelligence.comparison.retrieval
===============================================
Fetch + cache the primary document of a filing for comparison.

Documents are cached by accession on local disk (immutable once filed --
same reasoning as the Task 96A / IngestionLedger design). A cached filing
is never re-downloaded. Fetching goes through ``EdgarClient`` so it shares
the one SEC-compliant rate-limit / retry / backoff / User-Agent path. No
browser, no AI conversion.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from talonx_ingest.config import settings
from talonx_ingest.intelligence.comparison.identity import content_hash
from talonx_ingest.intelligence.identity import normalize_accession

logger = logging.getLogger("talonx_ingest.intelligence.comparison.retrieval")


@dataclass(frozen=True)
class FetchedDocument:
    accession: str
    url: str | None
    raw_html: str | None
    source_hash: str | None
    status: str                 # OK / UNAVAILABLE / NO_URL / CACHED
    error: str | None = None
    from_cache: bool = False


def _default_cache_dir() -> Path:
    return Path(settings.raw_cache_dir).parent / "filing_comparison_cache"


class FilingArchiveCache:
    def __init__(self, client, *, cache_dir: str | Path | None = None):
        self._client = client
        self._dir = Path(cache_dir) if cache_dir is not None else _default_cache_dir()
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, accession: str) -> Path:
        return self._dir / f"{normalize_accession(accession)}.html"

    def cached(self, accession: str) -> str | None:
        p = self._path(accession)
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        return None

    async def fetch_primary_document(
        self,
        *,
        accession: str,
        primary_document_url: str | None,
    ) -> FetchedDocument:
        acc = normalize_accession(accession)

        hit = self.cached(acc)
        if hit is not None:
            return FetchedDocument(
                accession=acc, url=primary_document_url, raw_html=hit,
                source_hash=content_hash(hit), status="CACHED", from_cache=True,
            )

        if not primary_document_url:
            return FetchedDocument(
                accession=acc, url=None, raw_html=None, source_hash=None,
                status="NO_URL", error="no primary_document_url on the event",
            )

        try:
            raw = await self._client.fetch_document(primary_document_url)
        except Exception as exc:  # noqa: BLE001 - surfaced as a quality flag upstream
            logger.warning("filing fetch failed for %s (%s): %s", acc, primary_document_url, exc)
            return FetchedDocument(
                accession=acc, url=primary_document_url, raw_html=None, source_hash=None,
                status="UNAVAILABLE", error=str(exc),
            )

        try:
            self._path(acc).write_text(raw, encoding="utf-8")
        except OSError as exc:  # cache is best-effort
            logger.warning("could not cache %s: %s", acc, exc)

        return FetchedDocument(
            accession=acc, url=primary_document_url, raw_html=raw,
            source_hash=content_hash(raw), status="OK",
        )
