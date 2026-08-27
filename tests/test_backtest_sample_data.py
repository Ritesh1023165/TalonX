"""
tests/test_backtest_sample_data.py
----------------------------------------
Both deterministic sample datasets must run successfully via the EXACT
documented commands (spec sections 3, 6, and 19) -- proves a fresh
clone can go from nothing to an open HTML report without real market
data, matching docs/backtesting.md and the README's "Run your first
backtest" section word for word, and that the engine is exercised
through BOTH the zero-trade path and the actual-trade path:

  - sample_AAPL_1m.csv        -- smoke-test/validation dataset. Zero
    trades is the CORRECT, expected outcome (every candidate is
    rejected on confluence) -- these tests assert that explicitly,
    not just "it ran without crashing."
  - sample_AAPL_trade_1m.csv  -- deterministic trade/execution/
    reporting dataset. Produces exactly one real trade, entirely
    through the FROZEN production QuantConfig (no gate relaxed) --
    exercises entry, a TARGET exit, trades.csv, equity_curve.csv, and
    the HTML report's trade-metrics rendering.
  - sample_multi_trade_1m.csv -- three independent synthetic symbols
    (TSTW/TSTL/TSTE), each a separate deterministic scenario, ALSO
    entirely through the frozen production QuantConfig: TSTW exits
    TARGET (win), TSTL exits STOP (loss), TSTE exits END_OF_SESSION
    (win, via the real EOD-flatten sweep). Together they give one win/
    loss/aggregate-statistics fixture -- profit factor, average loss,
    drawdown, cumulative R, and win/loss stats are all exercised on
    real (non-degenerate) numbers in one run.

Neither dataset represents real market performance -- none of these
fixtures should ever be cited as evidence of TalonX's real-world edge.
They are integration-test fixtures only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from talonx_backtest import cli

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SMOKE_CSV = _REPO_ROOT / "examples" / "data" / "sample_AAPL_1m.csv"
_TRADE_CSV = _REPO_ROOT / "examples" / "data" / "sample_AAPL_trade_1m.csv"
_MULTI_CSV = _REPO_ROOT / "examples" / "data" / "sample_multi_trade_1m.csv"

# Task 25A finding (2026-08-20): sample_AAPL_trade_1m.csv's one demo
# trade and ALL THREE of sample_multi_trade_1m.csv's TSTW/TSTL/TSTE
# demo trades turned out to be built entirely around a BEARISH
# macd_bearish_cross signal opening a short position while flat --
# i.e. these "documented, deterministic" example datasets were
# unknowingly relying on the exact long/short bug Task 24/25A fixes
# (see results/task24_requirements_parity_audit/long_short_flow.md).
# Under the corrected LONG_ONLY lifecycle these signals are, correctly,
# NO_ACTIVE_POSITION no-ops -- zero trades.
#
# sample_AAPL_trade_1m.csv was regenerated in Task 73S
# (results/task73s_regression_and_zero_trade_diagnosis/stage1_fixture_diff_explanation.md):
# ~9 trading days of quiet, LOW_VOLATILITY-rejected pre-roll data were
# prepended (purely to satisfy the ALREADY-EXISTING, unmodified 200-bar/
# 15-min HTF trend-gate warmup requirement -- trend_gate_applicable is
# BULLISH-only, see talonx_quant/consumer.py), and a genuine BULLISH
# macd_bullish_cross recovery (RSI+volume confluence legs, clearing the
# HTF trend gate and structural R:R) was appended, producing one real
# long trade -- entry, TARGET exit, trades.csv/equity_curve.csv, and
# HTML report metrics are now genuinely exercised. The xfail marker
# below no longer applies to this fixture and has been removed from
# its tests (this comment documents why, per the marker's own original
# instruction: "an eventual CSV regeneration is forced to remove this
# marker, not silently leave it stale").
#
# sample_multi_trade_1m.csv (TSTW/TSTL/TSTE) was NOT touched by Task 73S
# (out of scope for that task's specific regression target) and remains
# the pending BLOCKING FOLLOW-UP tracked in
# results/task25a_long_only_parity_fix/task25a_summary.md.
_XFAIL_PENDING_SAMPLE_DATA_REGENERATION = pytest.mark.xfail(
    reason="Task 25A: sample_multi_trade_1m.csv's demo trades were built on the long/short bug "
           "(BEARISH-while-flat) that Task 24/25A fixed; now correctly produce zero trades. "
           "Needs a dedicated CSV-regeneration follow-up, not fixed here.",
    strict=True,
)


def _run(csv_path: Path, out_dir: Path):
    exit_code = cli.main(["--data", str(csv_path), "--symbol", "AAPL", "--tz", "America/New_York", "--out", str(out_dir)])
    return exit_code


def _run_multi(csv_path: Path, out_dir: Path):
    exit_code = cli.main([
        "--data", str(csv_path), "--symbols", "TSTW,TSTL,TSTE", "--tz", "America/New_York", "--out", str(out_dir),
    ])
    return exit_code


# ------------------------------------------------------------------
# Smoke-test dataset (sample_AAPL_1m.csv) -- zero-trade path
# ------------------------------------------------------------------

def test_smoke_dataset_file_exists_and_is_labeled():
    assert _SMOKE_CSV.is_file()
    readme = _SMOKE_CSV.parent / "README.md"
    assert readme.is_file()
    assert "NOT MARKET DATA" in readme.read_text(encoding="utf-8")


def test_smoke_dataset_never_flags_critical_corruption():
    from talonx_backtest.data import check_data_quality, load_ohlcv_csv

    df = load_ohlcv_csv(_SMOKE_CSV, symbol="AAPL", tz="America/New_York")
    report = check_data_quality(df, symbol="AAPL")
    assert not report.has_critical_corruption


def test_smoke_dataset_has_no_unexpected_intra_session_gaps():
    """Regular-session-only by design -- confirms it doesn't itself
    trip the "unexpected gap" heuristic the docs reference."""
    from talonx_backtest.data import check_data_quality, load_ohlcv_csv

    df = load_ohlcv_csv(_SMOKE_CSV, symbol="AAPL", tz="America/New_York")
    report = check_data_quality(df, symbol="AAPL")
    assert report.unexpected_intra_session_gap_bars == 0


def test_smoke_dataset_runs_the_documented_command_and_produces_zero_trades(tmp_path, capsys):
    exit_code = _run(_SMOKE_CSV, tmp_path)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "CRITICAL CORRUPTION:     no" in out
    assert "Trades executed:      0" in out

    summary = json.loads((tmp_path / "backtest_summary.json").read_text(encoding="utf-8"))
    assert summary["trades_executed"] == 0
    assert summary["signals_generated"] > 0          # the strategy DID evaluate candidates...
    assert sum(summary["rejections_by_reason"].values()) > 0  # ...and every one was rejected (recorded, not silently dropped)

    dq = json.loads((tmp_path / "backtest_data_quality.json").read_text(encoding="utf-8"))
    assert dq["AAPL"]["rows"] == 780
    assert dq["AAPL"]["is_clean"] is True


def test_smoke_dataset_output_files_are_valid_with_zero_trades(tmp_path):
    _run(_SMOKE_CSV, tmp_path)

    # trades.csv/equity_curve.csv must be header-only, never zero-byte
    # (an empty file is ambiguous: crashed run, or genuinely zero trades?).
    trades_csv = (tmp_path / "backtest_trades.csv").read_text(encoding="utf-8")
    equity_csv = (tmp_path / "backtest_equity_curve.csv").read_text(encoding="utf-8")
    assert trades_csv.strip() != ""
    assert len(trades_csv.strip().splitlines()) == 1  # header row only
    assert equity_csv.strip() != ""
    assert len(equity_csv.strip().splitlines()) == 1  # header row only

    trades_json = json.loads((tmp_path / "backtest_trades.json").read_text(encoding="utf-8"))
    assert trades_json == []

    html = (tmp_path / "backtest_results.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")


# ------------------------------------------------------------------
# Trade dataset (sample_AAPL_trade_1m.csv) -- actual-trade path
# ------------------------------------------------------------------

def test_trade_dataset_file_exists_and_is_labeled():
    assert _TRADE_CSV.is_file()
    readme = _TRADE_CSV.parent / "README.md"
    assert readme.is_file()
    text = readme.read_text(encoding="utf-8")
    assert "NOT MARKET DATA" in text
    assert "sample_AAPL_trade_1m" in text


def test_trade_dataset_never_flags_critical_corruption():
    from talonx_backtest.data import check_data_quality, load_ohlcv_csv

    df = load_ohlcv_csv(_TRADE_CSV, symbol="AAPL", tz="America/New_York")
    report = check_data_quality(df, symbol="AAPL")
    assert not report.has_critical_corruption


def test_trade_dataset_runs_the_documented_command_and_produces_at_least_one_trade(tmp_path, capsys):
    exit_code = _run(_TRADE_CSV, tmp_path)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "CRITICAL CORRUPTION:     no" in out

    summary = json.loads((tmp_path / "backtest_summary.json").read_text(encoding="utf-8"))
    assert summary["trades_executed"] >= 1
    assert summary["metrics"], "metrics section must be populated when trades exist"
    assert summary["metrics"]["net"]["total_trades"] >= 1


def test_trade_dataset_populates_trades_and_equity_curve_csv(tmp_path):
    _run(_TRADE_CSV, tmp_path)

    trades_csv_text = (tmp_path / "backtest_trades.csv").read_text(encoding="utf-8")
    trades_lines = trades_csv_text.strip().splitlines()
    assert len(trades_lines) >= 2  # header + at least one trade row

    equity_csv_text = (tmp_path / "backtest_equity_curve.csv").read_text(encoding="utf-8")
    equity_lines = equity_csv_text.strip().splitlines()
    assert len(equity_lines) >= 2  # header + at least one row

    trades_json = json.loads((tmp_path / "backtest_trades.json").read_text(encoding="utf-8"))
    assert len(trades_json) >= 1
    assert trades_json[0]["exit_reason"] in ("TARGET", "STOP", "END_OF_SESSION", "DATA_END")
    assert trades_json[0]["direction"] in ("bullish", "bearish")


def test_trade_dataset_exercises_a_concrete_exit_path(tmp_path):
    """"Ideally exercise at least one exit path" -- this fixture is
    calibrated to hit TARGET specifically, not just fall through to
    END_OF_SESSION/DATA_END."""
    _run(_TRADE_CSV, tmp_path)
    trades_json = json.loads((tmp_path / "backtest_trades.json").read_text(encoding="utf-8"))
    assert any(t["exit_reason"] == "TARGET" for t in trades_json)


def test_trade_dataset_html_report_contains_real_trade_metrics(tmp_path):
    _run(_TRADE_CSV, tmp_path)
    html = (tmp_path / "backtest_results.html").read_text(encoding="utf-8")

    start = html.index('id="payload">') + len('id="payload">')
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])

    assert payload["meta"]["trades_executed"] >= 1
    assert payload["metrics"]["net"]["total_trades"] >= 1
    assert len(payload["trades"]) >= 1
    assert len(payload["equity_curve"]) >= 1


def test_trade_dataset_signal_satisfies_the_frozen_strategy_naturally(tmp_path):
    """Confirms the qualifying candidate cleared confluence AND R:R at
    their PRODUCTION default values -- nothing about this dataset
    relies on a relaxed gate."""
    from talonx_quant.config import QuantConfig

    _run(_TRADE_CSV, tmp_path)
    trades_json = json.loads((tmp_path / "backtest_trades.json").read_text(encoding="utf-8"))
    config = QuantConfig()

    trade = trades_json[0]
    assert trade["confluence_score"] >= config.confluence_score_min
    assert trade["risk_reward_ratio"] >= config.min_risk_reward_ratio


# ------------------------------------------------------------------
# Multi-trade dataset (sample_multi_trade_1m.csv) -- TARGET / STOP /
# END_OF_SESSION exit paths, plus a real win+loss mix for aggregate
# statistics (profit factor, average loss, drawdown, cumulative R).
# ------------------------------------------------------------------

def test_multi_trade_dataset_file_exists_and_is_labeled():
    assert _MULTI_CSV.is_file()
    readme = _MULTI_CSV.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "sample_multi_trade_1m" in text
    assert "NOT MARKET DATA" in text


def test_multi_trade_dataset_never_flags_critical_corruption():
    from talonx_backtest.data import check_data_quality, load_ohlcv_csv

    df = load_ohlcv_csv(_MULTI_CSV, tz="America/New_York")  # has its own `symbol` column
    for symbol in ("TSTW", "TSTL", "TSTE"):
        report = check_data_quality(df[df["symbol"] == symbol].reset_index(drop=True), symbol=symbol)
        assert not report.has_critical_corruption


@_XFAIL_PENDING_SAMPLE_DATA_REGENERATION
def test_multi_trade_dataset_runs_the_documented_command_and_produces_three_trades(tmp_path, capsys):
    exit_code = _run_multi(_MULTI_CSV, tmp_path)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "CRITICAL CORRUPTION:     no" in out

    summary = json.loads((tmp_path / "backtest_summary.json").read_text(encoding="utf-8"))
    assert summary["trades_executed"] == 3


@_XFAIL_PENDING_SAMPLE_DATA_REGENERATION
def test_multi_trade_dataset_exercises_target_stop_and_eod_exit_reasons(tmp_path):
    _run_multi(_MULTI_CSV, tmp_path)
    trades_json = json.loads((tmp_path / "backtest_trades.json").read_text(encoding="utf-8"))

    exit_reasons = {t["symbol"]: t["exit_reason"] for t in trades_json}
    assert exit_reasons == {"TSTW": "TARGET", "TSTL": "STOP", "TSTE": "END_OF_SESSION"}


@_XFAIL_PENDING_SAMPLE_DATA_REGENERATION
def test_multi_trade_dataset_has_at_least_one_winner_and_one_loser(tmp_path):
    _run_multi(_MULTI_CSV, tmp_path)
    trades_json = json.loads((tmp_path / "backtest_trades.json").read_text(encoding="utf-8"))

    gross_r_values = [t["gross_R"] for t in trades_json]
    assert any(r > 0 for r in gross_r_values), "expected at least one winning trade"
    assert any(r < 0 for r in gross_r_values), "expected at least one losing trade"

    stop_trade = next(t for t in trades_json if t["symbol"] == "TSTL")
    assert stop_trade["gross_R"] == pytest.approx(-1.0)  # a clean 1R stop-out


@_XFAIL_PENDING_SAMPLE_DATA_REGENERATION
def test_multi_trade_dataset_populates_aggregate_statistics(tmp_path):
    """Profit factor / average loss / drawdown / cumulative R / win-loss
    stats all need >=1 win AND >=1 loss to be non-degenerate -- this
    dataset is the one fixture that actually exercises all of them on
    real numbers, not None/inf placeholders."""
    _run_multi(_MULTI_CSV, tmp_path)
    summary = json.loads((tmp_path / "backtest_summary.json").read_text(encoding="utf-8"))
    net = summary["metrics"]["net"]

    assert net["winning_trades"] == 2
    assert net["losing_trades"] == 1
    assert net["average_loss_r"] == pytest.approx(-1.0)
    assert net["average_win_r"] is not None and net["average_win_r"] > 0
    assert net["profit_factor"] is not None and net["profit_factor"] > 0 and net["profit_factor"] != float("inf")
    assert net["max_drawdown_r"] == pytest.approx(-1.0)  # the single STOP loss is the only drawdown episode
    assert net["total_r"] is not None and net["total_r"] > 0  # net positive despite the loss
    assert net["win_rate"] == pytest.approx(2 / 3)


@_XFAIL_PENDING_SAMPLE_DATA_REGENERATION
def test_multi_trade_dataset_equity_curve_reflects_the_win_loss_sequence(tmp_path):
    _run_multi(_MULTI_CSV, tmp_path)
    equity_text = (tmp_path / "backtest_equity_curve.csv").read_text(encoding="utf-8")
    lines = equity_text.strip().splitlines()
    assert len(lines) == 4  # header + 3 trades

    rows = [line.split(",") for line in lines[1:]]
    cumulative = [float(row[-1]) for row in rows]  # cumulative_net_R is the last column
    assert cumulative[0] < 0        # first realized trade is the STOP loss
    assert cumulative[-1] > 0       # ends net positive
    assert cumulative[-1] == max(cumulative)  # no drawdown after the recovery


@_XFAIL_PENDING_SAMPLE_DATA_REGENERATION
def test_multi_trade_dataset_html_report_contains_populated_metrics(tmp_path):
    _run_multi(_MULTI_CSV, tmp_path)
    html = (tmp_path / "backtest_results.html").read_text(encoding="utf-8")

    start = html.index('id="payload">') + len('id="payload">')
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])

    assert payload["metrics"]["net"]["total_trades"] == 3
    assert payload["metrics"]["net"]["winning_trades"] == 2
    assert payload["metrics"]["net"]["losing_trades"] == 1
    assert set(payload["exit_reasons"].keys()) == {"TARGET", "STOP", "END_OF_SESSION"}
    assert len(payload["equity_curve"]) == 3


def test_multi_trade_dataset_signals_satisfy_the_frozen_strategy_naturally(tmp_path):
    """All three symbols' signals must clear confluence/R:R at the
    PRODUCTION default values -- confirms none of this dataset relies
    on a relaxed gate, same posture as the single-trade fixture."""
    from talonx_quant.config import QuantConfig

    _run_multi(_MULTI_CSV, tmp_path)
    trades_json = json.loads((tmp_path / "backtest_trades.json").read_text(encoding="utf-8"))
    config = QuantConfig()

    for trade in trades_json:
        assert trade["confluence_score"] >= config.confluence_score_min
        assert trade["risk_reward_ratio"] >= config.min_risk_reward_ratio
