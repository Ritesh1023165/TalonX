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


# --------------------------------------------------------------------------- fail-closed
def test_empty_allowlist_fails_closed_enters_nothing(tmp_path):
    svc = _svc(tmp_path, allowlist=[])                 # explicitly empty -> NOT unrestricted
    assert svc.execution_allowlist is not None and len(svc.execution_allowlist) == 0
    svc._records = lambda *, as_of: from_rows(_cluster_rows("INSCOPE") + _cluster_rows("OUTSCOPE"))
    st = svc.tick(as_of=date(2026, 8, 18))
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert st["execution_scope_enforced"] is True and st["execution_scope_count"] == 0
    assert s.all_positions() == [] and s.trades() == []


def test_run_py_fails_closed_when_scope_resolves_empty(tmp_path, monkeypatch):
    from talonx_v2 import run as _run
    from talonx_ops import watchlist_coverage as wc
    monkeypatch.setattr(wc, "build_coverage_map",
                        lambda **k: {"tickers": [{"symbol": "X", "v2_collection_scope": "NOT_POLLED"}]})
    with pytest.raises(SystemExit) as ei:
        _run.main(["--mode", "live", "--once", "--as-of", "2026-08-18",
                   "--form4-source", "insider", "--execution-scope", "resolved-active-watchlist",
                   "--db", str(tmp_path / "v.db"), "--status-path", str(tmp_path / "s.json")])
    assert "fail closed" in str(ei.value).lower()


def test_run_py_fails_closed_when_resolver_errors(tmp_path, monkeypatch):
    from talonx_v2 import run as _run
    from talonx_ops import watchlist_coverage as wc
    monkeypatch.setattr(wc, "build_coverage_map",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("resolver down")))
    with pytest.raises(SystemExit) as ei:
        _run.main(["--mode", "live", "--once", "--as-of", "2026-08-18",
                   "--form4-source", "insider", "--execution-scope", "resolved-active-watchlist",
                   "--db", str(tmp_path / "v.db"), "--status-path", str(tmp_path / "s.json")])
    assert "fail closed" in str(ei.value).lower()


# --------------------------------------------------------------------------- exits not blocked
def test_scope_does_not_block_exiting_an_existing_position(tmp_path):
    # open a position in INSCOPE, then re-instantiate with an allowlist that
    # NO LONGER contains it -- the +10td exit must still settle.
    from talonx_v2 import calendar as vc
    bd = _bars(tmp_path, ["INSCOPE"])
    cfg = V2Config(db_path=str(tmp_path / "v.db"), starting_cash_usd=300_000.0)
    svc1 = V2Service(config=cfg, bar_dirs=[bd], form4_kind="parquet",
                     status_path=str(tmp_path / "s.json"), execution_allowlist=["INSCOPE"])
    svc1._records = lambda *, as_of: from_rows(_cluster_rows("INSCOPE"))
    svc1.tick(as_of=date(2026, 8, 18))
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.n_open() == 1
    exit_session = vc.add_sessions(date(2026, 8, 17), 10)

    # RESTART with INSCOPE removed from the allowlist
    svc2 = V2Service(config=cfg, bar_dirs=[bd], form4_kind="parquet",
                     status_path=str(tmp_path / "s.json"), execution_allowlist=["OTHER"])
    svc2._records = lambda *, as_of: from_rows(_cluster_rows("INSCOPE"))
    svc2.tick(as_of=exit_session)
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert s.n_open() == 0                                   # the exit STILL happened
    assert [t["action"] for t in s.trades()] == ["BUY", "SELL"]


def test_restart_preserves_the_enforced_scope(tmp_path):
    bd = _bars(tmp_path, ["INSCOPE", "OUTSCOPE"])
    cfg = V2Config(db_path=str(tmp_path / "v.db"), starting_cash_usd=300_000.0)
    for _ in range(2):                                       # two fresh instances, same allowlist
        svc = V2Service(config=cfg, bar_dirs=[bd], form4_kind="parquet",
                        status_path=str(tmp_path / "s.json"), execution_allowlist=["INSCOPE"])
        svc._records = lambda *, as_of: from_rows(_cluster_rows("INSCOPE") + _cluster_rows("OUTSCOPE"))
        svc.tick(as_of=date(2026, 8, 18))
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert [p["symbol"] for p in s.all_positions()] == ["INSCOPE"]
    import sqlite3
    con = sqlite3.connect(str(tmp_path / "v.db"))
    assert {r[0] for r in con.execute("SELECT symbol FROM processed_episodes")} == {"INSCOPE"}
    con.close()


# --------------------------------------------------------------------------- prospective wiring
def test_prospective_start_stack_passes_the_deployment_flags(monkeypatch, tmp_path):
    from talonx_ops.prospective import proc as _proc
    from talonx_ops.prospective.lock import SingleWriterLock
    # Isolate the single-writer lock onto a tmp ledger -- start_stack() always
    # acquires SingleWriterLock(V2_DB_PATH) internally; without this override
    # this test would take/leak a REAL lock next to the production
    # v2_lane.db (confirmed: a prior run of this exact test left a stray
    # v2_lane.db.startlock, with a fake pid, sitting next to the live
    # ledger). Never touch V2_DB_PATH from a test.
    iso_ledger = tmp_path / "iso_v2_lane.db"
    monkeypatch.setattr(_proc, "SingleWriterLock", lambda _p: SingleWriterLock(iso_ledger))
    captured = []
    monkeypatch.setattr(_proc, "_spawn", lambda argv, **k: (captured.append(argv), 4242)[1])
    monkeypatch.setattr(_proc.time, "sleep", lambda *_: None)
    _proc.start_stack(tmp_path, env={}, tick_seconds=150,
                      pricing_mode="composite-yf", execution_scope="resolved-active-watchlist",
                      deliver=True, transport="telegram", with_checkpoint_daemon=False)
    v2 = next(a for a in captured if "talonx_v2.run" in a)
    assert "--pricing-mode" in v2 and v2[v2.index("--pricing-mode") + 1] == "composite-yf"
    assert "--execution-scope" in v2 and v2[v2.index("--execution-scope") + 1] == "resolved-active-watchlist"
    assert "--deliver" in v2 and "--transport" in v2 and v2[v2.index("--transport") + 1] == "telegram"
    # the isolated lock was taken (and rebound to the fake v2_companion pid,
    # 4242) -- confirms real lock plumbing ran, on the isolated ledger only
    assert iso_ledger.with_suffix(".db.startlock").exists()
    assert not (tmp_path / "v2_lane.db.startlock").exists()
