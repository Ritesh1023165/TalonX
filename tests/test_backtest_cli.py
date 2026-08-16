"""
tests/test_backtest_cli.py
-------------------------------
talonx_backtest.cli / `python -m talonx_backtest`: argument parsing,
single-file and directory data loading, date filtering, and that the
full results/ file set gets written. Invokes cli.main() directly rather
than via subprocess -- same code path, much faster.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from talonx_backtest import cli


def _write_csv(path, n=150, start="2026-01-05 14:30:00", symbol_col=False, symbol="AAPL"):
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    data = {"timestamp": ts, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0}
    if symbol_col:
        data["symbol"] = symbol
    pd.DataFrame(data).to_csv(path, index=False)


def test_cli_runs_single_csv_and_writes_all_report_files(tmp_path, capsys):
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path)
    out_dir = tmp_path / "out"

    exit_code = cli.main(["--data", str(csv_path), "--symbol", "AAPL", "--out", str(out_dir)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "DATA QUALITY" in captured.out
    assert "BACKTEST RESULT" in captured.out
    assert (out_dir / "backtest_results.html").exists()
    assert (out_dir / "backtest_trades.csv").exists()
    assert (out_dir / "backtest_data_quality.json").exists()

    dq = json.loads((out_dir / "backtest_data_quality.json").read_text(encoding="utf-8"))
    assert dq["AAPL"]["rows"] == 150


def test_cli_errors_cleanly_on_missing_data_path(tmp_path, capsys):
    exit_code = cli.main(["--data", str(tmp_path / "nope.csv"), "--out", str(tmp_path / "out")])
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


def test_cli_errors_when_start_end_filter_out_everything(tmp_path, capsys):
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path, start="2026-01-05 14:30:00")

    exit_code = cli.main([
        "--data", str(csv_path), "--symbol", "AAPL", "--out", str(tmp_path / "out"),
        "--start", "2030-01-01",
    ])
    assert exit_code == 1
    assert "no rows loaded" in capsys.readouterr().err


def test_cli_directory_input_with_symbol_filter(tmp_path, capsys):
    (tmp_path / "data").mkdir()
    _write_csv(tmp_path / "data" / "AAPL.csv")
    _write_csv(tmp_path / "data" / "MSFT.csv", start="2026-01-05 14:30:00")
    out_dir = tmp_path / "out"

    exit_code = cli.main(["--data", str(tmp_path / "data"), "--symbols", "AAPL", "--out", str(out_dir)])

    assert exit_code == 0
    dq = json.loads((out_dir / "backtest_data_quality.json").read_text(encoding="utf-8"))
    assert set(dq.keys()) == {"AAPL"}


def test_cli_uses_custom_prefix(tmp_path):
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path)
    out_dir = tmp_path / "out"

    exit_code = cli.main(["--data", str(csv_path), "--symbol", "AAPL", "--out", str(out_dir), "--prefix", "myrun"])

    assert exit_code == 0
    assert (out_dir / "myrun_results.html").exists()


def test_cli_start_end_actually_filters_rows(tmp_path):
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path, n=300, start="2026-01-05 14:30:00")
    out_dir = tmp_path / "out"

    exit_code = cli.main([
        "--data", str(csv_path), "--symbol", "AAPL", "--out", str(out_dir),
        "--start", "2026-01-05 15:00:00", "--end", "2026-01-05 16:00:00",
    ])
    assert exit_code == 0
    dq = json.loads((out_dir / "backtest_data_quality.json").read_text(encoding="utf-8"))
    assert dq["AAPL"]["rows"] == 61  # 15:00 through 16:00 inclusive, 1-min bars
