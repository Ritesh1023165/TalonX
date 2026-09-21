"""
Task 117 output-closure -- D5: intelligence-delivery age/cutoff policy.

The ``intelligence_delivery`` outbox has never drained (9,843 rows, 100% PENDING,
0 ever SENT). Before wiring a drain into the running service, the drain must be
unable to flood Telegram with a historical backlog. These tests pin the
age/cutoff behaviour: on the first real drain every stale PENDING row goes
straight to EXPIRED (terminal, audit-preserving) and NOTHING is sent.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from talonx_ingest.intelligence.delivery.config import CARD_MAX_AGE_SECONDS, ROUTE_IMMEDIATE
from talonx_ingest.intelligence.delivery.outbox import (
    STATE_EXPIRED,
    STATE_PENDING,
    STATE_SENT,
    STATE_SUPPRESSED,
    DeliveryOutbox,
)
from talonx_ingest.intelligence.delivery.pipeline import (
    RecordingSender,
    enqueue_card,
    process_pending,
)
from _delivery_helpers import make_card

UTC = timezone.utc


def _enq(ob, *, symbol, accession, enqueued_at):
    card, _ = make_card(symbol=symbol, accession=accession, on_watchlist=True, now=enqueued_at)
    return enqueue_card(card, outbox=ob, now=enqueued_at).row.delivery_id


def _drain(ob, sender, **kw):
    kw.setdefault("mode", "enabled")
    return asyncio.run(process_pending(ob, sender, **kw))


def test_stale_rows_expire_and_nothing_is_sent(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    old = now - timedelta(days=6)                       # a Sep-4-style backlog row
    did = _enq(ob, symbol="DELL", accession="0001193125-26-386868", enqueued_at=old)
    assert ob.get(did).state == STATE_PENDING

    snd = RecordingSender()
    res = _drain(ob, snd, now=now, enforce_age_cutoff=True)

    assert res.expired == 1 and did in res.expired_ids
    assert res.attempted == 0 and res.delivered == 0
    assert snd.sent == []                               # NOT flooded
    row = ob.get(did)
    assert row.state == STATE_EXPIRED
    assert "stale_card" in (row.suppress_reason or "")
    # audit trail preserved
    kinds = [l["kind"] for l in ob.logs(did)]
    assert "ENQUEUE" in kinds and "EXPIRED" in kinds
    assert "SENT" not in kinds
    ob.close()


def test_fresh_row_still_delivers_alongside_expiring_a_stale_one(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    stale = _enq(ob, symbol="DELL", accession="0001193125-26-386868",
                 enqueued_at=now - timedelta(hours=30))
    fresh = _enq(ob, symbol="ORCL", accession="0001193125-26-387905",
                 enqueued_at=now - timedelta(minutes=20))

    snd = RecordingSender()
    res = _drain(ob, snd, now=now, enforce_age_cutoff=True)

    assert ob.get(stale).state == STATE_EXPIRED
    assert ob.get(fresh).state == STATE_SENT
    assert res.expired == 1 and res.delivered == 1 and len(snd.sent) == 1
    ob.close()


def test_immediate_cutoff_is_six_hours(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    assert CARD_MAX_AGE_SECONDS[ROUTE_IMMEDIATE] == 6 * 3600
    just_ok = _enq(ob, symbol="V", accession="0001403161-26-000118",
                   enqueued_at=now - timedelta(hours=5, minutes=55))
    too_old = _enq(ob, symbol="ADP", accession="0001225208-26-007726",
                   enqueued_at=now - timedelta(hours=6, minutes=5))
    _drain(ob, RecordingSender(), now=now, enforce_age_cutoff=True)
    assert ob.get(just_ok).state == STATE_SENT
    assert ob.get(too_old).state == STATE_EXPIRED
    ob.close()


def test_expire_stale_is_idempotent_and_never_touches_terminal_rows(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    did = _enq(ob, symbol="DELL", accession="0001193125-26-386868",
               enqueued_at=now - timedelta(days=3))
    first = ob.expire_stale(now=now)
    second = ob.expire_stale(now=now)
    assert first == [did] and second == []              # idempotent
    assert ob.get(did).state == STATE_EXPIRED
    ob.close()


def test_default_drain_unchanged_without_opt_in(ledger_path):
    """The pure drain mechanics for existing callers are unaffected: no age
    cutoff unless enforce_age_cutoff=True is passed."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    did = _enq(ob, symbol="DELL", accession="0001193125-26-386868",
               enqueued_at=now - timedelta(days=30))
    res = _drain(ob, RecordingSender(), now=now)        # no enforce_age_cutoff
    assert res.expired == 0
    assert ob.get(did).state == STATE_SENT
    ob.close()


