"""
tests/test_backtest_research_telemetry.py
----------------------------------------------
Task 10 -- opt-in, observational-only research telemetry
(BacktestEngine(research_telemetry=True)): raw per-bar volatility-gate
values (volatility_telemetry) and per-candidate-signal values
(candidate_telemetry).

The single most important property under test is PARITY (spec section
"IMPORTANT PRINCIPLE" of Task 10): enabling telemetry must never change a
single strategy/trade decision. Every other test here proves the
telemetry values themselves are correct/consistent with the existing,
already-tested gate decisions -- never a second implementation of any
gate logic.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from talonx_backtest.data import from_dataframe
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_quant.config import QuantConfig

_START = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)  # 10:00 ET, regular session


def _relaxed_config() -> QuantConfig:
    """Same relaxation as test_backtest_regression.py's fixture (only
    atr_move_multiplier/min_atr_pct loosened so RSI/MACD/MA crossovers
    can fire without needing to hand-calibrate exact warm-up values) --
    NOT relaxing min_atr_pct itself here, since the volatility-gate
    telemetry tests below need SOME bars to genuinely fail it.

    volume_surge_ratio_threshold also loosened (Task 49): this fixture's
    volume oscillates around a ~1.0x ratio and never clears the production
    default (2.0x), so after the No-Self-Credit confluence fix (a
    MACD-triggered candidate can no longer reach confluence_score_min via
    self-credit + one other leg -- it needs an independent RSI AND volume
    leg together) no candidate in this fixture could ever reach threshold.
    Lowering the volume bar to what this fixture actually produces restores
    a genuine qualifying candidate without fabricating one -- confluence
    LOGIC is unchanged, only this test's own threshold input."""
    return dataclasses.replace(QuantConfig(), atr_move_multiplier=0.0, volume_surge_ratio_threshold=0.9)


def _build_bars(n: int = 260, calm_tail: int = 30) -> list[tuple[float, float, float, float, float]]:
    """Busy section (mirrors test_backtest_regression.py's fixture shape
    -- enough oscillation/volume variation that RSI/MACD crossovers fire
    more than once) followed by a deliberately CALM tail: a tiny
    high-low range (0.1 vs. the busy section's 0.8) that pulls the
    rolling ATR14 down enough to genuinely drop atr_pct below the
    production min_atr_pct floor (0.25%) for at least some bars -- so
    volatility telemetry tests below exercise BOTH passes_volatility
    outcomes, not just one."""
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
    for i in range(calm_tail):
        price += 0.01 if i % 2 == 0 else -0.01
        bars.append((price, price + 0.05, price - 0.05, price, 800.0))
    return bars


def _bars_to_df(bars, symbol: str = "AAPL") -> pd.DataFrame:
    rows = [
        {"timestamp": _START + timedelta(minutes=i), "open": o, "high": h, "low": l, "close": c, "volume": v}
        for i, (o, h, l, c, v) in enumerate(bars)
    ]
    return from_dataframe(pd.DataFrame(rows), symbol=symbol)


def _two_symbol_df() -> pd.DataFrame:
    """AAPL and MSFT with deliberately different price levels/moves, so
    per-symbol/timestamp association can be checked (a wrong association
    would show up as one symbol's telemetry rows carrying the other
    symbol's price)."""
    aapl_bars = _build_bars()
    msft_bars = [(o * 3 + 50, h * 3 + 50, l * 3 + 50, c * 3 + 50, v) for (o, h, l, c, v) in _build_bars()]
    return pd.concat([_bars_to_df(aapl_bars, "AAPL"), _bars_to_df(msft_bars, "MSFT")], ignore_index=True)


# ----------------------------------------------------------------------
# Behavioral parity (Step 9 -- the most important test in this file)
# ----------------------------------------------------------------------

def test_research_telemetry_disabled_by_default():
    engine = BacktestEngine(BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False))
    result = engine.run(_two_symbol_df())

    assert engine.research_telemetry is False
    assert engine.volatility_telemetry == []
    assert engine.candidate_telemetry == []
    assert result.volatility_telemetry == []
    assert result.candidate_telemetry == []


