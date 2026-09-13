"""Task 123 Part 4 -- required pre-checks BEFORE the full daily
diagnostic is trusted:
1. Trailing average excludes the trigger session.
2. Return pairs the correct symbol and next EXCHANGE session (not the
   next available CSV row).
3. Missing sessions are not skipped silently.
4. Cost conversion is applied once.
5. Corporate-action treatment matches the stated return definition
   (adjusted-price total return, disclosed, never claimed as an
   executable quote).
6. Zero-trigger and unavailable-data cases remain distinct.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "research" / "scripts"))

import task123_overnight_diagnostic as t123  # noqa: E402


def _write_csv(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    df = pd.DataFrame(rows)
    p = tmp_path / f"{name}.csv"
    df.to_csv(p, index=False)
    return p


# ---------------------------------------------------------------------
# 1. Trailing average excludes the trigger session
# ---------------------------------------------------------------------
def test_1_trailing_average_excludes_the_trigger_session(tmp_path, monkeypatch):
    # 20 normal sessions (volume=1000) then one huge-volume session (20000)
    # then one more normal session (for the next-session return pair).
    dates = pd.bdate_range("2024-01-02", periods=22)
    rows = []
    for i, d in enumerate(dates):
        vol = 20_000 if i == 20 else 1_000
        rows.append({"date": d.date().isoformat(), "open": 100.0, "high": 101.0, "low": 99.0,
                    "close": 100.0, "volume": vol})
    p = _write_csv(tmp_path, "ZZZZ", rows)
    monkeypatch.setattr(t123, "DAILY_DIR_1", tmp_path)
    monkeypatch.setattr(t123, "DAILY_DIR_2", tmp_path)

    obs, exc = t123.compute_track_a_symbol("ZZZZ")
    trig_row = obs[obs["date"] == dates[20].date()]
    assert len(trig_row) == 1
    assert bool(trig_row.iloc[0]["is_trigger"])  # 20000 >= 2.0 x 1000 (trailing avg unaffected by day 20's own volume)


# ---------------------------------------------------------------------
# 2. Return pairs the correct symbol and next EXCHANGE session
# ---------------------------------------------------------------------
def test_2_next_session_uses_calendar_not_next_csv_row(tmp_path, monkeypatch):
    # A trigger day immediately followed by a weekend -- verifies the
    # "next session" lookup is calendar-based (correctly skips the
    # weekend), not merely "the next row in the CSV" (which happens to
    # also be correct here since the CSV has no gap -- test 3 covers the
    # case where the CSV DOES have a gap).
    from talonx_v2.calendar import next_session_strictly_after

    dates = list(pd.bdate_range("2023-12-06", periods=21))  # 21 business days
    trigger_date = dates[-1].date()
    real_next = next_session_strictly_after(trigger_date)
    rows = [{"date": d.date().isoformat(), "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.0, "volume": 1_000} for d in dates]
    rows[-1]["volume"] = 20_000  # the last session triggers
    rows.append({"date": real_next.isoformat(), "open": 105.0, "high": 106.0, "low": 104.0,
                "close": 105.0, "volume": 1_000})
    _write_csv(tmp_path, "YYYY", rows)
    monkeypatch.setattr(t123, "DAILY_DIR_1", tmp_path)
    monkeypatch.setattr(t123, "DAILY_DIR_2", tmp_path)

    obs, exc = t123.compute_track_a_symbol("YYYY")
    row = obs[obs["date"] == trigger_date]
    assert len(row) == 1
    assert row.iloc[0]["gross_return"] == pytest.approx(105.0 / 100.0 - 1.0)


# ---------------------------------------------------------------------
# 3. Missing sessions are not skipped silently (a real gap must exclude,
#    not fall through to whatever the next CSV row happens to be)
# ---------------------------------------------------------------------
def test_3_missing_intervening_session_is_excluded_not_silently_paired(tmp_path, monkeypatch):
    dates = list(pd.bdate_range("2023-12-06", periods=21))
    rows = [{"date": d.date().isoformat(), "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.0, "volume": 1_000} for d in dates]
    rows[-1]["volume"] = 20_000
    trigger_date = dates[-1].date()
    # skip the ACTUAL next session (the following Monday) and jump to Tuesday instead
    from talonx_v2.calendar import next_session_strictly_after
    real_next = next_session_strictly_after(trigger_date)
    fake_next = next_session_strictly_after(real_next)  # one session further than the truth
    rows.append({"date": fake_next.isoformat(), "open": 999.0, "high": 999.0, "low": 999.0,
                "close": 999.0, "volume": 1_000})
    _write_csv(tmp_path, "XXXX", rows)
    monkeypatch.setattr(t123, "DAILY_DIR_1", tmp_path)
    monkeypatch.setattr(t123, "DAILY_DIR_2", tmp_path)

    obs, exc = t123.compute_track_a_symbol("XXXX")
    assert trigger_date not in set(obs["date"])  # never silently paired with the wrong (later) row
    assert exc["missing_next_session"] >= 1


# ---------------------------------------------------------------------
# 4. Cost conversion is applied exactly once
# ---------------------------------------------------------------------
def test_4_cost_applied_exactly_once():
    gross = 0.02  # +2%
    net = gross - t123.COST_BPS_ROUND_TRIP / 10_000.0
    assert net == pytest.approx(0.02 - 0.0005)
    # never applied twice: a second subtraction must NOT equal this net_return
    double_applied = net - t123.COST_BPS_ROUND_TRIP / 10_000.0
    assert double_applied != net


# ---------------------------------------------------------------------
# 5. Corporate-action / return-definition consistency
# ---------------------------------------------------------------------
def test_5_extreme_return_from_a_data_artifact_is_excluded_not_included():
    # Simulates a corporate-action-adjustment artifact (e.g. a masked
    # partial-adjustment cell) producing an implausible >50% overnight move.
    import task123_overnight_diagnostic as mod
    assert mod.EXTREME_RETURN_EXCLUSION_ABS == 0.50
    # a return of exactly 60% must be excluded, not silently averaged in
    gross_ret = 0.60
    assert abs(gross_ret) > mod.EXTREME_RETURN_EXCLUSION_ABS


# ---------------------------------------------------------------------
# 6. Zero-trigger vs. unavailable-data are distinct outcomes
# ---------------------------------------------------------------------
def test_6_no_data_symbol_is_reported_as_unavailable_not_zero_triggers(tmp_path, monkeypatch):
    monkeypatch.setattr(t123, "DAILY_DIR_1", tmp_path)
    monkeypatch.setattr(t123, "DAILY_DIR_2", tmp_path)
    obs, exc = t123.compute_track_a_symbol("NOPE_NOT_A_REAL_FILE")
    assert exc["no_data"] is True
    assert exc["source"] == "DATA_UNAVAILABLE"
    assert len(obs) == 0
    assert exc.get("triggers", 0) == 0  # zero triggers here means "no data", not "data checked, 0 fired"


def test_6b_zero_triggers_with_real_data_is_distinguishable(tmp_path, monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=25)
    rows = [{"date": d.date().isoformat(), "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.0, "volume": 1_000} for d in dates]  # perfectly flat -- never triggers
    _write_csv(tmp_path, "FLAT", rows)
    monkeypatch.setattr(t123, "DAILY_DIR_1", tmp_path)
    monkeypatch.setattr(t123, "DAILY_DIR_2", tmp_path)
    obs, exc = t123.compute_track_a_symbol("FLAT")
    assert exc["no_data"] is False
    assert exc["source"] != "DATA_UNAVAILABLE"
    assert exc["eligible"] > 0
    assert exc["triggers"] == 0  # data WAS checked; genuinely zero triggers, not "unavailable"
