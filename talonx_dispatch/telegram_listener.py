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
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

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

_ET = ZoneInfo("America/New_York")
_UK_TZ = ZoneInfo("Europe/London")
# Mirrors talonx_quant.session.get_session's own US-market time-of-day
# boundaries -- deliberately re-declared here rather than imported, same
# "no internal library between modules" convention this project already
# uses for _incr_metric (each module re-declares its own small copy
# rather than sharing one across the ingest/quant/brain/core/dispatch
# layering).
_PRE_MARKET_START = time(4, 0)
_REGULAR_START = time(9, 30)
_REGULAR_END = time(16, 0)


def _us_session(now_utc: datetime) -> str:
    local_time = now_utc.astimezone(_ET).time()
    if _PRE_MARKET_START <= local_time < _REGULAR_START:
        return "pre_market"
    if _REGULAR_START <= local_time < _REGULAR_END:
        return "regular"
    return "closed"


async def _get_metric(client, stage: str, counter: str) -> int | None:
    """Reads one `metrics:{today}:{stage}:{counter}` Redis key -- the
    same per-UTC-day scheme every producer module's own `_incr_metric`
    helper writes to (talonx_quant/talonx_brain/talonx_core/
    talonx_dispatch), already read back the same way by
    talonx_dispatch/app.py's Daily Funnel dashboard tab. Returns 0 if
    the key is simply absent (a counter that legitimately never
    incremented today -- _incr_metric only ever creates a key on a real
    increment, so "no key" truthfully means zero, not unknown), or None
    if the read couldn't be attempted/completed at all (no Redis client,
    a read failure, or an unparseable value) -- callers must surface
    None as "unknown", never silently coerce it to 0."""
    if client is None:
        return None
    key = f"metrics:{datetime.now(timezone.utc):%Y-%m-%d}:{stage}:{counter}"
    try:
        raw = await client.get(key)
    except Exception as exc:  # noqa: BLE001 -- a health-check read must never raise
        logger.warning("Metric read failed for %s: %s", key, exc)
        return None
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def _sum_metrics(client, stage: str, counters: list[str]) -> int | None:
    """Sum of several same-stage counters (e.g. dispatch's three
    suppression reasons) -- None (unknown) if ANY constituent read
    failed, since a partial sum would misrepresent the total rather
    than honestly reporting it couldn't be determined."""
    values = [await _get_metric(client, stage, c) for c in counters]
    if any(v is None for v in values):
        return None
    return sum(values)


