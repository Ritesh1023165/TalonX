"""
tests/test_run_historical_regimes.py
------------------------------------------
scripts/run_historical_regimes.py -- regime configuration, symbol
discovery, markdown/JSON comparison-table building (all mocked-
subprocess, fast), plus one real end-to-end run (an actual
`python -m talonx_backtest` subprocess) against the deterministic
sample_AAPL_trade_1m.csv fixture, proving the full orchestration path
works, not just its individual pieces.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.run_historical_regimes import (
    REGIMES,
    Regime,
    _discover_symbols,
    build_markdown_table,
    main,
    run_regime,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


# --- regime configuration ---

def test_all_four_required_regimes_are_defined():
    assert set(REGIMES.keys()) == {
        "bull_momentum_2024", "high_vol_pullback_2024", "range_chop_2025", "full_period_2024_2026",
    }


def test_regime_date_ranges_are_chronologically_valid():
    import pandas as pd
    for regime in REGIMES.values():
        assert pd.Timestamp(regime.start) < pd.Timestamp(regime.end)


# --- symbol discovery ---

def test_discover_symbols_flat_layout(tmp_path):
    (tmp_path / "AAPL.csv").write_text("timestamp,open,high,low,close,volume\n")
    (tmp_path / "msft.csv").write_text("timestamp,open,high,low,close,volume\n")
    assert _discover_symbols(tmp_path) == ["AAPL", "MSFT"]


def test_discover_symbols_subdirectory_layout(tmp_path):
    (tmp_path / "AAPL").mkdir()
    (tmp_path / "NVDA").mkdir()
    assert _discover_symbols(tmp_path) == ["AAPL", "NVDA"]


# --- run_regime (mocked subprocess) ---

def test_run_regime_parses_summary_json_on_success(tmp_path):
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    out_root = tmp_path / "reports"
    summary_dir = out_root / "regime_test_regime"
    summary_dir.mkdir(parents=True)
    (summary_dir / "backtest_summary.json").write_text(json.dumps({
        "metrics": {"net": {
            "total_trades": 5, "win_rate": 0.6, "profit_factor": 1.8, "expectancy_r": 0.25,
            "max_drawdown_r": -1.2, "sharpe_per_trade": 0.9, "sortino_per_trade": 1.4,
        }},
    }), encoding="utf-8")

    fake_result = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        row = run_regime(regime, tmp_path / "data", ["AAPL"], out_root, cost_sensitivity=True, tz="UTC")

    assert row["ran"] is True
    assert row["total_trades"] == 5
    assert row["win_rate"] == 0.6
    called_argv = mock_run.call_args.args[0]
    assert "--cost-sensitivity" in called_argv
    assert "--symbols" in called_argv and "AAPL" in called_argv
    assert "--start" in called_argv and "2024-01-01" in called_argv


def test_run_regime_reports_failure_without_fabricating_metrics(tmp_path):
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    out_root = tmp_path / "reports"
    fake_result = MagicMock(returncode=1, stdout="", stderr="error: no rows loaded")

    with patch("subprocess.run", return_value=fake_result):
        row = run_regime(regime, tmp_path / "data", ["AAPL"], out_root, cost_sensitivity=True, tz="UTC")

    assert row["ran"] is False
    assert row["exit_code"] == 1
    assert row["total_trades"] is None
    assert row["profit_factor"] is None


def test_run_regime_zero_trades_reports_zero_not_none(tmp_path):
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    out_root = tmp_path / "reports"
    summary_dir = out_root / "regime_test_regime"
    summary_dir.mkdir(parents=True)
    (summary_dir / "backtest_summary.json").write_text(json.dumps({"metrics": {}}), encoding="utf-8")

    fake_result = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake_result):
        row = run_regime(regime, tmp_path / "data", ["AAPL"], out_root, cost_sensitivity=True, tz="UTC")

    assert row["ran"] is True
    assert row["total_trades"] == 0
    assert row["win_rate"] is None


def test_no_cost_sensitivity_flag_omits_the_cli_flag(tmp_path):
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    fake_result = MagicMock(returncode=1, stdout="", stderr="")
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        run_regime(regime, tmp_path / "data", ["AAPL"], tmp_path / "reports", cost_sensitivity=False, tz="UTC")
    called_argv = mock_run.call_args.args[0]
    assert "--cost-sensitivity" not in called_argv


# --- markdown table ---

def test_markdown_table_includes_every_regime_and_a_no_optimization_disclaimer():
    rows = [
        {"regime": "r1", "start": "2024-01-01", "end": "2024-06-30", "ran": True, "exit_code": 0,
         "total_trades": 5, "win_rate": 0.6, "profit_factor": 1.8, "expectancy_r": 0.25,
         "max_drawdown_r": -1.2, "sharpe_per_trade": 0.9, "sortino_per_trade": 1.4},
        {"regime": "r2", "start": "2024-07-01", "end": "2024-09-30", "ran": False, "exit_code": 2,
         "total_trades": None, "win_rate": None, "profit_factor": None, "expectancy_r": None,
         "max_drawdown_r": None, "sharpe_per_trade": None, "sortino_per_trade": None},
    ]
    markdown = build_markdown_table(rows)
    assert "r1" in markdown and "r2" in markdown
    assert "not a parameter search" in markdown.lower()
    assert "FAILED" in markdown
    assert "60.0%" in markdown  # win_rate formatted as a percentage


def test_markdown_table_never_fabricates_missing_values():
    rows = [{
        "regime": "r1", "start": "2024-01-01", "end": "2024-06-30", "ran": True, "exit_code": 0,
        "total_trades": 0, "win_rate": None, "profit_factor": None, "expectancy_r": None,
        "max_drawdown_r": None, "sharpe_per_trade": None, "sortino_per_trade": None,
    }]
    markdown = build_markdown_table(rows)
    assert markdown.count("n/a") >= 5


# --- CLI errors ---

def test_main_errors_cleanly_on_missing_data_dir(tmp_path, capsys):
    exit_code = main(["--data-dir", str(tmp_path / "does_not_exist")])
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


def test_main_errors_on_unknown_regime(tmp_path, capsys):
    (tmp_path / "AAPL.csv").write_text("timestamp,open,high,low,close,volume\n")
    exit_code = main(["--data-dir", str(tmp_path), "--regimes", "not_a_real_regime"])
    assert exit_code == 1
    assert "unknown regime" in capsys.readouterr().err


# --- one real end-to-end run (actual subprocess, deterministic sample data) ---

def test_real_end_to_end_run_against_the_sample_trade_dataset(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy(_REPO_ROOT / "examples" / "data" / "sample_AAPL_trade_1m.csv", data_dir / "AAPL.csv")

    out_root = tmp_path / "reports"
    exit_code = main([
        "--data-dir", str(data_dir), "--symbols", "AAPL", "--regimes", "full_period_2024_2026",
        "--out-dir", str(out_root), "--tz", "America/New_York", "--no-cost-sensitivity",
    ])

    assert exit_code == 0
    comparison = json.loads((out_root / "regime_comparison.json").read_text(encoding="utf-8"))
    assert len(comparison) == 1
    assert comparison[0]["ran"] is True
    assert comparison[0]["total_trades"] == 1  # sample_AAPL_trade_1m.csv's one calibrated TARGET trade

    markdown = (out_root / "regime_comparison.md").read_text(encoding="utf-8")
    assert "full_period_2024_2026" in markdown
    assert (out_root / "regime_full_period_2024_2026" / "backtest_results.html").is_file()
