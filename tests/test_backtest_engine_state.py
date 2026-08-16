"""
tests/test_backtest_engine_state.py
----------------------------------------
Focused, white-box tests of BacktestEngine's cooldown/loss-lockout/
throttle/EOD-flatten state machinery (spec sections 15-16, 14) --
hand-built QuantSignal candidates are used directly (same convention
test_quant_strategy.py uses for IndicatorSnapshot) so these tests
exercise the state logic itself without needing to calibrate raw OHLCV
data to hit exact RSI/pivot thresholds -- that indicator-level fidelity
is already covered by test_backtest_regression.py and
test_quant_strategy.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import pandas as pd

from talonx_backtest.data import from_dataframe
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_backtest.portfolio import Trade
from talonx_quant.config import QuantConfig
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType

_NOW = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)


def _signal(
    ticker: str, confluence: int, rr: float, volume_surge: float, trend_aligned: bool | None,
    price: float = 100.0, atr: float = 1.0,
) -> QuantSignal:
    return QuantSignal(
        ticker=ticker, signal_type=SignalType.MACD_BULLISH_CROSS, direction=SignalDirection.BULLISH,
        message="test", price=price, atr=atr, confluence_score=confluence, risk_reward_ratio=rr,
        volume_surge_ratio=volume_surge, trend_aligned=trend_aligned,
        stop_price=price - 1.5 * atr, target_price=price + 10.0,
        pivot_resistance=price + 10.0, pivot_support=price - 10.0,
        session="regular", bar_timestamp=_NOW, signal_generated_at=_NOW,
    )


@pytest.fixture
def engine() -> BacktestEngine:
    return BacktestEngine(BacktestConfig(quant_config=QuantConfig(), eod_flatten_enabled=False))


# --- Cooldown (spec section 15) ---

def test_cooldown_blocks_the_same_ticker_until_it_expires(engine):
    assert not engine._is_on_cooldown("AAPL", _NOW)
    engine._arm_cooldown("AAPL", _NOW)
    assert engine._is_on_cooldown("AAPL", _NOW)

    almost_expired = _NOW + timedelta(seconds=engine.config.quant_config.cooldown_seconds - 1)
    assert engine._is_on_cooldown("AAPL", almost_expired)

    just_expired = _NOW + timedelta(seconds=engine.config.quant_config.cooldown_seconds)
    assert not engine._is_on_cooldown("AAPL", just_expired)


def test_cooldown_is_per_ticker(engine):
    engine._arm_cooldown("AAPL", _NOW)
    assert engine._is_on_cooldown("AAPL", _NOW)
    assert not engine._is_on_cooldown("MSFT", _NOW)


# --- Loss lockout (spec section 15, mirrors talonx_quant's post-loss lockout) ---

def test_loss_lockout_arms_only_on_a_losing_net_pnl(engine):
    losing_trade = Trade(
        trade_id="t", symbol="AAPL", direction="bullish", signal_type=None, session="regular",
        signal_timestamp=_NOW, entry_timestamp=_NOW, entry_price=100.0, stop_price=95.0, target_price=110.0,
        atr=1.0, risk_reward_ratio=2.0, screening_rr=2.0, execution_rr=2.0, confluence_score=2, opportunity_score=0.5, volume_surge_ratio=2.0,
        trend_alignment=True, exit_timestamp=_NOW, exit_price=95.0, exit_reason="STOP",
        gross_R=-1.0, net_R=-1.05, gross_pnl=-5.0, net_pnl=-5.5, holding_seconds=60.0,
        mfe_price=None, mfe_pct=None, mfe_r=0.1, mae_price=None, mae_pct=None, mae_r=-1.0,
    )
    engine._maybe_arm_loss_lockout("AAPL", losing_trade, _NOW)
    assert engine._is_loss_locked_out("AAPL", _NOW)


def test_loss_lockout_does_not_arm_on_a_winning_trade(engine):
    winning_trade = Trade(
        trade_id="t", symbol="AAPL", direction="bullish", signal_type=None, session="regular",
        signal_timestamp=_NOW, entry_timestamp=_NOW, entry_price=100.0, stop_price=95.0, target_price=110.0,
        atr=1.0, risk_reward_ratio=2.0, screening_rr=2.0, execution_rr=2.0, confluence_score=2, opportunity_score=0.5, volume_surge_ratio=2.0,
        trend_alignment=True, exit_timestamp=_NOW, exit_price=110.0, exit_reason="TARGET",
        gross_R=2.0, net_R=1.9, gross_pnl=10.0, net_pnl=9.5, holding_seconds=60.0,
        mfe_price=None, mfe_pct=None, mfe_r=2.0, mae_price=None, mae_pct=None, mae_r=-0.1,
    )
    engine._maybe_arm_loss_lockout("AAPL", winning_trade, _NOW)
    assert not engine._is_loss_locked_out("AAPL", _NOW)


# --- Throttle (spec section 16) ---

def test_throttle_publishes_only_the_top_ranked_candidates(engine):
    qc = engine.config.quant_config
    assert qc.throttle_max_signals == 3  # production default this test relies on

    candidates = [
        _signal("AAAA", confluence=3, rr=5.0, volume_surge=10.0, trend_aligned=True),   # highest score
        _signal("BBBB", confluence=3, rr=4.0, volume_surge=8.0, trend_aligned=True),
        _signal("CCCC", confluence=2, rr=3.0, volume_surge=6.0, trend_aligned=True),
        _signal("DDDD", confluence=2, rr=2.0, volume_surge=4.0, trend_aligned=None),
        _signal("EEEE", confluence=1, rr=1.5, volume_surge=2.0, trend_aligned=False),   # lowest score
    ]
    for s in candidates:
        engine._last_close[s.ticker] = s.price

    engine._flush_throttle(candidates, _NOW)

    assert engine.signals_published == 3
    published_tickers = set(engine._pending_entry.keys())
    assert published_tickers == {"AAAA", "BBBB", "CCCC"}

    throttle_rejections = [r for r in engine.rejections if r.reason == "THROTTLE"]
    assert {r.ticker for r in throttle_rejections} == {"DDDD", "EEEE"}


def test_opportunity_score_matches_the_production_formula_fed_by_screening_rr(engine):
    """R:R contributes opportunity_score_rr_weight (30% by default) to
    the Composite Opportunity Score. Confirms engine._flush_throttle
    computes that score via the SAME talonx_quant.consumer._opportunity_score
    production function the live system uses, fed by the candidate's own
    risk_reward_ratio (== screening_rr) -- not anything derived from a
    later fill price (execution_rr can't even exist yet here; entry
    hasn't happened). See test_backtest_execution.py's
    test_opportunity_score_is_unaffected_by_execution_rr_divergence for
    the other end of this chain (the score surviving unchanged once a
    real, possibly-divergent fill price is known)."""
    from talonx_quant.consumer import _opportunity_score

    qc = engine.config.quant_config
    signal = _signal("AAAA", confluence=3, rr=4.2, volume_surge=6.0, trend_aligned=True)
    engine._last_close["AAAA"] = signal.price

    expected_score = _opportunity_score(signal, qc)
    engine._flush_throttle([signal], _NOW)

    assert engine._pending_entry["AAAA"].opportunity_score == pytest.approx(expected_score)

    # sanity: the score is actually sensitive to risk_reward_ratio, not a
    # constant -- a lower screening_rr (all else equal) scores lower.
    lower_rr_signal = _signal("BBBB", confluence=3, rr=1.5, volume_surge=6.0, trend_aligned=True)
    engine._last_close["BBBB"] = lower_rr_signal.price
    assert _opportunity_score(lower_rr_signal, qc) < expected_score


def test_throttle_publish_arms_cooldown_for_released_tickers(engine):
    candidates = [_signal("AAAA", confluence=3, rr=5.0, volume_surge=10.0, trend_aligned=True)]
    engine._last_close["AAAA"] = 100.0
    engine._flush_throttle(candidates, _NOW)
    assert engine._is_on_cooldown("AAAA", _NOW)


def test_throttle_revalidation_drops_a_candidate_missing_fresh_price_data(engine):
    candidates = [_signal("ZZZZ", confluence=3, rr=5.0, volume_surge=10.0, trend_aligned=True)]
    # deliberately do NOT populate engine._last_close["ZZZZ"]
    engine._flush_throttle(candidates, _NOW)

    assert engine.signals_published == 0
    assert any(r.ticker == "ZZZZ" and r.reason == "FINAL_REVALIDATION_DATA_UNAVAILABLE" for r in engine.rejections)


def test_throttle_intra_flush_cooldown_recheck_drops_a_second_candidate_for_the_same_ticker(engine):
    """strategy.py can legitimately emit multiple independent candidates
    for the same ticker off one closed bar -- the second must not also
    publish once the first has armed cooldown within this same flush."""
    candidates = [
        _signal("AAAA", confluence=3, rr=5.0, volume_surge=10.0, trend_aligned=True),
        _signal("AAAA", confluence=2, rr=3.0, volume_surge=6.0, trend_aligned=True),
    ]
    engine._last_close["AAAA"] = 100.0
    engine._flush_throttle(candidates, _NOW)

    assert engine.signals_published == 1
    assert any(r.ticker == "AAAA" and r.reason == "COOLDOWN" for r in engine.rejections)


# --- EOD flatten (spec section 14, mirrors talonx_paper's 15:50 ET sweep) ---

def test_eod_flatten_closes_open_positions_at_the_configured_et_time():
    engine = BacktestEngine(BacktestConfig(quant_config=QuantConfig(), eod_flatten_enabled=True))
    signal = _signal("AAAA", confluence=3, rr=5.0, volume_surge=10.0, trend_aligned=True)
    entry_time = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
    engine.simulator.open_position(signal, entry_timestamp=entry_time, entry_price_raw=100.0)
    engine._last_close["AAAA"] = 103.0

    before_flatten = datetime(2026, 1, 5, 20, 49, tzinfo=timezone.utc)  # 15:49 ET
    engine._maybe_eod_flatten(before_flatten)
    assert engine.simulator.has_open("AAAA")

    at_flatten = datetime(2026, 1, 5, 20, 50, tzinfo=timezone.utc)  # 15:50 ET
    engine._maybe_eod_flatten(at_flatten)
    assert not engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1
    assert engine.trades[0].exit_reason == "END_OF_SESSION"
    assert engine.trades[0].exit_price == 103.0


def test_eod_flatten_only_fires_once_per_day():
    engine = BacktestEngine(BacktestConfig(quant_config=QuantConfig(), eod_flatten_enabled=True))
    signal = _signal("AAAA", confluence=3, rr=5.0, volume_surge=10.0, trend_aligned=True)
    engine.simulator.open_position(signal, entry_timestamp=_NOW, entry_price_raw=100.0)
    engine._last_close["AAAA"] = 100.0

    at_flatten = datetime(2026, 1, 5, 20, 50, tzinfo=timezone.utc)
    engine._maybe_eod_flatten(at_flatten)
    assert len(engine.trades) == 1

    # a second signal opens AFTER the flatten, same day -- must NOT be
    # immediately swept by a duplicate same-day flatten call
    signal2 = _signal("AAAA", confluence=3, rr=5.0, volume_surge=10.0, trend_aligned=True)
    engine.simulator.open_position(signal2, entry_timestamp=at_flatten, entry_price_raw=101.0)
    engine._maybe_eod_flatten(at_flatten + timedelta(minutes=1))
    assert engine.simulator.has_open("AAAA")
    assert len(engine.trades) == 1


# --- progress reporting (BacktestEngine.run's progress_callback) ---

def _flat_bars_df(n=60, symbol="AAAA"):
    ts = pd.date_range("2026-01-05 14:30:00", periods=n, freq="1min", tz="UTC")
    rows = [
        {"timestamp": t, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0}
        for t in ts
    ]
    return from_dataframe(pd.DataFrame(rows), symbol=symbol)


def test_run_without_a_progress_callback_is_unaffected():
    engine = BacktestEngine(BacktestConfig(quant_config=QuantConfig(), eod_flatten_enabled=False))
    result = engine.run(_flat_bars_df())
    assert result.symbols == ["AAAA"]


def test_progress_callback_is_always_called_once_at_completion():
    # progress_interval_seconds is huge -- the wall-clock throttle never
    # elapses during this fast test run -- so the ONLY call should be the
    # unconditional final one, with bars_done == bars_total.
    df = _flat_bars_df(n=60)
    calls = []
    engine = BacktestEngine(BacktestConfig(quant_config=QuantConfig(), eod_flatten_enabled=False))
    engine.run(df, progress_callback=lambda done, total: calls.append((done, total)), progress_interval_seconds=9999.0)

    assert len(calls) == 1
    done, total = calls[0]
    assert done == total == 60


def test_progress_callback_reports_increasing_bars_done_when_unthrottled():
    df = _flat_bars_df(n=60)
    calls = []
    engine = BacktestEngine(BacktestConfig(quant_config=QuantConfig(), eod_flatten_enabled=False))
    engine.run(df, progress_callback=lambda done, total: calls.append((done, total)), progress_interval_seconds=0.0)

    assert len(calls) >= 2
    bars_done_seq = [done for done, _ in calls]
    assert bars_done_seq == sorted(bars_done_seq)
    assert all(total == 60 for _, total in calls)
    assert calls[-1] == (60, 60)


def test_progress_callback_reflects_multiple_symbols_in_bars_total():
    # bars_total counts rows, not distinct timestamps -- two symbols over
    # the same 30 timestamps is 60 bars, not 30.
    df = pd.concat([_flat_bars_df(n=30, symbol="AAAA"), _flat_bars_df(n=30, symbol="BBBB")], ignore_index=True)
    calls = []
    engine = BacktestEngine(BacktestConfig(quant_config=QuantConfig(), eod_flatten_enabled=False))
    engine.run(df, progress_callback=lambda done, total: calls.append((done, total)), progress_interval_seconds=9999.0)

    assert calls == [(60, 60)]
