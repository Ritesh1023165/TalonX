"""
tests/test_60m_bootstrap.py
--------------------------------
Task 44 -- 60m shadow-regime historical warmup bootstrap
(QuantScanner._bootstrap_60m_if_needed / _feed_60m_bar / the
_update_regime_buffer_60m causality/dedup guard). Live-only (consumer.py);
talonx_backtest.engine is untouched by this task (a backtest always
starts from a complete dataset, so there is no "before start" history to
bootstrap from).

As with every prior regime-state task, the most important property is
PARITY: bootstrap may change ONLY regime readiness/ATR/shadow telemetry
-- never candidate generation, rejections, published signals, or trades.
"""
from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pandas as pd
import pandas_ta  # noqa: F401 -- registers the df.ta accessor compute_volatility_regime relies on (same side-effect import compute_indicators does internally); needed here since this file calls compute_volatility_regime directly, without going through compute_indicators first
import pytest

from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner, _fails_min_volatility
from talonx_quant.indicators import compute_indicators, compute_volatility_regime, evaluate_regime
from talonx_quant.schemas import MarketTickEvent, TickEventType, TickSource

_START = datetime(2026, 1, 5, 4, 0, tzinfo=timezone.utc)


def _relaxed_config() -> QuantConfig:
    return dataclasses.replace(QuantConfig(), atr_move_multiplier=0.0)


def _synthetic_1m_bars(n: int, start: datetime = _START, start_price: float = 100.0) -> list[dict]:
    """Continuous 1-minute bars shaped like preseed.fetch_1m_history's
    own output (dict per bar, oldest first, session-tagged)."""
    from talonx_quant.session import get_session
    price = start_price
    bars = []
    for i in range(n):
        price += 0.3 if i % 2 == 0 else -0.2
        ts = start + timedelta(minutes=i)
        bars.append({
            "timestamp": ts, "open": price, "high": price + 0.5, "low": price - 0.5,
            "close": price, "volume": 1000.0, "session": get_session(ts),
        })
    return bars


def _event_from_bar(symbol: str, bar: dict) -> MarketTickEvent:
    return MarketTickEvent(
        symbol=symbol, timestamp=bar["timestamp"], open=bar["open"], high=bar["high"],
        low=bar["low"], close=bar["close"], volume=bar["volume"],
        event_type=TickEventType.BAR, source=TickSource.POLLING,
    )


def _run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------------
# Enough / insufficient history
# ----------------------------------------------------------------------

def test_enough_history_becomes_ready():
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    bars = _synthetic_1m_bars(1020)  # 17h continuous -> >14 FINALIZED 60-min buckets (the trailing partial bucket never finalizes without one more bar past it)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=bars):
        _run(scanner._bootstrap_60m_if_needed("AAPL"))
    assert scanner.buffer_60m.bar_count("AAPL") > qc.atr_period
    df_60m = scanner.buffer_60m.get_dataframe("AAPL")
    atr, atr_pct, ready = _regime_leg_atr_via_compute(df_60m, qc)
    assert ready is True


def _regime_leg_atr_via_compute(df_60m, qc):
    snap = compute_volatility_regime(None, df_60m, qc.atr_period, df_60m.index[-1])
    return snap.atr_60m, snap.atr_pct_60m, snap.ready_60m


def test_insufficient_history_stays_not_ready():
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    bars = _synthetic_1m_bars(30)  # 30 min -> 0 complete 60-min buckets
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=bars):
        _run(scanner._bootstrap_60m_if_needed("AAPL"))
    df_60m = scanner.buffer_60m.get_dataframe("AAPL")
    snap = compute_volatility_regime(None, df_60m, qc.atr_period, _START)
    assert snap.ready_60m is False
    result = evaluate_regime(snap)
    assert result.ready is False
    assert result.eligible is False
    assert result.reason == "REGIME_STATE_NOT_READY"


def test_no_data_returned_falls_back_to_not_ready_never_crashes():
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=[]):
        _run(scanner._bootstrap_60m_if_needed("AAPL"))
    assert scanner.buffer_60m.bar_count("AAPL") == 0
    assert "AAPL" not in scanner._bootstrap_60m_cutoff


def test_fetch_exception_fails_soft():
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", side_effect=RuntimeError("network down")):
        _run(scanner._bootstrap_60m_if_needed("AAPL"))  # must not raise
    assert scanner.buffer_60m.bar_count("AAPL") == 0


# ----------------------------------------------------------------------
# Causality / duplicate protection
# ----------------------------------------------------------------------

