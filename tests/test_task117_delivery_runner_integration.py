"""
Task 117 -- the intelligence-card delivery drain is WIRED into the real
supervised service path (``IntelligenceService.deliver_cycle`` /
``run_poll_loop``), with a safe disabled default, explicit config, and the
existing official transport adapter.

disabled -> enabled -> restart -> successful send, with a fresh event never
lost by a disabled cycle, and a stale backlog row never sent.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import talonx_ingest.intelligence.delivery.pipeline as dp
from talonx_ingest.intelligence.delivery.outbox import (
    STATE_EXPIRED, STATE_PENDING, STATE_SENT, DeliveryOutbox,
)
from talonx_ingest.intelligence.delivery.pipeline import enqueue_card
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.runner import IntelligenceService
from talonx_ingest.intelligence.service.stores import StoreBundle
from _delivery_helpers import make_card

UTC = timezone.utc
NOW = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)


class _Intercept:
    """Stands in for TelegramSenderAdapter -- the network boundary, intercepted."""
    def __init__(self, *, configured=True, ambiguous_for=None):
        self.configured = configured
        self.sent = []
        self._ambig = ambiguous_for or set()

    async def send(self, row):
        if row.delivery_id in self._ambig:
            return dp.SenderResult(ok=False, ambiguous=True, error="intercepted timeout")
        self.sent.append(row.delivery_id)
        return dp.SenderResult(ok=True)


def _svc(tmp_path, **cfg_over):
    cfg = ServiceConfig(ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "state",
                        **cfg_over)
    svc = IntelligenceService(cfg)
    svc.stores = StoreBundle.open(cfg.ledger())
    return svc, cfg


def _enqueue(svc, *, symbol, accession, enqueued_at):
    card, wc = make_card(symbol=symbol, accession=accession, on_watchlist=True, now=enqueued_at)
    return enqueue_card(card, outbox=svc.stores.outbox, now=enqueued_at).row.delivery_id


def test_disabled_by_default_holds_then_enable_sends_after_restart(tmp_path, monkeypatch):
    svc, cfg = _svc(tmp_path)                       # deliver_intelligence_cards defaults False
    did = _enqueue(svc, symbol="ORCL", accession="0001193125-26-387905",
                   enqueued_at=NOW - timedelta(minutes=10))

    inter = _Intercept()
    monkeypatch.setattr(dp, "TelegramSenderAdapter", lambda *a, **k: inter)

    # --- cycle 1: delivery disabled -> row HELD, still PENDING, nothing sent
    s1 = asyncio.run(svc.deliver_cycle(now=NOW))
    assert s1["mode"] == "disabled"
    assert s1["IMMEDIATE"]["held"] >= 1 and s1["IMMEDIATE"]["delivered"] == 0
    assert inter.sent == []
    assert svc.stores.outbox.get(did).state == STATE_PENDING     # NOT lost

    svc.stores.outbox.close()

    # --- RESTART with delivery enabled ---------------------------------
    svc2, cfg2 = _svc(tmp_path, deliver_intelligence_cards=True, dry_run_delivery=False,
                      poll_base_seconds=0.01)
    inter2 = _Intercept()
    monkeypatch.setattr(dp, "TelegramSenderAdapter", lambda *a, **k: inter2)

    s2 = asyncio.run(svc2.deliver_cycle(now=NOW + timedelta(minutes=5)))
    assert s2["mode"] == "enabled"
    assert s2["IMMEDIATE"]["delivered"] == 1
    assert inter2.sent == [did]                                  # the SAME fresh row
    assert svc2.stores.outbox.get(did).state == STATE_SENT
    svc2.stores.outbox.close()


def test_enabled_cycle_expires_stale_backlog_and_delivers_only_fresh(tmp_path, monkeypatch):
    svc, cfg = _svc(tmp_path, deliver_intelligence_cards=True, dry_run_delivery=False)
    stale = _enqueue(svc, symbol="DELL", accession="0001193125-26-386868",
                     enqueued_at=NOW - timedelta(days=6))
    fresh = _enqueue(svc, symbol="ORCL", accession="0001193125-26-387905",
                     enqueued_at=NOW - timedelta(minutes=15))

    inter = _Intercept()
    monkeypatch.setattr(dp, "TelegramSenderAdapter", lambda *a, **k: inter)

    s = asyncio.run(svc.deliver_cycle(now=NOW))
    assert svc.stores.outbox.get(stale).state == STATE_EXPIRED
    assert svc.stores.outbox.get(fresh).state == STATE_SENT
    assert inter.sent == [fresh]                                 # backlog NOT flooded
    svc.stores.outbox.close()


def test_old_event_enqueued_today_is_not_fresh(tmp_path, monkeypatch):
    """Freshness is measured from the older of (event time, enqueue time)."""
    from talonx_ingest.intelligence.domain import TextEvent, EventType, SourceType

    svc, cfg = _svc(tmp_path, deliver_intelligence_cards=True, dry_run_delivery=False)
    did = _enqueue(svc, symbol="ORCL", accession="0001193125-26-387905",
                   enqueued_at=NOW - timedelta(minutes=5))          # enqueued just now
    row = svc.stores.outbox.get(did)
    # ...but the underlying event was accepted 5 days ago
    svc.stores.events.upsert_event(TextEvent(
        event_id=row.event_id, symbol="ORCL", company_name="ORACLE CORP",
        source_type=SourceType.SEC_EDGAR_SUBMISSIONS, source_record_id="x",
        event_type=EventType.EARNINGS_RESULTS, form_type="8-K",
        accession="0001193125-26-387905",
        accepted_at_utc=NOW - timedelta(days=5),
        ingested_at_utc=NOW - timedelta(days=5),
    ))
    inter = _Intercept()
    monkeypatch.setattr(dp, "TelegramSenderAdapter", lambda *a, **k: inter)

    asyncio.run(svc.deliver_cycle(now=NOW))
    assert svc.stores.outbox.get(did).state == STATE_EXPIRED
    assert "event_time" in (svc.stores.outbox.get(did).suppress_reason or "")
    assert inter.sent == []
    svc.stores.outbox.close()


def test_ambiguous_send_is_durable_and_not_retried(tmp_path, monkeypatch):
    svc, cfg = _svc(tmp_path, deliver_intelligence_cards=True, dry_run_delivery=False)
    did = _enqueue(svc, symbol="ORCL", accession="0001193125-26-387905",
                   enqueued_at=NOW - timedelta(minutes=5))
    inter = _Intercept(ambiguous_for={did})
    monkeypatch.setattr(dp, "TelegramSenderAdapter", lambda *a, **k: inter)

    asyncio.run(svc.deliver_cycle(now=NOW))
    r = svc.stores.outbox.get(did)
    assert r.state == "AMBIGUOUS"
    # a second cycle must NOT blind-retry an ambiguous row
    s2 = asyncio.run(svc.deliver_cycle(now=NOW + timedelta(minutes=1)))
    assert svc.stores.outbox.get(did).state == "AMBIGUOUS"
    assert s2["IMMEDIATE"]["delivered"] == 0
    svc.stores.outbox.close()


def test_digest_not_treated_as_immediate(tmp_path, monkeypatch):
    svc, cfg = _svc(tmp_path, deliver_intelligence_cards=True, dry_run_delivery=False,
                    deliver_cards_per_cycle=1)
    # one IMMEDIATE (HIGH) + one DIGEST (MEDIUM) fresh row
    imm = _enqueue(svc, symbol="ORCL", accession="0001193125-26-387905",
                   enqueued_at=NOW - timedelta(minutes=5))
    from _delivery_helpers import make_card
    from talonx_ingest.intelligence.domain import EventType
    card, _ = make_card(symbol="TSLA", event_type=EventType.INSIDER_TRANSACTION,
                        accession="0001104659-26-106432", on_watchlist=False, now=NOW)
    dig = enqueue_card(card, outbox=svc.stores.outbox, now=NOW - timedelta(minutes=5)).row
    inter = _Intercept()
    monkeypatch.setattr(dp, "TelegramSenderAdapter", lambda *a, **k: inter)

    s = asyncio.run(svc.deliver_cycle(now=NOW))
    # IMMEDIATE route processed first and separately from DIGEST
    assert "IMMEDIATE" in s and "DIGEST" in s
    assert svc.stores.outbox.get(imm).route == "IMMEDIATE"
    assert dig.route == "DIGEST"
    svc.stores.outbox.close()
