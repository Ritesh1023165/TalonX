"""
talonx_brain.consumer
--------------------------
Async Redis Pub/Sub consumer: subscribes to talonx:signals:quant, and for
each QuantSignal retrieves relevant filing and news context from ChromaDB,
runs it through the configured LLM's structured RAG chain (Gemini or a
local Ollama model -- see llm.build_research_chain / config.llm_provider),
and publishes the resulting ResearchReport to talonx:reports:brain.

Also subscribes to talonx:filings:events (talonx_ingest already publishes
NewFilingIngestedEvent there after every successful filing ingestion) to
invalidate cached research the moment a ticker's filings change -- see
cache.py for the caching layer this drives.

Reconnects with backoff on Redis connection loss, same pattern as
talonx_quant.consumer.QuantScanner (reusing talonx_ingest.common.backoff
here rather than re-implementing jitter a third time, since this module
already has a real import dependency on talonx_ingest -- see config.py).

A failure generating ONE report (retrieval error, LLM error, etc.) is
logged and skipped rather than tearing down the whole listener -- one bad
signal shouldn't stop research on the next one. An LLM failure
specifically doesn't just get dropped, though -- see _generate_report's
fallback chain (stale cache, then a degraded quant-only report) so a
QuantSignal always eventually gets SOME report published.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from pydantic import ValidationError

from talonx_ingest.common.backoff import jittered_backoff_seconds
from talonx_ingest.events.schemas import NewFilingIngestedEvent

from talonx_brain.cache import BrainCache
from talonx_brain.config import BrainConfig
from talonx_brain.llm import _BaseResearchChain, build_research_chain
from talonx_brain.retriever import ContextRetriever
from talonx_brain.schemas import QuantSignal, ResearchReport, ResearchVerdict
from talonx_brain.store import BrainStatsStore

logger = logging.getLogger("talonx_brain.consumer")

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None


class ResearchAgent:
    def __init__(
        self,
        config: BrainConfig | None = None,
        retriever: ContextRetriever | None = None,
        llm_chain: _BaseResearchChain | None = None,
        cache: BrainCache | None = None,
        store: BrainStatsStore | None = None,
    ):
        self.config = config or BrainConfig()
        self.retriever = retriever or ContextRetriever(self.config)
        self.llm_chain = llm_chain or build_research_chain(self.config)
        self.store = store
        # None until _connect_and_listen builds one against the real,
        # connected client -- unless a caller injects one directly (tests
        # inject a BrainCache pre-wired to a mock client, so
        # _connect_and_listen must NOT overwrite it -- see there).
        self.cache: BrainCache | None = cache
        self._client = None
        self._stop_event = asyncio.Event()
        self._reports_published = 0
        self._signals_processed = 0
        self._filing_invalidations = 0

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def reports_published(self) -> int:
        return self._reports_published

    @property
    def signals_processed(self) -> int:
        return self._signals_processed

    async def run(self) -> None:
        if redis_asyncio is None:
            raise ImportError(
                "The 'redis' package is required. Install it with: pip install redis"
            )

        attempt = 0
        while not self._stop_event.is_set():
            try:
                await self._connect_and_listen()
                return  # clean stop() was called
            except Exception as exc:  # noqa: BLE001 -- any connection/listen failure retries
                attempt += 1
                wait = jittered_backoff_seconds(
                    attempt,
                    self.config.reconnect_backoff_base_seconds,
                    self.config.reconnect_backoff_max_seconds,
                )
                logger.warning(
                    "Redis connection/listen error (%s); reconnecting in %.1fs (attempt %d)",
                    exc, wait, attempt,
                )
                await asyncio.sleep(wait)

    async def _connect_and_listen(self) -> None:
        self._client = redis_asyncio.from_url(
            self.config.redis_url,
            socket_connect_timeout=self.config.connect_timeout_seconds,
            socket_timeout=self.config.socket_timeout_seconds,
        )
        await self._client.ping()
        logger.info("Connected to Redis at %s", self.config.redis_url)

        if self.cache is None:
            self.cache = BrainCache(self._client, self.config)

        pubsub = self._client.pubsub()
        await pubsub.subscribe(self.config.signals_channel, self.config.filings_channel)
        logger.info(
            "Subscribed to %s and %s", self.config.signals_channel, self.config.filings_channel,
        )

        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue  # normal: no message within this poll window
                await self._handle_message(message)
        finally:
            await pubsub.unsubscribe(self.config.signals_channel, self.config.filings_channel)
            await pubsub.aclose()
            await self._client.aclose()

    async def _handle_message(self, message: dict) -> None:
        raw = message.get("data")
        if raw is None:
            return

        channel = message.get("channel")
        if isinstance(channel, bytes):
            channel = channel.decode()

        if channel == self.config.filings_channel:
            await self._handle_filing_event(raw)
            return
        if channel != self.config.signals_channel:
            logger.warning("Dropping message on unexpected channel %s", channel)
            return

        try:
            payload = json.loads(raw)
            signal = QuantSignal.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Dropping unparseable message on signals channel: %s", exc)
            return

        self._signals_processed += 1
        logger.info(
            "Researching %s trigger for %s: %s",
            signal.signal_type.value, signal.ticker, signal.message,
        )

        try:
            report = await self._generate_report(signal)
        except Exception as exc:  # noqa: BLE001 -- one bad signal shouldn't kill the listener
            logger.error("Failed to generate research report for %s: %s", signal.ticker, exc)
            return

        await self._publish_report(report)

    async def _handle_filing_event(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
            event = NewFilingIngestedEvent.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Dropping unparseable message on filings channel: %s", exc)
            return

        logger.info(
            "New filing for %s (%s, accession %s) -- invalidating cached research",
            event.ticker, event.form_type, event.accession_number,
        )
        await self.cache.invalidate(event.ticker)
        self._filing_invalidations += 1

    @property
    def filing_invalidations(self) -> int:
        return self._filing_invalidations

    async def _generate_report(self, signal: QuantSignal) -> ResearchReport:
        """
        Cache-first (Requirement 2): a fresh hit skips retrieval AND the
        LLM call entirely -- this is the actual token-spend reduction. On
        a miss, a distributed lock (lock:brain:{ticker}) prevents a cache
        stampede if this ever runs as more than one process (today it
        doesn't -- see cache.py's docstring); a worker that loses the lock
        race waits briefly for the winner to populate the cache rather
        than duplicating the LLM call, falling through to generating its
        own only if that wait times out.
        """
        ticker = signal.ticker

        if self.config.cache_enabled and self.cache is not None:
            hit = await self.cache.get(ticker)
            if hit is not None and hit[1]:  # fresh
                logger.info("Cache hit for %s -- skipping retrieval and the LLM call", ticker)
                return hit[0].model_copy(update={"triggering_signal": signal, "from_cache": True})

        acquired = False
        if self.config.cache_enabled and self.cache is not None:
            acquired = await self.cache.acquire_lock(ticker)
            if not acquired:
                waited = await self.cache.wait_for_cache(ticker)
                if waited is not None:
                    logger.info(
                        "Another worker populated the cache for %s while waiting -- using it", ticker,
                    )
                    return waited[0].model_copy(update={"triggering_signal": signal, "from_cache": True})
                # Timed out waiting -- proceed to generate without the lock
                # rather than blocking forever.

        try:
            report = await self._generate_fresh_report(signal)
        finally:
            if acquired:
                await self.cache.release_lock(ticker)

        # Only a genuinely FRESH generation gets cached -- a degraded
        # report has no real content worth keeping, and a stale-fallback
        # report is already the (older) cache entry itself, so re-setting
        # it would just refresh its expiry without any new information
        # (defeating the point of it being flagged stale in the first
        # place). Both must be excluded explicitly here.
        if self.config.cache_enabled and self.cache is not None and not report.is_degraded and not report.is_stale:
            await self.cache.set(ticker, report)

        return report

    async def _generate_fresh_report(self, signal: QuantSignal) -> ResearchReport:
        query_text = _build_retrieval_query(signal)
        # VectorStore.query() is a synchronous, blocking chromadb call --
        # offload it so it doesn't stall the event loop, same treatment
        # yfinance_poll.py gives the other synchronous library dependency
        # in this project.
        citations = await asyncio.to_thread(
            self.retriever.retrieve, signal.ticker, query_text, self.config.retrieval_top_k
        )

        if not citations:
            # Cold start (Requirement 4A): bypass the LLM entirely rather
            # than asking it to opine with zero grounding.
            logger.info("No filing or news context at all for %s -- bypassing the LLM", signal.ticker)
            return _insufficient_context_report(signal)

        try:
            findings = await self.llm_chain.generate(signal, citations)
        except Exception as exc:  # noqa: BLE001 -- fall back rather than losing this signal entirely
            return await self._fallback_report(signal, exc)

        return ResearchReport(
            ticker=signal.ticker,
            triggering_signal=signal,
            verdict=findings.verdict,
            confidence=findings.confidence,
            summary=findings.summary,
            key_findings=findings.key_findings,
            risk_factors=findings.risk_factors,
            citations=citations,
            model_used=self.llm_chain.model_used,
        )

    async def _fallback_report(self, signal: QuantSignal, exc: Exception) -> ResearchReport:
        """
        Requirement 4A's LLM-outage path: an EXPIRED (stale) cache entry
        beats no research at all, so it's used if one exists (flagged
        is_stale). Only if there's truly nothing cached does this publish
        a degraded, quant-only placeholder -- decision.py specifically
        recognizes is_degraded and dispatches a DEGRADED_QUANT_ALERT for
        it rather than silently suppressing a confidence=0.0 report.
        """
        ticker = signal.ticker
        if self.config.cache_enabled and self.cache is not None:
            stale_hit = await self.cache.get(ticker)
            if stale_hit is not None:
                logger.warning(
                    "LLM failed for %s (%s) -- falling back to a stale cached report", ticker, exc,
                )
                return stale_hit[0].model_copy(
                    update={"triggering_signal": signal, "is_stale": True, "from_cache": True}
                )

        logger.error(
            "LLM failed for %s (%s) and no cached report to fall back on -- "
            "publishing a degraded quant-only report", ticker, exc,
        )
        return ResearchReport(
            ticker=ticker,
            triggering_signal=signal,
            verdict=ResearchVerdict.NEUTRAL,
            confidence=0.0,
            summary=(
                f"Research unavailable: the LLM provider failed ({exc}) and no cached "
                f"report existed to fall back on. This alert carries quantitative "
                f"data only, with no qualitative research behind it."
            ),
            risk_factors=["No qualitative research available -- LLM provider failure, no cache fallback."],
            citations=[],
            model_used="none (degraded)",
            is_degraded=True,
        )

    async def _publish_report(self, report: ResearchReport) -> None:
        if self.store is not None:
            self.store.record_report(report.ticker, _categorize(report), datetime.now(timezone.utc))
        try:
            await self._client.publish(self.config.reports_channel, report.to_redis_payload())
            self._reports_published += 1
            logger.info(
                "Report: %s %s (confidence %.2f, %d citations) -- %s",
                report.ticker, report.verdict.value, report.confidence,
                len(report.citations), report.summary[:120],
            )
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the agent
            logger.warning("Failed to publish report to Redis: %s", exc)


def _categorize(report: ResearchReport) -> str:
    """Same decision table as dashboard.py's _categorize_report, just
    reading the ResearchReport object directly instead of a raw Redis
    payload dict -- kept as its own local copy (not imported from
    dashboard.py) since a root-level standalone script importing FROM a
    module would invert this project's dependency direction."""
    if report.from_cache:
        return "stale_fallback" if report.is_stale else "cache_hit"
    if report.is_degraded:
        return "degraded"
    if report.verdict == ResearchVerdict.INSUFFICIENT_CONTEXT:
        return "cold_start"
    return "llm_call"


