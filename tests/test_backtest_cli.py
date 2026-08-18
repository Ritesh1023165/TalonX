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
from talonx_backtest.reproducibility import get_dataset_hash


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


def test_cli_wires_the_real_input_path_through_to_dataset_hash(tmp_path):
    # 2026-08-17 Task 5.2: proves the actual end-to-end plumbing, not
    # just reproducibility.py's own unit tests -- a real `python -m
    # talonx_backtest` run's written summary.json must carry a
    # dataset_hash that matches independently hashing the same --data
    # path/--symbols the CLI was actually given.
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path)
    out_dir = tmp_path / "out"

    exit_code = cli.main(["--data", str(csv_path), "--symbol", "AAPL", "--out", str(out_dir)])
    assert exit_code == 0

    summary = json.loads((out_dir / "backtest_summary.json").read_text(encoding="utf-8"))
    reported_hash = summary["reproducibility"]["dataset_hash"]
    assert reported_hash is not None
    assert reported_hash == get_dataset_hash(csv_path)


def test_cli_research_telemetry_off_by_default_writes_no_telemetry_files(tmp_path):
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path)
    out_dir = tmp_path / "out"

    exit_code = cli.main(["--data", str(csv_path), "--symbol", "AAPL", "--out", str(out_dir)])

    assert exit_code == 0
    assert not (out_dir / "backtest_research_volatility_telemetry.csv").exists()
    assert not (out_dir / "backtest_research_candidate_telemetry.csv").exists()
    # existing artifact set is unaffected by this flag's mere existence
    assert (out_dir / "backtest_trades.csv").exists()


def test_cli_research_telemetry_flag_writes_telemetry_files(tmp_path, capsys):
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path)
    out_dir = tmp_path / "out"

    exit_code = cli.main([
        "--data", str(csv_path), "--symbol", "AAPL", "--out", str(out_dir), "--research-telemetry",
    ])

    assert exit_code == 0
    vol_path = out_dir / "backtest_research_volatility_telemetry.csv"
    cand_path = out_dir / "backtest_research_candidate_telemetry.csv"
    assert vol_path.exists()
    assert cand_path.exists()

    vol_df = pd.read_csv(vol_path)
    assert len(vol_df) > 0  # flat fixture still clears warm-up and gets evaluated every bar
    assert list(vol_df.columns) == [
        "timestamp", "symbol", "price", "atr", "atr_pct", "volatility_threshold", "passes_volatility",
    ]

    captured = capsys.readouterr()
    assert "Research telemetry written" in captured.out


def test_cli_help_does_not_crash(capsys):
    # Regression test (2026-08-17, discovered during Task 6): the
    # --no-progress help string contained a literal "X% (bars..." --
    # argparse's HelpFormatter treats help text as a %-format template,
    # so an unescaped "% (" crashed with ValueError: unsupported format
    # character '(' before --help could ever print anything. Fixed by
    # escaping it as "%%" (see cli.py); this pins --help to actually
    # exit 0 and print the flag's help text, not just "not raise".
    with pytest.raises(SystemExit) as exc_info:
        cli._build_parser().parse_args(["--help"])
    assert exc_info.value.code == 0
    assert "--no-progress" in capsys.readouterr().out


def test_cli_interim_stdout_dataset_hash_matches_persisted_summary(tmp_path, capsys):
    # Regression test (2026-08-17, discovered during Task 6): main()'s
    # interim result_summary_text() print used to omit dataset_path/
    # dataset_symbols (only write_report's later call had them), so a
    # run's live stdout showed "dataset_hash: None" for the same run
    # whose persisted backtest_summary.json carried the real hash --
    # same run, two different answers to "what data was this?". Fixed
    # by computing dataset_symbols once, before the interim print, and
    # passing it (plus --data) into both call sites.
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path)
    out_dir = tmp_path / "out"

    exit_code = cli.main(["--data", str(csv_path), "--symbol", "AAPL", "--out", str(out_dir)])
    assert exit_code == 0

    stdout = capsys.readouterr().out
    interim_lines = [line for line in stdout.splitlines() if line.strip().startswith("dataset_hash:")]
    assert len(interim_lines) == 1
    interim_hash = interim_lines[0].split(":", 1)[1].strip()
    assert interim_hash != "None"

    summary = json.loads((out_dir / "backtest_summary.json").read_text(encoding="utf-8"))
    persisted_hash = summary["reproducibility"]["dataset_hash"]

    assert interim_hash == persisted_hash == get_dataset_hash(csv_path)


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


# --- progress reporting (--no-progress / --progress-interval) ---

def test_cli_prints_progress_lines_by_default(tmp_path, capsys):
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path, n=150)
    out_dir = tmp_path / "out"

    exit_code = cli.main([
        "--data", str(csv_path), "--symbol", "AAPL", "--out", str(out_dir),
        "--progress-interval", "0",
    ])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "progress:" in out
    assert "150/150 bars" in out


def test_cli_no_progress_flag_suppresses_progress_lines(tmp_path, capsys):
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path, n=150)
    out_dir = tmp_path / "out"

    exit_code = cli.main([
        "--data", str(csv_path), "--symbol", "AAPL", "--out", str(out_dir),
        "--no-progress", "--progress-interval", "0",
    ])

    assert exit_code == 0
    assert "progress:" not in capsys.readouterr().out


def test_cli_cost_sensitivity_progress_lines_are_labeled_per_scenario(tmp_path, capsys):
    csv_path = tmp_path / "aapl.csv"
    _write_csv(csv_path, n=60)
    out_dir = tmp_path / "out"

    exit_code = cli.main([
        "--data", str(csv_path), "--symbol", "AAPL", "--out", str(out_dir),
        "--cost-sensitivity", "--progress-interval", "0",
    ])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "progress: scenario 1/4 (0 bps)" in out
    assert "progress: scenario 4/4 (20 bps)" in out
