"""
talonx_ingest.storage.ledger
--------------------------------
Tracks which SEC filings have been FULLY ingested (fetched, cleaned,
chunked, and embedded) so repeat pipeline runs skip work that's already
done, instead of re-fetching and re-embedding the same filings every time.

Design notes:
  - SQLite (stdlib, no new dependency), one row per filing, keyed by
    accession number (SEC's globally unique filing ID).
  - A filing is only marked complete AFTER its chunks are successfully
    upserted into the vector store -- so a crash or exception mid-run
    leaves that filing eligible for a clean retry on the next run,
    rather than being silently (and incorrectly) treated as done.
  - Filings are immutable once filed: a 10-K/A amendment gets its own
    new accession number rather than mutating the original, so "already
    ingested" is a safe, permanent skip condition -- no staleness/TTL
    logic needed.
  - This is intentionally a separate source of truth from ChromaDB
    itself, not a mirror of it. Querying Chroma metadata for "what's
    already in there" would work too, but requires loading the
    embedding model just to check state. The ledger is a plain,
    dependency-free, fast lookup.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from talonx_ingest.edgar.models import FilingMetadata

if TYPE_CHECKING:  # avoid a runtime circular import; only needed for type hints
    from talonx_ingest.news.models import NewsArticle

logger = logging.getLogger("talonx_ingest.storage.ledger")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingested_filings (
    accession_number TEXT PRIMARY KEY,
    ticker           TEXT NOT NULL,
    cik              TEXT NOT NULL,
    form_type        TEXT NOT NULL,
    filing_date      TEXT NOT NULL,
    chunk_count      INTEGER NOT NULL,
    ingested_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingested_filings_ticker
    ON ingested_filings (ticker);

CREATE TABLE IF NOT EXISTS ingested_news_articles (
    article_id   TEXT PRIMARY KEY,
    ticker       TEXT NOT NULL,
    source       TEXT NOT NULL,
    published_at TEXT,
    chunk_count  INTEGER NOT NULL,
    ingested_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingested_news_ticker
    ON ingested_news_articles (ticker);
"""


class IngestionLedger:
    """
    Not safe to share across OS threads (plain sqlite3.Connection,
    check_same_thread defaults to True). Safe to use from multiple
    asyncio tasks on the SAME thread/event loop, since asyncio is
    cooperative and these calls are synchronous, fast, local disk I/O --
    intentionally NOT wrapped in asyncio.to_thread, to avoid handing the
    connection to a different real thread.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "IngestionLedger":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def is_ingested(self, accession_number: str) -> bool:
        cursor = self._conn.execute(
            "SELECT 1 FROM ingested_filings WHERE accession_number = ?",
            (accession_number,),
        )
        return cursor.fetchone() is not None

    def filter_unseen(self, filings: list[FilingMetadata]) -> list[FilingMetadata]:
        """Return only the filings NOT already recorded as fully ingested."""
        if not filings:
            return []

        placeholders = ",".join("?" for _ in filings)
        accession_numbers = [f.accession_number for f in filings]
        cursor = self._conn.execute(
            f"SELECT accession_number FROM ingested_filings "
            f"WHERE accession_number IN ({placeholders})",
            accession_numbers,
        )
        already_seen = {row[0] for row in cursor.fetchall()}

        unseen = [f for f in filings if f.accession_number not in already_seen]
        skipped = len(filings) - len(unseen)
        if skipped:
            logger.info(
                "Ledger: skipping %d already-ingested filing(s), %d new",
                skipped, len(unseen),
            )
        return unseen

    def mark_ingested(self, filing: FilingMetadata, chunk_count: int) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO ingested_filings
                (accession_number, ticker, cik, form_type, filing_date,
                 chunk_count, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                filing.accession_number,
                filing.company.ticker,
                filing.company.cik,
                filing.form_type,
                filing.filing_date.isoformat(),
                chunk_count,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def stats_by_ticker(self, ticker: str) -> list[dict]:
        cursor = self._conn.execute(
            """
            SELECT accession_number, form_type, filing_date, chunk_count, ingested_at
            FROM ingested_filings WHERE ticker = ?
            ORDER BY filing_date DESC
            """,
            (ticker.upper(),),
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def forget_ticker(self, ticker: str) -> int:
        """Remove all ledger rows for a ticker, forcing full re-ingestion next run."""
        cursor = self._conn.execute(
            "DELETE FROM ingested_filings WHERE ticker = ?", (ticker.upper(),)
        )
        self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # News/social article tracking (separate table, same dedup philosophy:
    # once an article's chunks are fully embedded, skip it permanently.
    # Unlike filings, article content doesn't have a guaranteed-immutable
    # ID from an authoritative registry -- we use a hash of its URL,
    # computed by the caller (see news.models.NewsArticle.article_id).
    # ------------------------------------------------------------------

    def is_news_ingested(self, article_id: str) -> bool:
        cursor = self._conn.execute(
            "SELECT 1 FROM ingested_news_articles WHERE article_id = ?",
            (article_id,),
        )
        return cursor.fetchone() is not None

    def filter_unseen_articles(self, articles: list["NewsArticle"]) -> list["NewsArticle"]:
        """Return only articles NOT already recorded as fully ingested."""
        if not articles:
            return []

        placeholders = ",".join("?" for _ in articles)
        article_ids = [a.article_id for a in articles]
        cursor = self._conn.execute(
            f"SELECT article_id FROM ingested_news_articles "
            f"WHERE article_id IN ({placeholders})",
            article_ids,
        )
        already_seen = {row[0] for row in cursor.fetchall()}

        unseen = [a for a in articles if a.article_id not in already_seen]
        skipped = len(articles) - len(unseen)
        if skipped:
            logger.info(
                "Ledger: skipping %d already-ingested article(s), %d new",
                skipped, len(unseen),
            )
        return unseen

    def mark_news_ingested(self, article: "NewsArticle", chunk_count: int) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO ingested_news_articles
                (article_id, ticker, source, published_at, chunk_count, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                article.article_id,
                article.ticker,
                article.source,
                article.published_at.isoformat() if article.published_at else None,
                chunk_count,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
