"""
tests/test_task133_recoverable_processing.py
----------------------------------------------
Task 133 — RECOVERABLE INGESTION AND TIMELY DISCOVERY DELIVERY.

Covers, offline (FakeEdgarClient, tmp_path-isolated ledgers, never the
real ~/.talonx/ingestion_ledger.db):

1. ProcessingStateStore.find_undiscovered_events / next_for_processing —
   the two new queries the recovery pass is built on.
2. IntelligenceService.reconcile_and_enrich — orphan recovery, bounded
   batches, one-bad-event isolation, idempotent/duplicate-safe replay.
3. EdgarPoller's bounded inline enrichment (enrich_max_events_per_cycle)
   deferring overflow to the recovery pass instead of losing it.
4. run_poll_loop giving deliver_cycle a turn even with backlog remaining.
5. A genuine cross-PROCESS interruption/recovery test (subprocess hard-
   kill mid-pipeline, then a fresh process reopens the same ledger file).

Never sends to the real Telegram destination; never touches the real
campaign ledger.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
from talonx_ingest.intelligence.service.poller import EdgarPoller
from talonx_ingest.intelligence.service.runner import IntelligenceService
from talonx_ingest.intelligence.service.scope import resolve_scope
from talonx_ingest.intelligence.service.state_machine import ProcessingStage
from talonx_ingest.intelligence.service.stores import StoreBundle
from talonx_ingest.intelligence.comparison.retrieval import FilingArchiveCache

from tests._service_helpers import (
    FakeEdgarClient, FakeWatchlistStore, default_rows, make_submissions, wl_row,
)

UTC = timezone.utc


def _stack(tmp_path, *, symbols=("FAKE",), ciks=(12345,), **cfg_over):
    cfg = ServiceConfig(ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "state",
                        history_days=3650, **cfg_over)
    stores = StoreBundle.open(cfg.ledger())
    submissions = {
        str(cik).zfill(10): make_submissions(cik=cik, ticker=sym, rows=default_rows())
        for sym, cik in zip(symbols, ciks)
    }
    client = FakeEdgarClient(submissions=submissions)
    tickers = {
        str(i): {"cik_str": cik, "ticker": sym, "title": f"{sym} Inc."}
        for i, (sym, cik) in enumerate(zip(symbols, ciks))
    }
    directory = CikDirectory.from_company_tickers(tickers)
    wl = FakeWatchlistStore([wl_row(s) for s in symbols])
    scope = resolve_scope(config=cfg, watchlist_store=wl, directory=directory)
    enrich = EnrichmentEngine(
        stores, client, config=cfg,
        cache=FilingArchiveCache(client, cache_dir=tmp_path / "cache"),
    )
    poller = EdgarPoller(stores, client, config=cfg, scope=scope, enrichment=enrich)
    return cfg, stores, client, poller, enrich


def _svc_stack(tmp_path, monkeypatch, **cfg_over):
    cfg, stores, client, poller, enrich = _stack(tmp_path, **cfg_over)
    svc = IntelligenceService(cfg)
    svc.stores = stores
    svc.client = client
    svc.enrichment = enrich
    svc.poller = poller
    svc.scope = poller.scope

    async def _open(with_network=True):
        return svc
    monkeypatch.setattr(svc, "open", _open)
    return svc, cfg, stores, client


# ---------------------------------------------------------------------
# 1. store-level queries
# ---------------------------------------------------------------------

def test_find_undiscovered_events_returns_orphans_only(tmp_path):
    cfg, stores, client, poller, enrich = _stack(tmp_path)
    asyncio.run(poller.poll_once())  # persists text_events AND enriches (unbounded default)
    orphans = stores.processing.find_undiscovered_events(limit=100)
    assert orphans == []  # everything was enriched inline -> no orphans

    # simulate an event a PRIOR process persisted but crashed before ever
    # calling process_event() on: delete its processing row directly.
    any_row = stores.processing.open_rows(limit=1)
    ev = stores.events.get_event(
        stores.processing._conn.execute("SELECT event_id FROM intel_event_processing LIMIT 1").fetchone()[0]
    )
    stores.processing._conn.execute(
        "DELETE FROM intel_event_processing WHERE event_id = ?", (ev.event_id,)
    )
    stores.processing._conn.commit()

    orphans = stores.processing.find_undiscovered_events(limit=100)
    assert ev.event_id in orphans
    stores.close()


def test_next_for_processing_respects_retry_backoff(tmp_path):
    cfg, stores, client, poller, enrich = _stack(tmp_path)
    asyncio.run(poller.poll_once())
    eid = stores.processing.open_rows(limit=1) or None
    # pick any event and mark it FAILED_RETRYABLE with a future retry_after
    row = stores.processing._conn.execute("SELECT event_id FROM intel_event_processing LIMIT 1").fetchone()
    eid = row[0]
    future = datetime.now(UTC) + timedelta(hours=1)
    stores.processing.record_error(eid, error="boom", retryable=True, retry_after_utc=future)

    due_now = stores.processing.next_for_processing(now=datetime.now(UTC), limit=100)
    assert eid not in [r.event_id for r in due_now]

    due_later = stores.processing.next_for_processing(now=future + timedelta(seconds=1), limit=100)
    assert eid in [r.event_id for r in due_later]
    stores.close()


# ---------------------------------------------------------------------
# 2. reconcile_and_enrich
# ---------------------------------------------------------------------

def test_reconcile_and_enrich_recovers_a_backward_compat_orphan(tmp_path, monkeypatch):
    """Scenario: 'persist event, interrupt before enrichment, reopen and
    recover' -- simulated by deleting the processing row a prior
    poll_once() created (the row process_event() would have made had it
    run), leaving ONLY the text_events row, exactly what an old process
    that never enriched an event leaves behind."""
    svc, cfg, stores, client = _svc_stack(tmp_path, monkeypatch)
    asyncio.run(poller_poll_once_via(svc))
    row = stores.processing._conn.execute("SELECT event_id FROM intel_event_processing LIMIT 1").fetchone()
    eid = row[0]
    stores.processing._conn.execute("DELETE FROM intel_event_processing WHERE event_id=?", (eid,))
    stores.processing._conn.commit()
    assert stores.processing.get(eid) is None

    summary = asyncio.run(svc.reconcile_and_enrich())
    assert summary["reconciled"] >= 1
    assert summary["enriched"] >= 1
    recovered = stores.processing.get(eid)
    assert recovered is not None
    # made REAL progress past the bare STORED/DISCOVERED registration --
    # PARTIAL is a legitimate outcome for some fixture events (e.g. an
    # insider-confirmation quirk), not a bug; FAILED_TERMINAL/left at
    # STORED would be.
    assert recovered.stage in (
        ProcessingStage.COMPLETE, ProcessingStage.DELIVERY_QUEUED,
        ProcessingStage.SIGNIFICANCE_EVALUATED, ProcessingStage.PARTIAL,
    )
    stores.close()


def poller_poll_once_via(svc):
    return svc.poller.poll_once()


def test_reconcile_and_enrich_does_not_reprocess_completed_events(tmp_path, monkeypatch):
    """'Complete an event that produces no card; do not reprocess it
    forever.' A COMPLETE/DELIVERY_QUEUED row is a CLOSED stage -- must
    never be re-selected by next_for_processing, so a repeated recovery
    pass leaves it byte-unchanged (idempotent, no duplicate enrichment
    work, no duplicate card)."""
    svc, cfg, stores, client = _svc_stack(tmp_path, monkeypatch)
    asyncio.run(poller_poll_once_via(svc))

    # force every row to a definite CLOSED stage regardless of this
    # fixture's own natural per-event outcome, so the assertion below is
    # deterministic rather than dependent on fixture-specific quirks.
    rows_before = stores.processing._conn.execute(
        "SELECT event_id, updated_at_utc FROM intel_event_processing"
    ).fetchall()
    for eid, _ in rows_before:
        stores.processing._conn.execute(
            "UPDATE intel_event_processing SET stage='COMPLETE' WHERE event_id=?", (eid,)
        )
    stores.processing._conn.commit()
    before = dict(stores.processing._conn.execute(
        "SELECT event_id, updated_at_utc FROM intel_event_processing"
    ).fetchall())

    summary = asyncio.run(svc.reconcile_and_enrich())
    assert summary["reconciled"] == 0  # nothing orphaned -- every event already has a row
    assert summary["enriched"] == 0    # every row is CLOSED -> not selected by next_for_processing
    after = dict(stores.processing._conn.execute(
        "SELECT event_id, updated_at_utc FROM intel_event_processing"
    ).fetchall())
    assert after == before  # byte-identical -- genuinely untouched, not silently re-run
    stores.close()


def test_reconcile_and_enrich_one_bad_event_does_not_block_others(tmp_path, monkeypatch):
    svc, cfg, stores, client = _svc_stack(tmp_path, monkeypatch, enable_xbrl=False)
    asyncio.run(poller_poll_once_via(svc))

    # force every event back to an open stage (simulate an interrupted batch)
    rows = stores.processing._conn.execute("SELECT event_id FROM intel_event_processing").fetchall()
    for (eid,) in rows:
        stores.processing._conn.execute(
            "UPDATE intel_event_processing SET stage='ENRICHMENT_PENDING' WHERE event_id=?", (eid,)
        )
    stores.processing._conn.commit()

    real_process_event = svc.enrichment.process_event
    calls = []

    async def _flaky(event_id, **kw):
        calls.append(event_id)
        if len(calls) == 1:
            raise RuntimeError("simulated one bad event")
        return await real_process_event(event_id, **kw)

    monkeypatch.setattr(svc.enrichment, "process_event", _flaky)
    summary = asyncio.run(svc.reconcile_and_enrich())
    assert summary["failed"] == 1
    assert summary["enriched"] == len(rows) - 1  # every OTHER event still progressed
    stores.close()


def test_reconcile_and_enrich_replay_does_not_duplicate_cards(tmp_path, monkeypatch):
    """'Interrupt after card creation; retry without duplication.' A
    second reconcile_and_enrich pass over an already-DELIVERY_QUEUED /
    COMPLETE row must not enqueue a second outbox row for the same
    event_id -- the closed-stage guard plus _enqueue_delivery's own
    event_id-keyed dedup make a duplicate structurally impossible."""
    svc, cfg, stores, client = _svc_stack(tmp_path, monkeypatch,
                                          deliver_intelligence_cards=True, dry_run_delivery=False)
    asyncio.run(poller_poll_once_via(svc))
    outbox_count_before = stores.outbox.counts_by_state()

    for _ in range(3):
        asyncio.run(svc.reconcile_and_enrich())

    outbox_count_after = stores.outbox.counts_by_state()
    assert outbox_count_after == outbox_count_before  # not a single new/duplicated row
    stores.close()


def test_reconcile_and_enrich_bounded_batch_respects_limit(tmp_path, monkeypatch):
    svc, cfg, stores, client = _svc_stack(
        tmp_path, monkeypatch, enrich_max_events_per_cycle=1, enrich_time_budget_seconds=0,
    )
    asyncio.run(poller_poll_once_via(svc))
    rows = stores.processing._conn.execute("SELECT event_id FROM intel_event_processing").fetchall()
    assert len(rows) >= 2, "fixture must have >1 event for this bound to matter"
    for (eid,) in rows:
        stores.processing._conn.execute(
            "UPDATE intel_event_processing SET stage='ENRICHMENT_PENDING' WHERE event_id=?", (eid,)
        )
    stores.processing._conn.commit()

    summary = asyncio.run(svc.reconcile_and_enrich())
    assert summary["enriched"] == 1  # bounded, not "all of them"
    stores.close()


def test_reconcile_and_enrich_timeout_is_bounded_retryable_not_a_hang(tmp_path, monkeypatch):
    svc, cfg, stores, client = _svc_stack(tmp_path, monkeypatch,
                                          enrich_per_event_timeout_seconds=0.05)
    asyncio.run(poller_poll_once_via(svc))
    row = stores.processing._conn.execute("SELECT event_id FROM intel_event_processing LIMIT 1").fetchone()
    eid = row[0]
    stores.processing._conn.execute(
        "UPDATE intel_event_processing SET stage='ENRICHMENT_PENDING' WHERE event_id=?", (eid,)
    )
    stores.processing._conn.commit()

    async def _hang(event_id, **kw):
        await asyncio.sleep(5)

    monkeypatch.setattr(svc.enrichment, "process_event", _hang)
    summary = asyncio.run(svc.reconcile_and_enrich())
    assert summary["timed_out"] == 1
    row_after = stores.processing.get(eid)
    assert row_after.stage == ProcessingStage.FAILED_RETRYABLE
    assert row_after.retry_after_utc is not None  # bounded retry, not silently dropped
    stores.close()


# ---------------------------------------------------------------------
# 3. poller-level bounded inline enrichment defers overflow
# ---------------------------------------------------------------------

def test_poll_once_bounded_enrichment_defers_overflow_to_recovery(tmp_path):
    cfg, stores, client, poller, enrich = _stack(tmp_path, enrich_max_events_per_cycle=1)
    res = asyncio.run(poller.poll_once())
    assert len(res.new_event_ids) >= 2  # fixture yields >1 new event
    # exactly 1 was enriched inline; the rest are STORED (durable, not lost)
    rows = {r.event_id: r for r in stores.processing.open_rows(limit=100)}
    stored_only = [r for r in rows.values() if r.stage == ProcessingStage.STORED]
    assert len(stored_only) == len(res.new_event_ids) - 1
    for eid in res.new_event_ids:
        assert stores.processing.get(eid) is not None  # NONE lost
    stores.close()


# ---------------------------------------------------------------------
# 4. run_poll_loop: delivery gets a turn even with backlog remaining
# ---------------------------------------------------------------------

def test_run_poll_loop_calls_delivery_even_with_backlog_remaining(tmp_path, monkeypatch):
    svc, cfg, stores, client = _svc_stack(
        tmp_path, monkeypatch, enrich_max_events_per_cycle=1, poll_base_seconds=0.01,
    )
    delivery_mock = AsyncMock(return_value={"mode": "disabled", "ok": True})
    monkeypatch.setattr(svc, "deliver_cycle", delivery_mock)

    async def _go():
        await svc.open()
        return await svc.run_poll_loop(max_cycles=1)

    asyncio.run(_go())
    delivery_mock.assert_awaited_once()  # NOT starved by the (bounded) enrichment backlog


# ---------------------------------------------------------------------
# 5. genuine cross-process crash + recovery
# ---------------------------------------------------------------------

_CRASH_SCRIPT = textwrap.dedent("""
    import sys, os
    sys.path.insert(0, {repo!r})
    from datetime import datetime, timezone
    from talonx_ingest.intelligence.service.stores import StoreBundle
    from talonx_ingest.intelligence.service._ingest import ingest_symbol_filings
    from talonx_ingest.intelligence.service.state_machine import ProcessingStage
    from tests._service_helpers import make_submissions, default_rows

    ledger = sys.argv[1]
    stores = StoreBundle.open(ledger)
    now = datetime.now(timezone.utc)
    subs = make_submissions(cik=99999, ticker="CRASH", rows=default_rows())
    result = ingest_symbol_filings(
        stores.events, subs, symbol="CRASH",
        forms=("8-K", "10-Q", "10-K"), since_date=None, now=now,
    )
    assert result.new_event_ids, "fixture must persist at least one event"
    for eid in result.new_event_ids:
        ev = stores.events.get_event(eid)
        stores.processing.ensure(
            eid, symbol=ev.symbol, event_type=ev.event_type.value,
            form_type=ev.form_type, accession=ev.accession, origin="poll",
            stage=ProcessingStage.STORED,
        )
    sys.stdout.write("PERSISTED:" + ",".join(result.new_event_ids) + "\\n")
    sys.stdout.flush()
    os._exit(137)   # hard kill -- no clean shutdown, simulates a real crash,
                     # BEFORE process_event() (enrichment) is ever called
