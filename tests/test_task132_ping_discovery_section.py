"""
tests/test_task132_ping_discovery_section.py
----------------------------------------------
Task 132 section 5/6 — focused tests for the new /ping DISCOVERY / V2 /
DELIVERY block (talonx_dispatch/telegram_listener.py::
TelegramReplyListener._discovery_v2_section) and its size-aware send
(::_send_ping_reply).

Isolated: every snapshot path is monkeypatched to a tmp_path file/db, so
these NEVER touch the real ~/.talonx/ingestion_ledger.db, the real
v2_lane.db, or a real V2 companion status file -- unlike a manual /ping
send, this cannot be affected by (or affect) the live development stack.
"""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.telegram_listener import TelegramReplyListener


def _config(**overrides) -> DispatchConfig:
    defaults = dict(telegram_bot_token="TEST_TOKEN", telegram_chat_id="12345")
    defaults.update(overrides)
    return DispatchConfig(**defaults)


@pytest.fixture
def telegram_client():
    client = AsyncMock()
    client.is_configured = True
    return client


@pytest.fixture
def listener(telegram_client) -> TelegramReplyListener:
    return TelegramReplyListener(store=MagicMock(), config=_config(), telegram_client=telegram_client)


def _make_ledger_db(path, *, delivery_rows=(), text_event_rows=()):
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE text_events (event_id TEXT PRIMARY KEY, ingested_at_utc TEXT)"
    )
    con.execute(
        "CREATE TABLE intelligence_delivery (delivery_id TEXT PRIMARY KEY, state TEXT, sent_at_utc TEXT, "
        "route TEXT DEFAULT 'IMMEDIATE', enqueued_at_utc TEXT, updated_at_utc TEXT)"
    )
    for i, (eid, ts) in enumerate(text_event_rows):
        con.execute("INSERT INTO text_events VALUES (?, ?)", (eid or f"e{i}", ts))
    for i, (did, state, sent) in enumerate(delivery_rows):
        con.execute("INSERT INTO intelligence_delivery (delivery_id, state, sent_at_utc) VALUES (?, ?, ?)",
                    (did or f"d{i}", state, sent))
    con.commit()
    con.close()


# ---------------------------------------------------------------------
# every snapshot unavailable -> "unknown" everywhere, never a fabricated 0
# ---------------------------------------------------------------------

def test_discovery_v2_section_all_unavailable_reports_unknown_not_zero(listener, tmp_path, monkeypatch):
    missing_json = tmp_path / "does_not_exist.json"
    missing_db = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(TelegramReplyListener, "_intel_heartbeat_path", staticmethod(lambda: missing_json))
    monkeypatch.setattr(TelegramReplyListener, "_intel_progress_path", staticmethod(lambda: missing_json))
    monkeypatch.setattr(TelegramReplyListener, "_v2_status_path", staticmethod(lambda: missing_json))
    monkeypatch.setattr(TelegramReplyListener, "_intel_ledger_path", staticmethod(lambda: missing_db))

    lines = listener._discovery_v2_section()
    text = "\n".join(lines)

    assert "DISCOVERY" in text and "V2" in text and "DELIVERY" in text
    assert "unknown" in text
    # the two explicit "unavailable" callouts must be present
    assert "heartbeat file unavailable" in text
    assert "no progress snapshot written yet" in text
    assert "v2_service_status.json unavailable" in text
    assert "ledger DB unavailable" in text
    # never claim zero activity/scope when the source couldn't be read
    assert "Collection scope: 0" not in text
    assert "Execution-eligible scope: 0" not in text


# ---------------------------------------------------------------------
# every snapshot present -> real, correctly-sourced values surface
# ---------------------------------------------------------------------

