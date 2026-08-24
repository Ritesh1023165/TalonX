"""Task 66A Part 2 -- reuses the existing inbound Telegram command listener
(talonx_dispatch.telegram_listener.TelegramReplyListener) in the PAPER PIV
runtime, rather than building a second one. That class is already designed
for exactly this: `dispatch_agent=None` is a documented, supported degrade
path ("None just means /ping still replies, with 'unknown' for anything it
needs the agent for" -- see its own module docstring) that requires no
Redis-metric-counter wiring, no watchlist store, no DispatchAgent instance
-- just an AuditStore (a local SQLite file, PIV-scoped so it never shares
state with a separately-running full run_talonx.py instance's own audit
trail) and the same TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID already used for
outbound sends.

Single-poller constraint (documented in telegram_listener.py itself):
Telegram allows only ONE Bot.get_updates() poller per bot token at a time --
a second poller against the SAME token returns HTTP 409 Conflict. If a
separate run_talonx.py process is ALSO running against the same bot token
at the same time as a PIV session, do not enable this (--no-telegram-inbound
on `cli.py start`) -- outbound sends are unaffected either way; only the
inbound listener conflicts.
"""

from __future__ import annotations

from pathlib import Path

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.store import AuditStore
from talonx_dispatch.telegram_listener import TelegramReplyListener


def build_piv_telegram_listener(state_dir: Path) -> TelegramReplyListener:
    """PIV-scoped audit DB (under the PIV runtime state dir, not
    ~/.talonx/dispatch_audit.db) so this never shares or corrupts a
    separately-running full application's own audit trail. dispatch_agent
    is deliberately None -- see module docstring."""
    config = DispatchConfig(audit_db_path=str(state_dir / "piv_telegram_audit.db"))
    store = AuditStore(config.audit_db_path)
    return TelegramReplyListener(store, config, dispatch_agent=None)


def telegram_inbound_capable(state_dir: Path) -> tuple[bool, str]:
    """Cheap capability check for preflight: can the listener and its
    AuditStore actually be constructed (imports resolve, the local SQLite
    file opens) -- not a live poll, no network call, no side effect beyond
    a local file open/create identical to what logging_writable already
    does for telemetry."""
    try:
        listener = build_piv_telegram_listener(state_dir)
    except Exception as exc:  # noqa: BLE001 -- preflight must report, never raise
        return False, f"telegram inbound listener construction failed: {type(exc).__name__}: {exc}"
    configured = listener.telegram_client.is_configured
    return True, (
        "TelegramReplyListener constructed; will poll for inbound /ping when started"
        if configured else
        "TelegramReplyListener constructed; TELEGRAM_BOT_TOKEN/CHAT_ID not configured -- inbound listener will no-op, matching outbound's own additive posture"
    )
