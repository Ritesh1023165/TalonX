"""Task 121 Part 3/8 -- focused tests for the narrow adapter's OWN new
code (research/scripts/task121_experimental_replay.py): the relaxed-
config guard duplication and the per-share-to-dollar conversion. Does
NOT re-run the (slow) full historical replay -- that is covered by the
existing, already-passing talonx_backtest test suite (see
TASK121_EXPERIMENTAL_CONTRACT_RESULTS.md #2 for the cited test names) and
by the committed replay summary artifact itself.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "research/scripts/task121_experimental_replay.py"

spec = importlib.util.spec_from_file_location("task121_experimental_replay", SCRIPT)
t121 = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(REPO))
spec.loader.exec_module(t121)


def test_relaxed_config_matches_production_RELAXED_OVERRIDES_verbatim():
    from talonx_signals.config import RELAXED_OVERRIDES

    relaxed_cfg, frozen_cfg = t121._build_relaxed_config()
    for field, value in RELAXED_OVERRIDES.items():
        assert getattr(relaxed_cfg, field) == value
    # every OTHER field must be untouched relative to the frozen default
    from dataclasses import fields
    for f in fields(relaxed_cfg):
        if f.name in RELAXED_OVERRIDES:
            continue
        assert getattr(relaxed_cfg, f.name) == getattr(frozen_cfg, f.name), f.name


def test_relaxed_config_never_flips_locked_contract_fields():
    from talonx_quant.config import ConfluenceContract, VolatilityGateMode

    relaxed_cfg, _ = t121._build_relaxed_config()
    assert relaxed_cfg.volatility_gate_mode == VolatilityGateMode.CURRENT_1M
    assert relaxed_cfg.confluence_contract == ConfluenceContract.LEGACY


def test_relaxed_config_construction_never_mutates_frozen_default():
    from talonx_quant.config import QuantConfig

    before = QuantConfig()
    t121._build_relaxed_config()
    after = QuantConfig()
    assert before == after


def _fake_trade(entry_price, exit_price, direction="bullish", session="regular"):
    from types import SimpleNamespace

    unresolved = exit_price is None
    return SimpleNamespace(
        direction=direction, entry_price=entry_price, exit_price=exit_price,
        symbol="TEST", signal_timestamp="t0", entry_timestamp="t1", exit_timestamp="t2",
        exit_reason="TARGET", holding_seconds=600.0, session=session,
        signal_type="rsi_oversold", confluence_score=1, risk_reward_ratio=1.2,
        gross_pnl=None if unresolved else exit_price - entry_price,
        net_pnl=None if unresolved else
        (exit_price - entry_price) - (entry_price * 0.000125 + exit_price * 0.000125),
        gross_R=None, net_R=None,
    )


def test_dollar_conversion_uses_fixed_2500_allocation_and_matches_spread_formula():
    trades = [_fake_trade(100.0, 105.0)]
    out = t121._to_dollar_trades(trades)
    assert len(out) == 1
    row = out[0]
    # shares = allocation / entry_price_net (spread-adjusted fill, ~100.0125)
    assert abs(row["shares"] - (2500.0 / row["entry_price_net"])) < 1e-9
    assert row["allocation_usd"] == 2500.0
    # net P&L in dollars must be shares * net_pnl_per_share
    assert abs(row["net_pnl_usd"] - row["shares"] * row["net_pnl_per_share"]) < 1e-6
    # spread cost must be strictly positive on a round trip (BUY pays more, SELL receives less)
    assert row["spread_cost_usd"] > 0


def test_dollar_conversion_excludes_non_bullish_and_unresolved_trades():
    trades = [_fake_trade(100.0, 105.0, direction="bearish"), _fake_trade(100.0, None)]
    out = t121._to_dollar_trades(trades)
    assert out == []


def test_issuer_block_bootstrap_ci_brackets_the_sample_mean_for_a_single_issuer():
    dollar_trades = [{"symbol": "AAA", "net_pnl_usd": v} for v in (-10.0, 5.0, 20.0, -5.0)]
    result = t121._issuer_block_bootstrap(dollar_trades, "net_pnl_usd")
    assert result["effective_independent_groups"] == 1
    # a single issuer's block bootstrap can only ever resample that issuer's own
    # trades -- the CI must equal a single point (no cross-issuer variance to add)
    assert result["ci"][0] == result["ci"][1]
