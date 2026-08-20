"""
talonx_backtest.portfolio
------------------------------
The Trade record -- one row per signal that actually reached a simulated
entry (see engine.py). A published signal that never got an entry
(e.g. data ended before its next bar arrived) is not represented here;
engine.BacktestResult.rejections/signals_generated cover the funnel
above entry.

Every field the backtest spec's "Trade lifecycle" section calls for is
present; a field that couldn't be computed (e.g. gross_R when risk
resolves to 0) is explicitly None, never a fabricated placeholder.

R:R fields (three, deliberately distinct -- see docs/backtesting.md's
"risk_reward_ratio vs gross_R/net_R" section for the full explanation):
  - risk_reward_ratio / screening_rr (identical, screening_rr is just an
    explicitly-named alias): the STRATEGY's own gate-time R:R, copied
    verbatim from the published QuantSignal -- risk = atr_stop_multiplier
    x ATR measured at revalidation time, reward = distance to the pivot
    target from the REVALIDATION-time reference price. This is the
    number min_risk_reward_ratio actually gated on; never recalculated
    against the executed fill, by design -- it's an audit trail of what
    the strategy approved, not a live-updating figure.
  - execution_rr: reward:risk using the REAL fill price (entry_price,
    the next bar's open) against the SAME fixed stop_price/target_price
    -- "what R:R was actually available at the price this order filled
    at." Independent of how the trade actually exited (STOP/EOD/DATA_END
    trades still get an execution_rr; it is NOT the same as gross_R/
    net_R, which depend on the actual exit price/reason, not the
    target). A reader can verify this one directly from entry_price/
    stop_price/target_price columns sitting right next to it, unlike
    screening_rr's ATR/revalidation-price inputs which aren't otherwise
    visible on the trade record.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Trade:
    trade_id: str
    symbol: str
    direction: str  # "bullish" / "bearish" -- SignalDirection.value

    signal_type: str | None
    session: str | None

    signal_timestamp: object  # pandas.Timestamp (tz-aware UTC)
    entry_timestamp: object | None
    entry_price: float | None

    stop_price: float | None
    target_price: float | None
    atr: float | None
    risk_reward_ratio: float | None  # == screening_rr; kept for backward compatibility
    screening_rr: float | None       # explicit alias of risk_reward_ratio -- see module docstring
    execution_rr: float | None       # reward:risk at the REAL fill price -- see module docstring
    confluence_score: int | None
    opportunity_score: float | None
    volume_surge_ratio: float | None
    trend_alignment: bool | None

    exit_timestamp: object | None
    exit_price: float | None
    exit_reason: str | None  # TARGET / STOP / END_OF_SESSION / DATA_END / SIGNAL_EXIT

    gross_R: float | None
    net_R: float | None
    gross_pnl: float | None
    net_pnl: float | None
    holding_seconds: float | None

    mfe_price: float | None
    mfe_pct: float | None
    mfe_r: float | None
    mae_price: float | None
    mae_pct: float | None
    mae_r: float | None

    # Task 25A: populated only when exit_reason == "SIGNAL_EXIT" -- the
    # BEARISH/CONTRADICTED QuantSignal's own type/direction that
    # triggered an alert-driven exit of an existing long, kept distinct
    # from the entry's own signal_type/direction above so a reader can
    # always tell what opened a trade apart from what alert-driven
    # signal (if any, as opposed to STOP/TARGET/EOD) closed it.
    exit_signal_type: str | None = None
    exit_signal_direction: str | None = None

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        for key in ("signal_timestamp", "entry_timestamp", "exit_timestamp"):
            if d.get(key) is not None:
                d[key] = str(d[key])
        return d
