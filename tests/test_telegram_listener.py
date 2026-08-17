"""
tests/test_telegram_listener.py
------------------------------------
Tests talonx_dispatch.telegram_listener.TelegramReplyListener -- the
two-way half of the Telegram integration. Bot.get_updates is mocked by
patching the Bot class used inside telegram_listener.py (same "mock the
external service, exercise the orchestration logic" boundary every other
consumer's tests in this project use); replies go through an injected
mock TelegramClient rather than a second Bot mock, matching how the
constructor is actually meant to be used.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.schemas import AlertAction, AlertSeverity
from talonx_dispatch.telegram_client import TelegramSendError
from talonx_dispatch.telegram_listener import TelegramReplyListener, _parse_alert_id


def _config(**overrides) -> DispatchConfig:
    defaults = dict(telegram_bot_token="TEST_TOKEN", telegram_chat_id="12345")
    defaults.update(overrides)
    return DispatchConfig(**defaults)


def _row(alert_id: int = 47) -> dict:
    return {
        "id": alert_id,
        "ticker": "NVDA",
        "action": AlertAction.CONFIRMED_BULLISH.value,
        "severity": AlertSeverity.WARNING.value,
        "rationale": "Quant signal agrees with research.",
        "research_verdict": "bullish",
        "research_confidence": 0.85,
        "price": 131.5,
        "key_findings": [],
        "risk_factors": [],
        "model_used": "gemini-flash-latest",
        "correlated_at": "2026-08-10T18:51:43+00:00",
    }


def _update(update_id: int, text: str | None, chat_id: str = "12345"):
    update = MagicMock()
    update.update_id = update_id
    if text is None:
        update.message = None
    else:
        update.message = MagicMock()
        update.message.text = text
        update.message.chat_id = chat_id
    return update


@pytest.fixture
def store():
    return MagicMock()


@pytest.fixture
def telegram_client():
    client = AsyncMock()
    client.is_configured = True
    return client


@pytest.fixture
def listener(store, telegram_client) -> TelegramReplyListener:
    return TelegramReplyListener(store=store, config=_config(), telegram_client=telegram_client)


# --- _parse_alert_id --------------------------------------------------------
# Returns (is_long_term, id) since Phase 2 -- a bare number is the
# intraday alerts table; an "LT"-prefixed one is long_term_alerts.

@pytest.mark.parametrize(
    "text,expected",
    [
        ("47", (False, 47)),
        ("#47", (False, 47)),
        ("/details 47", (False, 47)),
        ("/details47", (False, 47)),
        ("/id 47", (False, 47)),
        ("  47  ", (False, 47)),
        ("LT47", (True, 47)),
        ("#LT47", (True, 47)),
        ("lt47", (True, 47)),  # case-insensitive
        ("/details LT47", (True, 47)),
        ("hello", None),
        ("", None),
        ("47.5", None),
    ],
)
def test_parse_alert_id(text, expected):
    assert _parse_alert_id(text) == expected


# --- _handle_update ----------------------------------------------------------

@pytest.mark.asyncio
async def test_known_id_replies_with_full_details(listener, store, telegram_client):
    store.get_by_id.return_value = _row(alert_id=47)

    await listener._handle_update(_update(1, "47"))

    store.get_by_id.assert_called_once_with(47)
    telegram_client.send.assert_awaited_once()
    text = telegram_client.send.await_args.args[0]
    assert "NVDA" in text
    assert "#47" in text
    assert listener.replies_sent == 1


@pytest.mark.asyncio
async def test_unknown_id_replies_not_found(listener, store, telegram_client):
    store.get_by_id.return_value = None

    await listener._handle_update(_update(1, "999"))

    telegram_client.send.assert_awaited_once()
    text = telegram_client.send.await_args.args[0]
    assert "999" in text
    assert "not found" in text.lower()


# --- Phase 2 LONG_TERM path -------------------------------------------------

def _long_term_row(alert_id: int = 12) -> dict:
    return {
        "id": alert_id, "ticker": "AAPL", "action": "high_conviction_buy", "severity": "critical",
        "rationale": "FY2025 fundamentals clear thresholds.",
        "quality_score": 8, "moat_rating": "wide", "market_price": 75.0,
        "intrinsic_fair_value": 100.0, "margin_of_safety_pct": 0.25,
        "capital_allocation_assessment": "Disciplined buybacks.",
        "key_findings": [], "risk_factors": [],
        "model_used": "gemini-flash-latest", "correlated_at": "2026-08-10T18:51:43+00:00",
    }


@pytest.mark.asyncio
async def test_lt_prefixed_id_looks_up_the_long_term_table(listener, store, telegram_client):
    store.get_long_term_by_id.return_value = _long_term_row(alert_id=12)

    await listener._handle_update(_update(1, "LT12"))

    store.get_long_term_by_id.assert_called_once_with(12)
    store.get_by_id.assert_not_called()
    text = telegram_client.send.await_args.args[0]
    assert "AAPL" in text
    assert "#LT12" in text
    assert listener.replies_sent == 1


@pytest.mark.asyncio
async def test_unknown_long_term_id_replies_not_found(listener, store, telegram_client):
    store.get_long_term_by_id.return_value = None

    await listener._handle_update(_update(1, "LT999"))

    text = telegram_client.send.await_args.args[0]
    assert "LT999" in text
    assert "not found" in text.lower()
    store.get_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_unrecognized_text_replies_with_usage_hint(listener, store, telegram_client):
    await listener._handle_update(_update(1, "hello there"))

    store.get_by_id.assert_not_called()
    telegram_client.send.assert_awaited_once()
    text = telegram_client.send.await_args.args[0]
    assert "Reply with an alert ID" in text


@pytest.mark.asyncio
async def test_message_from_unrecognized_chat_is_ignored(listener, store, telegram_client):
    await listener._handle_update(_update(1, "47", chat_id="99999"))

    store.get_by_id.assert_not_called()
    telegram_client.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_with_no_message_is_ignored(listener, store, telegram_client):
    await listener._handle_update(_update(1, None))

    telegram_client.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_send_failure_is_logged_not_raised(listener, store, telegram_client):
    store.get_by_id.return_value = _row()
    telegram_client.send.side_effect = TelegramSendError("boom")

    await listener._handle_update(_update(1, "47"))  # must not raise

    assert listener.replies_sent == 0


# --- run() / polling loop ----------------------------------------------------

# --- /ping (Interactive System Health Check) --------------------------------

def _dispatch_agent(started_at=None, redis_client=None):
    agent = MagicMock()
    agent.started_at = started_at or (datetime.now(timezone.utc) - timedelta(hours=14, minutes=22))
    agent._client = redis_client
    return agent


@pytest.mark.parametrize("text", ["/ping", "ping", "PING", "  /Ping  "])
@pytest.mark.asyncio
async def test_ping_replies_with_pong(listener, store, telegram_client, text):
    store.count_alerts_today.return_value = (86, 12)
    listener.dispatch_agent = _dispatch_agent()

    await listener._handle_update(_update(1, text))

    telegram_client.send.assert_awaited_once()
    reply = telegram_client.send.await_args.args[0]
    assert "Pong" in reply
    store.get_by_id.assert_not_called()  # never mistaken for an alert-ID lookup


@pytest.mark.asyncio
async def test_ping_reports_uptime_from_dispatch_agent(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    listener.dispatch_agent = _dispatch_agent(
        started_at=datetime.now(timezone.utc) - timedelta(hours=14, minutes=22)
    )

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "14h 22m" in reply


@pytest.mark.asyncio
async def test_ping_reports_todays_signal_counts(listener, store, telegram_client):
    store.count_alerts_today.return_value = (86, 12)
    listener.dispatch_agent = _dispatch_agent()

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "12 Pushes" in reply
    assert "86 Logs" in reply


@pytest.mark.asyncio
async def test_ping_reports_websocket_connected_via_polygon(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    redis_client = AsyncMock()
    redis_client.get.return_value = json.dumps({"source": "websocket", "connected": True})
    listener.dispatch_agent = _dispatch_agent(redis_client=redis_client)

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Connected (Polygon.io)" in reply


@pytest.mark.asyncio
async def test_ping_reports_websocket_connected_via_polling_fallback(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    redis_client = AsyncMock()
    redis_client.get.return_value = json.dumps({"source": "polling", "connected": True})
    listener.dispatch_agent = _dispatch_agent(redis_client=redis_client)

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "yfinance polling" in reply


@pytest.mark.asyncio
async def test_ping_reports_websocket_disconnected_when_heartbeat_missing(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    redis_client = AsyncMock()
    redis_client.get.return_value = None  # heartbeat key expired/never set
    listener.dispatch_agent = _dispatch_agent(redis_client=redis_client)

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Disconnected" in reply


@pytest.mark.asyncio
async def test_ping_reports_uptime_unknown_without_dispatch_agent(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    # listener.dispatch_agent stays None (constructor default) -- must not raise.

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "unknown" in reply
    assert "Disconnected" not in reply  # no Redis client to even check


@pytest.mark.asyncio
async def test_ping_ignored_from_unrecognized_chat(listener, store, telegram_client):
    await listener._handle_update(_update(1, "/ping", chat_id="99999"))

    telegram_client.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_is_a_noop_when_telegram_not_configured(store):
    client = AsyncMock()
    client.is_configured = False
    listener = TelegramReplyListener(store=store, config=_config(), telegram_client=client)

    with patch("talonx_dispatch.telegram_listener.Bot") as bot_cls:
        await listener.run()  # must return immediately, not hang

    bot_cls.assert_not_called()


# --- 2026-08-17 pipeline-observability fix: MARKET/QUANT/BRAIN/CORE/
# DISPATCH/SESSION sections, sourced from existing metrics:{date}:{stage}:
# {counter} Redis keys + the rejected_candidates SQLite audit table.
# "unknown" (not 0) whenever a figure genuinely can't be measured. ------

def _redis_with_metrics(heartbeat=None, metrics: dict[str, str] | None = None):
    """A fake async Redis client: .get(key) returns the heartbeat payload
    for the WS heartbeat key, a metric value for a `metrics:...` key (if
    present in `metrics`), or None otherwise -- same "absent key = 0"
    semantics the real _incr_metric/metrics reader relies on."""
    client = AsyncMock()

    async def fake_get(key):
        if key == "talonx:ingest:ws_heartbeat":
            return heartbeat
        if metrics and key in metrics:
            return metrics[key]
        return None

    client.get = AsyncMock(side_effect=fake_get)
    return client


def _today_key(stage: str, counter: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"metrics:{today}:{stage}:{counter}"


@pytest.mark.asyncio
async def test_ping_market_section_reports_bars_read_metric(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    redis_client = _redis_with_metrics(metrics={_today_key("ingest", "bars_read"): "482"})
    listener.dispatch_agent = _dispatch_agent(redis_client=redis_client)

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Bars/events received today: 482" in reply


@pytest.mark.asyncio
async def test_ping_market_section_watchlist_size_is_always_unknown(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    listener.dispatch_agent = _dispatch_agent(redis_client=_redis_with_metrics())

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Watchlist size: unknown" in reply


@pytest.mark.asyncio
async def test_ping_market_feed_status_healthy_for_a_fresh_heartbeat(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    fresh = json.dumps({"source": "polling", "connected": True, "updated_at": datetime.now(timezone.utc).isoformat()})
    listener.dispatch_agent = _dispatch_agent(redis_client=_redis_with_metrics(heartbeat=fresh))

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "healthy" in reply


@pytest.mark.asyncio
async def test_ping_market_feed_status_stale_for_an_old_heartbeat(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    stale = json.dumps({"source": "polling", "connected": True, "updated_at": old_ts})
    listener.dispatch_agent = _dispatch_agent(redis_client=_redis_with_metrics(heartbeat=stale))

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "stale" in reply
    assert "300s ago" in reply


@pytest.mark.asyncio
async def test_ping_missing_metric_key_reads_as_zero_not_unknown(listener, store, telegram_client):
    # A counter that legitimately never incremented today (key absent,
    # Redis reachable) must read as 0 -- distinct from "unknown".
    store.count_alerts_today.return_value = (0, 0)
    listener.dispatch_agent = _dispatch_agent(redis_client=_redis_with_metrics())  # no metrics keys set

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Candidates generated today: 0" in reply
    assert "Signals published today: 0" in reply


@pytest.mark.asyncio
async def test_ping_metrics_are_unknown_without_a_redis_client(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    # listener.dispatch_agent stays None -- no Redis client at all.

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Candidates generated today: unknown" in reply
    assert "Signals published today: unknown" in reply


@pytest.mark.asyncio
async def test_ping_quant_section_reports_candidates_and_published(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    redis_client = _redis_with_metrics(metrics={
        _today_key("quant", "evaluated"): "150",
        _today_key("quant", "published"): "9",
    })
    listener.dispatch_agent = _dispatch_agent(redis_client=redis_client)

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Candidates generated today: 150" in reply
    assert "Signals published today: 9" in reply


@pytest.mark.asyncio
async def test_ping_quant_section_reuses_the_rejected_candidates_audit_table(listener, store, telegram_client):
    # Part 6: reuse the EXISTING talonx:quant:rejected audit trail rather
    # than inventing a second mechanism.
    store.count_alerts_today.return_value = (0, 0)
    store.rejected_candidates_between.return_value = [{"id": i} for i in range(37)]
    listener.dispatch_agent = _dispatch_agent(redis_client=_redis_with_metrics())

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Rejected candidates today: 37" in reply
    assert store.rejected_candidates_between.call_count == 1


@pytest.mark.asyncio
async def test_ping_quant_section_rejected_count_unknown_on_audit_query_failure(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    store.rejected_candidates_between.side_effect = RuntimeError("db locked")
    listener.dispatch_agent = _dispatch_agent(redis_client=_redis_with_metrics())

    await listener._handle_update(_update(1, "/ping"))  # must not raise

    reply = telegram_client.send.await_args.args[0]
    assert "Rejected candidates today: unknown" in reply


@pytest.mark.asyncio
async def test_ping_brain_reports_generated_is_always_unknown(listener, store, telegram_client):
    # brain's own report counter is in-process only -- not a Redis metric
    # any other module (including dispatch) can read.
    store.count_alerts_today.return_value = (0, 0)
    redis_client = _redis_with_metrics(metrics={_today_key("brain", "received"): "22"})
    listener.dispatch_agent = _dispatch_agent(redis_client=redis_client)

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Quant signals received today: 22" in reply
    assert "Reports generated today: unknown" in reply


@pytest.mark.asyncio
async def test_ping_core_section_sums_actionable_alert_counters(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    redis_client = _redis_with_metrics(metrics={
        _today_key("core", "action_bullish"): "5",
        _today_key("core", "action_bearish"): "3",
        _today_key("core", "action_contradicted"): "2",
    })
    listener.dispatch_agent = _dispatch_agent(redis_client=redis_client)

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Actionable alerts today: 10" in reply
    assert "Research reports received today: unknown" in reply


@pytest.mark.asyncio
async def test_ping_dispatch_section_reports_received_suppressed_pushed(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    redis_client = _redis_with_metrics(metrics={
        _today_key("dispatch", "received"): "40",
        _today_key("dispatch", "muted_contradictions"): "4",
        _today_key("dispatch", "muted_confidence"): "1",
        _today_key("dispatch", "muted_cooldown"): "2",
        _today_key("dispatch", "pushed_telegram"): "33",
    })
    listener.dispatch_agent = _dispatch_agent(redis_client=redis_client)

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "Alerts received today: 40" in reply
    assert "Suppressed today: 7" in reply
    assert "Telegram pushed today: 33" in reply


@pytest.mark.asyncio
async def test_ping_session_section_reports_us_session_and_uk_time(listener, store, telegram_client):
    store.count_alerts_today.return_value = (0, 0)
    listener.dispatch_agent = _dispatch_agent(redis_client=_redis_with_metrics())

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "US market session:" in reply
    assert "UK time:" in reply
    assert "Regular session:" in reply


@pytest.mark.asyncio
async def test_ping_still_shows_original_uptime_cpu_and_signal_lines(listener, store, telegram_client):
    # The pre-existing summary lines (uptime, CPU/RAM, today's pushes)
    # must survive alongside the new sections, not be replaced by them.
    store.count_alerts_today.return_value = (86, 12)
    listener.dispatch_agent = _dispatch_agent(
        started_at=datetime.now(timezone.utc) - timedelta(hours=14, minutes=22),
        redis_client=_redis_with_metrics(),
    )

    await listener._handle_update(_update(1, "/ping"))

    reply = telegram_client.send.await_args.args[0]
    assert "14h 22m" in reply
    assert "CPU Usage" in reply
    assert "12 Pushes" in reply
    assert "86 Logs" in reply


@pytest.mark.asyncio
async def test_poll_forever_drains_backlog_then_handles_new_updates(listener, store, telegram_client):
    store.get_by_id.return_value = _row(alert_id=47)

    mock_bot = AsyncMock()
    call_count = {"n": 0}

    async def get_updates_side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (_update(100, "stale, ignored"),)  # backlog drain (timeout=0 call)
        if call_count["n"] == 2:
            return (_update(101, "47"),)  # first real poll
        listener.stop()
        return ()

    mock_bot.get_updates = AsyncMock(side_effect=get_updates_side_effect)

    bot_ctx = MagicMock()
    bot_ctx.__aenter__ = AsyncMock(return_value=mock_bot)
    bot_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("talonx_dispatch.telegram_listener.Bot", return_value=bot_ctx) as bot_cls:
        await listener.run()

    bot_cls.assert_called_once_with(token="TEST_TOKEN")
    assert call_count["n"] >= 3
    telegram_client.send.assert_awaited_once()
    # The backlog update ("stale, ignored") must never have triggered a reply --
    # only the post-drain update should have been handled.
    store.get_by_id.assert_called_once_with(47)