# ---------------------------------------------------------------------
# Task 133 P0: expire_stale must be boundable. A large PENDING backlog +
# an event_time_lookup (what deliver_cycle always passes) makes the
# unbounded scan do ONE SYNCHRONOUS DB read per PENDING row -- confirmed
# live to make the whole Intelligence process unresponsive for minutes
# (asyncio.wait_for's timeout around the caller cannot preempt a
# synchronous loop with no `await` inside it). limit=None preserves the
# exact old behaviour for every existing caller above; a real caller with
# a large volume MUST pass a bound.
# ---------------------------------------------------------------------

def test_expire_stale_default_is_unbounded_scans_every_pending_row(ledger_path):
    """Task 136B: a lookup that ran cleanly and found NOTHING for every one
    of these rows makes them UNQUALIFIED (SUPPRESSED), not EXPIRED -- there
    is no established age to report, only an absence of evidence. The scan
    coverage/boundedness behaviour under test is unchanged; only the
    resulting disposition is corrected."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    dids = [
        _enq(ob, symbol="DELL", accession=f"0001193125-26-{386800 + i}",
             enqueued_at=now - timedelta(days=3))
        for i in range(12)
    ]
    lookups = []

    def _lookup(event_id):
        lookups.append(event_id)
        return None

    expired = ob.expire_stale(now=now, event_time_lookup=_lookup)
    assert expired == []                             # none PROVEN old -- no evidence at all
    assert len(lookups) == 12          # every row scanned -- unchanged default behaviour
    assert all(ob.get(d).state == STATE_SUPPRESSED for d in dids)
    assert all("unqualified" in (ob.get(d).suppress_reason or "") for d in dids)
    ob.close()


def test_expire_stale_limit_bounds_the_scan_oldest_first(ledger_path):
    """The actual Task 133 fix: with a limit, at most `limit` rows are
    inspected (and at most `limit` calls made to event_time_lookup) no
    matter how many PENDING rows exist -- oldest enqueued_at_utc first,
    so the rows most likely to be genuinely stale are the ones handled
    each bounded pass.

    Task 136B: with no event-time evidence at all for any of them, the
    inspected rows become UNQUALIFIED (SUPPRESSED), not EXPIRED -- see
    ``test_expire_stale_default_is_unbounded_scans_every_pending_row``."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    older = [
        _enq(ob, symbol="DELL", accession=f"0001193125-26-{386800 + i}",
             enqueued_at=now - timedelta(days=3, hours=i))
        for i in range(20)
    ]
    newer = [
        _enq(ob, symbol="ORCL", accession=f"0001193125-26-{387900 + i}",
             enqueued_at=now - timedelta(minutes=i))
        for i in range(20)
    ]
    lookups = []

    def _lookup(event_id):
        lookups.append(event_id)
        return None

    expired = ob.expire_stale(now=now, event_time_lookup=_lookup, limit=5)
    assert len(lookups) == 5                       # bounded -- NOT all 40 PENDING rows
    assert expired == []                            # none PROVEN old -- no evidence at all
    touched = [d for d in older if ob.get(d).state == STATE_SUPPRESSED]
    assert len(touched) == 5
    assert set(touched).issubset(set(older))        # oldest-first, not last-in-first-out
    # nothing from the fresh batch was even inspected, let alone touched
    assert all(ob.get(d).state == STATE_PENDING for d in newer)
    ob.close()


