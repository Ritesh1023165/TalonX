"""SEC-stage tests on synthetic data: point-in-time availability, TTM construction, insider windows, gate-4 audit."""
import numpy as np
import pandas as pd

from talonx_scorecard import insider as INS
from talonx_scorecard import sec_facts as SF
from talonx_scorecard import sec_features as SFE


def _facts():
    R = []
    def add(concept, start, end, val, filed, cik=1):
        R.append((cik, concept, 0, start, end, val, filed))
    for s, e, v, f in [("2020-01-01", "2020-12-31", 400, "2021-02-15"), ("2020-01-01", "2020-03-31", 90, "2020-05-05"),
                       ("2020-01-01", "2020-06-30", 190, "2020-08-05"), ("2021-01-01", "2021-03-31", 110, "2021-05-05"),
                       ("2021-01-01", "2021-06-30", 230, "2021-08-05")]:
        add("gross_profit", s, e, v, f)
    add("net_income", "2020-01-01", "2020-12-31", 100, "2021-02-15")
    add("net_income", "2020-01-01", "2020-12-31", 999, "2022-02-15")              # later restatement must be ignored
    add("op_cash_flow", "2020-01-01", "2020-12-31", 130, "2021-02-15")
    add("revenue", "2019-01-01", "2019-12-31", 900, "2020-02-15")
    add("revenue", "2020-01-01", "2020-12-31", 1000, "2021-02-15")
    add("assets", None, "2020-12-31", 2000, "2021-02-15")
    add("equity", None, "2020-12-31", 800, "2021-02-15")
    add("shares", None, "2020-01-31", 100, "2020-02-20")
    add("shares", None, "2021-01-31", 110, "2021-02-20")
    return pd.DataFrame(R, columns=["cik", "concept", "rank", "start", "end", "val", "filed"])


def _build():
    ses = pd.bdate_range("2020-01-02", "2021-12-31")
    close = pd.DataFrame({"AAA": 10.0, "ZZZ": 5.0}, index=ses)
    feats, src = SFE.build_fundamental_features(_facts(), ses, close, {"AAA": 1, "ZZZ": None})
    return ses, feats, src


def test_value_usable_only_after_filing_date():
    ses, feats, _ = _build()
    f5 = feats["F5"]["AAA"]
    assert np.isnan(f5.loc["2021-02-15"])                  # filed that day: not usable until the next session
    assert abs(f5.loc["2021-02-16"] - 0.2) < 1e-12


def test_ttm_from_year_to_date_facts():
    ses, feats, _ = _build()
    f5 = feats["F5"]["AAA"]
    assert abs(f5.loc["2021-05-06"] - (400 + 110 - 90) / 2000) < 1e-12
    assert abs(f5.loc["2021-08-06"] - (400 + 230 - 190) / 2000) < 1e-12


def test_restatement_ignored_and_other_features():
    ses, feats, _ = _build()
    assert abs(feats["F6"]["AAA"].loc["2021-03-01"] - (100 - 130) / 2000) < 1e-12
    assert abs(feats["F9"]["AAA"].loc["2021-03-01"] - (1000 / 900 - 1)) < 1e-12
    assert abs(feats["F7"]["AAA"].loc["2021-03-01"] - 100 / (110 * 10)) < 1e-12
    assert abs(feats["F12"]["AAA"].loc["2021-03-01"] - 0.1) < 1e-9
    assert feats["F5"]["ZZZ"].isna().all()                  # symbol with no CIK has no fundamentals


def test_no_lookahead_audit_passes_and_catches_a_violation():
    ses, _, src = _build()
    ok, n, _ = SF.audit_no_lookahead(src, ses)
    assert ok and n > 0
    bad = {k: v.copy() for k, v in src.items()}
    k = next(iter(bad))
    bad[k].iloc[100, 0] = ses[100].value                    # a source dated ON the rank date
    assert not SF.audit_no_lookahead(bad, ses)[0]


def test_has_fundamental_gate_input():
    ses, feats, _ = _build()
    h = SFE.has_fundamental(feats)
    assert h["AAA"].loc["2021-03-01"] and not h["ZZZ"].any()


def test_insider_net_buyers_window():
    ses = pd.bdate_range("2020-01-02", "2021-12-31")
    ev = pd.DataFrame({"issuer_cik": [1, 1, 1], "owner_cik": [7, 8, 7],
                       "filed": pd.to_datetime(["2021-03-01", "2021-03-02", "2021-04-01"]), "code": ["P", "S", "P"]})
    w = INS.net_buyers_wide(ev, ses, [1])[1]
    assert w.loc["2021-03-01"] == 0.0                      # not counted on the filing day
    assert w.loc["2021-03-02"] == 1.0                      # buyer counts from the next session
    assert w.loc["2021-03-03"] == 0.0                      # seller joins: 1 buyer - 1 seller
    assert w.loc["2021-06-30"] == 1.0                      # second buyer filing keeps 7 active
    assert w.loc["2021-07-15"] == 0.0                      # all windows expired