def _fmt_metric(value: int | None) -> str:
    return "unknown" if value is None else f"{value:,}"

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
        beyond the Telegram send itself), well under the spec's <1s target.

        2026-08-17 pipeline-observability fix: beyond the original
        uptime/CPU/RAM/WS-status/today's-pushes summary, this now answers
        "where is the pipeline currently stopping" stage by stage
        (MARKET -> QUANT -> BRAIN -> CORE -> DISPATCH), plus current
        session state. Every figure below is read from something that
        already exists (the `metrics:{date}:{stage}:{counter}` Redis
        counters every producer module already writes -- see
        talonx_dispatch/app.py's Daily Funnel tab for the same read
        pattern; the rejected_candidates SQLite audit table; the WS
        heartbeat key) -- nothing here is invented. A figure with no
        reliable existing source (e.g. watchlist size, BRAIN's own
        reports-generated count -- an in-process-only counter no other
        module can see) is reported as the literal string "unknown",
        never a fabricated zero."""
        cpu_pct = self._process.cpu_percent(interval=None)
        mem_used_gb = self._process.memory_info().rss / (1024 ** 3)
        mem_total_gb = psutil.virtual_memory().total / (1024 ** 3)
        total_today, pushed_today = self.store.count_alerts_today()
        client = getattr(self.dispatch_agent, "_client", None)

        lines = [
            "\U0001F3D3 Pong! TalonX Engine Online",
            "─" * 30,
            "\U0001F7E2 Server Status: Active / Healthy",
            f"⏱️ Uptime: {self._format_uptime()}",
            f"\U0001F4BB CPU Usage: {cpu_pct:.1f}%  |  RAM: {mem_used_gb:.1f} GB / {mem_total_gb:.1f} GB",
            f"\U0001F4CA Today's Signals Pushed: {pushed_today} Pushes ({total_today} Logs)",
            "",
            *await self._market_section(client),
            "",
            *await self._quant_section(client),
            "",
            *await self._brain_section(client),
            "",
            *await self._core_section(client),
            "",
            *await self._dispatch_section(client),
            "",
            *self._session_section(),
        ]
        await self._reply("\n".join(lines))

    def _format_uptime(self) -> str:
        if self.dispatch_agent is None or getattr(self.dispatch_agent, "started_at", None) is None:
            return "unknown"
        total_seconds = int((datetime.now(timezone.utc) - self.dispatch_agent.started_at).total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours}h {minutes}m"

    async def _market_section(self, client) -> list[str]:
        bars_read = await _get_metric(client, "ingest", "bars_read")
        last_event_at, health = await self._market_feed_freshness(client)
        return [
            "\U0001F4E1 MARKET",
            f"  Source: {await self._ws_status()}",
            "  Watchlist size: unknown (no authoritative source is currently exposed to dispatch)",
            f"  Bars/events received today: {_fmt_metric(bars_read)}",
            f"  Last market event: {last_event_at}",
            f"  Feed status: {health}",
            "  Feed errors: unknown (not currently counted -- see remaining known issues)",
        ]

    async def _market_feed_freshness(self, client) -> tuple[str, str]:
        """Returns (last_event_description, health_label), derived from
        the WS heartbeat's `updated_at` field (talonx_ingest.events.
        publisher.RedisEventPublisher.write_ws_heartbeat already writes
        this timestamp on every market event -- _ws_status above never
        read it; this is the same key, read a second time, purely
        additive). Distinguishes a genuinely fresh feed from one that's
        technically still within the heartbeat's TTL but hasn't actually
        updated in a while -- a plain "key exists" check alone can't
        tell the two apart."""
        if client is None:
            return "unknown (no Redis connection)", "unknown"
        try:
            raw = await client.get(self.config.ws_heartbeat_key)
        except Exception as exc:  # noqa: BLE001 -- a status-check failure must not break /ping
            logger.warning("WS heartbeat lookup failed: %s", exc)
            return "unknown", "unknown"
        if raw is None:
            return "unknown (no heartbeat)", "\U0001F534 disconnected"

        try:
            updated_at_raw = json.loads(raw).get("updated_at")
        except (TypeError, ValueError):
            return "unknown (malformed heartbeat)", "\U0001F7E1 unknown"
        if not updated_at_raw:
            return "unknown (no timestamp in heartbeat)", "\U0001F7E1 unknown"
        try:
            updated_at = datetime.fromisoformat(updated_at_raw)
        except ValueError:
            return "unknown (unparseable timestamp)", "\U0001F7E1 unknown"

        age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
        last_event_desc = f"{age_seconds:.0f}s ago ({updated_at.strftime('%H:%M:%S')} UTC)"
        # 90s: comfortably above the 5s default yfinance poll interval and
        # a real WebSocket's tick cadence, comfortably below the 120s
        # heartbeat TTL a stale-but-not-yet-expired key could otherwise
        # hide behind.
        health = "\U0001F7E2 healthy" if age_seconds < 90 else "\U0001F7E1 stale"
        return last_event_desc, health

    async def _quant_section(self, client) -> list[str]:
        evaluated = await _get_metric(client, "quant", "evaluated")
        published = await _get_metric(client, "quant", "published")
        rejected_today = self._rejected_candidates_today_count()
        return [
            "\U0001F9E0 QUANT",
            f"  Candidates generated today: {_fmt_metric(evaluated)}",
            f"  Rejected candidates today: {_fmt_metric(rejected_today)}",
            f"  Signals published today: {_fmt_metric(published)}",
        ]

    def _rejected_candidates_today_count(self) -> int | None:
        """Reuses the EXISTING talonx:quant:rejected audit trail
        (AuditStore.rejected_candidates_between, already populated by
        talonx_dispatch.consumer's existing subscription to that
        channel -- see its own docstring) rather than standing up a
        second competing counter. None only if the query itself fails
        (e.g. the audit DB is unavailable) -- never a fabricated 0."""
        try:
            now = datetime.now(timezone.utc)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            return len(self.store.rejected_candidates_between(start, end))
        except Exception as exc:  # noqa: BLE001 -- a health-check read must never raise
            logger.warning("Rejected-candidate count query failed: %s", exc)
            return None

    async def _brain_section(self, client) -> list[str]:
        received = await _get_metric(client, "brain", "received")
        return [
            "\U0001F9E9 BRAIN",
            f"  Quant signals received today: {_fmt_metric(received)}",
            "  Reports generated today: unknown (brain's own report counter is in-process only, "
            "not published to a Redis metric another module can read)",
        ]

    async def _core_section(self, client) -> list[str]:
        actionable = await _sum_metrics(client, "core", ["action_bullish", "action_bearish", "action_contradicted"])
        return [
            "\U0001F52C CORE",
            "  Research reports received today: unknown (core's 'correlated' counter includes both "
            "signals and reports combined, not reports alone)",
            f"  Actionable alerts today: {_fmt_metric(actionable)}",
        ]

    async def _dispatch_section(self, client) -> list[str]:
        received = await _get_metric(client, "dispatch", "received")
        suppressed = await _sum_metrics(client, "dispatch", ["muted_contradictions", "muted_confidence", "muted_cooldown"])
        pushed = await _get_metric(client, "dispatch", "pushed_telegram")
        return [
            "\U0001F4EC DISPATCH",
            f"  Alerts received today: {_fmt_metric(received)}",
            f"  Suppressed today: {_fmt_metric(suppressed)}",
            f"  Telegram pushed today: {_fmt_metric(pushed)}",
        ]

    def _session_section(self) -> list[str]:
        now_utc = datetime.now(timezone.utc)
        us_session = _us_session(now_utc)
        uk_now = now_utc.astimezone(_UK_TZ)
        return [
            "\U0001F5D3️ SESSION",
            f"  US market session: {us_session}",
            f"  UK time: {uk_now.strftime('%H:%M:%S %Z')}",
            f"  Regular session: {'yes' if us_session == 'regular' else 'no'}",
        ]

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
