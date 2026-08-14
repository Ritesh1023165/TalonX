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

The embedded triggering signal is TriggeringSignalRef (ticker, signal_type
as a plain str, direction, message, price, bar_timestamp), plus (Phase 2
requirement doc) rsi/macd/macd_signal_line/volume_surge_ratio/atr/
stop_price/target_price/trend_aligned/htf_sma_200/session -- the Telegram
`#ID` detail reply now renders these (see formatter.format_telegram_details),
closing a real gap: the reply used to show only research fields, never
the technical setup that actually triggered the alert. `signal_type` is
kept as `str` rather than talonx_core's SignalType enum for the same
reason as before: a display-only consumer doesn't need to reject an
unrecognized-but-valid new signal type talonx_quant might add later.
Pydantic's default `extra="ignore"` behavior means any still-omitted
field (sma_fast/sma_slow/volume) is simply dropped on parse, not an
error, so this stays a strictly valid subset of the real wire shape.
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
    # Never a real ActionableAlert.action -- only ever appears as
    # PaperTradeExecution.triggering_action (talonx_paper's own
    # engine.check_stop_take triggered the SELL, not an alert). Must
    # exist here too since PaperTradeExecution is re-validated against
    # THIS module's mirror on talonx:paper:trades -- omitting it would
    # silently drop every stop-loss/take-profit execution as an
    # "invalid payload" rather than notify on it.
    STOP_LOSS_EXIT = "stop_loss_exit"
    TAKE_PROFIT_EXIT = "take_profit_exit"

    # --- Phase 2 LONG_TERM decision matrix -- disjoint from the
    # intraday actions above, never mixed on the same alert/channel.
    HIGH_CONVICTION_BUY = "high_conviction_buy"
    HOLD_QUALITY = "hold_quality"
    TAKE_PROFIT_REBALANCE = "take_profit_rebalance"
    UNDER_PERFORM_REBALANCE = "under_perform_rebalance"
    # Never a real LongTermActionableAlert.action -- only ever appears as
    # LongTermTradeExecution.triggering_action for a recurring DCA
    # contribution, which has no originating alert.
    DCA_CONTRIBUTION = "dca_contribution"


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

    # Technical-detail fields for the Telegram #ID reply (Phase 2
    # requirement doc) -- None for long-term alerts or any signal that
    # predates these fields.
    rsi: float | None = None
    macd: float | None = None
    macd_signal_line: float | None = None
    volume_surge_ratio: float | None = None
    atr: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    trend_aligned: bool | None = None
    htf_sma_200: float | None = None
    session: str | None = None


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


# ------------------------------------------------------------------
# Phase 2 LONG_TERM path
# ------------------------------------------------------------------

class MoatRating(str, Enum):
    WIDE = "wide"
    NARROW = "narrow"
    NONE = "none"


class _TriggeringFundamentalSignalRef(BaseModel):
    """Further-trimmed mirror of talonx_core.schemas.FundamentalFactorSignal
    -- this module only ever displays roic/piotroski_f_score (the post-
    earnings push's "Fundamental Shift" section), never the rest of the
    signal, so there's no reason to carry ticker/fiscal_year/price/message/
    computed_at here too."""

    roic: float | None = None
    piotroski_f_score: int | None = None


class LongTermActionableAlert(BaseModel):
    """Trimmed mirror of talonx_core.schemas.LongTermActionableAlert --
    consumed from talonx:alerts:longterm."""

    ticker: str
    action: AlertAction
    severity: AlertSeverity
    rationale: str
    # The LLM's clean free-text summary, separate from the more technical
    # `rationale` above -- the SHORT Telegram push uses this; the FULL
    # detail reply still uses rationale. See talonx_core.schemas' mirror
    # of this field for why the two are kept separate.
    summary: str

    quality_score: int
    moat_rating: MoatRating
    market_price: float
    intrinsic_fair_value: float
    margin_of_safety_pct: float

    # Event-Driven Earnings Radar, Requirement 8: populated only for an
    # earnings-triggered alert -- see talonx_core.schemas' mirror of this
    # field for the full "before vs after" rationale. When True,
    # consumer.py uses format_telegram_post_earnings_alert instead of the
    # routine format_telegram_long_term_alert, and bypasses both the
    # severity gate and _evaluate_push_eligibility entirely.
    previous_fair_value: float | None = None
    previous_margin_of_safety_pct: float | None = None
    guidance_revision_notes: str | None = None
    revenue_eps_surprise: str | None = None
    is_earnings_related: bool = False
    triggering_signal: _TriggeringFundamentalSignalRef | None = None

    capital_allocation_assessment: str
    key_findings: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    model_used: str
    is_degraded: bool = False

    correlated_at: datetime
    published_at: datetime


class LongTermOrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    DCA_CONTRIBUTION = "DCA_CONTRIBUTION"


class LongTermTradeExecution(BaseModel):
    """Trimmed mirror of talonx_paper.schemas.LongTermTradeExecution --
    consumed from talonx:paper:trades:longterm."""

    trade_id: int
    ticker: str
    order_type: LongTermOrderType
    execution_price: float
    shares: float
    contribution_cost: float
    avg_cost_basis_after: float | None = None
    total_shares_after: float | None = None
    realized_pnl_usd: float | None = None
    realized_pnl_pct: float | None = None
    holding_period_days: int | None = None
    portfolio_cash_after: float
    triggering_action: AlertAction
    timestamp: datetime


# ------------------------------------------------------------------
# Event-Driven Earnings Radar -- Requirement 5's T-48h heads-up push.
# Trimmed mirrors of talonx_brain.schemas.FundamentalFactorSignal /
# LongTermResearchReport, consumed PURELY to keep an in-memory latest-
# per-ticker cache (see consumer.py) for the heads-up push's price/
# quality/moat/fair-value fields -- this module never branches decision
# logic on them, same "wire-format-only" reasoning as every other mirror
# in this file.
# ------------------------------------------------------------------

class FundamentalFactorSignal(BaseModel):
    ticker: str
    fiscal_year: int
    price: float
    computed_at: datetime


class LongTermResearchReport(BaseModel):
    ticker: str
    moat_rating: MoatRating
    dcf_fair_value_per_share: float
    quality_score: int = Field(ge=0, le=10)
    summary: str
    is_degraded: bool = False
