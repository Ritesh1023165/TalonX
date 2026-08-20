"""
talonx_backtest.execution
------------------------------
Simulated trade execution: entry, stop/target monitoring, same-bar
stop/target ambiguity resolution, slippage, and spread -- see this
module's own docstrings on TradeSimulator/ExecutionConfig for the exact
rules applied (spec sections 5-9).

Entry timing: a published signal's entry is executed at the OPEN of the
NEXT bar for that symbol after publication (never the bar the signal was
generated from, and never a same-bar close -- that would be using a
price the strategy's own indicators were computed from, an unrealistic
zero-latency fill). Stop/target are then monitored starting on that same
entry bar (its own high/low, after the open) through every subsequent
bar until an exit condition is met or the data/session ends -- "use
subsequent bars only" per spec section 5, where "subsequent" includes
the entry bar itself for same-bar ambiguity purposes (spec section 6).
"""
from __future__ import annotations

from dataclasses import dataclass

from talonx_quant.schemas import SignalDirection

SAME_BAR_STOP_FIRST = "stop_first"
SAME_BAR_TARGET_FIRST = "target_first"


@dataclass(frozen=True)
class ExecutionConfig:
    entry_slippage_bps: float = 0.0
    exit_slippage_bps: float = 0.0
    spread_bps: float = 0.0
    # Same-Bar Stop/Target Ambiguity (spec section 6): when a single bar's
    # high/low touches BOTH stop and target, which is assumed to have
    # happened first. "stop_first" (the conservative default) prevents an
    # optimistic backtest bias -- see _resolve_same_bar_ambiguity.
    same_bar_resolution: str = SAME_BAR_STOP_FIRST

    def __post_init__(self) -> None:
        if self.same_bar_resolution not in (SAME_BAR_STOP_FIRST, SAME_BAR_TARGET_FIRST):
            raise ValueError(
                f"same_bar_resolution must be {SAME_BAR_STOP_FIRST!r} or "
                f"{SAME_BAR_TARGET_FIRST!r}, got {self.same_bar_resolution!r}"
            )


def _apply_cost(price: float, direction: SignalDirection, side: str, bps: float) -> float:
    """Moves `price` AGAINST the trader by `bps` basis points.
    side='entry': BULLISH pays more, BEARISH receives less.
    side='exit':  BULLISH receives less, BEARISH pays more."""
    if bps <= 0:
        return price
    factor = bps / 10_000.0
    bullish = direction == SignalDirection.BULLISH
    worse_is_higher = (side == "entry") == bullish
    return price * (1 + factor) if worse_is_higher else price * (1 - factor)


def apply_entry_cost(raw_price: float, direction: SignalDirection, config: ExecutionConfig) -> float:
    total_bps = config.entry_slippage_bps + config.spread_bps / 2.0
    return _apply_cost(raw_price, direction, "entry", total_bps)


def apply_exit_cost(raw_price: float, direction: SignalDirection, config: ExecutionConfig) -> float:
    total_bps = config.exit_slippage_bps + config.spread_bps / 2.0
    return _apply_cost(raw_price, direction, "exit", total_bps)


def check_bar_for_exit(
    direction: SignalDirection,
    stop_price: float,
    target_price: float,
    bar_high: float,
    bar_low: float,
    same_bar_resolution: str = SAME_BAR_STOP_FIRST,
) -> str | None:
    """Returns "stop", "target", or None for one bar's high/low against a
    trade's fixed stop/target. When BOTH are touched on the same bar
    (spec section 6), returns whichever `same_bar_resolution` says
    happened first -- "stop_first" (default) is the conservative choice
    that prevents an optimistic backtest bias."""
    if direction == SignalDirection.BULLISH:
        hit_target = bar_high >= target_price
        hit_stop = bar_low <= stop_price
    else:
        hit_target = bar_low <= target_price
        hit_stop = bar_high >= stop_price

    if hit_target and hit_stop:
        return "stop" if same_bar_resolution == SAME_BAR_STOP_FIRST else "target"
    if hit_stop:
        return "stop"
    if hit_target:
        return "target"
    return None


