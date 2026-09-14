"""
tests/test_task136b_freshness_edge_cases.py
--------------------------------------------
Task 136B: closes the two freshness defects left open after Task 136A --

1. Unknown/missing source-publication-time evidence must not fall back to
   queue-creation (enqueue) time as proof of freshness (``_expire_row_if_
   stale`` now distinguishes OK / EXPIRED / UNQUALIFIED / DEFER instead of
   silently treating "no event time" the same as "fresh").
2. The FINAL send-time freshness decision must use a clock read fresh at
   that decision point, not a single ``now`` value reused across an entire
   drain batch (the new ``clock`` parameter on ``process_pending`` /
   ``process_digest``).

Every test here uses an isolated, on-disk (restart-simulating) outbox and
either a fixed injected ``now`` or an explicitly-controlled ``clock``
callable -- nothing here depends on real wall-clock time. Assertions check
actual sender calls (``RecordingSender.sent``) and final row states, not
merely a helper's return value.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from talonx_ingest.intelligence.domain import EventType
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
    process_digest,
    process_pending,
)
from _delivery_helpers import make_card

UTC = timezone.utc


def _enq(ob, *, symbol, accession, enqueued_at, event_type=EventType.EARNINGS_RESULTS,
         on_watchlist=True):
    card, _ = make_card(symbol=symbol, accession=accession, event_type=event_type,
                        on_watchlist=on_watchlist, now=enqueued_at)
    r = enqueue_card(card, outbox=ob, now=enqueued_at).row
    return r.delivery_id, r.event_id, r.route


def _enq_digest(ob, *, symbol, accession, enqueued_at):
    did, eid, route = _enq(ob, symbol=symbol, accession=accession, enqueued_at=enqueued_at,
                           event_type=EventType.INSIDER_TRANSACTION, on_watchlist=False)
    assert route == "DIGEST"
    return did, eid


def _drain(ob, sender, **kw):
    kw.setdefault("mode", "enabled")
    kw.setdefault("enforce_age_cutoff", True)
    return asyncio.run(process_pending(ob, sender, **kw))


def _digest(ob, sender, **kw):
    kw.setdefault("mode", "enabled")
    kw.setdefault("enforce_age_cutoff", True)
    return asyncio.run(process_digest(ob, sender, **kw))


class _StepClock:
    """A fully test-controlled clock -- returns each of ``times`` once, in
    order, one call at a time; repeats the final value forever once
    exhausted. Never touches real wall time, and is never mixed with an
    injected historical ``now`` -- see process_pending/process_digest's own
    ``clock`` docstring for why the default (reuse ``now``) would otherwise
    hide exactly the race this proves is closed."""

    def __init__(self, times):
        self._times = list(times)
        self._i = 0
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self._i < len(self._times):
            t = self._times[self._i]
            self._i += 1
            return t
        return self._times[-1]


# ---------------------------------------------------------------------
# 1) unknown-publication-time enforcement
# ---------------------------------------------------------------------

def test_historical_source_with_fresh_enqueue_time_is_blocked(ledger_path):
    """A card enqueued moments ago (e.g. a re-processed/backfilled row) but
    whose SOURCE publication time is genuinely years old must NOT be
    delivered -- the older-of-source/enqueue policy (unchanged from Task
    136A) still applies whenever the source timestamp IS valid."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    did, eid, _ = _enq(ob, symbol="ACN", accession="0001467373-24-000206",
                       enqueued_at=now - timedelta(seconds=5))
    old_event_time = datetime(2024, 7, 15, 20, 14, 1, tzinfo=UTC)

    def _lookup(event_id):
        return old_event_time

    snd = RecordingSender()
    res = _drain(ob, snd, now=now, event_time_lookup=_lookup, route="IMMEDIATE")
    row = ob.get(did)
    assert row.state == STATE_EXPIRED
    assert "stale_card" in (row.suppress_reason or "")
    assert snd.sent == []
    assert res.expired == 1 and did in res.expired_ids
    ob.close()


