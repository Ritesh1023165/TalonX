"""
talonx_ingest.news.client
------------------------------
Fetches recent news articles per ticker.

Primary source: NewsAPI.org's `/v2/everything` endpoint (requires
NEWS_API_KEY). Fallback, used automatically when no key is configured:
Yahoo Finance's public per-ticker RSS feed, which needs no API key or
account at all. This mirrors the same "best available source, graceful
fallback" philosophy as market_data (Polygon WebSocket -> yfinance
polling).

Both paths are wrapped with retry/backoff (NewsAPI via aiohttp directly;
RSS parsing is a synchronous feedparser call, so it's wrapped in
asyncio.to_thread so it doesn't block the event loop).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiohttp

from talonx_ingest.common.backoff import jittered_backoff_seconds
from talonx_ingest.config import NewsConfig, settings
from talonx_ingest.news.models import NewsArticle

logger = logging.getLogger("talonx_ingest.news.client")


class NewsClientError(Exception):
    """Non-retryable news fetch error."""


class NewsClient:
    def __init__(self, config: NewsConfig | None = None):
        self.config = config or settings.news

    async def fetch_for_ticker(self, ticker: str) -> list[NewsArticle]:
        if self.config.news_api_key:
            try:
                return await self._fetch_from_newsapi(ticker)
            except NewsClientError as exc:
                logger.error(
                    "NewsAPI fetch failed for %s (%s) -- falling back to "
                    "RSS for this ticker", ticker, exc,
                )
        return await self._fetch_from_rss(ticker)

    # ------------------------------------------------------------------
    # NewsAPI.org path
    # ------------------------------------------------------------------

    async def _fetch_from_newsapi(self, ticker: str) -> list[NewsArticle]:
        from_date = (
            datetime.now(timezone.utc) - timedelta(days=self.config.lookback_days)
        ).strftime("%Y-%m-%d")

        params = {
            "q": ticker,
            "from": from_date,
            "sortBy": "publishedAt",
            "pageSize": str(self.config.articles_per_ticker),
            "language": "en",
            "apiKey": self.config.news_api_key,
        }

        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout_seconds)
        last_exc: Exception | None = None

        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            for attempt in range(1, self.config.max_retries + 1):
                try:
                    async with session.get(self.config.news_api_base_url, params=params) as resp:
                        if resp.status == 200:
                            payload = await resp.json()
                            return self._parse_newsapi_response(ticker, payload)
                        if resp.status in (401, 403):
                            body = (await resp.text())[:200]
                            raise NewsClientError(
                                f"NewsAPI auth error {resp.status}: {body}"
                            )
                        if resp.status == 429 or resp.status >= 500:
                            wait = jittered_backoff_seconds(
                                attempt, self.config.backoff_base_seconds,
                                self.config.backoff_max_seconds,
                            )
                            logger.warning(
                                "NewsAPI %s for %s (attempt %d/%d), retrying in %.1fs",
                                resp.status, ticker, attempt, self.config.max_retries, wait,
                            )
                            await asyncio.sleep(wait)
                            continue
                        raise NewsClientError(f"NewsAPI unexpected status {resp.status}")
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    last_exc = exc
                    wait = jittered_backoff_seconds(
                        attempt, self.config.backoff_base_seconds, self.config.backoff_max_seconds
                    )
                    logger.warning(
                        "NewsAPI network error for %s (attempt %d/%d): %s; retrying in %.1fs",
                        ticker, attempt, self.config.max_retries, exc, wait,
                    )
                    await asyncio.sleep(wait)

        raise NewsClientError(
            f"Exhausted {self.config.max_retries} retries fetching NewsAPI for {ticker}"
        ) from last_exc

    def _parse_newsapi_response(self, ticker: str, payload: dict) -> list[NewsArticle]:
        articles = []
        for item in payload.get("articles", []):
            url = item.get("url")
            title = item.get("title")
            if not url or not title:
                continue
            published_at = _parse_iso_datetime(item.get("publishedAt"))
            source_name = (item.get("source") or {}).get("name", "newsapi")
            summary = item.get("description") or item.get("content") or ""
            articles.append(
                NewsArticle(
                    ticker=ticker.upper(),
                    title=title,
                    url=url,
                    source=f"newsapi:{source_name}",
                    published_at=published_at,
                    summary=summary.strip(),
                )
            )
        logger.info("NewsAPI returned %d articles for %s", len(articles), ticker)
        return articles

    # ------------------------------------------------------------------
    # Yahoo Finance RSS fallback path (no API key required)
    # ------------------------------------------------------------------

    async def _fetch_from_rss(self, ticker: str) -> list[NewsArticle]:
        url = self.config.rss_feed_url_template.format(symbol=ticker.upper())
        last_exc: Exception | None = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                articles = await asyncio.to_thread(self._parse_rss_feed, ticker, url)
                logger.info("RSS feed returned %d articles for %s", len(articles), ticker)
                return articles
            except Exception as exc:  # noqa: BLE001 -- feedparser can raise various things
                last_exc = exc
                wait = jittered_backoff_seconds(
                    attempt, self.config.backoff_base_seconds, self.config.backoff_max_seconds
                )
                logger.warning(
                    "RSS fetch failed for %s (attempt %d/%d): %s; retrying in %.1fs",
                    ticker, attempt, self.config.max_retries, exc, wait,
                )
                await asyncio.sleep(wait)

        logger.error(
            "Exhausted %d retries fetching RSS for %s: %s -- returning no articles",
            self.config.max_retries, ticker, last_exc,
        )
        return []  # RSS is already the fallback -- nowhere further to fall back to

    def _parse_rss_feed(self, ticker: str, url: str) -> list[NewsArticle]:
        import feedparser  # imported lazily so this stays an optional dependency

        parsed = feedparser.parse(url)
        if parsed.bozo and not parsed.entries:
            raise NewsClientError(f"RSS feed unparseable: {parsed.bozo_exception}")

        articles = []
        for entry in parsed.entries[: self.config.articles_per_ticker]:
            link = entry.get("link")
            title = entry.get("title")
            if not link or not title:
                continue
            published_at = None
            if getattr(entry, "published_parsed", None):
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            articles.append(
                NewsArticle(
                    ticker=ticker.upper(),
                    title=title,
                    url=link,
                    source="rss:finance.yahoo.com",
                    published_at=published_at,
                    summary=(entry.get("summary") or "").strip(),
                )
            )
        return articles


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None