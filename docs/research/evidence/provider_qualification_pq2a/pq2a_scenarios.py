"""PQ-2A reproducible scenario evidence.

Runs the REAL settlement code (pipeline.settle_due_exits -> paper.close_position)
against throw-away temp ledgers.  No network, no broker, no production DB.

    .venv/Scripts/python.exe docs/research/evidence/provider_qualification_pq2a/pq2a_scenarios.py

Writes scenario_results.json next to this file.
"""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

from talonx_v2 import calendar as v2cal, pipeline
from talonx_v2.config import V2Config
from talonx_v2.corporate_actions import (
    CorporateActionGuard, StaticCorporateActionSource, make_dividend_event, make_split_event,
    make_unsupported_event)
from talonx_v2.store import V2Store

ENTRY = date(2026, 9, 8)
TARGET = v2cal.add_sessions(ENTRY, 10)
CFG = V2Config(starting_cash_usd=300_000.0)


def run(name, *, shares, entry_price, exit_close, events, guarded=True, entry_basis="2026-09-08",
        exit_basis="2026-09-23", as_of=TARGET):
    tmp = Path(tempfile.mkdtemp(prefix="pq2a_"))
    store = V2Store(str(tmp / "ledger.db"), starting_cash=300_000.0)
    cost = shares * entry_price
    prov = {"provider": "fixture", "field": "open", "session": ENTRY.isoformat(), "basis_as_of": entry_basis}
    pid = store.insert_open_position(
        episode_id=f"ep-{name}", symbol="PQX", issuer_cik="", entry_session=ENTRY,
        target_exit_session=TARGET, entry_price=entry_price, shares=shares, position_cost=cost,
        price_provenance=prov)
    store.set_cash(300_000.0 - cost)

    def price_lookup(sym, session):
        if session != TARGET:
            return None
        return {"open": exit_close, "close": exit_close, "volume": 1_000_000,
                "_provenance": {"provider": "fixture", "session": session.isoformat(),
                                "basis_as_of": exit_basis, "finality": "FINAL"}}

    guard = CorporateActionGuard(StaticCorporateActionSource(events)) if guarded else None
    res = pipeline.settle_due_exits(store=store, as_of_session=as_of, price_lookup=price_lookup,
                                    config=CFG, corporate_actions=guard)
    pos = store.all_positions()[0]
    sells = [t for t in store.trades() if t["action"] == "SELL"]
    return {
        "scenario": name, "guarded": guarded,
        "entry": {"shares": shares, "price": entry_price, "cost": cost},
        "exit_close_served": exit_close,
        "status": pos["status"],
        "economic_shares": float(store.effective_shares_exact(pid)),
        "exit_shares_settled": sells[0]["shares"] if sells else None,
        "position_cost_after": pos["position_cost"],
        "realized_pnl_usd": pos["realized_pnl_usd"],
        "realized_pnl_pct": pos["realized_pnl_pct"],
        "cash_after": store.cash(),
        "skipped": res.skipped,
        "trail": [{k: t[k] for k in ("kind", "ex_date", "ratio_num", "ratio_den", "status",
                                     "shares_before", "shares_after", "cost_basis")}
                  for t in store.position_action_trail(pid)],
    }


split_10 = make_split_event("PQX", v2cal.add_sessions(ENTRY, 4), 10, 1)
out = []
# --- the headline example: 10 sh @ $100, 10:1 split, exit @ ~$11 ---------------------------------
out.append(dict(run("headline_10sh_100_10to1_exit11_UNGUARDED", shares=10, entry_price=100.0, exit_close=11.0,
                    events=[], guarded=False),
                expected={"realized_pnl_usd": 100.0}, note="PRE-FIX behaviour: false -$890 (-89%)"))
out.append(dict(run("headline_10sh_100_10to1_exit11_GUARDED", shares=10, entry_price=100.0, exit_close=11.0,
                    events=[split_10]),
                expected={"economic_shares": 100, "realized_pnl_usd": 100.0}))
out.append(run("forward_2to1", shares=10, entry_price=100.0, exit_close=52.0,
               events=[make_split_event("PQX", v2cal.add_sessions(ENTRY, 3), 2, 1)]))
out.append(run("reverse_1for10_exact_whole", shares=100, entry_price=10.0, exit_close=105.0,
               events=[make_split_event("PQX", v2cal.add_sessions(ENTRY, 4), 1, 10)]))
out.append(dict(run("reverse_1for10_FRACTIONAL_5sh", shares=5, entry_price=100.0, exit_close=1050.0,
                    events=[make_split_event("PQX", v2cal.add_sessions(ENTRY, 4), 1, 10)]),
                expected={"economic_shares": 0.5, "realized_pnl_usd": 25.0},
                note="0.5 share retained EXACTLY (not 0, not 1); no cash-in-lieu invented"))
out.append(run("no_action", shares=10, entry_price=100.0, exit_close=110.0, events=[]))
out.append(dict(run("dividend_observed_not_credited", shares=10, entry_price=100.0, exit_close=110.0,
                    events=[make_dividend_event("PQX", v2cal.add_sessions(ENTRY, 3), "0.50")]),
                note="price return only: cash == start - cost + proceeds; no dividend credit"))
out.append(run("unsupported_spin_off_blocks", shares=10, entry_price=100.0, exit_close=110.0,
               events=[make_unsupported_event("PQX", v2cal.add_sessions(ENTRY, 3), "spin_offs")]))
out.append(run("unknown_entry_basis_with_split_blocks", shares=10, entry_price=100.0, exit_close=11.0,
               events=[split_10], entry_basis=None))
out.append(run("split_on_target_exit_session", shares=10, entry_price=100.0, exit_close=11.0,
               events=[make_split_event("PQX", TARGET, 10, 1)]))
Path(__file__).with_name("scenario_results.json").write_text(json.dumps(out, indent=2, default=str))
for r in out:
    print(f"{r['scenario']:52s} status={r['status']:15s} eco_sh={r['economic_shares']:>8} "
          f"pnl={r['realized_pnl_usd']} pct={r['realized_pnl_pct']}")