def test_missing_source_time_cannot_qualify_through_enqueue_time(ledger_path):
    """The core Task 136B defect: a lookup that ran CLEANLY and found NO
    publication evidence must not let a freshly-enqueued row through on
    enqueue time alone -- it is held/suppressed with a truthful reason, not
    silently treated as fresh, and not mislabelled "expired by age" (no age
    was ever established)."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    did, eid, _ = _enq(ob, symbol="ACN", accession="0001467373-24-000206",
                       enqueued_at=now - timedelta(seconds=5))

    def _lookup(event_id):
        return None                          # ran cleanly; genuinely no evidence

    snd = RecordingSender()
    res = _drain(ob, snd, now=now, event_time_lookup=_lookup, route="IMMEDIATE")
    row = ob.get(did)
    assert row.state == STATE_SUPPRESSED     # NOT STATE_EXPIRED -- no age was established
    assert "unqualified" in (row.suppress_reason or "")
    assert snd.sent == []
    assert res.unqualified == 1 and did in res.unqualified_ids
    assert res.expired == 0
    ob.close()


def test_lookup_failure_defers_and_remains_recoverable(ledger_path):
    """A transient lookup FAILURE (an exception, e.g. a DB hiccup) must not
    send, must not mark the row terminal either way, and must self-heal
    (deliver normally) once the lookup recovers on a later, bounded
    retry -- distinct from a lookup that ran and genuinely found nothing."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    did, eid, _ = _enq(ob, symbol="ACN", accession="0001467373-24-000206",
                       enqueued_at=now - timedelta(seconds=5))

    calls = {"n": 0}

    def _flaky_lookup(event_id):
        calls["n"] += 1
        raise RuntimeError("simulated DB error")

    snd = RecordingSender()
    res = _drain(ob, snd, now=now, event_time_lookup=_flaky_lookup, route="IMMEDIATE")
    row = ob.get(did)
    assert row.state == STATE_PENDING            # left completely untouched -- not terminal
    assert snd.sent == []
    assert res.expired == 0 and res.unqualified == 0   # neither verdict was reached
    # the lookup is consulted twice per drain pass by design -- once by the
    # bulk expire_stale() sweep, once more by the per-row inline gate
    # immediately before send (the two independent checks Task 136A/136B
    # deliberately keep in agreement) -- a DEFER from either leaves the row
    # untouched, so both see the same still-PENDING row.
    assert calls["n"] == 2

    def _recovered_lookup(event_id):
        return now - timedelta(seconds=5)          # a genuinely fresh, valid time

    res2 = _drain(ob, snd, now=now + timedelta(seconds=1),
                  event_time_lookup=_recovered_lookup, route="IMMEDIATE")
    assert ob.get(did).state == STATE_SENT
    assert did in [r.delivery_id for r in snd.sent]
    ob.close()


def test_naive_and_future_timestamps_are_explicitly_rejected(ledger_path):
    """A malformed (timezone-naive) or impossible (future) source timestamp
    is explicitly validated and rejected with a specific reason -- neither
    silently accepted at face value nor silently dropped to enqueue time."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    naive_did, naive_eid, _ = _enq(ob, symbol="ACN", accession="0001467373-24-000205",
                                   enqueued_at=now - timedelta(seconds=5))
    future_did, future_eid, _ = _enq(ob, symbol="ACN", accession="0001467373-24-000206",
                                     enqueued_at=now - timedelta(seconds=4))

    def _lookup(event_id):
        if event_id == naive_eid:
            return datetime(2026, 9, 14, 15, 0, 0)      # naive -- no tzinfo
        if event_id == future_eid:
            return now + timedelta(hours=2)              # impossible future time
        return None

    snd = RecordingSender()
    _drain(ob, snd, now=now, event_time_lookup=_lookup, route="IMMEDIATE")
    naive_row = ob.get(naive_did)
    future_row = ob.get(future_did)
    assert naive_row.state == STATE_SUPPRESSED
    assert "timezone-naive" in (naive_row.suppress_reason or "")
    assert future_row.state == STATE_SUPPRESSED
    assert "future" in (future_row.suppress_reason or "")
    assert snd.sent == []
    ob.close()


def test_valid_fresh_event_still_delivers(ledger_path):
    """The corrected rule does not become a new strategy filter -- a card
    WITH genuine, valid, fresh publication evidence is delivered exactly as
    before."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    did, eid, _ = _enq(ob, symbol="MSFT", accession="0000789019-26-000099",
                       enqueued_at=now - timedelta(minutes=10))

    def _lookup(event_id):
        return now - timedelta(minutes=12)

    snd = RecordingSender()
    _drain(ob, snd, now=now, event_time_lookup=_lookup, route="IMMEDIATE")
    assert ob.get(did).state == STATE_SENT
    assert did in [r.delivery_id for r in snd.sent]
    ob.close()


