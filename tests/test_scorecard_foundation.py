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
    ok = pd.DataFrame(True, index=idx, columns=["A", "B"])
    bad = ok.copy(); bad.iloc[:3, 0] = False                                   # 3 of 20 missing -> 85%
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


def test_label_available_matches_excess_return_nan_pattern():
    idx = pd.bdate_range("2024-01-02", periods=8)
    px = pd.DataFrame({"A": [1, 2, np.nan, 4, 5, 6, 7, 8.0], "B": np.arange(1, 9.0)}, index=idx)
    spy = pd.Series(np.arange(10, 18.0), index=idx)
    av = labels.label_available(px, spy, 2)
    assert av.equals(labels.excess_return(px, spy, 2).notna())


def test_bars_to_wide_and_universe_floor():
    from talonx_scorecard import panel
    days = pd.bdate_range("2024-01-02", periods=25)
    def rows(c, v):
        return [{"t": d.strftime("%Y-%m-%dT05:00:00Z"), "c": c, "v": v} for d in days]
    bars = {"BIG": rows(50.0, 1_000_000), "CHEAP": rows(4.0, 50_000_000), "THIN": rows(50.0, 1_000), "NONE": []}
    close, vol = panel.bars_to_wide(bars, "c"), panel.bars_to_wide(bars, "v")
    assert list(close.columns) == ["BIG", "CHEAP", "THIN"] and close.index[0] == days[0]
    u = panel.universe_mask(close, vol)
    assert not u.iloc[:19].any().any()                          # needs 20 sessions before entering
    assert u["BIG"].iloc[19:].all() and not u["CHEAP"].any() and not u["THIN"].any()


def test_parse_splits_ratio_and_bad_rows():
    from talonx_scorecard import panel
    p = {"corporate_actions": {"forward_splits": [{"symbol": "A", "ex_date": "2024-06-10", "new_rate": 2, "old_rate": 1}],
                               "reverse_splits": [{"symbol": "B", "ex_date": "2024-07-01", "new_rate": 1, "old_rate": 10},
                                                  {"symbol": "C", "ex_date": "2024-07-01"}]}}
    sp = {x.symbol: x.ratio for x in panel.parse_splits(p)}
    assert sp == {"A": 2.0, "B": 0.1, "C": 0.0}


def test_frame_sha256_deterministic_and_value_sensitive():
    from talonx_scorecard import panel
    idx = pd.bdate_range("2024-01-02", periods=3)
    f = pd.DataFrame({"A": [1.0, 2.0, 3.0], "B": [4.0, 5.0, 6.0]}, index=idx)
    assert panel.frame_sha256({"x": f}) == panel.frame_sha256({"x": f[["B", "A"]]})
    assert panel.frame_sha256({"x": f}) != panel.frame_sha256({"x": f.assign(A=[1.0, 2.0, 3.1])})


def _synthetic_panel(n=200, days=300, seed=3):
    from talonx_scorecard import features
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=days)
    names = [f"S{i:03d}" for i in range(n)]
    px = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, .01, (days, n)), axis=0)), index=idx, columns=names)
    raw = features.raw_price_features(px)
    for fid in ["F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"]:
        raw[fid] = pd.DataFrame(rng.normal(size=(days, n)), index=idx, columns=names)
    uni = pd.DataFrame(True, index=idx, columns=names)
    return {"raw": raw, "universe": uni}, idx, names, px


def test_price_features_known_values():
    from talonx_scorecard import features
    idx = pd.bdate_range("2023-01-02", periods=300)
    px = pd.DataFrame({"A": np.arange(1.0, 301.0)}, index=idx)
    f = features.raw_price_features(px)
    t = 280
    assert f["F1"]["A"].iloc[t] == pytest.approx(px["A"].iloc[t] / px["A"].iloc[t - 5] - 1)
    assert f["F2"]["A"].iloc[t] == pytest.approx(px["A"].iloc[t - 5] / px["A"].iloc[t - 26] - 1)
    assert f["F3"]["A"].iloc[t] == pytest.approx(px["A"].iloc[t - 21] / px["A"].iloc[t - 252] - 1)
    assert f["F4"]["A"].iloc[58:60].isna().all() or f["F4"]["A"].iloc[:59].isna().all()


