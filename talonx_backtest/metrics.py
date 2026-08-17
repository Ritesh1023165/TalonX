"""
talonx_backtest.metrics
----------------------------
Performance metrics computed purely from a list of closed
portfolio.Trade records. No look-ahead concerns here (that's engine.py's
job) -- this module is pure, descriptive statistics.

Every trade carries both a gross_R (before slippage/spread) and net_R
(after) -- see execution.py. `compute_metrics` is run once per R series
via `metric_set`, so a report can show RAW STRATEGY RETURN and NET
RETURN AFTER COSTS side by side rather than conflating them (spec
section 8).

Statistical-confidence note: confidence intervals here use the NORMAL
approximation (z=1.96 for 95%), not a t-distribution or bootstrap --
deliberately dependency-light (no scipy requirement for talonx_backtest
itself) and clearly labeled as approximate, which matters most exactly
when it's least accurate: small trade counts. Never treat a CI from
under ~30 trades as tight.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from talonx_backtest.portfolio import Trade


@dataclass(frozen=True)
class ConfidenceInterval:
    point_estimate: float
    lower_95: float
    upper_95: float
    n: int

    def summary(self) -> str:
        return f"{self.point_estimate:.4f} (95% CI [{self.lower_95:.4f}, {self.upper_95:.4f}], n={self.n})"


@dataclass(frozen=True)
class PerformanceMetrics:
    r_field: str  # "gross_R" or "net_R" -- which return series this was computed from

    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: float | None

    average_win_r: float | None
    average_loss_r: float | None
    average_r: float | None
    median_r: float | None
    total_r: float | None

    profit_factor: float | None
    expectancy_r: float | None
    max_drawdown_r: float | None

    average_holding_seconds: float | None
    median_holding_seconds: float | None

    best_trade_r: float | None
    worst_trade_r: float | None

    average_mfe_r: float | None
    average_mae_r: float | None
    # Win/loss-split excursion (how far a trade ran in its favor before
    # exiting, segmented by outcome): "winning trades typically reach
    # +2.8R before exiting at +1.4R" is a very different, more actionable
    # statement than an aggregate MFE blended across wins and losses --
    # this is what actually informs a stop/target-placement discussion
    # (kept purely descriptive; nothing here changes the frozen strategy).
    winners_average_mfe_r: float | None
    winners_average_mae_r: float | None
    losers_average_mfe_r: float | None
    losers_average_mae_r: float | None

    sharpe_per_trade: float | None
    sortino_per_trade: float | None

    win_rate_ci: ConfidenceInterval | None = field(default=None)
    expectancy_ci: ConfidenceInterval | None = field(default=None)
    average_r_ci: ConfidenceInterval | None = field(default=None)

    def summary_lines(self) -> list[str]:
        def fmt(x, suffix=""):
            return "n/a" if x is None else f"{x:.4f}{suffix}"

        return [
            f"Return series:        {self.r_field}",
            f"Total trades:         {self.total_trades}",
            f"Winning / Losing:     {self.winning_trades} / {self.losing_trades} (breakeven {self.breakeven_trades})",
            f"Win rate:             {fmt(self.win_rate)}",
            f"Average win (R):      {fmt(self.average_win_r)}",
            f"Average loss (R):     {fmt(self.average_loss_r)}",
            f"Average R:            {fmt(self.average_r)}",
            f"Median R:             {fmt(self.median_r)}",
            f"Total R:              {fmt(self.total_r)}",
            f"Profit factor:        {fmt(self.profit_factor)}",
            f"Expectancy (R/trade): {fmt(self.expectancy_r)}",
            f"Max drawdown (R):     {fmt(self.max_drawdown_r)}",
            f"Avg holding time:     {fmt(None if self.average_holding_seconds is None else self.average_holding_seconds / 60.0, ' min')}",
            f"Median holding time:  {fmt(None if self.median_holding_seconds is None else self.median_holding_seconds / 60.0, ' min')}",
            f"Best trade (R):       {fmt(self.best_trade_r)}",
            f"Worst trade (R):      {fmt(self.worst_trade_r)}",
            f"Average MFE (R):      {fmt(self.average_mfe_r)}",
            f"Average MAE (R):      {fmt(self.average_mae_r)}",
            f"  Winners -- avg MFE: {fmt(self.winners_average_mfe_r)}   avg MAE: {fmt(self.winners_average_mae_r)}",
            f"  Losers  -- avg MFE: {fmt(self.losers_average_mfe_r)}   avg MAE: {fmt(self.losers_average_mae_r)}",
            f"Sharpe (per-trade):   {fmt(self.sharpe_per_trade)}",
            f"Sortino (per-trade):  {fmt(self.sortino_per_trade)}",
        ]


def _ci_normal_approx(values: list[float]) -> ConfidenceInterval | None:
    n = len(values)
    if n < 2:
        return None
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    margin = 1.96 * (stdev / math.sqrt(n))
    return ConfidenceInterval(point_estimate=mean, lower_95=mean - margin, upper_95=mean + margin, n=n)


def _win_rate_ci(n_wins: int, n_total: int) -> ConfidenceInterval | None:
    if n_total == 0:
        return None
    p = n_wins / n_total
    margin = 1.96 * math.sqrt(max(p * (1 - p), 0.0) / n_total)
    return ConfidenceInterval(
        point_estimate=p, lower_95=max(0.0, p - margin), upper_95=min(1.0, p + margin), n=n_total,
    )


def compute_metrics(trades: list[Trade], r_field: str = "net_R") -> PerformanceMetrics:
    """`r_field`: "gross_R" (raw strategy return, before costs) or
    "net_R" (after slippage/spread). Only CLOSED trades with a non-None
    value in that field contribute to the R-based statistics; every
    other field (win rate, holding time) still uses every closed trade
    regardless."""
    if r_field not in ("gross_R", "net_R"):
        raise ValueError(f"r_field must be 'gross_R' or 'net_R', got {r_field!r}")

    total_trades = len(trades)
    r_values = [getattr(t, r_field) for t in trades if getattr(t, r_field) is not None]

    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r < 0]
    breakeven = [r for r in r_values if r == 0]

    win_rate = (len(wins) / len(r_values)) if r_values else None
    average_win = statistics.mean(wins) if wins else None
    average_loss = statistics.mean(losses) if losses else None
    average_r = statistics.mean(r_values) if r_values else None
    median_r = statistics.median(r_values) if r_values else None
    total_r = sum(r_values) if r_values else None

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (math.inf if gross_profit > 0 else None)

    expectancy = average_r  # expectancy per trade IS the mean R, kept as a distinct named field per spec

    max_drawdown = _max_drawdown_r(trades, r_field)

    holding = [t.holding_seconds for t in trades if t.holding_seconds is not None]
    avg_holding = statistics.mean(holding) if holding else None
    median_holding = statistics.median(holding) if holding else None

    best = max(r_values) if r_values else None
    worst = min(r_values) if r_values else None

    mfe_r_values = [t.mfe_r for t in trades if t.mfe_r is not None]
    mae_r_values = [t.mae_r for t in trades if t.mae_r is not None]
    avg_mfe = statistics.mean(mfe_r_values) if mfe_r_values else None
    avg_mae = statistics.mean(mae_r_values) if mae_r_values else None

    winner_trades = [t for t in trades if getattr(t, r_field) is not None and getattr(t, r_field) > 0]
    loser_trades = [t for t in trades if getattr(t, r_field) is not None and getattr(t, r_field) < 0]
    winners_mfe = [t.mfe_r for t in winner_trades if t.mfe_r is not None]
    winners_mae = [t.mae_r for t in winner_trades if t.mae_r is not None]
    losers_mfe = [t.mfe_r for t in loser_trades if t.mfe_r is not None]
    losers_mae = [t.mae_r for t in loser_trades if t.mae_r is not None]

    sharpe = None
    sortino = None
    if len(r_values) >= 2:
        stdev = statistics.stdev(r_values)
        if stdev > 0:
            sharpe = statistics.mean(r_values) / stdev
        downside = [min(r, 0.0) for r in r_values]
        downside_stdev = statistics.pstdev(downside) if any(d < 0 for d in downside) else 0.0
        if downside_stdev > 0:
            sortino = statistics.mean(r_values) / downside_stdev

    return PerformanceMetrics(
        r_field=r_field,
        total_trades=total_trades,
        winning_trades=len(wins),
        losing_trades=len(losses),
        breakeven_trades=len(breakeven),
        win_rate=win_rate,
        average_win_r=average_win,
        average_loss_r=average_loss,
        average_r=average_r,
        median_r=median_r,
        total_r=total_r,
        profit_factor=profit_factor,
        expectancy_r=expectancy,
        max_drawdown_r=max_drawdown,
        average_holding_seconds=avg_holding,
        median_holding_seconds=median_holding,
        best_trade_r=best,
        worst_trade_r=worst,
        average_mfe_r=avg_mfe,
        average_mae_r=avg_mae,
        winners_average_mfe_r=statistics.mean(winners_mfe) if winners_mfe else None,
        winners_average_mae_r=statistics.mean(winners_mae) if winners_mae else None,
        losers_average_mfe_r=statistics.mean(losers_mfe) if losers_mfe else None,
        losers_average_mae_r=statistics.mean(losers_mae) if losers_mae else None,
        sharpe_per_trade=sharpe,
        sortino_per_trade=sortino,
        win_rate_ci=_win_rate_ci(len(wins), len(r_values)),
        expectancy_ci=_ci_normal_approx(r_values),
        average_r_ci=_ci_normal_approx(r_values),
    )


def _max_drawdown_r(trades: list[Trade], r_field: str) -> float | None:
    """Peak-to-trough drawdown of the cumulative-R equity curve, trades
    ordered by exit_timestamp (the order P&L was actually realized in)."""
    ordered = sorted(
        (t for t in trades if getattr(t, r_field) is not None and t.exit_timestamp is not None),
        key=lambda t: t.exit_timestamp,
    )
    if not ordered:
        return None

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in ordered:
        cumulative += getattr(t, r_field)
        peak = max(peak, cumulative)
        max_dd = min(max_dd, cumulative - peak)
    return max_dd  # <= 0; report as a negative R figure


def metric_set(trades: list[Trade]) -> dict[str, PerformanceMetrics]:
    """Both the raw (pre-cost) and net (post-cost) metric sets, side by
    side -- spec section 8's "clearly distinguish raw strategy return
    from net return after costs" requirement."""
    return {
        "gross": compute_metrics(trades, r_field="gross_R"),
        "net": compute_metrics(trades, r_field="net_R"),
    }