def _build_retrieval_query(signal: QuantSignal) -> str:
    return (
        f"{signal.ticker} fundamentals, risk factors, and recent developments "
        f"relevant to a {signal.direction.value} "
        f"{signal.signal_type.value.replace('_', ' ')} technical setup: {signal.message}"
    )


def _insufficient_context_report(signal: QuantSignal) -> ResearchReport:
    """
    Cold start (Requirement 4A): ChromaDB returned zero chunks for this
    ticker. ResearchVerdict.INSUFFICIENT_CONTEXT already exists
    specifically for this case (see its own docstring in schemas.py) --
    used instead of a plain NEUTRAL verdict since it's more precise, and
    decision.py's matrix already treats both identically (neither is
    BULLISH/BEARISH, so no alert fires either way). Not flagged
    is_degraded -- this is a legitimate quiet non-alert, not a failure.
    """
    return ResearchReport(
        ticker=signal.ticker,
        triggering_signal=signal,
        verdict=ResearchVerdict.INSUFFICIENT_CONTEXT,
        confidence=0.0,
        summary=(
            f"No filing or news context was found for {signal.ticker} in ChromaDB -- "
            f"skipping the LLM call entirely rather than asking it to opine with zero grounding."
        ),
        risk_factors=["No retrieval context available -- this verdict has no fundamental/news backing."],
        citations=[],
        model_used="none (cold-start bypass)",
    )
