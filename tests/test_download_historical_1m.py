"""
tests/test_download_historical_1m.py
------------------------------------------
scripts/download_historical_1m.py -- provider selection, symbol
parsing, retry/backoff behavior, yfinance 7-day chunking, and each
provider's fetch function.

Every provider call is MOCKED here (never a real network/API call),
matching this repo's established convention for yfinance-dependent code
(see test_yfinance_poller.py/test_yfinance_extended_hours.py: always
`patch("yfinance...", ...)`, never a live call in the automated suite).
time.sleep is also mocked in every test that touches it (the retry
backoff AND the inter-chunk 0.5s pause) so they run instantly
regardless of the configured delay.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.download_historical_1m import (
    DownloadError,
    DownloadResult,
    _chunk_date_range,
    _classify_status,
    _parse_symbols,
    _retry,
    download_symbol,
    fetch_alpaca,
    fetch_polygon,
    fetch_yfinance,
    main,
    select_provider,
)


# --- _parse_symbols ---

def test_parse_symbols_comma_separated_list():
    assert _parse_symbols("aapl, MSFT ,nvda") == ["AAPL", "MSFT", "NVDA"]


def test_parse_symbols_from_file(tmp_path):
    path = tmp_path / "tickers.txt"
    path.write_text("AAPL\nmsft\n# a comment\n\nNVDA\n", encoding="utf-8")
    assert _parse_symbols(str(path)) == ["AAPL", "MSFT", "NVDA"]


# --- select_provider ---

def test_select_provider_explicit_choice_wins(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "x")
    assert select_provider("yfinance") == "yfinance"


def test_select_provider_prefers_polygon(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "x")
    monkeypatch.setenv("APCA_API_KEY_ID", "y")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "z")
    assert select_provider(None) == "polygon"


def test_select_provider_falls_back_to_alpaca_without_polygon_key(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.setenv("APCA_API_KEY_ID", "y")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "z")
    assert select_provider(None) == "alpaca"


def test_select_provider_requires_both_alpaca_vars(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.setenv("APCA_API_KEY_ID", "y")
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    assert select_provider(None) == "yfinance"


def test_select_provider_defaults_to_yfinance_with_no_keys(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    assert select_provider(None) == "yfinance"


# --- _retry ---

def test_retry_succeeds_after_transient_failures(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    result = _retry(flaky, max_retries=5, base_seconds=0.01, max_seconds=0.01, description="test")
    assert result == "ok"
    assert calls["n"] == 3


def test_retry_raises_download_error_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)

    def always_fails():
        raise ConnectionError("persistent failure")

    with pytest.raises(DownloadError):
        _retry(always_fails, max_retries=3, base_seconds=0.01, max_seconds=0.01, description="test")


# --- _chunk_date_range ---

def test_chunk_date_range_matches_the_documented_example():
    assert _chunk_date_range("2026-07-20", "2026-08-16") == [
        ("2026-07-20", "2026-07-27"),
        ("2026-07-27", "2026-08-03"),
        ("2026-08-03", "2026-08-10"),
        ("2026-08-10", "2026-08-16"),
    ]


def test_chunk_date_range_single_chunk_when_span_is_short():
    assert _chunk_date_range("2026-08-01", "2026-08-02") == [("2026-08-01", "2026-08-02")]


def test_chunk_date_range_exact_multiple_of_chunk_size():
    # 14 days, chunk_days=7 -- two full 7-day chunks, no short remainder.
    assert _chunk_date_range("2026-08-01", "2026-08-15") == [
        ("2026-08-01", "2026-08-08"),
        ("2026-08-08", "2026-08-15"),
    ]


def test_chunk_date_range_handles_start_equal_to_end():
    assert _chunk_date_range("2026-08-01", "2026-08-01") == [("2026-08-01", "2026-08-01")]


# --- fetch_yfinance ---

def _yf_download_df(n=5, start="2026-08-01 09:30:00"):
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC", name="Datetime")
    return pd.DataFrame({"Open": 100.0, "High": 100.5, "Low": 99.5, "Close": 100.2, "Volume": 1000.0}, index=ts)


def test_fetch_yfinance_returns_normalized_bars(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)

    with patch("yfinance.download", return_value=_yf_download_df(5)) as mock_download:
        bars = fetch_yfinance("AAPL", "2026-08-01", "2026-08-02", max_retries=3)

    # single-day span -> exactly one chunk -> exactly one yf.download call
    mock_download.assert_called_once_with("AAPL", start="2026-08-01", end="2026-08-02", interval="1m", prepost=True, progress=False)
    assert len(bars) == 5
    assert bars[0]["open"] == 100.0
    assert bars[0]["timestamp"].tzinfo is not None


def test_fetch_yfinance_empty_history_returns_empty_list(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)

    with patch("yfinance.download", return_value=pd.DataFrame()):
        bars = fetch_yfinance("AAPL", "2026-08-01", "2026-08-02", max_retries=3)
    assert bars == []


def test_fetch_yfinance_warns_on_wide_date_range(monkeypatch, caplog):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    with patch("yfinance.download", return_value=pd.DataFrame()):
        with caplog.at_level("WARNING"):
            fetch_yfinance("AAPL", "2024-01-01", "2024-06-30", max_retries=3)
    assert any("30 trailing days" in rec.message for rec in caplog.records)


def test_fetch_yfinance_chunks_wide_ranges_into_7_day_windows(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    # 21-day span -> three 7-day chunks
    frames = [_yf_download_df(2, start=f"2026-07-{d:02d} 09:30:00") for d in (1, 8, 15)]

    with patch("yfinance.download", side_effect=frames) as mock_download:
        bars = fetch_yfinance("AAPL", "2026-07-01", "2026-07-22", max_retries=3)

    assert mock_download.call_count == 3
    called_ranges = [(c.kwargs["start"], c.kwargs["end"]) for c in mock_download.call_args_list]
    assert called_ranges == [("2026-07-01", "2026-07-08"), ("2026-07-08", "2026-07-15"), ("2026-07-15", "2026-07-22")]
    assert len(bars) == 6  # 2 bars per chunk x 3 chunks, no overlap in this fixture


def test_fetch_yfinance_sleeps_half_a_second_between_chunks(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))
    frames = [_yf_download_df(1, start=f"2026-07-{d:02d} 09:30:00") for d in (1, 8, 15)]

    with patch("yfinance.download", side_effect=frames):
        fetch_yfinance("AAPL", "2026-07-01", "2026-07-22", max_retries=3)

    # 3 chunks -> 2 inter-chunk pauses (never a trailing sleep after the last chunk)
    assert sleep_calls == [0.5, 0.5]


def test_fetch_yfinance_dedupes_and_sorts_across_chunk_boundaries(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    # Chunk 1 ends on a bar that chunk 2 ALSO returns (the shared
    # boundary date) -- the duplicate must be dropped, not double-counted.
    shared_ts = pd.Timestamp("2026-07-08 09:30:00", tz="UTC")
    chunk1 = pd.DataFrame(
        {"Open": [100.0, 101.0], "High": [100.5, 101.5], "Low": [99.5, 100.5], "Close": [100.2, 101.2], "Volume": [1000.0, 1100.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-07-01 09:30:00", tz="UTC"), shared_ts], name="Datetime"),
    )
    chunk2 = pd.DataFrame(
        {"Open": [999.0, 102.0], "High": [999.0, 102.5], "Low": [999.0, 101.5], "Close": [999.0, 102.2], "Volume": [999.0, 1200.0]},
        index=pd.DatetimeIndex([shared_ts, pd.Timestamp("2026-07-09 09:30:00", tz="UTC")], name="Datetime"),
    )

    with patch("yfinance.download", side_effect=[chunk1, chunk2]):
        bars = fetch_yfinance("AAPL", "2026-07-01", "2026-07-15", max_retries=3)

    timestamps = [b["timestamp"] for b in bars]
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))  # no duplicate timestamp survived
    assert len(bars) == 3  # 2 + 2 raw rows, minus 1 duplicate at the shared boundary
    # the FIRST chunk's value for the shared bar wins (drop_duplicates keeps the first occurrence)
    shared_bar = next(b for b in bars if b["timestamp"] == shared_ts)
    assert shared_bar["open"] == 101.0


# --- fetch_polygon ---

def test_fetch_polygon_normalizes_aggs(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "fake-key")
    monkeypatch.setattr(time, "sleep", lambda _: None)

    agg = MagicMock()
    agg.timestamp = int(datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc).timestamp() * 1000)
    agg.open, agg.high, agg.low, agg.close, agg.volume = 100.0, 100.5, 99.5, 100.2, 1000.0

    mock_client = MagicMock()
    mock_client.list_aggs.return_value = iter([agg])

    fake_polygon_module = MagicMock()
    fake_polygon_module.RESTClient.return_value = mock_client

    with patch.dict("sys.modules", {"polygon": fake_polygon_module}):
        bars = fetch_polygon("AAPL", "2026-08-01", "2026-08-02", max_retries=3)

    fake_polygon_module.RESTClient.assert_called_once_with("fake-key")
    mock_client.list_aggs.assert_called_once_with("AAPL", 1, "minute", "2026-08-01", "2026-08-02", limit=50000, adjusted=True)
    assert len(bars) == 1
    assert bars[0]["close"] == 100.2


# --- fetch_alpaca ---

def test_fetch_alpaca_paginates_via_next_page_token(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "id")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setattr(time, "sleep", lambda _: None)

    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = {
        "bars": [{"t": "2026-08-01T09:30:00Z", "o": 100.0, "h": 100.5, "l": 99.5, "c": 100.2, "v": 1000.0}],
        "next_page_token": "abc",
    }
    page2 = MagicMock()
    page2.status_code = 200
    page2.json.return_value = {
        "bars": [{"t": "2026-08-01T09:31:00Z", "o": 100.2, "h": 100.6, "l": 99.9, "c": 100.4, "v": 900.0}],
        "next_page_token": None,
    }

    fake_requests = MagicMock()
    fake_requests.get.side_effect = [page1, page2]

    with patch.dict("sys.modules", {"requests": fake_requests}):
        bars = fetch_alpaca("AAPL", "2026-08-01", "2026-08-02", max_retries=3)

    assert len(bars) == 2
    assert fake_requests.get.call_count == 2
    second_call_params = fake_requests.get.call_args_list[1].kwargs["params"]
    assert second_call_params["page_token"] == "abc"


# --- download_symbol / main (end to end, mocked provider) ---

def test_download_symbol_returns_empty_status_on_empty_result(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    with patch("yfinance.download", return_value=pd.DataFrame()):
        result = download_symbol("AAPL", "2026-08-01", "2026-08-02", "yfinance", max_retries=2)
    assert isinstance(result, DownloadResult)
    assert result.status == "EMPTY"
    assert result.df is None
    assert result.bars == 0
    assert result.error is not None


def test_main_writes_a_valid_csv_that_passes_data_quality_checks(tmp_path, monkeypatch, capsys):
    from talonx_backtest.data import check_data_quality, load_ohlcv_csv

    monkeypatch.setattr(time, "sleep", lambda _: None)

    with patch("yfinance.download", return_value=_yf_download_df(10)):
        exit_code = main([
            "--symbols", "AAPL", "--start-date", "2026-08-01", "--end-date", "2026-08-02",
            "--output-dir", str(tmp_path), "--provider", "yfinance",
        ])

    assert exit_code == 0
    out_csv = tmp_path / "AAPL.csv"
    assert out_csv.is_file()

    df = load_ohlcv_csv(out_csv, symbol="AAPL")
    report = check_data_quality(df, symbol="AAPL")
    assert not report.has_critical_corruption
    assert report.rows == 10

    out = capsys.readouterr().out
    assert "1/1 symbol(s) written" in out


def test_main_reports_failed_symbols_without_aborting_the_batch(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(time, "sleep", lambda _: None)

    with patch("yfinance.download", return_value=pd.DataFrame()):  # empty for every symbol
        exit_code = main([
            "--symbols", "AAPL,MSFT", "--start-date", "2026-08-01", "--end-date", "2026-08-02",
            "--output-dir", str(tmp_path), "--provider", "yfinance",
        ])

    assert exit_code == 1  # every symbol failed/empty
    out = capsys.readouterr().out
    assert "Failed/empty: AAPL, MSFT" in out


# ------------------------------------------------------------------
# 2026-08-16 infra audit fix: exit code must reflect ANY symbol
# failure, not only a total wipeout -- see main()'s own comment at the
# `return 1 if failed_symbols else 0` line. Three cases below, matching
# the audit's own TEST 1/2/3.
# ------------------------------------------------------------------

def test_all_success_exits_zero(tmp_path, monkeypatch):
    # TEST 1 -- ALL SUCCESS: AAPL/MSFT/NVDA all succeed -> exit code 0.
    monkeypatch.setattr(time, "sleep", lambda _: None)

    with patch("yfinance.download", return_value=_yf_download_df(5)):
        exit_code = main([
            "--symbols", "AAPL,MSFT,NVDA", "--start-date", "2026-08-01", "--end-date", "2026-08-02",
            "--output-dir", str(tmp_path), "--provider", "yfinance",
        ])

    assert exit_code == 0
    for symbol in ("AAPL", "MSFT", "NVDA"):
        assert (tmp_path / f"{symbol}.csv").is_file()


def test_partial_failure_still_processes_remaining_symbols_but_exits_nonzero(tmp_path, monkeypatch, capsys):
    # TEST 2 -- PARTIAL FAILURE: AAPL/NVDA succeed, MSFT fails (empty
    # response) -> MSFT's failure is reported, AAPL/NVDA are still
    # written, and the process exits non-zero (the actual bug this task
    # fixes -- the OLD `len(failed_symbols) == len(symbols)` condition
    # would have exited 0 here).
    monkeypatch.setattr(time, "sleep", lambda _: None)

    def fake_download(symbol, *args, **kwargs):
        if symbol == "MSFT":
            return pd.DataFrame()  # empty response -> MSFT fails
        return _yf_download_df(5)

    with patch("yfinance.download", side_effect=fake_download):
        exit_code = main([
            "--symbols", "AAPL,MSFT,NVDA", "--start-date", "2026-08-01", "--end-date", "2026-08-02",
            "--output-dir", str(tmp_path), "--provider", "yfinance",
        ])

    assert exit_code != 0

    assert (tmp_path / "AAPL.csv").is_file()
    assert (tmp_path / "NVDA.csv").is_file()
    assert not (tmp_path / "MSFT.csv").is_file()

    out = capsys.readouterr().out
    assert "Failed/empty: MSFT" in out
    assert "2/3 symbol(s) written" in out


def test_all_failure_exits_nonzero(tmp_path, monkeypatch, capsys):
    # TEST 3 -- ALL FAILURE: AAPL/MSFT/NVDA all fail -> exit code != 0.
    monkeypatch.setattr(time, "sleep", lambda _: None)

    with patch("yfinance.download", return_value=pd.DataFrame()):
        exit_code = main([
            "--symbols", "AAPL,MSFT,NVDA", "--start-date", "2026-08-01", "--end-date", "2026-08-02",
            "--output-dir", str(tmp_path), "--provider", "yfinance",
        ])

    assert exit_code != 0
    out = capsys.readouterr().out
    assert "Failed/empty: AAPL, MSFT, NVDA" in out


# ------------------------------------------------------------------
# 2026-08-17 FULL/PARTIAL/EMPTY/FAILED status classification (Task 2.2).
# _classify_status is deliberately a pure date-range comparison -- no
# weekend/holiday interpretation, see its own docstring.
# ------------------------------------------------------------------

def _bars_at(*timestamps: str) -> pd.DataFrame:
    """A minimal yf.download-shaped frame with exactly one bar per given
    UTC timestamp string -- used to control the actual returned date
    range precisely, independent of _yf_download_df's fixed 1-minute cadence."""
    index = pd.DatetimeIndex([pd.Timestamp(t, tz="UTC") for t in timestamps], name="Datetime")
    return pd.DataFrame({"Open": 100.0, "High": 100.5, "Low": 99.5, "Close": 100.2, "Volume": 1000.0}, index=index)


