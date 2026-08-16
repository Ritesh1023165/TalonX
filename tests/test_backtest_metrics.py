"""
tests/test_backtest_metrics.py
-----------------------------------
talonx_backtest.metrics: win rate, profit factor, expectancy, drawdown,
MFE/MAE aggregation, and the raw-vs-net (gross_R vs net_R) distinction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_backtest.metrics import compute_metrics, metric_set
from talonx_backtest.portfolio import Trade


def _dt(offset_minutes: int) -> datetime:
    return datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc) + timedelta(minutes=offset_minutes)


def _trade(gross_r: float, net_r: float | None = None, holding_min: float = 20.0, exit_offset: int = 0, mfe_r=None, mae_r=None) -> Trade:
    return Trade(
        trade_id="t", symbol="AAPL", direction="bullish", signal_type="rsi_oversold_volume_surge",
        session="regular", signal_timestamp=_dt(0), entry_timestamp=_dt(0), entry_price=100.0,
        stop_price=95.0, target_price=110.0, atr=1.0, risk_reward_ratio=2.0, confluence_score=3,
        opportunity_score=0.5, volume_surge_ratio=3.0, trend_alignment=True,
        exit_timestamp=_dt(exit_offset), exit_price=105.0, exit_reason="TARGET",
        gross_R=gross_r, net_R=gross_r if net_r is None else net_r,
        gross_pnl=gross_r * 5, net_pnl=(gross_r if net_r is None else net_r) * 5,
        holding_seconds=holding_min * 60,
        mfe_price=None, mfe_pct=None, mfe_r=mfe_r if mfe_r is not None else gross_r,
        mae_price=None, mae_pct=None, mae_r=mae_r if mae_r is not None else -0.2,
    )


def test_win_rate_and_counts():
    trades = [_trade(2.0), _trade(1.0), _trade(-1.0), _trade(0.0)]
    m = compute_metrics(trades, r_field="gross_R")
    assert m.total_trades == 4
    assert m.winning_trades == 2
    assert m.losing_trades == 1
    assert m.breakeven_trades == 1
    assert m.win_rate == pytest.approx(0.5)  # 2 wins / 4 trades with an R value (breakeven counts in the denominator)


def test_profit_factor_and_expectancy():
    trades = [_trade(2.0), _trade(2.0), _trade(-1.0)]
    m = compute_metrics(trades, r_field="gross_R")
    assert m.profit_factor == pytest.approx(4.0)  # gross profit 4 / gross loss 1
    assert m.expectancy_r == pytest.approx((2.0 + 2.0 - 1.0) / 3)
    assert m.total_r == pytest.approx(3.0)
    assert m.average_win_r == pytest.approx(2.0)
    assert m.average_loss_r == pytest.approx(-1.0)


def test_profit_factor_is_infinite_with_no_losses():
    trades = [_trade(1.0), _trade(2.0)]
    m = compute_metrics(trades, r_field="gross_R")
    assert m.profit_factor == float("inf")


def test_profit_factor_is_none_with_no_trades():
    m = compute_metrics([], r_field="gross_R")
    assert m.profit_factor is None
    assert m.total_trades == 0
    assert m.win_rate is None


def test_max_drawdown_on_a_losing_streak():
    # Ordered by exit_timestamp: +1R, -1R, -1R, -1R, +0.5R -- drawdown
    # bottoms out at -3R after the third loss, before the partial recovery.
    trades = [
        _trade(1.0, exit_offset=0), _trade(-1.0, exit_offset=1), _trade(-1.0, exit_offset=2),
        _trade(-1.0, exit_offset=3), _trade(0.5, exit_offset=4),
    ]
    m = compute_metrics(trades, r_field="gross_R")
    assert m.max_drawdown_r == pytest.approx(-3.0)


def test_max_drawdown_is_zero_for_a_pure_winning_streak():
    trades = [_trade(1.0, exit_offset=0), _trade(1.0, exit_offset=1)]
    m = compute_metrics(trades, r_field="gross_R")
    assert m.max_drawdown_r == pytest.approx(0.0)


def test_median_and_best_worst():
    trades = [_trade(1.0), _trade(3.0), _trade(-2.0)]
    m = compute_metrics(trades, r_field="gross_R")
    assert m.median_r == pytest.approx(1.0)
    assert m.best_trade_r == pytest.approx(3.0)
    assert m.worst_trade_r == pytest.approx(-2.0)


def test_holding_time_stats():
    trades = [_trade(1.0, holding_min=10.0), _trade(1.0, holding_min=30.0)]
    m = compute_metrics(trades, r_field="gross_R")
    assert m.average_holding_seconds == pytest.approx(20 * 60)
    assert m.median_holding_seconds == pytest.approx(20 * 60)


def test_mfe_mae_averages():
    trades = [_trade(1.0, mfe_r=2.0, mae_r=-0.5), _trade(-1.0, mfe_r=0.5, mae_r=-1.5)]
    m = compute_metrics(trades, r_field="gross_R")
    assert m.average_mfe_r == pytest.approx(1.25)
    assert m.average_mae_r == pytest.approx(-1.0)


def test_mfe_mae_are_split_by_win_loss_outcome():
    # winner (gross_R=1.0): mfe_r=2.8, mae_r=-0.3
    # loser  (gross_R=-1.0): mfe_r=0.5, mae_r=-1.05
    trades = [_trade(1.0, mfe_r=2.8, mae_r=-0.3), _trade(-1.0, mfe_r=0.5, mae_r=-1.05)]
    m = compute_metrics(trades, r_field="gross_R")
    assert m.winners_average_mfe_r == pytest.approx(2.8)
    assert m.winners_average_mae_r == pytest.approx(-0.3)
    assert m.losers_average_mfe_r == pytest.approx(0.5)
    assert m.losers_average_mae_r == pytest.approx(-1.05)
    # the aggregate (unsplit) fields still blend both outcomes
    assert m.average_mfe_r == pytest.approx((2.8 + 0.5) / 2)


def test_mfe_mae_split_is_none_when_that_outcome_has_no_trades():
    trades = [_trade(1.0, mfe_r=2.0, mae_r=-0.2)]  # winners only
    m = compute_metrics(trades, r_field="gross_R")
    assert m.winners_average_mfe_r == pytest.approx(2.0)
    assert m.losers_average_mfe_r is None
    assert m.losers_average_mae_r is None


def test_gross_vs_net_are_distinct_series():
    trades = [_trade(2.0, net_r=1.5), _trade(-1.0, net_r=-1.3)]
    sets = metric_set(trades)
    assert sets["gross"].total_r == pytest.approx(1.0)
    assert sets["net"].total_r == pytest.approx(0.2)
    assert sets["gross"].r_field == "gross_R"
    assert sets["net"].r_field == "net_R"


def test_confidence_intervals_present_with_enough_trades():
    trades = [_trade(1.0), _trade(-1.0), _trade(2.0), _trade(0.5), _trade(-0.5)]
    m = compute_metrics(trades, r_field="gross_R")
    assert m.average_r_ci is not None
    assert m.average_r_ci.n == 5
    assert m.win_rate_ci is not None


def test_confidence_interval_is_none_with_fewer_than_two_trades():
    m = compute_metrics([_trade(1.0)], r_field="gross_R")
    assert m.average_r_ci is None


def test_invalid_r_field_rejected():
    with pytest.raises(ValueError):
        compute_metrics([_trade(1.0)], r_field="not_a_field")
