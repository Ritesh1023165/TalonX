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
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal
from zoneinfo import ZoneInfo

from talonx_paper.schemas import ActionableAlert, AlertAction, LongTermActionableAlert

_ET = ZoneInfo("America/New_York")

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
    stop_price: float | None = None, target_price: float | None = None,
) -> str | None:
    """
    Independent, price-driven exit check -- runs on every market tick for
    an open position, alongside (not instead of) the alert-driven SELL
    trigger in decide_trade().

    When stop_price/target_price are BOTH provided (ATR-anchored levels
    captured at signal time and persisted on the position -- see
    store.execute_buy), those exact dollar levels are used instead of the
    percentage bands: the trade was sized against those specific levels,
    not a live-recomputed ATR (which drifts after entry). Falls back to
    the percentage-based check (same style as talonx_core's
    price_delta_retrigger_pct) when either is missing -- e.g. a
    DEGRADED_QUANT_ALERT or any alert predating this field.

    Returns "STOP_LOSS" if current_price has crossed the stop side,
    "TAKE_PROFIT" if it has crossed the target side, else None. Stop-loss
    is checked first -- on the (rare) tick where both thresholds are
    somehow crossed at once, protecting capital wins the tiebreak over
    locking in a gain.
    """
    if entry_price <= 0:
        return None

    if stop_price is not None and target_price is not None:
        bullish = target_price > entry_price  # long position: target above entry, stop below
        if bullish:
            if current_price <= stop_price:
                return "STOP_LOSS"
            if current_price >= target_price:
                return "TAKE_PROFIT"
        else:
            if current_price >= stop_price:
                return "STOP_LOSS"
            if current_price <= target_price:
                return "TAKE_PROFIT"
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


def seconds_until_next_eod_flatten(now: datetime, hour_et: int, minute_et: int) -> float:
    """Seconds from `now` until the next occurrence of hour_et:minute_et
    America/New_York local time -- today if that moment hasn't passed yet,
    else tomorrow. Converts via ZoneInfo rather than a fixed UTC offset,
    so the target stays pinned to the correct ET wall-clock time across
    the spring/fall DST transition (a naive "wait until HH:MM UTC" would
    silently drift an hour off local close every six months). `now` may
    be tz-aware (any zone) or naive -- naive is assumed UTC, same
    convention talonx_quant.session.get_session uses."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_now = now.astimezone(_ET)
    target_local = local_now.replace(hour=hour_et, minute=minute_et, second=0, microsecond=0)
    if target_local <= local_now:
        target_local += timedelta(days=1)
    return (target_local - local_now).total_seconds()


# ------------------------------------------------------------------
# Phase 2 LONG_TERM path -- DCA-aware trigger mapping and math
#
# Trigger mapping (talonx_core.decision's long-term matrix -> this
# module's trading actions):
#   HIGH_CONVICTION_BUY        -> BUY   (new position only; ongoing
#                                  conviction is expressed via the DCA
#                                  loop, not repeated alert-driven buys --
#                                  matches the intraday module's own
#                                  "flat only" BUY gate)
#   TAKE_PROFIT_REBALANCE      -> SELL_PARTIAL (trims a configurable
#                                  fraction of the position)
#   UNDER_PERFORM_REBALANCE    -> SELL_FULL (fundamental stop, full exit)
#   HOLD_QUALITY                -> no trading action (informational,
#                                  same treatment DEGRADED_QUANT_ALERT
#                                  gets on the intraday side)
# ------------------------------------------------------------------

class LongTermDecisionKind(str, Enum):
    BUY = "buy"
    SELL_PARTIAL = "sell_partial"
    SELL_FULL = "sell_full"
    IGNORED = "ignored"


@dataclass(frozen=True)
class LongTermTradeDecision:
    kind: LongTermDecisionKind
    ticker: str
    price: float
    trim_fraction: float | None = None  # only set for SELL_PARTIAL
    reason: str | None = None  # only set when kind == IGNORED


def decide_long_term_trade(
    alert: LongTermActionableAlert, position: dict | None, rebalance_trim_pct: float,
) -> LongTermTradeDecision | None:
    """`position` is the open long-term position row for this ticker (as
    returned by PaperTradingStore.get_long_term_position), or None if
    flat. Returns None only for HOLD_QUALITY (not a trading trigger at
    all, informational) -- a suppressed entry/exit still returns a
    TradeDecision(kind=IGNORED) so the caller can log it, same
    Requirement-2C-style convention the intraday decide_trade() uses."""
    price = alert.market_price

    if alert.action == AlertAction.HIGH_CONVICTION_BUY:
        if position is not None:
            return LongTermTradeDecision(
                LongTermDecisionKind.IGNORED, alert.ticker, price, reason="POSITION_ALREADY_OPEN",
            )
        return LongTermTradeDecision(LongTermDecisionKind.BUY, alert.ticker, price)

    if alert.action == AlertAction.TAKE_PROFIT_REBALANCE:
        if position is None:
            return LongTermTradeDecision(
                LongTermDecisionKind.IGNORED, alert.ticker, price, reason="NO_ACTIVE_POSITION",
            )
        return LongTermTradeDecision(
            LongTermDecisionKind.SELL_PARTIAL, alert.ticker, price, trim_fraction=rebalance_trim_pct,
        )

    if alert.action == AlertAction.UNDER_PERFORM_REBALANCE:
        if position is None:
            return LongTermTradeDecision(
                LongTermDecisionKind.IGNORED, alert.ticker, price, reason="NO_ACTIVE_POSITION",
            )
        return LongTermTradeDecision(LongTermDecisionKind.SELL_FULL, alert.ticker, price)

    return None  # HOLD_QUALITY -- not a trading trigger


def calculate_average_cost_basis(
    existing_shares: float, existing_avg_cost: float, new_shares: float, new_price: float,
) -> float:
    """Recomputes the position's average cost basis after adding
    new_shares at new_price (a DCA contribution, or the initial BUY
    against a flat/zero-shares starting point)."""
    total_shares = existing_shares + new_shares
    if total_shares <= 0:
        return new_price
    total_cost = existing_shares * existing_avg_cost + new_shares * new_price
    return total_cost / total_shares


def calculate_partial_sell_pnl(
    shares_to_sell: float, avg_cost_basis: float, exit_price: float,
) -> tuple[float, float]:
    """Same formula as calculate_sell_pnl, parameterized on a share
    count instead of assuming the full position is being liquidated --
    TAKE_PROFIT_REBALANCE only trims a fraction, not the whole position."""
    proceeds = shares_to_sell * exit_price
    cost_basis = shares_to_sell * avg_cost_basis
    pnl_usd = proceeds - cost_basis
    pnl_pct = ((exit_price - avg_cost_basis) / avg_cost_basis) * 100 if avg_cost_basis else 0.0
    return pnl_usd, pnl_pct