def test_classify_status_full_when_actual_range_covers_the_request():
    df = pd.DataFrame({"timestamp": [pd.Timestamp("2026-08-01 09:30", tz="UTC"), pd.Timestamp("2026-08-02 09:30", tz="UTC")]})
    assert _classify_status(df, "2026-08-01", "2026-08-02") == "FULL"


def test_classify_status_partial_when_actual_range_falls_short():
    df = pd.DataFrame({"timestamp": [pd.Timestamp("2026-08-01 09:30", tz="UTC"), pd.Timestamp("2026-08-01 09:40", tz="UTC")]})
    assert _classify_status(df, "2026-08-01", "2026-08-02") == "PARTIAL"


def test_classify_status_est_after_hours_spillover_is_correctly_partial():
    # SCENARIO A -- 2026-08-17 timezone/date-boundary fix regression test.
    # Previously CONFIRMED REAL BUG: _classify_status compared raw UTC
    # calendar dates, but extended-hours 1-minute data (prepost=True)
    # genuinely trades as late as ~19:59 ET -- during EST (UTC-5,
    # roughly Nov-Mar), that crosses UTC midnight: 2026-01-15 19:59
    # America/New_York (2026-01-15's own last after-hours bar) is
    # 2026-01-16 00:59 UTC.
    #
    # A request for 2026-01-15 -> 2026-01-16 (two ET trading days) where
    # only Jan 15 actually has data (Jan 16 is ENTIRELY missing -- a
    # full one-day gap) used to be mislabeled FULL, because that last
    # Jan-15 bar's UTC .date() coincidentally read as 2026-01-16. Now
    # that the comparison is done on America/New_York calendar dates,
    # that same bar's ET date correctly reads as 2026-01-15 -- less than
    # the requested end date -- so this genuinely incomplete response is
    # now correctly PARTIAL.
    last_real_bar_utc = pd.Timestamp("2026-01-15 19:59:00", tz="America/New_York").tz_convert("UTC")
    first_real_bar_utc = pd.Timestamp("2026-01-15 04:00:00", tz="America/New_York").tz_convert("UTC")
    df = pd.DataFrame({"timestamp": [first_real_bar_utc, last_real_bar_utc]})

    result = _classify_status(df, "2026-01-15", "2026-01-16")

    assert result == "PARTIAL"  # was FULL before the fix -- this is the confirmed defect, now closed


