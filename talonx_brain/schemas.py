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

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()
