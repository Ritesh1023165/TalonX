"""
talonx_brain.cache
-----------------------
Redis-backed caching for ResearchReport, keyed per ticker
(`brain_cache:{ticker}`), plus the distributed lock that prevents a cache
stampede when multiple workers race to populate the same ticker's entry.

Why a cache entry embeds its OWN expiry rather than relying purely on
Redis's EX-based TTL: the requirement doc wants BOTH cache-first (skip
Gemini on a fresh hit) AND a fallback to an EXPIRED entry (flagged
`is_stale=True`) when a live regeneration attempt fails. Redis's native
TTL can't do both -- once a key's TTL elapses, Redis just deletes it, so
there'd be nothing left to fall back to. Instead, every entry stores its
own logical `expires_at` timestamp inside the JSON payload, and is
written to Redis under a much longer SAFETY-NET TTL
(`cache_safety_ttl_seconds`) that only exists to stop a forgotten entry
from living in Redis forever. Reads compare `now` against the EMBEDDED
`expires_at`, not Redis's own remaining TTL, to decide fresh vs stale --
`get()` returns both so the caller (consumer.py) decides policy: a
cache-first lookup only accepts a fresh hit, a post-failure fallback
lookup accepts either.

Phase 2: every method takes a `horizon` param, default "intraday" --
that default preserves the EXACT pre-Phase-2 key format
(`brain_cache:{TICKER}`, `lock:brain:{TICKER}`) byte-for-byte, so no
existing cache entry is invalidated by this change. `horizon="long_term"`
uses a separate key namespace (`brain_cache:long_term:{TICKER}`) and a
separate (LongTermResearchReport-typed, flat 90-day, no-market-boundary)
expiry policy -- see next_expiry()'s docstring.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from talonx_brain.config import BrainConfig
from talonx_brain.schemas import LongTermResearchReport, ResearchReport

logger = logging.getLogger("talonx_brain.cache")

_REPORT_CLS_BY_HORIZON = {"intraday": ResearchReport, "long_term": LongTermResearchReport}


class BrainCache:
    def __init__(self, client, config: BrainConfig | None = None):
        self._client = client
        self.config = config or BrainConfig()

    @staticmethod
    def _cache_key(ticker: str, horizon: str = "intraday") -> str:
        if horizon == "intraday":
            return f"brain_cache:{ticker.upper()}"
        return f"brain_cache:{horizon}:{ticker.upper()}"

    @staticmethod
    def _lock_key(ticker: str, horizon: str = "intraday") -> str:
        if horizon == "intraday":
            return f"lock:brain:{ticker.upper()}"
        return f"lock:brain:{horizon}:{ticker.upper()}"

    async def get(
        self, ticker: str, horizon: str = "intraday",
    ) -> tuple[ResearchReport | LongTermResearchReport, bool] | None:
        """Returns (report, is_fresh) if an entry exists at all, else None
        if there's nothing cached. Doesn't decide fresh-vs-stale POLICY --
        see module docstring."""
        try:
            raw = await self._client.get(self._cache_key(ticker, horizon))
        except Exception as exc:  # noqa: BLE001 -- a Redis hiccup shouldn't crash generation
            logger.warning("Cache read failed for %s/%s, treating as a miss: %s", horizon, ticker, exc)
            return None
        if raw is None:
            return None

        try:
            envelope = json.loads(raw)
            report_cls = _REPORT_CLS_BY_HORIZON[horizon]
            report = report_cls.model_validate(envelope["report"])
            expires_at = datetime.fromisoformat(envelope["expires_at"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Dropping unparseable cache entry for %s/%s: %s", horizon, ticker, exc)
            return None

        is_fresh = datetime.now(timezone.utc) <= expires_at
        return report, is_fresh

    async def set(
        self, ticker: str, report: ResearchReport | LongTermResearchReport, horizon: str = "intraday",
    ) -> None:
        expires_at = self.next_expiry(datetime.now(timezone.utc), horizon)
        envelope = json.dumps(
            {"report": json.loads(report.model_dump_json()), "expires_at": expires_at.isoformat()}
        )
        try:
            await self._client.set(
                self._cache_key(ticker, horizon), envelope, ex=int(self.config.cache_safety_ttl_seconds)
            )
        except Exception as exc:  # noqa: BLE001 -- caching is an optimization, not required for correctness
            logger.warning("Cache write failed for %s/%s: %s", horizon, ticker, exc)

    async def invalidate(self, ticker: str, horizon: str = "intraday") -> None:
        try:
            await self._client.delete(self._cache_key(ticker, horizon))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache invalidation failed for %s/%s: %s", horizon, ticker, exc)

    def next_expiry(self, now: datetime, horizon: str = "intraday") -> datetime:
        """Intraday: the sooner of (now + cache_base_ttl_seconds) or the
        next daily market-open/close boundary in the configured exchange
        timezone -- so a cached report never outlives the trading session
        it was generated for, e.g. overnight earnings force fresh
        analysis at the next open (Requirement 4D). No holiday/weekend
        calendar awareness -- plain daily clock-time boundaries.

        long_term: a flat cache_base_ttl_long_term_seconds cap (default
        90 days) with NO market-boundary math at all -- a multi-year
        holding thesis has no "trading session" to not outlive. The
        spec's other half ("or until the next SEC filing") is satisfied
        by invalidate() being called on both NewFilingIngestedEvent and
        NewFundamentalsIngestedEvent for this horizon, not by anything
        here."""
        if horizon == "long_term":
            return now + timedelta(seconds=self.config.cache_base_ttl_long_term_seconds)
        base = now + timedelta(seconds=self.config.cache_base_ttl_seconds)
        boundary = self._next_market_boundary(now)
        return min(base, boundary)

    def _next_market_boundary(self, now: datetime) -> datetime:
        tz = ZoneInfo(self.config.market_timezone)
        local_now = now.astimezone(tz)
        candidates = [
            (local_now + timedelta(days=day_offset)).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            for day_offset in (0, 1)
            for hour in (self.config.market_open_hour, self.config.market_close_hour)
        ]
        boundary = min(c for c in candidates if c > local_now)
        return boundary.astimezone(timezone.utc)

    async def acquire_lock(self, ticker: str, horizon: str = "intraday") -> bool:
        try:
            acquired = await self._client.set(
                self._lock_key(ticker, horizon), "1", nx=True, ex=int(self.config.cache_lock_ttl_seconds)
            )
        except Exception as exc:  # noqa: BLE001 -- Redis hiccup shouldn't block generation forever
            logger.warning("Lock acquire failed for %s/%s, proceeding without it: %s", horizon, ticker, exc)
            return False
        return bool(acquired)

    async def release_lock(self, ticker: str, horizon: str = "intraday") -> None:
        try:
            await self._client.delete(self._lock_key(ticker, horizon))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Lock release failed for %s/%s (it will expire on its own): %s", horizon, ticker, exc)

    async def wait_for_cache(
        self, ticker: str, horizon: str = "intraday",
    ) -> tuple[ResearchReport | LongTermResearchReport, bool] | None:
        """For a worker that LOST the lock race: polls for the winner to
        populate the cache, up to cache_lock_wait_seconds, rather than
        duplicating the LLM call. Returns None (not an error) on timeout
        -- the caller falls through to generating its own report."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.config.cache_lock_wait_seconds
        poll_interval = 0.5
        while loop.time() < deadline:
            hit = await self.get(ticker, horizon)
            if hit is not None:
                return hit
            await asyncio.sleep(poll_interval)
        return None
