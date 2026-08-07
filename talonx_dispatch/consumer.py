"""
talonx_dispatch.consumer
-----------------------------
Async Redis Pub/Sub consumer: subscribes to talonx:alerts:dispatch, and
for each ActionableAlert, records it to the durable audit trail
(store.py) and -- if Telegram is configured and the alert's severity
clears TALONX_DISPATCH_MIN_SEVERITY -- formats and sends it as a mobile
push notification.

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
"""
from __future__ import annotations

import asyncio
import json
import logging
import random

from pydantic import ValidationError

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.formatter import format_telegram_message
from talonx_dispatch.schemas import ActionableAlert, AlertSeverity
from talonx_dispatch.store import AuditStore
from talonx_dispatch.telegram_client import TelegramClient, TelegramSendError

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
    ):
        self.config = config or DispatchConfig()
        self.store = store or AuditStore(self.config.audit_db_path)
        self.telegram_client = telegram_client or TelegramClient(self.config)
        self._client = None
        self._stop_event = asyncio.Event()
        self._alerts_processed = 0
        self._telegram_sent = 0
        self._telegram_failed = 0

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

    @property
    def alerts_processed(self) -> int:
        return self._alerts_processed

    @property
    def telegram_sent(self) -> int:
        return self._telegram_sent

    @property
    def telegram_failed(self) -> int:
        return self._telegram_failed

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
        await pubsub.subscribe(self.config.alerts_channel)
        logger.info("Subscribed to %s", self.config.alerts_channel)

        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue  # normal: no message within this poll window
                await self._handle_message(message)
        finally:
            await pubsub.unsubscribe(self.config.alerts_channel)
            await pubsub.aclose()
            await self._client.aclose()

    async def _handle_message(self, message: dict) -> None:
        raw = message.get("data")
        if raw is None:
            return

        try:
            payload = json.loads(raw)
            alert = ActionableAlert.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Dropping unparseable alert: %s", exc)
            return

        self._alerts_processed += 1
        alert_id = self.store.record_alert(alert)
        logger.info(
            "Recorded alert #%d: %s %s (%s)",
            alert_id, alert.ticker, alert.action.value, alert.severity.value,
        )

        await self._maybe_send_telegram(alert, alert_id)

    async def _maybe_send_telegram(self, alert: ActionableAlert, alert_id: int) -> None:
        if not self.telegram_client.is_configured:
            return
        if alert.severity.rank < self._min_severity.rank:
            return

        text = format_telegram_message(alert)
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
