"""TICKER_SCORECARD_V1 foundation: locked spec, labels, purged segments, data gates."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from talonx_scorecard import config as C
from talonx_scorecard import gates, labels
from talonx_scorecard.splits import Split, check_split_adjustment


def _sessions(start="2019-01-02", end="2026-10-30"):
    return pd.bdate_range(start, end)


def test_spec_fingerprint_is_stable_and_sensitive(monkeypatch):
    a = C.spec_fingerprint()
    assert a == C.spec_fingerprint()
    monkeypatch.setattr(C, "RIDGE_ALPHA", 2.0)
    assert C.spec_fingerprint() != a


def test_twelve_features_unique_ids():
    assert [f.id for f in C.FEATURES] == [f"F{i}" for i in range(1, 13)]


def test_excess_return_known_values():
    idx = pd.bdate_range("2024-01-02", periods=5)
    px = pd.DataFrame({"A": [100, 110, 121, 121, 121.0]}, index=idx)
    spy = pd.Series([100, 100, 100, 100, 100.0], index=idx)
    out = labels.excess_return(px, spy, 2)
    assert out["A"].iloc[0] == pytest.approx(0.21)
    assert out["A"].iloc[-2:].isna().all()


def test_excess_return_rejects_misaligned_index():
    idx = pd.bdate_range("2024-01-02", periods=5)
    with pytest.raises(ValueError):
        labels.excess_return(pd.DataFrame({"A": range(5)}, index=idx), pd.Series(range(4), index=idx[:4]), 1)


def test_weekly_rank_dates_one_per_week_and_last_session():
    s = _sessions("2024-01-01", "2024-03-29")
    rd = labels.rank_dates(s, "1M")
    assert len(rd) == len(set(zip(rd.isocalendar().year, rd.isocalendar().week)))
    assert (rd.dayofweek == 4).sum() >= len(rd) - 2          # Fridays except holiday-shortened weeks
    assert len(labels.rank_dates(s, "1D")) == len(s)


@pytest.mark.parametrize("h", list(C.HORIZONS))
def test_segments_are_purged_and_disjoint(h):
    s = _sessions()
    n = C.HORIZONS[h]
    tr = labels.segment_rank_dates(s, h, "TRAIN")
    va = labels.segment_rank_dates(s, h, "VALIDATE")
    ho = labels.segment_rank_dates(s, h, "HOLDOUT")
    pos = {d: i for i, d in enumerate(s)}
    assert pos[tr[-1]] + n < pos[va[0]] or pos[tr[-1]] + n < s.searchsorted(pd.Timestamp(C.SEGMENTS["VALIDATE"][0]))
    assert tr[-1] + pd.offsets.BDay(n) < pd.Timestamp(C.SEGMENTS["VALIDATE"][0]) + pd.offsets.BDay(0) or n == 1
    assert va[-1] < ho[0] and tr[-1] < va[0]
    # label windows never reach the next segment
    assert s[pos[tr[-1]] + n] < pd.Timestamp(C.SEGMENTS["VALIDATE"][0])
    assert s[pos[va[-1]] + n] < pd.Timestamp(C.SEGMENTS["HOLDOUT"][0])
    assert ho[-1] <= pd.Timestamp(C.SEGMENTS["HOLDOUT"][1])


def test_split_check_accepts_adjusted_and_rejects_raw():
    idx = pd.bdate_range("2024-01-02", periods=10)
    ex = idx[5]
    adjusted = pd.Series(np.linspace(50, 52, 10), index=idx)                # smooth through the split
    raw = adjusted.copy(); raw.iloc[5:] = raw.iloc[5:] / 2                   # 2-for-1 not adjusted: price halves
    sp = [Split("AAA", ex, 2.0)]
    assert check_split_adjustment(pd.DataFrame({"AAA": adjusted}), sp).ok
    bad = check_split_adjustment(pd.DataFrame({"AAA": raw}), sp)
    assert not bad.ok and bad.failures[0][2] == "NOT_ADJUSTED"


def test_split_check_reverse_split_and_missing_cases():
    idx = pd.bdate_range("2024-01-02", periods=10)
    raw = pd.Series([2.0] * 5 + [20.0] * 5, index=idx)                      # 1-for-10 reverse, unadjusted
    assert not check_split_adjustment(pd.DataFrame({"R": raw}), [Split("R", idx[5], 0.1)]).ok
    fails = check_split_adjustment(pd.DataFrame({"R": raw}), [Split("X", idx[5], 2.0), Split("R", idx[0], 2.0),
                                                              Split("R", pd.Timestamp("2030-01-01"), 2.0)])
    assert [f[2] for f in fails.failures] == ["SYMBOL_MISSING", "NO_PRIOR_BAR", "EX_DATE_MISSING"]


def test_gate1_fails_with_no_known_splits():
    assert not gates.gate1_split_adjustment(pd.DataFrame({"A": [1.0, 2.0]}), []).passed


def test_gate2_label_coverage_threshold():
    idx = pd.bdate_range("2024-01-02", periods=10)
    uni = pd.DataFrame(True, index=idx, columns=["A", "B"])
    ok = pd.DataFrame(1.0, index=idx, columns=["A", "B"])
    bad = ok.copy(); bad.iloc[:3, 0] = np.nan                                  # 3 of 20 missing -> 85%
    assert gates.gate2_label_coverage(uni, {"1M": ok}).passed
    r = gates.gate2_label_coverage(uni, {"1M": ok, "3M": bad})
    assert not r.passed and "3M" in r.detail


def test_gate3_fundamental_coverage_threshold():
    idx = pd.bdate_range("2024-01-02", periods=10)
    uni = pd.DataFrame(True, index=idx, columns=["A", "B"])
    have = pd.DataFrame(True, index=idx, columns=["A", "B"]); have.iloc[:5, 1] = False   # 75%
    assert not gates.gate3_fundamental_coverage(uni, have).passed
    assert gates.gate3_fundamental_coverage(uni, pd.DataFrame(True, index=idx, columns=["A", "B"])).passed


def test_gate4_catches_values_published_after_the_close():
    rec = pd.DataFrame({
        "rank_date": ["2024-05-01", "2024-05-01"],
        "available_at": pd.to_datetime(["2024-05-01 19:59:00+00:00", "2024-05-01 21:12:00+00:00"]),  # 15:59 ET, 17:12 ET
    })
    r = gates.gate4_no_lookahead(rec)
    assert not r.passed and r.value == 1.0
    assert gates.gate4_no_lookahead(rec.iloc[:1]).passed
    naive = rec.assign(available_at=pd.to_datetime(["2024-05-01 10:00", "2024-05-01 11:00"]))
    assert not gates.gate4_no_lookahead(naive).passed
    assert not gates.gate4_no_lookahead(rec.iloc[0:0]).passed


def test_all_passed_requires_exactly_four():
    ok = gates.GateResult("x", True, 1.0, 1.0)
    assert gates.all_passed([ok] * 4) and not gates.all_passed([ok] * 3)
