"""
talonx_dispatch.consumer
-----------------------------
Async Redis Pub/Sub consumer: subscribes to talonx:alerts:dispatch, and
for each ActionableAlert, records it to the durable audit trail
(store.py) and -- if Telegram is configured and the alert's severity
clears TALONX_DISPATCH_MIN_SEVERITY -- formats and sends a SHORT push
notification (formatter.format_telegram_summary) with just enough to
read at a glance plus the alert's ID; the full writeup is available on
demand by replying to that push with the ID (telegram_listener.py).

Also subscribes to talonx:paper:trades (published by talonx_paper,
Module 6) -- a PaperTradeExecution gets its OWN short push
(formatter.format_telegram_trade_execution), deliberately SEPARATE from
and not appended to the triggering alert's push, so a trade execution
doesn't reinstate a long combined message. Not stored here either --
talonx_paper's own trade_history is already the durable record; this
module's job stays "notify," not "store twice."

Phase 2: ALSO subscribes to talonx:alerts:longterm and
talonx:paper:trades:longterm, running the exact same
record-then-maybe-notify shape through SEPARATE store methods/formatter
functions/audit table (long_term_alerts) -- see store.py's own docstring
for why long-term alerts get their own table rather than a horizon
column on the intraday one.

DispatchAgent.run() is three concurrent tasks, not one: the Redis alert
listener below, TelegramReplyListener's incoming-message poll (only
started if Telegram is configured -- no token, nothing to poll), and a
periodic audit-trail retention sweep (purges rows older than
TALONX_DISPATCH_RETENTION_DAYS so a long-running install doesn't grow
the audit db forever). All three share self._stop_event.

Reconnects with backoff on Redis connection loss, same pattern as every
other consumer in this project (jitter helper reimplemented locally
rather than imported, since this module is deliberately self-contained
at the code level -- see config.py).

The audit write happens FIRST, unconditionally, before any Telegram
attempt -- a failure sending ONE Telegram message is logged (and
recorded on that alert's own audit row) rather than crashing the
listener or losing the alert. The audit trail is the source of truth;
Telegram is a best-effort notification layer on top, same "durable write
first, best-effort broadcast second" split talonx_ingest.events.publisher
established for MarketTickEvent/NewFilingIngestedEvent.

Reads talonx_watchlist's store for a ticker's company name to show in
both push types (e.g. "AAPL (Apple Inc.)") -- a shared control-plane
lookup, not a pipeline data contract, same reasoning talonx_paper/
config.py and app.py already depend on talonx_watchlist directly for.
A ticker not (yet) on the watchlist just shows without a company name
suffix rather than failing the push.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.formatter import (
    format_telegram_long_term_alert,
    format_telegram_long_term_trade_execution,
    format_telegram_summary,
    format_telegram_trade_execution,
)
from talonx_dispatch.schemas import (
    ActionableAlert,
    AlertSeverity,
    LongTermActionableAlert,
    LongTermTradeExecution,
    PaperTradeExecution,
)
from talonx_dispatch.store import AuditStore
from talonx_dispatch.telegram_client import TelegramClient, TelegramSendError
from talonx_dispatch.telegram_listener import TelegramReplyListener
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

logger = logging.getLogger("talonx_dispatch.consumer")

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None


def _jittered_backoff(attempt: int, base: float, max_delay: float) -> float:
    raw = base * (2 ** (attempt - 1))
    capped = min(raw, max_delay)
    return capped * (0.5 + random.random())


class DispatchAgent:
    def __init__(
        self,
        config: DispatchConfig | None = None,
        store: AuditStore | None = None,
        telegram_client: TelegramClient | None = None,
        watchlist_store: TickerWatchlistStore | None = None,
    ):
        self.config = config or DispatchConfig()
        self.store = store or AuditStore(self.config.audit_db_path)
        self.telegram_client = telegram_client or TelegramClient(self.config)
        self.watchlist_store = watchlist_store or TickerWatchlistStore(WatchlistConfig().db_path)
        self.reply_listener = TelegramReplyListener(self.store, self.config, self.telegram_client)
        self._client = None
        self._stop_event = asyncio.Event()
        self._alerts_processed = 0
        self._telegram_sent = 0
        self._telegram_failed = 0
        self._alerts_purged = 0
        self._long_term_alerts_processed = 0
        self._long_term_telegram_sent = 0
        self._long_term_telegram_failed = 0
        self._long_term_alerts_purged = 0

        try:
            self._min_severity = AlertSeverity(self.config.telegram_min_severity.lower())
        except ValueError:
            logger.warning(
                "Invalid TALONX_DISPATCH_MIN_SEVERITY=%r, defaulting to 'warning'",
                self.config.telegram_min_severity,
            )
            self._min_severity = AlertSeverity.WARNING

        if not self.telegram_client.is_configured:
            logger.warning(
                "Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset) -- "
                "alerts will still be recorded to the audit trail, but no mobile push "
                "notifications will be sent."
            )

    def stop(self) -> None:
        self._stop_event.set()
        self.reply_listener.stop()

    @property
    def alerts_processed(self) -> int:
        return self._alerts_processed

    @property
    def telegram_sent(self) -> int:
        return self._telegram_sent

    @property
    def telegram_failed(self) -> int:
        return self._telegram_failed

    @property
    def alerts_purged(self) -> int:
        return self._alerts_purged

    @property
    def long_term_alerts_processed(self) -> int:
        return self._long_term_alerts_processed

    @property
    def long_term_telegram_sent(self) -> int:
        return self._long_term_telegram_sent

    @property
    def long_term_telegram_failed(self) -> int:
        return self._long_term_telegram_failed

    @property
    def long_term_alerts_purged(self) -> int:
        return self._long_term_alerts_purged

    async def run(self) -> None:
        if redis_asyncio is None:
            raise ImportError(
                "The 'redis' package is required. Install it with: pip install redis"
            )

        tasks = [
            asyncio.create_task(self._run_redis_listener(), name="dispatch_redis_listener"),
            asyncio.create_task(self._retention_sweep_loop(), name="dispatch_retention_sweep"),
        ]
        if self.telegram_client.is_configured:
            tasks.append(asyncio.create_task(self.reply_listener.run(), name="telegram_reply_listener"))
        await asyncio.gather(*tasks)

    async def _run_redis_listener(self) -> None:
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

    async def _retention_sweep_loop(self) -> None:
        """Purges audit rows older than TALONX_DISPATCH_RETENTION_DAYS,
        once immediately at startup and then every
        TALONX_DISPATCH_RETENTION_SWEEP_HOURS -- same sleep/wake-on-stop
        shape as run_talonx.py's periodic_ingestion_loop."""
        interval_seconds = self.config.retention_sweep_interval_hours * 3600
        while not self._stop_event.is_set():
            await self._run_retention_sweep_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass  # normal case: interval elapsed, sweep again

    async def _run_retention_sweep_once(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.retention_days)
        try:
            purged = self.store.purge_older_than(cutoff)
        except Exception as exc:  # noqa: BLE001 -- one bad sweep shouldn't kill the loop
            logger.error("Retention sweep failed: %s", exc)
            purged = 0
        self._alerts_purged += purged
        if purged:
            logger.info(
                "Retention sweep: purged %d alert(s) older than %s (%.0f day(s))",
                purged, cutoff.isoformat(), self.config.retention_days,
            )

        try:
            lt_purged = self.store.purge_long_term_older_than(cutoff)
        except Exception as exc:  # noqa: BLE001 -- one bad sweep shouldn't kill the loop
            logger.error("Long-term retention sweep failed: %s", exc)
            lt_purged = 0
        self._long_term_alerts_purged += lt_purged
        if lt_purged:
            logger.info(
                "Retention sweep: purged %d long-term alert(s) older than %s (%.0f day(s))",
                lt_purged, cutoff.isoformat(), self.config.retention_days,
            )
        return purged + lt_purged

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
            self.config.alerts_channel, self.config.paper_trades_channel,
            self.config.alerts_channel_long_term, self.config.paper_trades_channel_long_term,
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

        if channel == self.config.paper_trades_channel:
            await self._handle_trade_execution(payload)
            return
        if channel == self.config.paper_trades_channel_long_term:
            await self._handle_long_term_trade_execution(payload)
            return
        if channel == self.config.alerts_channel_long_term:
            await self._handle_long_term_alert(payload)
            return
        if channel != self.config.alerts_channel:
            logger.warning("Dropping message on unexpected channel %s", channel)
            return

        try:
            alert = ActionableAlert.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping unparseable alert: %s", exc)
            return

        self._alerts_processed += 1
        alert_id = self.store.record_alert(alert)
        logger.info(
            "Recorded alert #%d: %s %s (%s)",
            alert_id, alert.ticker, alert.action.value, alert.severity.value,
        )

        await self._maybe_send_telegram(alert, alert_id)

    async def _handle_long_term_alert(self, payload: dict) -> None:
        try:
            alert = LongTermActionableAlert.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping unparseable long-term alert: %s", exc)
            return

        self._long_term_alerts_processed += 1
        alert_id = self.store.record_long_term_alert(alert)
        logger.info(
            "Recorded long-term alert #LT%d: %s %s (%s)",
            alert_id, alert.ticker, alert.action.value, alert.severity.value,
        )

        await self._maybe_send_long_term_telegram(alert, alert_id)

    def _company_name(self, ticker: str) -> str | None:
        try:
            row = self.watchlist_store.get_ticker(ticker)
        except Exception as exc:  # noqa: BLE001 -- a lookup failure shouldn't block the push
            logger.warning("Watchlist lookup failed for %s (%s) -- pushing without a company name", ticker, exc)
            return None
        return row["name"] if row else None

    async def _handle_trade_execution(self, payload: dict) -> None:
        try:
            execution = PaperTradeExecution.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping unparseable paper trade execution: %s", exc)
            return

        if not self.telegram_client.is_configured:
            return

        text = format_telegram_trade_execution(execution, self._company_name(execution.ticker))
        try:
            await self.telegram_client.send(text)
            logger.info(
                "Telegram push sent for paper trade #%d (%s %s)",
                execution.trade_id, execution.ticker, execution.order_type.value,
            )
        except TelegramSendError as exc:
            logger.error(
                "Telegram push failed for paper trade #%d (%s): %s",
                execution.trade_id, execution.ticker, exc,
            )

    async def _maybe_send_telegram(self, alert: ActionableAlert, alert_id: int) -> None:
        if not self.telegram_client.is_configured:
            return
        if alert.severity.rank < self._min_severity.rank:
            return

        text = format_telegram_summary(alert, alert_id, self._company_name(alert.ticker))
        try:
            await self.telegram_client.send(text)
            self.store.mark_telegram_sent(alert_id)
            self._telegram_sent += 1
            logger.info("Telegram push sent for alert #%d (%s)", alert_id, alert.ticker)
        except TelegramSendError as exc:
            self.store.mark_telegram_failed(alert_id, str(exc))
            self._telegram_failed += 1
            logger.error(
                "Telegram push failed for alert #%d (%s): %s", alert_id, alert.ticker, exc
            )

    async def _handle_long_term_trade_execution(self, payload: dict) -> None:
        try:
            execution = LongTermTradeExecution.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping unparseable long-term paper trade execution: %s", exc)
            return

        if not self.telegram_client.is_configured:
            return

        text = format_telegram_long_term_trade_execution(execution, self._company_name(execution.ticker))
        try:
            await self.telegram_client.send(text)
            logger.info(
                "Telegram push sent for long-term paper trade #%d (%s %s)",
                execution.trade_id, execution.ticker, execution.order_type.value,
            )
        except TelegramSendError as exc:
            logger.error(
                "Telegram push failed for long-term paper trade #%d (%s): %s",
                execution.trade_id, execution.ticker, exc,
            )

    async def _maybe_send_long_term_telegram(self, alert: LongTermActionableAlert, alert_id: int) -> None:
        if not self.telegram_client.is_configured:
            return
        if alert.severity.rank < self._min_severity.rank:
            return

        text = format_telegram_long_term_alert(alert, alert_id, self._company_name(alert.ticker))
        try:
            await self.telegram_client.send(text)
            self.store.mark_long_term_telegram_sent(alert_id)
            self._long_term_telegram_sent += 1
            logger.info("Telegram push sent for long-term alert #LT%d (%s)", alert_id, alert.ticker)
        except TelegramSendError as exc:
            self.store.mark_long_term_telegram_failed(alert_id, str(exc))
            self._long_term_telegram_failed += 1
            logger.error(
                "Telegram push failed for long-term alert #LT%d (%s): %s", alert_id, alert.ticker, exc
            )
