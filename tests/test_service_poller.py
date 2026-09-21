"""
tests/test_service_poller.py
----------------------------
Task 96B — Gate D (incremental polling), Gate E (quiet health), Gate F
(96A events), Gate N (transient failure recovery), Gate Q (idempotency).
Offline: FakeEdgarClient.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from talonx_ingest.intelligence.domain import SourceType
from talonx_ingest.intelligence.freshness import SourceFreshnessTracker
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
from talonx_ingest.intelligence.service.poller import EdgarPoller
from talonx_ingest.intelligence.service.scope import resolve_scope
from talonx_ingest.intelligence.service.stores import StoreBundle
from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.comparison.retrieval import FilingArchiveCache

from tests._service_helpers import (
    FakeEdgarClient,
    FakeWatchlistStore,
    default_rows,
    make_submissions,
    wl_row,
)


def _setup(tmp_path, rows=None, fail_ciks=None):
    cfg = ServiceConfig(ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "state",
                        history_days=3650)
    stores = StoreBundle.open(cfg.ledger())
    client = FakeEdgarClient(
        submissions={"0000012345": make_submissions(rows=rows)},
        fail_submissions_for=set(fail_ciks or []),
    )
    directory = CikDirectory.from_company_tickers(
        {"0": {"cik_str": 12345, "ticker": "FAKE", "title": "Fake Industries Inc."}}
    )
    wl = FakeWatchlistStore([wl_row("FAKE")])
    scope = resolve_scope(config=cfg, watchlist_store=wl, directory=directory)
    enrich = EnrichmentEngine(
        stores, client, config=cfg,
        cache=FilingArchiveCache(client, cache_dir=tmp_path / "cache"),
    )
    poller = EdgarPoller(stores, client, config=cfg, scope=scope, enrichment=enrich)
    return cfg, stores, client, poller


def test_new_filings_become_events_and_enrich(tmp_path):
    cfg, stores, client, poller = _setup(tmp_path)
    res = asyncio.run(poller.poll_once())
    assert res.symbols_polled == 1 and res.symbols_failed == 0
    assert len(res.new_event_ids) >= 3
    assert res.submissions_freshness == "FRESH"
    # 96A events landed
    assert stores.events.count_events() >= 3
    # 96E significance ran for at least one
    assert stores.significance.count() >= 1
    # 96F durable outbox row(s), none SENT (dry-run enqueue only)
    counts = stores.outbox.counts_by_state()
    assert counts.get("PENDING", 0) >= 1
    assert counts.get("SENT", 0) == 0
    stores.close()


def test_second_poll_is_idempotent(tmp_path):
    cfg, stores, client, poller = _setup(tmp_path)
    asyncio.run(poller.poll_once())
    n_events = stores.events.count_events()
    n_txns = stores.insider.count_transactions()
    res2 = asyncio.run(poller.poll_once())
    assert res2.new_event_ids == []
    assert res2.new_form4_filings == 0
    assert stores.events.count_events() == n_events
    assert stores.insider.count_transactions() == n_txns
    stores.close()


def test_quiet_cycle_is_not_a_failure(tmp_path):
    cfg, stores, client, poller = _setup(tmp_path)
    asyncio.run(poller.poll_once())          # consumes everything
    res2 = asyncio.run(poller.poll_once())   # nothing new
    assert res2.new_event_ids == []
    snap = SourceFreshnessTracker(stores.events).snapshot(SourceType.SEC_EDGAR_SUBMISSIONS)
    assert snap.status.value == "FRESH"      # quiet != STALE/DOWN
    assert snap.consecutive_failures == 0
    stores.close()


def test_transient_source_failure_then_recovery(tmp_path):
    cfg, stores, client, poller = _setup(tmp_path, fail_ciks=["0000012345"])
    r1 = asyncio.run(poller.poll_once())
    assert r1.symbols_failed == 1 and r1.symbols_polled == 0
    assert r1.errors and "429" in r1.errors[0]
    # recover
    client.fail_submissions_for = set()
    r2 = asyncio.run(poller.poll_once())
    assert r2.symbols_polled == 1
    assert len(r2.new_event_ids) >= 3
    snap = SourceFreshnessTracker(stores.events).snapshot(SourceType.SEC_EDGAR_SUBMISSIONS)
    assert snap.status.value == "FRESH"
    stores.close()


def _setup_two_symbols(tmp_path, fail_second=False):
    """Task 132: a 2-symbol scope, for exercising ``poll_once``'s
    ``progress_cb`` across more than one symbol."""
    cfg = ServiceConfig(ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "state",
                        history_days=3650)
    stores = StoreBundle.open(cfg.ledger())
    client = FakeEdgarClient(
        submissions={
            "0000012345": make_submissions(cik=12345, ticker="FAKE", rows=default_rows()),
            "0000067890": make_submissions(cik=67890, ticker="OTHR", rows=default_rows()),
        },
        fail_submissions_for={67890} if fail_second else set(),
    )
    directory = CikDirectory.from_company_tickers({
        "0": {"cik_str": 12345, "ticker": "FAKE", "title": "Fake Industries Inc."},
        "1": {"cik_str": 67890, "ticker": "OTHR", "title": "Other Corp."},
    })
    wl = FakeWatchlistStore([wl_row("FAKE"), wl_row("OTHR")])
    scope = resolve_scope(config=cfg, watchlist_store=wl, directory=directory)
    enrich = EnrichmentEngine(
        stores, client, config=cfg,
        cache=FilingArchiveCache(client, cache_dir=tmp_path / "cache"),
    )
    poller = EdgarPoller(stores, client, config=cfg, scope=scope, enrichment=enrich)
    return cfg, stores, client, poller


def test_progress_cb_reports_every_symbol_in_order(tmp_path):
    """Task 132 section 2: ``poll_once`` must expose bounded, per-symbol
    progress so a large first-cycle scope isn't externally silent for the
    whole cycle duration."""
    cfg, stores, client, poller = _setup_two_symbols(tmp_path)
    calls = []
    res = asyncio.run(poller.poll_once(progress_cb=lambda done, total, sym: calls.append((done, total, sym))))
    assert res.symbols_polled == 2
    assert [c[:2] for c in calls] == [(1, 2), (2, 2)]
    assert {c[2] for c in calls} == {"FAKE", "OTHR"}
    stores.close()


def test_progress_cb_reports_failed_symbols_too(tmp_path):
    cfg, stores, client, poller = _setup_two_symbols(tmp_path, fail_second=True)
    calls = []
    res = asyncio.run(poller.poll_once(progress_cb=lambda done, total, sym: calls.append((done, total, sym))))
    assert res.symbols_polled == 1 and res.symbols_failed == 1
    # a failed symbol still advances the externally-observed progress count
    assert len(calls) == 2
    stores.close()


def test_progress_cb_exception_never_breaks_the_poll(tmp_path):
    cfg, stores, client, poller = _setup_two_symbols(tmp_path)

    def _boom(done, total, sym):
        raise RuntimeError("observer bug")

    res = asyncio.run(poller.poll_once(progress_cb=_boom))
    assert res.symbols_polled == 2 and res.symbols_failed == 0
    stores.close()


def test_poll_once_without_progress_cb_is_unaffected(tmp_path):
    """Default ``progress_cb=None`` stays a byte-identical no-op."""
    cfg, stores, client, poller = _setup_two_symbols(tmp_path)
    res = asyncio.run(poller.poll_once())
    assert res.symbols_polled == 2
    stores.close()


def test_enrich_progress_cb_reports_every_new_event(tmp_path):
    """Task 132 section 2: the confirmed dominant bottleneck of a large
    first cycle is the SEPARATE per-event enrichment pass (significance +
    comparison), not the per-symbol fetch loop -- it must expose its own
    progress independently."""
    cfg, stores, client, poller = _setup(tmp_path)  # single symbol, default_rows() -> 3 text events
    calls = []
    res = asyncio.run(poller.poll_once(
        enrich_progress_cb=lambda done, total, eid: calls.append((done, total, eid))
    ))
    assert len(res.new_event_ids) >= 3
    assert len(calls) == len(set(res.new_event_ids))
    assert calls[-1][0] == calls[-1][1]        # final call: done == total
    dones = [c[0] for c in calls]
    assert dones == sorted(dones)              # strictly increasing / in order
    stores.close()


def test_enrich_progress_cb_exception_never_breaks_the_poll(tmp_path):
    cfg, stores, client, poller = _setup(tmp_path)

    def _boom(done, total, eid):
        raise RuntimeError("observer bug")

    res = asyncio.run(poller.poll_once(enrich_progress_cb=_boom))
    assert len(res.new_event_ids) >= 3
    stores.close()
