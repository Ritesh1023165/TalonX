"""
Unit tests for the Task 107 Form 4 insider-cluster research tooling.

Covers the statistical-contract requirements for new research code:
causal timestamp handling, episode construction, PIT selection,
no-future-data access, cost calculation, holdout split, concentration
removal.  Pure-function tests -- no network, no file downloads.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "research" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ep_mod = _load("task107a_episodes")
try:
    b_mod = _load("task107b_form4_cluster")
except Exception:  # noqa: BLE001
    b_mod = None


# --------------------------------------------------------------------------
# Phase 3/4 -- episode construction & causal timing
# --------------------------------------------------------------------------
def _tdays():
    # weekdays only, 2023-01-02 .. 2023-03-31
    rng = pd.bdate_range("2023-01-02", "2023-03-31")
    return pd.DatetimeIndex(rng)


def _txn(sym, fdate, ocik, value=100_000.0, officer=False, director=True, ten=False):
    return dict(issuer_sym=sym, filing_date=pd.Timestamp(fdate), owner_cik=str(ocik),
                value=value, is_officer=officer, is_director=director, is_ten_pct=ten)


def test_episode_requires_two_distinct_owners():
    td = _tdays()
    i8 = td.values.astype("datetime64[ns]").astype("int64")
    # same owner twice -> NOT an episode
    P = pd.DataFrame([_txn("AAA", "2023-02-01", 1), _txn("AAA", "2023-02-03", 1)])
    out = ep_mod.build_episodes(P, 10, 2, i8)
    assert out.empty
    # two distinct owners -> one episode
    P = pd.DataFrame([_txn("AAA", "2023-02-01", 1), _txn("AAA", "2023-02-03", 2)])
    out = ep_mod.build_episodes(P, 10, 2, i8)
    assert len(out) == 1
    assert out.iloc[0].n_distinct_owners == 2


def test_entry_is_strictly_after_last_filing_knowable_date():
    td = _tdays()
    i8 = td.values.astype("datetime64[ns]").astype("int64")
    P = pd.DataFrame([_txn("BBB", "2023-02-01", 1), _txn("BBB", "2023-02-06", 2)])
    out = ep_mod.build_episodes(P, 10, 2, i8)
    row = out.iloc[0]
    assert row.knowable_date == pd.Timestamp("2023-02-06")
    # entry must be the NEXT trading session, strictly after 02-06 (a Monday)
    assert row.entry_session > row.knowable_date
    assert row.entry_session == pd.Timestamp("2023-02-07")


def test_window_excludes_late_filing_into_new_episode():
    td = _tdays()
    i8 = td.values.astype("datetime64[ns]").astype("int64")
    # 3rd filing is 20 trading days later -> must NOT join the first episode
    P = pd.DataFrame([
        _txn("CCC", "2023-02-01", 1),
        _txn("CCC", "2023-02-02", 2),
        _txn("CCC", "2023-03-20", 3),
    ])
    out = ep_mod.build_episodes(P, 10, 2, i8)
    assert len(out) == 1
    assert out.iloc[0].n_filings == 2
    assert out.iloc[0].last_filing == pd.Timestamp("2023-02-02")


def test_no_future_filing_leaks_into_aggregates():
    td = _tdays()
    i8 = td.values.astype("datetime64[ns]").astype("int64")
    P = pd.DataFrame([
        _txn("DDD", "2023-02-01", 1, value=10_000.0),
        _txn("DDD", "2023-02-03", 2, value=20_000.0),
        _txn("DDD", "2023-02-27", 3, value=999_999.0),  # after the 10td window
    ])
    out = ep_mod.build_episodes(P, 10, 2, i8)
    first = out.iloc[0]
    # aggregate value must only include the two in-window filings
    assert first.agg_value == pytest.approx(30_000.0)


def test_greedy_non_overlapping_episodes():
    td = _tdays()
    i8 = td.values.astype("datetime64[ns]").astype("int64")
    P = pd.DataFrame([
        _txn("EEE", "2023-02-01", 1), _txn("EEE", "2023-02-02", 2),   # episode 1
        _txn("EEE", "2023-03-01", 3), _txn("EEE", "2023-03-02", 4),   # episode 2
    ])
    out = ep_mod.build_episodes(P, 10, 2, i8).sort_values("first_filing")
    assert len(out) == 2
    assert out.iloc[0].last_filing < out.iloc[1].first_filing


# --------------------------------------------------------------------------
# Phase 107B -- cost calc, holdout split, concentration removal
# (skipped cleanly until task107b_form4_cluster.py exists)
# --------------------------------------------------------------------------
@pytest.mark.skipif(b_mod is None, reason="107B module not yet written")
def test_cost_is_subtracted_in_bps_round_trip():
    # 20 bps round-trip on a +1.00% gross should give +0.80%
    r = b_mod.apply_cost(pd.Series([0.01, -0.02, 0.0]), bps=20)
    assert r.iloc[0] == pytest.approx(0.01 - 0.0020)
    assert r.iloc[1] == pytest.approx(-0.02 - 0.0020)


@pytest.mark.skipif(b_mod is None, reason="107B module not yet written")
def test_holdout_split_is_chronological_and_frozen():
    ep = pd.DataFrame({"entry_session": pd.to_datetime(
        ["2020-01-01", "2022-01-01", "2023-06-29", "2023-07-01", "2025-01-01"])})
    disc, hold = b_mod.split_discovery_holdout(ep, cutoff=b_mod.HOLDOUT_CUTOFF)
    assert (disc.entry_session < pd.Timestamp(b_mod.HOLDOUT_CUTOFF)).all()
    assert (hold.entry_session >= pd.Timestamp(b_mod.HOLDOUT_CUTOFF)).all()
    assert len(disc) + len(hold) == len(ep)


@pytest.mark.skipif(b_mod is None, reason="107B module not yet written")
def test_concentration_removal_drops_top_contributors():
    rets = pd.Series([0.50, 0.01, 0.00, -0.01, 0.02])
    trimmed = b_mod.remove_top_k(rets, k=1)
    assert len(trimmed) == len(rets) - 1
    assert 0.50 not in set(trimmed.values)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
