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

@pytest.mark.parametrize(
    "text,expected",
    [
        ("47", 47),
        ("#47", 47),
        ("/details 47", 47),
        ("/details47", 47),
        ("/id 47", 47),
        ("  47  ", 47),
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

@pytest.mark.asyncio
async def test_run_is_a_noop_when_telegram_not_configured(store):
    client = AsyncMock()
    client.is_configured = False
    listener = TelegramReplyListener(store=store, config=_config(), telegram_client=client)

    with patch("talonx_dispatch.telegram_listener.Bot") as bot_cls:
        await listener.run()  # must return immediately, not hang

    bot_cls.assert_not_called()


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
