"""
tests/test_telegram_ping_safety.py
---------------------------------------
2026-08-18 live-incident correctness fixes (code-review findings #1, #2
partial, #6, #7, #8, #9): proves /ping's diagnostic reply is sent as
plain text (never Markdown-parsed, so dynamic content like a raw
session-state label can never break it -- the confirmed live root cause),
that existing Markdown-formatted callers (alert-detail lookups) are
unaffected, and that the health/labeling fixes (Process vs Pipeline,
Trade-action vs Contradicted, UTC metrics-day) are wired correctly.

Exercises the REAL TelegramClient.send() -> Bot.send_message() boundary
(only Bot itself is mocked, same boundary test_telegram_listener.py
already uses) rather than a fully-mocked TelegramClient, specifically to
prove the parse_mode value actually reaches the transport call -- a
fully-mocked TelegramClient (as most of test_telegram_listener.py uses)
would not catch a parse_mode regression, which is exactly finding #9's
own criticism of the existing test suite.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.constants import ParseMode

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.telegram_client import TelegramClient
from talonx_dispatch.telegram_listener import TelegramReplyListener


def _config(**overrides) -> DispatchConfig:
    defaults = dict(telegram_bot_token="TEST_TOKEN", telegram_chat_id="12345")
    defaults.update(overrides)
    return DispatchConfig(**defaults)


# ----------------------------------------------------------------------
# TelegramClient.send() transport boundary -- proves parse_mode actually
# reaches Bot.send_message, for both the default (Markdown) and the
# explicit-None (plain) cases.
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_default_parse_mode_is_markdown_unchanged():
    client = TelegramClient(_config())
    mock_bot = AsyncMock()
    bot_ctx = MagicMock()
    bot_ctx.__aenter__ = AsyncMock(return_value=mock_bot)
    bot_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("talonx_dispatch.telegram_client.Bot", return_value=bot_ctx):
        await client.send("hello")

    mock_bot.send_message.assert_awaited_once()
    assert mock_bot.send_message.call_args.kwargs["parse_mode"] == ParseMode.MARKDOWN


@pytest.mark.asyncio
async def test_send_explicit_none_parse_mode_reaches_transport():
    client = TelegramClient(_config())
    mock_bot = AsyncMock()
    bot_ctx = MagicMock()
    bot_ctx.__aenter__ = AsyncMock(return_value=mock_bot)
    bot_ctx.__aexit__ = AsyncMock(return_value=False)

    # Arbitrary content that would break legacy Markdown parsing if sent
    # with parse_mode=Markdown (unterminated entities) -- with parse_mode=
    # None, Telegram never attempts to parse it as Markdown at all, so
    # none of these can ever produce a "can't parse entities" error.
    dangerous_text = "US market session: pre_market\nWeird *bold_ `code [link"

    with patch("talonx_dispatch.telegram_client.Bot", return_value=bot_ctx):
        await client.send(dangerous_text, parse_mode=None)

    mock_bot.send_message.assert_awaited_once()
    assert mock_bot.send_message.call_args.kwargs["parse_mode"] is None
    assert mock_bot.send_message.call_args.kwargs["text"] == dangerous_text


# ----------------------------------------------------------------------
# TelegramReplyListener._reply() -- proves the plain/Markdown choice is
# correctly threaded from the caller through to TelegramClient.send().
# ----------------------------------------------------------------------

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


@pytest.mark.asyncio
async def test_reply_default_still_markdown_for_alert_detail_lookups(listener, telegram_client):
    """Backward-compat proof: existing callers (alert-ID detail replies)
    that don't pass plain=True are completely unaffected by this fix."""
    await listener._reply("*Alert #47*")
    telegram_client.send.assert_awaited_once_with("*Alert #47*", parse_mode=ParseMode.MARKDOWN)


@pytest.mark.asyncio
async def test_reply_plain_uses_no_parse_mode(listener, telegram_client):
    await listener._reply("US market session: pre_market", plain=True)
    telegram_client.send.assert_awaited_once_with("US market session: pre_market", parse_mode=None)


# ----------------------------------------------------------------------
# _handle_ping end to end -- proves the real /ping path (a) sends plain,
# (b) still contains the dynamic content that broke it before (proving
# the fix is "send safely" not "strip the content"), across every
# US session label, (c) never raises regardless of session/content.
# ----------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("us_session_label", ["pre_market", "regular", "closed", "after_hours"])
async def test_ping_sends_plain_text_across_all_session_labels(listener, telegram_client, us_session_label):
    listener.store.count_alerts_today = MagicMock(return_value=(0, 0))
    with patch("talonx_dispatch.telegram_listener._us_session", return_value=us_session_label):
        await listener._handle_ping()

    telegram_client.send.assert_awaited_once()
    call = telegram_client.send.call_args
    assert call.kwargs["parse_mode"] is None, "plain=True must reach TelegramClient.send as parse_mode=None"
    sent_text = call.args[0]
    assert f"US market session: {us_session_label}" in sent_text


