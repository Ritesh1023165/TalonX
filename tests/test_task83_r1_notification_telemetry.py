"""Task 83-R1 §5 -- authoritative PIV Telegram zero-attempt evidence.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. No real Telegram request is
possible: PIV outbound is disabled by default and every sender here is a
local fake.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from talonx_compare.notification import assess_piv_notification
from talonx_piv.config import PivConfig
from talonx_piv.events import EventBus, PivEvent
from talonx_piv.notification_telemetry import TELEMETRY_NAME, load_telemetry, merge_telemetry

DATE = "2026-08-28"
SESSION = "piv_2026-08-28_100000_abcd1234"


# --- 5.1 ownership persisted at runtime construction ------------

def test_runtime_persists_notification_ownership(tmp_path, monkeypatch):
    monkeypatch.delenv("TALONX_PIV_TELEGRAM_ENABLED", raising=False)
    from talonx_piv import cli

    cfg = PivConfig(state_dir=tmp_path)
    bus, broker, lifecycle, _ = cli.runtime(cfg, session_id=SESSION)
    tel = load_telemetry(tmp_path)
    assert tel is not None
    assert tel["session_id"] == SESSION
    assert tel["ownership"]["outbound_enabled"] is False
    assert tel["ownership"]["sender_constructed"] is False
    assert bus.telegram_send is None


# --- 5.2 outbound counters persist at the send boundary --------

def test_outbound_counters_persist_at_send_boundary(tmp_path):
    calls = []

    def sender(text):
        calls.append(text)
        return True

    bus = EventBus(tmp_path / "piv_events.jsonl", sender, session_id=SESSION,
                   telemetry_path=tmp_path, trading_date_et=DATE)
    bus.emit(PivEvent.build("SIGNAL", symbol="AAPL"))
    tel = load_telemetry(tmp_path)
    assert tel["outbound"]["attempts"] == 1
    assert tel["outbound"]["successes"] == 1
    assert tel["outbound"]["failures"] == 0
    assert tel["ownership"]["outbound_enabled"] is True


# --- 5.6 enabled sender, failed send -> still one attempt ------

def test_enabled_sender_failed_send_archives_one_attempt(tmp_path):
    def boom(text):
        raise RuntimeError("telegram API down")

    bus = EventBus(tmp_path / "piv_events.jsonl", boom, session_id=SESSION,
                   telemetry_path=tmp_path, trading_date_et=DATE)
    ok = bus.emit(PivEvent.build("SIGNAL", symbol="AAPL"))
    assert ok is False
    tel = load_telemetry(tmp_path)
    assert tel["outbound"]["attempts"] == 1
    assert tel["outbound"]["failures"] == 1
    # the archive must NOT be able to call this zero
    v = assess_piv_notification(tmp_path, SESSION, DATE)
    assert v["verdict"] == "ATTEMPTS_RECORDED"
    assert v["piv_zero_attempt_assertion"] is False


# --- 5.3 inbound poller counters ------------------------------

def test_inbound_poller_counters_persist(tmp_path):
    merge_telemetry(tmp_path, session_id=SESSION, trading_date_et=DATE,
                    ownership={"inbound_poller_constructed": True, "inbound_poller_started": True},
                    inbound_delta={"poll_starts": 1})
    tel = load_telemetry(tmp_path)
    assert tel["inbound"]["poll_starts"] == 1
    assert tel["ownership"]["inbound_poller_started"] is True
    v = assess_piv_notification(tmp_path, SESSION, DATE)
    assert v["verdict"] == "ATTEMPTS_RECORDED"


# --- 5.4 missing telemetry -> UNVERIFIED, never zero ----------

def test_missing_telemetry_is_unverified_not_zero(tmp_path):
    v = assess_piv_notification(tmp_path, SESSION, DATE)
    assert v["verdict"] == "UNVERIFIED"
    assert v["evidence_status"] == "MISSING"
    assert v["piv_zero_attempt_assertion"] is False
    assert "UNVERIFIED" in v["detail"] or "not zero" in v["detail"]


# --- 5.5 zero assertion needs all three conditions ------------

def test_zero_assertion_requires_all_three_conditions(tmp_path):
    # (a) telemetry present for the session
    merge_telemetry(tmp_path, session_id=SESSION, trading_date_et=DATE,
                    ownership={"outbound_enabled": False, "sender_constructed": False,
                              "inbound_poller_constructed": False, "inbound_poller_started": False})
    assert assess_piv_notification(tmp_path, SESSION, DATE)["verdict"] == "VERIFIED_ZERO"

    # (b) wrong session -> not zero
    wrong = assess_piv_notification(tmp_path, "some-other-session", DATE)
    assert wrong["verdict"] == "UNVERIFIED"
    assert wrong["evidence_status"] == "WRONG_SESSION"

    # (c) an ownership flag enabled -> not zero
    merge_telemetry(tmp_path, session_id=SESSION, trading_date_et=DATE,
                    ownership={"outbound_enabled": True})
    assert assess_piv_notification(tmp_path, SESSION, DATE)["verdict"] == "UNVERIFIED"


# --- 5.7 PIV disabled by default ---------------------------

def test_piv_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("TALONX_PIV_TELEGRAM_ENABLED", raising=False)
    cfg = PivConfig(state_dir=tmp_path)
    assert cfg.telegram_enabled is False


# --- 5.8 Original notification ownership untouched ---------

def test_original_notification_ownership_untouched():
    """The shared listener defaults to no telemetry hook for Original."""
    from talonx_dispatch.config import DispatchConfig
    from talonx_dispatch.store import AuditStore
    from talonx_dispatch.telegram_listener import TelegramReplyListener

    listener = TelegramReplyListener(AuditStore(":memory:"), DispatchConfig())
    assert listener.poll_telemetry is None