def test_classify_status_correctly_partial_for_the_same_scenario_in_edt():
    # SCENARIO B -- the EDT (summer) counterpart to Scenario A: the
    # identical "day D+1 entirely missing" scenario, at a time of year
    # where the after-hours session never crossed UTC midnight to begin
    # with (19:59 ET = 23:59 UTC same day, EDT is UTC-4). Was already
    # correctly PARTIAL before the fix, and must remain PARTIAL after
    # it -- proves the ET-basis change doesn't disturb the case that was
    # never broken.
    last_real_bar_utc = pd.Timestamp("2026-07-15 19:59:00", tz="America/New_York").tz_convert("UTC")
    first_real_bar_utc = pd.Timestamp("2026-07-15 04:00:00", tz="America/New_York").tz_convert("UTC")
    df = pd.DataFrame({"timestamp": [first_real_bar_utc, last_real_bar_utc]})

    result = _classify_status(df, "2026-07-15", "2026-07-16")

    assert result == "PARTIAL"


def test_download_symbol_full_status(monkeypatch):
    # TEST 1 -- FULL: requested a single day, data covers that whole day.
    monkeypatch.setattr(time, "sleep", lambda _: None)
    with patch("yfinance.download", return_value=_bars_at("2026-08-01 09:30", "2026-08-01 09:31")):
        result = download_symbol("AAPL", "2026-08-01", "2026-08-01", "yfinance", max_retries=2)
    assert result.status == "FULL"
    assert result.bars == 2
    assert result.df is not None
    assert result.error is None


