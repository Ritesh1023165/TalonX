"""PQ-2A closure -- reproducible dividend / fractional scenario evidence.

Real settlement + dividend code against throw-away temp ledgers (no network/broker/production DB).

    PYTHONPATH=. .venv/Scripts/python.exe docs/research/evidence/provider_qualification_pq2a_closure/pq2a_closure_scenarios.py
"""
from __future__ import annotations

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

from talonx_v2 import calendar as v2cal, dividends as dv, paper, pipeline
from talonx_v2.config import V2Config
from talonx_v2.corporate_actions import (
    CorporateActionGuard, StaticCorporateActionSource, make_dividend_event, make_split_event)
from talonx_v2.store import V2Store

ENTRY = date(2026, 9, 8)
TARGET = v2cal.add_sessions(ENTRY, 10)
CFG = V2Config(starting_cash_usd=300_000.0)


def ex_at(n):
    return v2cal.add_sessions(ENTRY, n)


def scenario(name, *, shares, price, exit_close, events, entry_fee=0.0, exit_fee=0.0, note=""):
    tmp = Path(tempfile.mkdtemp(prefix="pq2a_closure_"))
    store = V2Store(str(tmp / "ledger.db"), starting_cash=300_000.0)
    cost = shares * price + entry_fee
    prov = {"provider": "fixture", "field": "open", "session": ENTRY.isoformat(),
            "basis_as_of": ENTRY.isoformat(), "adjustment_state": "SPLIT_ADJUSTED"}
    pid = store.insert_open_position(
        episode_id=f"ep-{name}", symbol="PQX", issuer_cik="", entry_session=ENTRY, target_exit_session=TARGET,
        entry_price=price, shares=shares, position_cost=cost, entry_fee=entry_fee, price_provenance=prov)
    store.set_cash(300_000.0 - cost)
    cash_open = store.cash()
    guard = CorporateActionGuard(StaticCorporateActionSource(events))

    def price_lookup(sym, session):
        return None if session != TARGET else {
            "open": exit_close, "close": exit_close, "volume": 1_000_000,
            "_provenance": {"provider": "fixture", "session": session.isoformat(), "basis_as_of": "2026-09-23",
                            "adjustment_state": "SPLIT_ADJUSTED", "finality": "FINAL"}}

    if exit_fee:                        # fee-bearing settlement: drive paper.close_position directly
        v = guard.assess_position(store, store.all_positions()[0], as_of=TARGET, exit_basis_as_of=date(2026, 9, 23),
                                  exit_session=TARGET, exit_adjustment_state="SPLIT_ADJUSTED", settlement=True)
        paper.close_position(store, store.all_positions()[0], exit_price=exit_close, exit_session=TARGET,
                             config=CFG, fee_fn=lambda q, p: exit_fee, dividends=v.dividends)
    else:
        pipeline.settle_due_exits(store=store, as_of_session=TARGET, price_lookup=price_lookup, config=CFG,
                                  corporate_actions=guard)
    pos = store.all_positions()[0]
    cash_after_close = store.cash()
    receivable = [(e["state"], e["eligible_qty"], e["rate"], e["amount_usd"], e["payable_date"])
                  for e in store.dividend_entitlements()]
    pay = max((e["payable_date"] for e in store.dividend_entitlements() if e["payable_date"]), default=None)
    if pay:
        dv.settle_receivables(store, guard, as_of=date.fromisoformat(pay))
    price_pnl = pos["realized_pnl_usd"]
    div_pnl = store.dividends_credited_total()
    return {
        "scenario": name, "note": note,
        "entry": {"shares": shares, "price": price, "entry_fee": entry_fee, "economic_cost": cost},
        "exit_close": exit_close, "exit_fee": exit_fee,
        "economic_shares_at_exit": float(store.effective_shares_exact(pid)),
        "price_pnl_usd": price_pnl,
        "dividend_receivable_at_close": receivable,
        "cash": {"after_entry": cash_open, "after_close_before_payable": cash_after_close,
                 "after_dividend_credited": store.cash()},
        "dividend_pnl_usd": div_pnl,
        "total_return_pnl_usd": round(price_pnl + div_pnl, 6),
        "cash_minus_start": round(store.cash() - 300_000.0, 6),
        "reconstruction": f"{price_pnl} (price, fee-inclusive) + {div_pnl} (dividends) = {round(price_pnl + div_pnl, 6)}",
    }


pay = lambda n, d=7: ex_at(n) + timedelta(days=d)           # noqa: E731
out = [
    scenario("A_100sh_at_100_plus_0.50_dividend", shares=100, price=100.0, exit_close=105.0,
             events=[make_dividend_event("PQX", ex_at(3), "0.50", payable_date=pay(3, 15))],
             note="held through ex-date; payable AFTER the +10 exit"),
    scenario("B_10sh_10to1_split_then_0.20_dividend", shares=10, price=100.0, exit_close=11.0,
             events=[make_split_event("PQX", ex_at(3), 10, 1),
                     make_dividend_event("PQX", ex_at(6), "0.20", payable_date=pay(6))],
             note="dividend uses the POST-split quantity: 100 sh x $0.20 = $20 (not $2, not $200)"),
    scenario("C_5sh_1for10_reverse_split_then_1.00_dividend", shares=5, price=100.0, exit_close=1050.0,
             events=[make_split_event("PQX", ex_at(3), 1, 10),
                     make_dividend_event("PQX", ex_at(6), "1.00", payable_date=pay(6))],
             note="exact 0.5 share; dividend $0.50; no truncation, no cash-in-lieu"),
    scenario("D_with_fees_100sh_entry_fee_1_exit_fee_1_plus_0.50_dividend", shares=100, price=100.0, exit_close=105.0,
             entry_fee=1.0, exit_fee=1.0,
             events=[make_dividend_event("PQX", ex_at(3), "0.50", payable_date=pay(3))],
             note="TOTAL = price P&L (net of $2 fees) + dividend P&L"),
    scenario("E_entered_on_ex_date_not_eligible", shares=100, price=100.0, exit_close=105.0,
             events=[make_dividend_event("PQX", ENTRY, "0.50", payable_date=pay(0))], note="buyer on the ex-date is not entitled"),
    scenario("F_exit_before_ex_date_not_eligible", shares=100, price=100.0, exit_close=105.0,
             events=[make_dividend_event("PQX", v2cal.add_sessions(TARGET, 1), "0.50",
                                         payable_date=TARGET + timedelta(days=10))], note="sold before the ex-date"),
]
Path(__file__).with_name("closure_scenario_results.json").write_text(json.dumps(out, indent=2, default=str))
for r in out:
    print(f"{r['scenario']:66s} eco_sh={r['economic_shares_at_exit']:<6} price={r['price_pnl_usd']:<8} "
          f"div={r['dividend_pnl_usd']:<6} total={r['total_return_pnl_usd']:<8} cash-start={r['cash_minus_start']}")
