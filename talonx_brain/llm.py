"""
talonx_brain.llm
---------------------
Structured RAG generation via Gemini (langchain-google-genai). Takes a
QuantSignal (the technical trigger) plus retrieved Citations (SEC filing
excerpts and, optionally, recent news article excerpts -- see
retriever.py) and produces the LLM-authored portion of a ResearchReport --
verdict, confidence, summary, key findings, risk factors.

Deliberately narrow output schema (_LLMFindings): everything ResearchReport
needs that ISN'T reasoning -- ticker, the triggering signal, citation
objects, model name, timestamps -- is assembled by the caller
(consumer.py), not asked of the model. That keeps the LLM from having to
echo back structured data it could get wrong (e.g. mistyping an accession
number) when Python already has it exactly.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from pydantic import BaseModel, Field

from talonx_ingest.common.backoff import jittered_backoff_seconds

from talonx_brain.config import BrainConfig
from talonx_brain.schemas import (
    Citation,
    CitationSourceType,
    FundamentalFactorSignal,
    MoatRating,
    QuantSignal,
    ResearchVerdict,
)

logger = logging.getLogger("talonx_brain.llm")

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:  # pragma: no cover - exercised only when dependency missing
    ChatGoogleGenerativeAI = None

try:
    from langchain_ollama import ChatOllama
except ImportError:  # pragma: no cover - exercised only when dependency missing
    ChatOllama = None


class _TokenBucket:
    """
    Async token-bucket rate limiter, same shape as the one
    talonx_ingest.edgar.client uses for SEC's request cap -- duplicated
    here rather than imported since that one's module-private, and this
    project's convention (see talonx_quant's own backoff helper) is to
    keep small per-module utilities local rather than force a shared
    import for something this small.

    Paces calls to stay under quota PROACTIVELY (waiting before the call)
    rather than reactively (retrying after a 429) -- under a sustained
    burst, reactive retries just queue up unbounded delay while still
    hammering the API; this caps the actual call rate instead.
    """

    def __init__(self, rate_per_minute: float):
        self.rate = rate_per_minute / 60.0
        self.capacity = max(rate_per_minute, 1.0)
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._last_refill = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                deficit = 1 - self._tokens
                wait_time = deficit / self.rate
            await asyncio.sleep(wait_time)


class _LLMFindings(BaseModel):
    """What we ask Gemini to produce -- see module docstring for the split."""

    verdict: ResearchVerdict = Field(
        description=(
            "Overall qualitative read on the ticker given the filing context. "
            "Use 'insufficient_context' if the retrieved context is empty or "
            "not relevant enough to support a real judgment -- do not guess."
        )
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the verdict, 0-1")
    summary: str = Field(
        description="2-4 sentence summary connecting the filing context to the technical trigger"
    )
    key_findings: list[str] = Field(
        default_factory=list,
        description="Specific facts from the filing/news excerpts that support or undercut the technical signal",
    )
    risk_factors: list[str] = Field(
        default_factory=list,
        description="Risks grounded in the filing/news excerpts, relevant to acting on this signal",
    )


SYSTEM_PROMPT = (
    "You are an equity research analyst assisting a systematic trading desk. "
    "You are given a technical trading signal (from a quantitative scanner) "
    "and excerpts retrieved from two sources: the company's SEC filings "
    "(10-K/10-Q) and recent news/social articles. Filings are the more "
    "authoritative, slower-moving source; news is more current but less "
    "rigorous -- weigh them accordingly. Your job is to ground or challenge "
    "the technical signal using ONLY the excerpts provided -- do not invent "
    "facts, financials, or events not present in the context. Cite "
    "specifics (numbers, dates, named risks, headlines) from the excerpts "
    "wherever possible. Be concise and direct."
)


class _LLMFindingsLongTerm(BaseModel):
    """Phase 2's LONG_TERM structured-output target -- what we ask the LLM
    to produce from a fundamental factor signal + retrieved 10-K excerpts.
    A deliberately different shape from _LLMFindings: no bullish/bearish
    verdict, no single confidence scalar -- moat durability, capital
    allocation quality, an intrinsic fair-value estimate, and an overall
    0-10 quality score instead."""

    moat_rating: MoatRating = Field(
        description=(
            "Economic moat durability: 'wide' (strong, durable pricing power/switching "
            "costs/network effects), 'narrow' (some advantage, less durable), or 'none' "
            "(no meaningful competitive advantage evident in the excerpts)."
        )
    )
    capital_allocation_assessment: str = Field(
        description="2-4 sentence assessment of management's capital allocation -- reinvestment, buybacks, dividend sustainability, grounded in the excerpts"
    )
    dcf_fair_value_per_share: float = Field(
        description=(
            "Estimated intrinsic fair value per share, derived from a discounted cash "
            "flow projection using free cash flow, a reasonable growth assumption, and a "
            "reasonable discount rate -- state the figure even if only roughly estimable "
            "from the excerpts provided, but ground the reasoning in them."
        )
    )
    quality_score: int = Field(ge=0, le=10, description="Overall business quality score, 0-10")
    summary: str = Field(description="2-4 sentence overall summary of the long-term investment case")
    key_findings: list[str] = Field(
        default_factory=list,
        description="Specific facts from the filing excerpts supporting the moat/quality/valuation assessment",
    )
    risk_factors: list[str] = Field(
        default_factory=list,
        description="Risks grounded in the filing excerpts relevant to a multi-year holding period",
    )


SYSTEM_PROMPT_LONG_TERM = (
    "You are an equity research analyst assessing a company for a multi-year, "
    "buy-and-hold value/quality investment thesis -- NOT a short-term trading call. "
    "You are given a fundamental factor summary (ROIC, Piotroski F-Score, FCF Yield, "
    "Altman Z-Score) and excerpts retrieved from the company's SEC 10-K filings. "
    "Your job is to evaluate three things using ONLY the excerpts provided -- do not "
    "invent facts or financials not present in the context: (1) the durability of the "
    "company's economic moat (pricing power, switching costs, cost advantages, network "
    "effects), (2) the quality of management's capital allocation (reinvestment, "
    "buybacks, dividend sustainability), and (3) an intrinsic fair-value-per-share "
    "estimate via a discounted cash flow approach. Cite specifics (numbers, dates, named "
    "risks) from the excerpts wherever possible. Be concise and direct."
)


class _BaseResearchChain:
    """
    Shared retry/backoff loop for both providers below. Subclasses only
    need to build self._llm (a langchain chat model already wrapped in
    .with_structured_output(SOME schema)) and pass their own retry
    knobs -- keeping Gemini's and Ollama's config fields/env-var names
    fully separate (TALONX_BRAIN_GEMINI_* vs TALONX_BRAIN_OLLAMA_*) rather
    than merging them into shared fields, so switching providers can never
    silently reinterpret one provider's tuned values as the other's.

    self._bucket is optional and None for Ollama: proactive rate-limiting
    exists to respect a cloud quota (see _TokenBucket's docstring) -- a
    local model has no such quota to pace against.

    `structured_output_schema`/`prompt_builder` default to the intraday
    shapes (_LLMFindings/_build_prompt) so every EXISTING caller's
    behavior is byte-identical -- Phase 2's long-term chains are the only
    callers that override them (see build_long_term_research_chain).
    """

    def __init__(
        self,
        config: BrainConfig,
        llm,
        *,
        bucket: "_TokenBucket | None",
        max_retries: int,
        backoff_base_seconds: float,
        backoff_max_seconds: float,
        provider_label: str,
        model_label: str,
        structured_output_schema: type[BaseModel] = _LLMFindings,
        prompt_builder: Callable[..., str] | None = None,
    ):
        self.config = config
        self._llm = llm
        self._bucket = bucket
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_max_seconds = backoff_max_seconds
        self._provider_label = provider_label
        self._structured_output_schema = structured_output_schema
        self._prompt_builder = prompt_builder or _build_prompt
        # Public (no leading underscore): consumer.py reads this directly
        # for ResearchReport.model_used, same "assembled by Python code
        # that already has it exactly right" reasoning the module
        # docstring gives for ticker/signal/citations -- consumer.py
        # shouldn't have to know which provider's config field to read.
        self.model_used = model_label

    def describe(self) -> str:
        """One-line summary for a startup log line -- see run.py. Exists so
        "which provider actually loaded" is a log line to read, not a
        forensic timestamp comparison between process-start time and the
        last .env edit."""
        return f"{self._provider_label} ({self.model_used})"

    async def generate(
        self, signal: QuantSignal | FundamentalFactorSignal, citations: list[Citation]
    ) -> _LLMFindings | _LLMFindingsLongTerm:
        prompt = self._prompt_builder(signal, citations)

        attempt = 0
        while True:
            if self._bucket is not None:
                await self._bucket.acquire()
            try:
                return await self._llm.ainvoke(prompt)
            except Exception as exc:  # noqa: BLE001 -- retry any transient API error
                attempt += 1
                if attempt > self._max_retries:
                    raise
                wait = jittered_backoff_seconds(
                    attempt, self._backoff_base_seconds, self._backoff_max_seconds
                )
                logger.warning(
                    "%s call failed for %s (%s); retrying in %.1fs (attempt %d/%d)",
                    self._provider_label, signal.ticker, exc, wait, attempt, self._max_retries,
                )
                await asyncio.sleep(wait)


class GeminiResearchChain(_BaseResearchChain):
    def __init__(
        self,
        config: BrainConfig | None = None,
        *,
        structured_output_schema: type[BaseModel] = _LLMFindings,
        prompt_builder: Callable[..., str] | None = None,
    ):
        config = config or BrainConfig()
        if ChatGoogleGenerativeAI is None:
            raise ImportError(
                "langchain-google-genai is required. Install it with: "
                "pip install langchain-google-genai"
            )
        if not config.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set -- required to run talonx_brain with the "
                "'gemini' provider. Add it to .env at the repo root, or set "
                "TALONX_BRAIN_LLM_PROVIDER=ollama to use a local model instead."
            )

        llm = ChatGoogleGenerativeAI(
            model=config.gemini_model,
            google_api_key=config.gemini_api_key,
            temperature=config.gemini_temperature,
            max_output_tokens=config.gemini_max_output_tokens,
        ).with_structured_output(structured_output_schema)

        super().__init__(
            config,
            llm,
            bucket=_TokenBucket(config.gemini_max_requests_per_minute),
            max_retries=config.gemini_max_retries,
            backoff_base_seconds=config.gemini_backoff_base_seconds,
            backoff_max_seconds=config.gemini_backoff_max_seconds,
            provider_label="Gemini",
            model_label=config.gemini_model,
            structured_output_schema=structured_output_schema,
            prompt_builder=prompt_builder,
        )


class OllamaResearchChain(_BaseResearchChain):
    def __init__(
        self,
        config: BrainConfig | None = None,
        *,
        structured_output_schema: type[BaseModel] = _LLMFindings,
        prompt_builder: Callable[..., str] | None = None,
    ):
        config = config or BrainConfig()
        if ChatOllama is None:
            raise ImportError(
                "langchain-ollama is required. Install it with: pip install langchain-ollama"
            )

        llm = ChatOllama(
            model=config.ollama_model,
            base_url=config.ollama_base_url,
            temperature=config.ollama_temperature,
        ).with_structured_output(structured_output_schema)

        super().__init__(
            config,
            llm,
            bucket=None,
            max_retries=config.ollama_max_retries,
            backoff_base_seconds=config.ollama_backoff_base_seconds,
            backoff_max_seconds=config.ollama_backoff_max_seconds,
            provider_label="Ollama",
            model_label=config.ollama_model,
            structured_output_schema=structured_output_schema,
            prompt_builder=prompt_builder,
        )


def build_research_chain(config: BrainConfig | None = None) -> _BaseResearchChain:
    """
    Factory picking the LLM provider from config.llm_provider
    (TALONX_BRAIN_LLM_PROVIDER env var) -- the one place that needs to
    know both providers exist. Everything else (consumer.py, tests) talks
    to the common generate() interface and never branches on provider.
    """
    config = config or BrainConfig()
    if config.llm_provider == "ollama":
        return OllamaResearchChain(config)
    if config.llm_provider == "gemini":
        return GeminiResearchChain(config)
    raise ValueError(
        f"Unknown TALONX_BRAIN_LLM_PROVIDER={config.llm_provider!r} -- expected 'gemini' or 'ollama'"
    )


def build_long_term_research_chain(config: BrainConfig | None = None) -> _BaseResearchChain:
    """Phase 2's LONG_TERM factory -- same provider selection as
    build_research_chain, but wired to the moat/DCF structured-output
    schema and prompt instead of the intraday ones."""
    config = config or BrainConfig()
    if config.llm_provider == "ollama":
        return OllamaResearchChain(
            config, structured_output_schema=_LLMFindingsLongTerm, prompt_builder=_build_long_term_prompt,
        )
    if config.llm_provider == "gemini":
        return GeminiResearchChain(
            config, structured_output_schema=_LLMFindingsLongTerm, prompt_builder=_build_long_term_prompt,
        )
    raise ValueError(
        f"Unknown TALONX_BRAIN_LLM_PROVIDER={config.llm_provider!r} -- expected 'gemini' or 'ollama'"
    )


def _build_prompt(signal: QuantSignal, citations: list[Citation]) -> str:
    context_block = (
        _format_citations(citations)
        if citations
        else "(No relevant SEC filing or news excerpts were retrieved for this ticker.)"
    )
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"## Technical trigger\n"
        f"Ticker: {signal.ticker}\n"
        f"Signal: {signal.signal_type.value} ({signal.direction.value})\n"
        f"Detail: {signal.message}\n"
        f"Price at trigger: {signal.price}\n"
        f"Bar timestamp: {signal.bar_timestamp.isoformat()}\n\n"
        f"## Retrieved context ({len(citations)} excerpt(s))\n{context_block}\n\n"
        "Assess whether the context supports, contradicts, or is irrelevant "
        "to this technical setup."
    )


def _build_long_term_prompt(signal: FundamentalFactorSignal, citations: list[Citation]) -> str:
    context_block = (
        _format_citations(citations)
        if citations
        else "(No relevant SEC filing excerpts were retrieved for this ticker.)"
    )
    roic_str = f"{signal.roic:.1%}" if signal.roic is not None else "n/a"
    fcf_yield_str = f"{signal.fcf_yield:.1%}" if signal.fcf_yield is not None else "n/a"
    altman_z_str = f"{signal.altman_z_score:.2f}" if signal.altman_z_score is not None else "n/a"
    return (
        f"{SYSTEM_PROMPT_LONG_TERM}\n\n"
        f"## Fundamental factor summary (FY{signal.fiscal_year})\n"
        f"Ticker: {signal.ticker}\n"
        f"ROIC: {roic_str}\n"
        f"Piotroski F-Score: {signal.piotroski_f_score if signal.piotroski_f_score is not None else 'n/a'}/9\n"
        f"FCF Yield: {fcf_yield_str}\n"
        f"Altman Z-Score: {altman_z_str}\n"
        f"Current market price: {signal.price}\n"
        f"Detail: {signal.message}\n\n"
        f"## Retrieved 10-K context ({len(citations)} excerpt(s))\n{context_block}\n\n"
        "Assess the economic moat, capital allocation quality, and derive an intrinsic "
        "fair-value-per-share estimate for a multi-year holding thesis."
    )


def _format_citations(citations: list[Citation]) -> str:
    blocks = []
    for i, c in enumerate(citations, start=1):
        if c.source_type == CitationSourceType.NEWS:
            blocks.append(
                f"[{i}] News -- \"{c.article_title or 'untitled'}\" "
                f"({c.article_source or 'unknown source'}, "
                f"{c.published_at or 'undated'}):\n{c.excerpt}"
            )
        else:
            blocks.append(
                f"[{i}] {c.form_type or 'filing'} filed {c.filing_date or 'unknown date'} "
                f"({c.source_document or 'unknown document'}):\n{c.excerpt}"
            )
    return "\n\n".join(blocks)
