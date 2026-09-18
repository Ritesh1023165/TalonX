"""
talonx_ops.notify -- RI-2: the three LOGICAL Telegram destinations.
====================================================================
TRADE_EVENT, OPERATIONS, RESEARCH. Business code emits/classifies an
event against one of these three logical destinations; THIS module
resolves a logical destination to a bot/token/chat configuration --
business code never scatters raw Telegram chat IDs.

Today there is exactly ONE physical Telegram bot/token
(``TELEGRAM_BOT_TOKEN``/``TELEGRAM_CHAT_ID``, ``talonx_dispatch.config.
DispatchConfig``), already reused by V2 (``talonx_v2/delivery.py``) and
Intelligence (``talonx_ingest/intelligence/delivery/pipeline.py``). This
module does NOT invent a second bot -- TRADE_EVENT and OPERATIONS fall
back to that SAME existing bot/chat when no destination-specific
credentials are configured (byte-identical to today's single-bot
behavior, reusing existing architecture per this task's own
instruction). RESEARCH gets NO such fallback and requires an explicit,
separate double opt-in (its own credentials AND
``TALONX_NOTIFY_RESEARCH_ENABLED=1``) -- it is never reachable merely
because TRADE_EVENT/OPERATIONS happen to be configured.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

TRADE_EVENT = "TRADE_EVENT"
OPERATIONS = "OPERATIONS"
RESEARCH = "RESEARCH"

DESTINATIONS = (TRADE_EVENT, OPERATIONS, RESEARCH)


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class DestinationConfig:
    destination: str
    enabled: bool
    bot_token: str | None
    chat_id: str | None
    reason: str


def resolve_destination_config(destination: str) -> DestinationConfig:
    """The ONE place that decides whether/how a logical destination may
    send. Never raises -- an unconfigured/disabled destination is a
    normal, valid, silent-no-send state (RI2-C: "Research OFF + no
    Research token/chat = valid configuration"), not an error."""
    if destination not in DESTINATIONS:
        return DestinationConfig(destination, False, None, None,
                                 f"unknown destination {destination!r}")

    if destination == RESEARCH:
        # explicit double opt-in -- own credentials AND an explicit
        # enable flag, so a stray token/chat_id in the environment can
        # never silently activate Research on its own.
        if not _env_bool("TALONX_NOTIFY_RESEARCH_ENABLED", False):
            return DestinationConfig(RESEARCH, False, None, None,
                                     "RESEARCH is OFF by default "
                                     "(TALONX_NOTIFY_RESEARCH_ENABLED not set)")
        token = _env("TALONX_NOTIFY_RESEARCH_BOT_TOKEN")
        chat = _env("TALONX_NOTIFY_RESEARCH_CHAT_ID")
        if not (token and chat):
            return DestinationConfig(RESEARCH, False, None, None,
                                     "RESEARCH enabled but TALONX_NOTIFY_RESEARCH_BOT_TOKEN/"
                                     "_CHAT_ID not configured -- no fallback to the primary bot")
        return DestinationConfig(RESEARCH, True, token, chat, "RESEARCH explicitly enabled")

    # TRADE_EVENT / OPERATIONS: destination-specific credentials, or fall
    # back to the existing single official bot (today's behavior).
    prefix = f"TALONX_NOTIFY_{destination}"
    token = _env(f"{prefix}_BOT_TOKEN") or _env("TELEGRAM_BOT_TOKEN")
    chat = _env(f"{prefix}_CHAT_ID") or _env("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return DestinationConfig(destination, False, None, None,
                                 f"{destination}: no destination-specific credentials and no "
                                 "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID fallback configured")
    used_dedicated = bool(_env(f"{prefix}_BOT_TOKEN"))
    return DestinationConfig(destination, True, token, chat,
                             f"{destination}: using "
                             + ("dedicated destination credentials" if used_dedicated
                                else "the shared primary bot/chat (no dedicated credentials set)"))


def telegram_client_for(destination: str):
    """Returns a configured talonx_dispatch.telegram_client.TelegramClient
    for this destination, or None if the destination is not enabled.
    Reuses the EXISTING client class unchanged -- only the config it is
    constructed with differs per destination."""
    cfg = resolve_destination_config(destination)
    if not cfg.enabled:
        return None
    from talonx_dispatch.config import DispatchConfig
    from talonx_dispatch.telegram_client import TelegramClient
    return TelegramClient(config=DispatchConfig(telegram_bot_token=cfg.bot_token,
                                                 telegram_chat_id=cfg.chat_id))
