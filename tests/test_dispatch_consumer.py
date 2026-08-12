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
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.consumer import DispatchAgent
from talonx_dispatch.store import AuditStore
from talonx_dispatch.telegram_client import TelegramSendError
from talonx_watchlist.store import TickerWatchlistStore


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


def _trade_execution_payload(order_type: str = "SELL") -> dict:
    now = "2026-08-10T14:37:00Z"
    return {
        "trade_id": 12, "ticker": "SPCX", "order_type": order_type,
        "execution_price": 135.60, "shares": 18.5185, "position_cost": 2500.0,
        "entry_price": 135.00, "realized_pnl_usd": 44.81, "realized_pnl_pct": 0.45,
        "portfolio_cash_after": 10177.68, "triggering_action": "contradicted",
        "session_realized_pnl_usd": 177.68, "session_realized_pnl_pct": 1.78,
        "timestamp": now,
    }


def _trade_message(payload) -> dict:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return {"channel": b"talonx:paper:trades", "data": data}


@pytest.fixture
def agent(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    watchlist_store = TickerWatchlistStore(tmp_path / "watchlist.db")
    watchlist_store.add_ticker("AAPL", "Apple Inc.")
    watchlist_store.add_ticker("SPCX", "SpaceX Holdings")
    telegram_client = AsyncMock()
    telegram_client.is_configured = False  # tests override per-case

    agent = DispatchAgent(
        config=DispatchConfig(), store=store, telegram_client=telegram_client,
        watchlist_store=watchlist_store,
    )
    agent._client = AsyncMock()
    yield agent
    store.close()
    watchlist_store.close()


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


@pytest.mark.asyncio
async def test_telegram_push_uses_the_short_summary_format(agent):
    agent.telegram_client.is_configured = True
    await agent._handle_message(_message(_alert_payload(severity="critical")))

    text = agent.telegram_client.send.await_args.args[0]
    row = agent.store.recent(limit=1)[0]
    assert f"#{row['id']}" in text
    assert "Reply with" in text
    # The full research writeup no longer goes out in the push itself.
    assert "summary text" not in text


@pytest.mark.asyncio
async def test_trade_execution_sends_its_own_short_push(agent):
    agent.telegram_client.is_configured = True

    await agent._handle_message(_trade_message(_trade_execution_payload()))

    agent.telegram_client.send.assert_awaited_once()
    text = agent.telegram_client.send.await_args.args[0]
    assert "SPCX" in text
    assert "SELL EXECUTED" in text
    # Not recorded in the alert audit trail -- talonx_paper's own
    # trade_history is the durable record for this, not this store.
    assert agent.store.count() == 0
    assert agent.alerts_processed == 0


@pytest.mark.asyncio
async def test_trade_execution_skipped_when_telegram_not_configured(agent):
    agent.telegram_client.is_configured = False

    await agent._handle_message(_trade_message(_trade_execution_payload()))

    agent.telegram_client.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_unparseable_trade_execution_is_dropped(agent):
    agent.telegram_client.is_configured = True

    await agent._handle_message(_trade_message("not json"))

    agent.telegram_client.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_trade_execution_payload_is_dropped(agent):
    agent.telegram_client.is_configured = True

    await agent._handle_message(_trade_message({"ticker": "SPCX"}))  # missing required fields

    agent.telegram_client.send.assert_not_awaited()


def test_stop_also_stops_the_reply_listener(agent):
    agent.stop()
    assert agent.reply_listener._stop_event.is_set()


@pytest.mark.asyncio
async def test_retention_sweep_purges_stale_alerts(agent):
    old_payload = _alert_payload()
    old_payload["correlated_at"] = (datetime(2026, 1, 1, tzinfo=timezone.utc)).isoformat()
    await agent._handle_message(_message(old_payload))
    assert agent.store.count() == 1

    purged = await agent._run_retention_sweep_once()

    assert purged == 1
    assert agent.store.count() == 0
    assert agent.alerts_purged == 1


@pytest.mark.asyncio
async def test_retention_sweep_leaves_recent_alerts_alone(agent):
    await agent._handle_message(_message(_alert_payload()))  # correlated_at defaults to "now" (2026-08-07)

    purged = await agent._run_retention_sweep_once()

    assert purged == 0
    assert agent.store.count() == 1


# --- Company name + timestamp (looked up from talonx_watchlist) -----------

@pytest.mark.asyncio
async def test_telegram_push_includes_company_name_and_timestamp(agent):
    agent.telegram_client.is_configured = True
    await agent._handle_message(_message(_alert_payload(severity="critical")))

    text = agent.telegram_client.send.await_args.args[0]
    assert "Apple Inc." in text
    assert "2026-08-07" in text  # correlated_at's date


@pytest.mark.asyncio
async def test_telegram_push_omits_company_name_for_an_untracked_ticker(agent):
    agent.telegram_client.is_configured = True
    payload = _alert_payload(severity="critical")
    payload["ticker"] = "ZZZZ"  # not on the fixture's watchlist
    payload["triggering_signal"]["ticker"] = "ZZZZ"
    await agent._handle_message(_message(payload))

    text = agent.telegram_client.send.await_args.args[0]
    assert "ZZZZ" in text
    assert "(" not in text.split("•")[0]  # no company-name parens before the ID marker


@pytest.mark.asyncio
async def test_trade_execution_push_includes_company_name_and_timestamp(agent):
    agent.telegram_client.is_configured = True
    await agent._handle_message(_trade_message(_trade_execution_payload()))

    text = agent.telegram_client.send.await_args.args[0]
    assert "SpaceX Holdings" in text
    assert "2026-08-10" in text  # execution timestamp's date


@pytest.mark.asyncio
async def test_watchlist_lookup_failure_does_not_block_the_push(agent):
    agent.telegram_client.is_configured = True
    agent.watchlist_store.get_ticker = lambda ticker: (_ for _ in ()).throw(RuntimeError("db locked"))

    await agent._handle_message(_message(_alert_payload(severity="critical")))

    agent.telegram_client.send.assert_awaited_once()  # still sent, just without a company name


def test_invalid_min_severity_config_falls_back_to_warning(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    watchlist_store = TickerWatchlistStore(tmp_path / "watchlist.db")
    config = DispatchConfig(telegram_min_severity="not_a_real_severity")
    agent = DispatchAgent(
        config=config, store=store, telegram_client=AsyncMock(), watchlist_store=watchlist_store,
    )
    try:
        from talonx_dispatch.schemas import AlertSeverity
        assert agent._min_severity == AlertSeverity.WARNING
    finally:
        store.close()
        watchlist_store.close()


# ==========================================================================
# Phase 2 LONG_TERM path
# ==========================================================================

def _long_term_alert_payload(severity: str = "critical") -> dict:
    now = "2026-08-07T12:00:00Z"
    return {
        "ticker": "AAPL", "action": "high_conviction_buy", "severity": severity,
        "rationale": "FY2025 fundamentals clear thresholds.",
        "quality_score": 8, "moat_rating": "wide", "market_price": 75.0,
        "intrinsic_fair_value": 100.0, "margin_of_safety_pct": 0.25,
        "capital_allocation_assessment": "Disciplined buybacks.",
        "key_findings": [], "risk_factors": [],
        "model_used": "gemini-flash-latest", "correlated_at": now, "published_at": now,
    }


def _long_term_message(payload) -> dict:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return {"channel": b"talonx:alerts:longterm", "data": data}


def _long_term_trade_execution_payload(order_type: str = "BUY") -> dict:
    now = "2026-08-10T14:37:00Z"
    return {
        "trade_id": 7, "ticker": "AAPL", "order_type": order_type, "execution_price": 100.0,
        "shares": 20.0, "contribution_cost": 2000.0, "avg_cost_basis_after": 100.0,
        "total_shares_after": 20.0, "portfolio_cash_after": 18000.0,
        "triggering_action": "high_conviction_buy", "timestamp": now,
    }


def _long_term_trade_message(payload) -> dict:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return {"channel": b"talonx:paper:trades:longterm", "data": data}


@pytest.mark.asyncio
async def test_long_term_alert_always_recorded_even_when_telegram_not_configured(agent):
    await agent._handle_message(_long_term_message(_long_term_alert_payload()))

    assert agent.long_term_alerts_processed == 1
    assert agent.store.count_long_term() == 1
    agent.telegram_client.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_long_term_telegram_sent_when_configured_and_severity_clears_threshold(agent):
    agent.telegram_client.is_configured = True
    await agent._handle_message(_long_term_message(_long_term_alert_payload(severity="critical")))

    agent.telegram_client.send.assert_awaited_once()
    row = agent.store.recent_long_term(limit=1)[0]
    assert row["telegram_sent"] is True
    assert agent.long_term_telegram_sent == 1


@pytest.mark.asyncio
async def test_long_term_telegram_skipped_when_below_min_severity(agent):
    agent.telegram_client.is_configured = True
    await agent._handle_message(_long_term_message(_long_term_alert_payload(severity="info")))

    agent.telegram_client.send.assert_not_awaited()
    row = agent.store.recent_long_term(limit=1)[0]
    assert row["telegram_sent"] is False
    assert agent.long_term_alerts_processed == 1


@pytest.mark.asyncio
async def test_long_term_telegram_failure_is_recorded_not_raised(agent):
    agent.telegram_client.is_configured = True
    agent.telegram_client.send.side_effect = TelegramSendError("bad token")

    await agent._handle_message(_long_term_message(_long_term_alert_payload(severity="critical")))

    row = agent.store.recent_long_term(limit=1)[0]
    assert row["telegram_sent"] is False
    assert "bad token" in row["telegram_error"]
    assert agent.long_term_telegram_failed == 1


@pytest.mark.asyncio
async def test_long_term_alert_and_intraday_alert_are_independent(agent):
    agent.telegram_client.is_configured = True
    await agent._handle_message(_message(_alert_payload(severity="critical")))
    await agent._handle_message(_long_term_message(_long_term_alert_payload(severity="critical")))

    assert agent.alerts_processed == 1
    assert agent.long_term_alerts_processed == 1
    assert agent.store.count() == 1
    assert agent.store.count_long_term() == 1
    assert agent.telegram_client.send.await_count == 2


@pytest.mark.asyncio
async def test_long_term_push_uses_the_lt_prefixed_id_format(agent):
    agent.telegram_client.is_configured = True
    await agent._handle_message(_long_term_message(_long_term_alert_payload(severity="critical")))

    text = agent.telegram_client.send.await_args.args[0]
    row = agent.store.recent_long_term(limit=1)[0]
    assert f"#LT{row['id']}" in text
    assert f"Reply with LT{row['id']}" in text


@pytest.mark.asyncio
async def test_long_term_trade_execution_sends_its_own_short_push(agent):
    agent.telegram_client.is_configured = True

    await agent._handle_message(_long_term_trade_message(_long_term_trade_execution_payload()))

    agent.telegram_client.send.assert_awaited_once()
    text = agent.telegram_client.send.await_args.args[0]
    assert "AAPL" in text
    assert "POSITION OPENED" in text
    # Not recorded in the long_term_alerts audit trail -- talonx_paper's
    # own long_term_trade_history is the durable record for this.
    assert agent.store.count_long_term() == 0
    assert agent.long_term_alerts_processed == 0


@pytest.mark.asyncio
async def test_long_term_trade_execution_skipped_when_telegram_not_configured(agent):
    agent.telegram_client.is_configured = False

    await agent._handle_message(_long_term_trade_message(_long_term_trade_execution_payload()))

    agent.telegram_client.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_unparseable_long_term_alert_is_dropped(agent):
    await agent._handle_message(_long_term_message("not json"))
    assert agent.long_term_alerts_processed == 0


@pytest.mark.asyncio
async def test_invalid_long_term_alert_payload_is_dropped(agent):
    await agent._handle_message(_long_term_message({"ticker": "AAPL"}))
    assert agent.long_term_alerts_processed == 0


@pytest.mark.asyncio
async def test_unparseable_long_term_trade_execution_is_dropped(agent):
    agent.telegram_client.is_configured = True
    await agent._handle_message(_long_term_trade_message("not json"))
    agent.telegram_client.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_long_term_retention_sweep_purges_stale_alerts(agent):
    old_payload = _long_term_alert_payload()
    old_payload["correlated_at"] = (datetime(2026, 1, 1, tzinfo=timezone.utc)).isoformat()
    await agent._handle_message(_long_term_message(old_payload))
    assert agent.store.count_long_term() == 1

    purged = await agent._run_retention_sweep_once()

    assert purged == 1
    assert agent.store.count_long_term() == 0
    assert agent.long_term_alerts_purged == 1


@pytest.mark.asyncio
async def test_retention_sweep_purges_both_horizons_independently(agent):
    old_intraday = _alert_payload()
    old_intraday["correlated_at"] = "2026-01-01T00:00:00Z"
    old_long_term = _long_term_alert_payload()
    old_long_term["correlated_at"] = "2026-01-01T00:00:00Z"
    await agent._handle_message(_message(old_intraday))
    await agent._handle_message(_long_term_message(old_long_term))

    purged = await agent._run_retention_sweep_once()

    assert purged == 2
    assert agent.store.count() == 0
    assert agent.store.count_long_term() == 0
