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

from talonx_core.alert_outbox import KIND_INTRADAY, KIND_LONG_TERM, AlertOutbox, make_outbox_id
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


async def _incr_metric(client, stage: str, counter: str, amount: int = 1) -> None:
    """Stage-Gate Metric Funnel (Phase 2 requirement doc): atomic,
    per-UTC-day Redis counters at `metrics:{YYYY-MM-DD}:{stage}:{counter}`,
    read by talonx_dispatch's Daily Funnel dashboard tab. Each module
    re-declares this same small helper locally rather than sharing one --
    same "no internal library between modules" convention this project
    uses everywhere else. Never raises -- a metrics-write failure must
    not affect correlation/decisioning."""
    if client is None or amount <= 0:
        return
    key = f"metrics:{datetime.now(timezone.utc):%Y-%m-%d}:{stage}:{counter}"
    try:
        new_value = await client.incrby(key, amount)
        if new_value == amount:
            await client.expire(key, 2764800)  # 32 days
    except Exception as exc:  # noqa: BLE001 -- telemetry must never break correlation/decisioning
        logger.debug("Metric increment failed for %s: %s", key, exc)


class DecisionEngine:
    def __init__(
        self,
        config: CoreConfig | None = None,
        correlator: TickerCorrelator | None = None,
        long_term_correlator: LongTermTickerCorrelator | None = None,
        store: TickerStateStore | None = None,
        alert_outbox: AlertOutbox | None = None,
    ):
        self.config = config or CoreConfig()
        self.correlator = correlator or TickerCorrelator()
        self.long_term_correlator = long_term_correlator or LongTermTickerCorrelator()
        self.store = store
        self._client = None
        # Task 87B FC_01: durable decision-bearing alert outbox. An explicit
        # instance wins; otherwise build one from config unless the path is
        # blank ("" -> best-effort publish only, the pre-FC_01 behaviour).
        if alert_outbox is not None:
            self.alert_outbox = alert_outbox
        elif self.config.alert_outbox_path:
            self.alert_outbox = AlertOutbox(
                self.config.alert_outbox_path,
                self._raw_publish,
                backoff_base_seconds=self.config.alert_outbox_backoff_base_seconds,
                backoff_max_seconds=self.config.alert_outbox_backoff_max_seconds,
            )
        else:
            self.alert_outbox = AlertOutbox(None, self._raw_publish)
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

        # Task 87B FC_01: a reconnect means Redis is back -- immediately
        # drain any alert the previous connection (or a previous process)
        # failed to publish, before resuming normal message handling.
        await self._flush_alert_outbox()

        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                # Cheap no-op when nothing is pending / nothing is due;
                # retries a stuck alert on the next 1s poll tick otherwise.
                await self._flush_alert_outbox()
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
                # 2026-08-18 /ping observability fix: "correlated" below
                # fires once per handled message regardless of payload type
                # (signal OR report), so it can't answer "which did Core
                # actually receive". This is that genuine, type-specific
                # counter -- incremented exactly here, at the real signal-
                # ingestion boundary, not derived/guessed from correlated.
                await _incr_metric(self._client, "core", "signals_received")
                ticker = signal.ticker
                if self.store is not None:
                    self.store.save_signal(ticker, signal, state.latest_signal_at)
            elif channel == self.config.reports_channel:
                report = ResearchReport.model_validate(payload)
                state = self.correlator.update_report(report)
                self._reports_processed += 1
                # Sibling to signals_received above -- the real report-
                # ingestion boundary, distinct from the combined "correlated"
                # counter.
                await _incr_metric(self._client, "core", "reports_received")
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
        await _incr_metric(self._client, "core", "correlated")
        if alert is not None:
            await self._publish_alert(alert)
            if alert.action == AlertAction.CONFIRMED_BULLISH:
                await _incr_metric(self._client, "core", "action_bullish")
            elif alert.action == AlertAction.CONFIRMED_BEARISH:
                await _incr_metric(self._client, "core", "action_bearish")
            elif alert.action == AlertAction.CONTRADICTED:
                await _incr_metric(self._client, "core", "action_contradicted")
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
                        state.last_streak_fiscal_year, state.previous_fair_value,
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
                        state.last_streak_fiscal_year, state.previous_fair_value,
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

    async def _raw_publish(self, channel: str, payload: str) -> bool:
        """The actual Redis fan-out, wrapped so a lost connection or a
        publish exception is a clean ``False`` (retry later) rather than a
        raise -- the AlertOutbox owns retry/backoff/idempotency on top."""
        if self._client is None:
            return False
        try:
            await self._client.publish(channel, payload)
            return True
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the engine
            logger.warning("Failed to publish to Redis channel %s: %s", channel, exc)
            return False

    async def _flush_alert_outbox(self) -> None:
        try:
            await self.alert_outbox.flush()
        except Exception as exc:  # noqa: BLE001 -- the outbox flusher must never break the message loop
            logger.warning("Alert outbox flush failed (will retry): %s", exc)

    async def _deliver_alert(
        self, *, kind: str, channel: str, alert, ticker: str, action: str, correlated_at,
    ) -> bool:
        """Task 87B FC_01: persist the fan-out obligation BEFORE attempting
        delivery, so a publish failure leaves a recoverable PENDING record
        (survives restart, retried with backoff by ``flush``) instead of a
        silently lost alert. Returns True iff Redis accepted it right now."""
        trading_date = correlated_at.astimezone(timezone.utc).date().isoformat()
        outbox_id = make_outbox_id(
            ticker=ticker, trading_date=trading_date, kind=kind, action=action,
            correlated_at=correlated_at.isoformat(),
        )
        alert.outbox_id = outbox_id
        payload = alert.to_redis_payload()
        self.alert_outbox.enqueue(
            outbox_id=outbox_id, channel=channel, payload=payload, kind=kind, ticker=ticker, action=action,
        )
        ok = await self._raw_publish(channel, payload)
        if ok:
            self.alert_outbox.mark_published(outbox_id)
        else:
            logger.warning(
                "Alert fan-out for %s %s deferred to durable outbox (pending_depth=%d) -- "
                "will retry after Redis recovery",
                ticker, action, self.alert_outbox.pending_depth(),
            )
        return ok

    async def _publish_alert(self, alert: ActionableAlert) -> None:
        ok = await self._deliver_alert(
            kind=KIND_INTRADAY, channel=self.config.alerts_channel, alert=alert,
            ticker=alert.ticker, action=alert.action.value, correlated_at=alert.correlated_at,
        )
        if ok:
            self._alerts_published += 1
            logger.info(
                "Alert: %s %s (%s, confidence %.2f) -- %s",
                alert.ticker, alert.action.value, alert.severity.value,
                alert.research_confidence, alert.rationale[:120],
            )

    async def _publish_long_term_alert(self, alert: LongTermActionableAlert) -> None:
        ok = await self._deliver_alert(
            kind=KIND_LONG_TERM, channel=self.config.alerts_channel_long_term, alert=alert,
            ticker=alert.ticker, action=alert.action.value, correlated_at=alert.correlated_at,
        )
        if ok:
            self._long_term_alerts_published += 1
            logger.info(
                "Long-term alert: %s %s (%s, quality %d/10, MoS %.1f%%) -- %s",
                alert.ticker, alert.action.value, alert.severity.value,
                alert.quality_score, alert.margin_of_safety_pct * 100, alert.rationale[:120],
            )
