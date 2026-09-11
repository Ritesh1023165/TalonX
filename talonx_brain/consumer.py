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

Phase 2: ALSO subscribes to talonx:fundamentals:events
(talonx_quant.fundamental_consumer.FundamentalScanner's trigger,
NewFundamentalsIngestedEvent) and researches a LONG_TERM moat/DCF report
via the same cache-first skeleton, publishing LongTermResearchReport to
talonx:reports:longterm -- a sibling pipeline sharing this class (same
dual-subscribe-single-class pattern signals_channel/filings_channel
already used), not a second process, since both halves need the same
Redis connection and ContextRetriever/cache infrastructure. A
NewFilingIngestedEvent invalidates BOTH the intraday AND long_term
caches (fresh filing text matters to both prompt types); a
NewFundamentalsIngestedEvent invalidates ONLY the long_term cache
(new numbers don't affect the intraday technical-signal-driven cache).

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
from talonx_ingest.common.structured_logging import log_structured
from talonx_ingest.events.schemas import NewFilingIngestedEvent, NewFundamentalsIngestedEvent

from talonx_brain.cache import BrainCache
from talonx_brain.config import BrainConfig
from talonx_brain.llm import _BaseResearchChain, build_long_term_research_chain, build_research_chain
from talonx_brain.retriever import ContextRetriever
from talonx_brain.schemas import (
    FundamentalFactorSignal,
    LongTermResearchReport,
    MoatRating,
    QuantSignal,
    ResearchReport,
    ResearchVerdict,
)
from talonx_brain.store import BrainStatsStore

logger = logging.getLogger("talonx_brain.consumer")

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None


async def _incr_metric(client, stage: str, counter: str, amount: int = 1) -> None:
    """Stage-Gate Metric Funnel (Phase 2 requirement doc): atomic,
    per-UTC-day Redis counters at `metrics:{YYYY-MM-DD}:{stage}:{counter}`,
    read by talonx_dispatch's Daily Funnel dashboard tab. Each module
    re-declares this same small helper locally rather than sharing one --
    same "no internal library between modules" convention this project
    uses everywhere else. Never raises -- a metrics-write failure must
    not affect research generation."""
    if client is None or amount <= 0:
        return
    key = f"metrics:{datetime.now(timezone.utc):%Y-%m-%d}:{stage}:{counter}"
    try:
        new_value = await client.incrby(key, amount)
        if new_value == amount:
            await client.expire(key, 2764800)  # 32 days
    except Exception as exc:  # noqa: BLE001 -- telemetry must never break research generation
        logger.debug("Metric increment failed for %s: %s", key, exc)


class ResearchAgent:
    def __init__(
        self,
        config: BrainConfig | None = None,
        retriever: ContextRetriever | None = None,
        llm_chain: _BaseResearchChain | None = None,
        long_term_llm_chain: _BaseResearchChain | None = None,
        cache: BrainCache | None = None,
        store: BrainStatsStore | None = None,
    ):
        self.config = config or BrainConfig()
        self.retriever = retriever or ContextRetriever(self.config)
        self.llm_chain = llm_chain or build_research_chain(self.config)
        self.long_term_llm_chain = long_term_llm_chain or build_long_term_research_chain(self.config)
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
        self._long_term_reports_published = 0
        self._fundamentals_processed = 0

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def reports_published(self) -> int:
        return self._reports_published

    @property
    def signals_processed(self) -> int:
        return self._signals_processed

    @property
    def long_term_reports_published(self) -> int:
        return self._long_term_reports_published

    @property
    def fundamentals_processed(self) -> int:
        return self._fundamentals_processed

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
        channels = (
            self.config.signals_channel, self.config.filings_channel,
            self.config.fundamental_signals_channel, self.config.fundamentals_events_channel,
        )
        await pubsub.subscribe(*channels)
        logger.info("Subscribed to %s", ", ".join(channels))

        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue  # normal: no message within this poll window
                await self._handle_message(message)
        finally:
            await pubsub.unsubscribe(*channels)
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
        if channel == self.config.fundamentals_events_channel:
            await self._handle_fundamentals_ingested_event(raw)
            return
        if channel == self.config.fundamental_signals_channel:
            await self._handle_fundamental_signal(raw)
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
        await _incr_metric(self._client, "brain", "received")
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
            "New filing for %s (%s, accession %s) -- invalidating cached research (both horizons)",
            event.ticker, event.form_type, event.accession_number,
        )
        # Fresh filing TEXT matters to both prompt types -- the intraday
        # cache (news/filing-grounded technical read) AND the long_term
        # cache (moat/DCF, derived from the SAME filing text).
        await self.cache.invalidate(event.ticker, horizon="intraday")
        await self.cache.invalidate(event.ticker, horizon="long_term")
        self._filing_invalidations += 1

    async def _handle_fundamentals_ingested_event(self, raw: str) -> None:
        """Fresh structured financials landed (talonx_ingest ->
        talonx:fundamentals:events) -- invalidate the long_term cache
        ONLY (new numbers don't affect the intraday technical-signal
        cache). Deliberately separate from _handle_fundamental_signal:
        this fires on every fresh ingest regardless of whether
        FundamentalScanner's thresholds were cleared, so a ticker whose
        numbers changed but didn't produce a new FundamentalFactorSignal
        still doesn't serve a now-outdated cached moat/DCF report."""
        try:
            payload = json.loads(raw)
            event = NewFundamentalsIngestedEvent.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Dropping unparseable message on fundamentals events channel: %s", exc)
            return

        logger.info(
            "Fresh financials for %s -- invalidating long_term cached research", event.ticker,
        )
        await self.cache.invalidate(event.ticker, horizon="long_term")

    async def _handle_fundamental_signal(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
            signal = FundamentalFactorSignal.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Dropping unparseable message on fundamental signals channel: %s", exc)
            return

        self._fundamentals_processed += 1
        await _incr_metric(self._client, "brain", "received")
        logger.info(
            "Researching long-term thesis for %s (FY%d): %s",
            signal.ticker, signal.fiscal_year, signal.message,
        )

        try:
            report = await self._generate_long_term_report(signal)
        except Exception as exc:  # noqa: BLE001 -- one bad signal shouldn't kill the listener
            logger.error("Failed to generate long-term research report for %s: %s", signal.ticker, exc)
            return

        await self._publish_long_term_report(report)

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
                await _incr_metric(self._client, "brain", "cache_hits")
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
        # called directly (not offloaded via asyncio.to_thread) since
        # self.retriever wraps a get_vector_store()-cached VectorStore
        # shared with talonx_ingest.pipeline.ingest_ticker's upsert_chunks(),
        # which also runs synchronously on this SAME event-loop thread.
        # Offloading only this side to a real OS thread (tried 2026-08-13)
        # let the two calls genuinely run concurrently against one shared
        # embedding model -- crashed python.exe twice (ACCESS_VIOLATION in
        # c10.dll, PyTorch's core). A lock around the shared calls fixed
        # the crash but froze the whole process instead (see
        # VectorStore.__init__'s docstring). Keeping this on the main
        # thread, same as upsert_chunks(), means the two can never overlap
        # in the first place -- the cost is this call blocking the event
        # loop for its duration, same accepted tradeoff as
        # periodic_wal_checkpoint_loop's AuditStore call in run_talonx.py.
        citations = self.retriever.retrieve(signal.ticker, query_text, self.config.retrieval_top_k)

        if not citations:
            # Cold start (Requirement 4A): bypass the LLM entirely rather
            # than asking it to opine with zero grounding.
            logger.info("No filing or news context at all for %s -- bypassing the LLM", signal.ticker)
            return _insufficient_context_report(signal)

        await _incr_metric(self._client, "brain", "llm_calls")
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
            # 2026-08-18 /ping observability fix: a genuine "report produced"
            # counter, deliberately NOT tied to llm_calls -- this fires
            # uniformly for every report that reaches this point regardless
            # of whether _generate_report returned an LLM-generated, cached,
            # stale-fallback, degraded, or cold-start-bypass report (all of
            # them flow through here), unlike llm_calls, which only
            # increments on an actual LLM invocation and would silently
            # undercount fallback/cached/cold-start reports if used as a
            # "reports generated" proxy.
            await _incr_metric(self._client, "brain", "reports_generated")
            logger.info(
                "Report: %s %s (confidence %.2f, %d citations) -- %s",
                report.ticker, report.verdict.value, report.confidence,
                len(report.citations), report.summary[:120],
            )
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the agent
            logger.warning("Failed to publish report to Redis: %s", exc)

    # ------------------------------------------------------------------
    # Phase 2 LONG_TERM path -- same cache-first/lock/fallback shape as
    # the intraday trio above, sibling functions rather than a shared
    # generic one: the two report types don't share enough fields
    # (verdict/confidence vs. moat_rating/quality_score/fair_value) to
    # meaningfully parameterize a single implementation without it
    # becoming harder to read than just writing it twice.
    # ------------------------------------------------------------------

    async def _generate_long_term_report(self, signal: FundamentalFactorSignal) -> LongTermResearchReport:
        ticker = signal.ticker

        # Event-Driven Earnings Radar: an earnings-triggered signal always
        # forces a fresh generation, even if a recent cache entry exists
        # -- the whole point is a same-day re-read of the NEW filing, so
        # serving a pre-earnings cached report would silently defeat it.
        if self.config.cache_enabled and self.cache is not None and not signal.is_earnings_related:
            hit = await self.cache.get(ticker, horizon="long_term")
            if hit is not None and hit[1]:  # fresh
                logger.info("Long-term cache hit for %s -- skipping retrieval and the LLM call", ticker)
                await _incr_metric(self._client, "brain", "cache_hits")
                return hit[0].model_copy(update={"triggering_signal": signal, "from_cache": True})

        acquired = False
        if self.config.cache_enabled and self.cache is not None:
            acquired = await self.cache.acquire_lock(ticker, horizon="long_term")
            if not acquired:
                waited = await self.cache.wait_for_cache(ticker, horizon="long_term")
                if waited is not None:
                    logger.info(
                        "Another worker populated the long-term cache for %s while waiting -- using it", ticker,
                    )
                    return waited[0].model_copy(update={"triggering_signal": signal, "from_cache": True})

        try:
            report = await self._generate_fresh_long_term_report(signal)
        finally:
            if acquired:
                await self.cache.release_lock(ticker, horizon="long_term")

        if self.config.cache_enabled and self.cache is not None and not report.is_degraded and not report.is_stale:
            await self.cache.set(ticker, report, horizon="long_term")

        return report

    async def _generate_fresh_long_term_report(self, signal: FundamentalFactorSignal) -> LongTermResearchReport:
        query_text = _build_long_term_retrieval_query(signal)
        # Event-Driven Earnings Radar: an earnings-triggered signal needs
        # the freshly-ingested 8-K/10-Q chunks visible to retrieval, not
        # just the routine 10-K-only filter -- without this, an earnings-
        # triggered regeneration would silently ground itself in stale
        # annual-report text, with the actual earnings filing invisible.
        form_type = ["10-K", "10-Q", "8-K"] if signal.is_earnings_related else "10-K"
        # Not offloaded via asyncio.to_thread -- see _generate_fresh_report's
        # docstring above for why (shared embedding model with
        # talonx_ingest.pipeline.ingest_ticker, same fix applies here).
        citations = self.retriever.retrieve(
            signal.ticker, query_text, self.config.retrieval_top_k, form_type,
        )

        if not citations:
            logger.info("No filing context at all for %s -- bypassing the LLM", signal.ticker)
            return _insufficient_context_long_term_report(signal)

        await _incr_metric(self._client, "brain", "llm_calls")
        try:
            findings = await self.long_term_llm_chain.generate(signal, citations)
        except Exception as exc:  # noqa: BLE001 -- fall back rather than losing this signal entirely
            return await self._fallback_long_term_report(signal, exc)

        log_structured(
            logger, "MOAT_EVALUATED", ticker=signal.ticker,
            moat_rating=findings.moat_rating.value, quality_score=findings.quality_score,
            capital_allocation_assessment=findings.capital_allocation_assessment,
        )
        log_structured(
            logger, "VALUATION_DERIVED", ticker=signal.ticker,
            dcf_fair_value_per_share=findings.dcf_fair_value_per_share, price=signal.price,
        )

        return LongTermResearchReport(
            ticker=signal.ticker,
            triggering_signal=signal,
            moat_rating=findings.moat_rating,
            capital_allocation_assessment=findings.capital_allocation_assessment,
            dcf_fair_value_per_share=findings.dcf_fair_value_per_share,
            quality_score=findings.quality_score,
            summary=findings.summary,
            key_findings=findings.key_findings,
            risk_factors=findings.risk_factors,
            citations=citations,
            model_used=self.long_term_llm_chain.model_used,
            guidance_revision_notes=findings.guidance_revision_notes,
            revenue_eps_surprise=findings.revenue_eps_surprise,
            is_earnings_related=signal.is_earnings_related,
        )

    async def _fallback_long_term_report(
        self, signal: FundamentalFactorSignal, exc: Exception,
    ) -> LongTermResearchReport:
        ticker = signal.ticker
        if self.config.cache_enabled and self.cache is not None:
            stale_hit = await self.cache.get(ticker, horizon="long_term")
            if stale_hit is not None:
                logger.warning(
                    "LLM failed for long-term %s (%s) -- falling back to a stale cached report", ticker, exc,
                )
                return stale_hit[0].model_copy(
                    update={"triggering_signal": signal, "is_stale": True, "from_cache": True}
                )

        logger.error(
            "LLM failed for long-term %s (%s) and no cached report to fall back on -- "
            "publishing a degraded quant-only report", ticker, exc,
        )
        return LongTermResearchReport(
            ticker=ticker,
            triggering_signal=signal,
            moat_rating=MoatRating.NONE,
            capital_allocation_assessment="Unavailable -- LLM provider failure, no cache fallback.",
            dcf_fair_value_per_share=0.0,
            quality_score=0,
            summary=(
                f"Research unavailable: the LLM provider failed ({exc}) and no cached "
                f"long-term report existed to fall back on. This signal carries fundamental "
                f"factor data only, with no qualitative moat/DCF research behind it."
            ),
            risk_factors=["No qualitative research available -- LLM provider failure, no cache fallback."],
            citations=[],
            model_used="none (degraded)",
            is_degraded=True,
        )

    async def _publish_long_term_report(self, report: LongTermResearchReport) -> None:
        if self.store is not None:
            self.store.record_report(
                report.ticker, _categorize_long_term(report), datetime.now(timezone.utc), horizon="long_term",
            )
        try:
            await self._client.publish(self.config.reports_channel_long_term, report.to_redis_payload())
            self._long_term_reports_published += 1
            # Same genuine "report produced" counter the intraday path
            # increments in _publish_report -- shared Redis key (both
            # horizons count as one "reports_generated" total, matching how
            # "received" already combines intraday QuantSignal and
            # FundamentalFactorSignal counts).
            await _incr_metric(self._client, "brain", "reports_generated")
            logger.info(
                "Long-term report: %s moat=%s quality=%d/10 fair_value=%.2f -- %s",
                report.ticker, report.moat_rating.value, report.quality_score,
                report.dcf_fair_value_per_share, report.summary[:120],
            )
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the agent
            logger.warning("Failed to publish long-term report to Redis: %s", exc)


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


def _categorize_long_term(report: LongTermResearchReport) -> str:
    """Same category taxonomy _categorize() uses for the intraday
    ResearchReport. LongTermResearchReport has no `verdict` enum to
    check INSUFFICIENT_CONTEXT against (unlike ResearchReport), so
    cold-start is instead detected via the same sentinel model_used
    string _insufficient_context_long_term_report sets -- both cold-start
    paths bypass the LLM entirely and need to show up as "cold_start" in
    the EOD report's economics section, not get miscounted as a real
    "llm_call"."""
    if report.from_cache:
        return "stale_fallback" if report.is_stale else "cache_hit"
    if report.is_degraded:
        return "degraded"
    if report.model_used == "none (cold-start bypass)":
        return "cold_start"
    return "llm_call"


def _build_retrieval_query(signal: QuantSignal) -> str:
    return (
        f"{signal.ticker} fundamentals, risk factors, and recent developments "
        f"relevant to a {signal.direction.value} "
        f"{signal.signal_type.value.replace('_', ' ')} technical setup: {signal.message}"
    )


def _build_long_term_retrieval_query(signal: FundamentalFactorSignal) -> str:
    return (
        f"{signal.ticker} economic moat, competitive advantage, capital allocation, "
        f"management strategy, and long-term risk factors relevant to a durable "
        f"multi-year investment thesis. Fundamental context: {signal.message}"
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


def _insufficient_context_long_term_report(signal: FundamentalFactorSignal) -> LongTermResearchReport:
    """Cold start for the LONG_TERM path: ChromaDB returned zero 10-K
    chunks for this ticker. No ResearchVerdict-style enum value exists
    on LongTermResearchReport to flag this precisely (see schemas.py --
    it doesn't carry a verdict at all), so moat_rating/quality_score get
    conservative placeholder values (NONE/0) and the same
    "none (cold-start bypass)" model_used sentinel the intraday cold-
    start path uses -- _categorize_long_term() keys off exactly that
    string to bucket this as "cold_start", not "llm_call", in the EOD
    report's economics section. Not flagged is_degraded -- this is a
    legitimate quiet non-alert (no 10-K text exists yet for this ticker),
    not a failure."""
    return LongTermResearchReport(
        ticker=signal.ticker,
        triggering_signal=signal,
        moat_rating=MoatRating.NONE,
        capital_allocation_assessment="Unavailable -- no 10-K context retrieved.",
        dcf_fair_value_per_share=0.0,
        quality_score=0,
        summary=(
            f"No 10-K filing context was found for {signal.ticker} in ChromaDB -- "
            f"skipping the LLM call entirely rather than asking it to opine with zero grounding."
        ),
        risk_factors=["No retrieval context available -- this assessment has no filing backing."],
        citations=[],
        model_used="none (cold-start bypass)",
    )
