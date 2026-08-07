"""
tests/test_dispatch_consumer.py
------------------------------------
Tests talonx_dispatch.consumer.DispatchAgent's message-handling
orchestration: parse ActionableAlert -> record to the audit trail ->
maybe send Telegram (gated by is_configured + severity threshold).
The Redis client and TelegramClient are mocked (AsyncMock) -- the audit
STORE is real sqlite3 (tmp_path-backed), same "exercise local disk I/O
for real, mock the external services" boundary the rest of this
project's consumer tests use.

Requires pytest-asyncio (see requirements-dev.txt) for the
@pytest.mark.asyncio tests below.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.consumer import DispatchAgent
from talonx_dispatch.store import AuditStore
from talonx_dispatch.telegram_client import TelegramSendError


def _alert_payload(severity: str = "warning") -> dict:
    now = "2026-08-07T12:00:00Z"
    return {
        "ticker": "AAPL",
        "action": "confirmed_bullish",
        "severity": severity,
        "rationale": "rationale text",
        "quant_direction": "bullish",
        "research_verdict": "bullish",
        "research_confidence": 0.85,
        "triggering_signal": {
            "ticker": "AAPL",
            "signal_type": "rsi_oversold_volume_surge",
            "direction": "bullish",
            "message": "RSI oversold with volume surge",
            "price": 200.0,
            "bar_timestamp": now,
        },
        "research_summary": "summary text",
        "key_findings": [],
        "risk_factors": [],
        "model_used": "gemini-flash-latest",
        "signal_received_at": now,
        "report_received_at": now,
        "correlated_at": now,
        "published_at": now,
    }


def _message(payload) -> dict:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return {"channel": b"talonx:alerts:dispatch", "data": data}


@pytest.fixture
def agent(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    telegram_client = AsyncMock()
    telegram_client.is_configured = False  # tests override per-case

    agent = DispatchAgent(config=DispatchConfig(), store=store, telegram_client=telegram_client)
    agent._client = AsyncMock()
    yield agent
    store.close()


@pytest.mark.asyncio
async def test_alert_always_recorded_even_when_telegram_not_configured(agent):
    await agent._handle_message(_message(_alert_payload()))

    assert agent.alerts_processed == 1
    assert agent.store.count() == 1
    agent.telegram_client.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_sent_when_configured_and_severity_clears_threshold(agent):
    agent.telegram_client.is_configured = True
    await agent._handle_message(_message(_alert_payload(severity="critical")))

    agent.telegram_client.send.assert_awaited_once()
    row = agent.store.recent(limit=1)[0]
    assert row["telegram_sent"] is True
    assert agent.telegram_sent == 1


@pytest.mark.asyncio
async def test_telegram_skipped_when_below_min_severity(agent):
    agent.telegram_client.is_configured = True
    # Default TALONX_DISPATCH_MIN_SEVERITY is "warning" -- "info" should be skipped.
    await agent._handle_message(_message(_alert_payload(severity="info")))

    agent.telegram_client.send.assert_not_awaited()
    row = agent.store.recent(limit=1)[0]
    assert row["telegram_sent"] is False
    # Still recorded in the audit trail regardless of the Telegram filter.
    assert agent.alerts_processed == 1


@pytest.mark.asyncio
async def test_telegram_failure_is_recorded_not_raised(agent):
    agent.telegram_client.is_configured = True
    agent.telegram_client.send.side_effect = TelegramSendError("bad token")

    await agent._handle_message(_message(_alert_payload(severity="critical")))

    row = agent.store.recent(limit=1)[0]
    assert row["telegram_sent"] is False
    assert "bad token" in row["telegram_error"]
    assert agent.telegram_failed == 1


@pytest.mark.asyncio
async def test_drops_unparseable_json(agent):
    await agent._handle_message(_message("not json"))

    assert agent.alerts_processed == 0
    assert agent.store.count() == 0


@pytest.mark.asyncio
async def test_drops_invalid_payload(agent):
    await agent._handle_message(_message({"ticker": "AAPL"}))  # missing required fields

    assert agent.alerts_processed == 0
    assert agent.store.count() == 0


def test_invalid_min_severity_config_falls_back_to_warning(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    config = DispatchConfig(telegram_min_severity="not_a_real_severity")
    agent = DispatchAgent(config=config, store=store, telegram_client=AsyncMock())
    try:
        from talonx_dispatch.schemas import AlertSeverity
        assert agent._min_severity == AlertSeverity.WARNING
    finally:
        store.close()
