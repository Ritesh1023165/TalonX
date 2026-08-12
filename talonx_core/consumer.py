"""
talonx_core.consumer
-------------------------
Async Redis Pub/Sub consumer: subscribes to BOTH talonx:signals:quant and
talonx:reports:brain on one connection, updates the per-ticker correlator
on every message, re-runs the decision matrix for that ticker, and
publishes any resulting ActionableAlert to talonx:alerts:dispatch.

Phase 2: ALSO subscribes to talonx:signals:fundamental and
talonx:reports:longterm on the SAME connection, running the exact same
update-correlator -> evaluate -> publish/persist shape through a
SEPARATE long_term_correlator/evaluate_long_term_verbose/
alerts_channel_long_term path -- a DUAL_HORIZON ticker's intraday and
long-term state never share an object, only a Redis connection and this
class's event loop.

Reconnects with backoff on Redis connection loss, same pattern as
talonx_quant.consumer.QuantScanner and talonx_brain.consumer.ResearchAgent
-- the jitter helper is reimplemented locally rather than imported, since
this module is deliberately self-contained at the code level (see
config.py), same reasoning talonx_quant uses for its own copy.

A failure processing ONE message (bad JSON, invalid payload, publish
error) is logged and skipped rather than tearing down the whole listener
-- one bad message on either channel shouldn't stop correlation for
everything else.

If a TickerStateStore is provided (see store.py), the correlator is
rehydrated from it at startup, and every state change is written through
to it -- so a restart mid-correlation doesn't silently lose whichever
half of a signal/report pair had already arrived. `store` is None by
default (pure in-memory, same as before persistence existed); real
construction/wiring happens in run.py, not here, so this class stays
trivially testable without touching disk unless a test explicitly injects
a store.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timezone

from pydantic import ValidationError

from talonx_ingest.common.structured_logging import log_structured

from talonx_core.config import CoreConfig
from talonx_core.decision import evaluate_long_term_verbose, evaluate_verbose
from talonx_core.schemas import (
    ActionableAlert,
    AlertAction,
    FundamentalFactorSignal,
    LongTermActionableAlert,
    LongTermResearchReport,
    QuantSignal,
    ResearchReport,
)
from talonx_core.state import LongTermTickerCorrelator, TickerCorrelator
from talonx_core.store import TickerStateStore

logger = logging.getLogger("talonx_core.consumer")

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None


def _jittered_backoff(attempt: int, base: float, max_delay: float) -> float:
    raw = base * (2 ** (attempt - 1))
    capped = min(raw, max_delay)
    return capped * (0.5 + random.random())


class DecisionEngine:
    def __init__(
        self,
        config: CoreConfig | None = None,
        correlator: TickerCorrelator | None = None,
        long_term_correlator: LongTermTickerCorrelator | None = None,
        store: TickerStateStore | None = None,
    ):
        self.config = config or CoreConfig()
        self.correlator = correlator or TickerCorrelator()
        self.long_term_correlator = long_term_correlator or LongTermTickerCorrelator()
        self.store = store
        self._client = None
        self._stop_event = asyncio.Event()
        self._signals_processed = 0
        self._reports_processed = 0
        self._alerts_published = 0
        self._fundamentals_processed = 0
        self._long_term_reports_processed = 0
        self._long_term_alerts_published = 0

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def alerts_published(self) -> int:
        return self._alerts_published

    @property
    def signals_processed(self) -> int:
        return self._signals_processed

    @property
    def reports_processed(self) -> int:
        return self._reports_processed

    @property
    def fundamentals_processed(self) -> int:
        return self._fundamentals_processed

    @property
    def long_term_reports_processed(self) -> int:
        return self._long_term_reports_processed

    @property
    def long_term_alerts_published(self) -> int:
        return self._long_term_alerts_published

    async def run(self) -> None:
        if redis_asyncio is None:
            raise ImportError(
                "The 'redis' package is required. Install it with: pip install redis"
            )

        if self.store is not None:
            self.store.load_into(self.correlator)
            self.store.load_into_long_term(self.long_term_correlator)

        attempt = 0
        while not self._stop_event.is_set():
            try:
                await self._connect_and_listen()
                return  # clean stop() was called
            except Exception as exc:  # noqa: BLE001 -- any connection/listen failure retries
                attempt += 1
                wait = _jittered_backoff(
                    attempt, self.config.reconnect_backoff_base_seconds,
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
        channels = (
            self.config.signals_channel, self.config.reports_channel,
            self.config.fundamental_signals_channel, self.config.reports_channel_long_term,
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

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Dropping unparseable message on %s: %s", channel, exc)
            return

        if channel in (self.config.fundamental_signals_channel, self.config.reports_channel_long_term):
            await self._handle_long_term_message(channel, payload)
            return

        try:
            if channel == self.config.signals_channel:
                signal = QuantSignal.model_validate(payload)
                state = self.correlator.update_signal(signal)
                self._signals_processed += 1
                ticker = signal.ticker
                if self.store is not None:
                    self.store.save_signal(ticker, signal, state.latest_signal_at)
            elif channel == self.config.reports_channel:
                report = ResearchReport.model_validate(payload)
                state = self.correlator.update_report(report)
                self._reports_processed += 1
                ticker = report.ticker
                if self.store is not None:
                    self.store.save_report(ticker, report, state.latest_report_at)
            else:
                logger.warning("Dropping message on unexpected channel %s", channel)
                return
        except ValidationError as exc:
            logger.warning("Dropping invalid payload on %s: %s", channel, exc)
            return

        state = self.correlator.get_or_create(ticker)
        alert, reason = evaluate_verbose(state, self.config)
        if alert is not None:
            await self._publish_alert(alert)
            self.correlator.mark_alerted(
                ticker, action=alert.action, price=alert.triggering_signal.price, when=alert.correlated_at,
            )
            if self.store is not None:
                self.store.save_alert(
                    ticker, alert.correlated_at, alert.action, alert.triggering_signal.price,
                )
        elif self.store is not None:
            # Durable trace for the EOD report's signal-funnel section --
            # previously evaluate() returning None left zero trace
            # anywhere, ephemeral or durable (see decision.py).
            self.store.record_suppressed(ticker, reason, datetime.now(timezone.utc))

    async def _handle_long_term_message(self, channel: str, payload: dict) -> None:
        """Phase 2's sibling to the intraday branch above -- same
        update-correlator -> evaluate -> publish/persist shape, entirely
        separate correlator/store methods/channel."""
        try:
            if channel == self.config.fundamental_signals_channel:
                signal = FundamentalFactorSignal.model_validate(payload)
                state = self.long_term_correlator.update_signal(signal, self.config.assumed_wacc)
                self._fundamentals_processed += 1
                ticker = signal.ticker
                if self.store is not None:
                    self.store.save_fundamental_signal(ticker, signal, state.fundamental_signal_at)
                    self.store.save_long_term_fundamental_stop_state(
                        ticker, state.roic_below_wacc_streak, state.previous_moat_rating,
                    )
            elif channel == self.config.reports_channel_long_term:
                report = LongTermResearchReport.model_validate(payload)
                state = self.long_term_correlator.update_report(report)
                self._long_term_reports_processed += 1
                ticker = report.ticker
                if self.store is not None:
                    self.store.save_long_term_report(ticker, report, state.longterm_report_at)
                    self.store.save_long_term_fundamental_stop_state(
                        ticker, state.roic_below_wacc_streak, state.previous_moat_rating,
                    )
            else:
                logger.warning("Dropping message on unexpected channel %s", channel)
                return
        except ValidationError as exc:
            logger.warning("Dropping invalid payload on %s: %s", channel, exc)
            return

        state = self.long_term_correlator.get_or_create(ticker)
        alert, reason = evaluate_long_term_verbose(state, self.config)
        if alert is not None:
            await self._publish_long_term_alert(alert)
            self.long_term_correlator.mark_alerted(
                ticker, action=alert.action, price=alert.market_price, when=alert.correlated_at,
            )
            if self.store is not None:
                self.store.save_long_term_alert(ticker, alert.correlated_at, alert.action, alert.market_price)
            if alert.action == AlertAction.UNDER_PERFORM_REBALANCE:
                log_structured(
                    logger, "FUNDAMENTAL_STOP_TRIGGERED", ticker=ticker,
                    roic_below_wacc_streak=state.roic_below_wacc_streak,
                    previous_moat_rating=state.previous_moat_rating, rationale=alert.rationale,
                )
        elif self.store is not None:
            self.store.record_suppressed(ticker, reason, datetime.now(timezone.utc), horizon="long_term")

    async def _publish_alert(self, alert: ActionableAlert) -> None:
        try:
            await self._client.publish(self.config.alerts_channel, alert.to_redis_payload())
            self._alerts_published += 1
            logger.info(
                "Alert: %s %s (%s, confidence %.2f) -- %s",
                alert.ticker, alert.action.value, alert.severity.value,
                alert.research_confidence, alert.rationale[:120],
            )
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the engine
            logger.warning("Failed to publish alert to Redis: %s", exc)

    async def _publish_long_term_alert(self, alert: LongTermActionableAlert) -> None:
        try:
            await self._client.publish(self.config.alerts_channel_long_term, alert.to_redis_payload())
            self._long_term_alerts_published += 1
            logger.info(
                "Long-term alert: %s %s (%s, quality %d/10, MoS %.1f%%) -- %s",
                alert.ticker, alert.action.value, alert.severity.value,
                alert.quality_score, alert.margin_of_safety_pct * 100, alert.rationale[:120],
            )
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the engine
            logger.warning("Failed to publish long-term alert to Redis: %s", exc)
