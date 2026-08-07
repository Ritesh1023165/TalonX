"""
talonx_brain.consumer
--------------------------
Async Redis Pub/Sub consumer: subscribes to talonx:signals:quant, and for
each QuantSignal retrieves relevant filing and news context from ChromaDB,
runs it through the configured LLM's structured RAG chain (Gemini or a
local Ollama model -- see llm.build_research_chain / config.llm_provider),
and publishes the resulting ResearchReport to talonx:reports:brain.

Reconnects with backoff on Redis connection loss, same pattern as
talonx_quant.consumer.QuantScanner (reusing talonx_ingest.common.backoff
here rather than re-implementing jitter a third time, since this module
already has a real import dependency on talonx_ingest -- see config.py).

A failure generating ONE report (retrieval error, LLM error, etc.) is
logged and skipped rather than tearing down the whole listener -- one bad
signal shouldn't stop research on the next one.
"""
from __future__ import annotations

import asyncio
import json
import logging

from pydantic import ValidationError

from talonx_ingest.common.backoff import jittered_backoff_seconds

from talonx_brain.config import BrainConfig
from talonx_brain.llm import _BaseResearchChain, build_research_chain
from talonx_brain.retriever import ContextRetriever
from talonx_brain.schemas import QuantSignal, ResearchReport

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
    ):
        self.config = config or BrainConfig()
        self.retriever = retriever or ContextRetriever(self.config)
        self.llm_chain = llm_chain or build_research_chain(self.config)
        self._client = None
        self._stop_event = asyncio.Event()
        self._reports_published = 0
        self._signals_processed = 0

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

        pubsub = self._client.pubsub()
        await pubsub.subscribe(self.config.signals_channel)
        logger.info("Subscribed to %s", self.config.signals_channel)

        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue  # normal: no message within this poll window
                await self._handle_message(message)
        finally:
            await pubsub.unsubscribe(self.config.signals_channel)
            await pubsub.aclose()
            await self._client.aclose()

    async def _handle_message(self, message: dict) -> None:
        raw = message.get("data")
        if raw is None:
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

    async def _generate_report(self, signal: QuantSignal) -> ResearchReport:
        query_text = _build_retrieval_query(signal)
        # VectorStore.query() is a synchronous, blocking chromadb call --
        # offload it so it doesn't stall the event loop, same treatment
        # yfinance_poll.py gives the other synchronous library dependency
        # in this project.
        citations = await asyncio.to_thread(
            self.retriever.retrieve, signal.ticker, query_text, self.config.retrieval_top_k
        )
        findings = await self.llm_chain.generate(signal, citations)

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

    async def _publish_report(self, report: ResearchReport) -> None:
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


def _build_retrieval_query(signal: QuantSignal) -> str:
    return (
        f"{signal.ticker} fundamentals, risk factors, and recent developments "
        f"relevant to a {signal.direction.value} "
        f"{signal.signal_type.value.replace('_', ' ')} technical setup: {signal.message}"
    )
