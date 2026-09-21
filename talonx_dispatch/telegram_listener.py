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
import os
import re
from datetime import datetime, time, timedelta, timezone
from typing import Any, AsyncContextManager, Callable
from zoneinfo import ZoneInfo

import psutil
from telegram import Bot, Update
from telegram.constants import ParseMode
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


def _fmt_seconds(value: float | None) -> str:
    """Task 132: renders an elapsed/age seconds figure as e.g. '2h14m' or
    '37s' -- "unknown" (never "0s") if the value itself is unavailable."""
    if value is None:
        return "unknown"
    value = int(value)
    if value < 60:
        return f"{value}s"
    minutes, seconds = divmod(value, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _cap_message(text: str, budget: int) -> str:
    """Task 132: deterministic last-resort truncation to a hard size
    budget -- used only as a safety net once a message has already been
    split in two; under normal conditions neither half comes close to
    this. A truncated message is labelled as such, never silently cut."""
    if len(text) <= budget:
        return text
    marker = "\n… (truncated to fit Telegram's message-size limit)"
    return text[: budget - len(marker)] + marker


def _env_truthy(name: str) -> bool:
    """Task 132: each module in this project re-declares its own tiny env
    helper rather than sharing one (see the module docstring's note on
    _incr_metric) -- this one matches talonx_ingest.intelligence.service.
    config's own ``_env_bool`` truthy set exactly (also mirrored by
    talonx_ops/dashboard_read.py's own admission_policy block), so a
    value this process itself loaded via python-dotenv reads the same
    way the Intelligence/V2 processes that actually consume it do."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")

logger = logging.getLogger("talonx_dispatch.telegram_listener")

# Accepts a bare number ("47"), "#47", "/details 47", "/id 47" (intraday),
# or the same shapes prefixed with "LT" ("LT47", "#LT47") for a long-term
# alert. Group 1 captures the optional "LT" marker, group 2 the digits.
_ID_PATTERN = re.compile(r"^/?(?:details|id)?\s*#?(LT)?(\d+)$", re.IGNORECASE)

BotFactory = Callable[..., AsyncContextManager[Bot]]


def _default_bot_factory(*, token: str) -> Bot:
    """The single production construction boundary for inbound Telegram bots.

    Keeping this as a callable (rather than storing ``Bot`` on listener
    construction) lets tests inject their factory explicitly without any
    dependency on module-global patch timing.  Calling it is intentionally
    deferred until a configured listener actually starts polling.
    """
    return Bot(token=token)


class TelegramReplyListener:
    def __init__(
        self,
        store: AuditStore,
        config: DispatchConfig | None = None,
        telegram_client: TelegramClient | None = None,
        dispatch_agent=None,
        poll_telemetry=None,
        bot_factory: BotFactory | None = None,
        extra_resolvers=None,
        message_resolvers=None,
        primary_only: bool = False,
    ):
        self.store = store
        self.primary_only = primary_only
        self.config = config or DispatchConfig()
        # Task 99A additive hook: ordered list of callables `str -> str | None`.
        # Each is tried (before the numeric alert-ID path) against an inbound
        # message's text; the first to return a non-None string has that string
        # replied and handling stops. The Original application passes none, so
        # this list is empty and the existing behaviour is byte-identical.
        self.extra_resolvers = list(extra_resolvers or [])
        # Task 138 Workstream 3: ordered list of callables `Message -> str |
        # None`, tried BEFORE `extra_resolvers` -- receives the FULL inbound
        # `python-telegram-bot` ``Message`` object (not just its text), so a
        # resolver can read ``message.reply_to_message.message_id`` for true
        # message-ID correlation (a plain text-only resolver cannot). Same
        # additive posture: empty by default, byte-identical when unused.
        self.message_resolvers = list(message_resolvers or [])
        self.telegram_client = telegram_client or TelegramClient(self.config)
        # Optional -- see module docstring. Gives /ping access to
        # DispatchAgent.started_at (uptime) and its live Redis client (WS
        # heartbeat lookup) without a hard constructor dependency.
        self.dispatch_agent = dispatch_agent
        # Optional boundary hook.  The general/Original application does
        # not pass one, so its listener path remains a no-op.  PIV passes a
        # session-bound recorder and therefore cannot create a second
        # listener merely for measurement.
        self.poll_telemetry = poll_telemetry
        # This is the only inbound Bot construction boundary. Tests inject an
        # explicit factory; production receives the deferred default wrapper.
        # Neither path constructs or captures a Bot instance here.
        self._bot_factory: BotFactory | Any = (
            bot_factory if bot_factory is not None else _default_bot_factory
        )
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

        if self.poll_telemetry is not None:
            self.poll_telemetry.poller_started()

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
        bot_context = self._make_bot_context()
        async with bot_context as bot:
            offset = await self._drain_backlog(bot)
            logger.info("Telegram reply listener polling (poll timeout %.0fs)", self.config.telegram_poll_timeout_seconds)

            while not self._stop_event.is_set():
                try:
                    updates = await self._instrumented_get_updates(
                        bot,
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

    def _make_bot_context(self) -> AsyncContextManager[Bot]:
        """Validate and invoke the configured Bot factory immediately before polling."""
        factory = self._bot_factory
        if not callable(factory):
            raise TypeError("Telegram bot_factory must be callable")
        context = factory(token=self.config.telegram_bot_token)
        if not callable(getattr(context, "__aenter__", None)) or not callable(
            getattr(context, "__aexit__", None)
        ):
            raise TypeError("Telegram bot_factory must return an async context manager")
        return context

    async def _drain_backlog(self, bot: Bot) -> int | None:
        updates = await self._instrumented_get_updates(
            bot, timeout=0, allowed_updates=["message"],
        )
        if not updates:
            return None
        drained = updates[-1].update_id + 1
        logger.info("Drained %d pending Telegram update(s) on startup without replying", len(updates))
        return drained

    async def _instrumented_get_updates(self, bot: Bot, **kwargs):
        """Record the real request boundary, never a helper-only proxy.

        The attempt is durably recorded before network I/O.  If that write
        fails, the request is not made, preventing a stale verified-zero
        record from coexisting with an unrecorded Telegram attempt.
        """
        if self.poll_telemetry is not None:
            self.poll_telemetry.before_get_updates()
        try:
            updates = await bot.get_updates(**kwargs)
        except Exception:
            if self.poll_telemetry is not None:
                self.poll_telemetry.get_updates_failed()
            raise
        if self.poll_telemetry is not None:
            self.poll_telemetry.get_updates_succeeded()
        return updates

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

        for resolver in self.message_resolvers:
            try:
                reply = resolver(message)
            except Exception:  # noqa: BLE001 -- a broken resolver must never kill the poller
                logger.exception("message reply resolver raised; ignoring")
                continue
            if reply is not None:
                # plain=True (parse_mode=None): a message_resolvers reply can
                # carry arbitrary, uncontrolled SEC-sourced text (company
                # names, filing text, URLs) that is NOT guaranteed
                # Markdown-safe -- sending it under MARKDOWN parse mode risks
                # a Telegram "can't parse entities" send failure on a stray
                # unescaped _ / * / ` / [ character. See
                # talonx_ingest.intelligence.delivery.reply_correlation's own
                # module docstring for the matching rationale on its side
                # (it already strips HTML for the same reason).
                await self._reply(reply, plain=True)
                return

        if self.primary_only:
            # RI-3: primary commands/Intelligence correlation remain available;
            # historical Original/Experimental IDs cannot leak Research output.
            await self._reply("Research/Original details are available in the dashboard. Use /ping for status.", plain=True)
            return

        for resolver in self.extra_resolvers:
            try:
                reply = resolver(message.text)
            except Exception:  # noqa: BLE001 -- a broken resolver must never kill the poller
                logger.exception("extra reply resolver raised; ignoring")
                continue
            if reply is not None:
                await self._reply(reply)
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
        never a fabricated zero.

        2026-08-18 live-incident correctness fixes:
          - Sent via _reply(..., plain=True) (parse_mode=None) -- this
            message embeds dynamic content (the session-state label, e.g.
            'pre_market') that is NOT guaranteed Markdown-safe; sending it
            through Markdown parsing previously made Telegram reject the
            ENTIRE reply with a 400 whenever that content contained an
            unescaped `_`/`*`/`` ` ``/`[` (confirmed live, byte-for-byte
            reproducible). Formatted alert pushes/alert-detail replies are
            unaffected -- their content is already Markdown-escaped.
          - "Server Status: Active / Healthy" (a hardcoded string, true
            only of the PROCESS, not the pipeline) is replaced by two
            separate, honestly-derived lines: Process (this handler ran,
            so the process is definitionally running) and Pipeline
            (derived from the SAME market-feed-freshness signal the
            MARKET section below already computes -- not a new metric).
          - Metrics day is now stated explicitly as UTC -- every counter
            below reads a `metrics:{YYYY-MM-DD}:...` key keyed on UTC
            calendar date (see _get_metric), which silently disagrees with
            "today" in UK-local time for about an hour after UTC midnight
            (00:00-01:00 BST) each day."""
        cpu_pct = self._process.cpu_percent(interval=None)
        mem_used_gb = self._process.memory_info().rss / (1024 ** 3)
        mem_total_gb = psutil.virtual_memory().total / (1024 ** 3)
        total_today, pushed_today = self.store.count_alerts_today()
        client = getattr(self.dispatch_agent, "_client", None)
        _, market_health = await self._market_feed_freshness(client)

        # 2026-08-25 live-incident clarification (Task 69P): the MARKET/
        # Pipeline lines below read talonx_ingest's OWN Redis WS-heartbeat
        # and metrics:{date}:ingest:* keys -- a PIV session's SessionRunner
        # never writes to them (it calls Alpaca's REST bars/latest directly,
        # bypassing talonx_ingest entirely), so they correctly show "no
        # data" from THAT subsystem's point of view even while PIV's own
        # live feed (see the PIV block above) is healthy. Confirmed live:
        # independently querying the same bars/latest endpoint PIV uses
        # showed fresh (<=120s old) bars for the large majority of the
        # universe while /ping showed "DEGRADED"/"Disconnected" -- not
        # false data, but a whole-system-health claim from a
        # single-subsystem-scoped signal. This suffix is additive/opt-in
        # (piv_info is None for the general app) -- no existing behavior
        # changes for run_talonx.py's own DispatchAgent.
        piv_info = getattr(self.dispatch_agent, "piv_info", None)
        pipeline_suffix = (
            " [scoped to the general ingest pipeline, NOT used by this PIV session -- see PIV block below for the actual live feed status]"
            if piv_info is not None else ""
        )
        market_lines = await self._market_section(client)
        if piv_info is not None and market_lines:
            market_lines[0] = f"{market_lines[0]}  [see note above Pipeline: this section is scoped to the general ingest pipeline, not used by PIV]"

        lines = [
            "\U0001F3D3 Pong! TalonX Engine Online",
            "─" * 30,
            "\U00002699 Process: RUNNING",
            f"\U0001F4E1 Pipeline: {self._pipeline_status(client, market_health, piv_info)}{pipeline_suffix}",
            f"\U0001F4C5 Metrics day: {datetime.now(timezone.utc):%Y-%m-%d} (UTC)",
            f"⏱️ Uptime: {self._format_uptime()}",
            f"\U0001F4BB CPU Usage: {cpu_pct:.1f}%  |  RAM: {mem_used_gb:.1f} GB / {mem_total_gb:.1f} GB",
            f"\U0001F4CA Today's Signals Pushed (UTC day): {pushed_today} Pushes ({total_today} Logs)",
            "",
            *self._piv_section(),
            *market_lines,
            "",
            *await self._quant_section(client),
            "",
            *await self._signal_lifecycle_section(client),
            "",
            *self._session_section(),
        ]
        discovery_lines = self._discovery_v2_section()
        await self._send_ping_reply(lines, discovery_lines)

    async def _send_ping_reply(self, lines: list[str], discovery_lines: list[str]) -> None:
        """Task 132 section 5: appends the new DISCOVERY/V2/DELIVERY block
        to the existing /ping reply, splitting into a second message only
        if needed to respect Telegram's size limit -- reusing the delivery
        pipeline's OWN existing size-budget constant (Task 96F,
        talonx_ingest.intelligence.delivery.config) rather than inventing a
        second, competing size policy. Each half is ALSO independently
        capped at that same budget (deterministic truncation, never a
        silently-oversized message that Telegram's API would reject
        outright with a 400) -- the combined-length check alone is not
        sufficient once split, since either half could still exceed the
        budget on its own."""
        from talonx_ingest.intelligence.delivery.config import MESSAGE_BUDGET

        combined = "\n".join([*lines, "", *discovery_lines])
        if len(combined) <= MESSAGE_BUDGET:
            await self._reply(combined, plain=True)
            return
        await self._reply(_cap_message("\n".join(lines), MESSAGE_BUDGET), plain=True)
        part2 = "\n".join(["\U0001F3D3 Pong! (2/2)", "─" * 30, *discovery_lines])
        await self._reply(_cap_message(part2, MESSAGE_BUDGET), plain=True)

    def _piv_section(self) -> list[str]:
        """Additive, opt-in block for a PAPER PIV-context caller only
        (talonx_piv.telegram_inbound.build_piv_telegram_listener passes a
        `dispatch_agent` shim exposing `piv_info` -- the general
        run_talonx.py DispatchAgent never sets this attribute, so
        `getattr(..., None)` is None there and this returns [] --
        byte-for-byte unchanged /ping output for the general app).
        Exists because none of the fields below (mode, live feed
        provider, configured universe) have any other line anywhere in
        this reply -- everything else here is talonx_ingest/quant/brain/
        core/dispatch-shaped, not PIV-shaped."""
        info = getattr(self.dispatch_agent, "piv_info", None)
        if info is None:
            return []
        lines = [
            "\U0001F9EA PIV",
            f"  Mode: {info.get('mode', 'unknown')}",
            f"  Live feed provider: {info.get('feed_provider', 'unknown')}",
            f"  Configured universe: {info.get('universe_size', 'unknown')}",
        ]
        # Task 69Q Part 8 -- unified PIV /ping view: session identity, live
        # feed/readiness state, the full quant funnel, radar WATCH count,
        # and natural-vs-probe traffic, all read from the SAME mutable dict
        # SessionRunner updates in place (see telegram_inbound.build_piv_info).
        # Only rendered for a PIV caller (info is not None) -- byte-for-byte
        # unchanged output for the general app.
        optional_fields = (
            ("session_id", "Session ID"), ("runtime_sha", "Runtime SHA"), ("config_hash", "Config hash"),
            ("feed_health", "Feed health"),
            ("warmup_ready_count", "Warmup ready"), ("session_ready_count", "Session ready"),
            ("stale_count", "Currently stale"),
            ("quant_evaluation_cycles", "Quant evaluation cycles"), ("quant_candidates", "Quant candidates"),
            ("quant_published", "Quant published"), ("quant_rejected", "Quant rejected"),
            ("quant_unaccounted", "Quant unaccounted candidates"),
            ("radar_watch_count", "Radar WATCH count (observational, not alpha)"),
            ("natural_orders", "Natural orders"), ("natural_fills", "Natural fills"),
            ("probe_orders", "Probe orders (PIV_LIFECYCLE_PROBE, alpha_evidence=false)"),
            ("probe_fills", "Probe fills (PIV_LIFECYCLE_PROBE, alpha_evidence=false)"),
            ("eod_status", "EOD/reconciliation"),
        )
        for key, label in optional_fields:
            if key in info:
                lines.append(f"  {label}: {info[key]}")
        lines.append("")
        return lines

    def _pipeline_status(self, client, market_health: str, piv_info: dict | None = None) -> str:
        """Derived entirely from the market-feed-freshness label
        _market_feed_freshness already computes (healthy/stale/
        disconnected/unknown) -- no new metric, no new Redis read -- UNLESS
        this is a PIV caller (piv_info is not None), in which case the
        headline reflects PIV's OWN live-feed health (SessionRunner-updated
        `feed_health`), never the general talonx_ingest subsystem's, which
        a PIV session never writes to at all (Task69P live finding: /ping
        showed DEGRADED/Disconnected purely because that OTHER subsystem
        was idle, while PIV's actual Alpaca feed was healthy). General-app
        behavior (piv_info is None) is unchanged."""
        if piv_info is not None:
            return piv_info.get("feed_health", "UNKNOWN (PIV feed status pending)")
        if client is None:
            return "UNKNOWN (no Redis connection)"
        # Task 87B FC_03: an "idle" label means the ingest process is
        # provably alive (fresh liveness beat) but the current US session
        # phase legitimately has no ticks to expect -- a post-market /
        # pre-market-thin / weekend quiet, NOT a feed failure.
        if "idle" in market_health:
            return "IDLE (market quiet -- ingest alive, no ticks expected now)"
        if "disconnected" in market_health:
            return "DEGRADED (market feed disconnected)"
        if "stale" in market_health:
            return "DEGRADED (market feed stale)"
        if "unknown" in market_health:
            return "UNKNOWN (market feed status unavailable)"
        return "HEALTHY (market feed active)"

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
        provider_failed = await _get_metric(client, "ingest", "provider_requests_failed")
        provider_retries = await _get_metric(client, "ingest", "provider_retries")
        provider_rate_limited = await _get_metric(client, "ingest", "provider_rate_limited")
        redis_publish_failed = await _get_metric(client, "ingest", "market_redis_publish_failures")
        redis_reconnects = await _get_metric(client, "ingest", "market_redis_reconnect_successes")
        # Task 87B FC_02: the Redis counter can under-count an in-progress
        # incident (its own increment rides the failing transport). The
        # liveness beat carries the transport-INDEPENDENT tally; report
        # whichever is larger so the operator total is never optimistic.
        publish_failed_display = _fmt_metric(redis_publish_failed)
        live, _sent = await self._read_json_key(client, self.config.liveness_key)
        if isinstance(live, dict):
            tc = live.get("transport_counters") or {}
            local_pf = tc.get("publish_failures")
            try:
                redis_pf_int = int(redis_publish_failed) if redis_publish_failed is not None else 0
            except (TypeError, ValueError):
                redis_pf_int = 0
            if isinstance(local_pf, int) and local_pf > redis_pf_int:
                dropped = tc.get("dropped_while_disconnected") or 0
                publish_failed_display = (
                    f"{local_pf} (in-process; {redis_pf_int} flushed to Redis"
                    + (f", {dropped} while disconnected" if dropped else "") + ")"
                )
        return [
            "\U0001F4E1 MARKET",
            f"  Source: {await self._ws_status()}",
            f"  Watchlist size: {self._watchlist_size()}",
            f"  Bars/events received today: {_fmt_metric(bars_read)}",
            f"  Last market event: {last_event_at}",
            f"  Feed status: {health}",
            f"  Provider failures today: {_fmt_metric(provider_failed)}",
            f"  Provider retries today: {_fmt_metric(provider_retries)}",
            f"  Provider rate limits today: {_fmt_metric(provider_rate_limited)}",
            f"  Redis publish failures today: {publish_failed_display}",
            f"  Redis reconnects today: {_fmt_metric(redis_reconnects)}",
        ]

    def _watchlist_size(self) -> str:
        """2026-08-18 EOD fix: DispatchAgent already holds the SAME
        TickerWatchlistStore instance run_talonx.py's main() constructs
        (see DispatchAgent.__init__ and TelegramReplyListener's
        dispatch_agent=self wiring) -- no new store, no new wiring, this
        was simply never read from here before. Counts only ACTIVE symbols
        (list_active_symbols), matching what market data streaming and
        quant preseed actually subscribe to, not paused/inactive rows."""
        watchlist_store = getattr(self.dispatch_agent, "watchlist_store", None)
        if watchlist_store is None:
            return "unknown (no watchlist store available)"
        try:
            return str(len(watchlist_store.list_active_symbols()))
        except Exception as exc:  # noqa: BLE001 -- a health-check read must never raise
            logger.warning("Watchlist size query failed: %s", exc)
            return "unknown (watchlist query failed)"

    async def _market_feed_freshness(self, client) -> tuple[str, str]:
        """(last_event_description, health_label). Task 87B FC_03: when the
        market-INDEPENDENT ingest liveness beat (``talonx:ingest:liveness``,
        written on a timer by talonx_ingest.liveness.LivenessBeacon) is
        present, use a session-aware model so a legitimately quiet market
        (post-close, thin pre-market, weekend) reads as IDLE rather than
        DISCONNECTED, while a dead process/Redis link still reads as
        DISCONNECTED and stale ticks DURING the regular session still read
        as STALE. When the beat is absent (older runtime, or a fixture
        without it), fall back to the pre-FC_03 ws_heartbeat-only
        healthy/stale/disconnected behaviour -- unchanged."""
        state, desc, _reason = await self._market_feed_state(client)
        label = {
            "HEALTHY": "\U0001F7E2 healthy",
            "IDLE": "\U0001F7E2 idle",
            "STALE": "\U0001F7E1 stale",
            "DISCONNECTED": "\U0001F534 disconnected",
            "UNKNOWN": "\U0001F7E1 unknown",
        }.get(state, "\U0001F7E1 unknown")
        return desc, label

    async def _read_json_key(self, client, key: str) -> tuple[dict | None, str | None]:
        """(parsed_dict, sentinel). sentinel is 'missing' / 'error' /
        'malformed' when parsed_dict is None, else None."""
        try:
            raw = await client.get(key)
        except Exception as exc:  # noqa: BLE001 -- a status-check read must never break /ping
            logger.warning("Health key lookup failed for %s: %s", key, exc)
            return None, "error"
        if raw is None:
            return None, "missing"
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None, "malformed"
        return (data if isinstance(data, dict) else None), (None if isinstance(data, dict) else "malformed")

    async def _market_feed_state(self, client) -> tuple[str, str, str]:
        """Machine-readable feed state -> (STATE, last_event_desc, reason).

        STATE is one of HEALTHY / IDLE / STALE / DISCONNECTED / UNKNOWN.
        Historical Redis reconnect/failure counters are deliberately NOT an
        input here (they are informational only, printed elsewhere)."""
        if client is None:
            return "UNKNOWN", "unknown (no Redis connection)", "no Redis connection"

        now = datetime.now(timezone.utc)
        hb, hb_sentinel = await self._read_json_key(client, self.config.ws_heartbeat_key)
        hb_age: float | None = None
        hb_updated: datetime | None = None
        if hb is not None:
            try:
                hb_updated = datetime.fromisoformat(hb.get("updated_at"))
                hb_age = (now - hb_updated).total_seconds()
            except (TypeError, ValueError):
                hb_age = None
        last_event_desc = (
            f"{hb_age:.0f}s ago ({hb_updated.strftime('%H:%M:%S')} UTC)"
            if hb_age is not None and hb_updated is not None
            else {"missing": "unknown (no heartbeat)", "error": "unknown",
                  "malformed": "unknown (malformed heartbeat)"}.get(hb_sentinel or "", "unknown")
        )

        live, live_sentinel = await self._read_json_key(client, self.config.liveness_key)

        # ---- legacy fallback: no liveness beacon in play (unchanged) ----
        if live is None:
            if hb is None:
                return "DISCONNECTED", "unknown (no heartbeat)", f"ws_heartbeat {hb_sentinel}"
            if hb_age is None:
                return "UNKNOWN", last_event_desc, "ws_heartbeat has no usable timestamp"
            if hb_age < self.config.market_feed_fresh_seconds:
                return "HEALTHY", last_event_desc, "recent market event"
            return "STALE", last_event_desc, f"no market event for {hb_age:.0f}s (no liveness beacon)"

        # ---- FC_03 session-aware model (liveness beat present) ----
        try:
            live_updated = datetime.fromisoformat(live.get("updated_at"))
            live_age = (now - live_updated).total_seconds()
        except (TypeError, ValueError):
            live_age = None
        redis_reachable = bool(live.get("redis_reachable", True))
        phase = live.get("session_phase") or "unknown"

        if live_age is None or live_age > self.config.liveness_stale_seconds or not redis_reachable:
            why = (
                "liveness beat has no timestamp" if live_age is None
                else f"liveness beat {live_age:.0f}s old (> {self.config.liveness_stale_seconds:.0f}s)"
                if live_age > self.config.liveness_stale_seconds
                else "liveness beat reports redis unreachable"
            )
            return "DISCONNECTED", last_event_desc, why

        # process + redis provably alive from here on.
        beat_age = live.get("last_market_event_age_seconds")
        event_age = hb_age if hb_age is not None else (float(beat_age) if beat_age is not None else None)
        if event_age is not None and event_age < self.config.market_feed_fresh_seconds:
            return "HEALTHY", last_event_desc, f"market event {event_age:.0f}s ago"
        if phase == "regular":
            return "STALE", last_event_desc, (
                f"no market event for {event_age:.0f}s during the regular session"
                if event_age is not None else "no market event during the regular session"
            )
        return "IDLE", last_event_desc, f"ingest alive; market phase '{phase}' -- no ticks expected"

    # Fixed display order for the candidate-stage breakdown, matching the
    # gate pipeline's actual sequence in talonx_quant/consumer.py -- shown
    # every time (even at a genuine 0) since these are the strategy's
    # named, expected gates, not incidental noise. Any OTHER reason
    # actually found in the audit trail today (e.g. GLOBAL_RISK_DEGRADED,
    # UK_SESSION_CLOSED, THROTTLE, NEWS_CATALYST,
    # RISK_STORE_UNAVAILABLE_FAIL_CLOSED) is appended afterward, but only
    # if nonzero -- keeps /ping deterministic and readable while still
    # surfacing genuinely unexpected activity rather than silently hiding it.
    _CANDIDATE_REJECTION_DISPLAY_ORDER = (
        "LOW_CONFLUENCE", "LOW_RISK_REWARD", "OPENING_BLACKOUT", "CLOSING_BLACKOUT",
        "PREMARKET_PROVIDER_UNSUPPORTED", "PREMARKET_LIQUIDITY", "TREND_GATE",
        "LOSS_LOCKOUT", "COOLDOWN", "HTF_DATA_UNAVAILABLE", "US_MARKET_SESSION_CLOSED",
    )

    async def _quant_section(self, client) -> list[str]:
        evaluated = await _get_metric(client, "quant", "evaluated")
        published = await _get_metric(client, "quant", "published")
        # Task 135: "published" only ever meant "Redis accepted the PUBLISH
        # command" -- never "a subscriber received it" (fire-and-forget
        # Pub/Sub has no queue/ACK/redelivery). published_no_subscriber
        # (talonx_quant/consumer.py::_publish_signal) is the new, explicit
        # counter for the exact gap a published-vs-Brain-received mismatch
        # otherwise leaves silent -- shown only when there's a real,
        # measured count to report (never fabricated if the key is simply
        # absent because no signal has published yet today).
        published_no_sub = await _get_metric(client, "quant", "published_no_subscriber")
        bar_level, candidate_breakdown = self._quant_rejection_breakdown_today()

        lines = [
            "\U0001F9E0 QUANT",
            "  Volatility-stage:",
            f"    LOW_VOLATILITY: {_fmt_metric(bar_level)}",
            "",
            f"  Candidates generated today: {_fmt_metric(evaluated)}",
            "  Candidate-stage:",
        ]
        if candidate_breakdown is None:
            lines.append("    unknown (audit trail query failed)")
        else:
            for reason in self._CANDIDATE_REJECTION_DISPLAY_ORDER:
                lines.append(f"    {reason}: {candidate_breakdown.get(reason, 0):,}")
            extra_reasons = sorted(
                (r for r in candidate_breakdown if r not in self._CANDIDATE_REJECTION_DISPLAY_ORDER and candidate_breakdown[r] > 0),
                key=lambda r: candidate_breakdown[r], reverse=True,
            )
            for reason in extra_reasons:
                lines.append(f"    {reason}: {candidate_breakdown[reason]:,}")
        lines.append(f"  Signals published today: {_fmt_metric(published)}")
        if published_no_sub is not None and published_no_sub > 0:
            lines.append(
                f"    WARNING: {published_no_sub} of those had ZERO Redis subscribers "
                f"at publish time -- likely never reached Brain"
            )
        return lines

    def _quant_rejection_breakdown_today(self) -> tuple[int | None, dict[str, int] | None]:
        """Reuses the EXISTING talonx:quant:rejected audit trail
        (AuditStore.rejected_candidates_between, already populated by
        talonx_dispatch.consumer's existing subscription to that channel --
        see its own docstring) rather than standing up a second competing
        set of Redis counters -- EVERY rejection reason in
        talonx_quant/consumer.py already calls self._record_rejection(...),
        so this table already has complete, authoritative per-reason data
        (including COOLDOWN and THROTTLE, neither of which has a dedicated
        Redis counter at all). Returns (bar_level_count, {reason: count})
        -- LOW_VOLATILITY is split out as the bar-level count (rejected
        before any candidate signal exists), everything else keyed by its
        real reason string for the candidate-stage breakdown. (None, None)
        only if the query itself fails (e.g. the audit DB is unavailable)
        -- never a fabricated 0/empty dict."""
        try:
            now = datetime.now(timezone.utc)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            rows = self.store.rejected_candidates_between(start, end)
        except Exception as exc:  # noqa: BLE001 -- a health-check read must never raise
            logger.warning("Rejected-candidate breakdown query failed: %s", exc)
            return None, None
        bar_level = 0
        candidate_breakdown: dict[str, int] = {}
        for row in rows:
            reason = row.get("reason")
            if reason == "LOW_VOLATILITY":
                bar_level += 1
            elif reason:
                candidate_breakdown[reason] = candidate_breakdown.get(reason, 0) + 1
        return bar_level, candidate_breakdown

    async def _signal_lifecycle_section(self, client) -> list[str]:
        """2026-08-18 /ping observability completion: replaces the previous
        separate BRAIN/CORE/DISPATCH sections with one unified funnel,
        QUANT published -> ... -> Telegram pushed, so /ping directly answers
        "where do published signals go" instead of requiring three section
        headers to be mentally stitched together. Every counter here reads
        an existing or newly-added `metrics:{date}:{stage}:{counter}` key --
        brain_received/reports_generated (talonx_brain/consumer.py),
        core_signals_received/reports_received/action_bullish/
        action_bearish/action_contradicted (talonx_core/consumer.py),
        dispatch_received/muted_*/pushed_telegram (talonx_dispatch/
        consumer.py) -- none of these are new invented semantics, only
        reports_generated/signals_received/reports_received are genuinely
        new counters (see their own docstrings for why brain_llm_calls
        specifically must NOT be used as a reports_generated proxy)."""
        published = await _get_metric(client, "quant", "published")
        brain_received = await _get_metric(client, "brain", "received")
        brain_reports = await _get_metric(client, "brain", "reports_generated")
        core_signals = await _get_metric(client, "core", "signals_received")
        core_reports = await _get_metric(client, "core", "reports_received")
        # action_contradicted is quant/brain DISAGREEING -- the opposite of
        # actionable, not a third kind of actionable alert. Reported
        # separately so "Core actionable" only ever counts bullish/bearish
        # (the two outcomes that actually reach dispatch as an
        # ActionableAlert -- see talonx_core/consumer.py).
        core_actionable = await _sum_metrics(client, "core", ["action_bullish", "action_bearish"])
        core_contradicted = await _get_metric(client, "core", "action_contradicted")
        dispatch_received = await _get_metric(client, "dispatch", "received")
        dispatch_suppressed = await _sum_metrics(
            client, "dispatch", ["muted_contradictions", "muted_confidence", "muted_cooldown"]
        )
        telegram_pushed = await _get_metric(client, "dispatch", "pushed_telegram")

        lines = [
            "\U0001F504 SIGNAL LIFECYCLE",
            f"  Quant published: {_fmt_metric(published)}",
            f"  Brain received: {_fmt_metric(brain_received)}",
            f"  Brain reports generated: {_fmt_metric(brain_reports)}",
            f"  Core signals received: {_fmt_metric(core_signals)}",
            f"  Core reports received: {_fmt_metric(core_reports)}",
            f"  Core actionable: {_fmt_metric(core_actionable)} (bullish + bearish)",
            f"  Core contradicted: {_fmt_metric(core_contradicted)}",
            f"  Dispatch received: {_fmt_metric(dispatch_received)}",
            f"  Dispatch suppressed: {_fmt_metric(dispatch_suppressed)}",
            f"  Telegram pushed: {_fmt_metric(telegram_pushed)}",
        ]
        telegram_failed = self._telegram_send_failures_since_process_start()
        if telegram_failed is not None:
            lines.append(f"  Telegram send failures (since process start): {telegram_failed:,}")
        return lines

    def _telegram_send_failures_since_process_start(self) -> int | None:
        """DispatchAgent already tracks this in-process (self._telegram_failed
        / self._long_term_telegram_failed, incremented in
        _maybe_send_telegram/_maybe_send_long_term_telegram's TelegramSendError
        handlers) -- trivially readable via the SAME dispatch_agent reference
        /ping already uses for uptime/watchlist, no new counter needed. Unlike
        every other figure in this reply, this is scoped to the CURRENT
        process's uptime, not the UTC calendar day (it isn't a
        `metrics:{date}:...` Redis key) -- labeled accordingly at the call
        site rather than silently implying it's a daily total. None only if
        dispatch_agent itself isn't wired up (no live process to read from)."""
        if self.dispatch_agent is None:
            return None
        failed = getattr(self.dispatch_agent, "telegram_failed", None)
        long_term_failed = getattr(self.dispatch_agent, "long_term_telegram_failed", None)
        if failed is None or long_term_failed is None:
            return None
        return failed + long_term_failed

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

    def _discovery_v2_section(self) -> list[str]:
        """Task 132 section 5: DISCOVERY / V2 / DELIVERY -- additive, reads
        ONLY already-existing files/snapshots the Intelligence service and
        V2 companion write themselves (their own heartbeat/progress/status
        JSON, plus bounded COUNT/MAX queries against the shared, read-only-
        opened ``ingestion_ledger.db``). Never opens a second writer, never
        scans filing content, never touches a live trading decision. Every
        field follows this file's own convention: unavailable/never-yet-
        measured is the literal string "unknown" (or an explicit "not yet"
        phrase), NEVER a fabricated 0 -- an old event/filing time alone must
        not read as "unhealthy poller", and process uptime must not stand
        in for ingestion progress (see TASK132_EXPANDED_DISCOVERY_DEV_RUN.md
        for why: a still-running FIRST cycle over a 9x-expanded scope can
        look silent from any per-cycle-only signal for hours)."""
        lines: list[str] = []

        # -- DISCOVERY: heartbeat (scope, last completed upstream poll) +
        #    progress (in-flight cycle state, added this task) -----------
        lines.append("\U0001F50E DISCOVERY")
        heartbeat, hb_age_s = self._read_json_with_age(self._intel_heartbeat_path())
        progress, prog_age_s = self._read_json_with_age(self._intel_progress_path())
        if heartbeat is None:
            lines.append("  scope/poll status: unknown (heartbeat file unavailable)")
        else:
            scope = heartbeat.get("scope") or {}
            effective_n = len(heartbeat.get("effective_symbols") or [])
            lines.append(
                f"  Collection scope: {scope.get('effective', 'unknown')} watchlist"
                f" -> {effective_n or 'unknown'} effective (broad-discovery-inclusive)"
            )
            last_poll = (heartbeat.get("metrics") or {}).get("source", {}).get("last_successful_poll_utc")
            lines.append(
                "  Last completed upstream poll: "
                + (last_poll if last_poll else "none yet (first cycle still in progress)")
            )
        if progress is None:
            lines.append("  Current cycle: unknown (no progress snapshot written yet)")
        else:
            phase = progress.get("phase", "unknown")
            complete = progress.get("cycle_complete")
            elapsed = progress.get("elapsed_seconds")
            state_label = "COMPLETE" if complete else f"IN PROGRESS ({phase})"
            lines.append(f"  Current cycle: {state_label}, elapsed {_fmt_seconds(elapsed)}")
            sd, st = progress.get("symbols_done"), progress.get("symbols_total")
            if sd is not None and st is not None:
                lines.append(f"  Issuers polled: {sd}/{st} (as of {_fmt_seconds(prog_age_s)} ago)")
            ed, et = progress.get("events_done"), progress.get("events_total")
            if ed is not None and et is not None:
                lines.append(f"  New filings enriched: {ed:,}/{et:,} (same snapshot)")
        events_today = self._intel_bounded_counts()
        lines.append(
            "  New filing events persisted (today, UTC): "
            + (f"{events_today:,}" if events_today is not None else "unknown")
        )
        if events_today is None:
            lines.append("  (ledger DB unavailable for this reading -- not a claim of zero activity)")

        # -- V2: the companion's own status file (Task 112/113/114) -------
        lines.append("")
        lines.append("\U0001F4C8 V2")
        v2, v2_age_s = self._read_json_with_age(self._v2_status_path())
        if v2 is None:
            lines.append("  status: unknown (v2_service_status.json unavailable)")
        else:
            exec_scope = v2.get("execution_scope_count", "unknown")
            lines.append(f"  Execution-eligible scope: {exec_scope}")
            last_tick = v2.get("last_tick_utc", "unknown")
            lines.append(f"  Last successful tick: {last_tick} (snapshot read {_fmt_seconds(v2_age_s)} ago)")
            # FINAL ACCEPTANCE: release state, read ONLY from the companion's own status file (never a claim
            # the file does not support).  The stale csv default is labelled as NOT release-grade.
            rel = v2.get("release_mode")
            lines.append("  Release mode: " + ("ON" if rel is True else "OFF" if rel is False else "unknown"))
            pcs = v2.get("price_provider_contract")
            if isinstance(pcs, dict) and pcs.get("release_contract_active"):
                lines.append(f"  Price provider: {pcs.get('provider')} {str(pcs.get('feed')).upper()} "
                             f"adjustment={pcs.get('adjustment')} | {pcs.get('contract_id')} "
                             f"({pcs.get('contract_fingerprint')}) | fallback={pcs.get('fallback_mode')}")
            elif isinstance(pcs, dict):
                lines.append(f"  Price provider: NOT the release contract (pricing mode "
                             f"{pcs.get('mode', 'unknown')}) -- not release-grade")
            else:
                lines.append("  Price provider: unknown")
            unavailable = v2.get("pricing_unavailable_recent")
            lines.append("  Market-data health: " + (
                "unknown" if unavailable is None else
                ("OK (no recent unavailability)" if not unavailable else f"DEGRADED ({len(unavailable)} recent unavailable)")))
            lines.append(f"  Campaign: {v2.get('campaign_id', 'unknown')} ({v2.get('execution_mode', 'unknown')}), "
                         f"cash {v2.get('cash', 'unknown')}")
            blocks = v2.get("account_blocks_active")
            lines.append("  Account blocks: " + ("unknown" if blocks is None else ("none" if not blocks else ", ".join(blocks))))
            unresolved = v2.get("exit_unresolved")
            lines.append("  EXIT_UNRESOLVED: " + ("unknown" if unresolved is None else str(len(unresolved))))
            rejects = {
                "out_of_scope": v2.get("execution_scope_out_of_scope_dropped_this_tick"),
                "stale_entry": v2.get("stale_entry_skipped_this_tick"),
                "no_prior_intent": v2.get("no_prior_intent_skipped_this_tick"),
                "capacity": v2.get("capacity_rejected_this_tick"),
                "admission_deadline": v2.get("admission_deadline_rejected_this_tick"),
            }
            leading = sorted(
                ((k, n) for k, n in rejects.items() if isinstance(n, int) and n > 0),
                key=lambda kv: kv[1], reverse=True,
            )
            ripe = v2.get("ripe_episodes_this_tick", "unknown")
            lines.append(f"  Candidates evaluated (last tick): {ripe}")
            if leading:
                lines.append("  Leading rejection reasons (last tick): " + ", ".join(f"{k}={n}" for k, n in leading))
            pending_intents = v2.get("pending_entry_intents")
            lines.append(f"  Pending intents: {len(pending_intents) if pending_intents is not None else 'unknown'}")
            open_pos = v2.get("open_positions")
            lines.append(f"  Open positions: {open_pos if open_pos is not None else 'unknown'}")
            lines.append(
                f"  Entries/exits (last tick): {v2.get('entries_this_tick', 'unknown')}"
                f"/{v2.get('exits_this_tick', 'unknown')}"
            )
            # Task 140: prefer the REAL companion's own same-process value
            # (v2_service_status.json's "durable_store_gate_enabled",
            # written by the actual V2Service instance at the moment it
            # read TALONX_V2_DURABLE_STORE_ENABLED) over re-deriving the
            # env var HERE, in Original's own separate process -- Original
            # and the V2 companion are spawned independently and can, in
            # principle, see different merged environments (the exact
            # class of gap already found twice tonight for broad-discovery
            # and delivery-enablement). Falls back to the old env-derived
            # reading only for a status file predating this field.
            if "durable_store_gate_enabled" in v2:
                gated = bool(v2["durable_store_gate_enabled"])
                admission_mode = "GATED" if gated else "PERMISSIVE"
                lines.append(f"  Admission mode: {admission_mode} (source: live companion)")
            else:
                admission_mode = "GATED" if _env_truthy("TALONX_V2_DURABLE_STORE_ENABLED") else "PERMISSIVE"
                lines.append(f"  Admission mode: {admission_mode} (source: this process's own env -- "
                             f"status file predates durable_store_gate_enabled, unverified against the "
                             f"actual companion)")

        # -- DELIVERY: discovery informational outbox (ingestion_ledger.db)
        #    + V2 actionable outbox (already in v2_service_status.json) ---
        lines.append("")
        lines.append("\U0001F4EC DELIVERY")
        counts, last_sent = self._intel_delivery_counts()
        if counts is None:
            lines.append("  Discovery informational queue: unknown (ledger DB unavailable)")
        else:
            lines.append(
                "  Discovery informational queue -- pending: {p}, sent: {s}, "
                "expired/held: {e}, failed: {f}".format(
                    p=counts.get("PENDING", 0), s=counts.get("SENT", 0),
                    e=counts.get("EXPIRED", 0), f=counts.get("FAILED", 0),
                )
            )
            lines.append(
                "  Last successful discovery delivery: " + (last_sent if last_sent else "none in retained history")
            )
        if v2 is not None:
            ao = v2.get("alert_outbox") or {}
            lines.append(
                f"  V2 actionable outbox -- total: {ao.get('total', 'unknown')}, "
                f"by state: {ao.get('by_state') if ao.get('by_state') else '{}'}"
            )
        return lines

    @staticmethod
    def _intel_heartbeat_path():
        from talonx_ingest.intelligence.service.config import ServiceConfig
        return ServiceConfig().heartbeat_path()

    @staticmethod
    def _intel_progress_path():
        from talonx_ingest.intelligence.service.config import ServiceConfig
        return ServiceConfig().progress_path()

    @staticmethod
    def _v2_status_path():
        from talonx_ops.prospective.paths import V2_STATUS_PATH
        return V2_STATUS_PATH

    @staticmethod
    def _read_json_with_age(path) -> tuple[dict | None, float | None]:
        """Bounded, best-effort read of a small local JSON snapshot file.
        Never raises -- (None, None) means "unavailable", never a fabricated
        empty/zero reading."""
        try:
            if not path.is_file():
                return None, None
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            age_s = max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
            return data, age_s
        except Exception as exc:  # noqa: BLE001 -- a status-check read must never raise
            logger.warning("Discovery/V2 snapshot read failed for %s: %s", path, exc)
            return None, None

    @staticmethod
    def _intel_ledger_path():
        from talonx_ingest.config import settings
        return settings.ledger.path

    def _intel_bounded_counts(self) -> int | None:
        """Single bounded COUNT query against the shared, read-only-opened
        ingestion ledger -- new filing-text events persisted today (UTC),
        the SAME per-UTC-day windowing convention every other /ping counter
        in this file already uses (see _quant_section's "today"). A cheap
        indexed-enough scan of a table in the tens of thousands of rows,
        not a bulk content scan. None on any failure -- never a fabricated
        0 (a query failure is not evidence of zero activity)."""
        try:
            import sqlite3
            path = self._intel_ledger_path()
            start_of_day = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).isoformat()
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
            try:
                row = con.execute(
                    "SELECT COUNT(*) FROM text_events WHERE ingested_at_utc >= ?", (start_of_day,)
                ).fetchone()
                return row[0] if row else None
            finally:
                con.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Discovery bounded-count query failed: %s", exc)
            return None

    def _intel_delivery_counts(self) -> tuple[dict | None, str | None]:
        """Two single bounded queries (GROUP BY state; MAX(sent_at_utc)) --
        no per-row scan, no filing content read. (None, None) on failure."""
        try:
            import sqlite3
            path = self._intel_ledger_path()
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
            try:
                rows = con.execute(
                    "SELECT state, COUNT(*) FROM intelligence_delivery GROUP BY state"
                ).fetchall()
                counts = {state: n for state, n in rows}
                last = con.execute(
                    "SELECT MAX(sent_at_utc) FROM intelligence_delivery WHERE state='SENT'"
                ).fetchone()
                return counts, (last[0] if last else None)
            finally:
                con.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Discovery delivery-count query failed: %s", exc)
            return None, None

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

    async def _reply(self, text: str, plain: bool = False) -> None:
        """`plain=True` sends with parse_mode=None -- required for any
        reply containing dynamic/arbitrary content not guaranteed to be
        valid Markdown (see _handle_ping, which uses this). `plain=False`
        (default) preserves existing behavior for callers whose content
        is already Markdown-safe (the alert-ID detail-lookup formatters)."""
        try:
            await self.telegram_client.send(text, parse_mode=None if plain else ParseMode.MARKDOWN)
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