def test_bootstrap_sets_dedup_cutoff_at_last_bar_minute():
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    bars = _synthetic_1m_bars(1020)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=bars):
        _run(scanner._bootstrap_60m_if_needed("AAPL"))
    expected_cutoff = bars[-1]["timestamp"].replace(second=0, microsecond=0)
    assert scanner._bootstrap_60m_cutoff["AAPL"] == expected_cutoff


def test_live_tick_at_or_before_cutoff_is_skipped_no_double_count():
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    bars = _synthetic_1m_bars(1020)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=bars):
        _run(scanner._bootstrap_60m_if_needed("AAPL"))
    bar_count_after_bootstrap = scanner.buffer_60m.bar_count("AAPL")
    df_before = scanner.buffer_60m.get_dataframe("AAPL")

    # Re-deliver the LAST bootstrapped bar as a "live" tick -- must be a no-op.
    dup_event = _event_from_bar("AAPL", bars[-1])
    scanner._update_regime_buffer_60m(dup_event)
    assert scanner.buffer_60m.bar_count("AAPL") == bar_count_after_bootstrap
    df_after = scanner.buffer_60m.get_dataframe("AAPL")
    pd.testing.assert_frame_equal(df_before, df_after)  # byte-identical, no volume double-count


def test_live_tick_after_cutoff_is_processed_normally():
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    bars = _synthetic_1m_bars(1020)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=bars):
        _run(scanner._bootstrap_60m_if_needed("AAPL"))

    # A genuinely new, later bar -- 61 minutes after the last bootstrap
    # bar closes out a new 60-minute bucket and should finalize.
    next_bar = {
        "timestamp": bars[-1]["timestamp"] + timedelta(minutes=61),
        "open": 150.0, "high": 150.5, "low": 149.5, "close": 150.0, "volume": 2000.0,
    }
    finalized_before = scanner.buffer_60m.bar_count("AAPL")
    scanner._update_regime_buffer_60m(_event_from_bar("AAPL", next_bar))
    # A single tick 61 minutes later finalizes exactly one new bucket.
    assert scanner.buffer_60m.bar_count("AAPL") == finalized_before + 1


# ----------------------------------------------------------------------
# Cold start / warm restart / checkpoint+bootstrap overlap
# ----------------------------------------------------------------------

def test_cold_start_buffer_empty_before_bootstrap():
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    assert scanner.buffer_60m.bar_count("AAPL") == 0


def test_warm_restart_with_sufficient_checkpoint_skips_network_fetch():
    """Restart-priority rule: a valid persisted checkpoint (simulated
    here by pre-populating buffer_60m directly, as _load_buffers_from_store
    would) must be preferred -- bootstrap must not re-fetch."""
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    bars = _synthetic_1m_bars(1020)
    for bar in bars:
        scanner._feed_60m_bar("AAPL", bar["timestamp"], bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"])
    assert scanner.buffer_60m.bar_count("AAPL") > qc.atr_period

    with patch("talonx_quant.consumer.preseed.fetch_1m_history") as mock_fetch:
        _run(scanner._bootstrap_60m_if_needed("AAPL"))
        mock_fetch.assert_not_called()


def test_checkpoint_bootstrap_overlap_is_idempotent_via_upsert():
    """Partial checkpoint (not enough for readiness) + overlapping
    bootstrap fetch must merge safely (upsert-by-timestamp), never
    double-seed / corrupt volume."""
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    bars = _synthetic_1m_bars(1020)
    # Simulate a THIN partial checkpoint: only 5 bars pre-loaded (not enough for readiness).
    for bar in bars[:5]:
        scanner._feed_60m_bar("AAPL", bar["timestamp"], bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"])
    assert scanner.buffer_60m.bar_count("AAPL") <= qc.atr_period

    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=bars):
        _run(scanner._bootstrap_60m_if_needed("AAPL"))

    # Compare against a clean bootstrap-only run for the same bars.
    scanner2 = QuantScanner(qc)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=bars):
        _run(scanner2._bootstrap_60m_if_needed("AAPL"))
    pd.testing.assert_frame_equal(scanner.buffer_60m.get_dataframe("AAPL"), scanner2.buffer_60m.get_dataframe("AAPL"))


# ----------------------------------------------------------------------
# Invalid / out-of-order history
# ----------------------------------------------------------------------

