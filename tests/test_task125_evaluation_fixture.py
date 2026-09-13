"""Task 125 Part 5 -- deterministic fixture test for
task125_overnight_evaluation.compute_symbol, run BEFORE this task's real
acquired data is evaluated. Verifies the transformation/accounting is
correct on synthetic, hand-computable 1-min bars: trigger detection from
same-time-of-day cumulative volume, entry-after-delay reference price,
next-session-open reference exit, cost applied once, and that missing
entry/next-open bars are excluded rather than fabricated.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "research" / "scripts"))

import task125_overnight_evaluation as t125  # noqa: E402
from talonx_v2.calendar import next_session_strictly_after  # noqa: E402


def _session_bars(d, *, open_px=100.0, cutoff_vol=1_000, entry_px=None):
    """One session's minimal required bars: regular open (14:30 UTC,
    sets next-open reference for whoever's PRIOR session this becomes),
    one bar inside the cutoff window (carries the day's cutoff-cumulative
    volume), and the entry-observation bar (20:52 UTC)."""
    entry_px = entry_px if entry_px is not None else open_px
    return [
        {"timestamp": f"{d}T14:30:00Z", "open": open_px, "high": open_px, "low": open_px, "close": open_px, "volume": cutoff_vol},
        {"timestamp": f"{d}T20:52:00Z", "open": entry_px, "high": entry_px, "low": entry_px, "close": entry_px, "volume": 100},
    ]


def _write(tmp_path: Path, sym: str, rows: list[dict]) -> Path:
    df = pd.DataFrame(rows)
    p = tmp_path / f"{sym}.csv"
    df.to_csv(p, index=False)
    return p


def test_trigger_fires_and_uses_correct_entry_and_exit_prices(tmp_path):
    dates = list(pd.bdate_range("2024-01-02", periods=22))
    rows = []
    for i, d in enumerate(dates[:21]):
        dd = d.date().isoformat()
        vol = 20_000 if i == 20 else 1_000  # session 21 (index 20) triggers: 20000 >= 2x trailing(1000)
        rows.extend(_session_bars(dd, cutoff_vol=vol, entry_px=142.0 if i == 20 else 100.0))
    # next session's own open bar (the reference exit price)
    next_d = next_session_strictly_after(dates[20].date())
    rows.append({"timestamp": f"{next_d.isoformat()}T14:30:00Z", "open": 150.5, "high": 150.5,
                "low": 150.5, "close": 150.5, "volume": 500})
    _write(tmp_path, "FIX1", rows)

    obs, exc = t125.compute_symbol("FIX1", data_dir=tmp_path, window=("2024-01-01", "2024-03-01"))
    trig_row = obs[obs["is_trigger"]]
    assert len(trig_row) == 1
    row = trig_row.iloc[0]
    assert row["entry_price_reference_fill"] == pytest.approx(142.0)
    assert row["exit_price_reference_fill"] == pytest.approx(150.5)
    expected_gross = 150.5 / 142.0 - 1.0
    assert row["gross_return"] == pytest.approx(expected_gross)
    # cost applied EXACTLY once
    assert row["net_return"] == pytest.approx(expected_gross - t125.COST_BPS_ROUND_TRIP / 10_000.0)
    assert exc["triggers"] == 1
    assert exc["eligible"] >= 1


def test_missing_entry_bar_is_excluded_not_fabricated(tmp_path):
    dates = list(pd.bdate_range("2024-01-02", periods=22))
    rows = []
    for i, d in enumerate(dates[:21]):
        dd = d.date().isoformat()
        vol = 20_000 if i == 20 else 1_000
        bars = _session_bars(dd, cutoff_vol=vol)
        if i == 20:
            bars = [b for b in bars if "20:52:00" not in b["timestamp"]]  # drop the entry bar on the trigger day
        rows.extend(bars)
    next_d = next_session_strictly_after(dates[20].date())
    rows.append({"timestamp": f"{next_d.isoformat()}T14:30:00Z", "open": 150.5, "high": 150.5,
                "low": 150.5, "close": 150.5, "volume": 500})
    _write(tmp_path, "FIX2", rows)

    obs, exc = t125.compute_symbol("FIX2", data_dir=tmp_path, window=("2024-01-01", "2024-03-01"))
    assert dates[20].date() not in set(obs["date"]) if len(obs) else True
    assert exc["missing_entry_bar"] >= 1


def test_missing_next_session_open_is_excluded_not_fabricated(tmp_path):
    dates = list(pd.bdate_range("2024-01-02", periods=21))  # NO next-session bar appended at all
    rows = []
    for i, d in enumerate(dates):
        dd = d.date().isoformat()
        vol = 20_000 if i == 20 else 1_000
        rows.extend(_session_bars(dd, cutoff_vol=vol, entry_px=142.0 if i == 20 else 100.0))
    _write(tmp_path, "FIX3", rows)

    obs, exc = t125.compute_symbol("FIX3", data_dir=tmp_path, window=("2024-01-01", "2024-03-01"))
    assert dates[20].date() not in set(obs["date"]) if len(obs) else True
    assert exc["missing_next_session"] >= 1


def test_no_data_file_is_reported_distinctly(tmp_path):
    obs, exc = t125.compute_symbol("NOPE", data_dir=tmp_path, window=("2024-01-01", "2024-03-01"))
    assert exc["no_data"] is True
    assert len(obs) == 0


def test_extreme_return_guard_excludes_split_like_jump(tmp_path):
    dates = list(pd.bdate_range("2024-01-02", periods=21))
    rows = []
    for i, d in enumerate(dates):
        dd = d.date().isoformat()
        vol = 20_000 if i == 20 else 1_000
        rows.extend(_session_bars(dd, cutoff_vol=vol, entry_px=142.0 if i == 20 else 100.0))
    next_d = next_session_strictly_after(dates[20].date())
    # a 90% overnight drop -- simulates a raw/unadjusted 10:1 split discontinuity
    rows.append({"timestamp": f"{next_d.isoformat()}T14:30:00Z", "open": 14.2, "high": 14.2,
                "low": 14.2, "close": 14.2, "volume": 500})
    _write(tmp_path, "FIX4", rows)

    obs, exc = t125.compute_symbol("FIX4", data_dir=tmp_path, window=("2024-01-01", "2024-03-01"))
    assert dates[20].date() not in set(obs["date"]) if len(obs) else True
    assert exc["extreme_return_excluded"] >= 1
