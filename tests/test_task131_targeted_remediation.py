"""
Task 131 Targeted Remediation (on top of Final Remediation, commit
9a81e5c) -- three further production-boundary fixes, all confined to
``talonx_v2/service.py``:

  1. Strict intent deadline validation: ``_verify_temporal_boundary()``
     no longer returns ``True`` early for an unknown dissemination
     timestamp on a LIVE tick (previously only strict-failed when a real
     InsiderStore query happened to run this tick), and a missing or
     malformed intent ``created_at_utc`` is now itself a strict failure
     -- never silently treated as "assume it was early enough."
  2. Pre-admission deadline check: the SAME temporal check now also runs
     in ``_phase_post_close()``, BEFORE a reservation or its actionable
     alert is ever created -- called with ``intent=None`` so "the moment
     right now" stands in for a fresh intent's own future creation time.
  3. Atomic admission lifecycle: the capacity check
     (``_capacity_rejection_reason()``), intent creation
     (``upsert_entry_intent()``), and notification generation in
     ``_phase_post_close()`` now commit, or roll back, as ONE atomic
     ``V2Store.transaction()``.

All LIVE-tick behavior is exercised via direct unit-level calls
(``_verify_temporal_boundary(..., live=True)`` / ``_phase_post_close(...,
live=True)``) rather than a true ``tick(as_of=None)`` -- this codebase's
own established pattern (see ``test_task131_temporal_boundary.py``) for
testing wall-clock-dependent logic deterministically, without depending
on a real live tick's non-deterministic ``datetime.now()``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from talonx_v2.cluster_engine import ClusterEpisode
from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Action, V2Decision, V2Direction
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

SYM = "TGTX"
ACT = date(2026, 8, 14)     # activation filing date
ENTRY = date(2026, 8, 17)   # eligible entry session -- long past relative to real "now"
EARLY_DISSEMINATION = datetime(2026, 8, 14, 15, 20, tzinfo=timezone.utc)


def _bars(tmp):
    import csv
    from talonx_v2 import calendar as vc
    bd = tmp / "bars"
    bd.mkdir()
    sess = [s for s in vc._sessions() if date(2019, 1, 1) <= s <= date(2031, 12, 31)]
    with open(bd / f"{SYM}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "close", "volume"])
        for s in sess:
            w.writerow([s.isoformat(), 40.0, 40.5, 1_500_000])
    return bd


def _svc(tmp):
    cfg = V2Config(db_path=str(tmp / "v2.db"), starting_cash_usd=300_000.0,
                   per_position_allocation_usd=10_000.0)
    return V2Service(config=cfg, bar_dirs=[_bars(tmp)], form4_kind="parquet",
                     status_path=str(tmp / "s.json"))


def _ep(entry_session=ENTRY, episode_id="e1", symbol=SYM):
    return ClusterEpisode(episode_id=episode_id, symbol=symbol, issuer_cik="x",
                          distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
                          first_filing_date=ACT, activation_filing_date=ACT, last_filing_date=ACT,
                          aggregate_purchase_value=0.0, any_officer=False, any_director=False,
                          any_ten_percent=False,
                          causal_event_ts=datetime(2026, 8, 14, 23, 59, 59, tzinfo=timezone.utc),
                          eligible_entry_session=entry_session)


def _rth_open(session: date) -> datetime:
    import exchange_calendars as xc
    return xc.get_calendar("XNYS").session_open(session.isoformat()).to_pydatetime().astimezone(timezone.utc)


def _fixed_buy_decision(e):
    liq = type("Liq", (), {"ok": True, "median_dollar_volume": 1e7, "last_close": 10.0})()
    dec = V2Decision(signal_id="s1", episode_id=e.episode_id, symbol=e.symbol,
                     direction=V2Direction.BULLISH, action=V2Action.BUY,
                     official_eligible=False, rationale="test (targeted remediation fixture)",
                     eligible_entry_session=e.eligible_entry_session)
    return liq, dec


# --------------------------------------------------------------------- #
# Directive 1 -- strict intent deadline validation
# --------------------------------------------------------------------- #
def test_live_unknown_dissemination_is_strict_failure_even_without_a_query_this_tick(tmp_path):
    # form4_kind="parquet" never sets _dissemination_lookup_refreshed_this_tick
    # -- previously this silently PASSED on every tick, live or not. A true
    # LIVE tick must now strict-fail: an unobserved timestamp is never
    # "safely early," regardless of whether a real query ran this tick.
    svc = _svc(tmp_path)
    ep = _ep()
    ok, detail = svc._verify_temporal_boundary(ep, None, live=True)
    assert ok is False
    assert "no real dissemination timestamp" in detail


def test_non_live_unknown_dissemination_still_skips_gracefully(tmp_path):
    # regression: a pinned replay/test tick (live=False) keeps the
    # documented, non-fabricating SKIP -- unaffected by this remediation.
    svc = _svc(tmp_path)
    ep = _ep()
    ok, detail = svc._verify_temporal_boundary(ep, None, live=False)
    assert ok is True and detail == ""


def test_live_intent_missing_created_at_utc_is_strict_failure(tmp_path):
    svc = _svc(tmp_path)
    ep = _ep()
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    intent = {"intent_id": "i1", "created_at_utc": None}
    ok, detail = svc._verify_temporal_boundary(ep, intent, live=True)
    assert ok is False
    assert "no valid, parsable created_at_utc" in detail


def test_live_intent_malformed_created_at_utc_is_strict_failure(tmp_path):
    svc = _svc(tmp_path)
    ep = _ep()
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    intent = {"intent_id": "i1", "created_at_utc": "not-a-real-timestamp"}
    ok, detail = svc._verify_temporal_boundary(ep, intent, live=True)
    assert ok is False
    assert "no valid, parsable created_at_utc" in detail


def test_live_intent_valid_created_at_utc_before_rth_open_still_passes(tmp_path):
    # regression: the legitimate, well-formed case introduced by the prior
    # (Final) remediation pass keeps working unchanged.
    svc = _svc(tmp_path)
    ep = _ep()
    rth_open = _rth_open(ENTRY)
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    intent = {"intent_id": "i1", "created_at_utc": (rth_open - timedelta(minutes=5)).isoformat()}
    ok, detail = svc._verify_temporal_boundary(ep, intent, live=True)
    assert ok is True and detail == ""


def test_non_live_missing_intent_timing_is_never_checked(tmp_path):
    # regression: a pinned replay/test tick never compares wall clocks at
    # all (an intent row's REAL created_at_utc bears no relationship to a
    # simulated as_of) -- missing/malformed timing is simply not evaluated.
    svc = _svc(tmp_path)
    ep = _ep()
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    intent = {"intent_id": "i1", "created_at_utc": None}
    ok, detail = svc._verify_temporal_boundary(ep, intent, live=False)
    assert ok is True and detail == ""


# --------------------------------------------------------------------- #
# Directive 2 -- pre-admission deadline check
# --------------------------------------------------------------------- #
def test_live_admission_deadline_already_passed_refuses_with_no_intent_yet(tmp_path):
    # intent=None -- exactly how _phase_post_close calls this BEFORE a
    # reservation exists -- "right now" stands in for the intent's own
    # future creation time. ENTRY (2026-08-17) is long past real "now."
    svc = _svc(tmp_path)
    ep = _ep(entry_session=ENTRY)
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    ok, detail = svc._verify_temporal_boundary(ep, None, live=True)
    assert ok is False
    assert "admission is being evaluated at" in detail


def test_live_admission_before_deadline_passes_with_no_intent_yet(tmp_path):
    svc = _svc(tmp_path)
    future_entry = date(2027, 6, 3)
    ep = _ep(entry_session=future_entry)
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    ok, detail = svc._verify_temporal_boundary(ep, None, live=True)
    assert ok is True and detail == ""


def test_admission_refuses_a_buy_intent_when_target_session_rth_open_already_passed(tmp_path):
    """End-to-end wiring proof (not just the raw unit check above): a real
    call into _phase_post_close(), with a BUY decision forced, creates NO
    intent and NO alert for a session whose admission window has closed."""
    svc = _svc(tmp_path)
    ep = _ep(entry_session=ENTRY)
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    svc._eval_causal_decision = _fixed_buy_decision

    svc._phase_post_close([ep], [ep], today=ENTRY, ripe_through=ENTRY,
                          is_stale=lambda e: False, live=True)

    assert svc.store.entry_intent(ep.episode_id) is None
    assert svc.store.episode_disposition(ep.episode_id) == "SKIPPED_ADMISSION_DEADLINE_PASSED"
    assert svc.store.all_outbox() == []
    assert svc._admission_deadline_rejected == 1
    assert svc._intents_created == 0


def test_admission_creates_a_buy_intent_when_target_session_rth_open_has_not_passed_yet(tmp_path):
    """Positive counterpart: a future session's admission window is still
    open -- the fix must not block legitimate admissions."""
    svc = _svc(tmp_path)
    future_entry = date(2027, 6, 3)
    ep = _ep(entry_session=future_entry, episode_id="e2")
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    svc._eval_causal_decision = _fixed_buy_decision

    svc._phase_post_close([ep], [ep], today=future_entry, ripe_through=future_entry,
                          is_stale=lambda e: False, live=True)

    intent = svc.store.entry_intent(ep.episode_id)
    assert intent is not None and intent["status"] == "PENDING"
    assert svc._intents_created == 1
    assert svc._admission_deadline_rejected == 0
    outbox = svc.store.all_outbox()
    assert len(outbox) == 1
    assert outbox[0]["kind"] == "ENTRY_INTENT"


def test_non_live_admission_never_applies_the_deadline_check(tmp_path):
    # regression: a pinned replay/backtest tick (live=False) must be able
    # to admit ANY historical eligible_entry_session -- that is the whole
    # point of replay. The wall-clock deadline check is live-only.
    svc = _svc(tmp_path)
    ep = _ep(entry_session=ENTRY, episode_id="e3")
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    svc._eval_causal_decision = _fixed_buy_decision

    svc._phase_post_close([ep], [ep], today=ENTRY, ripe_through=ENTRY,
                          is_stale=lambda e: False, live=False)

    intent = svc.store.entry_intent(ep.episode_id)
    assert intent is not None and intent["status"] == "PENDING"
    assert svc._admission_deadline_rejected == 0


# --------------------------------------------------------------------- #
# Directive 3 -- atomic admission lifecycle under contention
# --------------------------------------------------------------------- #
def test_admission_sequence_commits_intent_and_notification_together_on_success(tmp_path):
    svc = _svc(tmp_path)
    future_entry = date(2027, 6, 3)
    ep = _ep(entry_session=future_entry, episode_id="e4")
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    svc._eval_causal_decision = _fixed_buy_decision

    svc._phase_post_close([ep], [ep], today=future_entry, ripe_through=future_entry,
                          is_stale=lambda e: False, live=True)

    fresh = V2Store(str(tmp_path / "v2.db"), starting_cash=300_000.0)
    assert fresh.entry_intent(ep.episode_id)["status"] == "PENDING"
    assert len(fresh.all_outbox()) == 1


def test_admission_sequence_reader_sees_nothing_mid_transaction_then_full_rollback(tmp_path, monkeypatch):
    """Targeted Remediation Directive 3: capacity check + intent creation +
    notification commit, or roll back, as ONE atomic unit. Simulates a
    concurrent READER (a genuinely SEPARATE store connection, opened
    WHILE the admission transaction is still active and uncommitted)
    observing NOTHING mid-sequence -- real SQLite-level (WAL) read
    isolation, not merely an in-process illusion -- and then a crash
    during notification generation, proving the ENTIRE sequence rolls
    back together: never a dangling PENDING intent with no alert ever
    delivered.

    SCOPE NOTE (Concurrent Admission Fix follow-up): this proves READ
    visibility and rollback on a SINGLE (simulated) writer -- it does
    NOT exercise two independent, genuinely concurrent WRITERS racing
    for the SAME capacity slot, and it predates the ``BEGIN IMMEDIATE``
    fix in ``V2Store.transaction()`` (the TOCTOU race that fix closes
    can only manifest between two REAL writers, never between a writer
    and a WAL reader, which never blocks on the writer's lock at all).
    The genuine competing-writer proof -- two real ``V2Store``
    connections, two real threads, one contended capacity slot -- lives
    in ``tests/test_task131_concurrent_admission.py``."""
    svc = _svc(tmp_path)
    future_entry = date(2027, 6, 3)
    ep = _ep(entry_session=future_entry, episode_id="e5")
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    svc._eval_causal_decision = _fixed_buy_decision

    seen_mid_transaction = {}

    def _contended_enqueue_alert(*a, **k):
        contender = V2Store(str(tmp_path / "v2.db"), starting_cash=300_000.0)
        seen_mid_transaction["intent"] = contender.entry_intent(ep.episode_id)
        raise RuntimeError("simulated crash/contention during notification generation")
    monkeypatch.setattr(svc.store, "enqueue_alert", _contended_enqueue_alert)

    with pytest.raises(RuntimeError):
        svc._phase_post_close([ep], [ep], today=future_entry, ripe_through=future_entry,
                              is_stale=lambda e: False, live=True)

    # the contending reader saw NOTHING while the outer transaction was
    # still open -- the reservation was never visible mid-sequence.
    assert seen_mid_transaction["intent"] is None
    # -- and after the crash, NOTHING from this sequence survives either:
    # full rollback, not a dangling intent with no delivered alert.
    fresh = V2Store(str(tmp_path / "v2.db"), starting_cash=300_000.0)
    assert fresh.entry_intent(ep.episode_id) is None
    assert fresh.all_outbox() == []
    assert fresh.episode_disposition(ep.episode_id) is None


def test_admission_sequence_rolls_back_if_intent_creation_itself_fails(tmp_path, monkeypatch):
    """A crash EARLIER in the sequence (inside upsert_entry_intent itself,
    before any notification is even attempted) must equally leave nothing
    partial -- and must never leave a REJECTED_CAPACITY_EXCEEDED-style
    stray write from a half-completed attempt."""
    svc = _svc(tmp_path)
    future_entry = date(2027, 6, 3)
    ep = _ep(entry_session=future_entry, episode_id="e6")
    svc._dissemination_lookup = {(SYM, ACT.isoformat()): EARLY_DISSEMINATION}
    svc._eval_causal_decision = _fixed_buy_decision

    def _boom(*a, **k):
        raise RuntimeError("simulated crash inside intent creation")
    monkeypatch.setattr(svc.store, "upsert_entry_intent", _boom)

    with pytest.raises(RuntimeError):
        svc._phase_post_close([ep], [ep], today=future_entry, ripe_through=future_entry,
                              is_stale=lambda e: False, live=True)

    fresh = V2Store(str(tmp_path / "v2.db"), starting_cash=300_000.0)
    assert fresh.entry_intent(ep.episode_id) is None
    assert fresh.all_outbox() == []
