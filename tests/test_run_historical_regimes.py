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
    _cost_sensitivity_summary,
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


# --- 2026-08-17 Finding C: consolidation gap (small_sample_warning /
# cost_sensitivity now propagated) + unambiguous failure_reason ---------

def test_run_regime_propagates_small_sample_warning_and_cost_sensitivity(tmp_path):
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    out_root = tmp_path / "reports"
    summary_dir = out_root / "regime_test_regime"
    summary_dir.mkdir(parents=True)
    cost_rows = [
        {"cost_bps": 0, "trades": 3, "expectancy_r": -1.0},
        {"cost_bps": 20, "trades": 3, "expectancy_r": -2.103},
    ]
    (summary_dir / "backtest_summary.json").write_text(json.dumps({
        "metrics": {"net": {
            "total_trades": 3, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_r": -1.0,
            "max_drawdown_r": -3.0, "sharpe_per_trade": None, "sortino_per_trade": None,
        }},
        "small_sample_warning": True,
        "cost_sensitivity": cost_rows,
    }), encoding="utf-8")

    fake_result = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake_result):
        row = run_regime(regime, tmp_path / "data", ["AAPL"], out_root, cost_sensitivity=True, tz="UTC")

    assert row["small_sample_warning"] is True
    assert row["cost_sensitivity"] == cost_rows
    assert row["failure_reason"] is None


def test_run_regime_zero_trades_still_carries_small_sample_and_cost_fields(tmp_path):
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    out_root = tmp_path / "reports"
    summary_dir = out_root / "regime_test_regime"
    summary_dir.mkdir(parents=True)
    (summary_dir / "backtest_summary.json").write_text(json.dumps({
        "metrics": {}, "small_sample_warning": False, "cost_sensitivity": [],
    }), encoding="utf-8")

    fake_result = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake_result):
        row = run_regime(regime, tmp_path / "data", ["AAPL"], out_root, cost_sensitivity=True, tz="UTC")

    assert row["ran"] is True
    assert row["total_trades"] == 0
    assert row["small_sample_warning"] is False
    assert row["cost_sensitivity"] is None  # empty list normalized to None, not fabricated


def test_run_regime_distinguishes_process_failure_from_missing_summary(tmp_path):
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    out_root = tmp_path / "reports"  # no summary file written at all

    process_failed = MagicMock(returncode=1, stdout="", stderr="crash")
    with patch("subprocess.run", return_value=process_failed):
        row_a = run_regime(regime, tmp_path / "data", ["AAPL"], out_root, cost_sensitivity=False, tz="UTC")
    assert row_a["failure_reason"] == "process_failed"

    exit_zero_no_summary = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=exit_zero_no_summary):
        row_b = run_regime(regime, tmp_path / "data", ["AAPL"], out_root, cost_sensitivity=False, tz="UTC")
    assert row_b["failure_reason"] == "missing_summary"

    assert row_a["failure_reason"] != row_b["failure_reason"]  # the actual ambiguity being fixed


def _summary_json(**overrides) -> str:
    base = {
        "metrics": {"net": {
            "total_trades": 5, "win_rate": 0.6, "profit_factor": 1.8, "expectancy_r": 0.25,
            "total_r": 1.25, "max_drawdown_r": -1.2, "sharpe_per_trade": 0.9, "sortino_per_trade": 1.4,
        }},
        "small_sample_warning": False,
        "cost_sensitivity": [],
    }
    base.update(overrides)
    return json.dumps(base)


def _run(tmp_path, out_root, summary_text, cost_sensitivity=True, returncode=0):
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    if summary_text is not None:
        summary_dir = out_root / "regime_test_regime"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / "backtest_summary.json").write_text(summary_text, encoding="utf-8")
    fake_result = MagicMock(returncode=returncode, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake_result):
        return run_regime(regime, tmp_path / "data", ["AAPL"], out_root, cost_sensitivity=cost_sensitivity, tz="UTC")


