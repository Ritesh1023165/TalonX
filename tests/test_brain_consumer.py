"""
tests/test_brain_consumer.py
---------------------------------
Tests talonx_brain.consumer.ResearchAgent's message-handling orchestration:
parse QuantSignal -> check cache -> retrieve citations -> run the LLM
chain -> publish a ResearchReport (Requirement 2's caching, Requirement
4A's cold-start/LLM-outage fallbacks, and filings-channel invalidation).
The retriever, LLM chain, cache, and Redis client are all mocked
(AsyncMock/MagicMock) here -- this is about the orchestration logic, not
real ChromaDB, Gemini, Redis, or cache.py's own boundary/timezone math
(see test_brain_cache.py for that), same boundary
test_pipeline_ledger_integration.py uses for talonx_ingest.pipeline.

Requires pytest-asyncio (see requirements-dev.txt) for the
@pytest.mark.asyncio tests below.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_brain.consumer import (
    ResearchAgent,
    _build_long_term_retrieval_query,
    _build_retrieval_query,
    _categorize,
    _categorize_long_term,
)
from talonx_brain.llm import _LLMFindings, _LLMFindingsLongTerm
from talonx_brain.schemas import (
    Citation,
    CitationSourceType,
    FundamentalFactorSignal,
    LongTermResearchReport,
    MoatRating,
    QuantSignal,
    ResearchReport,
    ResearchVerdict,
    SignalDirection,
    SignalType,
)
from talonx_brain.store import BrainStatsStore


def _signal_payload(ticker: str = "NVDA") -> dict:
    return {
        "ticker": ticker,
        "signal_type": "rsi_oversold_volume_surge",
        "direction": "bullish",
        "message": "RSI 24.3 oversold with 2.8x volume surge",
        "price": 131.5,
        "bar_timestamp": "2026-08-04T12:00:00Z",
    }


def _filing_event_payload(ticker: str = "NVDA") -> dict:
    return {
        "ticker": ticker,
        "cik": "0001045810",
        "company_name": "NVIDIA Corporation",
        "form_type": "10-Q",
        "accession_number": "0001045810-26-000123",
        "filing_date": "2026-08-04",
        "source_document": "nvda-10q.htm",
        "chunk_count": 42,
        "vector_collection": "sec_filings",
    }


def _signal() -> QuantSignal:
    return QuantSignal.model_validate(_signal_payload())


def _report(**overrides) -> ResearchReport:
    defaults = dict(
        ticker="NVDA",
        triggering_signal=_signal(),
        verdict=ResearchVerdict.BULLISH,
        confidence=0.8,
        summary="Fundamentals support the surge.",
        model_used="gemini-flash-latest",
    )
    defaults.update(overrides)
    return ResearchReport(**defaults)


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

    # Always injected (never left to the real build_long_term_research_chain
    # default) -- that default constructs a REAL Gemini/Ollama chain, which
    # would need a live API key/local model just to build a ResearchAgent
    # in a unit test. Individual long-term tests override .generate's
    # return_value/model_used as needed.
    long_term_llm_chain = AsyncMock()
    long_term_llm_chain.model_used = "gemini-flash-latest"
    long_term_llm_chain.generate.return_value = _LLMFindingsLongTerm(
        moat_rating=MoatRating.WIDE,
        capital_allocation_assessment="Disciplined buybacks and reinvestment.",
        dcf_fair_value_per_share=220.0,
        quality_score=8,
        summary="Durable compounder with a wide moat.",
        key_findings=["Strong recurring revenue base"],
        risk_factors=["Regulatory scrutiny"],
    )

    # cache_enabled defaults True, but agent.cache is None until
    # _connect_and_listen runs (never called in these tests) -- every
    # cache-branch check in consumer.py is `cache_enabled and cache is not
    # None`, so leaving it None here reproduces the pre-caching flow for
    # tests that don't care about caching. Tests that DO care inject a
    # cache explicitly via ResearchAgent(cache=...).
    agent = ResearchAgent(retriever=retriever, llm_chain=llm_chain, long_term_llm_chain=long_term_llm_chain)
    agent._client = AsyncMock()
    return agent


def _msg(agent: ResearchAgent, payload: dict, channel: str | None = None) -> dict:
    return {"channel": channel or agent.config.signals_channel, "data": json.dumps(payload)}


# --- Baseline flow (no cache configured) -------------------------------

@pytest.mark.asyncio
async def test_handle_message_publishes_research_report(agent):
    await agent._handle_message(_msg(agent, _signal_payload()))

    agent.retriever.retrieve.assert_called_once()
    agent.llm_chain.generate.assert_awaited_once()
    agent._client.publish.assert_awaited_once()

    channel, payload = agent._client.publish.await_args.args
    assert channel == agent.config.reports_channel
    body = json.loads(payload)
    assert body["ticker"] == "NVDA"
    assert body["verdict"] == "bullish"
    assert body["citations"][0]["excerpt"] == "Data center revenue up 40%."
    assert body["is_degraded"] is False

    assert agent.signals_processed == 1
    assert agent.reports_published == 1


@pytest.mark.asyncio
async def test_handle_message_drops_unparseable_payload(agent):
    await agent._handle_message({"channel": agent.config.signals_channel, "data": "not json"})

    agent.retriever.retrieve.assert_not_called()
    agent.llm_chain.generate.assert_not_awaited()
    agent._client.publish.assert_not_awaited()
    assert agent.signals_processed == 0


@pytest.mark.asyncio
async def test_handle_message_drops_message_on_unexpected_channel(agent):
    await agent._handle_message(_msg(agent, _signal_payload(), channel="some:other:channel"))

    agent.retriever.retrieve.assert_not_called()
    assert agent.signals_processed == 0


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


# --- Cold start (Requirement 4A) ----------------------------------------

@pytest.mark.asyncio
async def test_handle_message_bypasses_llm_when_no_context_at_all(agent):
    agent.retriever.retrieve.return_value = []

    await agent._handle_message(_msg(agent, _signal_payload()))

    agent.llm_chain.generate.assert_not_awaited()
    agent._client.publish.assert_awaited_once()
    body = json.loads(agent._client.publish.await_args.args[1])
    assert body["verdict"] == "insufficient_context"
    assert body["confidence"] == 0.0
    assert body["is_degraded"] is False


# --- LLM failure fallback chain (Requirement 4A) -------------------------

@pytest.mark.asyncio
async def test_llm_failure_with_no_cache_publishes_degraded_report(agent):
    agent.llm_chain.generate.side_effect = RuntimeError("Gemini exploded")

    await agent._handle_message(_msg(agent, _signal_payload()))

    agent._client.publish.assert_awaited_once()
    body = json.loads(agent._client.publish.await_args.args[1])
    assert body["is_degraded"] is True
    assert body["verdict"] == "neutral"
    assert body["confidence"] == 0.0
    assert agent.signals_processed == 1
    assert agent.reports_published == 1


@pytest.mark.asyncio
async def test_llm_failure_with_cached_entry_falls_back_to_stale(agent):
    agent.llm_chain.generate.side_effect = RuntimeError("Gemini exploded")
    cached = _report(summary="Old but usable analysis.")
    cache = AsyncMock()
    cache.get.return_value = (cached, False)  # exists, not fresh -- stale
    agent.cache = cache

    await agent._handle_message(_msg(agent, _signal_payload()))

    agent._client.publish.assert_awaited_once()
    body = json.loads(agent._client.publish.await_args.args[1])
    assert body["is_stale"] is True
    assert body["is_degraded"] is False
    assert body["summary"] == "Old but usable analysis."
    cache.set.assert_not_awaited()  # never re-cache a stale/degraded result


# --- Cache-first (Requirement 2) -----------------------------------------

@pytest.mark.asyncio
async def test_fresh_cache_hit_skips_retrieval_and_llm(agent):
    cached = _report(summary="Cached analysis.")
    cache = AsyncMock()
    cache.get.return_value = (cached, True)  # fresh
    agent.cache = cache

    await agent._handle_message(_msg(agent, _signal_payload()))

    agent.retriever.retrieve.assert_not_called()
    agent.llm_chain.generate.assert_not_awaited()
    cache.acquire_lock.assert_not_awaited()
    agent._client.publish.assert_awaited_once()
    body = json.loads(agent._client.publish.await_args.args[1])
    assert body["from_cache"] is True
    assert body["summary"] == "Cached analysis."


@pytest.mark.asyncio
async def test_cache_miss_acquires_lock_generates_and_caches(agent):
    cache = AsyncMock()
    cache.get.return_value = None  # nothing cached at all
    cache.acquire_lock.return_value = True
    agent.cache = cache

    await agent._handle_message(_msg(agent, _signal_payload()))

    cache.acquire_lock.assert_awaited_once()
    agent.llm_chain.generate.assert_awaited_once()
    cache.set.assert_awaited_once()
    cache.release_lock.assert_awaited_once()
    agent._client.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_losing_the_lock_race_waits_for_and_uses_the_winners_cache(agent):
    winner_report = _report(summary="Winner's analysis.")
    cache = AsyncMock()
    cache.get.return_value = None
    cache.acquire_lock.return_value = False  # lost the race
    cache.wait_for_cache.return_value = (winner_report, True)
    agent.cache = cache

    await agent._handle_message(_msg(agent, _signal_payload()))

    cache.wait_for_cache.assert_awaited_once()
    agent.llm_chain.generate.assert_not_awaited()  # never duplicated the LLM call
    cache.release_lock.assert_not_awaited()  # never held the lock, nothing to release
    body = json.loads(agent._client.publish.await_args.args[1])
    assert body["summary"] == "Winner's analysis."


@pytest.mark.asyncio
async def test_losing_lock_race_and_wait_timeout_generates_anyway(agent):
    cache = AsyncMock()
    cache.get.return_value = None
    cache.acquire_lock.return_value = False
    cache.wait_for_cache.return_value = None  # timed out, nothing appeared
    agent.cache = cache

    await agent._handle_message(_msg(agent, _signal_payload()))

    agent.llm_chain.generate.assert_awaited_once()
    cache.release_lock.assert_not_awaited()  # never acquired it
    agent._client.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_degraded_report_is_never_cached(agent):
    agent.llm_chain.generate.side_effect = RuntimeError("Gemini exploded")
    cache = AsyncMock()
    cache.get.return_value = None  # no fallback available either
    cache.acquire_lock.return_value = True
    agent.cache = cache

    await agent._handle_message(_msg(agent, _signal_payload()))

    cache.set.assert_not_awaited()
    cache.release_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_disabled_skips_all_cache_interaction(agent):
    from talonx_brain.config import BrainConfig

    agent.config = BrainConfig(cache_enabled=False)
    cache = AsyncMock()
    agent.cache = cache

    await agent._handle_message(_msg(agent, _signal_payload()))

    cache.get.assert_not_awaited()
    cache.acquire_lock.assert_not_awaited()
    cache.set.assert_not_awaited()
    agent.llm_chain.generate.assert_awaited_once()


# --- Filings-channel invalidation (Requirement 2) -------------------------

@pytest.mark.asyncio
async def test_filing_event_invalidates_cache_for_that_ticker(agent):
    cache = AsyncMock()
    agent.cache = cache

    await agent._handle_message(_msg(agent, _filing_event_payload("NVDA"), channel=agent.config.filings_channel))

    # Fresh filing text invalidates BOTH horizons -- the intraday
    # technical-signal cache AND the long_term moat/DCF cache, since both
    # prompt types are grounded in the same filing text.
    assert cache.invalidate.await_count == 2
    cache.invalidate.assert_any_await("NVDA", horizon="intraday")
    cache.invalidate.assert_any_await("NVDA", horizon="long_term")
    assert agent.filing_invalidations == 1
    # Not treated as a research trigger.
    agent.retriever.retrieve.assert_not_called()
    agent._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_unparseable_filing_event_is_dropped(agent):
    cache = AsyncMock()
    agent.cache = cache

    await agent._handle_message({"channel": agent.config.filings_channel, "data": "not json"})

    cache.invalidate.assert_not_awaited()
    assert agent.filing_invalidations == 0


# --- _categorize() + report-count persistence (the EOD report's LLM/cache
# economics section) --------------------------------------------------------

def test_categorize_fresh_llm_call():
    assert _categorize(_report()) == "llm_call"


def test_categorize_cache_hit():
    assert _categorize(_report(from_cache=True)) == "cache_hit"


def test_categorize_stale_fallback():
    assert _categorize(_report(from_cache=True, is_stale=True)) == "stale_fallback"


def test_categorize_degraded():
    assert _categorize(_report(is_degraded=True)) == "degraded"


def test_categorize_cold_start():
    assert _categorize(_report(verdict=ResearchVerdict.INSUFFICIENT_CONTEXT)) == "cold_start"


@pytest.mark.asyncio
async def test_fresh_llm_call_is_recorded(agent, tmp_path):
    with BrainStatsStore(tmp_path / "brain.db") as store:
        agent.store = store
        await agent._handle_message(_msg(agent, _signal_payload()))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = store.report_counts_for_date(today)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["category"] == "llm_call"


@pytest.mark.asyncio
async def test_cache_hit_is_recorded(agent, tmp_path):
    cached = _report(summary="Cached analysis.")
    cache = AsyncMock()
    cache.get.return_value = (cached, True)
    agent.cache = cache

    with BrainStatsStore(tmp_path / "brain.db") as store:
        agent.store = store
        await agent._handle_message(_msg(agent, _signal_payload()))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = store.report_counts_for_date(today)
    assert rows[0]["category"] == "cache_hit"


@pytest.mark.asyncio
async def test_degraded_report_is_recorded(agent, tmp_path):
    agent.llm_chain.generate.side_effect = RuntimeError("Gemini exploded")

    with BrainStatsStore(tmp_path / "brain.db") as store:
        agent.store = store
        await agent._handle_message(_msg(agent, _signal_payload()))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = store.report_counts_for_date(today)
    assert rows[0]["category"] == "degraded"


@pytest.mark.asyncio
async def test_cold_start_is_recorded(agent, tmp_path):
    agent.retriever.retrieve.return_value = []

    with BrainStatsStore(tmp_path / "brain.db") as store:
        agent.store = store
        await agent._handle_message(_msg(agent, _signal_payload()))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = store.report_counts_for_date(today)
    assert rows[0]["category"] == "cold_start"


@pytest.mark.asyncio
async def test_no_store_means_no_persistence_attempted(agent):
    # agent fixture has store=None by default -- must not raise.
    await agent._handle_message(_msg(agent, _signal_payload()))
    assert agent.reports_published == 1


# --- Phase 2 LONG_TERM path --------------------------------------------------

def _fundamental_signal_payload(ticker: str = "AAPL") -> dict:
    return {
        "ticker": ticker,
        "fiscal_year": 2025,
        "roic": 0.21,
        "piotroski_f_score": 8,
        "fcf_yield": 0.05,
        "altman_z_score": 5.5,
        "price": 200.0,
        "message": "ROIC 21.1%, F-Score 8/9",
        "computed_at": "2026-08-04T12:00:00Z",
    }


def _fundamentals_ingested_payload(ticker: str = "AAPL") -> dict:
    return {
        "ticker": ticker,
        "cik": "0000320193",
        "facts": [{"ticker": ticker, "cik": "0000320193", "fiscal_year": 2025}],
        "published_at": "2026-08-04T12:00:00Z",
    }


def _fundamental_signal() -> FundamentalFactorSignal:
    return FundamentalFactorSignal.model_validate(_fundamental_signal_payload())


def _long_term_report(**overrides) -> LongTermResearchReport:
    defaults = dict(
        ticker="AAPL",
        triggering_signal=_fundamental_signal(),
        moat_rating=MoatRating.WIDE,
        capital_allocation_assessment="disciplined",
        dcf_fair_value_per_share=220.0,
        quality_score=8,
        summary="durable compounder",
        model_used="gemini-flash-latest",
    )
    defaults.update(overrides)
    return LongTermResearchReport(**defaults)


@pytest.mark.asyncio
async def test_handle_message_publishes_long_term_research_report(agent):
    await agent._handle_message(_msg(agent, _fundamental_signal_payload(), channel=agent.config.fundamental_signals_channel))

    agent.retriever.retrieve.assert_called_once()
    args = agent.retriever.retrieve.call_args.args
    assert args[3] == "10-K"  # form_type filter, unique to the long-term retrieval call
    agent.long_term_llm_chain.generate.assert_awaited_once()
    agent._client.publish.assert_awaited_once()

    channel, payload = agent._client.publish.await_args.args
    assert channel == agent.config.reports_channel_long_term
    body = json.loads(payload)
    assert body["ticker"] == "AAPL"
    assert body["moat_rating"] == "wide"
    assert body["quality_score"] == 8

    assert agent.fundamentals_processed == 1
    assert agent.long_term_reports_published == 1


@pytest.mark.asyncio
async def test_long_term_cold_start_bypasses_the_llm(agent):
    agent.retriever.retrieve.return_value = []

    await agent._handle_message(_msg(agent, _fundamental_signal_payload(), channel=agent.config.fundamental_signals_channel))

    agent.long_term_llm_chain.generate.assert_not_awaited()
    body = json.loads(agent._client.publish.await_args.args[1])
    assert body["moat_rating"] == "none"
    assert body["model_used"] == "none (cold-start bypass)"


@pytest.mark.asyncio
async def test_long_term_llm_failure_with_no_cache_publishes_degraded_report(agent):
    agent.long_term_llm_chain.generate.side_effect = RuntimeError("Gemini exploded")

    await agent._handle_message(_msg(agent, _fundamental_signal_payload(), channel=agent.config.fundamental_signals_channel))

    body = json.loads(agent._client.publish.await_args.args[1])
    assert body["is_degraded"] is True
    assert body["moat_rating"] == "none"
    assert agent.long_term_reports_published == 1


@pytest.mark.asyncio
async def test_long_term_llm_failure_with_cached_entry_falls_back_to_stale(agent):
    agent.long_term_llm_chain.generate.side_effect = RuntimeError("Gemini exploded")
    cached = _long_term_report(summary="Old but usable long-term analysis.")
    cache = AsyncMock()
    cache.get.return_value = (cached, False)  # exists, not fresh -- stale
    agent.cache = cache

    await agent._handle_message(_msg(agent, _fundamental_signal_payload(), channel=agent.config.fundamental_signals_channel))

    body = json.loads(agent._client.publish.await_args.args[1])
    assert body["is_stale"] is True
    assert body["is_degraded"] is False
    assert body["summary"] == "Old but usable long-term analysis."
    cache.set.assert_not_awaited()  # never re-cache a stale/degraded result


@pytest.mark.asyncio
async def test_long_term_fresh_cache_hit_skips_retrieval_and_llm(agent):
    cached = _long_term_report(summary="Cached long-term analysis.")
    cache = AsyncMock()
    cache.get.return_value = (cached, True)  # fresh
    agent.cache = cache

    await agent._handle_message(_msg(agent, _fundamental_signal_payload(), channel=agent.config.fundamental_signals_channel))

    agent.retriever.retrieve.assert_not_called()
    agent.long_term_llm_chain.generate.assert_not_awaited()
    cache.get.assert_awaited_once_with("AAPL", horizon="long_term")
    body = json.loads(agent._client.publish.await_args.args[1])
    assert body["from_cache"] is True
    assert body["summary"] == "Cached long-term analysis."


@pytest.mark.asyncio
async def test_long_term_cache_miss_generates_and_caches_under_the_long_term_horizon(agent):
    cache = AsyncMock()
    cache.get.return_value = None
    cache.acquire_lock.return_value = True
    agent.cache = cache

    await agent._handle_message(_msg(agent, _fundamental_signal_payload(), channel=agent.config.fundamental_signals_channel))

    cache.acquire_lock.assert_awaited_once_with("AAPL", horizon="long_term")
    agent.long_term_llm_chain.generate.assert_awaited_once()
    cache.set.assert_awaited_once()
    assert cache.set.await_args.kwargs["horizon"] == "long_term"
    cache.release_lock.assert_awaited_once_with("AAPL", horizon="long_term")


@pytest.mark.asyncio
async def test_fundamental_signal_below_threshold_never_reaches_here_but_routing_still_works(agent):
    """FundamentalScanner already gates on ROIC/F-Score thresholds before
    ever publishing -- talonx_brain has no opinion on that, it just
    researches whatever FundamentalFactorSignal arrives. This just
    confirms channel routing works regardless of the signal's own values."""
    payload = _fundamental_signal_payload()
    payload["roic"] = 0.01  # would have failed FundamentalScanner's own gate upstream
    await agent._handle_message(_msg(agent, payload, channel=agent.config.fundamental_signals_channel))

    assert agent.fundamentals_processed == 1
    agent._client.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_fundamentals_ingested_event_invalidates_only_the_long_term_cache(agent):
    cache = AsyncMock()
    agent.cache = cache

    await agent._handle_message(
        _msg(agent, _fundamentals_ingested_payload("AAPL"), channel=agent.config.fundamentals_events_channel)
    )

    cache.invalidate.assert_awaited_once_with("AAPL", horizon="long_term")
    # Not treated as a research trigger.
    agent.retriever.retrieve.assert_not_called()
    agent._client.publish.assert_not_awaited()
    assert agent.fundamentals_processed == 0


