"""
tests/test_backtest_sample_data.py
----------------------------------------
The deterministic sample dataset (examples/data/sample_AAPL_1m.csv)
must run successfully via the EXACT documented command (spec sections 3
and 19) -- proves a fresh clone can go from nothing to an open HTML
report without real market data, matching docs/backtesting.md and the
README's "Run your first backtest" section word for word.
"""
from __future__ import annotations

import json
from pathlib import Path

from talonx_backtest import cli

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_CSV = _REPO_ROOT / "examples" / "data" / "sample_AAPL_1m.csv"


def test_sample_dataset_file_exists_and_is_labeled():
    assert _SAMPLE_CSV.is_file()
    readme = _SAMPLE_CSV.parent / "README.md"
    assert readme.is_file()
    assert "NOT MARKET DATA" in readme.read_text(encoding="utf-8")


def test_documented_sample_command_runs_successfully(tmp_path, capsys):
    # Exactly the command in README.md / docs/backtesting.md, with --out
    # redirected into a temp dir so this test doesn't write into the repo.
    exit_code = cli.main([
        "--data", str(_SAMPLE_CSV), "--symbol", "AAPL", "--tz", "America/New_York",
        "--out", str(tmp_path),
    ])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "CRITICAL CORRUPTION:     no" in out
    assert (tmp_path / "backtest_results.html").is_file()
    assert (tmp_path / "backtest_summary.txt").is_file()

    summary = json.loads((tmp_path / "backtest_data_quality.json").read_text(encoding="utf-8"))
    assert summary["AAPL"]["rows"] == 780
    assert summary["AAPL"]["is_clean"] is True


def test_sample_dataset_never_flags_critical_corruption():
    from talonx_backtest.data import check_data_quality, load_ohlcv_csv

    df = load_ohlcv_csv(_SAMPLE_CSV, symbol="AAPL", tz="America/New_York")
    report = check_data_quality(df, symbol="AAPL")
    assert not report.has_critical_corruption


def test_sample_dataset_has_no_unexpected_intra_session_gaps():
    """The sample is regular-session-only by design -- confirms it
    doesn't itself trip the "unexpected gap" heuristic the docs
    reference."""
    from talonx_backtest.data import check_data_quality, load_ohlcv_csv

    df = load_ohlcv_csv(_SAMPLE_CSV, symbol="AAPL", tz="America/New_York")
    report = check_data_quality(df, symbol="AAPL")
    assert report.unexpected_intra_session_gap_bars == 0