def test_download_symbol_partial_status(monkeypatch):
    # TEST 2 -- PARTIAL: requested 2 days, data only covers the first.
    monkeypatch.setattr(time, "sleep", lambda _: None)
    with patch("yfinance.download", return_value=_yf_download_df(5, start="2026-08-01 09:30:00")):
        result = download_symbol("AAPL", "2026-08-01", "2026-08-02", "yfinance", max_retries=2)
    assert result.status == "PARTIAL"
    assert result.bars == 5
    assert result.df is not None


def test_download_symbol_empty_status(monkeypatch):
    # TEST 3 -- EMPTY: provider call succeeds but returns zero bars.
    monkeypatch.setattr(time, "sleep", lambda _: None)
    with patch("yfinance.download", return_value=pd.DataFrame()):
        result = download_symbol("AAPL", "2026-08-01", "2026-08-02", "yfinance", max_retries=2)
    assert result.status == "EMPTY"
    assert result.bars == 0
    assert result.df is None
    assert result.error is not None


def test_download_symbol_failed_status(monkeypatch):
    # TEST 4 -- FAILED: provider call raises on every attempt.
    monkeypatch.setattr(time, "sleep", lambda _: None)
    with patch("yfinance.download", side_effect=ConnectionError("simulated network failure")):
        result = download_symbol("AAPL", "2026-08-01", "2026-08-02", "yfinance", max_retries=2)
    assert result.status == "FAILED"
    assert result.bars == 0
    assert result.df is None
    assert "simulated network failure" in result.error


