"""
talonx_dispatch.telegram_listener
--------------------------------------
The two-way half of the Telegram integration: long-polls for incoming
messages (Bot.get_updates) and, when someone replies to a push with its
alert ID, sends back the full detail (formatter.format_telegram_details)
looked up from the audit trail. telegram_client.py only ever SENDS; this
is the only place that reads.

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
"""
from __future__ import annotations

import asyncio
import logging
import re

from telegram import Bot, Update
from telegram.error import TelegramError

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.formatter import format_telegram_details
from talonx_dispatch.store import AuditStore
# _jittered_backoff comes from telegram_client.py (not consumer.py) specifically to
# avoid a consumer.py <-> telegram_listener.py import cycle -- consumer.py imports
# THIS module to wire it in, so this module can't import back from consumer.py.
from talonx_dispatch.telegram_client import TelegramClient, TelegramSendError, _jittered_backoff

logger = logging.getLogger("talonx_dispatch.telegram_listener")

# Accepts a bare number ("47"), "#47", "/details 47", or "/id 47".
_ID_PATTERN = re.compile(r"^/?(?:details|id)?\s*#?(\d+)$", re.IGNORECASE)


class TelegramReplyListener:
    def __init__(
        self,
        store: AuditStore,
        config: DispatchConfig | None = None,
        telegram_client: TelegramClient | None = None,
    ):
        self.store = store
        self.config = config or DispatchConfig()
        self.telegram_client = telegram_client or TelegramClient(self.config)
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

        alert_id = _parse_alert_id(message.text)
        if alert_id is None:
            await self._reply("Reply with an alert ID number (e.g. 47) to get its full details.")
            return

        row = self.store.get_by_id(alert_id)
        if row is None:
            await self._reply(
                f"Alert #{alert_id} not found -- either it never existed, or it's older "
                f"than the {self.config.retention_days:.0f}-day retention window."
            )
            return

        await self._reply(format_telegram_details(row))

    async def _reply(self, text: str) -> None:
        try:
            await self.telegram_client.send(text)
            self._replies_sent += 1
        except TelegramSendError as exc:
            logger.error("Failed to send Telegram reply: %s", exc)


def _parse_alert_id(text: str) -> int | None:
    match = _ID_PATTERN.match(text.strip())
    return int(match.group(1)) if match else None