def test_signed_scores_flip_sign_and_range():
    from talonx_scorecard import features
    panel, idx, names, px = _synthetic_panel()
    d = idx[-1]
    sig = features.signed_scores(panel["raw"], panel["universe"].loc[d], d)
    assert sig.shape[1] == 12 and sig.values.min() >= 0 and sig.values.max() <= 1
    f1 = panel["raw"]["F1"].loc[d]
    top = f1.idxmax()                                   # biggest 5d gain -> most bearish (reversal), sign -1
    assert sig.loc[top, "F1"] < 0.1
    f5 = panel["raw"]["F5"].loc[d]
    assert sig.loc[f5.idxmax(), "F5"] > 0.9             # quality, sign +1


def test_names_missing_more_than_six_features_are_dropped():
    from talonx_scorecard import features
    panel, idx, names, px = _synthetic_panel()
    d = idx[-1]
    for fid in ["F5", "F6", "F7", "F8", "F9", "F10", "F11"]:      # 7 missing for S000
        panel["raw"][fid].loc[d, "S000"] = np.nan
    for fid in ["F5", "F6", "F7", "F8", "F9", "F10"]:             # exactly 6 missing for S001: kept
        panel["raw"][fid].loc[d, "S001"] = np.nan
    sig = features.signed_scores(panel["raw"], panel["universe"].loc[d], d)
    assert "S000" not in sig.index and "S001" in sig.index
    assert (sig.loc["S001", ["F5", "F6"]] == C.MISSING_FILL).all()


def test_universe_excludes_names():
    from talonx_scorecard import features
    panel, idx, names, px = _synthetic_panel()
    d = idx[-1]
    row = panel["universe"].loc[d].copy(); row[["S000", "S001"]] = False
    assert not {"S000", "S001"} & set(features.signed_scores(panel["raw"], row, d).index)


def test_score_views_are_deciles_and_deterministic():
    from talonx_scorecard.score import score
    panel, idx, names, px = _synthetic_panel()
    d = idx[-1]
    out = score(panel, d)
    n = len(out)
    assert (out["view"] == "Bullish").sum() == pytest.approx(n * 0.10, abs=2)
    assert (out["view"] == "Bearish").sum() == pytest.approx(n * 0.10, abs=2)
    assert out["rank"].iloc[0] == 1.0 and out.index.is_unique
    pd.testing.assert_frame_equal(out, score(panel, d))
    assert out.loc[out["view"] == "Bullish", "composite"].min() > out.loc[out["view"] == "Bearish", "composite"].max()


def test_score_uses_only_data_up_to_the_date():
    from talonx_scorecard.score import score
    panel, idx, names, px = _synthetic_panel()
    d = idx[-40]
    base = score(panel, d)
    for k, f in panel["raw"].items():                   # corrupt everything AFTER d
        f.loc[f.index > d] = 1e9
    pd.testing.assert_frame_equal(base, score(panel, d))


def test_score_rejects_incomplete_weights():
    from talonx_scorecard.score import score
    panel, idx, names, px = _synthetic_panel()
    with pytest.raises(ValueError):
        score(panel, idx[-1], weights=pd.Series({"F1": 1.0}))


def test_price_features_never_use_future_prices():
    from talonx_scorecard import features
    _, idx, names, px = _synthetic_panel()
    d = idx[-60]
    a = features.raw_price_features(px)
    future = px.copy(); future.loc[future.index > d] = 1e9
    b = features.raw_price_features(future)
    for k in ["F1", "F2", "F3", "F4"]:
        pd.testing.assert_series_equal(a[k].loc[d], b[k].loc[d])


def test_clean_symbol_keeps_stocks_and_drops_preferreds_warrants_units():
    from talonx_scorecard.panel import clean_symbol
    assert clean_symbol(" aapl ") == "AAPL" and clean_symbol("A") == "A"
    assert clean_symbol("BRK-B") == "BRK.B" and clean_symbol("BF.B") == "BF.B"
    for bad in ["ABR-PD", "AAC-WT", "AAC-UN", "ABR-PE", "TOOLONGX", "A B", "", "123", "AB-1"]:
        assert clean_symbol(bad) is None, bad


