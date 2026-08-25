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

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.store import AuditStore
from talonx_dispatch.telegram_listener import TelegramReplyListener


@dataclass
class _PivPingContext:
    """Minimal `dispatch_agent`-shaped shim (Task 69P Telegram parity
    fix): TelegramReplyListener's /ping only reads `._client` (Redis,
    for uptime-independent quant/redis-backed metrics),
    `.started_at` (uptime), `.watchlist_store` (PIV has none -- stays
    None, already handled as "unknown" by the existing code), and now
    `.piv_info` (a small dict this class alone introduces -- see
    telegram_listener.TelegramReplyListener._piv_section). Nothing here
    changes any existing DispatchAgent code path; this is a new,
    separate, PIV-only object."""

    _client: Any = None
    started_at: datetime | None = None
    watchlist_store: Any = None
    piv_info: dict | None = None
    telegram_failed: int = 0
    long_term_telegram_failed: int = 0


def build_piv_info(
    feed_mode: str | None = None, universe: tuple[str, ...] = (),
    session_id: str | None = None, runtime_sha: str | None = None, config_hash: str | None = None,
) -> dict:
    """Task 69Q Part 8 -- the single mutable dict shared by cli.py between
    SessionRunner (which updates it live: feed health, warmup/session-ready
    counts, quant funnel, natural-vs-probe order/fill counts, radar WATCH
    count) and the /ping listener (which only reads it) so /ping reflects
    the CURRENT running session, not just its startup snapshot. All
    optional fields default to "unknown"/0 so the very first /ping right
    after startup still renders every line."""
    return {
        "mode": "PAPER / NO REAL CAPITAL",
        "feed_provider": _feed_provider_label(feed_mode),
        "universe_size": len(universe) if universe else "unknown",
        "session_id": session_id or "unknown",
        "runtime_sha": runtime_sha or "unknown",
        "config_hash": config_hash or "unknown",
        "feed_health": "UNKNOWN (session starting up)",
        "warmup_ready_count": "unknown", "session_ready_count": "unknown", "stale_count": 0,
        "quant_evaluation_cycles": 0, "quant_candidates": 0, "quant_published": 0,
        "quant_rejected": 0, "quant_unaccounted": 0,
        "radar_watch_count": 0,
        "natural_orders": 0, "natural_fills": 0, "probe_orders": 0, "probe_fills": 0,
        "eod_status": "PENDING (session in progress)",
    }


def build_piv_telegram_listener(
    state_dir: Path,
    *,
    redis_client: Any = None,
    started_at: datetime | None = None,
    feed_mode: str | None = None,
    universe: tuple[str, ...] = (),
    piv_info: dict | None = None,
) -> TelegramReplyListener:
    """PIV-scoped audit DB (under the PIV runtime state dir, not
    ~/.talonx/dispatch_audit.db) so this never shares or corrupts a
    separately-running full application's own audit trail.

    `dispatch_agent` is a `_PivPingContext` shim (not None, as of Task
    69P) -- reusing the EXISTING TelegramReplyListener/`_handle_ping`
    implementation unmodified in its general-app behavior (see
    telegram_listener.py's own additive `_piv_section` gate), while
    giving /ping real values for uptime, quant/redis-backed metrics
    (QuantScanner shares this SAME `redis_client`, writing to the same
    `metrics:{date}:quant:*` keys `_quant_section` already reads), and
    the PAPER-mode/feed-provider/universe fields this task requires that
    no other existing /ping field covers. All optional/keyword-only with
    safe defaults so a caller that doesn't pass them still gets a valid
    (mostly "unknown") listener, matching the pre-existing degrade
    posture."""
    config = DispatchConfig(audit_db_path=str(state_dir / "piv_telegram_audit.db"))
    store = AuditStore(config.audit_db_path)
    piv_info = piv_info if piv_info is not None else build_piv_info(feed_mode, universe)
    agent = _PivPingContext(
        _client=redis_client, started_at=started_at, piv_info=piv_info,
    )
    return TelegramReplyListener(store, config, dispatch_agent=agent)


def _feed_provider_label(feed_mode: str | None) -> str:
    """Human-readable label for the ACTUAL live feed this PIV session is
    using -- never a hardcoded/stale provider name. `feed_mode` is
    PivConfig.feed_mode ("RESEARCH_SIP" or "IEX_PAPER_PIV", see
    talonx_piv/config.py's FEED_MODES/FEED_MODE_PARAM)."""
    if feed_mode == "IEX_PAPER_PIV":
        return "Alpaca IEX (PAPER PIV operational feed)"
    if feed_mode == "RESEARCH_SIP":
        return "Alpaca SIP (research/canonical feed)"
    return f"unknown (feed_mode={feed_mode!r})" if feed_mode else "unknown (feed_mode not set)"


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
