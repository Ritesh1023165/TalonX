"""
talonx_ingest.market_data.models
------------------------------------
Normalized market data types. Both the Polygon WebSocket client and the
yfinance polling fallback emit the SAME `MarketEvent` shape -- downstream
consumers (the quant filtering stage) never need to know which source
produced an event. This is what makes the WebSocket/polling failover
transparent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class DataSource(str, Enum):
    WEBSOCKET = "websocket"
    POLLING = "polling"


class MarketEventType(str, Enum):
    TRADE = "trade"      # a single executed trade
    QUOTE = "quote"       # top-of-book bid/ask
    BAR = "bar"           # OHLCV aggregate (minute bar, or a polling snapshot)


@dataclass(frozen=True)
class MarketEvent:
    """
    One normalized market data event, regardless of source.

    Not every field is populated for every event_type:
      - TRADE: price, volume populated; bid/ask/open/high/low/close are None
      - QUOTE: bid, ask populated; price/volume/OHLC are None
      - BAR:   open/high/low/close/volume populated; bid/ask are None
    """
    symbol: str
    event_type: MarketEventType
    source: DataSource
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

    raw: dict = field(default_factory=dict)  # original message, for debugging