def test_discovery_v2_section_reads_real_snapshot_files(listener, tmp_path, monkeypatch):
    hb_path = tmp_path / "hb.json"
    hb_path.write_text(json.dumps({
        "mode": "poll:start",
        "scope": {"effective": 39},
        "effective_symbols": ["A"] * 569,
        "metrics": {"source": {"last_successful_poll_utc": None}},
    }), encoding="utf-8")

    prog_path = tmp_path / "progress.json"
    prog_path.write_text(json.dumps({
        "phase": "enriching", "cycle_complete": False, "elapsed_seconds": 9123.4,
        "symbols_done": 569, "symbols_total": 569,
        "events_done": 2565, "events_total": 27598,
    }), encoding="utf-8")

    v2_path = tmp_path / "v2_status.json"
    v2_path.write_text(json.dumps({
        "execution_scope_count": 626,
        "last_tick_utc": "2026-09-14T12:20:37+00:00",
        "ripe_episodes_this_tick": 3,
        "execution_scope_out_of_scope_dropped_this_tick": 16,
        "stale_entry_skipped_this_tick": 1,
        "no_prior_intent_skipped_this_tick": 0,
        "capacity_rejected_this_tick": 0,
        "admission_deadline_rejected_this_tick": 0,
        "pending_entry_intents": [],
        "open_positions": 0,
        "entries_this_tick": 0,
        "exits_this_tick": 0,
        "alert_outbox": {"total": 0, "by_state": {}},
    }), encoding="utf-8")

    ledger_path = tmp_path / "ledger.db"
    _make_ledger_db(
        ledger_path,
        text_event_rows=[(f"e{i}", "2026-09-14T09:50:30") for i in range(5)],
        delivery_rows=[
            ("d1", "PENDING", None), ("d2", "PENDING", None),
            ("d3", "SENT", "2026-09-11T08:15:56"), ("d4", "EXPIRED", None),
        ],
    )

    monkeypatch.setattr(TelegramReplyListener, "_intel_heartbeat_path", staticmethod(lambda: hb_path))
    monkeypatch.setattr(TelegramReplyListener, "_intel_progress_path", staticmethod(lambda: prog_path))
    monkeypatch.setattr(TelegramReplyListener, "_v2_status_path", staticmethod(lambda: v2_path))
    monkeypatch.setattr(TelegramReplyListener, "_intel_ledger_path", staticmethod(lambda: ledger_path))
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")

    text = "\n".join(listener._discovery_v2_section())

    assert "39 watchlist -> 569 effective" in text
    assert "none yet (first cycle still in progress)" in text
    assert "IN PROGRESS (enriching)" in text
    assert "2h" in text  # 9123s -> ~2h32m, distinguishing symbol-fetch elapsed from a stale process uptime
    assert "Issuers polled: 569/569" in text
    assert "New filings enriched: 2,565/27,598" in text
    assert "Execution-eligible scope: 626" in text
    assert "out_of_scope=16" in text
    assert "Admission mode: GATED" in text
    # Session 03 A5: live queue vs historical expiry (talonx_ops.intel_queue), not all-time totals
    assert "LIVE_PENDING: 2" in text and "LIVE_FAILED (24h): 0" in text and "all-time 1;" in text
    assert "2026-09-11T08:15:56" in text  # last successful discovery delivery


def test_discovery_v2_section_admission_mode_permissive_when_env_unset(listener, tmp_path, monkeypatch):
    missing_json = tmp_path / "x.json"
    missing_db = tmp_path / "x.db"
    monkeypatch.setattr(TelegramReplyListener, "_intel_heartbeat_path", staticmethod(lambda: missing_json))
    monkeypatch.setattr(TelegramReplyListener, "_intel_progress_path", staticmethod(lambda: missing_json))
    v2_path = tmp_path / "v2_status.json"
    v2_path.write_text(json.dumps({"execution_scope_count": 626}), encoding="utf-8")
    monkeypatch.setattr(TelegramReplyListener, "_v2_status_path", staticmethod(lambda: v2_path))
    monkeypatch.setattr(TelegramReplyListener, "_intel_ledger_path", staticmethod(lambda: missing_db))
    monkeypatch.delenv("TALONX_V2_DURABLE_STORE_ENABLED", raising=False)

    text = "\n".join(listener._discovery_v2_section())
    assert "Admission mode: PERMISSIVE" in text


# ---------------------------------------------------------------------
# _send_ping_reply -- single message when within budget, two labelled
# messages when the combined text exceeds it (Telegram size-limit rule).
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_ping_reply_single_message_within_budget(listener, telegram_client):
    await listener._send_ping_reply(["short line"], ["also short"])
    telegram_client.send.assert_awaited_once()
    assert telegram_client.send.call_args.kwargs["parse_mode"] is None
    sent = telegram_client.send.call_args.args[0]
    assert "short line" in sent and "also short" in sent


@pytest.mark.asyncio
async def test_send_ping_reply_splits_when_over_budget(listener, telegram_client):
    from talonx_ingest.intelligence.delivery.config import MESSAGE_BUDGET

    lines = ["main ping content"] * 50
    discovery_lines = ["DISCOVERY MARKER LINE " + "x" * 100] * (MESSAGE_BUDGET // 50)

    await listener._send_ping_reply(lines, discovery_lines)

    assert telegram_client.send.await_count == 2
    first = telegram_client.send.call_args_list[0].args[0]
    second = telegram_client.send.call_args_list[1].args[0]
    assert "main ping content" in first
    assert "DISCOVERY MARKER LINE" not in first
    assert "(2/2)" in second
    assert "DISCOVERY MARKER LINE" in second
    for call in telegram_client.send.call_args_list:
        assert call.kwargs["parse_mode"] is None
        assert len(call.args[0]) < 4096
