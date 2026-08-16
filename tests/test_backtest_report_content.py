"""
tests/test_backtest_report_content.py
-------------------------------------------
Verifies the HTML/JSON report actually SURFACES execution assumptions,
the zero-cost warning, timezone info, and reproducibility metadata
(spec sections 7, 8, 9, 11, 12) -- not just that the underlying data
exists somewhere, but that result_summary_text/json and
build_html_report's payload contain it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from talonx_backtest.data import from_dataframe
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_backtest.execution import ExecutionConfig
from talonx_backtest.reports import (
    build_html_report,
    execution_assumptions_dict,
    is_zero_cost_run,
    result_summary_json,
    result_summary_text,
    timezone_info_dict,
)
from talonx_quant.config import QuantConfig


def _tiny_df():
    ts = pd.date_range("2026-01-05 14:30:00", periods=5, freq="1min", tz="UTC")
    return from_dataframe(pd.DataFrame({
        "timestamp": ts, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0,
    }), symbol="AAPL")


def _payload_from_html(html: str) -> dict:
    start = html.index('id="payload">') + len('id="payload">')
    end = html.index("</script>", start)
    return json.loads(html[start:end])


def test_zero_cost_run_is_detected():
    result = BacktestEngine(BacktestConfig()).run(_tiny_df())
    assert is_zero_cost_run(result)


def test_nonzero_cost_run_is_not_flagged_zero_cost():
    config = BacktestConfig(execution=ExecutionConfig(entry_slippage_bps=5.0))
    result = BacktestEngine(config).run(_tiny_df())
    assert not is_zero_cost_run(result)


def test_execution_assumptions_dict_reflects_actual_config():
    config = BacktestConfig(
        execution=ExecutionConfig(entry_slippage_bps=5.0, exit_slippage_bps=7.0, spread_bps=10.0, same_bar_resolution="target_first"),
        eod_flatten_enabled=False,
    )
    result = BacktestEngine(config).run(_tiny_df())
    assumptions = execution_assumptions_dict(result)
    assert assumptions == {
        "entry_slippage_bps": 5.0, "exit_slippage_bps": 7.0, "spread_bps": 10.0,
        "same_bar_resolution": "target_first", "eod_flatten_enabled": False,
        "allow_overlapping_trades": False,
    }


def test_summary_text_shows_zero_cost_warning_banner():
    result = BacktestEngine(BacktestConfig()).run(_tiny_df())
    text = result_summary_text(result)
    assert "COST-FREE BASELINE" in text
    assert "do NOT represent realistic execution costs" in text


def test_summary_text_omits_warning_when_costs_are_set():
    config = BacktestConfig(execution=ExecutionConfig(entry_slippage_bps=5.0, exit_slippage_bps=5.0, spread_bps=10.0))
    result = BacktestEngine(config).run(_tiny_df())
    text = result_summary_text(result)
    assert "COST-FREE BASELINE" not in text


def test_summary_text_shows_eod_flatten_state():
    enabled = BacktestEngine(BacktestConfig(eod_flatten_enabled=True)).run(_tiny_df())
    disabled = BacktestEngine(BacktestConfig(eod_flatten_enabled=False)).run(_tiny_df())
    assert "EOD flatten:          ENABLED" in result_summary_text(enabled)
    assert "EOD flatten:          DISABLED" in result_summary_text(disabled)


def test_summary_text_shows_timezone_and_reproducibility_sections():
    result = BacktestEngine(BacktestConfig()).run(_tiny_df())
    text = result_summary_text(result, input_timezone="America/New_York")
    assert "Input timezone:       America/New_York" in text
    assert "Internal timezone:    UTC" in text
    assert "Session timezone:     America/New_York" in text
    assert "git_commit:" in text
    assert "strategy_version:" in text
    assert "config_hash:" in text


def test_timezone_info_dict_reports_unspecified_when_not_given():
    assert timezone_info_dict(None)["input_timezone"] == "unspecified"


def test_summary_json_contains_execution_assumptions_and_metadata():
    result = BacktestEngine(BacktestConfig()).run(_tiny_df())
    payload = json.loads(result_summary_json(result, input_timezone="UTC"))

    assert payload["execution_assumptions"]["entry_slippage_bps"] == 0.0
    assert payload["zero_cost_baseline_warning"] is True
    assert payload["timezone"]["input_timezone"] == "UTC"
    assert "git_commit" in payload["reproducibility"]
    assert "strategy_version" in payload["reproducibility"]
    assert "portfolio_disclaimer" in payload
    assert "survivorship_bias_note" in payload


def test_html_report_payload_contains_all_required_sections():
    result = BacktestEngine(BacktestConfig()).run(_tiny_df())
    html = build_html_report(result, input_timezone="America/New_York")
    payload = _payload_from_html(html)

    assert payload["execution_assumptions"]["same_bar_resolution"] == "stop_first"
    assert payload["zero_cost_baseline_warning"] is True
    assert payload["timezone"]["session_timezone"] == "America/New_York"
    assert payload["reproducibility"]["config_hash"]
    assert payload["portfolio_disclaimer"]
    assert payload["survivorship_bias_note"]
    assert payload["meta"]["bars_processed"] == 5


def test_html_report_renders_zero_cost_warning_html_element():
    result = BacktestEngine(BacktestConfig()).run(_tiny_df())
    html = build_html_report(result)
    assert 'id="zero-cost-warning"' in html
    assert "COST-FREE BASELINE" in html  # literal text present in the JS renderer


def test_html_report_includes_cost_sensitivity_table_when_provided():
    result = BacktestEngine(BacktestConfig()).run(_tiny_df())
    rows = [{"cost_bps": 0, "trades": 0, "win_rate": None, "profit_factor": None, "expectancy_r": None, "max_drawdown_r": None}]
    html = build_html_report(result, cost_sensitivity=rows)
    payload = _payload_from_html(html)
    assert payload["cost_sensitivity"] == rows


def test_html_report_cost_sensitivity_empty_when_not_provided():
    result = BacktestEngine(BacktestConfig()).run(_tiny_df())
    html = build_html_report(result)
    payload = _payload_from_html(html)
    assert payload["cost_sensitivity"] == []
