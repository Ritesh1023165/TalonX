"""
talonx_quant.schemas
------------------------
Pydantic contracts for this module's Redis boundary.

MarketTickEvent here mirrors talonx_ingest.events.schemas.MarketTickEvent
field-for-field, deliberately re-declared rather than imported. This
module only knows the WIRE format published to talonx:market:stream --
it doesn't import talonx_ingest's Python code at all, so the two modules
can be deployed, versioned, and scaled independently (this is the
"listens to a Redis channel" contract described in the module spec, not
a Python-level dependency). Keeping the schema in sync with talonx_ingest
is a wire-contract concern, same as any producer/consumer pair on a
message bus.

QuantSignal is this module's own output contract, published to
talonx:signals:quant.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Input contract (mirrors talonx_ingest.events.schemas.MarketTickEvent)
# ------------------------------------------------------------------

class TickEventType(str, Enum):
    TRADE = "trade"
    QUOTE = "quote"
    BAR = "bar"


class TickSource(str, Enum):
    WEBSOCKET = "websocket"
    POLLING = "polling"


class MarketTickEvent(BaseModel):
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

    published_at: datetime | None = None


# ------------------------------------------------------------------
# Output contract
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
    """Published to talonx:signals:quant when a trade setup condition passes."""

    ticker: str
    signal_type: SignalType
    direction: SignalDirection
    message: str  # human-readable summary, e.g. "RSI 24.3 oversold with 2.8x volume surge"

    # Indicator snapshot at the moment of trigger -- lets a consumer verify
    # or re-rank the signal without needing to recompute from raw bars.
    price: float
    rsi: float | None = None
    macd: float | None = None
    macd_signal_line: float | None = None
    sma_fast: float | None = None
    sma_slow: float | None = None
    volume: float | None = None
    volume_surge_ratio: float | None = None

    bar_timestamp: datetime
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()