def test_research_telemetry_enabled_does_not_change_trades_signals_or_rejections():
    df = _two_symbol_df()
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)

    plain = BacktestEngine(dataclasses.replace(cfg), research_telemetry=False)
    plain_result = plain.run(df)

    telemetry_on = BacktestEngine(dataclasses.replace(cfg), research_telemetry=True)
    telemetry_result = telemetry_on.run(df)

    assert plain_result.trades == telemetry_result.trades
    assert plain_result.signals_generated == telemetry_result.signals_generated
    assert plain_result.signals_published == telemetry_result.signals_published
    assert plain_result.bars_processed == telemetry_result.bars_processed
    assert plain.rejections == telemetry_on.rejections
    # The pre-existing signal_log (used by the regression/look-ahead
    # tests) must be byte-for-byte identical regardless of this flag --
    # candidate_telemetry is a deliberately separate list.
    assert plain.signal_log == telemetry_on.signal_log

    # And the flag actually did something -- otherwise this whole file
    # would be proving parity between two runs that trivially agree.
    assert len(telemetry_on.volatility_telemetry) > 0
    assert len(telemetry_on.candidate_telemetry) > 0


# ----------------------------------------------------------------------
# Volatility telemetry correctness (Step 10)
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def telemetry_result():
    df = _two_symbol_df()
    cfg = BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False)
    engine = BacktestEngine(cfg, research_telemetry=True)
    result = engine.run(df)
    return engine, result


def test_volatility_telemetry_atr_pct_matches_gate_formula(telemetry_result):
    engine, _ = telemetry_result
    assert engine.volatility_telemetry, "fixture produced no volatility telemetry -- strengthen it"
    for row in engine.volatility_telemetry:
        if row["atr"] is None or not row["price"]:
            assert row["atr_pct"] is None
            continue
        expected = (row["atr"] / row["price"]) * 100
        assert row["atr_pct"] == pytest.approx(expected, rel=1e-12)


def test_volatility_telemetry_passes_flag_matches_low_volatility_rejections(telemetry_result):
    """The exact same fails_volatility boolean drives both the telemetry
    row and the actual LOW_VOLATILITY reject-or-continue branch (engine.py
    computes it once and reuses it) -- so counting each independently
    from their own recorded outputs must agree."""
    engine, _ = telemetry_result
    failed_telemetry = sum(1 for row in engine.volatility_telemetry if not row["passes_volatility"])
    low_volatility_rejections = sum(r.count for r in engine.rejections if r.reason == "LOW_VOLATILITY")
    assert failed_telemetry == low_volatility_rejections
    assert failed_telemetry > 0, "fixture produced no LOW_VOLATILITY rejections -- strengthen it"

    passed_telemetry = sum(1 for row in engine.volatility_telemetry if row["passes_volatility"])
    assert passed_telemetry > 0, "fixture produced no volatility-gate passes -- strengthen it"
    assert passed_telemetry + failed_telemetry == len(engine.volatility_telemetry)


def test_volatility_telemetry_threshold_matches_config(telemetry_result):
    engine, _ = telemetry_result
    configured = engine.config.quant_config.min_atr_pct
    assert all(row["volatility_threshold"] == configured for row in engine.volatility_telemetry)


def test_volatility_telemetry_symbol_association_is_correct(telemetry_result):
    """MSFT's fixture prices are AAPL's * 3 + 50 (see _two_symbol_df) --
    a wrong symbol/timestamp association would show up as MSFT rows with
    AAPL-range prices or vice versa."""
    engine, _ = telemetry_result
    symbols = {row["symbol"] for row in engine.volatility_telemetry}
    assert symbols == {"AAPL", "MSFT"}

    aapl_prices = [row["price"] for row in engine.volatility_telemetry if row["symbol"] == "AAPL"]
    msft_prices = [row["price"] for row in engine.volatility_telemetry if row["symbol"] == "MSFT"]
    assert aapl_prices and msft_prices
    assert max(aapl_prices) < min(msft_prices), "AAPL/MSFT price ranges should not overlap given the fixture construction"


def test_volatility_telemetry_disabled_engine_has_no_rows_even_with_failures():
    """Confirms LOW_VOLATILITY rejections still occur without telemetry
    (so the parity test above isn't vacuous) while volatility_telemetry
    stays empty."""
    engine = BacktestEngine(BacktestConfig(quant_config=_relaxed_config(), eod_flatten_enabled=False))
    engine.run(_two_symbol_df())
    assert any(r.reason == "LOW_VOLATILITY" for r in engine.rejections)
    assert engine.volatility_telemetry == []


