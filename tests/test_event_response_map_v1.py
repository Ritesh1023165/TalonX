"""EVENT_RESPONSE_MAP_V1 design lock -- synthetic-fixture tests only (no network, no real prices)."""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date, datetime, timedelta, timezone


import numpy as np
import pandas as pd
import pytest

from research.common import locked_range_guard as G
from research.event_response_map_v1 import data as D, events as E, metrics as M, universe as U

UTC = timezone.utc
OFF_HOURS = lambda: datetime(2026, 10, 3, 2, 0, tzinfo=UTC)         # noqa: E731  (Saturday)


def sessions(n=60, start=date(2019, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def guard(tmp_path):
    return G.LockedRangeGuard(G.EVENT_RESPONSE_MAP_V1, root=tmp_path)


# ------------------------------------------------------------------------------------------------ guard / download
@pytest.mark.parametrize("s,e", [("2024-06-01", "2024-09-02"), ("2024-10-21", "2024-12-20"),
                                 ("2023-01-01", "2024-01-02"), ("2025-01-02", "2026-09-30")])
def test_downloader_refuses_locked_ranges_before_any_request(tmp_path, s, e):
    calls = []
    dl = D.Downloader(tmp_path / "a", {}, guard=guard(tmp_path), clock=OFF_HOURS, opener=calls.append, sleep=lambda x: None)
    with pytest.raises(G.HoldoutViolation):
        dl.pass_(["AAA"], purpose="RETURNS", start=s, end=e)
    assert calls == []


def test_downloader_refuses_market_hours(tmp_path):
    calls = []
    dl = D.Downloader(tmp_path / "a", {}, guard=guard(tmp_path), clock=lambda: datetime(2026, 10, 1, 15, 0, tzinfo=UTC),
                      opener=calls.append, sleep=lambda x: None)
    with pytest.raises(D.MarketHoursRefusal):
        dl.pass_(["AAA"], purpose="RETURNS")
    assert calls == []


@pytest.mark.parametrize("utc,blocked", [
    # EDT (UTC-4): block 13:00-20:30Z
    (datetime(2026, 10, 1, 12, 59, tzinfo=UTC), False), (datetime(2026, 10, 1, 13, 0, tzinfo=UTC), True),
    (datetime(2026, 10, 1, 20, 29, tzinfo=UTC), True), (datetime(2026, 10, 1, 20, 30, tzinfo=UTC), False),
    # EST (UTC-5) after DST ends 2026-11-01: block 14:00-21:30Z -- a fixed-UTC rule would get these wrong
    (datetime(2026, 11, 2, 13, 30, tzinfo=UTC), False), (datetime(2026, 11, 2, 14, 0, tzinfo=UTC), True),
    (datetime(2026, 11, 2, 21, 0, tzinfo=UTC), True), (datetime(2026, 11, 2, 21, 30, tzinfo=UTC), False),
    # weekend in New York (Saturday) and Friday-evening UTC that is still Friday in New York
    (datetime(2026, 10, 3, 15, 0, tzinfo=UTC), False), (datetime(2026, 10, 2, 19, 0, tzinfo=UTC), True),
    # Monday 01:00Z is Sunday evening in New York -> allowed
    (datetime(2026, 10, 5, 1, 0, tzinfo=UTC), False),
])
def test_r5_off_hours_guard_is_new_york_time_and_dst_aware(utc, blocked):
    assert D.market_hours_blocked(utc) is blocked


def test_adjustment_per_purpose_and_benchmarks_never_raw():
    assert D.request_params(["AAA"], "2019-01-02", "2019-02-01", purpose="RETURNS")["adjustment"] == "all"
    assert D.request_params(["AAA"], "2019-01-02", "2019-02-01", purpose="ELIGIBILITY_ONLY")["adjustment"] == "raw"
    with pytest.raises(ValueError):
        D.request_params(["AAA", "SPY"], "2019-01-02", "2019-02-01", purpose="ELIGIBILITY_ONLY")
    with pytest.raises(ValueError):
        D.request_params(["AAA"], "2019-01-02", "2019-02-01", purpose="OTHER")


def _body(bars, token=None):
    return json.dumps({"bars": bars, "next_page_token": token}).encode()


def test_archive_roundtrip_paging_manifest_and_duplicate_removal(tmp_path):
    pages = [_body({"AAA": [{"t": "2019-01-02T05:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 10}]}, "p2"),
             _body({"AAA": [{"t": "2019-01-03T05:00:00Z", "o": 2, "h": 2, "l": 2, "c": 2, "v": 10},
                            {"t": "2019-01-03T05:00:00Z", "o": 9, "h": 9, "l": 9, "c": 9, "v": 10}],
                    "BBB": [{"t": "2019-01-03T05:00:00Z", "o": 3, "h": 3, "l": 3, "c": 3, "v": 10}]})]
    seen = []
    dl = D.Downloader(tmp_path / "a", {}, guard=guard(tmp_path), clock=OFF_HOURS,
                      opener=lambda req: (seen.append(req.full_url), pages[len(seen) - 1])[1], sleep=lambda x: None)
    dl.pass_(["AAA", "BBB"], purpose="RETURNS")
    assert len(seen) == 2 and "adjustment=all" in seen[0] and "page_token=p2" in seen[1]
    man = json.loads((tmp_path / "a" / "manifest.json").read_text())
    assert [f["sha256"] for f in man["files"]] == [hashlib.sha256(p).hexdigest() for p in pages]
    df, dq = D.load(tmp_path / "a", purpose="RETURNS", guard=guard(tmp_path))
    assert dq["duplicate_symbol_sessions_removed"] == 1
    assert set(zip(df["symbol"], df["date"])) == {("AAA", date(2019, 1, 2)), ("BBB", date(2019, 1, 3))}


def test_load_refuses_locked_rows_and_corrupted_archive(tmp_path):
    arch = tmp_path / "a"
    arch.mkdir()
    body = _body({"AAA": [{"t": "2023-12-29T05:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
                          {"t": "2024-07-01T05:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]})
    (arch / "f.json.gz").write_bytes(gzip.compress(body))
    (arch / "manifest.json").write_text(json.dumps({"files": [{"file": "f.json.gz", "purpose": "RETURNS",
                                                               "sha256": hashlib.sha256(body).hexdigest()}]}))
    with pytest.raises(G.HoldoutViolation):
        D.load(arch, purpose="RETURNS", guard=guard(tmp_path))
    (arch / "manifest.json").write_text(json.dumps({"files": [{"file": "f.json.gz", "purpose": "RETURNS", "sha256": "0"}]}))
    with pytest.raises(G.HoldoutViolation):
        D.load(arch, purpose="RETURNS", guard=guard(tmp_path))


# ------------------------------------------------------------------------------------------------ universe
def _raw(sym, ss, close=10.0, vol=3_000_000):
    return pd.DataFrame({"symbol": sym, "date": ss, "close": close, "volume": vol})


def test_eligibility_uses_only_d_minus_1_and_requires_20_consecutive_sessions():
    ss = sessions(30)
    raw = _raw("AAA", ss)
    el = U.eligibility(raw, ss)
    assert el["date"].min() == ss[20]                            # first D with 20 prior sessions
    assert el.set_index("date").loc[ss[20], "bucket"] == "L1"    # $30M ADV
    bumped = raw.copy()
    bumped.loc[bumped["date"] == ss[25], "close"] = 1.0          # change D's own bar
    a = U.eligibility(raw, ss).set_index("date").loc[ss[25]]
    b = U.eligibility(bumped, ss).set_index("date").loc[ss[25]]
    assert a.equals(b)                                           # D's data never affects D
    gap = raw[raw["date"] != ss[10]]
    assert ss[21] not in set(U.eligibility(gap, ss)["date"])     # a missing session breaks the 20-session window


def test_eligibility_thresholds_and_buckets():
    ss = sessions(25)
    el = pd.concat([U.eligibility(_raw("P", ss, close=4.99), ss), U.eligibility(_raw("Q", ss, vol=1_000_000), ss),
                    U.eligibility(_raw("R", ss, close=100.0, vol=2_000_000), ss),
                    U.eligibility(_raw("S", ss, close=100.0, vol=20_000_000), ss)]).set_index("symbol")
    assert not el.loc["P", "eligible"].any() and not el.loc["Q", "eligible"].any()
    assert set(el.loc["R", "bucket"]) == {"L3"} or set(el.loc["R", "bucket"]) == {"L2"}
    assert U.bucket(20_000_000) == "L1" and U.bucket(100_000_000) == "L2" and U.bucket(1e9) == "L3"
    assert U.bucket(19_999_999) is None and set(el.loc["S", "bucket"]) == {"L3"}


def test_candidates_union_and_cik_mapping_prefers_rename_chain():
    c = U.candidates({"NEW", "AAA"}, {"OLD"}, {"ACQ"}, {"OLD", "SPXQ"})
    assert c["OLD"] == ["B", "D"] and c["ACQ"] == ["C"] and "SPXQ" in c
    m = U.map_ciks(c, {"NEW": 111, "OLD": 999, "AAA": 222}, [{"old_symbol": "OLD", "new_symbol": "NEW"}],
                   {"ACQ": "Acme Widgets, Inc."}, [("ACME WIDGETS INC", "333"), ("ACME WIDGETS CORP", "333")])
    assert m["OLD"] == ("0000000111", "RENAME_CHAIN")             # recycled ticker 'OLD' (999) is NOT used
    assert m["ACQ"] == ("0000000333", "UNIQUE_NAME_MATCH")
    assert m["SPXQ"] == (None, "UNMAPPED")
    amb = U.map_ciks({"X": ["C"]}, {}, [], {"X": "Foo Inc"}, [("FOO INC", "1"), ("FOO CORP", "2")])
    assert amb["X"] == (None, "UNMAPPED")                         # ambiguous name -> unmapped


# ------------------------------------------------------------------------------------------------ events / entry
def test_entry_session_strictly_after_causal_instant():
    ss = sessions(10, date(2019, 3, 4))                            # Mon 2019-03-04 (EST)
    et = E.ET
    at = lambda d, h, m: datetime(d.year, d.month, d.day, h, m, tzinfo=et).astimezone(UTC)  # noqa: E731
    assert E.entry_session(at(ss[0], 8, 0), ss) == ss[0]           # pre-open -> same day open
    assert E.entry_session(at(ss[0], 9, 30), ss) == ss[1]          # exactly at the open -> not strictly after
    assert E.entry_session(at(ss[0], 12, 0), ss) == ss[1]
    assert E.entry_session(at(ss[0], 16, 5), ss) == ss[1]          # after the close -> next session
    assert E.entry_session(at(date(2019, 3, 9), 10, 0), ss) == date(2019, 3, 11)   # Saturday -> Monday


def test_edgar_acceptance_conservative_dual_interpretation():
    c = E.edgar_acceptance_causal("2019-03-04T08:00:00.000Z")
    assert c == datetime(2019, 3, 4, 13, 0, tzinfo=UTC)            # later of 08:00Z and 08:00 ET
    ss = sessions(5, date(2019, 3, 4))
    assert E.entry_session(c, ss) == ss[0]                         # 08:00 ET still before the 09:30 open


def test_gap_events_nested_and_enter_next_session():
    ss = sessions(5)
    bars = pd.DataFrame({"symbol": "AAA", "date": ss, "open": [10, 11.2, 10, 9.4, 10],
                         "close": [10, 10, 10, 10, 10]})
    ev = E.gap_events(bars, ss)
    assert set(ev[ev["event_date"] == ss[1]]["event_type"]) == {"GAP_UP_3", "GAP_UP_5", "GAP_UP_10"}
    assert set(ev[ev["event_date"] == ss[3]]["event_type"]) == {"GAP_DOWN_3", "GAP_DOWN_5"}
    assert (ev["entry_date"] == ev["event_date"].map({ss[i]: ss[i + 1] for i in range(4)})).all()
    no_prev = bars[bars["date"] != ss[0]]
    assert ss[1] not in set(E.gap_events(no_prev, ss)["event_date"])   # needs the previous MARKET session's close


def test_eight_k_rules():
    ss = sessions(40)
    f = pd.DataFrame([
        {"cik": "1", "form": "8-K", "filingDate": "2019-01-03", "acceptanceDateTime": "2019-01-03T16:30:00.000Z", "items": "2.02,9.01"},
        {"cik": "1", "form": "8-K/A", "filingDate": "2019-01-04", "acceptanceDateTime": "2019-01-04T10:00:00.000Z", "items": "2.02"},
        {"cik": "1", "form": "8-K", "filingDate": "2024-01-04", "acceptanceDateTime": "2024-01-04T10:00:00.000Z", "items": "8.01"},
        {"cik": "2", "form": "8-K", "filingDate": "2019-01-07", "acceptanceDateTime": "2019-01-07T10:00:00.000Z", "items": "1.01,5.02"},
    ])
    ev = E.eight_k_events(f, {"0000000001": "AAA", "0000000002": "BBB"}, ss)
    assert sorted(ev["event_type"]) == ["8K_1.01", "8K_2.02", "8K_5.02"]
    assert ev[ev["symbol"] == "AAA"]["entry_date"].iloc[0] == date(2019, 1, 4)   # 16:30 -> next session


def test_outcomes_horizons_relative_returns_and_integrity():
    ss = sessions(40)
    px = pd.DataFrame({"symbol": "AAA", "date": ss, "open": 10.0, "close": [10.0 + 0.1 * i for i in range(40)]})
    spy = pd.DataFrame({"symbol": "SPY", "date": ss, "open": 100.0, "close": 101.0})
    xlk = pd.DataFrame({"symbol": "XLK", "date": ss, "open": 50.0, "close": 50.0})
    ev = pd.DataFrame([{"event_type": "GAP_UP_3", "symbol": "AAA", "entry_date": ss[5], "bucket": "L1"},
                       {"event_type": "GAP_UP_3", "symbol": "ZZZ", "entry_date": ss[5], "bucket": "L1"}])
    obs, cnt = E.outcomes(ev, px, {"SPY": spy, "XLK": xlk}, {"AAA": "XLK"}, ss)
    h1 = obs[obs["horizon"] == "H1"].iloc[0]
    assert h1["ret_raw"] == pytest.approx(10.6 / 10 - 1)
    assert h1["ret_spy_rel"] == pytest.approx(0.06 - 0.01) and h1["ret_sector_rel"] == pytest.approx(0.06)
    assert cnt["DATA_MISSING_ENTRY"] == 5 and len(obs) == 5 and not obs["missing_exit"].any()
    late = pd.DataFrame([{"event_type": "GAP_UP_3", "symbol": "AAA", "entry_date": date(2023, 12, 26), "bucket": "L1"}])
    s2 = sessions(10, date(2023, 12, 20))
    px2 = pd.DataFrame({"symbol": "AAA", "date": s2, "open": 1.0, "close": 1.0})
    b2 = pd.DataFrame({"symbol": "SPY", "date": s2, "open": 1.0, "close": 1.0})
    o2, c2 = E.outcomes(late, px2, {"SPY": b2}, {}, [d for d in s2 if d <= date(2023, 12, 29)])
    assert set(o2["horizon"]) == {"H0", "H1", "H3"} and c2["BEYOND_DEV_END"] == 2     # never reaches 2024


def test_no_event_control_is_deterministic_and_excludes_busy_symbols():
    ss = sessions(10)
    elig = pd.DataFrame([{"symbol": s, "date": d, "eligible": True, "bucket": "L1"}
                         for s in ["A", "B", "C", "D", "E", "F"] for d in ss])
    ev = pd.DataFrame([{"event_type": "GAP_UP_3", "symbol": "A", "entry_date": ss[5], "bucket": "L1"},
                       {"event_type": "8K_2.02", "symbol": "B", "entry_date": ss[6], "bucket": "L1"}])
    c1, c2 = E.no_event_control(ev, elig, ss), E.no_event_control(ev, elig, ss)
    assert c1.equals(c2) and len(c1) == 2
    assert "A" not in set(c1["symbol"]) and "B" not in set(c1["symbol"])      # B is busy within +/-2 of ss[5]


def test_sic_benchmark_map():
    m = {"default": "SPY", "ranges": [{"sic_lo": 7370, "sic_hi": 7379, "benchmark": "XLK"}]}
    assert E.sic_benchmark("7372", m) == "XLK" and E.sic_benchmark(None, m) == "SPY" and E.sic_benchmark(100, m) == "SPY"


# ------------------------------------------------------------------------------------------------ metrics / screen
def test_cell_grid_is_390():
    assert len(M.cells()) == 390 and len(E.EVENT_TYPES) == 13


def _obs(values, dates_per_year=80):
    rows, i = [], 0
    for y in M.YEARS:
        for k in range(dates_per_year):
            d = date(y, 1, 2) + timedelta(days=k)
            rows.append({"symbol": f"S{i % 50}", "entry_date": d, "ret_raw": values[i % len(values)],
                         "ret_spy_rel": values[i % len(values)], "ret_sector_rel": values[i % len(values)]})
            i += 1
    return pd.DataFrame(rows)


def test_screen_pass_on_strong_stable_signal_and_mirror_short_fails():
    obs = _obs([0.02, 0.015, 0.01, -0.005])                        # mean +1.0 % vs L3 cost 12 bps
    m = M.cell_metrics(obs, "LONG", "L3", n_resamples=500)
    s = M.screen(m, "GAP_UP_3")
    assert s["SCREEN_PASS"] and s["nominatable"] and m["stable_years"] == 5
    short = M.screen(M.cell_metrics(obs, "SHORT", "L3", n_resamples=500), "GAP_UP_3")
    assert not short["SCREEN_PASS"] and not short["criteria"]["mean_ge_2x_cost"]
    assert M.screen(m, "FORM4_CLUSTER")["SCREEN_PASS"] and not M.screen(m, "FORM4_CLUSTER")["nominatable"]
    assert not M.screen(m, "NO_EVENT")["nominatable"]


def test_screen_fails_on_outlier_driven_and_small_cells():
    obs = _obs([-0.001])
    obs.loc[:4, "ret_sector_rel"] = 5.0                            # five huge winners carry the mean
    s = M.screen(M.cell_metrics(obs, "LONG", "L1", n_resamples=200), "GAP_UP_3")
    assert not s["criteria"]["top5_removal_keeps_sign"] and not s["SCREEN_PASS"]
    small = M.screen(M.cell_metrics(_obs([0.05], dates_per_year=20), "LONG", "L1", n_resamples=200), "GAP_UP_3")
    assert not small["criteria"]["n_ge_300"] and not small["SCREEN_PASS"]


def test_cost_threshold_is_directional_2x_bucket_cost():
    obs = _obs([0.0059, 0.0061])                                   # mean 60 bps
    assert M.screen(M.cell_metrics(obs, "LONG", "L1", n_resamples=200), "GAP_UP_3")["criteria"]["mean_ge_2x_cost"]
    obs2 = _obs([0.0058, 0.0060])                                  # 59 bps < 2 x 30
    assert not M.screen(M.cell_metrics(obs2, "LONG", "L1", n_resamples=200), "GAP_UP_3")["criteria"]["mean_ge_2x_cost"]


def test_evaluate_ledgers_every_cell_even_empty():
    led = M.evaluate(pd.DataFrame(columns=["event_type", "horizon", "bucket", "symbol", "entry_date", "ret_raw",
                                           "ret_spy_rel", "ret_sector_rel"]), n_resamples=10)
    assert len(led) == 390 and all(not c["screen"]["SCREEN_PASS"] for c in led)


# ------------------------------------------------------------------------------------------------ lock / phase D
def test_fingerprint_is_sensitive_to_spec(monkeypatch):
    from research.event_response_map_v1 import fingerprint as F, spec as S
    a = F.fingerprint()
    monkeypatch.setitem(S.SPEC["costs_round_trip_bps"], "L1", 31)
    assert F.fingerprint() != a


def test_phase_d_refuses_without_go_or_approval():
    from research.event_response_map_v1 import phase_d as P
    with pytest.raises(SystemExit, match="go"):
        P.main(["--stage", "download"])
    with pytest.raises(SystemExit, match="not approved"):
        P.main(["--stage", "download", "--go"])


def test_design_lock_matches_code_when_present():
    from research.event_response_map_v1 import fingerprint as F
    p = F.ROOT / "results/event_response_map_v1/design_lock.json"
    if not p.exists():
        pytest.skip("design lock not yet written")
    lock = json.loads(p.read_text())
    assert F.verify() == lock["fingerprint"]
    assert F.lf_sha256(F.ROOT / "results/event_response_map_v1/candidates.json") == lock["candidates_sha256"]




# ------------------------------------------------------------------------------------------------ LOCK REV 2
def test_r1_master_idx_parse_and_instrument_filter():
    from research.event_response_map_v1 import instrument_filter as R1
    idx = ("Description: Master Index\n--------\n"
           "1|ALPHA INC|10-K|2020-03-01|edgar/data/1/a.txt\n"
           "2|BETA SPAC|10-Q/A|2018-12-31|edgar/data/2/b.txt\n"          # outside 2019-2023
           "3|GAMMA|8-K|2021-05-05|edgar/data/3/c.txt\n"
           "4|DELTA|10-Q|2023-12-29|edgar/data/4/d.txt\n")
    periodic, any_ = R1.parse_master_idx(idx)
    assert periodic == {"0000000001", "0000000004"} and any_ == {"0000000001", "0000000003", "0000000004"}
    cand = {"symbols": {"NAMD": ["A"], "UNA": ["C"], "UNB": ["C"], "UNC": ["C"], "SPAC": ["A"], "UND": ["C"]},
            "names": {"NAMD": "Named Corp", "SPAC": "Blank Check Acquisition Corp"}}
    cmap = {"NAMD": (None, "UNMAPPED"), "UNA": ("0000000001", "SEC_TICKERS"), "UNB": ("0000000003", "SEC_TICKERS"),
            "UNC": (None, "UNMAPPED"), "SPAC": ("0000000004", "SEC_TICKERS"), "UND": ("0000000004", "SEC_TICKERS")}
    doc = R1.apply(cand, cmap, periodic, {"0000000001": "3674", "0000000004": "6770"})
    assert doc["kept"] == ["NAMD", "UNA"]                         # named+unmapped kept; unnamed periodic filer kept
    assert doc["removed"] == {"SPAC": ["R1B_SIC_6770"], "UNB": ["R1A_UNNAMED_CIK_NO_10K_10Q_2019_2023"],
                              "UNC": ["R1A_UNNAMED_NO_CIK"], "UND": ["R1B_SIC_6770"]}
    c = doc["counts"]
    assert (c["R1a_unnamed_removed"], c["R1a_unnamed_no_cik"], c["R1a_unnamed_cik_without_10k_10q"],
            c["R1b_sic_6770_removed"], c["removed_total"]) == (2, 1, 1, 2, 4)


def _cell_obs(n_valid, n_missing, value=0.02):
    rows = []
    for i in range(n_valid + n_missing):
        miss = i >= n_valid
        d = date(2019 + (i % 5), 1, 2) + timedelta(days=i // 5 % 300)
        rows.append({"symbol": f"S{i % 60}", "entry_date": d, "missing_exit": miss,
                     "ret_raw": float("nan") if miss else value + (0.01 if i % 2 else -0.005),
                     "ret_spy_rel": float("nan") if miss else value, "ret_sector_rel": float("nan") if miss else value + (0.01 if i % 2 else -0.005)})
    return pd.DataFrame(rows)


def test_r3_missing_exit_rate_gates_screen_and_is_excluded_from_metrics():
    ok = M.cell_metrics(_cell_obs(1000, 20), "LONG", "L3", n_resamples=200)        # 1.96 %
    assert ok["n"] == 1000 and ok["n_missing_exit"] == 20 and ok["missing_exit_rate"] == pytest.approx(20 / 1020)
    assert np.isfinite(ok["mean_sector_relative"])
    s_ok = M.screen(ok, "GAP_UP_3")
    assert s_ok["criteria"]["missing_exit_rate_le_2pct"] and s_ok["SCREEN_PASS"]
    bad = M.cell_metrics(_cell_obs(1000, 25), "LONG", "L3", n_resamples=200)       # 2.44 %
    s_bad = M.screen(bad, "GAP_UP_3")
    assert not s_bad["criteria"]["missing_exit_rate_le_2pct"] and not s_bad["SCREEN_PASS"]
    assert "missing_exit_bounds" not in bad                                      # bounds only for remaining cells


def test_r3_bound_sensitivity_values_and_is_non_gating():
    m = M.cell_metrics(_cell_obs(1000, 20), "LONG", "L3", n_resamples=200)
    b = m["missing_exit_bounds"]
    x = m["mean_sector_relative"]
    assert b["BOUND_LONG_MINUS100_SHORT_0"]["mean_sector_relative"] == pytest.approx((1000 * x - 20) / 1020)
    assert b["BOUND_MIRROR_LONG_0_SHORT_MINUS100"]["mean_sector_relative"] == pytest.approx(1000 * x / 1020)
    for v in b.values():
        assert v["mean_ge_2x_cost"] == (v["mean_sector_relative"] >= 2 * 12 / 1e4)
    assert M.screen(m, "GAP_UP_3")["SCREEN_PASS"]                               # ... but the bound never gates
    sh = M.cell_metrics(_cell_obs(1000, 20), "SHORT", "L3", n_resamples=200)["missing_exit_bounds"]
    assert sh["BOUND_LONG_MINUS100_SHORT_0"]["mean_sector_relative"] == pytest.approx(-1000 * x / 1020)
    assert sh["BOUND_MIRROR_LONG_0_SHORT_MINUS100"]["mean_sector_relative"] == pytest.approx((-1000 * x - 20) / 1020)


def test_r3_outcomes_emit_flagged_missing_exit_rows():
    ss = sessions(20)
    px = pd.DataFrame({"symbol": "AAA", "date": ss[:8], "open": 10.0, "close": 10.0})        # delisted after ss[7]
    spy = pd.DataFrame({"symbol": "SPY", "date": ss, "open": 100.0, "close": 100.0})
    ev = pd.DataFrame([{"event_type": "GAP_UP_3", "symbol": "AAA", "entry_date": ss[5], "bucket": "L1"}])
    obs, cnt = E.outcomes(ev, px, {"SPY": spy}, {}, ss)
    assert dict(zip(obs["horizon"], obs["missing_exit"])) == {"H0": False, "H1": False, "H3": True, "H5": True,
                                                             "H10": True}
    assert cnt["DATA_MISSING_EXIT"] == 3 and obs.loc[obs["missing_exit"], "ret_sector_rel"].isna().all()


def _ledger(no_event_pass: bool):
    led = M.evaluate(pd.DataFrame(columns=["event_type", "horizon", "bucket", "symbol", "entry_date", "ret_raw",
                                           "ret_spy_rel", "ret_sector_rel", "missing_exit"]), n_resamples=10)
    for c in led:
        if c["cell"] in ("GAP_UP_5|LONG|H1|L2", "NO_EVENT|LONG|H3|L1") and (no_event_pass or c["event_type"] != "NO_EVENT"):
            c["screen"]["SCREEN_PASS"] = True
            c["screen"]["nominatable"] = c["event_type"] not in E.NON_NOMINATABLE
    return led


def test_r2_any_no_event_pass_marks_map_miscalibrated_and_blocks_nomination():
    led = _ledger(True)
    cal = M.classify(led)
    assert cal["no_event_screen_pass"] == 1 and cal["classification"] == "MAP_MISCALIBRATED"
    assert not cal["nomination_allowed"] and cal["nominatable_cells"] == 0
    assert all(not c["screen"]["nominatable"] for c in led)
    clean = M.classify(_ledger(False))
    assert clean["classification"] == "NULL_CALIBRATION_CLEAN" and clean["nominatable_cells"] == 1


def test_r2_report_md_first_line_is_no_event_pass_count():
    from research.event_response_map_v1 import phase_d as P
    led = _ledger(True)
    for c in led:          # give passing cells printable metrics
        if c["screen"]["SCREEN_PASS"]:
            c["metrics"].update({"n": 400, "distinct_dates": 200, "mean_sector_relative": 0.01, "ci_low": 0.002,
                                 "ci_high": 0.02, "missing_exit_rate": 0.0})
    md = P.report_md(M.classify(led), led, {"DATA_MISSING_EXIT": 0})
    assert md.splitlines()[0].startswith("**NO_EVENT SCREEN_PASS: 1 of 30**") and "MAP_MISCALIBRATED" in md.splitlines()[0]


def test_r4_coverage_breaks_out_by_bucket_and_year():
    from research.event_response_map_v1 import phase_d as P
    elig = pd.DataFrame([{"symbol": "A", "date": date(2019, 3, 1), "eligible": True, "bucket": "L1"},
                         {"symbol": "A", "date": date(2019, 3, 4), "eligible": True, "bucket": "L1"},
                         {"symbol": "B", "date": date(2020, 3, 2), "eligible": True, "bucket": "L3"},
                         {"symbol": "C", "date": date(2020, 3, 2), "eligible": False, "bucket": None}])
    eq = pd.DataFrame({"symbol": ["A", "B"], "date": [date(2019, 3, 1), date(2020, 3, 2)]})
    obs = pd.DataFrame({"bucket": ["L1", "L1"], "entry_date": [date(2019, 3, 1)] * 2, "missing_exit": [True, False]})
    cov = P.bucket_year_coverage(eq, elig, obs)
    assert cov["L1|2019"] == {"eligible_symbol_days": 2, "distinct_symbols": 1, "all_bar_present_rate": 0.5,
                              "missing_exit_rate": 0.5}
    assert cov["L3|2020"]["all_bar_present_rate"] == 1.0 and set(cov) == {"L1|2019", "L3|2020"}


def test_lock_revision_2_recorded_in_spec():
    from research.event_response_map_v1.spec import SPEC
    assert SPEC["lock_revision"] == 2
    assert any(k.startswith("revision_2_changes") for k in SPEC)