def test_out_of_order_history_is_sorted_before_feeding_and_still_deterministic():
    qc = _relaxed_config()
    bars = _synthetic_1m_bars(1020)
    shuffled = list(reversed(bars))  # deliberately out of order

    scanner_sorted = QuantScanner(qc)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=bars):
        _run(scanner_sorted._bootstrap_60m_if_needed("AAPL"))

    scanner_shuffled = QuantScanner(qc)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=shuffled):
        _run(scanner_shuffled._bootstrap_60m_if_needed("AAPL"))

    pd.testing.assert_frame_equal(
        scanner_sorted.buffer_60m.get_dataframe("AAPL"), scanner_shuffled.buffer_60m.get_dataframe("AAPL"),
    )
    assert scanner_sorted._bootstrap_60m_cutoff["AAPL"] == scanner_shuffled._bootstrap_60m_cutoff["AAPL"]


# ----------------------------------------------------------------------
# Continuous vs. split replay parity (the central proof)
# ----------------------------------------------------------------------

def test_continuous_vs_bootstrap_plus_live_split_produces_identical_regime_state():
    """Path A: feed ALL bars as 'live' ticks continuously (no bootstrap).
    Path B: feed the historical PREFIX via bootstrap (mocked fetch), then
    the remaining SUFFIX as live ticks. At the matching final timestamp,
    the two paths must produce byte-identical 60m state and identical
    evaluate_regime results."""
    qc = _relaxed_config()
    all_bars = _synthetic_1m_bars(1020)
    split_at = 600
    prefix, suffix = all_bars[:split_at], all_bars[split_at:]

    # Path A: continuous live feed, no bootstrap.
    scanner_a = QuantScanner(qc)
    for bar in all_bars:
        scanner_a._update_regime_buffer_60m(_event_from_bar("AAPL", bar))

    # Path B: bootstrap the prefix, then feed the suffix as live.
    scanner_b = QuantScanner(qc)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=prefix):
        _run(scanner_b._bootstrap_60m_if_needed("AAPL"))
    for bar in suffix:
        scanner_b._update_regime_buffer_60m(_event_from_bar("AAPL", bar))

    df_a = scanner_a.buffer_60m.get_dataframe("AAPL")
    df_b = scanner_b.buffer_60m.get_dataframe("AAPL")
    pd.testing.assert_frame_equal(df_a, df_b)

    as_of = all_bars[-1]["timestamp"]
    snap_a = compute_volatility_regime(None, df_a, qc.atr_period, as_of)
    snap_b = compute_volatility_regime(None, df_b, qc.atr_period, as_of)
    assert snap_a == snap_b
    assert evaluate_regime(snap_a) == evaluate_regime(snap_b)


# ----------------------------------------------------------------------
# Zero strategy behavior change
# ----------------------------------------------------------------------

def test_bootstrap_does_not_change_the_existing_min_atr_pct_gate_decision():
    """Confirms _fails_min_volatility (the ONLY active gate) produces the
    identical decision whether or not the 60m bootstrap ran -- it reads
    only the primary 1-minute IndicatorSnapshot, never buffer_60m."""
    qc = _relaxed_config()
    all_bars = _synthetic_1m_bars(200)

    scanner_no_bootstrap = QuantScanner(qc)
    scanner_with_bootstrap = QuantScanner(qc)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=_synthetic_1m_bars(1020)):
        _run(scanner_with_bootstrap._bootstrap_60m_if_needed("AAPL"))

    for bar in all_bars:
        for sc in (scanner_no_bootstrap, scanner_with_bootstrap):
            sc.buffer.add_bar(
                symbol="AAPL", timestamp=bar["timestamp"], open_=bar["open"], high=bar["high"],
                low=bar["low"], close=bar["close"], volume=bar["volume"], session=bar["session"],
            )

    df_1m_a = scanner_no_bootstrap.buffer.get_dataframe("AAPL")
    df_1m_b = scanner_with_bootstrap.buffer.get_dataframe("AAPL")
    pd.testing.assert_frame_equal(df_1m_a, df_1m_b)  # 1m buffer itself is untouched by 60m bootstrap

    snap_a = compute_indicators(df_1m_a, qc)
    snap_b = compute_indicators(df_1m_b, qc)
    assert snap_a == snap_b
    assert _fails_min_volatility(snap_a, qc) == _fails_min_volatility(snap_b, qc)


@pytest.mark.asyncio
async def test_preseed_symbols_wires_bootstrap_without_crashing():
    qc = _relaxed_config()
    scanner = QuantScanner(qc)
    with patch("talonx_quant.consumer.preseed.fetch_1m_history", return_value=[]), \
         patch.object(scanner, "_run_1m_preseed", AsyncMock()), \
         patch.object(scanner, "_preseed_1m_if_needed", AsyncMock()), \
         patch.object(scanner, "_preseed_htf_if_needed", AsyncMock()):
        await scanner.preseed_symbols(["AAPL"])
    assert "AAPL" in scanner._bootstrapped_60m
