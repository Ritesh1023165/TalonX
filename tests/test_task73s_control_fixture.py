"""Task 73S Stage 3 -- control-fixture proof that the production replay/
decision path can reach signal publication -> simulated order -> simulated
fill -> simulated exit -> trade ledger for an eligible setup, and correctly
excludes a rejected or readiness-blocked (insufficient-warmup) one.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Every trade/candidate produced or
referenced here is either a repaired example fixture (Stage 1) or a
minimal synthetic DataFrame -- none of it is real market data and none of
it is counted anywhere as profitability evidence (see
results/task73s_regression_and_zero_trade_diagnosis/stage3_control_fixture_evidence.json).
All broker interaction is talonx_backtest's own offline TradeSimulator --
no real or PAPER broker is reachable from any code path here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from zoneinfo import ZoneInfo

from talonx_backtest import cli
from talonx_quant.config import QuantConfig
from talonx_quant.indicators import compute_indicators

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TRADE_CSV = _REPO_ROOT / "examples" / "data" / "sample_AAPL_trade_1m.csv"
ET = ZoneInfo("America/New_York")


def test_case_1_eligible_setup_reaches_signal_to_ledger(tmp_path):
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Injection point: Stage 1's
    repaired sample_AAPL_trade_1m.csv (constructed OHLCV price/volume data,
    not a synthetic QuantSignal object) -- proves harness reachability,
    not that QuantScanner naturally generates this setup from real data."""
    exit_code = cli.main(["--data", str(_TRADE_CSV), "--symbol", "AAPL", "--tz", "America/New_York", "--out", str(tmp_path)])
    assert exit_code == 0

    summary = json.loads((tmp_path / "backtest_summary.json").read_text(encoding="utf-8"))
    assert summary["signals_published"] == 1
    assert summary["trades_executed"] == 1

    trades = json.loads((tmp_path / "backtest_trades.json").read_text(encoding="utf-8"))
    assert len(trades) == 1
    trade = trades[0]
    config = QuantConfig()
    assert trade["confluence_score"] >= config.confluence_score_min  # cleared, not weakened
    assert trade["direction"] == "bullish"
    assert trade["exit_reason"] in ("TARGET", "STOP", "END_OF_SESSION", "DATA_END")  # a real exit, not a crash artifact


def test_case_2_rejected_setup_never_reaches_the_ledger(tmp_path):
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. The same repaired fixture
    also contains a pre-existing BEARISH macd_bearish_cross candidate
    (confluence_score=1, below threshold) -- proves a rejected candidate
    is excluded from every downstream stage, not silently leaked through."""
    exit_code = cli.main(["--data", str(_TRADE_CSV), "--symbol", "AAPL", "--tz", "America/New_York", "--out", str(tmp_path)])
    assert exit_code == 0

    rejected_text = (tmp_path / "backtest_rejected_signals.csv").read_text(encoding="utf-8")
    assert "LOW_CONFLUENCE" in rejected_text

    trades = json.loads((tmp_path / "backtest_trades.json").read_text(encoding="utf-8"))
    assert not any(t["direction"] == "bearish" for t in trades)  # the rejected bearish candidate produced no trade


def test_case_3_readiness_blocked_setup_generates_zero_candidates():
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. A minimal 5-bar synthetic
    DataFrame -- far short of the ~14-26 bars RSI/MACD/ATR need -- fed
    through the UNMODIFIED compute_indicators. Proves the harness fails
    closed on insufficient data (never fabricates a reading) exactly as
    talonx_backtest/engine.py's own `if snapshot is None: return` warm-up
    guard requires."""
    config = QuantConfig()
    rows = []
    ts = pd.Timestamp("2026-03-02 09:30:00", tz=ET)
    price = 100.0
    for _ in range(5):
        rows.append([ts, price, price + 0.05, price - 0.05, price, 1000.0])
        ts = ts + pd.Timedelta(minutes=1)
        price += 0.01
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"]).set_index("timestamp")

    snapshot = compute_indicators(df, config)
    assert snapshot is None  # insufficient warmup -- no fabricated indicator reading