# --- 2026-08-17 Task 5.3: unified status field (SUCCESS / SUCCESS_ZERO_TRADES /
# SUCCESS_SMALL_SAMPLE / FAILED_PROCESS / FAILED_MISSING_SUMMARY / FAILED_INVALID_SUMMARY) ---

def test_status_is_success_for_a_normal_populated_regime(tmp_path):
    row = _run(tmp_path, tmp_path / "r1", _summary_json())
    assert row["status"] == "SUCCESS"
    assert row["total_r"] == 1.25  # newly propagated, from metrics.net.total_r


def test_status_is_success_zero_trades_not_a_failure(tmp_path):
    row = _run(tmp_path, tmp_path / "r2", _summary_json(metrics={}))
    assert row["ran"] is True  # zero trades is NOT a failure
    assert row["status"] == "SUCCESS_ZERO_TRADES"
    assert row["total_trades"] == 0


def test_status_is_success_small_sample_when_flagged_and_nonzero_trades(tmp_path):
    row = _run(tmp_path, tmp_path / "r3", _summary_json(small_sample_warning=True))
    assert row["status"] == "SUCCESS_SMALL_SAMPLE"


def test_status_zero_trades_takes_priority_over_small_sample_flag(tmp_path):
    # An (unrealistic, but defensively worth pinning) summary claiming
    # BOTH zero trades AND small_sample_warning=True must resolve to the
    # more specific SUCCESS_ZERO_TRADES, not SUCCESS_SMALL_SAMPLE.
    row = _run(tmp_path, tmp_path / "r4", _summary_json(metrics={}, small_sample_warning=True))
    assert row["status"] == "SUCCESS_ZERO_TRADES"


def test_status_is_failed_process_on_nonzero_exit(tmp_path):
    row = _run(tmp_path, tmp_path / "r5", None, returncode=1)
    assert row["status"] == "FAILED_PROCESS"


def test_status_is_failed_missing_summary_on_exit_zero_no_file(tmp_path):
    row = _run(tmp_path, tmp_path / "r6", None, returncode=0)
    assert row["status"] == "FAILED_MISSING_SUMMARY"


def test_status_is_failed_invalid_summary_on_malformed_json(tmp_path):
    row = _run(tmp_path, tmp_path / "r7", "{not valid json")
    assert row["status"] == "FAILED_INVALID_SUMMARY"


# --- cost sensitivity: all scenarios + requested-vs-missing distinction ---

def test_all_four_cost_scenarios_survive_consolidation_with_every_field(tmp_path):
    cost_rows = [
        {"cost_bps": 0, "trades": 10, "win_rate": 0.5, "profit_factor": 1.5, "expectancy_r": 0.1, "total_r": 1.0, "max_drawdown_r": -2.0},
        {"cost_bps": 5, "trades": 10, "win_rate": 0.5, "profit_factor": 1.4, "expectancy_r": 0.05, "total_r": 0.5, "max_drawdown_r": -2.1},
        {"cost_bps": 10, "trades": 10, "win_rate": 0.5, "profit_factor": 1.3, "expectancy_r": 0.0, "total_r": 0.0, "max_drawdown_r": -2.2},
        {"cost_bps": 20, "trades": 10, "win_rate": 0.5, "profit_factor": 1.1, "expectancy_r": -0.1, "total_r": -1.0, "max_drawdown_r": -2.4},
    ]
    row = _run(tmp_path, tmp_path / "r8", _summary_json(cost_sensitivity=cost_rows))
    assert row["cost_sensitivity"] == cost_rows  # every row, every field, byte-for-byte, nothing recalculated
    assert len(row["cost_sensitivity"]) == 4


