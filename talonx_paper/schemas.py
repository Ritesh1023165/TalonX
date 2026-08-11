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