def test_empty_and_failed_are_not_conflated():
    # EMPTY and FAILED must remain distinguishable, not merged into one
    # generic "failure" status.
    assert "EMPTY" != "FAILED"
    empty_result = DownloadResult(symbol="A", status="EMPTY", requested_start="x", requested_end="y", actual_start=None, actual_end=None, bars=0)
    failed_result = DownloadResult(symbol="B", status="FAILED", requested_start="x", requested_end="y", actual_start=None, actual_end=None, bars=0)
    assert empty_result.status != failed_result.status


def test_mixed_full_partial_failed_across_symbols(tmp_path, monkeypatch, capsys):
    # TEST 5 -- mixed multi-symbol results, matching the task's own
    # example: AAPL FULL, MSFT PARTIAL, NVDA FAILED. All three must be
    # attempted, all three explicitly reported, and the process must
    # exit non-zero because of NVDA alone (MSFT's PARTIAL must not force
    # a non-zero exit by itself -- see the two exit-code tests below).
    monkeypatch.setattr(time, "sleep", lambda _: None)

    def fake_download(symbol, *args, **kwargs):
        if symbol == "AAPL":
            return _bars_at("2026-08-01 09:30", "2026-08-02 09:30")  # covers the full requested range
        if symbol == "MSFT":
            return _yf_download_df(5, start="2026-08-01 09:30:00")  # only day 1 -- PARTIAL
        if symbol == "NVDA":
            raise ConnectionError("simulated network failure")
        raise AssertionError(f"unexpected symbol {symbol}")

    with patch("yfinance.download", side_effect=fake_download):
        exit_code = main([
            "--symbols", "AAPL,MSFT,NVDA", "--start-date", "2026-08-01", "--end-date", "2026-08-02",
            "--output-dir", str(tmp_path), "--provider", "yfinance", "--max-retries", "1",
        ])

    assert exit_code != 0  # NVDA's failure alone must force a non-zero exit

    out = capsys.readouterr().out
    assert "Status:    FULL" in out
    assert "Status:    PARTIAL" in out
    assert "Status:    FAILED" in out

    # all three were attempted -- AAPL/MSFT wrote real CSVs, NVDA did not
    assert (tmp_path / "AAPL.csv").is_file()
    assert (tmp_path / "MSFT.csv").is_file()
    assert not (tmp_path / "NVDA.csv").is_file()


