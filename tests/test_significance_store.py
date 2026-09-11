"""
tests/test_significance_store.py
-------------------------------
Task 96E -- SignificanceStore: additive schema, idempotency, ruleset
history, deterministic query ordering, migration safety.
"""
from __future__ import annotations

import sqlite3

from talonx_ingest.intelligence.domain import EventType, SignificanceBand
from talonx_ingest.intelligence.significance import evaluate_significance
from talonx_ingest.intelligence.significance.store import SignificanceStore
from _significance_helpers import NOW, mk_comparison, mk_event


def _sig(acc, et=EventType.RESTRUCTURING, items=("2.05",), **kw):
    ev = mk_event(event_type=et, accession=acc, items=items)
    return evaluate_significance(ev, now=NOW, **kw)


def test_roundtrip_is_faithful(ledger_path):
    s = SignificanceStore(ledger_path)
    sig = _sig("0000320193-26-000101", on_watchlist=True)
    assert s.upsert(sig) is True
    got = s.get(sig.significance_id)
    assert got.model_dump() == sig.model_dump()
    s.close()


def test_idempotent_upsert(ledger_path):
    s = SignificanceStore(ledger_path)
    sig = _sig("0000320193-26-000102")
    assert s.upsert(sig) is True
    assert s.upsert(sig) is False
    assert s.count() == 1
    s.close()


def test_ruleset_bump_keeps_history(ledger_path):
    s = SignificanceStore(ledger_path)
    ev = mk_event(event_type=EventType.RESTRUCTURING, accession="0000320193-26-000103", items=("2.05",))
    v1 = evaluate_significance(ev, now=NOW, ruleset_version="information-significance-v1")
    v2 = evaluate_significance(ev, now=NOW, ruleset_version="information-significance-v2")
    s.upsert(v1)
    s.upsert(v2)
    assert s.count() == 2
    assert s.get_for_event(ev.event_id, ruleset_version="information-significance-v1").ruleset_version == "information-significance-v1"
    assert s.get_for_event(ev.event_id, ruleset_version="information-significance-v2").ruleset_version == "information-significance-v2"
    s.close()


def test_query_orders_by_score_desc_then_stable(ledger_path):
    s = SignificanceStore(ledger_path)
    low = _sig("0000320193-26-000201", et=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",))
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(),
                  accession="0000320193-26-000202")
    high = evaluate_significance(ev, comparison=mk_comparison(event=ev, rf_diff=0.7), now=NOW)
    s.upsert(low)
    s.upsert(high)
    rows = s.query()
    assert [r.score for r in rows] == sorted([r.score for r in rows], reverse=True)
    assert rows[0].event_id == high.event_id


def test_query_filters(ledger_path):
    s = SignificanceStore(ledger_path)
    s.upsert(_sig("0000320193-26-000301"))
    s.upsert(_sig("0000320193-26-000302", et=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",)))
    assert len(s.query(min_score=2)) == 1
    assert len(s.query(band=SignificanceBand.LOW)) == 1
    assert len(s.query(symbol="AAPL")) == 2
    assert len(s.query(symbol="MSFT")) == 0
    s.close()


def test_additive_to_existing_ledger(ledger_path):
    # a DB that predates this module opens cleanly and keeps its rows
    conn = sqlite3.connect(ledger_path)
    conn.execute("CREATE TABLE ingested_filings (accession TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO ingested_filings VALUES ('pre-existing')")
    conn.commit()
    conn.close()

    s = SignificanceStore(ledger_path)
    s.upsert(_sig("0000320193-26-000401"))
    s.close()

    conn = sqlite3.connect(ledger_path)
    assert conn.execute("SELECT COUNT(*) FROM ingested_filings").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM event_significance").fetchone()[0] == 1
    conn.close()


def test_schema_version(ledger_path):
    s = SignificanceStore(ledger_path)
    assert s.schema_version() == 1
    s.close()
