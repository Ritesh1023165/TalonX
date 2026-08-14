"""
talonx_ingest.events.schemas
--------------------------------
Pydantic contracts for events published to Redis Pub/Sub. These are the
module's formal OUTPUT contract -- anything downstream (the quant filter
stage, a dashboard, another service entirely) subscribes to these shapes,
not to our internal dataclasses. Keeping them Pydantic (not the internal
`MarketEvent`/`FilingMetadata` dataclasses) means:
  - JSON (de)serialization is built-in and validated, not hand-rolled.
  - The wire contract can evolve independently of internal representations.
  - Consumers in other languages/services have an unambiguous schema to
    code against (e.g. via `MarketTickEvent.model_json_schema()`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from talonx_ingest.edgar.financials import FinancialStatementFacts


class TickEventType(str, Enum):
    TRADE = "trade"
    QUOTE = "quote"
    BAR = "bar"


class TickSource(str, Enum):
    WEBSOCKET = "websocket"
    POLLING = "polling"


class MarketTickEvent(BaseModel):
    """Published to the `talonx:market:stream` Redis channel, one per tick/bar."""

    event_type: TickEventType
    symbol: str
    source: TickSource
    timestamp: datetime

    price: float | None = None
    volume: float | None = None

    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None

    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None

    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


class NewFundamentalsIngestedEvent(BaseModel):
    """
    Published to the `talonx:fundamentals:events` Redis channel once fresh
    structured financials (SEC XBRL company facts, NOT filing text) have
    been parsed for a ticker -- Phase 2's LONG_TERM-horizon trigger,
    parallel to NewFilingIngestedEvent's role for the intraday/RAG path.

    EMBEDS the actual parsed numbers (`facts`), not just metadata --
    unlike NewFilingIngestedEvent (which only needs to tell talonx_brain
    "go invalidate your cache," since the filing TEXT itself already
    lives in the shared ChromaDB both processes can query), a consumer
    of THIS event (talonx_quant's FundamentalScanner) has no database of
    its own to read the numbers back from -- talonx_quant only ever
    talks to other modules over the Redis wire contract, never by
    querying talonx_ingest's SQLite directly. So the numbers have to
    ride along on the event itself.
    """

    ticker: str
    cik: str
    facts: list[FinancialStatementFacts]  # most recent fiscal year first, up to 10 years

    # Event-Driven Earnings Radar: True when this ingestion was triggered
    # by ingest_earnings_filing's fast-track poller during a ticker's
    # active earnings window (the 10-Q stage of the two-stage
    # recalculation), rather than the regular periodic/reactive cadence.
    # Set at the SOURCE ingestion call, not re-derived downstream --
    # consumers use it to bypass their own cooldowns for exactly this one
    # signal (talonx_quant.fundamental_consumer.FundamentalScanner,
    # talonx_core.decision's long-term cooldown).
    is_earnings_related: bool = False

    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


class NewsArticleIngestedEvent(BaseModel):
    """
    Published to the `talonx:news:events` Redis channel once per newly-
    ingested news/social article -- talonx_quant's pre-market news-
    catalyst gate trigger (requires a catalyst within the last N hours).
    Deliberately minimal, same "consumer only needs recency, not content"
    reasoning as NewFilingIngestedEvent's own trimmed-mirror consumers:
    talonx_quant only tracks the MOST RECENT published_at per ticker, it
    never reads article text.
    """

    ticker: str
    published_at: datetime

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


class NewFilingIngestedEvent(BaseModel):
    """
    Published to the `talonx:filings:events` Redis channel once per filing,
    only after its chunks are successfully written to ChromaDB (i.e. this
    event firing is itself a signal that the filing is now searchable).
    """

    ticker: str
    cik: str
    company_name: str
    form_type: str
    accession_number: str
    filing_date: str  # ISO date (YYYY-MM-DD)
    report_date: str | None = None
    source_document: str
    chunk_count: int
    vector_collection: str

    # Event-Driven Earnings Radar: True only for a filing
    # ingest_earnings_filing's fast-track poller confirmed as the actual
    # earnings release -- a 10-Q filed during the tracked window, or an
    # 8-K whose body was fetched and text-scanned for "Item 2.02". An
    # 8-K NOT matching that check is still ingested normally (useful RAG
    # context) but with this False, so it never triggers the downstream
    # cooldown-bypass path. See talonx_quant.fundamental_consumer and
    # talonx_brain.consumer for the two things that read this field.
    is_earnings_related: bool = False

    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()
