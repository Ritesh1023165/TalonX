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

    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()