# ---------------------------------------------------------------------
# 2) actual send-time clock
# ---------------------------------------------------------------------

def test_clock_advances_during_batch_processing_expires_a_later_row(ledger_path):
    """Row A is processed first (fresh); by the time row B's OWN freshness
    decision is made, the injected clock has moved past B's cutoff -- B
    must be blocked even though it was selected in the same, single drain
    pass as A. This is the exact process_pending gap Task 136B closes: the
    stale, drain-level `now` can no longer stand in for each row's own
    send-decision time."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    did_a, eid_a, _ = _enq(ob, symbol="AAA", accession="0000000001-26-000001",
                           enqueued_at=now - timedelta(minutes=10))
    did_b, eid_b, _ = _enq(ob, symbol="BBB", accession="0000000002-26-000002",
                           enqueued_at=now - timedelta(minutes=9))
    event_times = {eid_a: now - timedelta(minutes=10), eid_b: now - timedelta(minutes=9)}

    def _lookup(event_id):
        return event_times.get(event_id)

    # row A's decision clock reads "now" (fresh); row B's reads 7h later,
    # crossing the 6h IMMEDIATE cutoff.
    clock = _StepClock([now, now + timedelta(hours=7)])
    snd = RecordingSender()
    res = _drain(ob, snd, now=now, event_time_lookup=_lookup, route="IMMEDIATE", clock=clock)

    assert ob.get(did_a).state == STATE_SENT
    assert ob.get(did_b).state == STATE_EXPIRED
    assert [r.delivery_id for r in snd.sent] == [did_a]
    assert clock.calls == 2
    ob.close()


def test_retry_crosses_the_cutoff_and_is_not_sent(ledger_path):
    """A row that failed transiently on its first attempt and is re-drained
    later, after its cutoff has since passed, is NOT sent on the retry --
    every retry re-evaluates freshness, it is not grandfathered in by
    having been attempted once while still fresh."""
    ob = DeliveryOutbox(ledger_path)
    t1 = datetime(2026, 9, 14, 10, 0, 0, tzinfo=UTC)
    did, eid, _ = _enq(ob, symbol="CCC", accession="0000000003-26-000003", enqueued_at=t1)

    def _lookup(event_id):
        return t1                                # fixed, valid publication time

    snd = RecordingSender(fail_times=1, retry_after_seconds=30)
    _drain(ob, snd, now=t1, event_time_lookup=_lookup, route="IMMEDIATE")
    row = ob.get(did)
    assert row.state == STATE_PENDING and (row.attempts or 0) == 1
    assert snd.attempts == 1

    t2 = t1 + timedelta(hours=7)                 # past the 6h IMMEDIATE cutoff
    _drain(ob, snd, now=t2, event_time_lookup=_lookup, route="IMMEDIATE")
    assert ob.get(did).state == STATE_EXPIRED
    assert snd.attempts == 1                     # sender never invoked again
    ob.close()


def test_mixed_digest_sends_only_still_eligible_cards(ledger_path):
    """A DIGEST batch with two rows: one is still eligible at the FINAL
    send decision, the other has crossed its cutoff in the interim -- the
    digest is rebuilt to include only the survivor, and the excluded card
    is never marked SENT alongside it.

    The whole digest renders and sends as ONE message at ONE moment, so
    the final-decision clock is read ONCE and applied uniformly to every
    constituent card (not walked per-card with an artificially advancing
    clock) -- did2 starts the batch already close to its 24h cutoff, so
    the SAME modest, realistic rendering-delay jump pushes only it over
    the line while did1 (enqueued far more recently) stays comfortably
    inside it."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
    did1, eid1 = _enq_digest(ob, symbol="TSLA", accession="0001104659-26-000021",
                             enqueued_at=now - timedelta(minutes=5))
    did2, eid2 = _enq_digest(ob, symbol="NVDA", accession="0001045810-26-000022",
                             enqueued_at=now - timedelta(hours=23, minutes=50))
    times = {eid1: now - timedelta(minutes=5), eid2: now - timedelta(hours=23, minutes=50)}

    def _lookup(event_id):
        return times.get(event_id)

    # early-selection filter: 2 calls, both read "now" -- did2 is 23h50m
    # old, still just inside the 24h DIGEST cutoff, so both pass. The
    # single final-decision call jumps 20 real minutes forward (assembling
    # + rendering the batch) -- did1 is still ~25m old (fine); did2 is now
    # ~24h10m old (over cutoff).
    clock = _StepClock([now, now, now + timedelta(minutes=20)])
    snd = RecordingSender()
    res = _digest(ob, snd, interval_seconds=6 * 3600.0, now=now,
                 event_time_lookup=_lookup, clock=clock)

    assert ob.get(did1).state == STATE_SENT
    assert ob.get(did2).state == STATE_EXPIRED
    assert len(snd.sent) == 1
    text = snd.sent[0].text
    assert "TSLA" in text and "NVDA" not in text
    ob.close()


