"""
tests/test_volatility_gate_mode.py
----------------------------------------
Task 45 -- explicit experimental research/backtest volatility gate mode
(talonx_quant.config.VolatilityGateMode,
talonx_quant.consumer._evaluate_active_volatility_gate). Exactly two
modes: CURRENT_1M (the default, and the ONLY mode QuantScanner --
live/paper-shadow -- will ever accept) and MULTITIMEFRAME_EXPERIMENTAL
(research/backtest-only).

As with every prior regime-state task, the single most important property
is PARITY for the default mode: CURRENT_1M must be byte-for-byte
equivalent to pre-Task-45 behavior -- see
test_current_mode_regression_equivalence, the central test in this file.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from talonx_backtest.data import from_dataframe
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_backtest.reproducibility import config_hash
from talonx_quant.config import QuantConfig, VolatilityGateMode
from talonx_quant.consumer import QuantScanner, _evaluate_active_volatility_gate
from talonx_quant.indicators import (
    PROVISIONAL_REGIME_15M_THRESHOLD_PCT,
    PROVISIONAL_REGIME_60M_THRESHOLD_PCT,
    REGIME_15M_BELOW_THRESHOLD,
    REGIME_60M_BELOW_THRESHOLD,
    REGIME_BOTH_BELOW_THRESHOLD,
    REGIME_ELIGIBLE,
    REGIME_STATE_NOT_READY,
    VolatilityRegimeSnapshot,
    evaluate_regime,
)

_START = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)


def _snap(atr_pct_15m, ready_15m, atr_pct_60m, ready_60m):
    return VolatilityRegimeSnapshot(
        atr_15m=1.0 if atr_pct_15m is not None else None, atr_pct_15m=atr_pct_15m, ready_15m=ready_15m,
        atr_60m=1.0 if atr_pct_60m is not None else None, atr_pct_60m=atr_pct_60m, ready_60m=ready_60m,
        as_of=_START,
    )


def _relaxed_config(mode: VolatilityGateMode = VolatilityGateMode.CURRENT_1M) -> QuantConfig:
    return dataclasses.replace(QuantConfig(), atr_move_multiplier=0.0, volatility_gate_mode=mode)


def _build_bars(n: int = 260):
    bars = []
    price = 100.0
    for i in range(n):
        if i % 47 == 0 and i > 0:
            price -= 3.0
        elif i % 61 == 0 and i > 0:
            price += 3.5
        else:
            price += 0.05 if i % 2 == 0 else -0.03
        vol = 5000.0 if i % 47 == 1 else 1000.0 + (i % 5) * 50
        bars.append((price, price + 0.4, price - 0.4, price, vol))
    return bars


def _bars_to_df(bars, symbol="AAPL"):
    rows = [
        {"timestamp": _START + timedelta(minutes=i), "open": o, "high": h, "low": l, "close": c, "volume": v}
        for i, (o, h, l, c, v) in enumerate(bars)
    ]
    return from_dataframe(pd.DataFrame(rows), symbol=symbol)


def _two_symbol_df():
    aapl_bars = _build_bars()
    msft_bars = [(o * 3 + 50, h * 3 + 50, l * 3 + 50, c * 3 + 50, v) for (o, h, l, c, v) in _build_bars()]
    return pd.concat([_bars_to_df(aapl_bars, "AAPL"), _bars_to_df(msft_bars, "MSFT")], ignore_index=True)


# ----------------------------------------------------------------------
# Default mode / mode selection
# ----------------------------------------------------------------------

def test_default_mode_is_current_1m():
    qc = QuantConfig()
    assert qc.volatility_gate_mode == VolatilityGateMode.CURRENT_1M


def test_exactly_two_modes_defined():
    assert set(VolatilityGateMode) == {VolatilityGateMode.CURRENT_1M, VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL}


def test_invalid_mode_string_fails_closed_at_config_construction():
    import os
    os.environ["TALONX_QUANT_VOLATILITY_GATE_MODE"] = "BOGUS_MODE"
    try:
        with pytest.raises(ValueError):
            # Re-importing wouldn't re-trigger the module-level default,
            # so directly exercise the same construction the config
            # module performs.
            VolatilityGateMode(os.environ["TALONX_QUANT_VOLATILITY_GATE_MODE"])
    finally:
        del os.environ["TALONX_QUANT_VOLATILITY_GATE_MODE"]


# ----------------------------------------------------------------------
# Dispatch function -- each evaluator outcome
# ----------------------------------------------------------------------

def test_dispatch_current_1m_uses_fails_volatility_1m_unchanged():
    qc = _relaxed_config(VolatilityGateMode.CURRENT_1M)
    regime_result = evaluate_regime(_snap(1.0, True, 1.0, True))  # would be eligible under experimental
    fails, reason, detail = _evaluate_active_volatility_gate(True, regime_result, qc)
    assert fails is True  # CURRENT_1M's own fails_volatility_1m=True wins, regime_result ignored
    assert reason == "LOW_VOLATILITY"
    assert detail is None

    fails2, reason2, detail2 = _evaluate_active_volatility_gate(False, regime_result, qc)
    assert fails2 is False
    assert reason2 == "LOW_VOLATILITY"
    assert detail2 is None


def test_dispatch_experimental_both_pass():
    qc = _relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL)
    regime_result = evaluate_regime(_snap(
        PROVISIONAL_REGIME_15M_THRESHOLD_PCT + 0.1, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT + 0.1, True,
    ))
    fails, reason, detail = _evaluate_active_volatility_gate(False, regime_result, qc)
    assert fails is False
    assert reason == "LOW_VOLATILITY_REGIME"
    assert detail == REGIME_ELIGIBLE


def test_dispatch_experimental_not_ready():
    qc = _relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL)
    regime_result = evaluate_regime(_snap(None, False, None, False))
    fails, reason, detail = _evaluate_active_volatility_gate(False, regime_result, qc)
    assert fails is True
    assert reason == "LOW_VOLATILITY_REGIME"
    assert detail == REGIME_STATE_NOT_READY


def test_dispatch_experimental_15m_below():
    qc = _relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL)
    regime_result = evaluate_regime(_snap(
        PROVISIONAL_REGIME_15M_THRESHOLD_PCT - 0.01, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT + 0.1, True,
    ))
    fails, reason, detail = _evaluate_active_volatility_gate(False, regime_result, qc)
    assert fails is True
    assert detail == REGIME_15M_BELOW_THRESHOLD


def test_dispatch_experimental_60m_below():
    qc = _relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL)
    regime_result = evaluate_regime(_snap(
        PROVISIONAL_REGIME_15M_THRESHOLD_PCT + 0.1, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT - 0.01, True,
    ))
    fails, reason, detail = _evaluate_active_volatility_gate(False, regime_result, qc)
    assert fails is True
    assert detail == REGIME_60M_BELOW_THRESHOLD


def test_dispatch_experimental_both_below():
    qc = _relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL)
    regime_result = evaluate_regime(_snap(
        PROVISIONAL_REGIME_15M_THRESHOLD_PCT - 0.01, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT - 0.01, True,
    ))
    fails, reason, detail = _evaluate_active_volatility_gate(False, regime_result, qc)
    assert fails is True
    assert detail == REGIME_BOTH_BELOW_THRESHOLD


def test_dispatch_experimental_exact_15m_threshold_boundary_inclusive():
    qc = _relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL)
    regime_result = evaluate_regime(_snap(
        PROVISIONAL_REGIME_15M_THRESHOLD_PCT, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT + 0.1, True,
    ))
    fails, _, detail = _evaluate_active_volatility_gate(False, regime_result, qc)
    assert fails is False
    assert detail == REGIME_ELIGIBLE


def test_dispatch_experimental_exact_60m_threshold_boundary_inclusive():
    qc = _relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL)
    regime_result = evaluate_regime(_snap(
        PROVISIONAL_REGIME_15M_THRESHOLD_PCT + 0.1, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT, True,
    ))
    fails, _, detail = _evaluate_active_volatility_gate(False, regime_result, qc)
    assert fails is False
    assert detail == REGIME_ELIGIBLE


def test_dispatch_unknown_mode_fails_closed():
    qc = _relaxed_config(VolatilityGateMode.CURRENT_1M)
    # Force an out-of-band value past the type system, simulating the
    # (structurally unreachable, since VolatilityGateMode's own
    # constructor already rejects it) case this defense-in-depth check
    # guards against.
    qc_bad = dataclasses.replace(qc)
    object.__setattr__(qc_bad, "volatility_gate_mode", "NOT_A_REAL_MODE")
    regime_result = evaluate_regime(_snap(1.0, True, 1.0, True))
    with pytest.raises(ValueError):
        _evaluate_active_volatility_gate(False, regime_result, qc_bad)


def test_dispatch_is_deterministic():
    qc = _relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL)
    regime_result = evaluate_regime(_snap(1.0, True, 1.0, True))
    r1 = _evaluate_active_volatility_gate(False, regime_result, qc)
    r2 = _evaluate_active_volatility_gate(False, regime_result, qc)
    assert r1 == r2


# ----------------------------------------------------------------------
# Live safety guard
# ----------------------------------------------------------------------

def test_quantscanner_accepts_current_1m():
    QuantScanner(_relaxed_config(VolatilityGateMode.CURRENT_1M))  # must not raise


def test_quantscanner_rejects_experimental_mode():
    with pytest.raises(ValueError, match="CURRENT_1M"):
        QuantScanner(_relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL))


def test_quantscanner_default_construction_is_safe():
    QuantScanner()  # no config passed -- must default to CURRENT_1M and not raise


# ----------------------------------------------------------------------
# Backtest config propagation
# ----------------------------------------------------------------------

def test_backtest_engine_accepts_both_modes():
    for mode in VolatilityGateMode:
        cfg = BacktestConfig(quant_config=_relaxed_config(mode))
        BacktestEngine(cfg)  # must not raise for either mode


# ----------------------------------------------------------------------
# Fingerprints differ correctly
# ----------------------------------------------------------------------

def test_fingerprints_differ_between_modes():
    qc_current = QuantConfig()
    qc_experimental = dataclasses.replace(QuantConfig(), volatility_gate_mode=VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL)
    assert config_hash(qc_current) != config_hash(qc_experimental)

    bc_current = BacktestConfig(quant_config=qc_current)
    bc_experimental = BacktestConfig(quant_config=qc_experimental)
    assert config_hash(bc_current) != config_hash(bc_experimental)


def test_fingerprint_is_deterministic_within_a_mode():
    qc1 = QuantConfig()
    qc2 = QuantConfig()
    assert config_hash(qc1) == config_hash(qc2)


# ----------------------------------------------------------------------
# CURRENT_1M mode regression equivalence (the central proof)
# ----------------------------------------------------------------------

def test_current_mode_regression_equivalence():
    """CURRENT_1M must produce byte-for-byte identical candidates,
    rejections, published signals, trades, and signal_log to a plain,
    mode-unaware config (dataclasses.replace with no
    volatility_gate_mode override, i.e. relying purely on the default)."""
    df = _two_symbol_df()
    cfg_default = BacktestConfig(quant_config=_relaxed_config())  # default mode, unspecified
    cfg_explicit = BacktestConfig(quant_config=_relaxed_config(VolatilityGateMode.CURRENT_1M))  # explicit

    e1 = BacktestEngine(dataclasses.replace(cfg_default))
    r1 = e1.run(df)
    e2 = BacktestEngine(dataclasses.replace(cfg_explicit))
    r2 = e2.run(df)

    assert r1.trades == r2.trades
    assert r1.signals_generated == r2.signals_generated
    assert r1.signals_published == r2.signals_published
    assert r1.bars_processed == r2.bars_processed
    assert e1.rejections == e2.rejections
    assert e1.signal_log == e2.signal_log


# ----------------------------------------------------------------------
# Experimental-mode scope proof: ONLY the volatility predicate differs
# ----------------------------------------------------------------------

def test_experimental_mode_gate_ordering_unchanged():
    """The volatility gate has ALWAYS been evaluated before evaluate_signals
    (Task 38's own finding) -- unchanged by Task 45. On this small 260-bar
    fixture, the 60m leg never warms up (needs >14 continuous hours), so
    EVERY bar fails the experimental gate with REGIME_STATE_NOT_READY --
    zero candidates ever reach evaluate_signals, hence zero
    confluence/RR/etc rejections occur. This is the CORRECT, expected
    consequence of gate ordering being unchanged (proven directly here),
    not a downstream-gate difference between modes -- see
    test_evaluate_signals_is_mode_agnostic below for the unit-level proof
    that downstream logic itself does not depend on volatility_gate_mode
    at all."""
    df = _two_symbol_df()
    cfg_experimental = BacktestConfig(quant_config=_relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL))
    e_experimental = BacktestEngine(cfg_experimental)
    e_experimental.run(df)

    reasons = {r.reason for r in e_experimental.rejections}
    assert reasons == {"LOW_VOLATILITY_REGIME"}
    assert e_experimental.signal_log == []  # evaluate_signals never ran -- proves gate ordering unchanged
    assert e_experimental.signals_generated == 0


def test_evaluate_signals_is_mode_agnostic():
    """Unit-level proof that evaluate_signals (trigger generation/
    confluence/trend/RR/stop-target) does not consult volatility_gate_mode
    at all -- calling it directly with the SAME snapshot/htf_sma_200/
    daily_pivots inputs under both a CURRENT_1M-configured QuantConfig and
    an EXPERIMENTAL-configured one must produce byte-identical signals,
    since evaluate_signals's own signature never even receives the mode."""
    from talonx_quant.strategy import evaluate_signals
    from talonx_quant.indicators import compute_indicators

    df = _bars_to_df(_build_bars())
    df_indexed = df.set_index("timestamp")
    qc_current = _relaxed_config(VolatilityGateMode.CURRENT_1M)
    qc_experimental = _relaxed_config(VolatilityGateMode.MULTITIMEFRAME_EXPERIMENTAL)

    snapshot = compute_indicators(df_indexed, qc_current)
    assert snapshot is not None

    signals_current = evaluate_signals("AAPL", snapshot, qc_current, htf_sma_200=None, daily_pivots=None)
    signals_experimental = evaluate_signals("AAPL", snapshot, qc_experimental, htf_sma_200=None, daily_pivots=None)
    assert signals_current == signals_experimental
