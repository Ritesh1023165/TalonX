"""
Task 117 final activation -- EXECUTION SCOPE ENFORCEMENT.

The InsiderStore can carry a broad historical backfill (68 code-P issuer symbols
in production, 48 outside the approved 39).  V2 must consider ONLY the approved
set -- enforced in code, not merely described.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from talonx_v2 import calendar as vc
from talonx_v2.config import V2Config
from talonx_v2.form4_source import from_rows
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

ENTRY = date(2026, 8, 17)
ACT = date(2026, 8, 14)


def _bars(tmp, syms):
    bd = tmp / "bars"
    bd.mkdir(exist_ok=True)
    for sym in syms:
        with open(bd / f"{sym}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "close", "volume"])
            for s in vc._sessions():
                if date(2026, 6, 1) <= s <= date(2026, 8, 31):
                    w.writerow([s.isoformat(), 50.0, 50.5, 2_000_000])
    return bd


def _cluster_rows(sym):
    return [
        {"symbol": sym, "issuer_cik": sym + "_CIK", "owner_cik": "o1",
         "filing_date": ACT.isoformat(), "accession": sym + "a1", "transaction_code": "P",
         "transaction_value": 400000},
        {"symbol": sym, "issuer_cik": sym + "_CIK", "owner_cik": "o2",
         "filing_date": ACT.isoformat(), "accession": sym + "a2", "transaction_code": "P",
         "transaction_value": 400000},
    ]


def _svc(tmp, *, allowlist):
    cfg = V2Config(db_path=str(tmp / "v.db"), starting_cash_usd=300_000.0)
    return V2Service(config=cfg, bar_dirs=[_bars(tmp, ["INSCOPE", "OUTSCOPE", "MUNI1"])],
                     form4_kind="parquet", status_path=str(tmp / "s.json"),
                     execution_allowlist=allowlist)


def test_no_allowlist_considers_every_issuer(tmp_path):
    svc = _svc(tmp_path, allowlist=None)
    svc._records = lambda *, as_of: from_rows(
        _cluster_rows("INSCOPE") + _cluster_rows("OUTSCOPE") + _cluster_rows("MUNI1"))
    st = svc.tick(as_of=date(2026, 8, 18))
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert st["execution_scope_enforced"] is False
    assert sorted(p["symbol"] for p in s.all_positions()) == ["INSCOPE", "MUNI1", "OUTSCOPE"]


def test_allowlist_drops_out_of_scope_issuers(tmp_path):
    svc = _svc(tmp_path, allowlist=["INSCOPE"])
    svc._records = lambda *, as_of: from_rows(
        _cluster_rows("INSCOPE") + _cluster_rows("OUTSCOPE") + _cluster_rows("MUNI1"))
    st = svc.tick(as_of=date(2026, 8, 18))
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert st["execution_scope_enforced"] is True and st["execution_scope_count"] == 1
    assert st["execution_scope_out_of_scope_dropped_this_tick"] >= 2   # OUTSCOPE + MUNI1 episodes
    assert [p["symbol"] for p in s.all_positions()] == ["INSCOPE"]
    # no out-of-scope disposition, intent, trade or outbox row was ever created
    import sqlite3
    con = sqlite3.connect(str(tmp_path / "v.db"))
    disp_syms = {r[0] for r in con.execute("SELECT symbol FROM processed_episodes")}
    assert disp_syms == {"INSCOPE"}
    assert {r[0] for r in con.execute("SELECT symbol FROM trades")} == {"INSCOPE"}
    con.close()


def test_allowlist_defense_in_depth_at_episode_stage(tmp_path):
    # even if _records is bypassed, detect_episodes output is filtered
    svc = _svc(tmp_path, allowlist=["INSCOPE"])
    svc._records = lambda *, as_of: from_rows(
        _cluster_rows("INSCOPE") + _cluster_rows("OUTSCOPE"))
    st = svc.tick(as_of=date(2026, 8, 18))
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert [p["symbol"] for p in s.all_positions()] == ["INSCOPE"]
    assert st["execution_scope_out_of_scope_dropped_this_tick"] >= 1


def test_run_resolved_active_watchlist_builds_the_39(monkeypatch):
    # the run.py wiring path -- 'resolved-active-watchlist' -> POLLED symbols
    from talonx_ops import watchlist_coverage as wc
    fake = {"tickers": [{"symbol": "AAPL", "v2_collection_scope": "POLLED"},
                        {"symbol": "BABA", "v2_collection_scope": "NOT_POLLED"},
                        {"symbol": "NVDA", "v2_collection_scope": "POLLED"}]}
    monkeypatch.setattr(wc, "build_coverage_map", lambda **k: fake)
    allow = sorted(c["symbol"] for c in wc.build_coverage_map()["tickers"]
                   if c["v2_collection_scope"] == "POLLED")
    assert allow == ["AAPL", "NVDA"]


def test_frozen_replay_unaffected_when_allowlist_is_none(tmp_path):
    # allowlist None == prior behaviour, byte for byte (the frozen replay path)
    svc = _svc(tmp_path, allowlist=None)
    assert svc.execution_allowlist is None
    recs = from_rows(_cluster_rows("INSCOPE"))
    assert svc._apply_execution_allowlist(recs, stage="records") is recs
