"""
tests/test_brain_llm.py
----------------------------
Tests talonx_brain.llm's provider-switch machinery: build_research_chain()
picks Gemini or Ollama from config.llm_provider, and both chains share the
same retry/backoff loop (_BaseResearchChain.generate()). The underlying
langchain chat model classes are stubbed here -- this is about the
provider-selection and retry logic, not real Gemini/Ollama I/O, same
boundary test_brain_consumer.py uses for ResearchAgent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_brain import llm as llm_module
from talonx_brain.config import BrainConfig
from talonx_brain.llm import (
    GeminiResearchChain,
    OllamaResearchChain,
    _LLMFindings,
    _LLMFindingsLongTerm,
    build_long_term_research_chain,
    build_research_chain,
)
from talonx_brain.schemas import (
    FundamentalFactorSignal,
    MoatRating,
    QuantSignal,
    ResearchVerdict,
    SignalDirection,
    SignalType,
)


class _FakeCompiledChain:
    """Stand-in for `<ChatModel>(...).with_structured_output(_LLMFindings)`."""

    def __init__(self, result=None, side_effect=None):
        self.ainvoke = AsyncMock(
            return_value=result
            or _LLMFindings(verdict=ResearchVerdict.BULLISH, confidence=0.6, summary="ok"),
            side_effect=side_effect,
        )


class _FakeChatModel:
    """Stand-in for ChatGoogleGenerativeAI/ChatOllama -- records init kwargs
    and which structured-output schema it was asked to bind to (checked
    explicitly by the tests that care, e.g. the long-term-chain ones --
    everything else just needs SOME compiled chain back)."""

    last_kwargs: dict | None = None
    last_schema: type | None = None
    compiled: _FakeCompiledChain | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs

    def with_structured_output(self, schema):
        type(self).last_schema = schema
        return type(self).compiled or _FakeCompiledChain()


def _signal() -> QuantSignal:
    return QuantSignal(
        ticker="NVDA",
        signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE,
        direction=SignalDirection.BULLISH,
        message="RSI oversold with volume surge",
        price=131.5,
        bar_timestamp=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc),
    )


def _fundamental_signal() -> FundamentalFactorSignal:
    return FundamentalFactorSignal(
        ticker="AAPL",
        fiscal_year=2025,
        roic=0.21,
        piotroski_f_score=8,
        fcf_yield=0.05,
        altman_z_score=5.5,
        price=200.0,
        message="ROIC 21.1%, F-Score 8/9",
        computed_at=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc),
    )


@pytest.fixture(autouse=True)
def _reset_fake_chat_model():
    _FakeChatModel.last_kwargs = None
    _FakeChatModel.last_schema = None
    _FakeChatModel.compiled = None
    yield
    _FakeChatModel.last_kwargs = None
    _FakeChatModel.last_schema = None
    _FakeChatModel.compiled = None


def test_gemini_chain_requires_api_key(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatGoogleGenerativeAI", _FakeChatModel)
    config = BrainConfig(gemini_api_key=None)

    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiResearchChain(config)


def test_gemini_chain_uses_token_bucket(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatGoogleGenerativeAI", _FakeChatModel)
    config = BrainConfig(gemini_api_key="fake-key", gemini_max_requests_per_minute=30.0)

    chain = GeminiResearchChain(config)

    assert chain._bucket is not None
    assert _FakeChatModel.last_kwargs["model"] == config.gemini_model
    assert _FakeChatModel.last_kwargs["google_api_key"] == "fake-key"


def test_ollama_chain_has_no_token_bucket_or_api_key_requirement(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatOllama", _FakeChatModel)
    config = BrainConfig(llm_provider="ollama", ollama_model="llama3.1")

    chain = OllamaResearchChain(config)

    assert chain._bucket is None
    assert _FakeChatModel.last_kwargs["model"] == "llama3.1"
    assert _FakeChatModel.last_kwargs["base_url"] == config.ollama_base_url


def test_build_research_chain_selects_gemini(monkeypatch):
    # Explicit llm_provider rather than relying on BrainConfig's default --
    # that default is baked in from whatever TALONX_BRAIN_LLM_PROVIDER
    # happens to be in the local repo-root .env at import time, so
    # asserting on it here would make this test depend on the developer's
    # local config instead of testing build_research_chain's own logic.
    monkeypatch.setattr(llm_module, "ChatGoogleGenerativeAI", _FakeChatModel)
    config = BrainConfig(gemini_api_key="fake-key", llm_provider="gemini")

    chain = build_research_chain(config)

    assert isinstance(chain, GeminiResearchChain)


def test_build_research_chain_selects_ollama(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatOllama", _FakeChatModel)
    config = BrainConfig(llm_provider="ollama")

    chain = build_research_chain(config)

    assert isinstance(chain, OllamaResearchChain)


def test_describe_reports_active_provider_and_model(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatGoogleGenerativeAI", _FakeChatModel)
    monkeypatch.setattr(llm_module, "ChatOllama", _FakeChatModel)

    gemini_chain = GeminiResearchChain(BrainConfig(gemini_api_key="fake-key", gemini_model="gemini-flash-latest"))
    ollama_chain = OllamaResearchChain(BrainConfig(llm_provider="ollama", ollama_model="llama3.1"))

    assert gemini_chain.describe() == "Gemini (gemini-flash-latest)"
    assert ollama_chain.describe() == "Ollama (llama3.1)"


def test_build_research_chain_unknown_provider_raises():
    config = BrainConfig(llm_provider="not-a-real-provider")

    with pytest.raises(ValueError, match="not-a-real-provider"):
        build_research_chain(config)


@pytest.mark.asyncio
async def test_generate_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatOllama", _FakeChatModel)
    expected = _LLMFindings(verdict=ResearchVerdict.BEARISH, confidence=0.7, summary="recovered")
    _FakeChatModel.compiled = _FakeCompiledChain(
        result=expected, side_effect=[RuntimeError("transient"), expected]
    )
    config = BrainConfig(
        llm_provider="ollama",
        ollama_max_retries=3,
        ollama_backoff_base_seconds=0.001,
        ollama_backoff_max_seconds=0.01,
    )
    chain = OllamaResearchChain(config)

    result = await chain.generate(_signal(), citations=[])

    assert result is expected
    assert _FakeChatModel.compiled.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_generate_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatOllama", _FakeChatModel)
    _FakeChatModel.compiled = _FakeCompiledChain(side_effect=RuntimeError("still down"))
    config = BrainConfig(
        llm_provider="ollama",
        ollama_max_retries=2,
        ollama_backoff_base_seconds=0.001,
        ollama_backoff_max_seconds=0.01,
    )
    chain = OllamaResearchChain(config)

    with pytest.raises(RuntimeError, match="still down"):
        await chain.generate(_signal(), citations=[])

    assert _FakeChatModel.compiled.ainvoke.await_count == 3  # initial attempt + 2 retries


# --- Phase 2 LONG_TERM chain (moat/DCF structured output + prompt) ---------

def test_default_chain_binds_the_intraday_schema(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatOllama", _FakeChatModel)
    OllamaResearchChain(BrainConfig(llm_provider="ollama"))
    assert _FakeChatModel.last_schema is _LLMFindings


def test_long_term_gemini_chain_binds_the_long_term_schema(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatGoogleGenerativeAI", _FakeChatModel)
    config = BrainConfig(gemini_api_key="fake-key", llm_provider="gemini")

    chain = build_long_term_research_chain(config)

    assert isinstance(chain, GeminiResearchChain)
    assert _FakeChatModel.last_schema is _LLMFindingsLongTerm


def test_long_term_ollama_chain_binds_the_long_term_schema(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatOllama", _FakeChatModel)
    config = BrainConfig(llm_provider="ollama")

    chain = build_long_term_research_chain(config)

    assert isinstance(chain, OllamaResearchChain)
    assert _FakeChatModel.last_schema is _LLMFindingsLongTerm


def test_build_long_term_research_chain_unknown_provider_raises():
    config = BrainConfig(llm_provider="not-a-real-provider")
    with pytest.raises(ValueError, match="not-a-real-provider"):
        build_long_term_research_chain(config)


@pytest.mark.asyncio
async def test_long_term_generate_uses_the_long_term_prompt_builder(monkeypatch):
    """Confirms generate() routes through _build_long_term_prompt, not the
    intraday _build_prompt -- the prompt text must reference the
    fundamental-factor framing, not the technical-trigger one."""
    monkeypatch.setattr(llm_module, "ChatOllama", _FakeChatModel)
    expected = _LLMFindingsLongTerm(
        moat_rating=MoatRating.WIDE, capital_allocation_assessment="disciplined",
        dcf_fair_value_per_share=210.0, quality_score=8, summary="strong compounder",
    )
    _FakeChatModel.compiled = _FakeCompiledChain(result=expected)
    config = BrainConfig(llm_provider="ollama")
    chain = build_long_term_research_chain(config)

    captured_prompt = {}

    async def _capture(prompt):
        captured_prompt["text"] = prompt
        return expected

    _FakeChatModel.compiled.ainvoke.side_effect = _capture

    result = await chain.generate(_fundamental_signal(), citations=[])

    assert result is expected
    assert "Fundamental factor summary" in captured_prompt["text"]
    assert "economic moat" in captured_prompt["text"].lower()
    assert "AAPL" in captured_prompt["text"]


# --- Event-Driven Earnings Radar: _build_long_term_prompt ------------------

def test_long_term_prompt_omits_earnings_instruction_by_default():
    prompt = llm_module._build_long_term_prompt(_fundamental_signal(), citations=[])
    assert "FRESH EARNINGS EVENT" not in prompt


def test_long_term_prompt_includes_earnings_instruction_when_earnings_related():
    signal = _fundamental_signal().model_copy(update={"is_earnings_related": True})
    prompt = llm_module._build_long_term_prompt(signal, citations=[])
    assert "FRESH EARNINGS EVENT" in prompt


def test_llm_findings_long_term_guidance_fields_default_to_none():
    findings = _LLMFindingsLongTerm(
        moat_rating=MoatRating.WIDE, capital_allocation_assessment="disciplined",
        dcf_fair_value_per_share=210.0, quality_score=8, summary="strong compounder",
    )
    assert findings.guidance_revision_notes is None
    assert findings.revenue_eps_surprise is None
