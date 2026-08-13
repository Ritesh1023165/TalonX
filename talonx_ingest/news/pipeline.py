"""
talonx_ingest.news.pipeline
--------------------------------
Orchestrates news/social feed ingestion:

    tickers -> fetch recent articles (NewsAPI, or RSS fallback)
            -> ALSO fetch recent Reddit posts (optional -- see
               RedditConfig; [] if REDDIT_CLIENT_ID/SECRET aren't set)
            -> [ledger check: skip already-ingested articles/posts]
            -> chunk -> embed -> ChromaDB (separate "news_feed" collection)
            -> [ledger: mark each article/post complete once its chunks land]

Deliberately mirrors talonx_ingest.pipeline's structure (same incremental
ledger philosophy, same partial-upsert safety) so the two are easy to
reason about side by side. News articles get their own ChromaDB
collection (configurable, default "news_feed") rather than sharing
"sec_filings" -- keeping filing text and news text queryable separately,
per the project's structured/unstructured separation principle. Reddit
posts are normalized into the same NewsArticle shape as NewsAPI/RSS
articles (see reddit_client.py), so they flow through this exact same
path with no special-casing below.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from talonx_ingest.config import settings
from talonx_ingest.news.client import NewsClient
from talonx_ingest.news.models import NewsArticle
from talonx_ingest.news.reddit_client import RedditClient
from talonx_ingest.processing.chunker import DocumentChunker
from talonx_ingest.storage.ledger import IngestionLedger
from talonx_ingest.storage.vector_store import VectorStore, get_vector_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("talonx_ingest.news.pipeline")


async def ingest_ticker_news(
    ticker: str,
    news_client: NewsClient,
    chunker: DocumentChunker,
    vector_store: VectorStore,
    ledger: IngestionLedger,
    reddit_client: RedditClient | None = None,
    force_refresh: bool = False,
) -> int:
    """Fetch, chunk, and embed new articles/posts for one ticker. Returns new chunks written."""
    logger.info("[%s] Fetching recent news/social articles...", ticker)
    news_articles = await news_client.fetch_for_ticker(ticker)

    reddit_articles: list[NewsArticle] = []
    if reddit_client is not None:
        reddit_articles = await reddit_client.fetch_for_ticker(ticker)
        if reddit_articles:
            logger.info("[%s] Found %d Reddit post(s)", ticker, len(reddit_articles))

    all_articles = news_articles + reddit_articles
    if not all_articles:
        logger.warning("[%s] No articles found", ticker)
        return 0

    target_articles = (
        all_articles if force_refresh else ledger.filter_unseen_articles(all_articles)
    )
    if not target_articles:
        logger.info(
            "[%s] Up to date -- all %d recent articles already ingested",
            ticker, len(all_articles),
        )
        return 0

    total_written = 0
    for article in target_articles:
        chunks = _chunk_article(chunker, article)
        if not chunks:
            continue  # empty/too-short summary -- nothing to embed

        written = vector_store.upsert_chunks(chunks)
        if written == len(chunks):
            ledger.mark_news_ingested(article, chunk_count=written)
            total_written += written
        else:
            logger.error(
                "[%s] Partial upsert for article %s (%d/%d chunks) -- "
                "NOT marking ledger complete, will retry next run",
                ticker, article.article_id, written, len(chunks),
            )

    logger.info(
        "[%s] Ingested %d new chunks across %d article(s) this run",
        ticker, total_written, len(target_articles),
    )
    return total_written


def _chunk_article(chunker: DocumentChunker, article: NewsArticle) -> list:
    # Combine title + summary so the title's signal isn't lost for short
    # articles that would otherwise be a single small chunk.
    text = f"{article.title}\n\n{article.summary}".strip()
    base_metadata = {
        "ticker": article.ticker,
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at.isoformat() if article.published_at else None,
    }
    return chunker.chunk_text(text=text, id_prefix=article.article_id, base_metadata=base_metadata)


async def run_news_ingestion(
    tickers: list[str], force_refresh: bool = False
) -> dict[str, int]:
    logger.info("Starting news ingestion for tickers: %s", tickers)

    news_client = NewsClient()
    reddit_client = RedditClient()  # no-op per ticker if not configured -- see RedditConfig
    chunker = DocumentChunker()

    # Cached process-wide (see get_vector_store's docstring) -- this used to
    # reload the embedding model fresh on every call, and WatchlistDrivenIngestion
    # in run_talonx.py calls run_news_ingestion right after run_ingestion on
    # every single reactive ticker-add event, doubling that reload per event.
    vector_store = get_vector_store(collection_name=settings.news.vector_collection_name)
    logger.info(
        "News vector store ready (collection=%s). Existing chunk count: %d. "
        "Reddit source: %s",
        settings.news.vector_collection_name, vector_store.count(),
        "enabled" if reddit_client.is_configured else "not configured (REDDIT_CLIENT_ID/SECRET unset)",
    )

    ledger = IngestionLedger(settings.ledger.path)  # same ledger file, separate table

    results: dict[str, int] = {}
    try:
        tasks = {
            ticker: asyncio.create_task(
                ingest_ticker_news(
                    ticker, news_client, chunker, vector_store, ledger,
                    reddit_client=reddit_client, force_refresh=force_refresh,
                )
            )
            for ticker in tickers
        }
        for ticker, task in tasks.items():
            try:
                results[ticker] = await task
            except Exception as exc:  # noqa: BLE001 -- isolate per-ticker failures
                logger.error("Unhandled error ingesting news for %s: %s", ticker, exc)
                results[ticker] = 0
    finally:
        ledger.close()

    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TalonX news/social feed ingestion")
    parser.add_argument(
        "tickers", nargs="*", default=["AAPL", "MSFT", "NVDA"],
        help="Ticker symbols to ingest news for (default: AAPL MSFT NVDA)",
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Bypass the ledger and reprocess all articles even if already ingested",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    summary = asyncio.run(run_news_ingestion(args.tickers, force_refresh=args.force_refresh))
    print("News ingestion summary (new chunks written this run):", summary)