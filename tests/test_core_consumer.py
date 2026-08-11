"""
tests/test_core_consumer.py
--------------------------------
Tests talonx_core.consumer.DecisionEngine's message-handling orchestration:
route a message to the right channel handler, update the correlator, run
the decision matrix, and publish an alert only when the matrix actually
produces one. The Redis client is mocked (AsyncMock) -- this is about the
orchestration logic, not real Redis I/O, same boundary the rest of this
project's consumer tests use. The state STORE, where used below, is a
real TickerStateStore (real sqlite3, tmp_path-backed) rather than a
mock -- same "exercise local disk I/O for real" choice test_ledger.py
makes, since sqlite3 isn't the kind of external dependency this project
mocks (Redis, Gemini, ChromaDB are).

Requires pytest-asyncio (see requirements-dev.txt) for the
@pytest.mark.asyncio tests below.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_core.config import CoreConfig
from talonx_core.consumer import DecisionEngine
from talonx_core.state import TickerCorrelator
from talonx_core.store import TickerStateStore


def _signal_payload(direction: str = "bullish") -> dict:
    return {
        "ticker": "AAPL",
        "signal_type": "rsi_oversold_volume_surge",
        "direction": direction,
        "message": "RSI oversold with volume surge",
        "price": 200.0,
        "bar_timestamp": "2026-08-07T12:00:00Z",
    }


def _report_payload(verdict: str = "bullish", confidence: float = 0.8) -> dict:
    return {
        "ticker": "AAPL",
        "triggering_signal": _signal_payload(),
        "verdict": verdict,
        "confidence": confidence,
        "summary": "Fundamentals support the move.",
        "key_findings": [],
        "risk_factors": [],
        "citations": [],  # present on the real wire payload; must be safely ignored
        "model_used": "gemini-flash-latest",
        "generated_at": "2026-08-07T12:00:30Z",
        "published_at": "2026-08-07T12:00:30Z",
    }


def _message(channel: str, payload: dict) -> dict:
    return {"channel": channel.encode(), "data": json.dumps(payload)}


@pytest.fixture
def engine():
    engine = DecisionEngine(config=CoreConfig())
    engine._client = AsyncMock()
    return engine


@pytest.mark.asyncio
async def test_signal_alone_does_not_publish_an_alert(engine):
    await engine._handle_message(_message(engine.config.signals_channel, _signal_payload()))

    assert engine.signals_processed == 1
    engine._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_alone_does_not_publish_an_alert(engine):
    await engine._handle_message(_message(engine.config.reports_channel, _report_payload()))

    assert engine.reports_processed == 1
    engine._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_signal_then_matching_report_publishes_confirmed_alert(engine):
    await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bullish")))
    await engine._handle_message(
        _message(engine.config.reports_channel, _report_payload("bullish", confidence=0.9))
    )

    engine._client.publish.assert_awaited_once()
    channel, payload = engine._client.publish.await_args.args
    assert channel == engine.config.alerts_channel
    body = json.loads(payload)
    assert body["ticker"] == "AAPL"
    assert body["action"] == "confirmed_bullish"
    assert engine.alerts_published == 1


@pytest.mark.asyncio
async def test_report_then_matching_signal_publishes_alert_regardless_of_arrival_order(engine):
    await engine._handle_message(
        _message(engine.config.reports_channel, _report_payload("bearish", confidence=0.9))
    )
    await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bearish")))

    engine._client.publish.assert_awaited_once()
    body = json.loads(engine._client.publish.await_args.args[1])
    assert body["action"] == "confirmed_bearish"


@pytest.mark.asyncio
async def test_second_correlated_pair_within_cooldown_is_suppressed(engine):
    await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bullish")))
    await engine._handle_message(
        _message(engine.config.reports_channel, _report_payload("bullish", confidence=0.9))
    )
    assert engine._client.publish.await_count == 1

    # A new signal arrives for the same ticker moments later -- still
    # within the default 300s cooldown, so no second alert.
    await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bullish")))
    assert engine._client.publish.await_count == 1
    assert engine.signals_processed == 2


@pytest.mark.asyncio
async def test_drops_unparseable_json(engine):
    await engine._handle_message({"channel": engine.config.signals_channel.encode(), "data": "not json"})

    assert engine.signals_processed == 0
    engine._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_drops_invalid_payload_on_known_channel(engine):
    bad_payload = {"ticker": "AAPL"}  # missing required fields
    await engine._handle_message(_message(engine.config.signals_channel, bad_payload))

    assert engine.signals_processed == 0
    engine._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_drops_message_on_unexpected_channel(engine):
    await engine._handle_message(_message("some:other:channel", _signal_payload()))

    assert engine.signals_processed == 0
    assert engine.reports_processed == 0
    engine._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_low_confidence_report_does_not_publish(engine):
    await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bullish")))
    await engine._handle_message(
        _message(engine.config.reports_channel, _report_payload("bullish", confidence=0.1))
    )

    engine._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_handling_a_signal_persists_it_to_the_store(tmp_path):
    with TickerStateStore(tmp_path / "core_state.db") as store:
        engine = DecisionEngine(config=CoreConfig(), store=store)
        engine._client = AsyncMock()

        await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bullish")))

        # A brand-new correlator, rehydrated from the SAME store instance --
        # proves the write-through actually landed on disk, not just in
        # engine.correlator's in-memory dict.
        fresh_correlator = TickerCorrelator()
        loaded = store.load_into(fresh_correlator)

    assert loaded == 1
    assert fresh_correlator.get_or_create("AAPL").latest_signal is not None


@pytest.mark.asyncio
async def test_confirmed_alert_persists_report_and_cooldown(tmp_path):
    path = tmp_path / "core_state.db"
    with TickerStateStore(path) as store:
        engine = DecisionEngine(config=CoreConfig(), store=store)
        engine._client = AsyncMock()

        await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bullish")))
        await engine._handle_message(
            _message(engine.config.reports_channel, _report_payload("bullish", confidence=0.9))
        )

    engine._client.publish.assert_awaited_once()

    # Reopen fresh, as if the process had restarted right after the alert.
    fresh_correlator = TickerCorrelator()
    with TickerStateStore(path) as store2:
        store2.load_into(fresh_correlator)

    state = fresh_correlator.get_or_create("AAPL")
    assert state.latest_signal is not None
    assert state.latest_report is not None
    assert state.last_alert_at is not None  # cooldown survives the restart too


@pytest.mark.asyncio
async def test_suppressed_evaluation_persists_a_reason(tmp_path):
    with TickerStateStore(tmp_path / "core_state.db") as store:
        engine = DecisionEngine(config=CoreConfig(min_confidence=0.5), store=store)
        engine._client = AsyncMock()

        await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bullish")))
        await engine._handle_message(
            _message(engine.config.reports_channel, _report_payload("bullish", confidence=0.1))
        )

        rows = store.suppression_counts_for_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    # The first message (signal alone) is itself a MISSING_PAIR
    # suppression -- both get recorded.
    by_reason = {r["reason"]: r for r in rows}
    assert by_reason["LOW_CONFIDENCE"]["ticker"] == "AAPL"
    assert by_reason["MISSING_PAIR"]["ticker"] == "AAPL"


@pytest.mark.asyncio
async def test_a_published_alert_does_not_also_record_a_suppression(tmp_path):
    with TickerStateStore(tmp_path / "core_state.db") as store:
        engine = DecisionEngine(config=CoreConfig(), store=store)
        engine._client = AsyncMock()

        await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bullish")))
        await engine._handle_message(
            _message(engine.config.reports_channel, _report_payload("bullish", confidence=0.9))
        )

        # The signal-alone message above IS a suppression (MISSING_PAIR),
        # but the second message that completes the pair must not also
        # record one -- it published an alert instead.
        rows = store.suppression_counts_for_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    assert len(rows) == 1
    assert rows[0]["reason"] == "MISSING_PAIR"


@pytest.mark.asyncio
async def test_no_store_means_no_persistence_attempted(engine):
    # The default `engine` fixture has store=None -- this should just be a
    # normal in-memory run, no AttributeError from a missing store.
    assert engine.store is None
    await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bullish")))
    assert engine.signals_processed == 1