@pytest.mark.asyncio
async def test_unparseable_fundamentals_ingested_event_is_dropped(agent):
    cache = AsyncMock()
    agent.cache = cache

    await agent._handle_message(
        {"channel": agent.config.fundamentals_events_channel, "data": "not json"}
    )

    cache.invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_unparseable_fundamental_signal_is_dropped(agent):
    await agent._handle_message(
        _msg(agent, {"ticker": "AAPL"}, channel=agent.config.fundamental_signals_channel)
    )
    assert agent.fundamentals_processed == 0


@pytest.mark.asyncio
async def test_long_term_report_persists_with_long_term_horizon(agent, tmp_path):
    with BrainStatsStore(tmp_path / "brain.db") as store:
        agent.store = store
        await agent._handle_message(_msg(agent, _fundamental_signal_payload(), channel=agent.config.fundamental_signals_channel))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = store.report_counts_for_date(today)
    assert len(rows) == 1
    assert rows[0]["horizon"] == "long_term"
    assert rows[0]["category"] == "llm_call"


def test_build_long_term_retrieval_query_includes_ticker_and_moat_framing():
    query = _build_long_term_retrieval_query(_fundamental_signal())
    assert "AAPL" in query
    assert "moat" in query.lower()


def test_categorize_long_term_cache_hit():
    assert _categorize_long_term(_long_term_report(from_cache=True)) == "cache_hit"


def test_categorize_long_term_stale_fallback():
    assert _categorize_long_term(_long_term_report(from_cache=True, is_stale=True)) == "stale_fallback"


def test_categorize_long_term_degraded():
    assert _categorize_long_term(_long_term_report(is_degraded=True)) == "degraded"


def test_categorize_long_term_cold_start():
    assert _categorize_long_term(_long_term_report(model_used="none (cold-start bypass)")) == "cold_start"


def test_categorize_long_term_llm_call():
    assert _categorize_long_term(_long_term_report()) == "llm_call"
