"""
talonx_paper.schemas
-------------------------
Pydantic contracts for this module's Redis boundary.

ActionableAlert and MarketTickEvent here are DELIBERATELY TRIMMED,
re-declared mirrors of talonx_core.schemas.ActionableAlert and
talonx_ingest.events.schemas.MarketTickEvent -- same "each module only
knows the WIRE format of what it actually consumes" reasoning used
everywhere else in this project. Pydantic's default `extra="ignore"`
means parsing the real, fuller wire payloads still works fine.

PaperTradeExecution is this module's own OUTPUT contract, published to
talonx:paper:trades -- matches the requirement doc's "Paper Trade Log
Contract" field-for-field, plus a few extras (triggering_action/severity,
session-level PnL/cash snapshot) so talonx_dispatch can format a
Telegram push from this ONE message without a second lookup call back
into talonx_paper's store.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class AlertAction(str, Enum):
    CONFIRMED_BULLISH = "confirmed_bullish"
    CONFIRMED_BEARISH = "confirmed_bearish"
    CONTRADICTED = "contradicted"
    DEGRADED_QUANT_ALERT = "degraded_quant_alert"
    # Never a real ActionableAlert.action -- only ever used as
    # PaperTradeExecution.triggering_action for a SELL that engine.
    # check_stop_take triggered on a market tick, with no originating
    # alert at all.
    STOP_LOSS_EXIT = "stop_loss_exit"
    TAKE_PROFIT_EXIT = "take_profit_exit"

    # --- Phase 2 LONG_TERM decision matrix (talonx_core.decision's
    # evaluate_long_term) -- disjoint from the intraday actions above.
    HIGH_CONVICTION_BUY = "high_conviction_buy"
    HOLD_QUALITY = "hold_quality"
    TAKE_PROFIT_REBALANCE = "take_profit_rebalance"
    UNDER_PERFORM_REBALANCE = "under_perform_rebalance"
    # Never a real LongTermActionableAlert.action -- only ever used as
    # LongTermTradeExecution.triggering_action for a recurring DCA
    # contribution, which has no originating alert.
    DCA_CONTRIBUTION = "dca_contribution"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Ordinal for >= comparisons against config.min_entry_severity --
        same pattern talonx_dispatch.schemas.AlertSeverity already uses
        for its own TALONX_DISPATCH_MIN_SEVERITY gate."""
        return {"info": 0, "warning": 1, "critical": 2}[self.value]


class TriggeringSignalRef(BaseModel):
    price: float
    # ATR-anchored dollar stop/target (Phase 2 requirement doc) -- mirrored
    # from talonx_core.schemas.QuantSignal, None when ATR wasn't available
    # at signal time. See engine.check_stop_take for how these override
    # the static stop_loss_pct/take_profit_pct config once a position is open.
    stop_price: float | None = None
    target_price: float | None = None


class ActionableAlert(BaseModel):
    """Consumed from talonx:alerts:dispatch (published by talonx_core)."""

    ticker: str
    action: AlertAction
    # Defaulted, not required -- keeps any payload/test that predates the
    # entry-conviction gate (config.min_entry_severity) parsing cleanly.
    severity: AlertSeverity = AlertSeverity.WARNING
    triggering_signal: TriggeringSignalRef
    correlated_at: datetime


class TickEventType(str, Enum):
    TRADE = "trade"
    QUOTE = "quote"
    BAR = "bar"


class MarketTickEvent(BaseModel):
    """Consumed from talonx:market:stream -- only the fields needed for
    mark-to-market pricing (see consumer.py, which only ever looks at
    BAR events, same as talonx_quant.consumer)."""

    event_type: TickEventType
    symbol: str
    close: float | None = None


class OrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PaperTradeExecution(BaseModel):
    """Published to talonx:paper:trades once per executed (non-ignored) trade."""

    trade_id: int
    ticker: str
    order_type: OrderType
    execution_price: float
    shares: float
    position_cost: float
    # Populated for SELL only -- what the closed position was opened at,
    # so a formatter can show "Entry $X -> Exit $Y" without a second
    # lookup back into the store.
    entry_price: float | None = None
    realized_pnl_usd: float | None = None
    realized_pnl_pct: float | None = None
    portfolio_cash_after: float

    # Context carried along so talonx_dispatch can format a full push
    # without a second call back into this module's store.
    triggering_action: AlertAction
    session_realized_pnl_usd: float
    session_realized_pnl_pct: float

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


# ------------------------------------------------------------------
# Phase 2 LONG_TERM path -- DCA-aware ledger input/output contracts
# ------------------------------------------------------------------

class MoatRating(str, Enum):
    WIDE = "wide"
    NARROW = "narrow"
    NONE = "none"


class LongTermActionableAlert(BaseModel):
    """Trimmed mirror of talonx_core.schemas.LongTermActionableAlert --
    consumed from talonx:alerts:longterm."""

    ticker: str
    action: AlertAction
    quality_score: int
    moat_rating: MoatRating
    market_price: float
    intrinsic_fair_value: float
    margin_of_safety_pct: float
    correlated_at: datetime


class LongTermOrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    DCA_CONTRIBUTION = "DCA_CONTRIBUTION"


class LongTermTradeExecution(BaseModel):
    """Published to talonx:paper:trades:longterm once per executed
    (non-ignored) long-term action -- a sibling to PaperTradeExecution,
    not a repurposing of it: DCA contributions accumulate an AVERAGE
    cost basis across possibly-many buys, and a partial rebalance sells
    only a fraction of the position, neither of which the intraday
    single-lot model represents."""

    trade_id: int
    ticker: str
    order_type: LongTermOrderType
    execution_price: float
    shares: float  # shares bought/sold/contributed THIS execution
    contribution_cost: float  # cash spent (BUY/DCA) or received (SELL, before PnL netting)

    # Populated after every execution -- the position's state post-trade
    # (0/None if the position was fully closed by a SELL).
    avg_cost_basis_after: float | None = None
    total_shares_after: float | None = None

    # Populated for SELL only.
    realized_pnl_usd: float | None = None
    realized_pnl_pct: float | None = None
    holding_period_days: int | None = None

    portfolio_cash_after: float
    triggering_action: AlertAction  # HIGH_CONVICTION_BUY / TAKE_PROFIT_REBALANCE / UNDER_PERFORM_REBALANCE / DCA_CONTRIBUTION

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()
