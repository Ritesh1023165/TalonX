"""Fixtures for the ERM nominee validation plumbing (research/erm_nominee_validation). SYNTHETIC data only: no archive,
no validation data, no network. Separate from any research scoring."""
from datetime import date, timedelta
import socket

import numpy as np
import pandas as pd
import pytest

from research.erm_nominee_validation import builder as B, gates as G
from research.erm_nominee_validation.config import OwnerDecisionPending, OwnerDecisions, ValidationConfig
from research.erm_nominee_validation.guard import GuardReleaseNotAuthorised, ValidationGuard
from research.erm_nominee_validation.inventory import inventory
from research.event_response_map_v1 import events as E

CIK = "0000000001"


def sessions(n=80, start=date(2021, 3, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars(sym, ss, gap_at=None, zero_vol=(), close=10.0, vol=3_000_000):
    rows = []
    px = close
    for i, d in enumerate(ss):
        o = px * (1.12 if i == gap_at else 1.0)
        c = o
        rows.append({"symbol": sym, "date": d, "open": o, "high": o, "low": o, "close": c,
                     "volume": 0 if d in zero_vol else vol})
        px = c
    return pd.DataFrame(rows)


def meta(f345=None, names=None, sic="3571", company_filing=date(2020, 1, 15), periodic=("2019-03-01",), trans=()):
    def subs(cik):
        if cik != CIK:
            return None
        rows = [(company_filing.isoformat(), "8-K", "ACC-1", "8.01", "")]   # company filing, NOT periodic
        rows += [(f, "8-K", f"ACC-5{i}", "5.06", r) for i, (r, f) in enumerate(trans)]
        return sorted(rows)
    return B.Meta(names=names if names is not None else {"XX": "X Corp"}, frozen_cik={"XX": CIK}, edges=[],
                  f345=f345 if f345 is not None else {"XX": [(date(2020, 6, 1), CIK)]}, sp_rows=[],
                  periodic={CIK: set(periodic)}, subs=subs,
                  header=lambda acc: ((sic, "ARCHIVED") if sic else (None, "HEADER_NOT_ARCHIVED")),
                  etf_div={"XLK": [], "SPY": []}, sic_to_etf=lambda s: "XLK" if s == "3571" else "SPY")


def run_build(ss, frames, start, end, m):
    df = pd.concat(frames)
    pop = B.population(df, df, ss, start, end, "MAIN")
    ser = B.series(df, df)
    return B.build(pop, ser, ss, m, end)


# window boundaries / H10 beyond the end -----------------------------------------------------------------------------
def test_gap_inside_window_valid_and_exit_beyond_end_flagged():
    ss = sessions()
    rows, _ = run_build(ss, [bars("XX", ss, gap_at=30)], ss[25], ss[-1], meta())
    assert [r["v2_status"] for r in rows] == ["VALID"] and rows[0]["benchmark_v2"] == "XLK"
    rows, _ = run_build(ss, [bars("XX", ss, gap_at=30)], ss[25], ss[35], meta())   # exit = ss[41] > end
    assert rows[0]["v2_status"] == "BEYOND_WINDOW" and rows[0]["first_reason"] == "BEYOND_WINDOW"


def test_gap_before_window_start_is_not_an_event_and_bounds_are_restored():
    ss = sessions()
    old = (E.DEV_START, E.DEV_END)
    rows, _ = run_build(ss, [bars("XX", ss, gap_at=30)], ss[31], ss[-1], meta())
    assert rows == [] and (E.DEV_START, E.DEV_END) == old


# metadata availability, dated identity / SIC ------------------------------------------------------------------------
def test_identity_needs_dated_evidence_on_or_before_d():
    ss = sessions()
    late = meta(f345={"XX": [(ss[60], CIK)]})                 # only a Form 3/4/5 AFTER the gap day
    rows, _ = run_build(ss, [bars("XX", ss, gap_at=30)], ss[25], ss[-1], late)
    assert rows[0]["identity_reason"].startswith("ABSENT") and rows[0]["first_reason"] == "ID_UNRESOLVED"


def test_sic_from_latest_company_filing_on_or_before_d_only():
    ss = sessions()
    m = meta(company_filing=ss[50])                            # the only company filing is after D
    rows, _ = run_build(ss, [bars("XX", ss, gap_at=30)], ss[25], ss[-1], m)
    assert rows[0]["sic_source"] == "NO_COMPANY_FILING_BY_D" and rows[0]["first_reason"] == "INSTRUMENT_UNRESOLVED"


def test_subs_reader_drops_rows_after_evidence_end(tmp_path):
    import gzip, json
    doc = {"filings": {"recent": {"filingDate": ["2023-12-01", "2024-02-01"], "form": ["10-K", "10-Q"],
                                  "accessionNumber": ["a", "b"], "items": ["", ""], "reportDate": ["", ""]},
                       "files": []}}
    (tmp_path / f"sub_CIK{CIK}.json.gz").write_bytes(gzip.compress(json.dumps(doc).encode()))
    rows = B.subs_reader([tmp_path], "2023-12-29")(CIK)
    assert [r[0] for r in rows] == ["2023-12-01"]
    assert B.header_reader([tmp_path])("zzz") == (None, "HEADER_NOT_ARCHIVED")


def test_unnamed_symbol_needs_available_periodic_filing():
    ss = sessions()
    m = meta(names={}, periodic=(ss[60].isoformat(),))
    rows, _ = run_build(ss, [bars("XX", ss, gap_at=30)], ss[25], ss[-1], m)
    assert "R1A_NOT_AVAILABLE" in rows[0]["flags"]


# placeholder bars, unresolved identity ------------------------------------------------------------------------------
def test_placeholder_gap_reference_and_eligibility_window():
    ss = sessions()
    rows, _ = run_build(ss, [bars("XX", ss, gap_at=30, zero_vol={ss[29]})], ss[25], ss[-1], meta())
    assert rows == [] or rows[0]["first_reason"] in ("C1_NO_GAP_PLACEHOLDER", "C1_NOT_ELIGIBLE_PLACEHOLDER")
    rows, _ = run_build(ss, [bars("XX", ss, gap_at=30, zero_vol={ss[41]})], ss[25], ss[-1], meta())
    assert rows[0]["v2_status"] == "DATA_MISSING_EXIT"           # exit placeholder -> missing exit


# deduplication and benchmark ----------------------------------------------------------------------------------------
def test_relabelled_duplicate_series_keeps_own_ticker_representative():
    ss = sessions()
    a, b = bars("XX", ss, gap_at=30), bars("NEWX", ss, gap_at=30)
    m = meta()
    m.edges = [("XX", "NEWX", ss[70])]                            # rename after D: NEWX history is XX relabelled
    m.frozen_cik["NEWX"] = CIK
    m.names["NEWX"] = "X Corp"
    rows, groups = run_build(ss, [a, b], ss[25], ss[-1], m)
    st = {r["symbol"]: (r["v2_status"], r["first_reason"]) for r in rows}
    assert st["XX"] == ("VALID", "") and st["NEWX"] == ("EXCLUDED", "DUP_NOT_REPRESENTATIVE")
    assert groups[0]["representative"] == "XX" and groups[0]["reason"] == "OWN_TICKER_ON_D"


def test_identical_volume_different_price_series_stay_separate():
    ss = sessions()
    a, b = bars("XX", ss, gap_at=30), bars("YY", ss, gap_at=30, close=20.0)
    m = meta(f345={"XX": [(date(2020, 6, 1), CIK)], "YY": [(date(2020, 6, 1), "0000000002")]})
    rows, groups = run_build(ss, [a, b], ss[25], ss[-1], m)
    assert groups == [] and all(r["dup_group"] == "" for r in rows)


# costs, verdict precedence, n = 0, floor ----------------------------------------------------------------------------
def obs_frame(vals, missing=0, dates=None):
    n = len(vals)
    d = dates or [date(2021, 1, 4) + timedelta(days=i % 60) for i in range(n)]
    o = pd.DataFrame({"symbol": [f"S{i}" for i in range(n)], "entry_date": d, "ret_sector_rel": -np.array(vals),
                      "missing_exit": False})
    if missing:
        o = pd.concat([o, pd.DataFrame({"symbol": [f"M{i}" for i in range(missing)], "entry_date": d[:missing],
                                        "ret_sector_rel": np.nan, "missing_exit": True})], ignore_index=True)
    return o


def test_costs_are_round_trip_totals_subtracted_once():
    x, g, nm = G.pair_net(obs_frame([0.01, 0.02]), 0.0030, 0.0004)
    assert np.allclose(sorted(x), [0.01 - 0.0034, 0.02 - 0.0034])


def test_verdict_precedence_and_pass_label():
    rng = np.random.default_rng(1)
    vals = list(0.02 + 0.01 * rng.standard_normal(400))
    x, g, nm = G.pair_net(obs_frame(vals), 0.0030, 0.0004)
    v = G.verdict(G.gates(x, g, nm), True, {"n_valid": 100, "distinct_dates": 40})
    assert v == (G.PASS_LABEL, "STEP4_ALL_GATES") and G.scheme(v[0]) == "PASS"
    x, g, nm = G.pair_net(obs_frame(vals, missing=20), 0.0030, 0.0004)      # 20 / 420 > 2 %
    assert G.verdict(G.gates(x, g, nm), True, {"n_valid": 100, "distinct_dates": 40})[0] == "FAIL"
    x, g, nm = G.pair_net(obs_frame([-0.01] * 200), 0.0030, 0.0004)
    assert G.verdict(G.gates(x, g, nm), False, {"n_valid": 100, "distinct_dates": 40})[1] == "STEP3_MEAN_LE_0_OR_CI_HIGH_LT_0"


def test_n_zero_and_sample_floor_branches():
    x, g, nm = G.pair_net(obs_frame([]), 0.0030, 0.0004)
    gt = G.gates(x, g, nm)
    assert G.verdict(gt, False, {"n_valid": 100, "distinct_dates": 40}) == ("INCONCLUSIVE", "STEP2P_N_ZERO")
    small = obs_frame([0.05] * 50)
    x, g, nm = G.pair_net(small, 0.0030, 0.0004)
    gt = G.gates(x, g, nm)
    assert G.verdict(gt, True, {"n_valid": 100, "distinct_dates": 40}) == ("INCONCLUSIVE", "STEP2_SAMPLE_FLOOR")
    assert G.verdict(gt, False, {"n_valid": 100, "distinct_dates": 40}) == (G.PASS_LABEL, "STEP4_ALL_GATES")
    with pytest.raises(ValueError):
        G.verdict(gt, None, {"n_valid": 100, "distinct_dates": 40})          # pending decision rejected


def test_ci_withheld_below_five_dates_fails_g2():
    x, g, nm = G.pair_net(obs_frame([0.05] * 10, dates=[date(2021, 1, 4)] * 10), 0.0, 0.0)
    gt = G.gates(x, g, nm)
    assert gt["ci_withheld"] and not gt["G2"]


# guard denial and owner decisions ------------------------------------------------------------------------------------
def test_guard_denies_protected_acquisition_and_load():
    cfg = ValidationConfig("A", OwnerDecisions())
    gd = ValidationGuard(cfg)
    assert gd.release_authorised() is False
    with pytest.raises(GuardReleaseNotAuthorised):
        gd.check_acquisition(cfg.start, cfg.end, "bars")
    with pytest.raises(GuardReleaseNotAuthorised):
        gd.check_acquisition(date(2025, 3, 1), date(2025, 3, 2), "metadata")
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2023-12-28", "2024-01-03"], utc=True)})
    with pytest.raises(GuardReleaseNotAuthorised):
        gd.check_load(df, "frame")
    gd.check_acquisition(date(2023, 1, 1), date(2023, 12, 29), "development")      # allowed


def test_unresolved_owner_decisions_are_rejected():
    with pytest.raises(OwnerDecisionPending) as e:
        ValidationConfig("B", OwnerDecisions()).require_decided()
    assert "window" in str(e.value) and "task75_reserve_acknowledged" in str(e.value)
    with pytest.raises(OwnerDecisionPending):
        ValidationConfig("DEV").require_decided()
    d = OwnerDecisions(window="A", task75_reserve_acknowledged=True, min_sample_floor_adopted=True, etf_cost_bps=4,
                       procedural_amendments_approved=True, decision_record="x")
    with pytest.raises(OwnerDecisionPending):
        ValidationConfig("B", d).require_decided()                                   # window mismatch
    assert ValidationConfig("A", d).config_hash() != ValidationConfig("A", OwnerDecisions()).config_hash()


def test_runner_refuses_validation_windows():
    from research.erm_nominee_validation import run
    with pytest.raises(OwnerDecisionPending):
        run.main(["--window", "A"])
    with pytest.raises(OwnerDecisionPending):
        run.main(["--window", "B"])


# no implicit downloads -----------------------------------------------------------------------------------------------
def test_builder_makes_no_network_calls(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("network attempted")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    ss = sessions()
    rows, _ = run_build(ss, [bars("XX", ss, gap_at=30)], ss[25], ss[-1], meta(sic=None))
    assert rows[0]["sic_source"] == "HEADER_NOT_ARCHIVED"                            # absent, never fetched


def test_plumbing_modules_have_no_download_code():
    import pathlib
    src = "".join(p.read_text() for p in pathlib.Path("research/erm_nominee_validation").glob("*.py"))
    for bad in ("urllib", "requests", "http.client", "Sec(", "D.download", "fetch_"):
        assert bad not in src


def test_inventory_marks_window_inputs_not_acquired_and_guarded():
    inv = {i["input"]: i for i in inventory(ValidationConfig("A"))}
    assert inv["bars_all_raw"]["status"] == "NOT_ACQUIRED+GUARDED" and inv["bars_all_raw"]["task75_reserved_overlap"]
    assert inv["form345"]["category"] == "IDENTITY_METADATA" and inv["etf_cash_dividends"]["category"] == "DESCRIPTIVE_METADATA"
    assert all(i["status"] == "ARCHIVED_DEVELOPMENT" for i in inventory(ValidationConfig("DEV")))


def test_deterministic_manifest_output(tmp_path):
    ss = sessions()
    r1, g1 = run_build(ss, [bars("XX", ss, gap_at=30), bars("ZZ", ss, gap_at=40)], ss[25], ss[-1], meta())
    r2, g2 = run_build(ss, [bars("ZZ", ss, gap_at=40), bars("XX", ss, gap_at=30)], ss[25], ss[-1], meta())
    h1 = B.write_manifest(r1, g1 or [{}], tmp_path / "a") if g1 else B.write_manifest(r1, [], tmp_path / "a")
    h2 = B.write_manifest(r2, g2, tmp_path / "b")
    assert h1["manifest.csv"] == h2["manifest.csv"]
