"""
talonx_dispatch.schemas
----------------------------
Pydantic contracts for this module's Redis boundary.

ActionableAlert here is a DELIBERATELY TRIMMED mirror of
talonx_core.schemas.ActionableAlert -- deliberately re-declared rather
than imported, same reasoning as talonx_quant/talonx_core's own
re-declarations: this module only knows the WIRE format published to
talonx:alerts:dispatch, so producer and consumer stay independently
deployable/versionable.

The embedded triggering signal is trimmed to TriggeringSignalRef (ticker,
signal_type as a plain str, direction, message, price, bar_timestamp) --
dropping rsi/macd/macd_signal_line/sma_fast/sma_slow/volume/
volume_surge_ratio, which this module only ever displays, never
recomputes or branches logic on. `signal_type` is kept as `str` rather
than talonx_core's SignalType enum for the same reason: a display-only
consumer doesn't need to reject an unrecognized-but-valid new signal type
talonx_quant might add later. Pydantic's default `extra="ignore"`
behavior means the omitted numeric fields are simply dropped on parse,
not an error, so this stays a strictly valid subset of the real wire
shape.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SignalDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class ResearchVerdict(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class AlertAction(str, Enum):
    CONFIRMED_BULLISH = "confirmed_bullish"
    CONFIRMED_BEARISH = "confirmed_bearish"
    CONTRADICTED = "contradicted"
    DEGRADED_QUANT_ALERT = "degraded_quant_alert"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Ordinal for >= comparisons (e.g. against TALONX_DISPATCH_MIN_SEVERITY)."""
        return {"info": 0, "warning": 1, "critical": 2}[self.value]


class TriggeringSignalRef(BaseModel):
    ticker: str
    signal_type: str
    direction: SignalDirection
    message: str
    price: float
    bar_timestamp: datetime


class ActionableAlert(BaseModel):
    """Consumed from talonx:alerts:dispatch (published by talonx_core)."""

    ticker: str
    action: AlertAction
    severity: AlertSeverity
    rationale: str

    quant_direction: SignalDirection
    research_verdict: ResearchVerdict
    research_confidence: float = Field(ge=0.0, le=1.0)

    triggering_signal: TriggeringSignalRef
    research_summary: str
    key_findings: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    model_used: str
    is_degraded: bool = False

    signal_received_at: datetime
    report_received_at: datetime
    correlated_at: datetime
    published_at: datetime


class OrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PaperTradeExecution(BaseModel):
    """Consumed from talonx:paper:trades (published by talonx_paper) --
    trimmed mirror of talonx_paper.schemas.PaperTradeExecution, same
    re-declaration convention as ActionableAlert above."""

    trade_id: int
    ticker: str
    order_type: OrderType
    execution_price: float
    shares: float
    position_cost: float
    entry_price: float | None = None
    realized_pnl_usd: float | None = None
    realized_pnl_pct: float | None = None
    portfolio_cash_after: float
    triggering_action: AlertAction
    session_realized_pnl_usd: float
    session_realized_pnl_pct: float
    timestamp: datetime
