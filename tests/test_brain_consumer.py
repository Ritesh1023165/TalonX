"""
tests/test_brain_consumer.py
---------------------------------
Tests talonx_brain.consumer.ResearchAgent's message-handling orchestration:
parse QuantSignal -> retrieve citations -> run the LLM chain -> publish a
ResearchReport. The retriever, LLM chain, and Redis client are all mocked
(AsyncMock/MagicMock) here -- this is about the orchestration logic, not
real ChromaDB, Gemini, or Redis I/O, same boundary
test_pipeline_ledger_integration.py uses for talonx_ingest.pipeline.

Requires pytest-asyncio (see requirements-dev.txt) for the
@pytest.mark.asyncio tests below.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_brain.consumer import ResearchAgent, _build_retrieval_query
from talonx_brain.llm import _LLMFindings
from talonx_brain.schemas import (
    Citation,
    CitationSourceType,
    QuantSignal,
    ResearchVerdict,
    SignalDirection,
    SignalType,
)


def _signal_payload() -> dict:
    return {
        "ticker": "NVDA",
        "signal_type": "rsi_oversold_volume_surge",
        "direction": "bullish",
        "message": "RSI 24.3 oversold with 2.8x volume surge",
        "price": 131.5,
        "bar_timestamp": "2026-08-04T12:00:00Z",
    }


@pytest.fixture
def agent():
    retriever = MagicMock()
    retriever.retrieve.return_value = [
        Citation(
            chunk_id="c1",
            excerpt="Data center revenue up 40%.",
            source_type=CitationSourceType.FILING,
            source_document="nvda-10q.htm",
        )
    ]

    llm_chain = AsyncMock()
    llm_chain.model_used = "gemini-flash-latest"  # ResearchReport.model_used is a real str field
    llm_chain.generate.return_value = _LLMFindings(
        verdict=ResearchVerdict.BULLISH,
        confidence=0.8,
        summary="Fundamentals support the surge.",
        key_findings=["Data center revenue up 40% YoY"],
        risk_factors=["Export restrictions"],
    )

    agent = ResearchAgent(retriever=retriever, llm_chain=llm_chain)
    agent._client = AsyncMock()
    return agent


@pytest.mark.asyncio
async def test_handle_message_publishes_research_report(agent):
    message = {"data": json.dumps(_signal_payload())}

    await agent._handle_message(message)

    agent.retriever.retrieve.assert_called_once()
    agent.llm_chain.generate.assert_awaited_once()
    agent._client.publish.assert_awaited_once()

    channel, payload = agent._client.publish.await_args.args
    assert channel == agent.config.reports_channel
    body = json.loads(payload)
    assert body["ticker"] == "NVDA"
    assert body["verdict"] == "bullish"
    assert body["citations"][0]["excerpt"] == "Data center revenue up 40%."

    assert agent.signals_processed == 1
    assert agent.reports_published == 1


@pytest.mark.asyncio
async def test_handle_message_drops_unparseable_payload(agent):
    message = {"data": "not json"}

    await agent._handle_message(message)

    agent.retriever.retrieve.assert_not_called()
    agent.llm_chain.generate.assert_not_awaited()
    agent._client.publish.assert_not_awaited()
    assert agent.signals_processed == 0


@pytest.mark.asyncio
async def test_handle_message_skips_publish_when_report_generation_fails(agent):
    agent.llm_chain.generate.side_effect = RuntimeError("Gemini exploded")
    message = {"data": json.dumps(_signal_payload())}

    await agent._handle_message(message)

    agent._client.publish.assert_not_awaited()
    assert agent.signals_processed == 1
    assert agent.reports_published == 0


def test_build_retrieval_query_includes_ticker_direction_and_message():
    signal = QuantSignal(
        ticker="NVDA",
        signal_type=SignalType.MACD_BULLISH_CROSS,
        direction=SignalDirection.BULLISH,
        message="MACD crossed above signal line",
        price=131.5,
        bar_timestamp=datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc),
    )
    query = _build_retrieval_query(signal)
    assert "NVDA" in query
    assert "bullish" in query
    assert "macd bullish cross" in query
    assert "MACD crossed above signal line" in query
