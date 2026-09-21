"""
Package 4 -- Whole-Share, Fee-Inclusive Sizing & Precise Accounting.

Targeted tests only, covering P4-B through P4-H. Uses real temporary
SQLite files and, for concurrency claims, genuinely independent
V2Store/V2Service connections -- never a single-connection stand-in.
"""
from __future__ import annotations

import math
import threading
from datetime import date, datetime, timezone

import pytest

from talonx_v2 import calendar as v2cal
from talonx_v2 import paper, pipeline
from talonx_v2.cluster_engine import ClusterEpisode
from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Action, V2Decision, V2Direction
from talonx_v2.service import V2Service
from talonx_v2.sizing import compute_exit_economics, size_whole_shares_fee_inclusive, zero_fee
from talonx_v2.store import V2Store

ACT = date(2026, 8, 14)
BALANCE = 300_000.0
ALLOC = 10_000.0


def _decision(episode_id="ep1", symbol="AAA"):
    return V2Decision(signal_id=f"sig-{episode_id}", episode_id=episode_id, symbol=symbol,
                      direction=V2Direction.BULLISH, action=V2Action.BUY,
                      official_eligible=False, rationale="test",
                      eligible_entry_session=date(2026, 9, 8))


def _entered(tmp_path, *, cash=BALANCE, allocation=ALLOC, symbol="AAA", episode_id="ep1",
            db_name="v.db", entry_price=100.0, fee_fn=None):
    store = V2Store(str(tmp_path / db_name), starting_cash=cash)
    cfg = V2Config(starting_cash_usd=cash, per_position_allocation_usd=allocation)
    outcome = paper.enter_position(store, _decision(episode_id, symbol), entry_price=entry_price,
                                   entry_session=date(2026, 9, 8), config=cfg, fee_fn=fee_fn)
    return store, cfg, outcome


def _ep(entry_session, episode_id, symbol):
    return ClusterEpisode(episode_id=episode_id, symbol=symbol, issuer_cik="x",
                          distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
                          first_filing_date=ACT, activation_filing_date=ACT, last_filing_date=ACT,
                          aggregate_purchase_value=0.0, any_officer=False, any_director=False,
                          any_ten_percent=False,
                          causal_event_ts=datetime(2026, 8, 14, 23, 59, 59, tzinfo=timezone.utc),
                          eligible_entry_session=entry_session)


def _fixed_buy_decision(e):
    liq = type("Liq", (), {"ok": True, "median_dollar_volume": 1e7, "last_close": 10.0})()
    dec = V2Decision(signal_id="s1", episode_id=e.episode_id, symbol=e.symbol,
                     direction=V2Direction.BULLISH, action=V2Action.BUY,
                     official_eligible=False, rationale="test (package4 fixture)",
                     eligible_entry_session=e.eligible_entry_session)
    return liq, dec


