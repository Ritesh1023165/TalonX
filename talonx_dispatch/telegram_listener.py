"""
talonx_dispatch.telegram_listener
--------------------------------------
The two-way half of the Telegram integration: long-polls for incoming
messages (Bot.get_updates) and, when someone replies to a push with its
alert ID, sends back the full detail (formatter.format_telegram_details)
looked up from the audit trail. telegram_client.py only ever SENDS; this
is the only place that reads.

Phase 2: a bare numeric reply ("47") looks up the intraday `alerts`
table; an "LT"-prefixed reply ("LT47") looks up `long_term_alerts`
instead -- both tables start their own AUTOINCREMENT id sequence at 1,
so the prefix is what disambiguates which ledger a given reply means
(matches the "#LT{id}" the long-term push itself already shows).

Uses Bot.get_updates(timeout=N) -- Telegram's own server-side long-poll:
the call blocks up to N seconds waiting for a new message before
returning (possibly empty), so this isn't a busy-wait loop. `read_timeout`
(the HTTP client's own socket timeout) is set comfortably above that
server-side timeout, or the HTTP call would time out before Telegram's
long-poll ever gets a chance to respond -- a common gotcha with this
pattern.

On startup, one throwaway get_updates() call with no offset drains
whatever's already pending (without replying to any of it) before the
real loop starts, so a restart doesn't replay old commands sent while
this wasn't running.

Security: this is a personal, single-user bot (see telegram_client.py's
own docstring) -- only messages from the configured TELEGRAM_CHAT_ID are
ever acted on; anything else is silently ignored, not replied to (no
information disclosure about which IDs exist to an unrecognized chat).

Operational note: Telegram allows only ONE get_updates poller per bot
token at a time -- running two DispatchAgent processes against the same
token will make the second one's polling fail with HTTP 409 Conflict.

Interactive System Health Check (Phase 2 requirement doc): a bare "/ping"
or "ping" message is handled BEFORE the alert-ID pattern below, replying
with process uptime, CPU/RAM, the ingest WebSocket's heartbeat status
(a Redis key, not a channel -- see talonx_ingest.events.publisher.
RedisEventPublisher.write_ws_heartbeat), and today's signal counts from
the audit trail. `dispatch_agent` (optional, set by consumer.py) is how
this otherwise-standalone-testable class reaches DispatchAgent's process
start time and live Redis client without a hard constructor dependency --
None just means /ping still replies, with "unknown" for anything it needs
the agent for.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

import psutil
from telegram import Bot, Update
from telegram.error import TelegramError

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.formatter import format_telegram_details, format_telegram_long_term_details
from talonx_dispatch.store import AuditStore
# _jittered_backoff comes from telegram_client.py (not consumer.py) specifically to
# avoid a consumer.py <-> telegram_listener.py import cycle -- consumer.py imports
# THIS module to wire it in, so this module can't import back from consumer.py.
from talonx_dispatch.telegram_client import TelegramClient, TelegramSendError, _jittered_backoff

logger = logging.getLogger("talonx_dispatch.telegram_listener")

# Accepts a bare number ("47"), "#47", "/details 47", "/id 47" (intraday),
# or the same shapes prefixed with "LT" ("LT47", "#LT47") for a long-term
# alert. Group 1 captures the optional "LT" marker, group 2 the digits.
_ID_PATTERN = re.compile(r"^/?(?:details|id)?\s*#?(LT)?(\d+)$", re.IGNORECASE)


class TelegramReplyListener:
    def __init__(
        self,
        store: AuditStore,
        config: DispatchConfig | None = None,
        telegram_client: TelegramClient | None = None,
        dispatch_agent=None,
    ):
        self.store = store
        self.config = config or DispatchConfig()
        self.telegram_client = telegram_client or TelegramClient(self.config)
        # Optional -- see module docstring. Gives /ping access to
        # DispatchAgent.started_at (uptime) and its live Redis client (WS
        # heartbeat lookup) without a hard constructor dependency.
        self.dispatch_agent = dispatch_agent
        self._process = psutil.Process()
        self._stop_event = asyncio.Event()
        self._replies_sent = 0

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def replies_sent(self) -> int:
        return self._replies_sent

    async def run(self) -> None:
        if not self.telegram_client.is_configured:
            return  # nothing to poll against -- same "additive, not required" posture as sending

        attempt = 0
        while not self._stop_event.is_set():
            try:
                await self._poll_forever()
                return  # clean stop() was called
            except Exception as exc:  # noqa: BLE001 -- any polling failure retries
                attempt += 1
                wait = _jittered_backoff(
                    attempt, self.config.reconnect_backoff_base_seconds,
                    self.config.reconnect_backoff_max_seconds,
                )
                logger.warning(
                    "Telegram polling error (%s); reconnecting in %.1fs (attempt %d)",
                    exc, wait, attempt,
                )
                await asyncio.sleep(wait)

    async def _poll_forever(self) -> None:
        async with Bot(token=self.config.telegram_bot_token) as bot:
            offset = await self._drain_backlog(bot)
            logger.info("Telegram reply listener polling (poll timeout %.0fs)", self.config.telegram_poll_timeout_seconds)

            while not self._stop_event.is_set():
                try:
                    updates = await bot.get_updates(
                        offset=offset,
                        timeout=int(self.config.telegram_poll_timeout_seconds),
                        read_timeout=self.config.telegram_poll_timeout_seconds + 10.0,
                        allowed_updates=["message"],
                    )
                except TelegramError as exc:
                    logger.warning("get_updates failed (%s); retrying shortly", exc)
                    await asyncio.sleep(5.0)
                    continue

                for update in updates:
                    offset = update.update_id + 1
                    await self._handle_update(update)

    async def _drain_backlog(self, bot: Bot) -> int | None:
        updates = await bot.get_updates(timeout=0, allowed_updates=["message"])
        if not updates:
            return None
        drained = updates[-1].update_id + 1
        logger.info("Drained %d pending Telegram update(s) on startup without replying", len(updates))
        return drained

    async def _handle_update(self, update: Update) -> None:
        message = update.message
        if message is None or not message.text:
            return

        if str(message.chat_id) != str(self.config.telegram_chat_id):
            logger.warning("Ignoring Telegram message from unrecognized chat_id=%s", message.chat_id)
            return

        if message.text.strip().lower() in ("/ping", "ping"):
            await self._handle_ping()
            return

        parsed = _parse_alert_id(message.text)
        if parsed is None:
            await self._reply(
                "Reply with an alert ID number (e.g. 47) or a long-term alert ID "
                "(e.g. LT47) to get its full details."
            )
            return
        is_long_term, alert_id = parsed

        if is_long_term:
            row = self.store.get_long_term_by_id(alert_id)
            if row is None:
                await self._reply(
                    f"Long-term alert #LT{alert_id} not found -- either it never existed, or it's "
                    f"older than the {self.config.retention_days:.0f}-day retention window."
                )
                return
            await self._reply(format_telegram_long_term_details(row))
            return

        row = self.store.get_by_id(alert_id)
        if row is None:
            await self._reply(
                f"Alert #{alert_id} not found -- either it never existed, or it's older "
                f"than the {self.config.retention_days:.0f}-day retention window."
            )
            return

        await self._reply(format_telegram_details(row))

    async def _handle_ping(self) -> None:
        """Interactive System Health Check -- replies within the same
        long-poll turn that received the message (no extra network hop
        beyond the Telegram send itself), well under the spec's <1s target."""
        cpu_pct = self._process.cpu_percent(interval=None)
        mem_used_gb = self._process.memory_info().rss / (1024 ** 3)
        mem_total_gb = psutil.virtual_memory().total / (1024 ** 3)
        total_today, pushed_today = self.store.count_alerts_today()

        lines = [
            "\U0001F3D3 Pong! TalonX Engine Online",
            "─" * 30,
            "\U0001F7E2 Server Status: Active / Healthy",
            f"⏱️ Uptime: {self._format_uptime()}",
            f"\U0001F4BB CPU Usage: {cpu_pct:.1f}%  |  RAM: {mem_used_gb:.1f} GB / {mem_total_gb:.1f} GB",
            f"\U0001F4E1 WebSocket Stream: {await self._ws_status()}",
            f"\U0001F4CA Today's Signals Pushed: {pushed_today} Pushes ({total_today} Logs)",
        ]
        await self._reply("\n".join(lines))

    def _format_uptime(self) -> str:
        if self.dispatch_agent is None or getattr(self.dispatch_agent, "started_at", None) is None:
            return "unknown"
        total_seconds = int((datetime.now(timezone.utc) - self.dispatch_agent.started_at).total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours}h {minutes}m"

    async def _ws_status(self) -> str:
        client = getattr(self.dispatch_agent, "_client", None)
        if client is None:
            return "Unknown (no Redis connection)"
        try:
            raw = await client.get(self.config.ws_heartbeat_key)
        except Exception as exc:  # noqa: BLE001 -- a status-check failure must not break /ping
            logger.warning("WS heartbeat lookup failed: %s", exc)
            return "Unknown"
        if raw is None:
            return "Disconnected"
        try:
            source = json.loads(raw).get("source")
        except (TypeError, ValueError):
            return "Connected"
        label = "Polygon.io" if source == "websocket" else "yfinance polling" if source == "polling" else source
        return f"Connected ({label})" if label else "Connected"

    async def _reply(self, text: str) -> None:
        try:
            await self.telegram_client.send(text)
            self._replies_sent += 1
        except TelegramSendError as exc:
            logger.error("Failed to send Telegram reply: %s", exc)


def _parse_alert_id(text: str) -> tuple[bool, int] | None:
    """Returns (is_long_term, id), or None if the text doesn't match the
    ID pattern at all."""
    match = _ID_PATTERN.match(text.strip())
    if not match:
        return None
    is_long_term = match.group(1) is not None
    return is_long_term, int(match.group(2))
