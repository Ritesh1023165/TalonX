"""
Task 131 -- Concurrent Admission Fix and SPA Dashboard Acceptance,
section 1/2: a GENUINE competing-writer proof for the database-boundary
concurrency fix in ``V2Store.transaction()`` (an explicit ``BEGIN
IMMEDIATE`` acquired the instant the OUTERMOST transaction opens, before
its own first read -- see the docstring on ``V2Store.transaction()`` in
``talonx_v2/store.py`` for the full root-cause explanation).

Every test here uses TWO INDEPENDENT ``V2Service``/``V2Store`` instances
(two genuinely separate ``sqlite3`` connections) against ONE shared,
on-disk, temporary database file -- not two calls on the same store
instance, and not a simulated single-threaded "crash." Coordination
between the two writer threads is via ``threading.Event`` (deterministic
signalling), not arbitrary sleeps: writer A signals when it genuinely
holds the real SQLite write lock, and the test confirms writer B is
still blocked (via a short, bounded ``Thread.join`` liveness check, not
a hopeful fixed sleep) before releasing A -- the actual correctness
property under test (serialization, exactly-one-admission) is enforced
by SQLite's own real file-level lock, not by the timing of the test
harness.

NOTE on ``tests/test_task131_targeted_remediation.py``'s own
``test_admission_sequence_is_atomic_under_simulated_contention``: that
test (from the prior Targeted Remediation pass) opens a SECOND
connection mid-sequence to prove the reservation is invisible until
commit, and that a crash rolls the whole sequence back -- real and
still valid, but it is a READER-isolation and rollback proof, on a
SINGLE simulated writer. It does NOT exercise two REAL, independent
writers racing for the SAME capacity slot -- that is what this file
adds.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timezone

import pytest

from talonx_v2.cluster_engine import ClusterEpisode
from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Action, V2Decision, V2Direction
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

ACT = date(2026, 8, 14)
FUTURE_ENTRY = date(2027, 6, 3)   # within the XNYS calendar's generated range, far past real "now"
EARLY_DISSEMINATION = datetime(2026, 8, 14, 15, 20, tzinfo=timezone.utc)
BALANCE = 300_000.0
ALLOC = 10_000.0


def _bars(tmp, symbols):
    import csv
    from talonx_v2 import calendar as vc
    bd = tmp / "bars"
    bd.mkdir(exist_ok=True)
    sess = [s for s in vc._sessions() if date(2019, 1, 1) <= s <= date(2027, 12, 31)]
    for sym in symbols:
        with open(bd / f"{sym}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "close", "volume"])
            for s in sess:
                w.writerow([s.isoformat(), 40.0, 40.5, 1_500_000])
    return bd


def _svc(tmp, db_path, *, name, symbols, starting_cash=BALANCE,
        alloc=ALLOC, busy_timeout_ms: int | None = None):
    # max_concurrent_positions is part of the FROZEN strategy contract
    # (V2Config.validate_frozen() asserts it == 20) -- it is never
    # configured per-test. To get down to "one remaining slot" a test
    # instead pre-seeds 19 PENDING intents (see _seed_pending_intents)
    # before the two writers race for the last one.
    cfg = V2Config(db_path=str(db_path), starting_cash_usd=starting_cash,
                   per_position_allocation_usd=alloc)
    svc = V2Service(config=cfg, bar_dirs=[_bars(tmp, symbols)], form4_kind="parquet",
                    status_path=str(tmp / f"{name}.json"))
    if busy_timeout_ms is not None:
        # a SEPARATE store instance, pointed at the SAME on-disk file, with
        # its own (shorter) busy_timeout -- used only to exercise the
        # bounded-lock-failure path quickly and deterministically.
        svc.store = V2Store(str(db_path), starting_cash=starting_cash, busy_timeout_ms=busy_timeout_ms)
    return svc


def _ep(entry_session, episode_id, symbol):
    return ClusterEpisode(episode_id=episode_id, symbol=symbol, issuer_cik="x",
                          distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
                          first_filing_date=ACT, activation_filing_date=ACT, last_filing_date=ACT,
                          aggregate_purchase_value=0.0, any_officer=False, any_director=False,
                          any_ten_percent=False,
                          causal_event_ts=datetime(2026, 8, 14, 23, 59, 59, tzinfo=timezone.utc),
                          eligible_entry_session=entry_session)


def _fixed_buy_decision(e):
    liq = type("Liq", (), {"ok": True, "median_dollar_volume": 1e7, "last_close": 10.0})()
    dec = V2Decision(signal_id="s1", episode_id=e.episode_id, symbol=e.symbol,
                     direction=V2Direction.BULLISH, action=V2Action.BUY,
                     official_eligible=False, rationale="test (concurrent admission fixture)",
                     eligible_entry_session=e.eligible_entry_session)
    return liq, dec


def _seed_pending_intents(store: V2Store, n: int, *, prefix: str,
                          entry_session=FUTURE_ENTRY) -> None:
    """Directly write ``n`` PENDING entry intents (bypassing the full
    episode/decision pipeline -- this is pure store-level setup, done
    BEFORE the concurrent part of a test begins) so that, against the
    FROZEN max_concurrent_positions=20, exactly ``20 - n`` real slots
    remain for the two racing writers to compete over."""
    liq = type("Liq", (), {"ok": True, "median_dollar_volume": 1e7, "last_close": 10.0})()
    for i in range(n):
        ep = _ep(entry_session, f"{prefix}-seed-{i}", f"{prefix}SEED{i}")
        dec = V2Decision(signal_id=f"seed{i}", episode_id=ep.episode_id, symbol=ep.symbol,
                         direction=V2Direction.BULLISH, action=V2Action.BUY,
                         official_eligible=False, rationale="capacity-seed fixture",
                         eligible_entry_session=entry_session)
        store.upsert_entry_intent(ep, dec, liq, horizon=10,
                                  planned_exit_session=entry_session.isoformat())


def _wire(svc, symbol):
    svc._dissemination_lookup = {(symbol, ACT.isoformat()): EARLY_DISSEMINATION}
    svc._eval_causal_decision = _fixed_buy_decision


def _run_admission(svc, ep):
    svc._phase_post_close([ep], [ep], today=FUTURE_ENTRY, ripe_through=FUTURE_ENTRY,
                          is_stale=lambda e: False, live=True)


# --------------------------------------------------------------------- #
# Core requirement: one remaining slot, two competing writers
# --------------------------------------------------------------------- #
def test_two_concurrent_writers_one_slot_exactly_one_admitted(tmp_path, monkeypatch):
    """Two INDEPENDENT V2Service/V2Store instances (two real sqlite3
    connections), one shared on-disk db, exactly ONE remaining capacity
    slot, two DIFFERENT eligible episodes. Writer A is made to hold the
    real SQLite write reservation (already acquired via BEGIN IMMEDIATE
    the instant its transaction opened) while writer B attempts its own
    admission. B's own BEGIN IMMEDIATE blocks on the real lock until A
    commits -- so B's capacity read, once it finally runs, sees A's
    already-committed reservation and correctly rejects."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc_a = _svc(tmp_path, db_path, name="a", symbols=["RACA", "RACB"])
    svc_b = _svc(tmp_path, db_path, name="b", symbols=["RACA", "RACB"])
    # max_concurrent_positions is FROZEN at 20 -- pre-seed 19 PENDING
    # intents so exactly ONE real slot remains for the two writers below
    # to race over.
    _seed_pending_intents(svc_a.store, 19, prefix="RAC")
    ep_a = _ep(FUTURE_ENTRY, "race-a", "RACA")
    ep_b = _ep(FUTURE_ENTRY, "race-b", "RACB")
    _wire(svc_a, "RACA")
    _wire(svc_b, "RACB")

    a_holds_lock = threading.Event()
    release_a = threading.Event()
    real_enqueue_alert = svc_a.store.enqueue_alert

    def _a_paused_enqueue_alert(*a, **k):
        # by the time this runs, A's outer transaction() has already
        # executed BEGIN IMMEDIATE and A's own capacity check + intent
        # INSERT -- A genuinely holds the real SQLite write reservation
        # right now.
        a_holds_lock.set()
        assert release_a.wait(timeout=10), "test harness never released writer A"
        return real_enqueue_alert(*a, **k)
    monkeypatch.setattr(svc_a.store, "enqueue_alert", _a_paused_enqueue_alert)

    b_result: dict = {}

    def _run_b():
        _run_admission(svc_b, ep_b)
        b_result["capacity_rejected"] = svc_b._capacity_rejected
        b_result["intents_created"] = svc_b._intents_created

    a_thread = threading.Thread(target=lambda: _run_admission(svc_a, ep_a))
    a_thread.start()
    assert a_holds_lock.wait(timeout=5), "writer A never reached its held-lock checkpoint"

    b_thread = threading.Thread(target=_run_b)
    b_thread.start()
    # B's own BEGIN IMMEDIATE is now attempting against a lock A is
    # CONFIRMED to genuinely hold (event above) -- a short, bounded
    # liveness check (not an arbitrary sleep-and-hope) that B has not
    # returned yet is evidence it is blocked on that real lock, not that
    # it raced past A.
    b_thread.join(timeout=0.5)
    assert b_thread.is_alive(), "writer B did not block on the real SQLite write lock"

    release_a.set()
    a_thread.join(timeout=10)
    b_thread.join(timeout=10)
    assert not a_thread.is_alive() and not b_thread.is_alive()

    fresh = V2Store(str(db_path), starting_cash=BALANCE)
    intent_a = fresh.entry_intent("race-a")
    intent_b = fresh.entry_intent("race-b")
    admitted = [i for i in (intent_a, intent_b) if i is not None and i["status"] == "PENDING"]
    assert len(admitted) == 1, "exactly one of the two competing episodes must be admitted"
    # A held the lock FIRST (confirmed via the event above) -- it must
    # have committed first and won the single slot.
    assert intent_a is not None and intent_a["status"] == "PENDING"
    assert intent_b is None
    assert b_result["capacity_rejected"] == 1
    assert b_result["intents_created"] == 0
    assert fresh.episode_disposition("race-b") == "REJECTED_CAPACITY_EXCEEDED"
    outbox = fresh.all_outbox()
    assert len(outbox) == 1 and outbox[0]["episode_id"] == "race-a"
    # no over-reservation, no economic mutation from a PENDING intent --
    # it reserves capacity/cash logically, never touches the raw ledger.
    assert fresh.n_open() == 0
    assert fresh.cash() == BALANCE
    assert fresh.trades() == []


