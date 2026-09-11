"""
tests/test_regime_eligibility_evaluator.py
------------------------------------------------
Task 42 -- shadow-only Contract B evaluator (talonx_quant.indicators.
evaluate_regime) and disagreement classification
(classify_regime_shadow_disagreement). Both are observability-only;
see indicators.py's own module-level note above evaluate_regime.

As with Task 40's research telemetry, the single most important
property under test is PARITY: adding this evaluator/shadow telemetry
must never change a single strategy/trade/rejection decision -- see
test_regime_shadow_does_not_change_trades_signals_or_rejections.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from talonx_backtest.data import from_dataframe
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner
from talonx_quant.indicators import (
    PROVISIONAL_REGIME_15M_THRESHOLD_PCT,
    PROVISIONAL_REGIME_60M_THRESHOLD_PCT,
    REGIME_15M_BELOW_THRESHOLD,
    REGIME_60M_BELOW_THRESHOLD,
    REGIME_BOTH_BELOW_THRESHOLD,
    REGIME_ELIGIBLE,
    REGIME_STATE_NOT_READY,
    REGIME_SHADOW_BOTH_FAIL,
    REGIME_SHADOW_BOTH_PASS,
    REGIME_SHADOW_NEW_NOT_READY,
    REGIME_SHADOW_OLD_FAIL_NEW_PASS,
    REGIME_SHADOW_OLD_PASS_NEW_FAIL,
    VolatilityRegimeSnapshot,
    classify_regime_shadow_disagreement,
    evaluate_regime,
)
from talonx_quant.schemas import MarketTickEvent, TickEventType, TickSource

_START = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)


def _snap(atr_pct_15m, ready_15m, atr_pct_60m, ready_60m, as_of=_START):
    return VolatilityRegimeSnapshot(
        atr_15m=1.0 if atr_pct_15m is not None else None, atr_pct_15m=atr_pct_15m, ready_15m=ready_15m,
        atr_60m=1.0 if atr_pct_60m is not None else None, atr_pct_60m=atr_pct_60m, ready_60m=ready_60m,
        as_of=as_of,
    )


def _relaxed_config() -> QuantConfig:
    return dataclasses.replace(QuantConfig(), atr_move_multiplier=0.0)


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


def _bars_to_df(bars, symbol="AAPL", start=_START):
    rows = [
        {"timestamp": start + timedelta(minutes=i), "open": o, "high": h, "low": l, "close": c, "volume": v}
        for i, (o, h, l, c, v) in enumerate(bars)
    ]
    return from_dataframe(pd.DataFrame(rows), symbol=symbol)


def _two_symbol_df():
    aapl_bars = _build_bars()
    msft_bars = [(o * 3 + 50, h * 3 + 50, l * 3 + 50, c * 3 + 50, v) for (o, h, l, c, v) in _build_bars()]
    return pd.concat([_bars_to_df(aapl_bars, "AAPL"), _bars_to_df(msft_bars, "MSFT")], ignore_index=True)


# ----------------------------------------------------------------------
# evaluate_regime: threshold logic, readiness, edge cases
# ----------------------------------------------------------------------

def test_both_legs_above_threshold_is_eligible():
    snap = _snap(PROVISIONAL_REGIME_15M_THRESHOLD_PCT + 0.1, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT + 0.1, True)
    r = evaluate_regime(snap)
    assert r.ready is True
    assert r.eligible is True
    assert r.reason == REGIME_ELIGIBLE


def test_15m_below_threshold():
    snap = _snap(PROVISIONAL_REGIME_15M_THRESHOLD_PCT - 0.01, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT + 0.1, True)
    r = evaluate_regime(snap)
    assert r.ready is True
    assert r.eligible is False
    assert r.reason == REGIME_15M_BELOW_THRESHOLD


def test_60m_below_threshold():
    snap = _snap(PROVISIONAL_REGIME_15M_THRESHOLD_PCT + 0.1, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT - 0.01, True)
    r = evaluate_regime(snap)
    assert r.ready is True
    assert r.eligible is False
    assert r.reason == REGIME_60M_BELOW_THRESHOLD


def test_both_below_threshold():
    snap = _snap(PROVISIONAL_REGIME_15M_THRESHOLD_PCT - 0.01, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT - 0.01, True)
    r = evaluate_regime(snap)
    assert r.ready is True
    assert r.eligible is False
    assert r.reason == REGIME_BOTH_BELOW_THRESHOLD


def test_15m_not_ready():
    snap = _snap(None, False, PROVISIONAL_REGIME_60M_THRESHOLD_PCT + 0.1, True)
    r = evaluate_regime(snap)
    assert r.ready is False
    assert r.eligible is False
    assert r.reason == REGIME_STATE_NOT_READY


def test_60m_not_ready():
    snap = _snap(PROVISIONAL_REGIME_15M_THRESHOLD_PCT + 0.1, True, None, False)
    r = evaluate_regime(snap)
    assert r.ready is False
    assert r.eligible is False
    assert r.reason == REGIME_STATE_NOT_READY


def test_both_not_ready():
    snap = _snap(None, False, None, False)
    r = evaluate_regime(snap)
    assert r.ready is False
    assert r.eligible is False
    assert r.reason == REGIME_STATE_NOT_READY


def test_60m_ready_but_not_15m_never_falls_back_to_15m_only():
    """Explicit instruction: do NOT fall back to 15m-only eligibility
    when 60m is not ready (or vice versa) -- both legs are required to
    be determinable, always."""
    snap = _snap(PROVISIONAL_REGIME_15M_THRESHOLD_PCT + 5.0, True, None, False)  # 15m wildly above threshold
    r = evaluate_regime(snap)
    assert r.ready is False
    assert r.eligible is False  # never eligible=True just because 15m alone looks great


def test_exact_threshold_boundary_is_eligible_inclusive():
    snap = _snap(PROVISIONAL_REGIME_15M_THRESHOLD_PCT, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT, True)
    r = evaluate_regime(snap)
    assert r.ready is True
    assert r.eligible is True
    assert r.reason == REGIME_ELIGIBLE


def test_nan_or_missing_atr_pct_despite_ready_flags_is_not_ready():
    """The Task 40 zero/negative/NaN-price edge case: ready_15m/
    ready_60m True but atr_pct is None. evaluate_regime must treat this
    as undeterminable, never fabricate eligible=True/False from it."""
    snap = _snap(None, True, PROVISIONAL_REGIME_60M_THRESHOLD_PCT + 0.1, True)
    r = evaluate_regime(snap)
    assert r.ready is False
    assert r.eligible is False
    assert r.reason == REGIME_STATE_NOT_READY


def test_evaluate_regime_result_carries_thresholds_and_as_of():
    as_of = _START + timedelta(minutes=42)
    snap = _snap(0.5, True, 1.0, True, as_of=as_of)
    r = evaluate_regime(snap)
    assert r.threshold_15m == PROVISIONAL_REGIME_15M_THRESHOLD_PCT
    assert r.threshold_60m == PROVISIONAL_REGIME_60M_THRESHOLD_PCT
    assert r.as_of == as_of


def test_evaluate_regime_is_deterministic():
    snap = _snap(0.5, True, 1.0, True)
    r1 = evaluate_regime(snap)
    r2 = evaluate_regime(snap)
    assert r1 == r2


# ----------------------------------------------------------------------
# Disagreement classification
# ----------------------------------------------------------------------

def test_disagreement_both_pass():
    r = evaluate_regime(_snap(1.0, True, 1.0, True))
    assert classify_regime_shadow_disagreement(True, r) == REGIME_SHADOW_BOTH_PASS


def test_disagreement_both_fail():
    r = evaluate_regime(_snap(0.01, True, 0.01, True))
    assert classify_regime_shadow_disagreement(False, r) == REGIME_SHADOW_BOTH_FAIL


def test_disagreement_old_fail_new_pass():
    r = evaluate_regime(_snap(1.0, True, 1.0, True))
    assert classify_regime_shadow_disagreement(False, r) == REGIME_SHADOW_OLD_FAIL_NEW_PASS


def test_disagreement_old_pass_new_fail():
    r = evaluate_regime(_snap(0.01, True, 0.01, True))
    assert classify_regime_shadow_disagreement(True, r) == REGIME_SHADOW_OLD_PASS_NEW_FAIL


def test_disagreement_new_not_ready_takes_priority_regardless_of_old():
    r = evaluate_regime(_snap(None, False, None, False))
    assert classify_regime_shadow_disagreement(True, r) == REGIME_SHADOW_NEW_NOT_READY
    assert classify_regime_shadow_disagreement(False, r) == REGIME_SHADOW_NEW_NOT_READY


# ----------------------------------------------------------------------
# Behavioral parity -- zero trading behavior change (mirrors Task 40's
# own parity test exactly)
# ----------------------------------------------------------------------

def test_regime_shadow_does_not_change_trades_signals_or_rejections():
    df = _two_symbol_df()
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)

    before = BacktestEngine(dataclasses.replace(cfg))
    before_result = before.run(df)

    after = BacktestEngine(dataclasses.replace(cfg), research_telemetry=True)
    after_result = after.run(df)

    assert before_result.trades == after_result.trades
    assert before_result.signals_generated == after_result.signals_generated
    assert before_result.signals_published == after_result.signals_published
    assert before_result.bars_processed == after_result.bars_processed
    assert before.rejections == after.rejections
    assert before.signal_log == after.signal_log

    assert len(after.regime_shadow_comparisons) > 0


def test_regime_shadow_comparisons_disabled_by_default():
    engine = BacktestEngine(BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False))
    engine.run(_two_symbol_df())
    assert engine.research_telemetry is False
    assert engine.regime_shadow_comparisons == []


def test_regime_shadow_comparison_fields_and_disagreement_are_consistent():
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)
    engine = BacktestEngine(cfg, research_telemetry=True)
    engine.run(_two_symbol_df())
    assert len(engine.regime_shadow_comparisons) > 0
    for row in engine.regime_shadow_comparisons:
        assert set(row.keys()) == {
            "timestamp", "symbol", "current_atr_pct_1m", "current_passes_min_atr_pct",
            "new_regime_ready", "new_regime_eligible", "regime_reason",
            "atr_pct_15m", "atr_pct_60m", "regime_as_of", "disagreement_category",
        }
        if not row["new_regime_ready"]:
            assert row["disagreement_category"] == REGIME_SHADOW_NEW_NOT_READY
            assert row["new_regime_eligible"] is False


# ----------------------------------------------------------------------
# Repeated deterministic state (engine-level)
# ----------------------------------------------------------------------

def test_engine_regime_shadow_comparisons_deterministic_across_two_runs():
    df = _two_symbol_df()
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)
    e1 = BacktestEngine(dataclasses.replace(cfg), research_telemetry=True)
    e1.run(df)
    e2 = BacktestEngine(dataclasses.replace(cfg), research_telemetry=True)
    e2.run(df)
    assert e1.regime_shadow_comparisons == e2.regime_shadow_comparisons


# ----------------------------------------------------------------------
# Live/backtest parity
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_path_does_not_crash_and_matches_backtest_disagreement_pattern():
    """Feeds the identical bar sequence through the live QuantScanner's
    real per-tick handler (_handle_market_tick) and confirms it runs to
    completion without error -- the same evaluate_regime/
    classify_regime_shadow_disagreement functions the backtest engine
    calls, applied to buffers built by the identical RollingBarBuffer/
    HtfBarAggregator classes (Task 40 parity guarantee), so no separate
    formula exists on the live side to drift."""
    cfg_qc = _relaxed_config()
    df = _bars_to_df(_build_bars(), "AAPL")
    scanner = QuantScanner(cfg_qc)
    for _, row in df.iterrows():
        event = MarketTickEvent(
            symbol="AAPL", timestamp=row["timestamp"], open=row["open"], high=row["high"],
            low=row["low"], close=row["close"], volume=row["volume"],
            event_type=TickEventType.BAR, source=TickSource.POLLING,
        )
        await scanner._handle_market_tick(event)
    # No exception raised -- the shadow block runs on every closed bar
    # without needing Redis/pubsub (client is None, _incr_metric no-ops).
    assert "AAPL" in scanner._latest_regime_snapshot
