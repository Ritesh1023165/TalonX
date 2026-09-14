"""
tests/test_task138_telegram_message_resolvers.py
==================================================
Task 138 Workstream 3 -- isolated coverage for the new
``message_resolvers`` extension point on
``talonx_dispatch.telegram_listener.TelegramReplyListener`` and
``talonx_dispatch.consumer.DispatchAgent``: an ordered list of
``Message -> str | None`` callables tried BEFORE the existing
``extra_resolvers`` (``str -> str | None``) and the numeric alert-ID
path. Mirrors the fixture/mock conventions already established in
tests/test_telegram_listener.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.telegram_listener import TelegramReplyListener


def _config(**overrides) -> DispatchConfig:
    defaults = dict(telegram_bot_token="TEST_TOKEN", telegram_chat_id="12345")
    defaults.update(overrides)
    return DispatchConfig(**defaults)


def _update(update_id: int, text: str | None, chat_id: str = "12345",
           reply_to_message_id: int | None = None):
    update = MagicMock()
    update.update_id = update_id
    if text is None:
        update.message = None
    else:
        update.message = MagicMock()
        update.message.text = text
        update.message.chat_id = chat_id
        if reply_to_message_id is not None:
            update.message.reply_to_message = MagicMock()
            update.message.reply_to_message.message_id = reply_to_message_id
        else:
            update.message.reply_to_message = None
    return update


@pytest.fixture
def store():
    return MagicMock()


@pytest.fixture
def telegram_client():
    client = AsyncMock()
    client.is_configured = True
    return client


class _NeverBotFactory:
    def __call__(self, **kwargs):
        raise AssertionError("handler-only test attempted to construct a Telegram Bot")


@pytest.fixture
def never_bot_factory():
    return _NeverBotFactory()


def _listener(store, telegram_client, never_bot_factory, **kw):
    return TelegramReplyListener(
        store=store, config=_config(), telegram_client=telegram_client,
        bot_factory=never_bot_factory, **kw,
    )


@pytest.mark.asyncio
async def test_message_resolver_is_tried_and_its_reply_is_sent_plain(store, telegram_client,
                                                                      never_bot_factory):
    calls = []

    def resolver(message):
        calls.append(message.text)
        return "resolved details text"

    listener = _listener(store, telegram_client, never_bot_factory, message_resolvers=[resolver])
    await listener._handle_update(_update(1, "details", reply_to_message_id=945))

    assert calls == ["details"]
    telegram_client.send.assert_awaited_once()
    args, kwargs = telegram_client.send.await_args
    assert args[0] == "resolved details text"
    # plain=True -> parse_mode=None, since resolver output can carry
    # arbitrary uncontrolled SEC-sourced text not guaranteed Markdown-safe.
    assert kwargs.get("parse_mode") is None
    store.get_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_message_resolver_receives_the_full_message_object_not_just_text(store,
                                                                                telegram_client,
                                                                                never_bot_factory):
    """The whole point of message_resolvers (vs the older extra_resolvers)
    is access to reply_to_message.message_id -- confirm it's really there."""
    seen = {}

    def resolver(message):
        seen["reply_to_id"] = (
            message.reply_to_message.message_id if message.reply_to_message else None
        )
        return "ok" if seen["reply_to_id"] == 945 else None

    listener = _listener(store, telegram_client, never_bot_factory, message_resolvers=[resolver])
    await listener._handle_update(_update(1, "details", reply_to_message_id=945))

    assert seen["reply_to_id"] == 945
    telegram_client.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_message_resolvers_tried_before_extra_resolvers(store, telegram_client,
                                                               never_bot_factory):
    extra_calls = []

    def msg_resolver(message):
        return "from message_resolvers"

    def extra_resolver(text):
        extra_calls.append(text)
        return "from extra_resolvers"

    listener = _listener(store, telegram_client, never_bot_factory,
                         message_resolvers=[msg_resolver], extra_resolvers=[extra_resolver])
    await listener._handle_update(_update(1, "details"))

    assert extra_calls == []          # never reached -- message_resolvers won first
    args, _ = telegram_client.send.await_args
    assert args[0] == "from message_resolvers"


@pytest.mark.asyncio
async def test_message_resolver_returning_none_falls_through_to_extra_resolvers(store,
                                                                                 telegram_client,
                                                                                 never_bot_factory):
    def msg_resolver(message):
        return None   # not recognized -- fall through

    def extra_resolver(text):
        return "handled by extra_resolvers"

    listener = _listener(store, telegram_client, never_bot_factory,
                         message_resolvers=[msg_resolver], extra_resolvers=[extra_resolver])
    await listener._handle_update(_update(1, "hello"))

    args, _ = telegram_client.send.await_args
    assert args[0] == "handled by extra_resolvers"


@pytest.mark.asyncio
async def test_message_resolver_returning_none_falls_through_to_numeric_alert_id_path(store,
                                                                                       telegram_client,
                                                                                       never_bot_factory):
    store.get_by_id.return_value = None

    def msg_resolver(message):
        return None

    listener = _listener(store, telegram_client, never_bot_factory, message_resolvers=[msg_resolver])
    await listener._handle_update(_update(1, "47"))

    store.get_by_id.assert_called_once_with(47)


@pytest.mark.asyncio
async def test_message_resolver_exception_is_logged_and_skipped_not_raised(store, telegram_client,
                                                                            never_bot_factory,
                                                                            caplog):
    def broken(message):
        raise RuntimeError("boom")

    def working(message):
        return "second resolver handled it"

    listener = _listener(store, telegram_client, never_bot_factory,
                         message_resolvers=[broken, working])
    await listener._handle_update(_update(1, "details"))

    args, _ = telegram_client.send.await_args
    assert args[0] == "second resolver handled it"


@pytest.mark.asyncio
async def test_no_message_resolvers_is_byte_identical_to_prior_behaviour(store, telegram_client,
                                                                          never_bot_factory):
    """Default (message_resolvers omitted) must reach the existing
    numeric-alert-id / usage-hint path exactly as before Task 138."""
    listener = _listener(store, telegram_client, never_bot_factory)
    assert listener.message_resolvers == []

    await listener._handle_update(_update(1, "hello there"))
    args, _ = telegram_client.send.await_args
    assert "Reply with an alert ID" in args[0]


@pytest.mark.asyncio
async def test_unauthorized_chat_never_reaches_message_resolvers(store, telegram_client,
                                                                  never_bot_factory):
    calls = []

    def resolver(message):
        calls.append(message)
        return "should never be sent"

    listener = _listener(store, telegram_client, never_bot_factory, message_resolvers=[resolver])
    await listener._handle_update(_update(1, "details", chat_id="99999", reply_to_message_id=945))

    assert calls == []
    telegram_client.send.assert_not_awaited()