# ---- split classification (gate 1 refinement) ----
def _cls_frame():
    idx = pd.bdate_range("2021-01-04", periods=30)
    return pd.DataFrame({"AAA": 100.0, "BBB": np.r_[np.full(15, 100.0), np.full(15, 50.0)]}, index=idx), idx


def test_classify_adjusted_missing_exdate_bar_and_out_of_sample():
    from talonx_scorecard.splits import Split, classify_splits
    df, idx = _cls_frame()
    df.loc[idx[15], "AAA"] = np.nan                       # no bar on the ex-date itself: not a failure
    rows = classify_splits(df, [Split("AAA", idx[15], 2.0), Split("AAA", pd.Timestamp("2016-01-04"), 2.0)], "2019-01-02", "2026-10-30")
    st = {r[1].year: r[2] for r in rows}
    assert st[2021] == "ADJUSTED"
    assert st[2016] == "OUT_OF_SAMPLE"


def test_classify_true_not_adjusted_still_fails():
    from talonx_scorecard.splits import Split, classify_splits
    from talonx_scorecard.gates import gate1_from_classification
    df, idx = _cls_frame()
    rows = classify_splits(df, [Split("BBB", idx[15], 2.0)], "2019-01-02", "2026-10-30")   # price halves: unadjusted
    assert rows[0][2] == "NOT_ADJUSTED"
    assert not gate1_from_classification(rows).passed


def test_gate1_strict_on_unverifiable():
    from talonx_scorecard.splits import Split, classify_splits
    from talonx_scorecard.gates import gate1_from_classification
    df, idx = _cls_frame()
    rows = classify_splits(df, [Split("AAA", idx[15], 2.0), Split("ZZZ", idx[15], 2.0)], "2019-01-02", "2026-10-30")
    assert {r[2] for r in rows} == {"ADJUSTED", "SYMBOL_MISSING"}
    assert not gate1_from_classification(rows).passed


def test_gate1_amendment1_universe_scope():
    from talonx_scorecard.splits import Split, classify_splits
    from talonx_scorecard.gates import gate1_from_classification
    df, idx = _cls_frame()
    uni = pd.DataFrame(False, index=idx, columns=df.columns)
    uni["AAA"] = True                                     # BBB (unadjusted) is outside the universe
    rows = classify_splits(df, [Split("AAA", idx[15], 2.0), Split("BBB", idx[15], 2.0), Split("ZZZ", idx[15], 2.0)],
                           "2019-01-02", "2026-10-30", universe=uni)
    assert [r[2] for r in rows] == ["ADJUSTED", "NOT_IN_UNIVERSE", "NOT_IN_UNIVERSE"]
    assert gate1_from_classification(rows).passed
    uni["BBB"] = True                                     # now in universe: the unadjusted split must fail the gate
    rows = classify_splits(df, [Split("AAA", idx[15], 2.0), Split("BBB", idx[15], 2.0)], "2019-01-02", "2026-10-30", universe=uni)
    assert not gate1_from_classification(rows).passed


def test_gate1_amendment2_factor_test_ignores_market_moves():
    from talonx_scorecard.splits import Split, classify_splits
    idx = pd.bdate_range("2021-01-04", periods=20)
    raw = pd.DataFrame({"REV": np.r_[np.full(10, 2.0), np.full(10, 12.0)],      # 1:6 reverse split, raw jumps 6x
                        "BAD": np.r_[np.full(10, 2.0), np.full(10, 12.0)]}, index=idx)
    adj = raw.copy()
    adj["REV"] = 12.0                                    # correctly back-adjusted: adj flat, factor steps by the ratio
    uni = pd.DataFrame(True, index=idx, columns=raw.columns)
    rows = classify_splits(adj, [Split("REV", idx[10], 1 / 6), Split("BAD", idx[10], 1 / 6)], "2019-01-02", "2026-10-30",
                           universe=uni, raw_close=raw)
    assert [r[2] for r in rows] == ["ADJUSTED", "NOT_ADJUSTED"]       # BAD: adj == raw, factor never moved
