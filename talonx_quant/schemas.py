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

    # Analyst-review additions (see strategy.py): atr feeds the
    # risk/reward calculation below; confluence_score (0-3) counts how
    # many of {MACD cross, RSI extreme, volume surge} agree on this bar,
    # gating whether this signal survives past consumer.py's
    # confluence_score_min filter; risk_reward_ratio is
    # (atr_reward_multiplier * atr) / (assumed_stop_loss_pct * price),
    # gating consumer.py's min_risk_reward_ratio filter.
    atr: float | None = None
    confluence_score: int | None = None
    risk_reward_ratio: float | None = None

    # Phase 2 requirement doc: explicit dollar stop/target (1x/2x ATR),
    # rather than only the derived ratio above -- see strategy.py's
    # _stop_target_prices. None when atr is None (insufficient history).
    stop_price: float | None = None
    target_price: float | None = None

    # 15-min 200 SMA higher-timeframe trend gate (regular session, BULLISH
    # candidates only -- see strategy.py). trend_aligned is None when the
    # gate doesn't apply to this signal (bearish, pre-market, or the HTF
    # buffer hasn't warmed up yet), not "failed".
    trend_aligned: bool | None = None
    htf_sma_200: float | None = None

    # Session this candidate's triggering bar fell in -- carried through
    # so downstream consumers (talonx_dispatch's detail reply) can label
    # a push "Pre-Market" vs "Regular" without recomputing it.
    session: str | None = None

    bar_timestamp: datetime
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


# ------------------------------------------------------------------
# Post-Loss Lockout input contract (mirrors
# talonx_paper.schemas.PaperTradeExecution, DELIBERATELY TRIMMED to just
# the 3 fields consumer.py's loss-lockout check actually needs -- same
# "each module only knows the wire shape of what it consumes" convention
# as MarketTickEvent above; Pydantic's default extra="ignore" means
# parsing the real, fuller payload still works fine)
# ------------------------------------------------------------------

class PaperOrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PaperTradeExecution(BaseModel):
    """Consumed from talonx:paper:trades, talonx_paper's own output
    contract -- this module only cares whether a SELL closed at a loss."""

    ticker: str
    order_type: PaperOrderType
    realized_pnl_usd: float | None = None


# ------------------------------------------------------------------
# Phase 2 LONG_TERM path -- fundamentals input/output contracts
# ------------------------------------------------------------------

class FinancialStatementFacts(BaseModel):
    """Mirrors talonx_ingest.edgar.financials.FinancialStatementFacts
    field-for-field, same re-declared-not-imported convention as
    MarketTickEvent above -- this module only knows the wire shape
    published on talonx:fundamentals:events."""

    ticker: str
    cik: str
    fiscal_year: int
    fiscal_period: str = "FY"
    revenue: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    total_equity: float | None = None
    total_assets: float | None = None
    retained_earnings: float | None = None
    shares_outstanding: float | None = None


class NewFundamentalsIngestedEvent(BaseModel):
    """Mirrors talonx_ingest.events.schemas.NewFundamentalsIngestedEvent --
    consumed from talonx:fundamentals:events, this module's trigger for
    the fundamental factor pipeline."""

    ticker: str
    cik: str
    facts: list[FinancialStatementFacts]
    # Event-Driven Earnings Radar Stage 2: True when this ingestion was
    # triggered by the fast-track poller during the ticker's active
    # earnings window -- threaded onto the republished FundamentalFactorSignal.
    is_earnings_related: bool = False
    published_at: datetime


class NewFilingIngestedEvent(BaseModel):
    """Trimmed mirror of talonx_ingest.events.schemas.NewFilingIngestedEvent
    -- consumed from talonx:filings:events PURELY to detect a fast-track-
    confirmed earnings filing (form_type + is_earnings_related); this
    module never needs the rest of the wire shape (accession/chunk-count/
    vector-collection details are irrelevant here)."""

    ticker: str
    form_type: str
    is_earnings_related: bool = False


class NewsArticleIngestedEvent(BaseModel):
    """Trimmed mirror of talonx_ingest.events.schemas.NewsArticleIngestedEvent
    -- consumed from talonx:news:events, the pre-market news-catalyst
    gate's trigger. This module only tracks the most recent published_at
    per ticker (see consumer.py's _last_news_seen), never article text."""

    ticker: str
    published_at: datetime


class FundamentalFactorSignal(BaseModel):
    """Published to talonx:signals:fundamental when a ticker's latest
    fundamental factor scores clear config's thresholds -- the LONG_TERM
    horizon's equivalent of QuantSignal."""

    ticker: str
    fiscal_year: int
    roic: float | None = None
    piotroski_f_score: int | None = None
    fcf_yield: float | None = None
    altman_z_score: float | None = None
    debt_to_ebitda_proxy: float | None = None
    price: float  # last known market price used for fcf_yield/altman_z_score
    message: str

    # Event-Driven Earnings Radar: True when this signal was republished
    # by FundamentalScanner's earnings-triggered path (fast 8-K-stage
    # reuse of persisted factors, or a genuinely fresh 10-Q-stage
    # computation) rather than a routine periodic re-score. Consumers
    # (talonx_brain, talonx_core) use this to bypass their own cooldowns
    # and cache-hit shortcuts for exactly this one signal.
    is_earnings_related: bool = False

    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()