def test_empty_eligible_digest_sends_nothing(ledger_path):
    """If every card in a claimed digest batch falls out of eligibility
    before the final send decision, NOTHING is sent -- no transport call at
    all, not an empty/degenerate message."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
    did, eid = _enq_digest(ob, symbol="TSLA", accession="0001104659-26-000031",
                           enqueued_at=now - timedelta(minutes=30))

    def _lookup(event_id):
        return now - timedelta(minutes=30)

    clock = _StepClock([now, now + timedelta(hours=25)])
    snd = RecordingSender()
    _digest(ob, snd, interval_seconds=6 * 3600.0, now=now,
           event_time_lookup=_lookup, clock=clock)

    assert snd.sent == []                        # no transport call whatsoever
    assert ob.get(did).state == STATE_EXPIRED
    ob.close()


# ---------------------------------------------------------------------
# 3) already-queued rows, starvation, cross-cutting
# ---------------------------------------------------------------------

def test_already_queued_backlog_rows_get_the_same_protection(ledger_path):
    """A row that was ALREADY sitting in the outbox (a pre-existing backlog
    entry, enqueued long before this fix ran) receives exactly the same
    unknown-source-time protection as a brand-new one -- no grandfathering
    of old queue contents."""
    ob = DeliveryOutbox(ledger_path)
    backlog_enqueued = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
    did, eid, _ = _enq(ob, symbol="OLD", accession="0000000009-26-000009",
                       enqueued_at=backlog_enqueued)
    ob.close()

    # "restart": a fresh outbox handle over the SAME on-disk backlog, days
    # later, running the fixed code for the first time against it.
    ob2 = DeliveryOutbox(ledger_path)
    now = backlog_enqueued + timedelta(days=13)

    def _lookup(event_id):
        return None                              # still no evidence found

    snd = RecordingSender()
    _drain(ob2, snd, now=now, event_time_lookup=_lookup, route="IMMEDIATE")
    row = ob2.get(did)
    assert row.state == STATE_SUPPRESSED
    assert "unqualified" in (row.suppress_reason or "")
    assert snd.sent == []
    ob2.close()


def test_unqualified_rows_do_not_starve_eligible_rows(ledger_path):
    """An unqualified row sitting ahead of (or alongside) an eligible one in
    the same bounded batch does not block the eligible row from being
    delivered."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
    unk_did, unk_eid, _ = _enq(ob, symbol="UNK", accession="0000000010-26-000010",
                               enqueued_at=now - timedelta(minutes=5))
    ok_did, ok_eid, _ = _enq(ob, symbol="OKX", accession="0000000011-26-000011",
                             enqueued_at=now - timedelta(minutes=4))

    def _lookup(event_id):
        if event_id == ok_eid:
            return now - timedelta(minutes=4)
        return None                                # unk has no evidence

    snd = RecordingSender()
    _drain(ob, snd, now=now, event_time_lookup=_lookup, route="IMMEDIATE")
    assert ob.get(unk_did).state == STATE_SUPPRESSED
    assert ob.get(ok_did).state == STATE_SENT
    assert ok_did in [r.delivery_id for r in snd.sent]
    ob.close()


