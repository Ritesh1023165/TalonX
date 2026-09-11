"""
talonx_dispatch.telegram_client
------------------------------------
Thin async wrapper around python-telegram-bot's Bot.send_message, with
retry/backoff matching this project's established pattern (SEC EDGAR,
NewsAPI, Reddit, and Gemini all retry transient failures with jittered
exponential backoff; non-retryable errors -- bad token, bot blocked --
fail fast instead of burning through the retry budget).

Additive, not required: like RedditClient, `is_configured` gates the
whole thing -- if TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID aren't set, send()
is a silent no-op, and the rest of the pipeline (the audit trail) is
unaffected.

Uses `async with Bot(token=...) as bot:` per call rather than holding one
Bot "initialized" for the process's whole lifetime -- python-telegram-bot
v20+'s documented safe usage pattern, and alerts are infrequent enough
(rate-limited upstream to a handful per minute by talonx_brain's own
Gemini quota) that the per-call overhead is negligible.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import timedelta

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import Forbidden, InvalidToken, NetworkError, RetryAfter, TelegramError, TimedOut

from talonx_dispatch.config import DispatchConfig

logger = logging.getLogger("talonx_dispatch.telegram_client")


class TelegramSendError(Exception):
    """Raised after exhausting retries -- caller decides how to record the failure."""

    def __init__(self, *a, ambiguous: bool = False):
        super().__init__(*a)
        self.ambiguous = ambiguous


class TelegramAmbiguousError(TelegramSendError):
    """The request left the process but the outcome could not be confirmed
    (post-send timeout / network drop). Telegram may or may not have the
    message. The caller MUST NOT blind-retry -- resolve it as AMBIGUOUS."""

    def __init__(self, *a):
        super().__init__(*a, ambiguous=True)


def _jittered_backoff(attempt: int, base: float, max_delay: float) -> float:
    raw = base * (2 ** (attempt - 1))
    capped = min(raw, max_delay)
    return capped * (0.5 + random.random())


class TelegramClient:
    def __init__(self, config: DispatchConfig | None = None):
        self.config = config or DispatchConfig()

    @property
    def is_configured(self) -> bool:
        return bool(self.config.telegram_bot_token and self.config.telegram_chat_id)

    async def send(
        self, text: str, parse_mode: str | None = ParseMode.MARKDOWN,
        *, retry_ambiguous: bool = True,
    ):
        """
        No-op if not configured. Raises TelegramSendError after
        exhausting retries on a transient failure, or immediately on a
        non-retryable one (bad token, bot blocked/kicked from the chat).

        `parse_mode` defaults to legacy Markdown (existing behavior, for
        every pre-existing caller -- formatted alert pushes/alert-detail
        replies that already escape their own Markdown). Pass `None` for
        text that may contain arbitrary/dynamic content (ticker symbols,
        status strings) not guaranteed to be valid Markdown -- e.g. an
        unescaped `_`/`*`/`` ` ``/`[` in the text otherwise makes Telegram
        reject the ENTIRE message with a 400 "can't parse entities" error
        (confirmed live, 2026-08-18 incident: talonx_dispatch/telegram_listener.py's
        /ping diagnostics embed the raw session-state label, e.g.
        'pre_market', whose underscore broke Markdown parsing every time).
        """
        if not self.is_configured:
            return None

        attempt = 0
        while True:
            try:
                async with Bot(token=self.config.telegram_bot_token) as bot:
                    return await bot.send_message(
                        chat_id=self.config.telegram_chat_id,
                        text=text,
                        parse_mode=parse_mode,
                        disable_web_page_preview=True,
                    )
            except (InvalidToken, Forbidden) as exc:
                # Config/permission problem, not a transient failure -- retrying won't help.
                raise TelegramSendError(f"Telegram send failed (non-retryable): {exc}") from exc
            except RetryAfter as exc:
                # A 429 means Telegram REJECTED the request -- it is NOT ambiguous;
                # safe to wait and retry per Telegram's own hint.
                attempt += 1
                if attempt > self.config.telegram_max_retries:
                    raise TelegramSendError(
                        f"Exhausted {self.config.telegram_max_retries} retries: {exc}"
                    ) from exc
                wait = exc.retry_after.total_seconds() if isinstance(exc.retry_after, timedelta) else float(exc.retry_after)
                logger.warning("Telegram rate limit hit; retrying in %.1fs (attempt %d)", wait, attempt)
                await asyncio.sleep(wait)
            except (TimedOut, NetworkError) as exc:
                # The request may have reached Telegram AFTER we gave up waiting
                # for the ack. Blind-retrying here can double-send.
                if not retry_ambiguous:
                    raise TelegramAmbiguousError(
                        f"Telegram send outcome unconfirmed ({type(exc).__name__}: {exc})"
                    ) from exc
                attempt += 1
                if attempt > self.config.telegram_max_retries:
                    raise TelegramSendError(
                        f"Exhausted {self.config.telegram_max_retries} retries: {exc}"
                    ) from exc
                wait = _jittered_backoff(
                    attempt, self.config.telegram_backoff_base_seconds,
                    self.config.telegram_backoff_max_seconds,
                )
                logger.warning(
                    "Telegram network error (%s); retrying in %.1fs (attempt %d/%d)",
                    exc, wait, attempt, self.config.telegram_max_retries,
                )
                await asyncio.sleep(wait)
            except TelegramError as exc:
                # a clean, definite error (bad request, chat migrated, ...) --
                # Telegram did not accept the message; retry within budget.
                attempt += 1
                if attempt > self.config.telegram_max_retries:
                    raise TelegramSendError(
                        f"Exhausted {self.config.telegram_max_retries} retries: {exc}"
                    ) from exc
                wait = _jittered_backoff(
                    attempt, self.config.telegram_backoff_base_seconds,
                    self.config.telegram_backoff_max_seconds,
                )
                logger.warning(
                    "Telegram send error (%s); retrying in %.1fs (attempt %d/%d)",
                    exc, wait, attempt, self.config.telegram_max_retries,
                )
                await asyncio.sleep(wait)