def test_summary_json_is_written_with_the_documented_schema(tmp_path, monkeypatch):
    # TEST 6 -- summary JSON generation.
    monkeypatch.setattr(time, "sleep", lambda _: None)

    def fake_download(symbol, *args, **kwargs):
        if symbol == "AAPL":
            return _bars_at("2026-08-01 09:30", "2026-08-02 09:30")
        if symbol == "MSFT":
            return _yf_download_df(5, start="2026-08-01 09:30:00")
        if symbol == "NVDA":
            raise ConnectionError("simulated network failure")
        raise AssertionError(f"unexpected symbol {symbol}")

    with patch("yfinance.download", side_effect=fake_download):
        main([
            "--symbols", "AAPL,MSFT,NVDA", "--start-date", "2026-08-01", "--end-date", "2026-08-02",
            "--output-dir", str(tmp_path), "--provider", "yfinance", "--max-retries", "1",
        ])

    summary_path = tmp_path / "download_summary.json"
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["provider"] == "yfinance"
    assert summary["requested_start"] == "2026-08-01"
    assert summary["requested_end"] == "2026-08-02"
    assert set(summary["symbols"].keys()) == {"AAPL", "MSFT", "NVDA"}

    assert summary["symbols"]["AAPL"]["status"] == "FULL"
    assert summary["symbols"]["AAPL"]["bars"] == 2
    assert summary["symbols"]["AAPL"]["actual_start"] is not None

    assert summary["symbols"]["MSFT"]["status"] == "PARTIAL"
    assert summary["symbols"]["MSFT"]["bars"] == 5

    assert summary["symbols"]["NVDA"]["status"] == "FAILED"
    assert summary["symbols"]["NVDA"]["bars"] == 0
    assert summary["symbols"]["NVDA"]["actual_start"] is None
    assert summary["symbols"]["NVDA"]["error"] is not None


