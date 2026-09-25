"""
Sentinel command poller: long-polls ONLY the TalonX Sentinel (OPERATIONS) bot and answers operator commands.

Off unless ``TALONX_SENTINEL_COMMANDS_ENABLED=1`` (not started today). Credentials come only from
``talonx_ops.notify.telegram_client_for(OPERATIONS)`` -- never the Signal/Lab bots or the legacy default token.
Each bot token has its own update queue, so this does not compete with the existing primary listener. NOTE for
activation: the prospective single-poller health check counts processes holding a Telegram long-poll; it must
learn about this registered Sentinel poller before this is enabled (see the EOD activation package).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from talonx_ops.operator_control import mutation_mode
from talonx_ops.operator_control.commands import handle
from talonx_ops.operator_control.scanned import ScannedReader
from talonx_ops.operator_control.store import OperatorStore

log = logging.getLogger("talonx_ops.operator_control.sentinel")
ENABLE_ENV = "TALONX_SENTINEL_COMMANDS_ENABLED"


class SentinelCommandPoller:
    def __init__(self, *, bot, owner_chat_id, store: OperatorStore | None = None, scanned_factory=None, env=None):
        self.bot, self.owner = bot, owner_chat_id
        self.store = store or OperatorStore()
        self.env = env
        self.scanned_factory = scanned_factory or (lambda: ScannedReader(excluded=self.store.excluded(),
                                                                         added=self.store.added()))
        self.handled = 0

    async def handle_message(self, message) -> bool:
        if message is None or not getattr(message, "text", None):
            return False
        user = str(getattr(getattr(message, "from_user", None), "id", "") or "")
        rep = handle(message.text, chat_id=message.chat_id, user=user, owner_chat_id=self.owner, store=self.store,
                     mode=mutation_mode(self.env), scanned=self.scanned_factory())
        if rep is None:
            return False
        if rep.document is not None:
            await self.bot.send_document(chat_id=message.chat_id, document=rep.document, filename=rep.filename,
                                         caption=rep.text[:1000])
        else:
            await self.bot.send_message(chat_id=message.chat_id, text=rep.text[:4000])
        self.handled += 1
        return True

    async def poll_once(self, offset: int | None, timeout: int = 30) -> int | None:
        updates = await self.bot.get_updates(offset=offset, timeout=timeout, allowed_updates=["message"])
        for u in updates:
            offset = u.update_id + 1
            try:
                await self.handle_message(u.message)
            except Exception:  # noqa: BLE001 -- one bad command must never stop the poller
                log.exception("sentinel command failed")
        return offset


async def _run() -> int:
    from telegram import Bot

    from talonx_ops.notify import OPERATIONS, resolve_destination_config
    cfg = resolve_destination_config(OPERATIONS)
    if not cfg.enabled:
        print(f"Sentinel commands: OPERATIONS destination not configured ({cfg.reason})")
        return 2
    async with Bot(token=cfg.bot_token) as bot:
        p = SentinelCommandPoller(bot=bot, owner_chat_id=cfg.chat_id)
        offset = None
        while True:
            offset = await p.poll_once(offset)


def main() -> int:
    try:                                        # .env with override=False (a process-scoped value always wins)
        from pathlib import Path

        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    except Exception:  # noqa: BLE001
        pass
    if os.environ.get(ENABLE_ENV, "0").strip() != "1":
        print(f"Sentinel commands are OFF ({ENABLE_ENV}=1 required; post-EOD activation boundary)")
        return 0
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
