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
    risk_reward_ratio: float | None
    confluence_score: int | None
    opportunity_score: float | None
    volume_surge_ratio: float | None
    trend_alignment: bool | None

    exit_timestamp: object | None
    exit_price: float | None
    exit_reason: str | None  # TARGET / STOP / END_OF_SESSION / DATA_END

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

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        for key in ("signal_timestamp", "entry_timestamp", "exit_timestamp"):
            if d.get(key) is not None:
                d[key] = str(d[key])
        return d