""")


@pytest.mark.skipif(sys.platform == "win32" and False, reason="")
def test_subprocess_crash_after_persist_before_enrich_is_recoverable(tmp_path):
    """Genuine cross-process interruption: a SEPARATE OS process persists
    a TextEvent + a STORED processing row, then hard-exits (os._exit,
    bypassing any graceful shutdown) BEFORE ever calling process_event().
    The test process then reopens the SAME ledger file cold (exactly what
    a managed restart does) and proves the event is recoverable --
    find_undiscovered_events / next_for_processing / reconcile_and_enrich
    all see it, with no corruption from the hard kill."""
    ledger = tmp_path / "crash_ledger.db"
    script = tmp_path / "crash_script.py"
    repo_root = str(__import__("pathlib").Path(__file__).resolve().parents[1])
    script.write_text(_CRASH_SCRIPT.format(repo=repo_root), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(script), str(ledger)],
        capture_output=True, text=True, timeout=30,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
    )
    assert "PERSISTED:" in proc.stdout, f"child did not reach persistence: {proc.stdout} {proc.stderr}"
    assert proc.returncode == 137  # confirms the hard kill actually happened, not a clean exit
    persisted_ids = proc.stdout.strip().split("PERSISTED:", 1)[1].split(",")
    assert persisted_ids

    # --- cold reopen in THIS process, exactly like a managed restart ---
    stores = StoreBundle.open(str(ledger))
    for eid in persisted_ids:
        row = stores.processing.get(eid)
        assert row is not None and row.stage == ProcessingStage.STORED

    orphans = stores.processing.find_undiscovered_events(limit=10)
    assert orphans == []  # every persisted event DOES have a row -- "interrupted", not "orphaned"
    due = [r.event_id for r in stores.processing.next_for_processing(limit=10)]
    for eid in persisted_ids:
        assert eid in due  # recoverable: a fresh process's recovery pass will pick it up

    # prove recovery actually completes the work, not just sees it
    cfg = ServiceConfig(ledger_path=str(ledger), state_dir=tmp_path / "state2")
    client = FakeEdgarClient(submissions={})
    directory = CikDirectory.from_company_tickers({})
    from talonx_ingest.intelligence.service.scope import IngestionScope
    enrich = EnrichmentEngine(
        stores, client, config=cfg, cache=FilingArchiveCache(client, cache_dir=tmp_path / "cache2"),
    )
    svc = IntelligenceService(cfg)
    svc.stores = stores
    svc.enrichment = enrich
    summary = asyncio.run(svc.reconcile_and_enrich())
    assert summary["enriched"] >= len(persisted_ids)
    for eid in persisted_ids:
        row = stores.processing.get(eid)
        # real progress past the bare STORED registration -- PARTIAL is a
        # legitimate outcome for some fixture events, not a bug.
        assert row.stage in (
            ProcessingStage.COMPLETE, ProcessingStage.DELIVERY_QUEUED,
            ProcessingStage.SIGNIFICANCE_EVALUATED, ProcessingStage.PARTIAL,
        )
    stores.close()
