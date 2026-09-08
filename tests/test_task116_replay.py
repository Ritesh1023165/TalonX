"""
Task 116 -- exact 2-year production replay of V2@1, focused tests.

14 exact V2@1 fingerprint            23 exit fall-forward
15 chronological event visibility    24 EXIT_UNRESOLVED surfaced
16 second-insider activation         25 max concurrent 20
17 stale episode rejection           26 $10k sizing
18 duplicate BUY prevention          27 paper cash reconciliation
19 duplicate SELL prevention         28 alert-payload creation
20 +10-session hold                  29 zero external Telegram sends
21 no EOD flatten                    30 trade-level parity machinery
22 repeatability
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from talonx_v2 import form4_source, pipeline
from talonx_v2.config import V2Config
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store
from talonx_research.replay_engine import (LiveLedgerProtectionError,
                                           assert_research_ledger_path,
                                           run_chronological_replay)
from talonx_research.versioning import v2_fingerprint

PRIMARY = Path("C:/workspace/TalonX")
_HAVE_DATA = (PRIMARY / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet").exists()
BALANCE = 10_000_000.0


def _bars(a="2024-01-01", b="2027-01-01", close=100.0, vol=800_000):
    from talonx_v2 import calendar as v2cal
    sess = [s for s in v2cal._sessions() if date.fromisoformat(a) <= s <= date.fromisoformat(b)]
    return [{"date": s.isoformat(), "open": close, "close": close, "volume": vol} for s in sess]


def _cluster(sym, d1, d2, val=600_000):
    return [dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "1", filing_date=d1,
                 accession=sym + "a1", transaction_value=val, is_officer=True, transaction_code="P"),
            dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "2", filing_date=d2,
                 accession=sym + "a2", transaction_value=val, is_director=True, transaction_code="P")]


def _svc(tmp_path, rows, bars, status="s.json"):
    cfg = V2Config(db_path=str(tmp_path / "results" / "replay_v2_lane.db"), starting_cash_usd=BALANCE)
    (tmp_path / "results").mkdir(exist_ok=True)
    s = V2Service(config=cfg, bar_dirs=[tmp_path], form4_kind="parquet",
                  status_path=str(tmp_path / status))
    s._records = lambda *, as_of: form4_source.from_rows(rows)  # noqa: SLF001
    s._bars = lambda sym: bars                                   # noqa: SLF001
    s._price = lambda sym, d: next(                              # noqa: SLF001
        (b for b in bars if b["date"] == (d.isoformat() if isinstance(d, date) else str(d)[:10])), None)
    return s, V2Store(cfg.db_path)


# ---- 14 exact V2@1 fingerprint ----------------------------------------
def test_14_v2at1_fingerprint_is_frozen():
    assert v2_fingerprint() == "11107198c5b81237"


# ---- 15 chronological event visibility -------------------------------
def test_15_no_future_filing_is_visible(tmp_path):
    rows = _cluster("VIS", "2025-01-06", "2025-06-02")   # 2nd filing far in the future
    s, store = _svc(tmp_path, rows, _bars())
    s.tick(as_of=date(2025, 1, 10))                      # before the 2nd filing
    # only 1 distinct insider is knowable -> no cluster, no entry
    assert store.n_open() == 0 and store.trades() == []


# ---- 16 second-insider activation ---------------------------------
def test_16_activation_at_second_distinct_insider(tmp_path):
    rows = _cluster("ACT", "2025-01-06", "2025-01-08")
    ep = pipeline.detect_episodes(form4_source.from_rows(rows), config=V2Config())[0]
    assert ep.n_distinct_owners == 2
    assert str(ep.activation_filing_date) == "2025-01-08"
    assert ep.eligible_entry_session > date(2025, 1, 8)


# ---- 17 stale episode rejection ---------------------------------
def test_17_stale_episode_skipped_no_cash_mutation(tmp_path):
    rows = _cluster("STALE", "2024-11-01", "2024-11-05")
    s, store = _svc(tmp_path, rows, _bars())
    for _ in range(5):
        st = s.tick(as_of=date(2025, 3, 3))
        assert st["entries_this_tick"] == 0
    ep = pipeline.detect_episodes(form4_source.from_rows(rows), config=V2Config())[0]
    assert store.episode_disposition(ep.episode_id) == "SKIPPED_ENTRY_STALE"
    assert store.cash() == BALANCE and store.trades() == []


# ---- 18 / 19 duplicate BUY / SELL prevention --------------------
def test_18_19_no_duplicate_buy_or_sell_across_ticks(tmp_path):
    rows = _cluster("DUP", "2025-01-06", "2025-01-08")
    s, store = _svc(tmp_path, rows, _bars())
    for d in ("2025-01-13", "2025-01-14", "2025-01-15", "2025-02-03", "2025-02-04"):
        s.tick(as_of=date.fromisoformat(d))
    tr = store.trades()
    buys = [t for t in tr if t["action"] == "BUY"]
    sells = [t for t in tr if t["action"] == "SELL"]
    assert len(buys) == len({b["episode_id"] for b in buys})
    assert len(sells) == len({x["episode_id"] for x in sells})


# ---- 20 +10-session hold + 21 no EOD flatten -------------------
def test_20_21_ten_session_hold_no_eod_flatten(tmp_path):
    rows = _cluster("HOLD", "2025-01-06", "2025-01-08")
    s, store = _svc(tmp_path, rows, _bars())
    s.tick(as_of=date(2025, 1, 13))
    pos = store.open_positions()[0]
    from talonx_v2.calendar import trading_days_elapsed
    held = trading_days_elapsed(date.fromisoformat(str(pos["entry_session"])[:10]),
                                date.fromisoformat(str(pos["target_exit_session"])[:10]))
    assert held == 10
    st = s.tick(as_of=date(2025, 1, 14))
    assert st["eod_forced_flatten"] is False
    from talonx_v2.dashboard_read import eod_view
    assert eod_view(store)["v2_positions_flattened_at_eod"] is False


# ---- 22 repeatability -------------------------------------------
@pytest.mark.skipif(not _HAVE_DATA, reason="primary worktree data not present")
def test_22_chronological_replay_is_repeatable(tmp_path):
    kw = dict(start="2025-01-02", end="2025-03-01",
              bar_dirs=[PRIMARY / "results/task95g_broad_cross_sectional/_daily",
                        PRIMARY / "results/task107a_form4_feasibility/_prices"],
              form4_parquet=PRIMARY / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet",
              starting_cash=BALANCE)
    a = run_chronological_replay(ledger_path=tmp_path / "results" / "a.db", **kw)
    b = run_chronological_replay(ledger_path=tmp_path / "results" / "b.db", **kw)
    assert a.activity["n_buys"] == b.activity["n_buys"]
    assert a.activity["n_sells"] == b.activity["n_sells"]
    assert [t["episode_id"] for t in a.trades] == [t["episode_id"] for t in b.trades]


# ---- 23 exit fall-forward + 24 EXIT_UNRESOLVED -----------------
def test_23_24_exit_fallforward_then_unresolved(tmp_path):
    rows = _cluster("FF", "2025-01-06", "2025-01-08")
    bars = _bars()
    # drop the exact +10td exit bar + the next 5 -> forced to EXIT_UNRESOLVED
    s, store = _svc(tmp_path, rows, bars)
    s.tick(as_of=date(2025, 1, 13))
    pos = store.open_positions()[0]
    tgt = date.fromisoformat(str(pos["target_exit_session"])[:10])
    from talonx_v2.calendar import add_sessions
    drop = {add_sessions(tgt, k).isoformat() for k in range(0, 7)}
    s._price = lambda sym, d: None if (d.isoformat() if isinstance(d, date) else str(d)[:10]) in drop \
        else next((b for b in bars if b["date"] == (d.isoformat() if isinstance(d, date) else str(d)[:10])), None)
    s.tick(as_of=add_sessions(tgt, 8))
    assert len(store.unresolved_positions()) == 1


# ---- 25 max concurrent 20 + 26 $10k sizing + 27 cash recon ----
def test_25_26_27_capacity_sizing_cash(tmp_path):
    rows = []
    for i in range(25):
        rows += _cluster(f"C{i:02d}", "2025-01-06", "2025-01-08")
    s, store = _svc(tmp_path, rows, _bars())
    s.tick(as_of=date(2025, 1, 13))
    opens = store.open_positions()
    assert len(opens) == 20                                  # 21st+ blocked
    for p in opens:
        assert abs(p["position_cost"] - 10_000.0) < 1e-6
    assert abs(store.cash() - (BALANCE - 20 * 10_000.0)) < 1e-6
    buys = [t for t in store.trades() if t["action"] == "BUY"]
    assert len(buys) == 20


# ---- 28 alert payload + 29 zero external sends ----------------
@pytest.mark.skipif(not _HAVE_DATA, reason="primary worktree data not present")
def test_28_29_dry_run_payloads_zero_external(tmp_path):
    res = run_chronological_replay(
        start="2025-01-02", end="2025-02-15",
        ledger_path=tmp_path / "results" / "replay_v2_lane.db",
        bar_dirs=[PRIMARY / "results/task95g_broad_cross_sectional/_daily",
                  PRIMARY / "results/task107a_form4_feasibility/_prices"],
        form4_parquet=PRIMARY / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet",
        starting_cash=BALANCE)
    assert res.external_sends == 0
    for p in res.alert_payloads:
        assert p["dry_run"] and p["transport"] == "NONE"
        assert p["strategy_version"] == "INSIDER_BUY_CLUSTER_V2@1"
        assert p["fingerprint"] == "11107198c5b81237"
        assert p["action"] in ("BUY", "SELL")
        assert p["episode_id"] and p["symbol"]


# ---- 30 trade-level parity machinery + live-ledger guard ------
def test_30_live_ledger_guard_and_parity_keys():
    with pytest.raises(LiveLedgerProtectionError):
        run_chronological_replay(start="2025-01-01", end="2025-01-05",
                                 ledger_path="C:/workspace/TalonX/v2_lane.db", bar_dirs=[])
    assert assert_research_ledger_path("results/task116_v2_production_replay/replay_v2_lane.db")
