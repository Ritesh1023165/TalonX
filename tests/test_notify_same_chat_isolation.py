"""Notification contract: Signal / Sentinel / Lab may share ONE private chat_id.

Isolation is enforced by logical destination + bot identity + event contract, never by chat_id
uniqueness: a Telegram chat_id names the conversation, a bot token names the sender, and the
owner's private chat_id is identical for every bot. What must never be shared is a bot token.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_ops.notify import (OPERATIONS, RESEARCH, TRADE_EVENT, resolve_destination_config,
                               telegram_client_for)
from talonx_ops.notify.outbox import NotifyStore
from talonx_ops.notify.worker import drain

REPO = Path(__file__).resolve().parents[1]
CHAT = "4242424242"                                   # one private owner chat for all three bots
TOKENS = {TRADE_EVENT: "111:signal-bot", OPERATIONS: "222:sentinel-bot", RESEARCH: "333:lab-bot"}
_ENV_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TALONX_NOTIFY_RESEARCH_ENABLED",
             *(f"TALONX_NOTIFY_{d}_{k}" for d in (TRADE_EVENT, OPERATIONS, RESEARCH) for k in ("BOT_TOKEN", "CHAT_ID")))


@pytest.fixture
def same_chat(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    for d, tok in TOKENS.items():
        monkeypatch.setenv(f"TALONX_NOTIFY_{d}_BOT_TOKEN", tok)
        monkeypatch.setenv(f"TALONX_NOTIFY_{d}_CHAT_ID", CHAT)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKENS[TRADE_EVENT])
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "1")
    return monkeypatch


class _Bot:
    """Transport double that records which bot identity sent what."""

    def __init__(self, token, log):
        self.token, self.log = token, log

    def send(self, text, *, meta):
        self.log.append((self.token, meta["destination"], meta["event_type"], text))
        return {"ok": True, "ref": f"fake:{meta['event_id']}"}


def _enqueue(store, dest, eid, etype):
    return store.enqueue(event_id=eid, destination=dest, event_type=etype, producer="test", dedup_key=eid,
                         payload_text=f"{dest} payload", provenance={},
                         deliver_by_utc=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat())


# 1 -- same chat_id + distinct bot tokens is allowed
def test_research_destination_allows_same_chat_with_distinct_bot(same_chat):
    cfgs = {d: resolve_destination_config(d) for d in (TRADE_EVENT, OPERATIONS, RESEARCH)}
    assert all(c.enabled for c in cfgs.values()), {d: c.reason for d, c in cfgs.items()}
    assert {c.chat_id for c in cfgs.values()} == {CHAT}
    assert {d: c.bot_token for d, c in cfgs.items()} == TOKENS


# 2 -- same chat_id: each destination resolves and drains through ITS OWN bot only
def test_same_chat_id_preserves_destination_isolation(same_chat, tmp_path):
    for d in (TRADE_EVENT, OPERATIONS, RESEARCH):
        assert telegram_client_for(d).config.telegram_bot_token == TOKENS[d]
    store = NotifyStore(str(tmp_path / "outbox.db"))
    for d, etype in ((TRADE_EVENT, "ENTRY"), (OPERATIONS, "DEGRADED_HEALTH"), (RESEARCH, "PREMARKET_RESEARCH_TEST")):
        _enqueue(store, d, f"e-{d}", etype)
    log = []
    for d in (TRADE_EVENT, OPERATIONS, RESEARCH):
        drain(store, destination=d, client=_Bot(resolve_destination_config(d).bot_token, log))
    assert sorted((tok, dest) for tok, dest, _, _ in log) == sorted((TOKENS[d], d) for d in TOKENS)
    assert [tok for tok, dest, _, _ in log if dest == RESEARCH] == [TOKENS[RESEARCH]]
    assert TOKENS[RESEARCH] not in [tok for tok, dest, _, _ in log if dest != RESEARCH]


# 3 / 4 -- a reused bot token is rejected (Signal, Sentinel, legacy primary)
@pytest.mark.parametrize("alias_of", ["TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN", "TALONX_NOTIFY_OPERATIONS_BOT_TOKEN",
                                      "TELEGRAM_BOT_TOKEN"])
def test_research_destination_rejects_bot_alias(same_chat, alias_of):
    same_chat.setenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN", "999:shared-bot")
    same_chat.setenv(alias_of, "999:shared-bot")
    cfg = resolve_destination_config(RESEARCH)
    assert cfg.enabled is False and cfg.bot_token is None and "aliases" in cfg.reason
    assert telegram_client_for(RESEARCH) is None


def test_research_destination_rejects_signal_bot_alias(same_chat):
    same_chat.setenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN", TOKENS[TRADE_EVENT])
    assert "TRADE_EVENT" in resolve_destination_config(RESEARCH).reason
    assert not resolve_destination_config(RESEARCH).enabled


def test_research_destination_rejects_sentinel_bot_alias(same_chat):
    same_chat.setenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN", TOKENS[OPERATIONS])
    assert "OPERATIONS" in resolve_destination_config(RESEARCH).reason
    assert not resolve_destination_config(RESEARCH).enabled


# no fallback in either direction
def test_research_never_falls_back_to_signal_or_sentinel(same_chat, tmp_path):
    same_chat.delenv("TALONX_NOTIFY_RESEARCH_BOT_TOKEN")
    cfg = resolve_destination_config(RESEARCH)
    assert not cfg.enabled and cfg.bot_token is None                      # no borrowing of Signal/Sentinel/legacy
    store = NotifyStore(str(tmp_path / "o.db"))
    _enqueue(store, RESEARCH, "r1", "PREMARKET_RESEARCH_TEST")
    log = []
    for d in (TRADE_EVENT, OPERATIONS):
        assert drain(store, destination=d, client=_Bot(TOKENS[d], log))["considered"] == 0
    assert drain(store, destination=RESEARCH, client=_Bot("x", log))["skipped_disabled"] == 1
    assert log == [] and store.all_outbox(destination=RESEARCH)[0]["state"] == "PENDING"


def test_signal_and_sentinel_never_use_the_lab_bot(same_chat):
    for d in (TRADE_EVENT, OPERATIONS):
        same_chat.delenv(f"TALONX_NOTIFY_{d}_BOT_TOKEN")
    same_chat.delenv("TELEGRAM_BOT_TOKEN")
    for d in (TRADE_EVENT, OPERATIONS):
        cfg = resolve_destination_config(d)
        assert not cfg.enabled and cfg.bot_token != TOKENS[RESEARCH]


# 5 / 6 / 7 -- research event contract + protected DBs
def test_research_router_emits_only_research_events_and_refuses_protected_dbs(same_chat, tmp_path):
    from talonx_premarket.__main__ import PROTECTED_DB_NAMES, _router
    assert PROTECTED_DB_NAMES >= {"v2_release_rc1_notifications.db", "notifications.db", "v2_release_rc1.db",
                                  "v2_lane.db"}
    for name in PROTECTED_DB_NAMES:
        with pytest.raises(SystemExit):
            _router(True, tmp_path / name)
    db = tmp_path / "premarket_research_notifications.db"
    route, _, _, _ = _router(True, db)
    alert = {"alert_id": "a1", "decision_utc": "2026-09-24T09:00:00+00:00", "alert_type": "NEW",
             "text": "t", "candidate_id": "c1", "symbol": "ZZZZ"}
    assert route(alert) == "ENQUEUED_RESEARCH"
    rows = NotifyStore(str(db)).all_outbox()
    assert [(r["destination"], r["event_type"][:18]) for r in rows] == [(RESEARCH, "PREMARKET_RESEARCH")]
    assert json.loads(rows[0]["provenance_json"])["not_a_trade_event"] is True


def test_research_lane_has_no_v2_order_ledger_or_campaign_path():
    banned = ("talonx_v2", "talonx_dispatch", "alpaca_trade_api", "talonx_ops.prospective")
    for f in (REPO / "talonx_premarket").glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not [m for m in mods if m.startswith(banned)], (f.name, mods)
        src = f.read_text(encoding="utf-8")
        for dest in ("destination=TRADE_EVENT", "destination=OPERATIONS"):
            assert dest not in src, f.name


# 9 -- dedup: the same event identity never produces a second send
def test_same_event_identity_is_sent_once(same_chat, tmp_path):
    store = NotifyStore(str(tmp_path / "o.db"))
    log = []
    assert _enqueue(store, RESEARCH, "lab-test", "PREMARKET_RESEARCH_TEST") is True
    assert drain(store, destination=RESEARCH, client=_Bot(TOKENS[RESEARCH], log))["sent"] == 1
    assert _enqueue(store, RESEARCH, "lab-test", "PREMARKET_RESEARCH_TEST") is False
    assert drain(store, destination=RESEARCH, client=_Bot(TOKENS[RESEARCH], log))["considered"] == 0
    assert len(log) == 1 and len(store.all_outbox()) == 1


# 10 -- default OFF: fully configured Lab still sends nothing without the explicit enable
def test_lab_is_off_without_explicit_enable(same_chat, tmp_path):
    same_chat.delenv("TALONX_NOTIFY_RESEARCH_ENABLED")
    assert not resolve_destination_config(RESEARCH).enabled
    same_chat.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "0")
    assert not resolve_destination_config(RESEARCH).enabled
    store = NotifyStore(str(tmp_path / "o.db"))
    _enqueue(store, RESEARCH, "r", "PREMARKET_RESEARCH_TEST")
    log = []
    assert drain(store, destination=RESEARCH, client=_Bot(TOKENS[RESEARCH], log))["skipped_disabled"] == 1
    assert log == []


# 11 -- V2 release gate: same chat across bots does not affect readiness; Lab ON in the V2 env still fails lab_off
def test_release_gate_ready_with_shared_chat_and_lab_configured_but_off(tmp_path):
    import talonx_v2.release_gate as rg
    from talonx_ops.operator_read import _destination_fingerprint
    from test_v2_final_release_acceptance import gate, good_env
    env, _ = good_env(tmp_path)
    shared = dict(env, TALONX_NOTIFY_TRADE_EVENT_CHAT_ID=CHAT, TALONX_NOTIFY_OPERATIONS_CHAT_ID=CHAT,
                  TALONX_NOTIFY_RESEARCH_BOT_TOKEN="333:lab-bot", TALONX_NOTIFY_RESEARCH_CHAT_ID=CHAT,
                  TALONX_NOTIFY_RESEARCH_ENABLED="0")
    with rg._scoped_env(shared):        # validation evidence bound to the shared-chat config
        fp = {d: _destination_fingerprint(resolve_destination_config(d)) for d in (TRADE_EVENT, OPERATIONS)}
    vp = tmp_path / "v_shared.json"
    vp.write_text(json.dumps({"schema_version": 1, "kind": "ri4_controlled_telegram_validation",
                              "destinations": {d: {"state": "SENT", "configuration_fingerprint": fp[d]}
                                               for d in fp}}))
    rep = gate(tmp_path, env=shared, vpath=vp)
    by = {c.name: c.status for c in rep.checks}
    assert rep.status == "READY", [f"{c.name}: {c.detail}" for c in rep.failed]
    assert by["lab_off"] == "PASS" and by["signal_sentinel_distinct"] == "PASS"
    on = gate(tmp_path, env=dict(shared, TALONX_NOTIFY_RESEARCH_ENABLED="1"), vpath=vp)
    assert "lab_off" in {c.name for c in on.failed}                   # never set the enable in the V2 shell


# 12 -- frozen fingerprints untouched by this contract change
def test_frozen_fingerprints_unchanged():
    assert json.loads((REPO / "talonx_premarket" / "frozen_config.json").read_text())["fingerprint"] == "62ba413daf85e674"
    from talonx_premarket.config import PREMARKET_RESEARCH_V1
    assert PREMARKET_RESEARCH_V1.fingerprint() == "62ba413daf85e674"


def test_research_startup_block_names_destination_and_lab_bot_without_secrets(same_chat, tmp_path):
    from talonx_premarket.__main__ import _router
    *_, info = _router(True, tmp_path / "premarket_research_notifications.db")
    assert info["destination"] == RESEARCH and info["bot"] == "LAB" and info["research_destination_enabled"] is True
    assert TOKENS[RESEARCH] not in json.dumps(info) and CHAT not in json.dumps(info)
    same_chat.setenv("TALONX_NOTIFY_RESEARCH_ENABLED", "0")
    *_, off = _router(True, tmp_path / "premarket_research_notifications.db")
    assert off["bot"] is None and off["research_destination_enabled"] is False
