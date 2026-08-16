"""
tests/test_backtest_reports.py
-----------------------------------
talonx_backtest.reports: equity_curve.csv, rejected_signals.csv,
data_quality.json, and the self-contained results.html report --
including that its embedded JSON payload is valid and matches what a
zero-trade run should (and should not) claim.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from talonx_backtest.data import check_dataset_quality
from talonx_backtest.engine import BacktestConfig, BacktestEngine, BacktestResult, RejectionRecord
from talonx_backtest.portfolio import Trade
from talonx_backtest.reports import (
    EQUITY_CURVE_FIELDS,
    build_html_report,
    data_quality_to_json,
    equity_curve_to_csv,
    rejected_signals_to_csv,
    write_report,
)
from talonx_quant.config import QuantConfig


def _build_bars():
    """Two full regular sessions (Mon/Tue) -- same fixture shape as
    test_backtest_regression.py's, duplicated locally rather than
    imported so this file stays self-contained (the `tests/` directory
    has no __init__.py, so cross-file imports between test modules
    aren't reliable across pytest invocation styles)."""
    import pandas as pd

    def session_bars(day_start, n=390, seed_price=100.0):
        bars = []
        price = seed_price
        for i in range(n):
            if i % 53 == 0 and i > 0:
                price -= 3.0
            elif i % 67 == 0 and i > 0:
                price += 3.5
            else:
                price += 0.05 if i % 2 == 0 else -0.03
            vol = 6000.0 if i % 53 == 1 else 1000.0 + (i % 5) * 50
            bars.append((day_start + timedelta(minutes=i), price, price + 0.4, price - 0.4, price, vol))
        return bars, price

    day1_start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
    day2_start = datetime(2026, 1, 6, 14, 30, tzinfo=timezone.utc)
    day1, last_price = session_bars(day1_start)
    day2, _ = session_bars(day2_start, seed_price=last_price)
    return day1 + day2


def _bars_to_df(bars, symbol="AAPL"):
    import pandas as pd

    from talonx_backtest.data import from_dataframe

    rows = [{"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v} for ts, o, h, l, c, v in bars]
    return from_dataframe(pd.DataFrame(rows), symbol=symbol)


def _dt(offset_minutes: int = 0) -> datetime:
    return datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc) + timedelta(minutes=offset_minutes)


def _trade(gross_r=1.0, net_r=0.9, exit_offset=0) -> Trade:
    return Trade(
        trade_id=f"t{exit_offset}", symbol="AAPL", direction="bullish", signal_type="rsi_oversold_volume_surge",
        session="regular", signal_timestamp=_dt(0), entry_timestamp=_dt(0), entry_price=100.0,
        stop_price=95.0, target_price=110.0, atr=1.0, risk_reward_ratio=2.0, screening_rr=2.0, execution_rr=2.0,
        confluence_score=3, opportunity_score=0.5, volume_surge_ratio=3.0, trend_alignment=True,
        exit_timestamp=_dt(exit_offset), exit_price=105.0, exit_reason="TARGET",
        gross_R=gross_r, net_R=net_r, gross_pnl=gross_r * 5, net_pnl=net_r * 5, holding_seconds=1200.0,
        mfe_price=None, mfe_pct=None, mfe_r=1.5, mae_price=None, mae_pct=None, mae_r=-0.2,
    )


def _empty_result() -> BacktestResult:
    return BacktestResult(
        trades=[], rejections=[RejectionRecord(ticker="AAPL", reason="LOW_CONFLUENCE", count=3, timestamp=_dt())],
        signals_generated=3, signals_published=0, config=BacktestConfig(),
        start=_dt(), end=_dt(60), symbols=["AAPL"],
    )


def _real_run_result() -> BacktestResult:
    import dataclasses
    config = dataclasses.replace(QuantConfig(), atr_move_multiplier=0.0, min_atr_pct=0.0)
    df = _bars_to_df(_build_bars())
    engine = BacktestEngine(BacktestConfig(quant_config=config, eod_flatten_enabled=False))
    return engine.run(df), df


# --- equity_curve.csv ---

def test_equity_curve_is_ordered_by_exit_and_cumulates_correctly():
    trades = [_trade(gross_r=1.0, net_r=0.9, exit_offset=2), _trade(gross_r=-0.5, net_r=-0.55, exit_offset=1)]
    csv_text = equity_curve_to_csv(trades)
    lines = csv_text.strip().splitlines()
    assert len(lines) == 3  # header + 2 rows
    # earlier exit (offset=1, -0.5R) should appear before offset=2 (+1.0R)
    first_row = lines[1].split(",")
    assert first_row[1] == "t1"


def test_equity_curve_is_header_only_not_empty_for_no_trades():
    # A zero-byte file is ambiguous (empty file? crashed run? really
    # zero trades?) -- a header-only CSV is not.
    csv_text = equity_curve_to_csv([])
    assert csv_text != ""
    lines = csv_text.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].split(",") == list(EQUITY_CURVE_FIELDS)


# --- rejected_signals.csv ---

def test_rejected_signals_csv_contains_every_record():
    rejections = [
        RejectionRecord(ticker="AAPL", reason="COOLDOWN", count=2, timestamp=_dt()),
        RejectionRecord(ticker="MSFT", reason="THROTTLE", count=1, timestamp=_dt(1)),
    ]
    csv_text = rejected_signals_to_csv(rejections)
    lines = csv_text.strip().splitlines()
    assert len(lines) == 3
    assert "COOLDOWN" in csv_text and "THROTTLE" in csv_text


def test_rejected_signals_csv_empty_for_no_rejections():
    assert rejected_signals_to_csv([]) == ""


# --- data_quality.json ---

def test_data_quality_json_round_trips():
    import pandas as pd
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-05 14:30", periods=5, freq="1min", tz="UTC"),
        "symbol": "AAPL", "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0,
    })
    reports = check_dataset_quality(df)
    payload = json.loads(data_quality_to_json(reports))
    assert payload["AAPL"]["rows"] == 5
    assert payload["AAPL"]["is_clean"] is True


