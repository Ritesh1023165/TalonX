"""
tests/test_backtest_analysis.py
------------------------------------
talonx_backtest.analysis: breakdowns (confluence/R:R/volume/trend/
session/direction), exit-reason counts, walk-forward date splitting, and
ablation config generation. Descriptive only -- these tests also assert
nothing here mutates or "picks a winner" from the frozen QuantConfig.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pandas as pd
import pytest

from talonx_backtest.analysis import (
    TIME_OF_DAY_ORDER,
    ablation_configs,
    by_confluence,
    by_direction,
    by_risk_reward,
    by_session,
    by_symbol,
    by_time_of_day,
    by_trend_alignment,
    by_volume_surge,
    exit_reason_counts,
    walk_forward_split,
)
from talonx_backtest.portfolio import Trade
from talonx_quant.config import QuantConfig


def _trade(**overrides) -> Trade:
    defaults = dict(
        trade_id="t", symbol="AAPL", direction="bullish", signal_type="rsi_oversold_volume_surge",
        session="regular", signal_timestamp=datetime(2026, 1, 5, tzinfo=timezone.utc),
        entry_timestamp=datetime(2026, 1, 5, tzinfo=timezone.utc), entry_price=100.0,
        stop_price=95.0, target_price=110.0, atr=1.0, risk_reward_ratio=2.2, confluence_score=2,
        opportunity_score=0.5, volume_surge_ratio=2.5, trend_alignment=True,
        exit_timestamp=datetime(2026, 1, 5, 0, 20, tzinfo=timezone.utc), exit_price=105.0,
        exit_reason="TARGET", gross_R=1.0, net_R=0.9, gross_pnl=5.0, net_pnl=4.5, holding_seconds=1200.0,
        mfe_price=None, mfe_pct=None, mfe_r=1.2, mae_price=None, mae_pct=None, mae_r=-0.3,
    )
    defaults.update(overrides)
    return Trade(**defaults)


def test_by_confluence_buckets():
    trades = [_trade(confluence_score=2), _trade(confluence_score=3), _trade(confluence_score=3)]
    result = by_confluence(trades)
    assert set(result.keys()) == {"2/3", "3/3"}
    assert result["3/3"].total_trades == 2
    assert result["2/3"].total_trades == 1


def test_by_risk_reward_buckets():
    trades = [_trade(risk_reward_ratio=1.6), _trade(risk_reward_ratio=2.3), _trade(risk_reward_ratio=3.5)]
    result = by_risk_reward(trades)
    assert set(result.keys()) == {"1.5-2.0", "2.0-2.5", "3.0+"}


def test_by_volume_surge_buckets():
    trades = [_trade(volume_surge_ratio=2.5), _trade(volume_surge_ratio=6.0), _trade(volume_surge_ratio=12.0)]
    result = by_volume_surge(trades)
    assert set(result.keys()) == {"2-3x", "5-10x", "10x+"}


def test_by_trend_alignment_buckets():
    trades = [_trade(trend_alignment=True), _trade(trend_alignment=False), _trade(trend_alignment=None)]
    result = by_trend_alignment(trades)
    assert set(result.keys()) == {"aligned", "misaligned", "neutral"}


def test_by_session_and_direction():
    trades = [_trade(session="regular"), _trade(session="pre_market"), _trade(direction="bearish")]
    assert set(by_session(trades).keys()) == {"regular", "pre_market"}
    assert set(by_direction(trades).keys()) == {"bullish", "bearish"}


def test_by_symbol_buckets():
    trades = [_trade(symbol="AAPL"), _trade(symbol="AAPL"), _trade(symbol="MSFT")]
    result = by_symbol(trades)
    assert set(result.keys()) == {"AAPL", "MSFT"}
    assert result["AAPL"].total_trades == 2
    assert result["MSFT"].total_trades == 1


def test_by_time_of_day_buckets_use_et_entry_time():
    # Jan -> EST (UTC-5): 13:00 UTC = 08:00 ET (premarket), 14:45 UTC =
    # 09:45 ET (first_30m), 17:00 UTC = 12:00 ET (midday), 20:30 UTC =
    # 15:30 ET (last_hour), 22:00 UTC = 17:00 ET (after_hours).
    trades = [
        _trade(entry_timestamp=datetime(2026, 1, 5, 13, 0, tzinfo=timezone.utc)),
        _trade(entry_timestamp=datetime(2026, 1, 5, 14, 45, tzinfo=timezone.utc)),
        _trade(entry_timestamp=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc)),
        _trade(entry_timestamp=datetime(2026, 1, 5, 20, 30, tzinfo=timezone.utc)),
        _trade(entry_timestamp=datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc)),
    ]
    result = by_time_of_day(trades)
    assert set(result.keys()) == {"premarket", "first_30m", "midday", "last_hour", "after_hours"}
    for bucket in result:
        assert bucket in TIME_OF_DAY_ORDER


def test_by_time_of_day_skips_trades_with_no_entry_timestamp():
    trades = [_trade(entry_timestamp=None)]
    result = by_time_of_day(trades)
    assert result == {}


def test_exit_reason_counts():
    trades = [_trade(exit_reason="TARGET"), _trade(exit_reason="TARGET"), _trade(exit_reason="STOP")]
    counts = exit_reason_counts(trades)
    assert counts == {"STOP": 1, "TARGET": 2}


def test_walk_forward_split_is_chronological_and_non_overlapping():
    ts = pd.date_range("2024-01-01", "2026-06-30", freq="7D", tz="UTC")
    df = pd.DataFrame({
        "timestamp": ts, "symbol": "AAPL", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
    })
    split = walk_forward_split(df, train_end="2025-01-01", validation_end="2025-07-01", out_of_sample_end="2026-01-01")

    assert split.train["timestamp"].max() < pd.Timestamp("2025-01-01", tz="UTC")
    assert split.validation["timestamp"].min() >= pd.Timestamp("2025-01-01", tz="UTC")
    assert split.validation["timestamp"].max() < pd.Timestamp("2025-07-01", tz="UTC")
    assert split.out_of_sample["timestamp"].min() >= pd.Timestamp("2025-07-01", tz="UTC")
    assert split.out_of_sample["timestamp"].max() <= pd.Timestamp("2026-01-01", tz="UTC")
    # no row appears in more than one slice
    total = len(split.train) + len(split.validation) + len(split.out_of_sample)
    assert total <= len(df)


def test_ablation_configs_include_baseline_and_do_not_mutate_it():
    base = QuantConfig()
    configs = ablation_configs(base)

    assert "baseline" in configs
    assert configs["baseline"] == base
    assert configs["baseline"] is not base  # a copy, not the same frozen instance

    assert configs["baseline_minus_rsi"].rsi_oversold == -1.0
    assert configs["baseline_minus_trend_gate"].trend_gate_enabled is False
    # the original, frozen production config is completely untouched
    assert base.rsi_oversold == 30.0
    assert base.trend_gate_enabled is True


def test_ablation_configs_are_independent_dataclass_instances():
    base = QuantConfig()
    configs = ablation_configs(base)
    labels = list(configs.keys())
    assert len(labels) == len(set(labels))
    for label, cfg in configs.items():
        assert dataclasses.is_dataclass(cfg)