# ----------------------------------------------------------------------
# Candidate telemetry correctness (Step 11)
# ----------------------------------------------------------------------

def test_candidate_telemetry_has_exactly_one_row_per_raw_candidate(telemetry_result):
    """candidate_telemetry and signal_log are appended in the same `for
    s in signals` scope at the same call site -- their lengths must match
    exactly whenever telemetry is enabled."""
    engine, _ = telemetry_result
    assert len(engine.candidate_telemetry) == len(engine.signal_log)
    assert len(engine.candidate_telemetry) > 0


def test_candidate_telemetry_shared_fields_match_signal_log(telemetry_result):
    engine, _ = telemetry_result
    for cand, logged in zip(engine.candidate_telemetry, engine.signal_log):
        assert cand["timestamp"] == logged["timestamp"]
        assert cand["symbol"] == logged["ticker"]
        assert cand["direction"] == logged["direction"]
        assert cand["signal_type"] == logged["signal_type"]
        assert cand["price"] == logged["price"]
        assert cand["rsi"] == logged["rsi"]
        assert cand["confluence_score"] == logged["confluence_score"]
        assert cand["risk_reward_ratio"] == logged["risk_reward_ratio"]


def test_candidate_telemetry_represents_both_rejected_and_published_candidates(telemetry_result):
    engine, result = telemetry_result
    qc = engine.config.quant_config

    below_min_confluence = [row for row in engine.candidate_telemetry if (row["confluence_score"] or 0) < qc.confluence_score_min]
    at_or_above_min_confluence = [row for row in engine.candidate_telemetry if (row["confluence_score"] or 0) >= qc.confluence_score_min]
    assert below_min_confluence, "fixture produced no sub-threshold-confluence candidates -- strengthen it"
    assert at_or_above_min_confluence, "fixture produced no qualifying-confluence candidates -- strengthen it"

    # engine.py's LOW_CONFLUENCE gate (`qualifying = [s for s in signals if
    # score >= min]; if not qualifying: reject ALL len(signals) as
    # LOW_CONFLUENCE`) only records a rejection when NO candidate in that
    # bar's batch qualifies -- a sub-threshold candidate sharing a batch
    # with a qualifying sibling is silently excluded from `qualifying`
    # with no individual rejection logged (engine.py:614-617). This
    # fixture (Task 49: lowered volume_surge_ratio_threshold so a genuine
    # qualifying candidate exists at all, see _relaxed_config) now
    # produces exactly that mixed-batch case for the first time, so the
    # two counts are no longer expected to match exactly -- below_min_
    # confluence is an upper bound on low_confluence_rejections, not an
    # exact match.
    low_confluence_rejections = sum(r.count for r in engine.rejections if r.reason == "LOW_CONFLUENCE")
    assert low_confluence_rejections <= len(below_min_confluence)
    assert low_confluence_rejections > 0, "fixture produced no LOW_CONFLUENCE rejections -- strengthen it"


def test_candidate_telemetry_trend_component_is_bool_or_none(telemetry_result):
    """trend_aligned (captured as trend_component) is the one genuinely
    exposed per-signal gate boolean on QuantSignal -- None means "gate
    doesn't apply to this signal", never a fabricated pass/fail."""
    engine, _ = telemetry_result
    for row in engine.candidate_telemetry:
        assert row["trend_component"] is None or isinstance(row["trend_component"], bool)


def test_candidate_telemetry_raw_component_values_are_untransformed(telemetry_result):
    """macd/macd_signal_line/volume_surge_ratio are captured as the RAW
    QuantSignal values, not booleans -- no component pass/fail
    reconstruction happens here (see Task 10's own INSUFFICIENT
    TELEMETRY note for why)."""
    engine, _ = telemetry_result
    numeric_or_none = (int, float, type(None))
    for row in engine.candidate_telemetry:
        assert isinstance(row["macd"], numeric_or_none)
        assert isinstance(row["macd_signal_line"], numeric_or_none)
        assert isinstance(row["volume_surge_ratio"], numeric_or_none)
        assert not isinstance(row["macd"], bool)  # bool is an int subclass -- guard against accidental coercion