def _svc(tmp, db_path, *, name, symbols, starting_cash=BALANCE, alloc=ALLOC):
    import csv
    from talonx_v2 import calendar as vc
    bd = tmp / f"bars_{name}"
    bd.mkdir(exist_ok=True)
    sess = [s for s in vc._sessions() if date(2019, 1, 1) <= s <= date(2027, 12, 31)]
    for sym in symbols:
        with open(bd / f"{sym}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "close", "volume"])
            for s in sess:
                w.writerow([s.isoformat(), 40.0, 40.5, 1_500_000])
    cfg = V2Config(db_path=str(db_path), starting_cash_usd=starting_cash,
                   per_position_allocation_usd=alloc)
    return V2Service(config=cfg, bar_dirs=[bd], form4_kind="parquet",
                     status_path=str(tmp / f"{name}.json"))


def _wire(svc, symbol):
    svc._dissemination_lookup = {(symbol, ACT.isoformat()): datetime(2026, 8, 14, 15, 20, tzinfo=timezone.utc)}
    svc._eval_causal_decision = _fixed_buy_decision


# ======================================================================= #
# P4-B -- whole-share, fee-inclusive sizing (boundary tests)
# ======================================================================= #

def test_p4b_allocation_exactly_fits_n_shares_no_fee():
    r = size_whole_shares_fee_inclusive(price=100.0, allocation_usd=10_000.0, available_cash=10_000.0)
    assert r.ok and r.shares == 100 and r.entry_total == pytest.approx(10_000.0)


def test_p4b_allocation_short_by_smallest_unit_drops_one_share():
    # $10,000 - $0.01: one share's own price ($100) would still fit,
    # but the LAST share (#100) now pushes total to $10,000.00 exactly
    # under a fee -- use a $0.02 shortfall + $0.01/share fee so the
    # boundary is exercised precisely.
    fee = lambda q, p: 0.01 * q
    r = size_whole_shares_fee_inclusive(price=100.0, allocation_usd=9_999.99, available_cash=9_999.99,
                                        fee_fn=fee)
    # 100*100 + 100*0.01 = 10001.00 > 9999.99 -> drop to 99
    assert r.shares == 99
    assert r.entry_total <= 9_999.99


def test_p4b_high_priced_stock_only_one_share_fits():
    r = size_whole_shares_fee_inclusive(price=9_999.0, allocation_usd=10_000.0, available_cash=10_000.0)
    assert r.ok and r.shares == 1


def test_p4b_high_priced_stock_zero_shares_fit():
    r = size_whole_shares_fee_inclusive(price=15_000.0, allocation_usd=10_000.0, available_cash=10_000.0)
    assert r.ok is False and r.shares == 0
    assert r.reason == "ALLOCATION_BELOW_ONE_SHARE"


def test_p4b_fee_causes_quantity_to_fall_from_n_to_n_minus_1():
    fee = lambda q, p: 5.0  # flat
    without_fee = size_whole_shares_fee_inclusive(price=100.0, allocation_usd=10_000.0, available_cash=10_000.0)
    with_fee = size_whole_shares_fee_inclusive(price=100.0, allocation_usd=10_000.0, available_cash=10_000.0,
                                               fee_fn=fee)
    assert without_fee.shares == 100
    assert with_fee.shares == 99
    assert with_fee.entry_total <= 10_000.0


def test_p4b_available_cash_smaller_than_allocation_rejects_not_resizes():
    """Session 10 §C: insufficient cash to reserve the approved
    allocation causes a SKIP, never a smaller reservation."""
    r = size_whole_shares_fee_inclusive(price=100.0, allocation_usd=10_000.0, available_cash=5_000.0)
    assert r.ok is False
    assert r.reason == "INSUFFICIENT_AVAILABLE_CASH"
    assert r.shares == 0  # NOT 50 (which $5,000/$100 would allow)


def test_p4b_awkward_decimal_price_33_33():
    r = size_whole_shares_fee_inclusive(price=33.33, allocation_usd=10_000.0, available_cash=10_000.0)
    assert r.ok
    assert r.shares == 300  # floor(10000/33.33) = 300
    assert r.entry_total == pytest.approx(9_999.0)
    assert r.entry_total <= 10_000.0


def test_p4b_price_from_float_with_inexact_binary_representation():
    # 0.1 + 0.2 = 0.30000000000000004 in raw binary float
    price = (0.1 + 0.2) * 100  # ~30.000000000000004, a genuinely awkward float
    r = size_whole_shares_fee_inclusive(price=price, allocation_usd=1000.0, available_cash=1000.0)
    assert r.ok
    assert r.entry_total <= 1000.0
    # the naive continuous division would have suggested this many
    # shares; whole-share sizing must never exceed it, and must never
    # be corrupted by the float's own binary imprecision into an
    # off-by-one that lets entry_total exceed the allocation.
    assert r.shares <= math.floor(1000.0 / price) + 1
    assert r.shares * price <= 1000.0 + 1e-6


def test_p4b_zero_shares_reject_has_explicit_reason():
    r = size_whole_shares_fee_inclusive(price=0.0, allocation_usd=10_000.0, available_cash=10_000.0)
    assert r.ok is False and r.reason == "BAD_PRICE"


def test_p4b_never_rounds_up():
    r = size_whole_shares_fee_inclusive(price=99.0, allocation_usd=1000.0, available_cash=1000.0)
    # 1000/99 = 10.10... -> must floor to 10, never round to 10.1 or up to 11
    assert r.shares == 10
    assert r.entry_total == pytest.approx(990.0)
    assert 11 * 99.0 > 1000.0  # sanity: 11 genuinely would not fit


def test_p4b_end_to_end_via_enter_position_produces_whole_shares(tmp_path):
    store, cfg, outcome = _entered(tmp_path, cash=BALANCE, allocation=ALLOC, entry_price=37.25)
    assert outcome.entered, outcome.reason
    pos = store.all_positions()[0]
    assert pos["shares"] == float(int(pos["shares"]))  # whole
    assert pos["shares"] == math.floor(ALLOC / 37.25)
    assert pos["position_cost"] <= ALLOC


# ======================================================================= #
# P4-C -- money precision (Decimal boundary, never silently mixed)
# ======================================================================= #

def test_p4c_decimal_boundary_avoids_binary_float_accumulation_error(tmp_path):
    """A price whose naive float division would drift past the
    allocation cap by a sub-cent binary-float error must still be
    correctly rejected/accepted at the TRUE boundary."""
    # construct a price where shares*price in raw binary float is
    # *epsilon* over the allocation even though the "true" decimal
    # value is exactly at the boundary.
    price = 0.1  # 0.1 has no exact binary representation
    r = size_whole_shares_fee_inclusive(price=price, allocation_usd=10.0, available_cash=10.0)
    # true decimal: 10.0 / 0.1 = 100 shares, 100*0.1 = 10.0 exactly
    assert r.shares == 100
    assert r.entry_total <= 10.0


# ======================================================================= #
# P4-D -- reservation semantics
# ======================================================================= #

def test_p4d_creating_reservation_does_not_touch_cash(tmp_path, monkeypatch):
    """Session 10 §B: reservation does not itself alter ledger cash."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="p4d1", symbols=["AAAA"])
    cash_before = svc.store.cash()
    ep = _ep(date(2027, 6, 7), "p4d1-ep1", "AAAA")
    _wire(svc, "AAAA")
    svc._phase_post_close([ep], [ep], today=date(2027, 6, 7), ripe_through=date(2027, 6, 7),
                          is_stale=lambda e: False, live=True)
    assert svc.store.entry_intent("p4d1-ep1")["status"] == "PENDING"
    assert svc.store.cash() == cash_before  # UNCHANGED -- reservation is not a debit


def test_p4d_fill_debits_cash_exactly_once(tmp_path):
    store, cfg, outcome = _entered(tmp_path, cash=BALANCE, allocation=ALLOC, entry_price=100.0)
    assert outcome.entered
    fresh = V2Store(str(tmp_path / "v.db"))
    assert fresh.cash() == pytest.approx(BALANCE - outcome.shares * 100.0)
    assert len(fresh.trades()) == 1


def test_p4d_release_via_expiry_does_not_change_cash(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="p4d3", symbols=["ZZZZ"])
    monday = date(2027, 6, 7)
    ep = _ep(monday, "p4d3-ep1", "ZZZZ")
    _wire(svc, "ZZZZ")
    svc._phase_post_close([ep], [ep], today=monday, ripe_through=monday,
                          is_stale=lambda e: False, live=True)
    cash_before = svc.store.cash()

    svc._phase_post_close([ep], [ep], today=monday, ripe_through=monday,
                          is_stale=lambda e: True, live=True)  # force staleness sweep

    fresh = V2Store(str(db_path))
    assert fresh.entry_intent("p4d3-ep1")["status"] == "EXPIRED_STALE"
    assert fresh.cash() == cash_before  # released, not "refunded" -- cash never touched


def test_p4d_duplicate_fill_attempt_is_refused(tmp_path):
    store, cfg, outcome = _entered(tmp_path, cash=BALANCE, allocation=ALLOC, entry_price=100.0)
    assert outcome.entered
    second = paper.enter_position(store, _decision("ep1", "AAA"), entry_price=100.0,
                                  entry_session=date(2026, 9, 8), config=cfg)
    assert second.entered is False
    fresh = V2Store(str(tmp_path / "v.db"))
    assert len(fresh.all_positions()) == 1
    assert len(fresh.trades()) == 1


def test_p4d_restart_preserves_active_reservation(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="p4d5a", symbols=["RST"])
    monday = date(2027, 6, 7)
    ep = _ep(monday, "p4d5-ep1", "RST")
    _wire(svc, "RST")
    svc._phase_post_close([ep], [ep], today=monday, ripe_through=monday,
                          is_stale=lambda e: False, live=True)
    cash_before = svc.store.cash()

    # simulate restart: a brand-new V2Service/V2Store instance
    svc2 = _svc(tmp_path, db_path, name="p4d5b", symbols=["RST"])
    assert svc2.store.entry_intent("p4d5-ep1")["status"] == "PENDING"
    assert svc2.store.cash() == cash_before


def test_p4d_account_block_still_prevents_new_reservation(tmp_path, monkeypatch):
    """Package 2 behaviour must remain intact under the new sizing path."""
    from talonx_ops import account_blocks
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc = _svc(tmp_path, db_path, name="p4d6", symbols=["BLKD"])
    svc.store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                   reference="x", detail="")
    monday = date(2027, 6, 7)
    ep = _ep(monday, "p4d6-ep1", "BLKD")
    _wire(svc, "BLKD")
    svc._phase_post_close([ep], [ep], today=monday, ripe_through=monday,
                          is_stale=lambda e: False, live=True)
    assert svc.store.entry_intent("p4d6-ep1") is None
    assert svc.store.episode_disposition("p4d6-ep1") == "SKIPPED_ACCOUNT_BLOCKED"


# ======================================================================= #
# P4-E -- exit / realized P&L reconciliation
# ======================================================================= #

def test_p4e_round_trip_cash_reconciles_with_fees(tmp_path):
    """initial_cash - entry_total + exit_net == ending_cash, and
    realized_pnl reconciles to that same cash movement."""
    entry_fee_fn = lambda q, p: 2.5 * q      # illustrative per-share fee, TEST-ONLY
    exit_fee_fn = lambda q, p: 1.5 * q
    store = V2Store(str(tmp_path / "v.db"), starting_cash=BALANCE)
    cfg = V2Config(starting_cash_usd=BALANCE, per_position_allocation_usd=ALLOC)
    outcome = paper.enter_position(store, _decision("ep1", "AAA"), entry_price=100.0,
                                   entry_session=date(2026, 9, 8), config=cfg, fee_fn=entry_fee_fn)
    assert outcome.entered
    cash_after_entry = store.cash()
    pos = store.all_positions()[0]
    entry_total = pos["position_cost"]
    assert entry_total == pytest.approx(pos["shares"] * 100.0 + 2.5 * pos["shares"])

    out = paper.close_position(store, pos, exit_price=110.0, exit_session=date(2026, 9, 22),
                               config=cfg, fee_fn=exit_fee_fn)
    assert out.settled
    fresh = V2Store(str(tmp_path / "v.db"))
    ending_cash = fresh.cash()

    exit_notional = pos["shares"] * 110.0
    exit_fee = 1.5 * pos["shares"]
    exit_net = exit_notional - exit_fee
    assert ending_cash == pytest.approx(cash_after_entry + exit_net)
    assert ending_cash == pytest.approx(BALANCE - entry_total + exit_net)

    realized_pnl = exit_net - entry_total
    assert out.realized_pnl_usd == pytest.approx(realized_pnl)
    closed_pos = fresh.all_positions()[0]
    assert closed_pos["realized_pnl_usd"] == pytest.approx(realized_pnl)


def test_p4e_exit_pnl_uses_authoritative_entry_total_not_notional_alone():
    """Once a non-zero entry fee exists, P&L must be computed against
    entry_total (notional+fee), never re-derived as shares*entry_price
    alone (which would omit the fee)."""
    ee = compute_exit_economics(shares=100.0, exit_price=105.0, entry_total=10_050.0,
                                fee_fn=zero_fee)
    # notional-only cost basis would have been 100*100=10,000 (if entry
    # price were 100) -- but entry_total (10,050, fee-inclusive) is what
    # must be used.
    assert ee.realized_pnl_usd == pytest.approx(10_500.0 - 10_050.0)


def test_p4e_duplicate_settlement_attempt_is_safe(tmp_path):
    store, cfg, outcome = _entered(tmp_path, cash=BALANCE, allocation=ALLOC, entry_price=100.0)
    assert outcome.entered
    pos = store.all_positions()[0]
    out1 = paper.close_position(store, pos, exit_price=105.0, exit_session=date(2026, 9, 22), config=cfg)
    out2 = paper.close_position(store, pos, exit_price=105.0, exit_session=date(2026, 9, 22), config=cfg)
    assert out1.settled is True
    assert out2.settled is False
    fresh = V2Store(str(tmp_path / "v.db"))
    assert len(fresh.trades()) == 2  # one BUY, one SELL -- no duplicate SELL


# ======================================================================= #
# P4-F -- campaign defaults / existing-account preservation
# ======================================================================= #

def test_p4f_new_campaign_file_receives_configured_defaults(tmp_path):
    store = V2Store(str(tmp_path / "new_campaign.db"))  # no starting_cash override -> class default
    assert store.cash() == 100_000.0  # V2Store's own default matches the agreed $100,000


def test_p4f_existing_account_retains_its_cash_when_reopened_with_different_config(tmp_path):
    path = tmp_path / "existing.db"
    store1 = V2Store(str(path), starting_cash=100_000.0)
    outcome = paper.enter_position(
        store1, _decision("ep1", "AAA"), entry_price=100.0, entry_session=date(2026, 9, 8),
        config=V2Config(starting_cash_usd=100_000.0, per_position_allocation_usd=ALLOC))
    assert outcome.entered
    cash_after_trade = store1.cash()
    assert cash_after_trade != 100_000.0  # a real trade happened

    # "restart" with a DIFFERENT configured starting_cash -- must NOT reset.
    store2 = V2Store(str(path), starting_cash=250_000.0)
    assert store2.cash() == cash_after_trade
    assert store2.cash() != 250_000.0


def test_p4f_default_allocation_is_10000_and_configurable(tmp_path):
    default_cfg = V2Config()
    assert default_cfg.per_position_allocation_usd == 10_000.0
    assert default_cfg.starting_cash_usd == 100_000.0
    custom_cfg = V2Config(per_position_allocation_usd=5_000.0, starting_cash_usd=50_000.0)
    assert custom_cfg.per_position_allocation_usd == 5_000.0
    assert custom_cfg.starting_cash_usd == 50_000.0


# ======================================================================= #
# P4-G -- concurrent capacity (cash-limited, independent connections)
# ======================================================================= #

def test_p4g_two_concurrent_admissions_cannot_together_overcommit_cash(tmp_path, monkeypatch):
    """Cash = $15,000, allocation = $10,000/intent -- two DIFFERENT
    episodes, two genuinely independent V2Service/V2Store connections
    racing for admission. Only ONE may reserve; the other must be
    refused for insufficient (unreserved) cash -- proven via SQLite's
    own real write-lock serialization, not a Python threading.Lock."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc_a = _svc(tmp_path, db_path, name="p4g-a", symbols=["CAPA", "CAPB"], starting_cash=15_000.0)
    svc_b = _svc(tmp_path, db_path, name="p4g-b", symbols=["CAPA", "CAPB"], starting_cash=15_000.0)
    monday = date(2027, 6, 7)
    ep_a = _ep(monday, "p4g-ep-a", "CAPA")
    ep_b = _ep(monday, "p4g-ep-b", "CAPB")
    _wire(svc_a, "CAPA")
    _wire(svc_b, "CAPB")

    a_holds_lock = threading.Event()
    release_a = threading.Event()
    real_enqueue = svc_a.store.enqueue_alert

    def _paused_enqueue(*a, **k):
        a_holds_lock.set()
        assert release_a.wait(timeout=10), "test harness stalled"
        return real_enqueue(*a, **k)
    monkeypatch.setattr(svc_a.store, "enqueue_alert", _paused_enqueue)

    def _run_a():
        svc_a._phase_post_close([ep_a], [ep_a], today=monday, ripe_through=monday,
                                is_stale=lambda e: False, live=True)

    def _run_b():
        svc_b._phase_post_close([ep_b], [ep_b], today=monday, ripe_through=monday,
                                is_stale=lambda e: False, live=True)

    t_a = threading.Thread(target=_run_a)
    t_a.start()
    assert a_holds_lock.wait(timeout=5), "writer A never reached its held-lock checkpoint"
    t_b = threading.Thread(target=_run_b)
    t_b.start()
    t_b.join(timeout=0.5)
    assert t_b.is_alive(), "writer B did not block on the real SQLite write lock"
    release_a.set()
    t_a.join(timeout=10)
    t_b.join(timeout=10)
    assert not t_a.is_alive() and not t_b.is_alive()

    fresh = V2Store(str(db_path))
    intents = fresh.all_entry_intents()
    pending = [i for i in intents if i["status"] == "PENDING"]
    rejected_disp = fresh.episode_disposition("p4g-ep-b")
    # exactly one of the two got a real PENDING reservation; the other
    # was refused (capacity gate not authorized to create a second
    # $10,000 reservation against only $15,000 of true cash).
    assert len(pending) == 1
    assert pending[0]["episode_id"] == "p4g-ep-a"
    assert rejected_disp == "REJECTED_CAPACITY_EXCEEDED"


# ======================================================================= #
# P4-H -- accounting invariants (reuse account_blocks, not a parallel system)
# ======================================================================= #

def test_p4h_non_whole_share_position_triggers_ledger_mismatch_block(tmp_path, monkeypatch):
    import talonx_ops.prospective.close as close_mod
    from talonx_ops import account_blocks

    db = tmp_path / "v2_lane.db"
    store, cfg, outcome = _entered(tmp_path, cash=BALANCE, allocation=ALLOC,
                                   entry_price=100.0, db_name="v2_lane.db")
    assert outcome.entered
    # simulate corruption: directly force a fractional share count onto
    # the persisted row (bypassing the now-whole-share-only sizing path
    # -- exactly the invariant this check exists to catch if it were
    # ever reintroduced by a future bug).
    import sqlite3
    with sqlite3.connect(str(db)) as raw:
        raw.execute("UPDATE positions SET shares = 12.5")
        raw.commit()

    monkeypatch.setattr(close_mod, "V2_DB_PATH", str(db))
    # RI-1: this store's own `campaign.starting_cash_usd` is already
    # authoritatively BALANCE (seeded at creation) -- this patch is
    # belt-and-suspenders, not load-bearing.
    import talonx_ops.prospective.campaign_cash as campaign_cash_mod
    monkeypatch.setattr(campaign_cash_mod, "CAMPAIGN_STARTING_CASH", BALANCE)
    rec, asserts, findings = close_mod._v2_reconcile()
    assert asserts["whole_share_positions"] == "FAIL"

    recorded = close_mod._record_v2_reconciliation_blocks(asserts, findings)
    assert recorded
    fresh = V2Store(str(db))
    assert fresh.blocked_reason() is not None
    active = fresh.active_account_blocks()
    assert any(b["reference"] == "whole_share_positions" for b in active)


def test_p4h_invalid_cost_basis_triggers_ledger_mismatch_block(tmp_path, monkeypatch):
    import talonx_ops.prospective.close as close_mod

    db = tmp_path / "v2_lane.db"
    store, cfg, outcome = _entered(tmp_path, cash=BALANCE, allocation=ALLOC,
                                   entry_price=100.0, db_name="v2_lane.db")
    assert outcome.entered
    import sqlite3
    with sqlite3.connect(str(db)) as raw:
        raw.execute("UPDATE positions SET position_cost = -50.0")
        raw.commit()

    monkeypatch.setattr(close_mod, "V2_DB_PATH", str(db))
    # RI-1: this store's own `campaign.starting_cash_usd` is already
    # authoritatively BALANCE (seeded at creation) -- this patch is
    # belt-and-suspenders, not load-bearing.
    import talonx_ops.prospective.campaign_cash as campaign_cash_mod
    monkeypatch.setattr(campaign_cash_mod, "CAMPAIGN_STARTING_CASH", BALANCE)
    rec, asserts, findings = close_mod._v2_reconcile()
    assert asserts["positive_finite_position_cost"] == "FAIL"

    recorded = close_mod._record_v2_reconciliation_blocks(asserts, findings)
    assert recorded


def test_p4h_healthy_ledger_produces_no_invariant_blocks(tmp_path, monkeypatch):
    import talonx_ops.prospective.close as close_mod

    db = tmp_path / "v2_lane.db"
    store, cfg, outcome = _entered(tmp_path, cash=BALANCE, allocation=ALLOC,
                                   entry_price=100.0, db_name="v2_lane.db")
    assert outcome.entered

    monkeypatch.setattr(close_mod, "V2_DB_PATH", str(db))
    # RI-1: this store's own `campaign.starting_cash_usd` is already
    # authoritatively BALANCE (seeded at creation) -- this patch is
    # belt-and-suspenders, not load-bearing.
    import talonx_ops.prospective.campaign_cash as campaign_cash_mod
    monkeypatch.setattr(campaign_cash_mod, "CAMPAIGN_STARTING_CASH", BALANCE)
    rec, asserts, findings = close_mod._v2_reconcile()
    assert asserts["whole_share_positions"] == "PASS"
    assert asserts["positive_finite_position_cost"] == "PASS"
    recorded = close_mod._record_v2_reconciliation_blocks(asserts, findings)
    assert recorded == []