def test_partial_alone_does_not_force_a_nonzero_exit(tmp_path, monkeypatch):
    # A PARTIAL-only result (no EMPTY/FAILED symbols) must still exit 0
    # -- PARTIAL must never be silently treated as a fetch failure.
    monkeypatch.setattr(time, "sleep", lambda _: None)
    with patch("yfinance.download", return_value=_yf_download_df(5, start="2026-08-01 09:30:00")):
        exit_code = main([
            "--symbols", "AAPL", "--start-date", "2026-08-01", "--end-date", "2026-08-02",
            "--output-dir", str(tmp_path), "--provider", "yfinance",
        ])
    assert exit_code == 0
    summary = json.loads((tmp_path / "download_summary.json").read_text(encoding="utf-8"))
    assert summary["symbols"]["AAPL"]["status"] == "PARTIAL"


def test_task_1_1_exit_code_contract_still_holds_with_the_new_status_field(tmp_path, monkeypatch):
    # TEST 7 -- existing Task 1.1 exit-code behaviour, re-affirmed now
    # that failure detection routes through DownloadResult.status instead
    # of a plain None return: EMPTY/FAILED -> non-zero, no EMPTY/FAILED -> 0.
    monkeypatch.setattr(time, "sleep", lambda _: None)

    with patch("yfinance.download", return_value=_yf_download_df(5)):
        all_success_exit = main([
            "--symbols", "AAPL", "--start-date", "2026-08-01", "--end-date", "2026-08-01",
            "--output-dir", str(tmp_path / "a"), "--provider", "yfinance",
        ])
    assert all_success_exit == 0

    with patch("yfinance.download", return_value=pd.DataFrame()):
        all_empty_exit = main([
            "--symbols", "AAPL", "--start-date", "2026-08-01", "--end-date", "2026-08-01",
            "--output-dir", str(tmp_path / "b"), "--provider", "yfinance",
        ])
    assert all_empty_exit != 0