# --------------------------------------------------------------------- #
# Cash-limited admission with sufficient SLOTS
# --------------------------------------------------------------------- #
def test_two_concurrent_writers_cash_limited_with_sufficient_slots(tmp_path, monkeypatch):
    """20 real slots are available (the frozen max_concurrent_positions,
    unmodified -- 0 seeded here) but starting cash only covers ONE
    $10,000 reservation with $5,000 left over -- not enough for a
    second. The SAME real-lock serialization must correctly enforce the
    CASH boundary too, not just the slot-count boundary."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    cash = 15_000.0
    svc_a = _svc(tmp_path, db_path, name="a", symbols=["CASA", "CASB"],
                starting_cash=cash, alloc=10_000.0)
    svc_b = _svc(tmp_path, db_path, name="b", symbols=["CASA", "CASB"],
                starting_cash=cash, alloc=10_000.0)
    ep_a = _ep(FUTURE_ENTRY, "cash-a", "CASA")
    ep_b = _ep(FUTURE_ENTRY, "cash-b", "CASB")
    _wire(svc_a, "CASA")
    _wire(svc_b, "CASB")

    a_holds_lock = threading.Event()
    release_a = threading.Event()
    real_enqueue_alert = svc_a.store.enqueue_alert

    def _a_paused_enqueue_alert(*a, **k):
        a_holds_lock.set()
        assert release_a.wait(timeout=10)
        return real_enqueue_alert(*a, **k)
    monkeypatch.setattr(svc_a.store, "enqueue_alert", _a_paused_enqueue_alert)

    b_result: dict = {}

    def _run_b():
        _run_admission(svc_b, ep_b)
        b_result["capacity_rejected"] = svc_b._capacity_rejected

    a_thread = threading.Thread(target=lambda: _run_admission(svc_a, ep_a))
    a_thread.start()
    assert a_holds_lock.wait(timeout=5)
    b_thread = threading.Thread(target=_run_b)
    b_thread.start()
    b_thread.join(timeout=0.5)
    assert b_thread.is_alive()
    release_a.set()
    a_thread.join(timeout=10)
    b_thread.join(timeout=10)

    fresh = V2Store(str(db_path), starting_cash=cash)
    assert fresh.entry_intent("cash-a")["status"] == "PENDING"
    assert fresh.entry_intent("cash-b") is None
    assert b_result["capacity_rejected"] == 1
    detail = fresh.episode_disposition("cash-b")
    assert detail == "REJECTED_CAPACITY_EXCEEDED"
    assert fresh.cash() == cash   # a PENDING intent never mutates raw cash


# --------------------------------------------------------------------- #
# A competing writer succeeds after the first writer rolls back
# --------------------------------------------------------------------- #
def test_competing_writer_succeeds_after_first_writer_rolls_back(tmp_path, monkeypatch):
    """Writer A holds the real lock, inserts its own reservation, then
    CRASHES before its notification completes -- the whole sequence
    rolls back and the lock is released. Writer B, which was genuinely
    blocked waiting on that same lock, then acquires it, re-reads
    capacity fresh (A's failed attempt left nothing behind), and
    successfully admits its OWN episode."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc_a = _svc(tmp_path, db_path, name="a", symbols=["ROLA", "ROLB"])
    svc_b = _svc(tmp_path, db_path, name="b", symbols=["ROLA", "ROLB"])
    # again, exactly ONE real slot left -- so B's eventual success is
    # genuinely contingent on A's rollback actually freeing it, not on
    # spare capacity existing regardless.
    _seed_pending_intents(svc_a.store, 19, prefix="ROL")
    ep_a = _ep(FUTURE_ENTRY, "roll-a", "ROLA")
    ep_b = _ep(FUTURE_ENTRY, "roll-b", "ROLB")
    _wire(svc_a, "ROLA")
    _wire(svc_b, "ROLB")

    a_holds_lock = threading.Event()
    release_a = threading.Event()

    def _a_paused_then_crashes(*a, **k):
        a_holds_lock.set()
        assert release_a.wait(timeout=10)
        raise RuntimeError("simulated crash in writer A, after its own intent INSERT")
    monkeypatch.setattr(svc_a.store, "enqueue_alert", _a_paused_then_crashes)

    a_exc: dict = {}

    def _run_a():
        try:
            _run_admission(svc_a, ep_a)
        except RuntimeError as exc:
            a_exc["error"] = exc

    b_result: dict = {}

    def _run_b():
        _run_admission(svc_b, ep_b)
        b_result["intents_created"] = svc_b._intents_created

    a_thread = threading.Thread(target=_run_a)
    a_thread.start()
    assert a_holds_lock.wait(timeout=5)
    b_thread = threading.Thread(target=_run_b)
    b_thread.start()
    b_thread.join(timeout=0.5)
    assert b_thread.is_alive(), "writer B should still be blocked on A's (about to be rolled back) lock"

    release_a.set()
    a_thread.join(timeout=10)
    b_thread.join(timeout=10)
    assert not a_thread.is_alive() and not b_thread.is_alive()
    assert "error" in a_exc, "writer A's simulated crash did not propagate"

    fresh = V2Store(str(db_path), starting_cash=BALANCE)
    assert fresh.entry_intent("roll-a") is None       # A's own attempt fully rolled back
    assert fresh.episode_disposition("roll-a") is None
    intent_b = fresh.entry_intent("roll-b")
    assert intent_b is not None and intent_b["status"] == "PENDING"   # B succeeded, using the freed slot
    assert b_result["intents_created"] == 1
    outbox = fresh.all_outbox()
    assert len(outbox) == 1 and outbox[0]["episode_id"] == "roll-b"


# --------------------------------------------------------------------- #
# Bounded lock failure leaves no partial state
# --------------------------------------------------------------------- #
def test_bounded_lock_failure_leaves_no_partial_state(tmp_path, monkeypatch):
    """Writer A holds the lock indefinitely (never released within the
    test). Writer B uses a deliberately SHORT busy_timeout (a few hundred
    ms, not production's 30s) so the test proves the BOUNDED-wait
    contract quickly: B's transaction() call itself raises
    sqlite3.OperationalError, and nothing from B's attempted admission
    (no intent, no alert, no disposition) was ever written."""
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    db_path = tmp_path / "v2.db"
    svc_a = _svc(tmp_path, db_path, name="a", symbols=["LKA", "LKB"])
    svc_b = _svc(tmp_path, db_path, name="b", symbols=["LKA", "LKB"], busy_timeout_ms=300)
    ep_a = _ep(FUTURE_ENTRY, "lock-a", "LKA")
    ep_b = _ep(FUTURE_ENTRY, "lock-b", "LKB")
    _wire(svc_a, "LKA")
    _wire(svc_b, "LKB")

    a_holds_lock = threading.Event()
    release_a = threading.Event()
    real_enqueue_alert = svc_a.store.enqueue_alert

    def _a_paused_enqueue_alert(*a, **k):
        a_holds_lock.set()
        assert release_a.wait(timeout=10)
        return real_enqueue_alert(*a, **k)
    monkeypatch.setattr(svc_a.store, "enqueue_alert", _a_paused_enqueue_alert)

    b_exc: dict = {}

    def _run_b():
        try:
            _run_admission(svc_b, ep_b)
        except sqlite3.OperationalError as exc:
            b_exc["error"] = exc

    a_thread = threading.Thread(target=lambda: _run_admission(svc_a, ep_a))
    a_thread.start()
    assert a_holds_lock.wait(timeout=5)

    b_thread = threading.Thread(target=_run_b)
    b_thread.start()
    # B's short busy_timeout (300ms) must elapse and raise WELL before we
    # release A -- bound the join comfortably above that.
    b_thread.join(timeout=5)
    assert not b_thread.is_alive(), "writer B did not raise within its own bounded busy_timeout"
    assert "error" in b_exc, "writer B's bounded lock wait did not raise sqlite3.OperationalError"

    release_a.set()
    a_thread.join(timeout=10)
    assert not a_thread.is_alive()

    fresh = V2Store(str(db_path), starting_cash=BALANCE)
    assert fresh.entry_intent("lock-a") is not None   # A, unblocked, still succeeded
    assert fresh.entry_intent("lock-b") is None        # B never wrote anything at all
    assert fresh.episode_disposition("lock-b") is None
    outbox_b = [r for r in fresh.all_outbox() if r["episode_id"] == "lock-b"]
    assert outbox_b == []