def test_cost_sensitivity_requested_flag_distinguishes_not_requested_from_missing(tmp_path):
    not_requested = _run(tmp_path, tmp_path / "r9", _summary_json(cost_sensitivity=[]), cost_sensitivity=False)
    assert not_requested["cost_sensitivity_requested"] is False
    assert not_requested["cost_sensitivity"] is None

    requested_but_absent = _run(tmp_path, tmp_path / "r10", _summary_json(cost_sensitivity=[]), cost_sensitivity=True)
    assert requested_but_absent["cost_sensitivity_requested"] is True
    assert requested_but_absent["cost_sensitivity"] is None
    # same observable cost_sensitivity value (None) but a DIFFERENT reason, distinguishable via the new flag
    assert not_requested["cost_sensitivity_requested"] != requested_but_absent["cost_sensitivity_requested"]


def test_markdown_cost_sensitivity_section_explains_absence_reasons():
    rows = [
        {  # not requested
            "regime": "not_requested", "start": "2024-01-01", "end": "2024-06-30", "ran": True,
            "exit_code": 0, "failure_reason": None, "status": "SUCCESS", "total_trades": 1,
            "win_rate": 1.0, "profit_factor": None, "expectancy_r": 1.0, "total_r": 1.0,
            "max_drawdown_r": 0.0, "sharpe_per_trade": None, "sortino_per_trade": None,
            "small_sample_warning": True, "cost_sensitivity": None, "cost_sensitivity_requested": False,
        },
        {  # requested but absent from the summary
            "regime": "requested_missing", "start": "2024-01-01", "end": "2024-06-30", "ran": True,
            "exit_code": 0, "failure_reason": None, "status": "SUCCESS", "total_trades": 1,
            "win_rate": 1.0, "profit_factor": None, "expectancy_r": 1.0, "total_r": 1.0,
            "max_drawdown_r": 0.0, "sharpe_per_trade": None, "sortino_per_trade": None,
            "small_sample_warning": True, "cost_sensitivity": None, "cost_sensitivity_requested": True,
        },
        {  # the regime never ran at all
            "regime": "never_ran", "start": "2024-01-01", "end": "2024-06-30", "ran": False,
            "exit_code": 1, "failure_reason": "process_failed", "status": "FAILED_PROCESS",
            "total_trades": None, "win_rate": None, "profit_factor": None, "expectancy_r": None,
            "total_r": None, "max_drawdown_r": None, "sharpe_per_trade": None, "sortino_per_trade": None,
            "small_sample_warning": None, "cost_sensitivity": None, "cost_sensitivity_requested": None,
        },
    ]
    markdown = build_markdown_table(rows)

    assert "### not_requested" in markdown
    assert "not requested for this run" in markdown

    assert "### requested_missing" in markdown
    assert "requested for this run, but is absent" in markdown

    assert "### never_ran" in markdown
    assert "did not produce a usable result" in markdown


def test_run_regime_handles_invalid_summary_json_without_crashing(tmp_path):
    # Previously an unparseable summary.json would raise INSIDE run_regime
    # and crash the whole multi-regime run -- now it's caught and reported
    # as this one regime's row.
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    out_root = tmp_path / "reports"
    summary_dir = out_root / "regime_test_regime"
    summary_dir.mkdir(parents=True)
    (summary_dir / "backtest_summary.json").write_text("{not valid json", encoding="utf-8")

    fake_result = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake_result):
        row = run_regime(regime, tmp_path / "data", ["AAPL"], out_root, cost_sensitivity=False, tz="UTC")  # must not raise

    assert row["ran"] is False
    assert row["failure_reason"].startswith("invalid_summary")


def test_cost_sensitivity_summary_shows_low_and_high_bps_expectancy():
    rows = [
        {"cost_bps": 0, "expectancy_r": -1.0},
        {"cost_bps": 5, "expectancy_r": -1.276},
        {"cost_bps": 20, "expectancy_r": -2.103},
    ]
    summary = _cost_sensitivity_summary(rows)
    assert "-1.000 (0bps)" in summary
    assert "-2.103 (20bps)" in summary


