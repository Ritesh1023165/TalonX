"""
talonx_paper.engine
------------------------
Pure decision/math functions, no I/O -- same testability philosophy as
talonx_core.decision: given the current position (if any) and an
incoming alert, decide whether to BUY, SELL, or do nothing, and compute
the position-sizing / PnL math. Trivial to unit test in isolation from
Redis/SQLite/asyncio.

Trigger mapping (the requirement doc's action names don't exist in the
real AlertAction enum -- BUY_SIGNAL/BEARISH/VALUE_TRAP_WARNING were
fictional; mapped onto the real one here):
  BUY  <- CONFIRMED_BULLISH
  SELL <- CONFIRMED_BEARISH or CONTRADICTED (the doc's own Telegram
          example shows CONTRADICTED triggering a SELL)
  (no action) <- DEGRADED_QUANT_ALERT -- no research backing at all,
          not a signal worth acting on financially.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from talonx_paper.schemas import ActionableAlert, AlertAction

_SELL_ACTIONS = (AlertAction.CONFIRMED_BEARISH, AlertAction.CONTRADICTED)


class DecisionKind(str, Enum):
    BUY = "buy"
    SELL = "sell"
    IGNORED = "ignored"


@dataclass(frozen=True)
class TradeDecision:
    kind: DecisionKind
    ticker: str
    price: float
    reason: str | None = None  # only set when kind == IGNORED


def decide_trade(alert: ActionableAlert, position: dict | None) -> TradeDecision | None:
    """
    `position` is the open-position row for this ticker (as returned by
    PaperTradingStore.get_position), or None if flat. Returns None only
    for an action that isn't a trading trigger at all (DEGRADED_QUANT_ALERT)
    -- a suppressed re-entry/re-exit still returns a TradeDecision(kind=IGNORED)
    so the caller can log it, per Requirement 2C.
    """
    price = alert.triggering_signal.price

    if alert.action == AlertAction.CONFIRMED_BULLISH:
        if position is not None:
            return TradeDecision(DecisionKind.IGNORED, alert.ticker, price, reason="POSITION_ALREADY_OPEN")
        return TradeDecision(DecisionKind.BUY, alert.ticker, price)

    if alert.action in _SELL_ACTIONS:
        if position is None:
            return TradeDecision(DecisionKind.IGNORED, alert.ticker, price, reason="NO_ACTIVE_POSITION")
        return TradeDecision(DecisionKind.SELL, alert.ticker, price)

    return None  # DEGRADED_QUANT_ALERT -- not a trading trigger


def calculate_buy(cash: float, allocation_usd: float, price: float) -> tuple[float, float] | None:
    """
    Returns (shares, cost) for a BUY, spending min(allocation_usd, cash)
    -- never more than what's actually available. Returns None if there's
    no cash left to spend, or price is non-positive (bad data, don't
    divide by it).
    """
    if price <= 0:
        return None
    spend = min(allocation_usd, cash)
    if spend <= 0:
        return None
    return spend / price, spend


def calculate_sell_pnl(shares: float, entry_price: float, exit_price: float) -> tuple[float, float]:
    """Returns (realized_pnl_usd, realized_pnl_pct) -- exact formulas
    from the requirement doc's Requirement 2B."""
    proceeds = shares * exit_price
    cost_basis = shares * entry_price
    pnl_usd = proceeds - cost_basis
    pnl_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price else 0.0
    return pnl_usd, pnl_pct


def check_stop_take(
    entry_price: float, current_price: float, stop_loss_pct: float, take_profit_pct: float,
) -> str | None:
    """
    Independent, price-driven exit check -- runs on every market tick for
    an open position, alongside (not instead of) the alert-driven SELL
    trigger in decide_trade(). Percentage-based off entry price, same
    style as talonx_core's price_delta_retrigger_pct.

    Returns "STOP_LOSS" if current_price has fallen stop_loss_pct or more
    below entry, "TAKE_PROFIT" if it has risen take_profit_pct or more
    above entry, else None. Stop-loss is checked first -- on the (rare)
    tick where both thresholds are somehow crossed at once, protecting
    capital wins the tiebreak over locking in a gain.
    """
    if entry_price <= 0:
        return None
    change_pct = (current_price - entry_price) / entry_price
    if change_pct <= -stop_loss_pct:
        return "STOP_LOSS"
    if change_pct >= take_profit_pct:
        return "TAKE_PROFIT"
    return None


def apply_spread(price: float, spread_bps: float, side: Literal["BUY", "SELL"]) -> float:
    """
    Simulates crossing half the bid-ask spread on a fill -- a BUY fills
    ABOVE the quoted price, a SELL fills BELOW it, same convention a real
    market/marketable-limit order experiences. spread_bps=0 is an exact
    no-op pass-through (default-off friction, opt-in via config).
    """
    half_spread = price * (spread_bps / 2 / 10000)
    return price + half_spread if side == "BUY" else price - half_spread