@dataclass
class OpenPosition:
    symbol: str
    direction: SignalDirection
    signal: object  # the originating QuantSignal
    entry_timestamp: object
    entry_price_raw: float
    entry_price_net: float
    stop_price: float
    target_price: float
    risk: float | None  # abs(entry_price_raw - stop_price); None if it resolves to 0

    mfe_price: float
    mae_price: float
    opportunity_score: float | None = None

    def update_excursion(self, bar_high: float, bar_low: float) -> None:
        """Updates the running most-favorable/most-adverse price reached
        so far, using this bar's full high/low range -- see
        TradeSimulator.check_exit's own docstring for why this runs
        BEFORE the exit check on the same bar."""
        if self.direction == SignalDirection.BULLISH:
            self.mfe_price = max(self.mfe_price, bar_high)
            self.mae_price = min(self.mae_price, bar_low)
        else:
            self.mfe_price = min(self.mfe_price, bar_low)
            self.mae_price = max(self.mae_price, bar_high)


class TradeSimulator:
    """Owns all currently-open simulated positions (one per symbol,
    unless the caller opts into overlapping trades -- see engine.py) and
    turns each into a portfolio.Trade once it exits."""

    def __init__(self, config: ExecutionConfig | None = None):
        self.config = config or ExecutionConfig()
        self._open: dict[str, OpenPosition] = {}

    def has_open(self, symbol: str) -> bool:
        return symbol.upper() in self._open

    def get_open(self, symbol: str) -> OpenPosition | None:
        return self._open.get(symbol.upper())

    def open_position(
        self, signal, entry_timestamp, entry_price_raw: float,
        opportunity_score: float | None = None,
    ) -> OpenPosition:
        """Generic, direction-symmetric execution primitive -- TradeSimulator
        itself has no opinion on which directions a caller should open
        (see check_bar_for_exit/_close's own direction_sign handling,
        both still fully bidirectional and independently tested). The
        TalonX-specific LONG_ONLY invariant (Task 24/25A: a BEARISH/
        CONTRADICTED QuantSignal must only ever close an existing long,
        never open a new position) is enforced one layer up, in
        engine.py's _flush_throttle -- only a BULLISH signal is ever
        routed into a _PendingEntry / this method in the first place.
        Kept generic here deliberately, not a destructive refactor of a
        reusable, already-tested execution primitive."""
        symbol = signal.ticker.upper()
        entry_price_net = apply_entry_cost(entry_price_raw, signal.direction, self.config)
        risk = abs(entry_price_raw - signal.stop_price) if signal.stop_price is not None else None
        if risk is not None and risk <= 0:
            risk = None
        position = OpenPosition(
            symbol=symbol, direction=signal.direction, signal=signal,
            entry_timestamp=entry_timestamp, entry_price_raw=entry_price_raw,
            entry_price_net=entry_price_net, stop_price=signal.stop_price,
            target_price=signal.target_price, risk=risk,
            mfe_price=entry_price_raw, mae_price=entry_price_raw,
            opportunity_score=opportunity_score,
        )
        self._open[symbol] = position
        return position

    def check_exit(
        self, symbol: str, timestamp, bar_high: float, bar_low: float,
    ) -> "Trade | None":
        """Feeds one subsequent bar (which may be the entry bar itself)
        to `symbol`'s open position. MFE/MAE is updated from the bar's
        FULL high/low range BEFORE the stop/target check runs, so the
        excursion captured on the exact bar that closes the trade still
        reflects the full range that bar reached, not just the point the
        stop/target was struck at (a real position could have run
        further in its favor intrabar before reversing to the exit
        level -- the same reasoning a live trader would apply). Returns
        the closed Trade if this bar closed the position, else None."""
        position = self._open.get(symbol.upper())
        if position is None:
            return None
        position.update_excursion(bar_high, bar_low)

        outcome = check_bar_for_exit(
            position.direction, position.stop_price, position.target_price,
            bar_high, bar_low, self.config.same_bar_resolution,
        )
        if outcome is None:
            return None
        exit_price_raw = position.stop_price if outcome == "stop" else position.target_price
        return self._close(symbol, timestamp, exit_price_raw, outcome.upper())

    def force_close(self, symbol: str, timestamp, price_raw: float, reason: str) -> "Trade | None":
        """Closes `symbol`'s open position (if any) at `price_raw` for a
        reason OTHER than stop/target being struck intrabar -- END_OF_SESSION
        (EOD flatten) or DATA_END (historical data ran out)."""
        if symbol.upper() not in self._open:
            return None
        return self._close(symbol, timestamp, price_raw, reason)

    def close_on_signal_exit(self, symbol: str, timestamp, price_raw: float, exit_signal) -> "Trade | None":
        """Closes `symbol`'s open long (if any) because a BEARISH/
        CONTRADICTED alert-driven exit signal fired -- distinct from
        STOP/TARGET (intrabar bracket struck) and END_OF_SESSION/
        DATA_END (forced flatten); see Task 24's long_short_flow.md and
        Task 25A's canonical LONG_ONLY lifecycle. `exit_signal` is the
        QuantSignal that triggered the exit; recorded on the resulting
        Trade (exit_signal_type/exit_signal_direction) so the record
        never conflates an alert-driven reversal with a price-driven
        stop/target/EOD exit. TalonX never opens a new short here --
        this only ever closes an existing long."""
        if symbol.upper() not in self._open:
            return None
        return self._close(symbol, timestamp, price_raw, "SIGNAL_EXIT", exit_signal=exit_signal)

    def _close(self, symbol: str, timestamp, exit_price_raw: float, reason: str, exit_signal=None) -> "Trade":
        from talonx_backtest.portfolio import Trade  # local import: avoids a portfolio<->execution cycle

        position = self._open.pop(symbol.upper())
        signal = position.signal
        direction_sign = 1.0 if position.direction == SignalDirection.BULLISH else -1.0

        exit_price_net = apply_exit_cost(exit_price_raw, position.direction, self.config)

        gross_pnl = (exit_price_raw - position.entry_price_raw) * direction_sign
        net_pnl = (exit_price_net - position.entry_price_net) * direction_sign

        gross_R = net_R = None
        if position.risk:
            gross_R = gross_pnl / position.risk
            net_R = net_pnl / position.risk

        mfe_dist = (position.mfe_price - position.entry_price_raw) * direction_sign
        mae_dist = (position.mae_price - position.entry_price_raw) * direction_sign  # <= 0 by construction
        mfe_pct = (mfe_dist / position.entry_price_raw) * 100 if position.entry_price_raw else None
        mae_pct = (mae_dist / position.entry_price_raw) * 100 if position.entry_price_raw else None
        mfe_r = (mfe_dist / position.risk) if position.risk else None
        mae_r = (mae_dist / position.risk) if position.risk else None

        # execution_rr: reward:risk at the price this order ACTUALLY
        # filled at (position.entry_price_raw), against the same fixed
        # stop_price/target_price -- independent of exit_reason/how the
        # trade actually closed. See portfolio.Trade's own docstring for
        # why this is a distinct number from screening_rr (the
        # strategy's gate-time R:R, never recalculated against the
        # fill) and from gross_R/net_R (the ACTUALLY REALIZED outcome).
        execution_rr = None
        if position.risk and position.target_price is not None:
            execution_rr = abs(position.target_price - position.entry_price_raw) / position.risk

        holding_seconds = None
        if position.entry_timestamp is not None and timestamp is not None:
            holding_seconds = (timestamp - position.entry_timestamp).total_seconds()

        return Trade(
            trade_id=f"{symbol.upper()}-{position.entry_timestamp}",
            symbol=symbol.upper(),
            direction=position.direction.value,
            signal_type=None if signal.signal_type is None else signal.signal_type.value,
            session=signal.session,
            signal_timestamp=signal.bar_timestamp,
            entry_timestamp=position.entry_timestamp,
            entry_price=position.entry_price_raw,
            stop_price=position.stop_price,
            target_price=position.target_price,
            atr=signal.atr,
            risk_reward_ratio=signal.risk_reward_ratio,
            screening_rr=signal.risk_reward_ratio,
            execution_rr=execution_rr,
            confluence_score=signal.confluence_score,
            opportunity_score=position.opportunity_score,
            volume_surge_ratio=signal.volume_surge_ratio,
            trend_alignment=signal.trend_aligned,
            exit_timestamp=timestamp,
            exit_price=exit_price_raw,
            exit_reason=reason,
            exit_signal_type=None if exit_signal is None else exit_signal.signal_type.value,
            exit_signal_direction=None if exit_signal is None else exit_signal.direction.value,
            gross_R=gross_R,
            net_R=net_R,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            holding_seconds=holding_seconds,
            mfe_price=position.mfe_price,
            mfe_pct=mfe_pct,
            mfe_r=mfe_r,
            mae_price=position.mae_price,
            mae_pct=mae_pct,
            mae_r=mae_r,
        )

    def open_symbols(self) -> list[str]:
        return list(self._open.keys())
