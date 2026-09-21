"""PQ-2A CLOSURE -- fractional-entitlement decision + dividend TOTAL-RETURN accounting.

Deterministic; no network/broker/production DB.  Reuses the PQ-2A fixture world
(entry open 25.00 -> 400 sh -> cost $10,000 on a SPLIT_ADJUSTED, dividend-unadjusted basis).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

import test_pq2a_corporate_actions as base
from test_pq2a_corporate_actions import (
    CFG, ENTRY, TARGET, ENTRY_BASIS, _World, guard_with, row)
from talonx_v2 import calendar as v2cal, corporate_actions as ca, dividends as dv, paper, pipeline
from talonx_v2.corporate_actions import (
    CorporateActionGuard, StaticCorporateActionSource, make_dividend_event, make_split_event,
    make_unsupported_event)
from talonx_v2.sizing import size_whole_shares_fee_inclusive
from talonx_v2.store import V2Store

EXIT_BASIS = "2026-09-23"


def ex_at(n):                        # n sessions after entry
    return v2cal.add_sessions(ENTRY, n)


def div(n=3, rate="0.50", pay_days=7, **kw):
    ex = ex_at(n) if isinstance(n, int) else n
    return make_dividend_event("PQX", ex, rate, payable_date=ex + timedelta(days=pay_days), **kw)


def payable(ev):
    return ev.payable_date


def close_with(w, *events, as_of=None):
    w.add_exit_bar(TARGET, 27.0, basis=EXIT_BASIS)
    g = guard_with(*events)
    w.settle(g, as_of=as_of)
    return g


# =========================================================================== #
# DECISION 1 -- fractional post-corporate-action entitlement (items 1-5)
# =========================================================================== #
def test_01_new_entry_sizing_is_whole_share_only_and_unchanged():
    assert size_whole_shares_fee_inclusive(price=25.0, allocation_usd=10_000.0, available_cash=300_000.0).shares == 400
    assert size_whole_shares_fee_inclusive(price=30.0, allocation_usd=10_000.0, available_cash=300_000.0).shares == 333
    assert size_whole_shares_fee_inclusive(price=7000.0, allocation_usd=10_000.0, available_cash=300_000.0).shares == 1
    r = size_whole_shares_fee_inclusive(price=20_000.0, allocation_usd=10_000.0, available_cash=300_000.0)
    assert (r.ok, r.shares) == (False, 0)                          # never a fractional NEW entry


def _direct_position(tmp_path, *, shares, price, name="d", campaign="V2", entry_state="SPLIT_ADJUSTED"):
    store = V2Store(str(tmp_path / f"{name}.db"), starting_cash=300_000.0, campaign_id=campaign)
    prov = {"provider": "fixture", "field": "open", "session": ENTRY.isoformat(),
            "basis_as_of": ENTRY_BASIS, "adjustment_state": entry_state}
    pid = store.insert_open_position(
        episode_id=f"ep-{name}", symbol="PQX", issuer_cik="", entry_session=ENTRY, target_exit_session=TARGET,
        entry_price=price, shares=shares, position_cost=shares * price, price_provenance=prov)
    store.set_cash(300_000.0 - shares * price)
    return store, pid


def _settle_direct(store, *, exit_close, events, as_of=TARGET, exit_state="SPLIT_ADJUSTED", exit_session=TARGET,
                   exit_basis=EXIT_BASIS):
    def price_lookup(sym, session):
        if session != exit_session:
            return None
        return {"open": exit_close, "close": exit_close, "volume": 1_000_000,
                "_provenance": {"provider": "fixture", "session": session.isoformat(), "basis_as_of": exit_basis,
                                "adjustment_state": exit_state, "finality": "FINAL"}}
    g = guard_with(*events)
    res = pipeline.settle_due_exits(store=store, as_of_session=as_of, price_lookup=price_lookup,
                                    config=CFG, corporate_actions=g)
    return g, res


def test_02_to_05_reverse_split_yields_exact_half_share_no_truncate_no_roundup_no_cash_in_lieu(tmp_path):
    store, pid = _direct_position(tmp_path, shares=5, price=100.0)
    cash_before = store.cash()
    g = guard_with(make_split_event("PQX", ex_at(4), 1, 10))
    pipeline.sweep_corporate_actions(store=store, as_of=ex_at(6), guard=g)
    eff = store.effective_shares_exact(pid)
    assert eff == Fraction(1, 2)                                   # 2: exactly 0.5
    assert eff != 0                                                # 3: not truncated to zero
    assert eff != 1                                                # 4: not rounded up
    assert store.cash() == cash_before                             # 5: no cash-in-lieu fabricated
    assert [t["action"] for t in store.trades()] == [] and store.dividend_entitlements() == []
    assert store.all_positions()[0]["shares"] == 5.0               # original ENTRY quantity untouched (whole)


# =========================================================================== #
# DECISION 2 -- dividends, TOTAL RETURN (items 6-34)
# =========================================================================== #
def test_06_07_eligible_dividend_entry_before_ex_date_held_through_it(tmp_path):
    w = _World(tmp_path)
    ev = div(3, "0.50")
    close_with(w, ev)
    pos = w.position()
    ents = w.store.dividend_entitlements()
    assert len(ents) == 1
    e = ents[0]
    assert (e["state"], e["symbol"], e["ex_date"], e["rate"], e["eligible_qty"]) == (
        "ACCRUED", "PQX", ev.ex_date.isoformat(), "0.5", "400")
    assert e["amount_usd"] == 200.0                                # 400 sh x $0.50
    assert (e["campaign_id"], e["account_id"], e["position_id"], e["episode_id"]) == (
        "V2", "V2", pos["position_id"], pos["episode_id"])
    assert w.store.cash() == pytest.approx(300_000.0 + pos["realized_pnl_usd"])      # NO cash before payable


def test_08_entry_on_or_after_ex_date_is_not_eligible(tmp_path):
    for n, name in ((0, "onEntryDay"), (-2, "beforeEntry")):
        w = _World(tmp_path, name=name)
        close_with(w, div(n, "0.50"))
        assert w.position()["status"] == "CLOSED" and w.store.dividend_entitlements() == []


def test_09_exit_before_ex_date_is_not_eligible(tmp_path):
    w = _World(tmp_path)
    close_with(w, make_dividend_event(
        "PQX", v2cal.add_sessions(TARGET, 1), "0.50", payable_date=TARGET + timedelta(days=9)))
    assert w.position()["status"] == "CLOSED" and w.store.dividend_entitlements() == []


def test_exit_ON_the_ex_date_is_eligible_by_definition(tmp_path):
    """Sold at the close of the ex-date session = owned through the prior close -> keeps the dividend."""
    w = _World(tmp_path)
    close_with(w, make_dividend_event("PQX", TARGET, "0.50", payable_date=TARGET + timedelta(days=7)))
    assert [e["amount_usd"] for e in w.store.dividend_entitlements()] == [200.0]


def test_10_11_receivable_survives_exit_and_is_credited_after_the_trade_is_closed(tmp_path):
    w = _World(tmp_path)
    ev = div(3, "0.50", pay_days=12)                               # payable AFTER the +10 exit
    g = close_with(w, ev)
    pos_before = dict(w.position())
    assert pos_before["status"] == "CLOSED" and ev.payable_date > TARGET
    # not yet payable -> nothing credited, receivable retained
    out = dv.settle_receivables(w.store, g, as_of=ev.payable_date - timedelta(days=1))
    assert [o["status"] for o in out] == ["NOT_YET_PAYABLE"] and w.store.dividends_credited_total() == 0.0
    cash0 = w.store.cash()
    out = dv.settle_receivables(w.store, g, as_of=ev.payable_date)
    assert [o["status"] for o in out] == ["CREDITED"]
    assert w.store.cash() == pytest.approx(cash0 + 200.0)
    # the CLOSED trade row was never touched to attach the dividend
    assert dict(w.position()) == pos_before
    e = w.store.dividend_entitlements()[0]
    assert (e["state"], e["credited_as_of"], e["cash_after"]) == ("CREDITED", ev.payable_date.isoformat(),
                                                                  pytest.approx(cash0 + 200.0))


def test_12_multiple_dividends_are_independent(tmp_path):
    w = _World(tmp_path)
    e1, e2 = div(2, "0.10", pay_days=3), div(6, "0.20", pay_days=20)
    g = close_with(w, e1, e2)
    ents = w.store.dividend_entitlements()
    assert sorted(e["amount_usd"] for e in ents) == [40.0, 80.0]
    dv.settle_receivables(w.store, g, as_of=e1.payable_date)                 # only the first is payable
    assert {e["ex_date"]: e["state"] for e in w.store.dividend_entitlements()} == {
        e1.ex_date.isoformat(): "CREDITED", e2.ex_date.isoformat(): "ACCRUED"}
    assert w.store.dividends_credited_total() == 40.0
    dv.settle_receivables(w.store, g, as_of=e2.payable_date)
    assert w.store.dividends_credited_total() == 120.0


def test_13_14_duplicate_provider_event_repeated_polls_and_restart_never_double_credit(tmp_path):
    w = _World(tmp_path)
    ev = div(3, "0.50", provider_id="alp-A")
    dup = make_dividend_event("PQX", ev.ex_date, "0.500", provider_id="alp-B-DIFFERENT-ID",
                              payable_date=ev.payable_date)                  # same content, new id, "0.500"
    g = close_with(w, ev, dup)
    assert len(w.store.dividend_entitlements()) == 1
    cash0 = w.store.cash()
    for _ in range(3):                                                        # repeated polls
        dv.settle_receivables(w.store, g, as_of=ev.payable_date)
    assert w.store.cash() == pytest.approx(cash0 + 200.0)
    restarted = V2Store(w.db)                                                 # restart: new process, same ledger
    for _ in range(2):
        dv.settle_receivables(restarted, guard_with(ev, dup), as_of=ev.payable_date + timedelta(days=1))
    assert restarted.cash() == pytest.approx(cash0 + 200.0)
    assert restarted.dividends_credited_total() == 200.0
    # the direct once-only gate: a stale caller crediting the SAME entitlement again is a no-op
    eid = restarted.dividend_entitlements()[0]["entitlement_id"]
    assert restarted.credit_dividend(eid, as_of=ev.payable_date) is False
    # a second settlement attempt (same position) does not create a second entitlement either
    assert restarted.record_dividend_entitlement(position_id=w.pos["position_id"], event=ev, exit_session=TARGET) is False


@pytest.mark.parametrize("rate", [None, "abc", "", 0, "0", -0.5, float("nan"), float("inf")])
def test_15_16_malformed_zero_negative_nan_amount_is_rejected_and_never_credited(tmp_path, rate):
    e = ca.classify_alpaca_record("PQX", "cash_dividends",
                                  {"id": "x", "ex_date": ex_at(3).isoformat(), "rate": rate,
                                   "payable_date": (ex_at(3) + timedelta(days=5)).isoformat()},
                                  source="t", received_at_utc="t")
    assert e.kind == ca.KIND_UNSUPPORTED and "rate" in e.malformed
    w = _World(tmp_path, name=f"m{abs(hash(str(rate)))}")
    w.add_exit_bar(TARGET, 27.0, basis=EXIT_BASIS)
    w.settle(guard_with(e))
    pos = w.position()
    assert pos["status"] == "EXIT_UNRESOLVED" and pos["realized_pnl_usd"] is None
    assert w.store.dividend_entitlements() == [] and w.store.cash() == 290_000.0


def test_17_special_foreign_and_stock_dividends_are_not_treated_as_ordinary_cash(tmp_path):
    base_rec = {"id": "x", "ex_date": ex_at(3).isoformat(), "rate": 0.5,
                "payable_date": (ex_at(3) + timedelta(days=5)).isoformat()}
    special = ca.classify_alpaca_record("PQX", "cash_dividends", {**base_rec, "special": True},
                                        source="t", received_at_utc="t")
    foreign = ca.classify_alpaca_record("PQX", "cash_dividends", {**base_rec, "foreign": True},
                                        source="t", received_at_utc="t")
    stock = ca.classify_alpaca_record("PQX", "stock_dividends", base_rec, source="t", received_at_utc="t")
    ordinary = ca.classify_alpaca_record("PQX", "cash_dividends", {**base_rec, "special": False, "foreign": False},
                                         source="t", received_at_utc="t")
    assert [x.kind for x in (special, foreign, stock, ordinary)] == [
        ca.KIND_UNSUPPORTED, ca.KIND_UNSUPPORTED, ca.KIND_UNSUPPORTED, ca.KIND_CASH_DIVIDEND]
    assert "special" in special.malformed and "foreign" in foreign.malformed
    for i, ev in enumerate((special, foreign, stock)):
        w = _World(tmp_path, name=f"u{i}")
        w.add_exit_bar(TARGET, 27.0, basis=EXIT_BASIS)
        w.settle(guard_with(ev))
        assert w.position()["status"] == "EXIT_UNRESOLVED" and w.store.dividend_entitlements() == []
        assert w.store.blocked_action_rows(w.pos["position_id"])[0]["status"].startswith("BLOCKED_CA_")


def test_unsupported_dividend_effective_AFTER_the_exit_is_irrelevant(tmp_path):
    w = _World(tmp_path)
    late_special = ca.classify_alpaca_record(
        "PQX", "cash_dividends", {"id": "s", "ex_date": v2cal.add_sessions(TARGET, 1).isoformat(), "rate": 1.0,
                                  "special": True}, source="t", received_at_utc="t")
    close_with(w, late_special)
    assert w.position()["status"] == "CLOSED"


def test_18_split_then_dividend_uses_the_post_split_quantity(tmp_path):
    """10 sh -> 10:1 split -> 100 sh -> later $0.20/share  =>  $20 (not $2, not $200)."""
    store, pid = _direct_position(tmp_path, shares=10, price=100.0)
    dvd = make_dividend_event("PQX", ex_at(6), "0.20", payable_date=ex_at(6) + timedelta(days=5))
    g, _ = _settle_direct(store, exit_close=11.0, events=[make_split_event("PQX", ex_at(3), 10, 1), dvd])
    e = store.dividend_entitlements()[0]
    assert (e["eligible_qty"], e["amount_usd"]) == ("100", 20.0)
    assert store.all_positions()[0]["realized_pnl_usd"] == pytest.approx(100.0)   # 100 sh x $11 - $1,000
    # dividend BEFORE the split is on the PRE-split basis: 10 sh x $2.00 = $20 (rate raw as of that ex-date)
    store2, pid2 = _direct_position(tmp_path, shares=10, price=100.0, name="before")
    pre = make_dividend_event("PQX", ex_at(2), "2.00", payable_date=ex_at(2) + timedelta(days=5))
    _settle_direct(store2, exit_close=11.0, events=[make_split_event("PQX", ex_at(5), 10, 1), pre])
    e2 = store2.dividend_entitlements()[0]
    assert (e2["eligible_qty"], e2["amount_usd"]) == ("10", 20.0)


def test_split_and_dividend_on_the_same_ex_date_is_ambiguous_and_fails_closed(tmp_path):
    store, pid = _direct_position(tmp_path, shares=10, price=100.0)
    _settle_direct(store, exit_close=11.0, events=[
        make_split_event("PQX", ex_at(4), 10, 1),
        make_dividend_event("PQX", ex_at(4), "0.20", payable_date=ex_at(4) + timedelta(days=5))])
    pos = store.all_positions()[0]
    assert pos["status"] == "EXIT_UNRESOLVED" and store.dividend_entitlements() == []
    assert store.blocked_action_rows(pid)[0]["status"] == "BLOCKED_CA_DIVIDEND_SPLIT_SAME_EX_DATE"


def test_split_already_reflected_in_the_entry_basis_undoes_for_an_earlier_dividend(tmp_path):
    """Entry shares are on basis B_e (post-split).  A dividend BEFORE that split's ex-date was paid on
    the smaller pre-split share count: qty = entry shares / R."""
    store = V2Store(str(tmp_path / "refl.db"), starting_cash=300_000.0)
    late_basis = ex_at(5)
    prov = {"provider": "f", "field": "open", "session": ENTRY.isoformat(), "basis_as_of": late_basis.isoformat(),
            "adjustment_state": "SPLIT_ADJUSTED"}
    pid = store.insert_open_position(episode_id="e", symbol="PQX", issuer_cik="", entry_session=ENTRY,
                                     target_exit_session=TARGET, entry_price=2.5, shares=1000,
                                     position_cost=2500.0, price_provenance=prov)
    store.set_cash(297_500.0)
    _settle_direct(store, exit_close=2.7, events=[
        make_split_event("PQX", ex_at(4), 10, 1),                      # ex < B_e => reflected
        make_dividend_event("PQX", ex_at(2), "1.00", payable_date=ex_at(2) + timedelta(days=5))])
    e = store.dividend_entitlements()[0]
    assert (e["eligible_qty"], e["amount_usd"]) == ("100", 100.0)      # 1000 / 10 pre-split shares x $1.00


def test_19_reverse_split_then_dividend_uses_the_fractional_entitlement(tmp_path):
    store, pid = _direct_position(tmp_path, shares=5, price=100.0)
    dvd = make_dividend_event("PQX", ex_at(6), "1.00", payable_date=ex_at(6) + timedelta(days=5))
    _settle_direct(store, exit_close=1050.0, events=[make_split_event("PQX", ex_at(3), 1, 10), dvd])
    e = store.dividend_entitlements()[0]
    assert (e["eligible_qty"], e["amount_usd"]) == ("1/2", 0.5)         # 0.5 sh x $1.00
    # exact amount preserved; cents rounding ROUND_HALF_UP once: 33.3 sh x $0.15 = 4.995 -> $5.00
    store2, _ = _direct_position(tmp_path, shares=333, price=30.0, name="frac")
    _settle_direct(store2, exit_close=330.0, events=[
        make_split_event("PQX", ex_at(3), 1, 10),
        make_dividend_event("PQX", ex_at(6), "0.15", payable_date=ex_at(6) + timedelta(days=5))])
    e2 = store2.dividend_entitlements()[0]
    assert (e2["eligible_qty"], Decimal(e2["amount_exact"]), e2["amount_usd"]) == ("333/10", Decimal("4.995"), 5.0)


def test_20_same_symbol_two_campaigns_only_the_eligible_one_receives_it(tmp_path):
    """Campaign A holds through the ex-date; campaign B (different window, its own ledger) enters after it."""
    ev = div(3, "0.50")
    a = _World(tmp_path, name="campA")
    close_with(a, ev)
    # B enters ON the ex-date session (=> bought ex-dividend) and exits later
    b = _World(tmp_path, name="campB")
    with sqlite3.connect(b.db) as con:
        con.execute("UPDATE positions SET entry_session=?", (ev.ex_date.isoformat(),))
    b.add_exit_bar(TARGET, 27.0, basis=EXIT_BASIS)
    b.settle(guard_with(ev))
    assert [e["amount_usd"] for e in a.store.dividend_entitlements()] == [200.0]
    assert b.store.dividend_entitlements() == []
    dv.settle_receivables(a.store, guard_with(ev), as_of=ev.payable_date)
    dv.settle_receivables(b.store, guard_with(ev), as_of=ev.payable_date)
    assert a.store.dividends_credited_total() == 200.0 and b.store.dividends_credited_total() == 0.0
    # explicit campaign/account lineage on every entitlement row
    named = V2Store(str(tmp_path / "named.db"), starting_cash=300_000.0, campaign_id="CAMP-X")
    pid = named.insert_open_position(episode_id="n", symbol="PQX", issuer_cik="", entry_session=ENTRY,
                                     target_exit_session=TARGET, entry_price=25.0, shares=400,
                                     position_cost=10_000.0)
    named.record_dividend_entitlement(position_id=pid, event=ev, exit_session=TARGET)
    r = named.dividend_entitlements()[0]
    assert (r["campaign_id"], r["account_id"]) == ("CAMP-X", "CAMP-X")


def test_21_22_price_pnl_plus_dividend_pnl_reconstructs_total_and_cash_agrees(tmp_path):
    w = _World(tmp_path)
    ev = div(3, "0.50")
    g = close_with(w, ev)
    price_pnl = w.position()["realized_pnl_usd"]
    assert price_pnl == pytest.approx(400 * 27.0 - 10_000.0)             # $800 price P&L, fee-inclusive basis
    cash_pre = w.store.cash()
    assert cash_pre == pytest.approx(300_000.0 + price_pnl)              # receivable is NOT cash
    dv.settle_receivables(w.store, g, as_of=ev.payable_date)
    div_pnl = w.store.dividends_credited_total()
    assert div_pnl == 200.0
    total = price_pnl + div_pnl
    assert total == pytest.approx(1000.0)
    assert w.store.cash() == pytest.approx(300_000.0 + total)            # cash == starting + total return, exactly
    perf = __import__("talonx_ops.paper_performance", fromlist=["x"]).build_v2_paper_performance(Path(w.db))
    assert perf["reconciliation"]["status"] == "EXACT"
    assert perf["realized_pnl"]["campaign_to_date"] == pytest.approx(price_pnl)
    assert perf["dividend_pnl"]["credited_usd"] == 200.0
    assert perf["total_return_pnl"]["realized_price_plus_credited_dividends"] == pytest.approx(total)
    ct = perf["closed_trades"][0]
    assert (ct["price_pnl_usd"], ct["dividend_pnl_usd"], ct["total_return_pnl_usd"]) == (
        pytest.approx(price_pnl), 200.0, pytest.approx(total))


def test_accrued_receivable_is_an_asset_in_equity_but_not_cash(tmp_path):
    w = _World(tmp_path)
    close_with(w, div(3, "0.50", pay_days=15))
    perf = __import__("talonx_ops.paper_performance", fromlist=["x"]).build_v2_paper_performance(Path(w.db))
    assert perf["dividend_pnl"] == {"credited_usd": 0.0, "accrued_receivable_usd": 200.0,
                                    "source": "v2_lane.db.dividend_entitlements"}
    assert perf["reconciliation"]["status"] == "EXACT"
    assert perf["equity"]["value"] == pytest.approx(w.store.cash() + 200.0)


def _reconcile(tmp_path, monkeypatch, db):
    from talonx_ops.prospective import close
    monkeypatch.setattr(close, "V2_DB_PATH", db)
    monkeypatch.setattr(close, "V2_STATUS_PATH", str(tmp_path / "no_status.json"))
    return close._v2_reconcile()


def test_23_reconciliation_accepts_correct_dividend_accounting(tmp_path, monkeypatch):
    w = _World(tmp_path)
    ev = div(3, "0.50")
    g = close_with(w, ev)
    for stage in ("accrued", "credited"):
        rec, asserts, findings = _reconcile(tmp_path, monkeypatch, w.db)
        for k in ("dividend_accounting_consistent", "cash_plus_open_cost_reconciles", "no_negative_cash",
                  "buys_eq_sells_plus_open_plus_unresolved", "corporate_action_adjustments_consistent"):
            assert asserts[k] == "PASS", (stage, k, findings)
        if stage == "accrued":
            assert rec["dividends_accrued_usd"] == 200.0 and rec["dividends_credited_usd"] == 0.0
            dv.settle_receivables(w.store, g, as_of=ev.payable_date)
    rec2, _, _ = _reconcile(tmp_path, monkeypatch, w.db)
    assert rec2["dividends_credited_usd"] == 200.0 and rec2["total_return_pnl_usd"] == pytest.approx(1000.0)
    from talonx_ops.prospective import ledger_guard
    assert not any("dividend" in p or "cash accounting" in p
                   for p in ledger_guard.check_ledger_continuity(w.db).problems)


def test_24_reconciliation_detects_duplicate_missing_credit_and_impossible_lineage(tmp_path, monkeypatch):
    w = _World(tmp_path)
    ev = div(3, "0.50")
    g = close_with(w, ev)
    dv.settle_receivables(w.store, g, as_of=ev.payable_date)
    # (a) MISSING expected credit: the ledger says CREDITED but cash never received it
    con = sqlite3.connect(w.db)
    con.execute("UPDATE portfolio SET cash = cash - 200.0"); con.commit(); con.close()
    _, asserts, findings = _reconcile(tmp_path, monkeypatch, w.db)
    assert asserts["cash_plus_open_cost_reconciles"] == "FAIL" and any("credited_dividends" in f for f in findings)
    con = sqlite3.connect(w.db); con.execute("UPDATE portfolio SET cash = cash + 200.0"); con.commit(); con.close()
    # (b) DUPLICATE credit: a second CREDITED row for the same position/ex-date under another key
    con = sqlite3.connect(w.db)
    con.execute("INSERT INTO dividend_entitlements (campaign_id,account_id,position_id,episode_id,symbol,action_key,"
                "ex_date,payable_date,rate,eligible_qty,amount_exact,amount_usd,state,accrued_at_utc,credited_as_of,"
                "cash_after) SELECT campaign_id,account_id,position_id,episode_id,symbol,'DIV|DUP',ex_date,payable_date,"
                "rate,eligible_qty,amount_exact,amount_usd,'CREDITED',accrued_at_utc,credited_as_of,cash_after "
                "FROM dividend_entitlements LIMIT 1")
    con.commit()
    probs = dv.problems(con)
    con.close()
    assert any("duplicate dividend entitlement" in p for p in probs)
    _, asserts, findings = _reconcile(tmp_path, monkeypatch, w.db)
    assert asserts["dividend_accounting_consistent"] == "FAIL" and asserts["cash_plus_open_cost_reconciles"] == "FAIL"
    # (c) impossible lineage / wrong quantity / ineligible ex-date / credit before payable
    w2 = _World(tmp_path, name="lin")
    close_with(w2, ev)
    con = sqlite3.connect(w2.db)
    con.execute("UPDATE dividend_entitlements SET eligible_qty='4000'")
    assert any("eligible_qty" in p for p in dv.problems(con))
    con.execute("UPDATE dividend_entitlements SET eligible_qty='400', ex_date=?", (ENTRY.isoformat(),))
    assert any("ineligible" in p for p in dv.problems(con))
    con.execute("UPDATE dividend_entitlements SET ex_date=?, position_id=999", (ev.ex_date.isoformat(),))
    assert any("lineage broken" in p for p in dv.problems(con))
    con.execute("UPDATE dividend_entitlements SET position_id=?, state='CREDITED', credited_as_of=?, cash_after=1.0",
                (w2.pos["position_id"], (ev.payable_date - timedelta(days=1)).isoformat()))
    assert any("credited before payable date" in p for p in dv.problems(con))
    con.execute("UPDATE dividend_entitlements SET state='ACCRUED', credited_as_of=NULL, cash_after=NULL")
    con.commit()
    assert any("overdue" in p for p in dv.problems(con, as_of=ev.payable_date + timedelta(days=30)))
    assert not any("overdue" in p for p in dv.problems(con, as_of=ev.payable_date + timedelta(days=2)))
    con.close()


def test_25_operator_view_is_read_only_and_shows_the_dividend(tmp_path):
    w = _World(tmp_path)
    ev = div(3, "0.50")
    close_with(w, ev)
    snapshot = lambda: sqlite3.connect(w.db).execute(   # noqa: E731
        "SELECT COUNT(*), SUM(entitlement_id), (SELECT cash FROM portfolio) FROM dividend_entitlements").fetchone()
    before = snapshot()
    ro = sqlite3.connect(f"file:{w.db}?mode=ro", uri=True)
    items = dv.rows(ro)
    assert [(i["symbol"], i["ex_date"], i["rate"], i["eligible_qty"], i["amount_usd"], i["state"]) for i in items] == [
        ("PQX", ev.ex_date.isoformat(), "0.5", "400", 200.0, "ACCRUED")]
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM dividend_entitlements")
    ro.close()
    from talonx_ops.paper_performance import build_v2_paper_performance
    perf = build_v2_paper_performance(Path(w.db))
    assert perf["dividends"][0]["state"] == "ACCRUED" and perf["dividends"][0]["amount_usd"] == 200.0
    assert snapshot() == before                                     # reading changed nothing


def test_26_dividend_provenance_is_retained(tmp_path):
    w = _World(tmp_path)
    ev = div(3, "0.50", provider_id="alpaca-uuid-1")
    close_with(w, ev)
    e = w.store.dividend_entitlements()[0]
    prov = json.loads(e["provenance_json"])
    assert prov["sources"][0]["provider_id"] == "alpaca-uuid-1" and prov["sources"][0]["received_at_utc"]
    assert prov["sources"][0]["source"] == "static"
    reg = [r for r in w.store.corporate_action_registry() if r["kind"] == "CASH_DIVIDEND"][0]
    assert reg["action_key"] == e["action_key"] == f"DIV|PQX|{ev.ex_date.isoformat()}|0.5"
    assert (e["ex_date"], e["payable_date"], e["rate"]) == (ev.ex_date.isoformat(), ev.payable_date.isoformat(), "0.5")


def test_27_legacy_rows_are_never_backfilled(tmp_path):
    store = V2Store(str(tmp_path / "legacy.db"), starting_cash=300_000.0)
    pid = store.insert_open_position(episode_id="legacy", symbol="PQX", issuer_cik="", entry_session=ENTRY,
                                     target_exit_session=TARGET, entry_price=25.0, shares=400, position_cost=10_000.0)
    store.set_cash(290_000.0)
    p = store.all_positions()[0]
    g = guard_with()                                             # no dividend -> settles exactly as before
    assert g.assess_position(store, p, as_of=TARGET, exit_basis_as_of=TARGET, exit_session=TARGET,
                             exit_adjustment_state=None, settlement=True).status == ca.V_CLEAR
    assert store.dividend_entitlements() == [] and store.all_positions()[0]["entry_price_provenance"] is None
    # a dividend in the window of a legacy (basis-unknown) position is NOT fabricated: fail closed
    g2 = guard_with(div(3, "0.50"))
    v = g2.assess_position(store, p, as_of=TARGET, exit_basis_as_of=TARGET, exit_session=TARGET,
                           exit_adjustment_state="SPLIT_ADJUSTED", settlement=True)
    assert v.status == ca.V_BLOCK and v.code == ca.C_DIVIDEND_BASIS and store.dividend_entitlements() == []


@pytest.mark.parametrize("entry_state,exit_state", [
    ("SPLIT_DIVIDEND_ADJUSTED", "SPLIT_ADJUSTED"), ("SPLIT_ADJUSTED", "SPLIT_DIVIDEND_ADJUSTED"),
    ("UNKNOWN_LEGACY_CSV", "SPLIT_ADJUSTED"), (None, "SPLIT_ADJUSTED")])
def test_no_double_count_a_dividend_adjusted_or_unknown_fill_basis_fails_closed(tmp_path, entry_state, exit_state):
    """Crediting cash on top of a dividend-ADJUSTED price would count the dividend twice."""
    store, pid = _direct_position(tmp_path, shares=400, price=25.0, entry_state=entry_state,
                                  name=f"b{abs(hash((entry_state, exit_state)))}")
    _settle_direct(store, exit_close=27.0, events=[div(3, "0.50")], exit_state=exit_state)
    pos = store.all_positions()[0]
    assert pos["status"] == "EXIT_UNRESOLVED" and pos["realized_pnl_usd"] is None
    assert store.dividend_entitlements() == [] and store.cash() == 290_000.0
    assert store.blocked_action_rows(pid)[0]["status"] == "BLOCKED_CA_DIVIDEND_PRICE_BASIS_NOT_UNADJUSTED"


def test_dividend_adjusted_basis_is_harmless_when_no_dividend_is_in_the_window(tmp_path):
    store, pid = _direct_position(tmp_path, shares=400, price=25.0, entry_state="SPLIT_DIVIDEND_ADJUSTED")
    _settle_direct(store, exit_close=27.0, events=[], exit_state="SPLIT_DIVIDEND_ADJUSTED")
    assert store.all_positions()[0]["status"] == "CLOSED"


def test_receivable_is_never_credited_without_fresh_provider_confirmation(tmp_path):
    ev = div(3, "0.50")
    cases = {
        "unavailable": StaticCorporateActionSource(status="UNAVAILABLE", detail="outage"),
        "dropped": StaticCorporateActionSource([]),
        "amount_changed": StaticCorporateActionSource([make_dividend_event("PQX", ev.ex_date, "0.60",
                                                                            payable_date=ev.payable_date)]),
        "payable_moved": StaticCorporateActionSource([make_dividend_event(
            "PQX", ev.ex_date, "0.50", payable_date=ev.payable_date + timedelta(days=3))]),
        "now_special": None,
    }
    for name, src in cases.items():
        w = _World(tmp_path, name=f"conf_{name}")
        close_with(w, ev)
        if name == "now_special":
            src = StaticCorporateActionSource([ca.classify_alpaca_record(
                "PQX", "cash_dividends", {"id": "s", "ex_date": ev.ex_date.isoformat(), "rate": 0.5, "special": True,
                                          "payable_date": ev.payable_date.isoformat()}, source="t",
                received_at_utc="t")])
        out = dv.settle_receivables(w.store, CorporateActionGuard(src), as_of=ev.payable_date + timedelta(days=1))
        assert out[0]["status"] != "CREDITED", name
        assert w.store.dividends_credited_total() == 0.0 and w.store.dividend_entitlements()[0]["state"] == "ACCRUED"
    w = _World(tmp_path, name="nopay")
    nopay = make_dividend_event("PQX", ev.ex_date, "0.50")                # payable_date unknown
    g = close_with(w, nopay)
    assert dv.settle_receivables(w.store, g, as_of=date(2027, 1, 1))[0]["status"] == "NO_PAYABLE_DATE"
    assert w.store.dividends_credited_total() == 0.0
    assert w.store.credit_dividend(w.store.dividend_entitlements()[0]["entitlement_id"], as_of=date(2027, 1, 1)) is False


def test_evidence_unavailable_at_settlement_holds_and_never_settles_without_dividend_knowledge(tmp_path):
    w = _World(tmp_path)
    w.add_exit_bar(TARGET, 27.0, basis=EXIT_BASIS)
    w.settle(guard_with(status="UNAVAILABLE", detail="outage"))
    assert w.position()["status"] == "OPEN" and w.store.dividend_entitlements() == []


def test_28_split_idempotency_still_holds_with_dividends_present(tmp_path):
    w = _World(tmp_path)
    sp = make_split_event("PQX", ex_at(2), 10, 1)
    g = guard_with(sp, div(6, "0.20"))
    asof = ex_at(7)
    for _ in range(3):
        pipeline.sweep_corporate_actions(store=w.store, as_of=asof, guard=g)
    assert w.store.effective_shares_exact(w.pos["position_id"]) == 4000
    assert len([t for t in w.store.position_action_trail(w.pos["position_id"]) if t["status"] == "APPLIED"]) == 1
    assert w.store.dividend_entitlements() == []                    # sweeps only OBSERVE; entitlement is decided at settlement


def test_29_composite_basis_safety_still_holds_and_live_adapters_are_split_only():
    from talonx_v2.pricing import AlpacaIexBarAdapter, CompositeBarAdapter, IncompatibleAdjustmentBasis, YFinanceBarAdapter
    hist = base.MemAdapter("snapshot", [row(s, open_=250.0, close=250.0, volume=100_000) for s in base._prior(ENTRY, 20)[:14]])
    live = base.MemAdapter("live", [row(s, open_=25.0, close=25.0, _basis_as_of="2026-09-08")
                                    for s in base._prior(ENTRY, 20)[14:]])
    with pytest.raises(IncompatibleAdjustmentBasis):
        CompositeBarAdapter(hist, live).history("PQX")
    # live adapters request the DIVIDEND-UNADJUSTED basis and tag it
    seen = {}
    iex = AlpacaIexBarAdapter(key_id="k", secret="s", http_get=lambda url, params: (
        seen.update(params) or {"bars": {"X": []}}))
    iex.history("X")
    assert seen["adjustment"] == "split" and AlpacaIexBarAdapter.adjustment_state == "SPLIT_ADJUSTED"
    kwargs = {}
    class T:
        def history(self, **kw):
            kwargs.update(kw)
            import pandas as pd
            return pd.DataFrame(columns=["Open", "Close", "Volume"])
    YFinanceBarAdapter(ticker_factory=lambda s: T()).history("X")
    assert kwargs["auto_adjust"] is False and YFinanceBarAdapter.adjustment_state == "SPLIT_ADJUSTED"
    assert "SPLIT_ADJUSTED" in ca.DIVIDEND_SAFE_BASES and "SPLIT_DIVIDEND_ADJUSTED" not in ca.DIVIDEND_SAFE_BASES


def test_30_session_10_plus_5_exit_rules_are_unchanged_with_dividends(tmp_path):
    ff2 = v2cal.add_sessions(TARGET, 2)
    w = _World(tmp_path)
    w.add_exit_bar(ff2, 28.0, basis=ff2.isoformat())
    ev = make_dividend_event("PQX", v2cal.add_sessions(TARGET, 1), "0.10", payable_date=ff2 + timedelta(days=6))
    w.settle(guard_with(ev), as_of=ff2)
    pos = w.position()
    assert pos["status"] == "CLOSED" and pos["exit_session"] == ff2.isoformat()
    assert [e["amount_usd"] for e in w.store.dividend_entitlements()] == [40.0]   # ex (+1) <= fill (+2)
    w2 = _World(tmp_path, name="late")
    too_late = v2cal.add_sessions(TARGET, 6)
    w2.add_exit_bar(too_late, 28.0, basis=too_late.isoformat())
    w2.settle(guard_with(ev), as_of=too_late)
    assert w2.position()["status"] == "EXIT_UNRESOLVED" and w2.store.dividend_entitlements() == []


def test_33_settlement_idempotency_unchanged_with_a_dividend(tmp_path):
    w = _World(tmp_path)
    ev = div(3, "0.50")
    g = close_with(w, ev)
    cash1, trades1, ents1 = w.store.cash(), w.store.trades(), w.store.dividend_entitlements()
    w.settle(g)                                                     # nothing due
    out = paper.close_position(w.store, w.pos, exit_price=27.0, exit_session=TARGET, config=CFG, dividends=(ev,))
    assert out.settled is False                                     # stale duplicate close: no-op, no 2nd receivable
    assert (w.store.cash(), w.store.trades(), w.store.dividend_entitlements()) == (cash1, trades1, ents1)


def test_service_phase_credits_receivables_after_close_and_reports_them(tmp_path):
    from talonx_v2.service import V2Service
    ev = div(3, "0.50")
    guard = CorporateActionGuard(StaticCorporateActionSource([ev]))
    svc = V2Service(config=base.V2Config(db_path=str(tmp_path / "svc.db"), starting_cash_usd=300_000.0),
                    bar_dirs=[tmp_path], status_path=str(tmp_path / "s.json"), corporate_actions=guard)
    pid = svc.store.insert_open_position(
        episode_id="e", symbol="PQX", issuer_cik="", entry_session=ENTRY, target_exit_session=TARGET,
        entry_price=25.0, shares=400, position_cost=10_000.0,
        price_provenance={"provider": "f", "session": ENTRY.isoformat(), "basis_as_of": ENTRY_BASIS,
                          "adjustment_state": "SPLIT_ADJUSTED"})
    svc.store.set_cash(290_000.0)
    svc.store.record_dividend_entitlement(position_id=pid, event=ev, exit_session=TARGET)
    svc._phase_dividends(ev.payable_date - timedelta(days=1))
    assert svc.store.dividends_credited_total() == 0.0
    svc._phase_dividends(ev.payable_date)
    assert svc.store.dividends_credited_total() == 200.0 and svc.store.cash() == 290_200.0
    assert svc._last_dividend_run[0]["status"] == "CREDITED"


def test_alpaca_dividend_payload_shape_from_the_real_probe():
    rec = {"cusip": "037833100", "ex_date": "2026-05-11", "foreign": False, "id": "a2df24db", "payable_date": "2026-05-14",
           "process_date": "2026-05-14", "rate": 0.27, "record_date": "2026-05-11", "special": False, "symbol": "AAPL"}
    e = ca.classify_alpaca_record("AAPL", "cash_dividends", rec, source="alpaca", received_at_utc="t")
    assert (e.kind, e.ex_date, e.payable_date, e.record_date, e.cash_rate) == (
        ca.KIND_CASH_DIVIDEND, date(2026, 5, 11), date(2026, 5, 14), date(2026, 5, 11), "0.27")
    assert e.action_key == "DIV|AAPL|2026-05-11|0.27"
    # same content re-listed under a different id collapses; a corrected amount on the same ex-date conflicts
    r2 = ca.classify_alpaca_record("AAPL", "cash_dividends", {**rec, "id": "OTHER"}, source="alpaca", received_at_utc="t")
    r3 = ca.classify_alpaca_record("AAPL", "cash_dividends", {**rec, "id": "FIX", "rate": 0.28}, source="alpaca", received_at_utc="t")
    assert len(ca._finalize("alpaca", [e, r2]).events) == 1 and not ca._finalize("alpaca", [e, r2]).conflicts
    assert ca._finalize("alpaca", [e, r3]).conflicts


def test_34_strategy_thresholds_and_fingerprint_unchanged():
    cfg = base.V2Config()
    assert (cfg.min_distinct_owners, cfg.hold_trading_days, cfg.entry_offset_sessions,
            cfg.liquidity_lookback_sessions, cfg.liquidity_min_median_dollar_volume,
            cfg.liquidity_min_close, cfg.exit_fallforward_max_sessions,
            cfg.max_entry_staleness_sessions) == (2, 10, 1, 20, 5_000_000.0, 5.0, 5, 3)
    import importlib.util
    p = Path(__file__).resolve().parents[1] / "research" / "scripts" / "task112_v2_release_fingerprint.py"
    spec = importlib.util.spec_from_file_location("pq2a_closure_fp", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.v2_release_fingerprint()["fingerprint"] == "e2acf6454789217e"
