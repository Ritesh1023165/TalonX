"""Task 83-R3B: explicit Telegram factories plus fail-closed networking."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import NetworkError

import talonx_dispatch.telegram_listener as listener_module
from _network_guard import GuardInitializationError, NetworkBlockedError, NetworkGuard
from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.telegram_listener import TelegramReplyListener
from talonx_piv.telegram_inbound import build_piv_telegram_listener


# Matches Telegram's local token shape validation but is deliberately not a
# credential: an impossible all-zero bot id plus a synthetic repeated suffix.
LOCAL_TOKEN = "000000000:" + ("A" * 35)
LOCAL_CHAT = "123"


def _config() -> DispatchConfig:
    return DispatchConfig(
        telegram_bot_token=LOCAL_TOKEN,
        telegram_chat_id=LOCAL_CHAT,
        reconnect_backoff_base_seconds=0,
        reconnect_backoff_max_seconds=0,
        telegram_poll_timeout_seconds=1,
    )


def _configured_client():
    client = AsyncMock()
    client.is_configured = True
    return client


class _FakeBot:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *_args):
        self.exited += 1
        return False

    async def get_updates(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response() if callable(response) else response


class _RecordingFactory:
    def __init__(self, bot):
        self.bot = bot
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.bot


class _NeverFactory:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("disabled listener constructed a Telegram Bot")


def _listener(factory) -> TelegramReplyListener:
    return TelegramReplyListener(
        store=MagicMock(),
        config=_config(),
        telegram_client=_configured_client(),
        bot_factory=factory,
    )


@pytest.mark.asyncio
async def test_listener_constructed_with_fake_uses_that_exact_fake():
    bot = _FakeBot([[], lambda: (listener.stop() or [])])
    factory = _RecordingFactory(bot)
    listener = _listener(factory)

    await asyncio.wait_for(listener.run(), timeout=1)

    assert factory.calls == [{"token": LOCAL_TOKEN}]
    assert bot.entered == bot.exited == 1
    assert len(bot.calls) == 2


@pytest.mark.asyncio
async def test_module_patch_order_cannot_replace_explicit_factory(monkeypatch):
    bot = _FakeBot([[], lambda: (listener.stop() or [])])
    factory = _RecordingFactory(bot)
    listener = _listener(factory)
    unintended_default = MagicMock(side_effect=AssertionError("default Bot was captured"))
    monkeypatch.setattr(listener_module, "Bot", unintended_default)

    await asyncio.wait_for(listener.run(), timeout=1)

    unintended_default.assert_not_called()
    assert factory.calls == [{"token": LOCAL_TOKEN}]


@pytest.mark.asyncio
async def test_backlog_drain_uses_injected_fake():
    stale = MagicMock(update_id=41)
    bot = _FakeBot([[stale], lambda: (listener.stop() or [])])
    factory = _RecordingFactory(bot)
    listener = _listener(factory)

    await asyncio.wait_for(listener.run(), timeout=1)

    assert bot.calls[0] == {"timeout": 0, "allowed_updates": ["message"]}
    assert bot.calls[1]["offset"] == 42


@pytest.mark.asyncio
async def test_live_get_updates_uses_injected_fake():
    bot = _FakeBot([[], lambda: (listener.stop() or [])])
    factory = _RecordingFactory(bot)
    listener = _listener(factory)

    await asyncio.wait_for(listener.run(), timeout=1)

    live_call = bot.calls[1]
    assert live_call["timeout"] == 1
    assert live_call["read_timeout"] == 11
    assert live_call["allowed_updates"] == ["message"]


@pytest.mark.asyncio
async def test_retry_after_fake_telegram_failure_remains_fake(monkeypatch):
    bot = _FakeBot([[], NetworkError("local fake failure"), lambda: (listener.stop() or [])])
    factory = _RecordingFactory(bot)
    listener = _listener(factory)
    unintended_default = MagicMock(side_effect=AssertionError("default Bot was used on retry"))
    monkeypatch.setattr(listener_module, "Bot", unintended_default)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(listener_module.asyncio, "sleep", no_sleep)
    await asyncio.wait_for(listener.run(), timeout=1)

    assert len(bot.calls) == 3
    assert factory.calls == [{"token": LOCAL_TOKEN}]
    unintended_default.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_piv_constructs_no_bot_or_poller(tmp_path):
    never = _NeverFactory()
    listener = build_piv_telegram_listener(tmp_path, bot_factory=never)

    await asyncio.wait_for(listener.run(), timeout=1)

    assert listener.telegram_client.is_configured is False
    assert listener.poll_telemetry is None
    assert never.calls == []


@pytest.mark.asyncio
async def test_original_remains_sole_poller_when_piv_is_disabled(tmp_path):
    bot = _FakeBot([[], lambda: (listener.stop() or [])])
    factory = _RecordingFactory(bot)
    listener = _listener(factory)
    piv_factory = _NeverFactory()
    piv_listener = build_piv_telegram_listener(tmp_path, bot_factory=piv_factory)

    await asyncio.wait_for(
        asyncio.gather(listener.run(), piv_listener.run()), timeout=1
    )

    assert listener.poll_telemetry is None
    assert len(factory.calls) == 1
    assert bot.entered == bot.exited == 1
    assert piv_factory.calls == []


@pytest.mark.asyncio
async def test_unfaked_telegram_is_blocked_before_external_access(talonx_network_guard):
    listener = TelegramReplyListener(
        store=MagicMock(),
        config=_config(),
        telegram_client=_configured_client(),
    )

    with talonx_network_guard.expect_block("unfaked_telegram_getme"):
        with pytest.raises(Exception) as caught:  # library may wrap the guarded socket error
            await asyncio.wait_for(listener._poll_forever(), timeout=3)

    assert not isinstance(caught.value, asyncio.TimeoutError)
    report = talonx_network_guard.snapshot()
    assert report["expected_negative_controls"]["unfaked_telegram_getme"] >= 1
    assert report["observed_expected_negative_control_blocks"][
        "unfaked_telegram_getme"
    ] >= 1
    assert report["counters"]["unexpected_external_attempts"] == 0


@pytest.mark.parametrize(
    ("label", "path", "host"),
    [
        ("block_ipv4", "connect", "198.51.100.10"),
        ("block_ipv6", "connect_v6", "2001:db8::10"),
        ("block_hostname", "dns", "telegram.invalid.example"),
    ],
)
def test_non_loopback_destinations_are_blocked_before_dns(
    talonx_network_guard, label, path, host
):
    with talonx_network_guard.expect_block(label):
        with pytest.raises(NetworkBlockedError):
            if path == "dns":
                socket.getaddrinfo(host, 443)
            elif path == "connect_v6":
                with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as client:
                    client.connect((host, 443, 0, 0))
            else:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                    client.connect((host, 443))


def test_loopback_ipv4_ipv6_and_localhost_remain_permitted(talonx_network_guard):
    before = talonx_network_guard.snapshot()["counters"]["permitted_loopback_connections"]

    socket.getaddrinfo("localhost", 0)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client4:
        client4.connect_ex(("127.0.0.1", 9))
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as client6:
        client6.connect_ex(("::1", 9, 0, 0))

    after = talonx_network_guard.snapshot()["counters"]["permitted_loopback_connections"]
    assert after >= before + 3


def test_guard_initialization_failure_is_visible(tmp_path):
    report_path = tmp_path / "initialization_failure.json"
    broken = NetworkGuard(
        report_path,
        target_overrides={"socket.socket.connect": None},
    )

    with pytest.raises(GuardInitializationError, match="socket.socket.connect"):
        broken.install()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["guard_initialized_successfully"] is False
    assert report["counters"]["guard_initialization_failures"] == 1
    assert report["events"][0]["kind"] == "guard_initialization_failure"


@pytest.mark.asyncio
async def test_no_valid_token_or_external_credential_is_required(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    bot = _FakeBot([[], lambda: (listener.stop() or [])])
    factory = _RecordingFactory(bot)
    listener = _listener(factory)

    await asyncio.wait_for(listener.run(), timeout=1)

    assert factory.calls == [{"token": LOCAL_TOKEN}]
    assert bot.calls


@pytest.mark.asyncio
async def test_factory_interface_is_validated_before_polling():
    listener = _listener(object())
    with pytest.raises(TypeError, match="must be callable"):
        await listener._poll_forever()

    listener = _listener(lambda **_kwargs: object())
    with pytest.raises(TypeError, match="async context manager"):
        await listener._poll_forever()


def test_zz_guard_report_reconciles_expected_and_unexpected_attempts(
    talonx_network_guard,
):
    talonx_network_guard.assert_reconciled()
    talonx_network_guard.write_report()
    report = talonx_network_guard.snapshot()

    assert report["guard_initialized_successfully"] is True
    assert report["counters"]["unexpected_external_attempts"] == 0
    assert report["counters"]["guard_initialization_failures"] == 0
    assert report["negative_controls_reconciled"] is True
    assert report["expected_negative_controls"] == report[
        "observed_expected_negative_control_blocks"
    ]
    assert report["counters"]["expected_negative_control_blocks"] == sum(
        report["expected_negative_controls"].values()
    )
    assert {
        "unfaked_telegram_getme",
        "block_ipv4",
        "block_ipv6",
        "block_hostname",
    }.issubset(report["expected_negative_controls"])
    assert report["counters"]["permitted_loopback_connections"] >= 3
    assert talonx_network_guard.report_path is not None
    on_disk = json.loads(Path(talonx_network_guard.report_path).read_text(encoding="utf-8"))
    assert on_disk == report