def test_data_quality_json_empty_when_none_supplied():
    assert json.loads(data_quality_to_json(None)) == {}


# --- results.html ---

def test_html_report_embeds_valid_json_for_a_real_run():
    result, df = _real_run_result()
    quality = check_dataset_quality(df)
    html = build_html_report(result, data_quality=quality)

    assert "<title>TalonX Backtest Report</title>" in html
    start = html.index('id="payload">') + len('id="payload">')
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])

    assert payload["meta"]["trades_executed"] == len(result.trades)
    assert payload["meta"]["signals_generated"] == result.signals_generated
    assert "AAPL" in payload["data_quality"]
    assert set(payload["breakdowns"].keys()) >= {"by_symbol", "by_confluence", "by_direction"}


def test_html_report_zero_trades_does_not_fabricate_metrics():
    html = build_html_report(_empty_result())
    start = html.index('id="payload">') + len('id="payload">')
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])

    assert payload["metrics"] == {}
    assert payload["meta"]["trades_executed"] == 0
    assert payload["rejections_by_reason"] == {"LOW_CONFLUENCE": 3}


def test_html_report_never_makes_a_network_request():
    html = build_html_report(_empty_result())
    assert "http://" not in html
    assert "https://" not in html
    assert "cdn." not in html.lower()


def test_html_payload_escapes_script_close_tag_in_embedded_strings():
    result = _empty_result()
    result.rejections[0].reason = "WEIRD</script><script>alert(1)"
    html = build_html_report(result)
    # the literal "</script>" must not appear INSIDE the JSON payload span
    start = html.index('id="payload">') + len('id="payload">')
    end = html.index("</script>", start)
    raw_payload_text = html[start:end]
    assert "</script>" not in raw_payload_text
    # and the payload still parses cleanly as JSON
    json.loads(raw_payload_text)


# --- write_report (full file set) ---

def test_write_report_writes_all_eight_files(tmp_path):
    result, df = _real_run_result()
    quality = check_dataset_quality(df)
    paths = write_report(result, tmp_path, prefix="demo", data_quality=quality)

    expected_keys = {
        "trades_csv", "trades_json", "summary_json", "summary_txt",
        "equity_curve_csv", "rejected_signals_csv", "data_quality_json", "results_html",
    }
    assert set(paths.keys()) == expected_keys
    for key, path in paths.items():
        assert path.exists(), f"{key} was not written"

    assert paths["results_html"].read_text(encoding="utf-8").startswith("<!doctype html>")
    dq = json.loads(paths["data_quality_json"].read_text(encoding="utf-8"))
    assert "AAPL" in dq


def test_write_report_csv_files_have_no_spurious_blank_lines(tmp_path):
    """Regression test: csv.writer emits its own "\\r\\n" row
    terminators; without newline="" on the write_text() call, Windows'
    platform-default newline translation re-translates the "\\n" INSIDE
    that "\\r\\n" a second time (-> "\\r\\r\\n"), which readers/
    splitlines() see as an extra blank line after every single row.
    Caught originally by a stricter equity_curve.csv line-count
    assertion in test_backtest_sample_data.py; this pins the fix
    directly against write_report's own file output (the in-memory
    equity_curve_to_csv()/trades_to_csv() string builders never exhibit
    this bug -- it only happens at the write_text() step)."""
    result, df = _real_run_result()
    quality = check_dataset_quality(df)
    paths = write_report(result, tmp_path, prefix="demo", data_quality=quality)

    for key in ("trades_csv", "equity_curve_csv", "rejected_signals_csv"):
        text = paths[key].read_bytes().decode("utf-8")
        assert "\r\r\n" not in text, f"{key} has doubled CSV line terminators"
        lines = text.splitlines()
        assert all(line != "" for line in lines), f"{key} has a spurious blank line: {lines!r}"