def test_cost_sensitivity_summary_is_na_when_not_requested():
    assert _cost_sensitivity_summary(None) == "n/a"
    assert _cost_sensitivity_summary([]) == "n/a"


def test_markdown_table_shows_small_sample_column_and_a_dedicated_cost_sensitivity_section():
    # 2026-08-17 consolidated-reporting redesign: cost sensitivity moved
    # OUT of the compact main table into its own '## Cost Sensitivity'
    # section (one '### {regime}' sub-table per regime, one row per bps
    # scenario) -- see _cost_sensitivity_section.
    rows = [{
        "regime": "r1", "start": "2024-01-01", "end": "2024-06-30", "ran": True, "exit_code": 0,
        "failure_reason": None, "status": "SUCCESS_SMALL_SAMPLE", "total_trades": 3, "win_rate": 0.0,
        "profit_factor": 0.0, "expectancy_r": -1.0, "total_r": -3.0, "max_drawdown_r": -3.0,
        "sharpe_per_trade": None, "sortino_per_trade": None, "small_sample_warning": True,
        "cost_sensitivity_requested": True,
        "cost_sensitivity": [
            {"cost_bps": 0, "trades": 3, "expectancy_r": -1.0, "profit_factor": 0.0, "max_drawdown_r": -3.0},
            {"cost_bps": 20, "trades": 3, "expectancy_r": -2.1, "profit_factor": 0.0, "max_drawdown_r": -6.3},
        ],
    }]
    markdown = build_markdown_table(rows)

    # main table: compact, small-sample column present, status visible
    assert "| yes |" in markdown
    assert "SUCCESS_SMALL_SAMPLE" in markdown

    # dedicated cost-sensitivity section: every bps scenario, its own sub-table
    assert "## Cost Sensitivity" in markdown
    assert "### r1" in markdown
    assert "| 0 | 3 | -1.000 | 0.00 | -3.00 |" in markdown
    assert "| 20 | 3 | -2.100 | 0.00 | -6.30 |" in markdown


def test_markdown_table_failed_row_shows_the_specific_failure_reason():
    rows = [{
        "regime": "r1", "start": "2024-01-01", "end": "2024-06-30", "ran": False, "exit_code": 0,
        "failure_reason": "missing_summary", "total_trades": None, "win_rate": None, "profit_factor": None,
        "expectancy_r": None, "max_drawdown_r": None, "sharpe_per_trade": None, "sortino_per_trade": None,
        "small_sample_warning": None, "cost_sensitivity": None,
    }]
    markdown = build_markdown_table(rows)
    assert "missing_summary" in markdown


def test_no_cost_sensitivity_flag_omits_the_cli_flag(tmp_path):
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    fake_result = MagicMock(returncode=1, stdout="", stderr="")
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        run_regime(regime, tmp_path / "data", ["AAPL"], tmp_path / "reports", cost_sensitivity=False, tz="UTC")
    called_argv = mock_run.call_args.args[0]
    assert "--cost-sensitivity" not in called_argv


def test_run_regime_does_not_capture_subprocess_output(tmp_path):
    # Regression test: capture_output=True/text=True used to buffer the
    # child `python -m talonx_backtest` process's stdout/stderr (including
    # its own progress lines) and only print it after the whole subprocess
    # exited -- a long regime run looked hung with zero output for
    # minutes. The child must inherit this process's stdout/stderr so
    # everything streams live.
    regime = Regime("test_regime", "2024-01-01", "2024-06-30", "test")
    fake_result = MagicMock(returncode=1, stdout="", stderr="")
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        run_regime(regime, tmp_path / "data", ["AAPL"], tmp_path / "reports", cost_sensitivity=False, tz="UTC")

    assert mock_run.call_args.kwargs.get("capture_output") is not True
    assert "stdout" not in mock_run.call_args.kwargs
    assert "stderr" not in mock_run.call_args.kwargs


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
