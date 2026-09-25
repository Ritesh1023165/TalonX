"""2026-09-25 V2 -> Signal routing fix (ROUTING_FIX).

The V2 actionable Telegram transport built a bare ``TelegramClient()`` from the legacy ``TELEGRAM_BOT_TOKEN`` (revoked
-> Telegram 401) instead of the TRADE_EVENT (TalonX Signal) destination, and the release gate only checked the
configured destination. No message is sent by these tests; no real token is used.
"""
from __future__ import annotations

import json

import pytest

import tests.test_v2_final_release_acceptance as acc
from talonx_v2 import release_gate as rg
from talonx_v2.delivery import OfficialTelegramTransport

LEGACY = "9999999999:AA-legacy_revoked_token_value_QQQQQQQQ"
NOTIFY_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN",
               "TALONX_NOTIFY_TRADE_EVENT_CHAT_ID", "TALONX_NOTIFY_OPERATIONS_BOT_TOKEN",
               "TALONX_NOTIFY_OPERATIONS_CHAT_ID", "TALONX_NOTIFY_RESEARCH_ENABLED",
               "TALONX_NOTIFY_RESEARCH_BOT_TOKEN", "TALONX_NOTIFY_RESEARCH_CHAT_ID")


@pytest.fixture
def env(monkeypatch):
    for k in NOTIFY_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", LEGACY)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "legacy-chat")
    monkeypatch.setenv("TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN", "signal-token")
    monkeypatch.setenv("TALONX_NOTIFY_TRADE_EVENT_CHAT_ID", "owner-chat")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_BOT_TOKEN", "sentinel-token")
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_CHAT_ID", "owner-chat")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN", "lab-token")
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_CHAT_ID", "owner-chat")
    return monkeypatch


def _capture_sends(monkeypatch):
    sent = []

    async def fake_send(self, text, parse_mode=None, **kw):
        sent.append((self.config.telegram_bot_token, self.config.telegram_chat_id, text))
    from talonx_dispatch import telegram_client as tc
    monkeypatch.setattr(tc.TelegramClient, "send", fake_send)
    return sent


def test_v2_transport_resolves_the_signal_destination_not_the_legacy_token(env):
    cli = OfficialTelegramTransport()._resolve()
    assert (cli.config.telegram_bot_token, cli.config.telegram_chat_id) == ("signal-token", "owner-chat")
    assert cli.config.telegram_bot_token != LEGACY


@pytest.mark.parametrize("action", ["BUY", "SELL"])
def test_buy_and_sell_are_sent_by_the_signal_bot(env, action):
    sent = _capture_sends(env)
    res = OfficialTelegramTransport().send(f"V2 {action} XYZ", meta={"dedup_key": f"k-{action}", "action": action})
    assert res["ok"] is True
    assert [(t, c) for t, c, _ in sent] == [("signal-token", "owner-chat")]


def test_disabled_trade_event_destination_holds_and_never_uses_a_default_client(env):
    for k in ("TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN", "TALONX_NOTIFY_TRADE_EVENT_CHAT_ID", "TELEGRAM_BOT_TOKEN",
              "TELEGRAM_CHAT_ID"):
        env.delenv(k, raising=False)
    sent = _capture_sends(env)
    res = OfficialTelegramTransport().send("V2 BUY XYZ", meta={"dedup_key": "k"})
    assert res.get("held") is True and "TRADE_EVENT" in res["detail"] and sent == []


def test_the_revoked_legacy_token_cannot_affect_the_signal_route(env):
    env.setenv("TELEGRAM_BOT_TOKEN", "a-completely-different-legacy-value")
    cli = OfficialTelegramTransport()._resolve()
    assert cli.config.telegram_bot_token == "signal-token"