@pytest.mark.asyncio
async def test_ping_message_survives_arbitrary_markdown_special_characters(listener, telegram_client):
    """Directly proves the ORIGINAL failure mode (an unescaped `_` in a
    dynamic value) can no longer break /ping -- sent plain, Telegram
    never attempts to parse this as Markdown, so unterminated entities
    are a non-issue regardless of what dynamic content ends up in the
    message."""
    listener.store.count_alerts_today = MagicMock(return_value=(0, 0))
    with patch("talonx_dispatch.telegram_listener._us_session", return_value="pre_market"):
        await listener._handle_ping()  # must not raise
    telegram_client.send.assert_awaited_once()
    assert telegram_client.send.call_args.kwargs["parse_mode"] is None


@pytest.mark.asyncio
async def test_ping_message_size_within_telegram_limit(listener, telegram_client):
    """Telegram's hard limit is 4096 characters per message -- confirms
    the current diagnostic message has comfortable headroom (not a new
    truncation mechanism, just a safety confirmation)."""
    listener.store.count_alerts_today = MagicMock(return_value=(12345, 6789))
    await listener._handle_ping()
    sent_text = telegram_client.send.call_args.args[0]
    assert len(sent_text) < 4096


# ----------------------------------------------------------------------
# Process/Pipeline health semantics (finding #6) -- no more hardcoded
# "Active / Healthy" regardless of actual pipeline state.
# ----------------------------------------------------------------------

def test_pipeline_status_unknown_when_no_redis_client(listener):
    assert listener._pipeline_status(None, "\U0001F7E2 healthy") == "UNKNOWN (no Redis connection)"


def test_pipeline_status_degraded_when_market_feed_disconnected(listener):
    status = listener._pipeline_status(MagicMock(), "\U0001F534 disconnected")
    assert status.startswith("DEGRADED")


def test_pipeline_status_degraded_when_market_feed_stale(listener):
    status = listener._pipeline_status(MagicMock(), "\U0001F7E1 stale")
    assert status.startswith("DEGRADED")


def test_pipeline_status_healthy_when_market_feed_healthy(listener):
    status = listener._pipeline_status(MagicMock(), "\U0001F7E2 healthy")
    assert status.startswith("HEALTHY")


@pytest.mark.asyncio
async def test_ping_no_longer_hardcodes_active_healthy(listener, telegram_client):
    listener.store.count_alerts_today = MagicMock(return_value=(0, 0))
    await listener._handle_ping()
    sent_text = telegram_client.send.call_args.args[0]
    assert "Active / Healthy" not in sent_text
    assert "Process: RUNNING" in sent_text
    assert "Pipeline:" in sent_text


# ----------------------------------------------------------------------
# Trade-action vs Contradicted labeling (finding #7).
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_core_section_separates_contradicted_from_trade_action():
    # 2026-08-18 /ping observability completion: _core_section was merged
    # into _signal_lifecycle_section (QUANT published -> ... -> Telegram
    # pushed, one unified funnel instead of three separate BRAIN/CORE/
    # DISPATCH headers) -- renamed/updated in place, same assertion intent.
    async def fake_get(key, *a, **kw):
        return None

    redis_client = AsyncMock()

    async def fake_get_side_effect(key):
        if key.endswith(":action_bullish"):
            return "3"
        if key.endswith(":action_bearish"):
            return "2"
        if key.endswith(":action_contradicted"):
            return "7"
        return None

    redis_client.get = AsyncMock(side_effect=fake_get_side_effect)
    listener = TelegramReplyListener(store=MagicMock(), config=_config(), telegram_client=AsyncMock())

    lines = await listener._signal_lifecycle_section(redis_client)
    joined = "\n".join(lines)
    assert "Core actionable: 5 (bullish + bearish)" in joined
    assert "Core contradicted: 7" in joined
    assert "Actionable alerts today" not in joined  # old, misleading label gone


# ----------------------------------------------------------------------
# UTC metrics-day label (finding #8).
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ping_states_metrics_day_is_utc(listener, telegram_client):
    listener.store.count_alerts_today = MagicMock(return_value=(0, 0))
    await listener._handle_ping()
    sent_text = telegram_client.send.call_args.args[0]
    assert "(UTC)" in sent_text
    assert f"{datetime.now(timezone.utc):%Y-%m-%d}" in sent_text
