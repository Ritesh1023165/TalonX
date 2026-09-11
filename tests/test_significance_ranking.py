"""
tests/test_significance_ranking.py
---------------------------------
Task 96E -- deterministic event + watchlist-symbol ranking.
"""
from __future__ import annotations

from datetime import timedelta

from talonx_ingest.intelligence.domain import EventType, SignificanceBand
from talonx_ingest.intelligence.significance import evaluate_significance
from talonx_ingest.intelligence.significance.ranking import (
    rank_events,
    rank_watchlist_symbols,
)
from talonx_ingest.intelligence.significance.store import SignificanceStore
from _significance_helpers import NOW, mk_comparison, mk_event


def _seed(store, *, symbol, acc, et, items, hours_ago, **kw):
    ev = mk_event(
        event_type=et, symbol=symbol, accession=acc, items=items,
        form_type="10-Q" if et is EventType.QUARTERLY_FILING else "8-K",
        accepted_at=NOW - timedelta(hours=hours_ago),
    )
    cmp = kw.pop("comparison", None)
    sig = evaluate_significance(ev, comparison=cmp, now=NOW, **kw)
    store.upsert(sig)
    return ev, sig


def test_rank_events_orders_and_filters(ledger_path):
    s = SignificanceStore(ledger_path)
    evs = {}
    e1, s1 = _seed(s, symbol="AAPL", acc="0000320193-26-000101",
                   et=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",), hours_ago=2)
    ev2 = mk_event(event_type=EventType.QUARTERLY_FILING, symbol="MSFT", form_type="10-Q",
                   items=(), accession="0000789019-26-000102", accepted_at=NOW - timedelta(hours=3))
    s2 = evaluate_significance(
        ev2, comparison=mk_comparison(event=ev2, rf_diff=0.7, mdna_diff=0.35, neg_kw_delta=20),
        now=NOW,
    )
    s.upsert(s2)
    evs = {e1.event_id: e1, ev2.event_id: ev2}

    ranked = rank_events(s, event_lookup=evs.get)
    assert [r.symbol for r in ranked] == ["MSFT", "AAPL"]  # higher score first

    only_high = rank_events(s, min_band=SignificanceBand.HIGH, event_lookup=evs.get)
    assert [r.symbol for r in only_high] == ["MSFT"]

    just_aapl = rank_events(s, symbols=["AAPL"], event_lookup=evs.get)
    assert [r.symbol for r in just_aapl] == ["AAPL"]
    s.close()


def test_rank_events_tie_break_is_deterministic(ledger_path):
    s = SignificanceStore(ledger_path)
    lookup = {}
    for i in range(3):
        ev, _ = _seed(
            s, symbol="AAPL", acc=f"0000320193-26-00020{i}",
            et=EventType.RESTRUCTURING, items=("2.05",), hours_ago=1,
        )
        lookup[ev.event_id] = ev
    r1 = [r.significance.event_id for r in rank_events(s, event_lookup=lookup.get)]
    r2 = [r.significance.event_id for r in rank_events(s, event_lookup=lookup.get)]
    assert r1 == r2 == sorted(r1)  # equal score+time -> event_id asc, stable
    s.close()


def test_rank_watchlist_symbols(ledger_path):
    s = SignificanceStore(ledger_path)
    lookup = {}
    ev_a, _ = _seed(s, symbol="AAPL", acc="0000320193-26-000301",
                    et=EventType.RESTRUCTURING, items=("2.05",), hours_ago=5)
    lookup[ev_a.event_id] = ev_a
    ev_m = mk_event(event_type=EventType.QUARTERLY_FILING, symbol="MSFT", form_type="10-Q",
                    items=(), accession="0000789019-26-000302", accepted_at=NOW - timedelta(hours=6))
    s.upsert(evaluate_significance(
        ev_m, comparison=mk_comparison(event=ev_m, rf_diff=0.7, mdna_diff=0.35, neg_kw_delta=20),
        now=NOW,
    ))
    lookup[ev_m.event_id] = ev_m

    rows = rank_watchlist_symbols(
        s, watchlist=["AAPL", "MSFT", "NVDA"], pinned={"NVDA"}, now=NOW, event_lookup=lookup.get
    )
    by_sym = {r.symbol: r for r in rows}
    # MSFT (HIGH) ranks above AAPL (MEDIUM); NVDA has no event -> quiet, last
    assert [r.symbol for r in rows][:2] == ["MSFT", "AAPL"]
    assert rows[-1].symbol == "NVDA" and rows[-1].events == []
    assert by_sym["MSFT"].why  # "why it's here" strings present
    s.close()


def test_quiet_symbol_still_present_when_event_out_of_window(ledger_path):
    s = SignificanceStore(ledger_path)
    ev, _ = _seed(s, symbol="AAPL", acc="0000320193-26-000401",
                  et=EventType.RESTRUCTURING, items=("2.05",), hours_ago=24 * 30)
    rows = rank_watchlist_symbols(
        s, watchlist=["AAPL"], now=NOW, trailing_days=7, event_lookup={ev.event_id: ev}.get
    )
    assert rows[0].symbol == "AAPL" and rows[0].score == 0 and rows[0].band is SignificanceBand.LOW
    s.close()