def test_expire_stale_limit_makes_full_backlog_progress_over_several_calls(ledger_path):
    """A bounded scan still eventually covers the WHOLE backlog -- calling
    it repeatedly (as deliver_cycle does, once per poll-loop iteration)
    drains a large stale backlog completely, just spread over multiple
    calls instead of one unbounded one."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    dids = [
        _enq(ob, symbol="DELL", accession=f"0001193125-26-{386800 + i}",
             enqueued_at=now - timedelta(days=3, minutes=i))
        for i in range(23)
    ]
    total_expired: list[str] = []
    for _ in range(6):  # 6 * 5 = 30 >= 23 -- enough passes to cover everything
        total_expired.extend(ob.expire_stale(now=now, limit=5))
    assert set(total_expired) == set(dids)
    assert all(ob.get(d).state == STATE_EXPIRED for d in dids)
    ob.close()


@pytest.mark.asyncio
async def test_process_pending_and_process_digest_thread_the_expire_scan_limit(ledger_path, monkeypatch):
    """Confirms deliver_cycle's actual fix end-to-end: process_pending's
    (and process_digest's) expire_scan_limit reaches outbox.expire_stale,
    not just a plumbing no-op."""
    from talonx_ingest.intelligence.delivery.pipeline import process_digest, process_pending

    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    for i in range(10):
        _enq(ob, symbol="DELL", accession=f"0001193125-26-{386800 + i}",
             enqueued_at=now - timedelta(days=3, minutes=i))

    seen = {"count": 0}
    real_expire = ob.expire_stale

    def _spy(*a, **kw):
        seen["count"] += 1
        seen["limit"] = kw.get("limit")
        return real_expire(*a, **kw)

    monkeypatch.setattr(ob, "expire_stale", _spy)

    await process_pending(ob, RecordingSender(), mode="enabled", route="IMMEDIATE",
                          now=now, enforce_age_cutoff=True, expire_scan_limit=3)
    assert seen["limit"] == 3

    await process_digest(ob, RecordingSender(), mode="enabled", interval_seconds=21600,
                         now=now, enforce_age_cutoff=True, expire_scan_limit=7)
    assert seen["limit"] == 7
    ob.close()


# ---------------------------------------------------------------------
# Task 136A: reproduces the ACN incident precisely -- a HIGH-band stale
# card, enqueued AFTER a pile of other PENDING rows, was sent (4 real
# Telegram messages, 2024-vintage ACN Form 4s delivered 2026-09-14) even
# though it was over two years past the 6h IMMEDIATE cutoff. Root cause:
# outbox.pending() orders by BAND PRIORITY first, then enqueue time --
# completely independent of expire_stale()'s own enqueue-time-ordered,
# BOUNDED sweep. A HIGH-band row enqueued late (beyond the bound) can be
# selected for sending before the bounded sweep ever reaches it.
# ---------------------------------------------------------------------

def _enq_with_band(ob, *, symbol, accession, enqueued_at, band):
    did = _enq(ob, symbol=symbol, accession=accession, enqueued_at=enqueued_at)
    ob._conn.execute("UPDATE intelligence_delivery SET band=? WHERE delivery_id=?", (band, did))
    ob._conn.commit()
    return did


def test_high_band_stale_card_cannot_jump_the_bounded_expire_sweep(ledger_path):
    """The exact discovered defect, reproduced then fixed: with a small
    expire_scan_limit, a stale HIGH-band row enqueued AFTER many older-
    enqueued LOW-band filler rows is NOT reached by the bounded sweep
    (limit smaller than the filler count) -- yet outbox.pending()'s
    band-first ordering would select it to send FIRST. The per-row gate
    (outbox.expire_one_if_stale, called inline in process_pending's send
    loop) must catch it anyway."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)

    # 5 older-enqueued, LOW-band, genuinely FRESH filler rows (a REAL,
    # verified-fresh event_time each, matching their enqueue time -- Task
    # 136B: unknown event-time evidence is no longer treated as "fresh via
    # enqueue time", so these must carry real, positively-fresh evidence to
    # exercise "fresh rows still deliver" meaningfully) -- these are what a
    # bounded (limit=2) expire_stale() sweep actually reaches first.
    filler_accessions = [f"0001193125-26-{386800 + i}" for i in range(5)]
    fillers = [
        _enq_with_band(ob, symbol="DELL", accession=filler_accessions[i],
                       enqueued_at=now - timedelta(minutes=30 - i), band="LOW")
        for i in range(5)
    ]
    filler_event_times = {
        filler_accessions[i]: now - timedelta(minutes=30 - i) for i in range(5)
    }
    # the ACN-shaped card: enqueued LAST (so the bounded-by-enqueue-order
    # sweep never reaches it), HIGH band (so pending() selects it FIRST
    # despite that), and genuinely stale (a 2024 event_time).
    stale_high = _enq_with_band(ob, symbol="ACN", accession="0001467373-24-000206",
                                enqueued_at=now - timedelta(seconds=1), band="HIGH")

    def _event_time(event_id):
        if "0001467373-24-000206" in event_id:
            return datetime(2024, 7, 15, 20, 14, 1, tzinfo=UTC)
        for acc, evt in filler_event_times.items():
            if acc in event_id:
                return evt
        return None

    snd = RecordingSender()
    res = _drain(
        ob, snd, now=now, enforce_age_cutoff=True,
        event_time_lookup=_event_time, expire_scan_limit=2,  # deliberately too small to reach stale_high
    )

    assert ob.get(stale_high).state == STATE_EXPIRED
    assert "stale_card" in (ob.get(stale_high).suppress_reason or "")
    assert stale_high not in [r.delivery_id for r in snd.sent]
    # the genuinely fresh filler rows still deliver -- this is NOT a
    # blanket pause, only the specific stale row is blocked
    assert all(ob.get(d).state == STATE_SENT for d in fillers)
    assert res.expired >= 1
    ob.close()