def test_sentinel_and_lab_routes_are_unchanged_and_distinct(env):
    from talonx_ops.notify import OPERATIONS, RESEARCH, TRADE_EVENT, telegram_client_for
    tok = {d: telegram_client_for(d).config.telegram_bot_token for d in (TRADE_EVENT, OPERATIONS, RESEARCH)}
    assert tok == {TRADE_EVENT: "signal-token", OPERATIONS: "sentinel-token", RESEARCH: "lab-token"}
    assert OfficialTelegramTransport(destination=OPERATIONS)._resolve().config.telegram_bot_token == "sentinel-token"


def test_no_cross_send_between_signal_sentinel_and_lab(env):
    sent = _capture_sends(env)
    OfficialTelegramTransport().send("trade", meta={"dedup_key": "a"})
    assert {t for t, _, _ in sent} == {"signal-token"}


# ------------------------------------------------------------------------------------------- release-gate hardening
def _gate(tmp_path, env, **kw):
    return rg.evaluate_release_readiness(db_path=tmp_path / "none.db", pricing_mode="sip", deliver=True,
                                         transport="telegram", env=env, http_get=acc._Ready(),
                                         now=lambda: acc.clk(acc.date(2026, 10, 5)), **kw)


def _checks(rep):
    return {c.name: c for c in rep.checks}


def test_gate_passes_when_the_transport_binds_the_signal_destination_and_the_bot_is_live(tmp_path):
    env, vp = acc.good_env(tmp_path)
    env = dict(env, TELEGRAM_BOT_TOKEN=LEGACY)                    # the revoked legacy token is present but irrelevant
    rep = _gate(tmp_path, env, validation_path=vp, bot_identity_check=lambda tok: (tok == "sig-token-SECRET", "@TalonXSignalBot"))
    c = _checks(rep)
    assert c["signal_transport_binding"].status == "PASS" and c["signal_transport_bot_live"].status == "PASS"
    assert "SECRET" not in json.dumps(rep.to_dict())               # no token/chat value ever emitted


def test_gate_fails_when_the_resolved_signal_token_is_revoked(tmp_path):
    env, vp = acc.good_env(tmp_path)
    rep = _gate(tmp_path, env, validation_path=vp, bot_identity_check=lambda tok: (False, "HTTP 401"))
    c = _checks(rep)
    assert c["signal_transport_bot_live"].status == "FAIL" and "signal_transport_bot_live" in {x.name for x in rep.failed}
    assert rep.status != "READY"


def test_gate_fails_when_the_transport_resolves_a_different_credential_source(tmp_path, monkeypatch):
    env, vp = acc.good_env(tmp_path)
    from talonx_dispatch.config import DispatchConfig
    from talonx_dispatch.telegram_client import TelegramClient
    monkeypatch.setattr(OfficialTelegramTransport, "_resolve", lambda self: TelegramClient(
        config=DispatchConfig(telegram_bot_token=LEGACY, telegram_chat_id="legacy-chat")))   # the pre-fix behaviour
    rep = _gate(tmp_path, env, validation_path=vp, bot_identity_check=lambda tok: (True, "@x"))
    assert _checks(rep)["signal_transport_binding"].status == "FAIL" and rep.status != "READY"


def test_gate_fails_when_the_trade_event_destination_is_disabled(tmp_path):
    env, vp = acc.good_env(tmp_path)
    env = {k: v for k, v in env.items() if not k.startswith("TALONX_NOTIFY_TRADE_EVENT")}
    rep = _gate(tmp_path, env, validation_path=vp, bot_identity_check=lambda tok: (True, "@x"))
    assert _checks(rep)["signal_transport_binding"].status == "FAIL"


def test_identity_helper_never_returns_the_token(monkeypatch):
    import urllib.error
    import urllib.request

    def boom(url, timeout):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", None, None)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    live, who = rg.telegram_bot_identity("tok-SECRET")
    assert live is False and who == "HTTP 401" and "SECRET" not in who


def test_the_routing_fix_does_not_touch_the_strategy_fingerprint():
    assert rg._strategy_fingerprint() == rg.RELEASE_PROFILE.strategy_fingerprint