def test_v2_actionable_delivery_module_is_structurally_independent():
    """Task 136B touches only talonx_ingest.intelligence.delivery.{outbox,
    pipeline} and talonx_ingest.intelligence.service.runner -- V2's own
    actionable entry/exit delivery path (talonx_v2/) does not import from,
    or otherwise reference, any of those modules, so this freshness fix
    structurally cannot affect it. (Existing V2 replay/live-companion
    behaviour is additionally re-confirmed by the pre-existing task110-119
    V2 test suites, run separately -- not duplicated here.)"""
    from pathlib import Path

    v2_root = Path(__file__).resolve().parents[1] / "talonx_v2"
    assert v2_root.is_dir()
    # full, unambiguous module paths -- NOT "delivery import" alone, which
    # would false-positive on V2's own, unrelated talonx_v2.delivery module.
    touched_substrings = (
        "talonx_ingest.intelligence.delivery",
        "talonx_ingest.intelligence.service.runner",
    )
    offenders = []
    for py in v2_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for sub in touched_substrings:
            if sub in text:
                offenders.append((str(py), sub))
    assert offenders == [], offenders


# ---------------------------------------------------------------------
# Task 136 EOD follow-up, verification point B: a lookup that keeps
# failing for ONE row must not starve an eligible row sitting alongside
# it -- neither within a single bounded drain cycle nor across repeated
# cycles.
# ---------------------------------------------------------------------

def test_repeated_lookup_failure_does_not_starve_an_eligible_row_same_cycle(ledger_path):
    """A permanently-flaky lookup for row A (always raises -> DEFER every
    time) sits AHEAD of eligible row B in band/enqueue order. Row B must
    still be sent in the SAME drain cycle -- the per-row loop `continue`s
    past a DEFER'd row rather than stopping the batch."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    did_a, eid_a, _ = _enq(ob, symbol="AAA", accession="0000000020-26-000020",
                           enqueued_at=now - timedelta(minutes=10))
    did_b, eid_b, _ = _enq(ob, symbol="BBB", accession="0000000021-26-000021",
                           enqueued_at=now - timedelta(minutes=9))

    def _lookup(event_id):
        if event_id == eid_a:
            raise RuntimeError("permanently flaky lookup for A")
        return now - timedelta(minutes=9)          # B: valid, fresh

    snd = RecordingSender()
    res = _drain(ob, snd, now=now, event_time_lookup=_lookup, route="IMMEDIATE")

    assert ob.get(did_a).state == STATE_PENDING     # untouched, not starved-out either way
    assert ob.get(did_b).state == STATE_SENT
    assert did_b in [r.delivery_id for r in snd.sent]
    ob.close()


def test_repeated_lookup_failure_does_not_starve_eligible_rows_across_cycles(ledger_path):
    """The SAME permanently-flaky row is re-drained across several
    consecutive cycles (simulating repeated poll-loop iterations). Each
    cycle it DEFERs again (never blocks), and a batch of otherwise-
    eligible rows enqueued around it are delivered normally across those
    cycles -- the flaky row consumes at most its own slot each time, never
    exhausting the bounded per-cycle budget for everyone else."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    did_flaky, eid_flaky, _ = _enq(ob, symbol="FLK", accession="0000000030-26-000030",
                                   enqueued_at=now - timedelta(minutes=30))
    good_ids = []
    good_eids = {}
    for i in range(5):
        did, eid, _ = _enq(ob, symbol=f"GD{i}", accession=f"000000003{i+1}-26-00003{i+1}",
                           enqueued_at=now - timedelta(minutes=20 - i))
        good_ids.append(did)
        good_eids[eid] = now - timedelta(minutes=20 - i)

    calls = {"n": 0}

    def _lookup(event_id):
        if event_id == eid_flaky:
            calls["n"] += 1
            raise RuntimeError("permanently flaky lookup")
        return good_eids.get(event_id)

    snd = RecordingSender()
    for cycle in range(3):
        _drain(ob, snd, now=now + timedelta(seconds=cycle), event_time_lookup=_lookup,
              route="IMMEDIATE")

    assert ob.get(did_flaky).state == STATE_PENDING       # still recoverable, never stuck terminal
    assert calls["n"] >= 3                                 # re-attempted every cycle, not given up on
    assert all(ob.get(d).state == STATE_SENT for d in good_ids)
    assert set(good_ids) == {r.delivery_id for r in snd.sent}
    ob.close()
