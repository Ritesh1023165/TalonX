"""
talonx_brain.schemas
-------------------------
Pydantic contracts for this module's Redis boundary.

QuantSignal here mirrors talonx_quant.schemas.QuantSignal field-for-field,
deliberately re-declared rather than imported -- same reasoning as
talonx_quant's own re-declaration of MarketTickEvent: this module only
knows the WIRE format published to talonx:signals:quant, so producer and
consumer stay independently deployable/versionable, and drift between them
is a wire-contract concern rather than a Python import.

ResearchReport is this module's own output contract, published to
talonx:reports:brain. It embeds the full triggering QuantSignal (not just
its ticker) so a consumer can correlate a report back to the exact
technical setup that caused it without a separate lookup/join.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Input contract (mirrors talonx_quant.schemas.QuantSignal)
# ------------------------------------------------------------------

class SignalType(str, Enum):
    RSI_OVERSOLD_VOLUME_SURGE = "rsi_oversold_volume_surge"
    RSI_OVERBOUGHT_VOLUME_SURGE = "rsi_overbought_volume_surge"
    MACD_BULLISH_CROSS = "macd_bullish_cross"
    MACD_BEARISH_CROSS = "macd_bearish_cross"
    MA_GOLDEN_CROSS = "ma_golden_cross"
    MA_DEATH_CROSS = "ma_death_cross"


class SignalDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class QuantSignal(BaseModel):
    ticker: str
    signal_type: SignalType
    direction: SignalDirection
    message: str

    price: float
    rsi: float | None = None
    macd: float | None = None
    macd_signal_line: float | None = None
    sma_fast: float | None = None
    sma_slow: float | None = None
    volume: float | None = None
    volume_surge_ratio: float | None = None

    bar_timestamp: datetime
    published_at: datetime | None = None


# ------------------------------------------------------------------
# Output contract
# ------------------------------------------------------------------

class ResearchVerdict(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    # Retrieval came back empty, or too thin/irrelevant to say anything
    # meaningful -- distinct from NEUTRAL, which means "we looked and the
    # fundamentals genuinely don't lean either way."
    INSUFFICIENT_CONTEXT = "insufficient_context"


class CitationSourceType(str, Enum):
    FILING = "filing"
    NEWS = "news"


class Citation(BaseModel):
    """
    One retrieved chunk, from either the sec_filings or news_feed ChromaDB
    collection (see retriever.py). The filing-specific and news-specific
    fields are each optional and populated based on `source_type` -- kept
    as one model rather than two so ResearchReport.citations can be a
    single flat list without a union type on the wire.
    """

    chunk_id: str
    excerpt: str
    source_type: CitationSourceType

    # Populated when source_type == FILING
    source_document: str | None = None
    form_type: str | None = None
    filing_date: str | None = None
    accession_number: str | None = None

    # Populated when source_type == NEWS
    article_title: str | None = None
    article_url: str | None = None
    article_source: str | None = None
    published_at: str | None = None

    # Chroma cosine distance for this chunk vs. the retrieval query --
    # lower is more relevant. None if the store didn't return distances.
    # NOT comparable across source types (see retriever.py) -- filing and
    # news text have different length/style profiles, so don't sort a
    # combined list by this without accounting for that.
    relevance_distance: float | None = None


class ResearchReport(BaseModel):
    """Published to talonx:reports:brain once per researched QuantSignal."""

    ticker: str
    triggering_signal: QuantSignal
    verdict: ResearchVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    model_used: str

    # is_stale: served from an EXPIRED cache entry because a fresh
    # generation attempt failed (see cache.py) -- the analysis is real,
    # just possibly outdated. is_degraded: no real analysis exists at all
    # (LLM failed AND no cache to fall back on either) -- verdict/
    # confidence are meaningless placeholders in this case, and
    # talonx_core's decision matrix branches on this flag specifically to
    # still dispatch a quant-only DEGRADED_QUANT_ALERT rather than
    # silently suppressing it. from_cache: served from a FRESH cache hit
    # (retrieval + LLM were skipped entirely) -- purely informational, not
    # branched on downstream, kept for observability into the caching
    # this module does to cut LLM spend.
    is_stale: bool = False
    is_degraded: bool = False
    from_cache: bool = False

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


# ------------------------------------------------------------------
# Phase 2 LONG_TERM path -- fundamentals input / moat+DCF output contracts
# ------------------------------------------------------------------

class FundamentalFactorSignal(BaseModel):
    """Mirrors talonx_quant.schemas.FundamentalFactorSignal -- consumed
    from talonx:signals:fundamental, the LONG_TERM horizon's trigger,
    parallel to QuantSignal's role for the intraday path."""

    ticker: str
    fiscal_year: int
    roic: float | None = None
    piotroski_f_score: int | None = None
    fcf_yield: float | None = None
    altman_z_score: float | None = None
    debt_to_ebitda_proxy: float | None = None
    price: float
    message: str
    computed_at: datetime


class MoatRating(str, Enum):
    """Economic moat classification -- how durable the company's
    competitive advantage is judged to be, per the spec's Module 3B
    (pricing power, switching costs, cost advantages, network effects)."""

    WIDE = "wide"
    NARROW = "narrow"
    NONE = "none"


class LongTermResearchReport(BaseModel):
    """
    Published to talonx:reports:longterm once per researched
    FundamentalFactorSignal -- the LONG_TERM sibling to ResearchReport,
    deliberately a SEPARATE model rather than an extension of it:
    verdict/confidence don't map cleanly onto moat/DCF output (there's
    no "bullish/bearish" binary here, and "confidence" isn't the
    relevant scalar -- quality_score and the fair-value estimate are).
    """

    ticker: str
    triggering_signal: FundamentalFactorSignal
    moat_rating: MoatRating
    capital_allocation_assessment: str
    dcf_fair_value_per_share: float
    quality_score: int = Field(ge=0, le=10)
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    model_used: str

    # Same three flags ResearchReport carries, same meaning -- see its
    # own docstring above.
    is_stale: bool = False
    is_degraded: bool = False
    from_cache: bool = False

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()
