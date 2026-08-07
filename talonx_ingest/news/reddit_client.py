"""
talonx_ingest.news.reddit_client
-------------------------------------
Optional social-feed source: searches a configured set of subreddits
(default: wallstreetbets, stocks, investing -- see RedditConfig) for
recent posts mentioning a ticker, via Reddit's OAuth2 API. Normalizes
results into the same NewsArticle shape client.py's NewsAPI/RSS path
produces, so the rest of the pipeline (chunk -> embed -> ledger ->
"news_feed" collection) needs no changes to accept Reddit content.

Additive, not a fallback: see RedditConfig's docstring in config.py for
why this sits alongside NewsClient rather than inside its NewsAPI/RSS
fallback chain, and why Twitter/X was deliberately not built.

Uses the client_credentials OAuth grant (app-only auth -- no Reddit user
account needed, just the registered app's own id/secret), rate-limited
via a token-bucket, same proactive-throttle pattern talonx_brain uses for
Gemini (paces calls to stay under quota instead of reactively retrying
429s).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import aiohttp

from talonx_ingest.common.backoff import jittered_backoff_seconds
from talonx_ingest.config import RedditConfig, settings
from talonx_ingest.news.models import NewsArticle

logger = logging.getLogger("talonx_ingest.news.reddit_client")

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"


class RedditClientError(Exception):
    """Non-retryable Reddit fetch error."""


class _TokenBucket:
    """
    Async token-bucket rate limiter -- same shape as the one
    talonx_ingest.edgar.client uses for SEC's request cap. Duplicated
    here (module-private in both places) rather than shared, matching
    the small-per-module-utility convention already established for it
    elsewhere in this project (see talonx_brain.llm's own copy).
    """

    def __init__(self, rate_per_minute: float):
        self.rate = rate_per_minute / 60.0
        self.capacity = max(rate_per_minute, 1.0)
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._last_refill = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                deficit = 1 - self._tokens
                wait_time = deficit / self.rate
            await asyncio.sleep(wait_time)


class RedditClient:
    def __init__(self, config: RedditConfig | None = None):
        self.config = config or settings.reddit
        self._bucket = _TokenBucket(self.config.max_requests_per_minute)
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0  # time.monotonic()-based

    @property
    def is_configured(self) -> bool:
        return bool(self.config.client_id and self.config.client_secret)

    async def fetch_for_ticker(self, ticker: str) -> list[NewsArticle]:
        """
        Returns [] immediately, with no network call, if Reddit isn't
        configured -- this is what makes it "additive, not required":
        callers don't need to check is_configured themselves.
        """
        if not self.is_configured:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.lookback_days)
        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout_seconds)
        headers = {"User-Agent": self.config.user_agent}

        articles: list[NewsArticle] = []
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True, headers=headers) as session:
            try:
                token = await self._ensure_token(session)
            except (aiohttp.ClientError, asyncio.TimeoutError, RedditClientError) as exc:
                logger.warning(
                    "Reddit auth failed, skipping Reddit for %s: %s", ticker, exc
                )
                return []

            for subreddit in self.config.subreddits:
                try:
                    posts = await self._search_subreddit(session, token, subreddit, ticker, cutoff)
                    articles.extend(posts)
                except RedditClientError as exc:
                    logger.warning(
                        "Reddit search failed for r/%s (%s): %s -- skipping this subreddit",
                        subreddit, ticker, exc,
                    )

        articles.sort(
            key=lambda a: a.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        result = articles[: self.config.posts_per_ticker]
        logger.info(
            "Reddit returned %d post(s) for %s across %d subreddit(s)",
            len(result), ticker, len(self.config.subreddits),
        )
        return result

    async def _ensure_token(self, session: aiohttp.ClientSession) -> str:
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        auth = aiohttp.BasicAuth(self.config.client_id, self.config.client_secret)
        async with session.post(
            _TOKEN_URL, auth=auth, data={"grant_type": "client_credentials"}
        ) as resp:
            if resp.status != 200:
                body = (await resp.text())[:200]
                raise RedditClientError(f"Reddit auth failed {resp.status}: {body}")
            payload = await resp.json()

        token = payload.get("access_token")
        if not token:
            raise RedditClientError(f"Reddit auth response missing access_token: {payload}")

        self._access_token = token
        # Refresh a bit early (60s margin) rather than right at expiry.
        self._token_expires_at = time.monotonic() + payload.get("expires_in", 3600) - 60
        return token

    async def _search_subreddit(
        self,
        session: aiohttp.ClientSession,
        token: str,
        subreddit: str,
        ticker: str,
        cutoff: datetime,
    ) -> list[NewsArticle]:
        url = f"https://oauth.reddit.com/r/{subreddit}/search"
        params = {
            "q": ticker,
            "restrict_sr": "1",
            "sort": "new",
            "limit": "25",
            "t": _time_filter_for(self.config.lookback_days),
        }
        headers = {"Authorization": f"Bearer {token}"}

        last_exc: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            await self._bucket.acquire()
            try:
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        payload = await resp.json()
                        return _parse_listing(ticker, subreddit, payload, cutoff)
                    if resp.status in (401, 403):
                        body = (await resp.text())[:200]
                        raise RedditClientError(f"Reddit auth/permission error {resp.status}: {body}")
                    if resp.status == 429 or resp.status >= 500:
                        wait = jittered_backoff_seconds(
                            attempt, self.config.backoff_base_seconds, self.config.backoff_max_seconds
                        )
                        logger.warning(
                            "Reddit %s for r/%s %s (attempt %d/%d), retrying in %.1fs",
                            resp.status, subreddit, ticker, attempt, self.config.max_retries, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise RedditClientError(f"Reddit unexpected status {resp.status} for r/{subreddit}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                wait = jittered_backoff_seconds(
                    attempt, self.config.backoff_base_seconds, self.config.backoff_max_seconds
                )
                logger.warning(
                    "Reddit network error for r/%s %s (attempt %d/%d): %s; retrying in %.1fs",
                    subreddit, ticker, attempt, self.config.max_retries, exc, wait,
                )
                await asyncio.sleep(wait)

        raise RedditClientError(
            f"Exhausted {self.config.max_retries} retries searching r/{subreddit} for {ticker}"
        ) from last_exc


def _time_filter_for(lookback_days: int) -> str:
    """Maps a lookback window to Reddit search's coarse `t=` parameter."""
    if lookback_days <= 1:
        return "day"
    if lookback_days <= 7:
        return "week"
    if lookback_days <= 31:
        return "month"
    if lookback_days <= 365:
        return "year"
    return "all"


def _parse_listing(
    ticker: str, subreddit: str, payload: dict, cutoff: datetime
) -> list[NewsArticle]:
    articles = []
    for child in payload.get("data", {}).get("children", []):
        post = child.get("data", {})
        permalink = post.get("permalink")
        title = post.get("title")
        if not permalink or not title:
            continue

        created_utc = post.get("created_utc")
        published_at = (
            datetime.fromtimestamp(created_utc, tz=timezone.utc) if created_utc else None
        )
        # Reddit's own t= filter is coarse (day/week/month/...) -- this
        # enforces the exact lookback_days cutoff on top of it.
        if published_at and published_at < cutoff:
            continue

        selftext = (post.get("selftext") or "").strip()
        # Link posts (news articles shared to Reddit, not text posts)
        # have no selftext -- fall back to just the title so there's
        # still something to embed.
        summary = selftext[:1000] if selftext else title

        articles.append(
            NewsArticle(
                ticker=ticker.upper(),
                title=title,
                url=f"https://www.reddit.com{permalink}",
                source=f"reddit:r/{subreddit}",
                published_at=published_at,
                summary=summary,
            )
        )
    return articles
