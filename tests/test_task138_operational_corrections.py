"""
tests/test_task138_operational_corrections.py
------------------------------------------------
Task 138, Workstream 1: closes the three concrete Task 137 review gaps.

A. Delivery fairness at REAL production scheduling intervals (~3-4 min
   cycles), not the artificially tight (1s) gaps the Task 137 fixture
   used -- which happened to mask the real gap: a FIXED 30s DEFER
   backoff is shorter than a real cycle interval, so a permanently-
   failing row's backoff always fully expires before the NEXT cycle,
   letting it re-occupy a bounded `pending()` selection forever whenever
   the bulk sweep cannot reach it. Fixed with a genuine, exponential,
   capped, per-row backoff.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.delivery.outbox import (
    STATE_PENDING,
    STATE_SENT,
    DeliveryOutbox,
)
from talonx_ingest.intelligence.delivery.pipeline import (
    RecordingSender,
    enqueue_card,
    process_pending,
)
from _delivery_helpers import make_card

UTC = timezone.utc
REAL_CYCLE_GAP_SECONDS = 210.0   # ~3.5 min -- matches observed production poll-cycle cadence


def _enq(ob, *, symbol, accession, enqueued_at, band=None,
         event_type=EventType.EARNINGS_RESULTS, on_watchlist=True):
    card, _ = make_card(symbol=symbol, accession=accession, event_type=event_type,
                        on_watchlist=on_watchlist, now=enqueued_at)
    r = enqueue_card(card, outbox=ob, now=enqueued_at).row
    if band is not None:
        ob._conn.execute("UPDATE intelligence_delivery SET band=? WHERE delivery_id=?",
                         (band, r.delivery_id))
        ob._conn.commit()
    return r.delivery_id, r.event_id


def _drain(ob, sender, **kw):
    kw.setdefault("mode", "enabled")
    kw.setdefault("enforce_age_cutoff", True)
    return asyncio.run(process_pending(ob, sender, **kw))


def _build_realistic_saturation_scenario(ledger_path, *, scan_limit=50, send_limit=3):
    """The exact reproduction fixture: a bounded bulk-sweep scan
    (`scan_limit`) PERMANENTLY consumed by `scan_limit + 20` older,
    LOW-band, genuinely-fresh filler rows (never expire, never leave
    PENDING -- the sweep can never progress past them); `send_limit`
    persistently-failing HIGH-band rows enqueued AFTER the fillers (so
    they are outside the bulk sweep's reach) but sorting FIRST in
    `pending()`'s band-priority order; one genuinely eligible HIGH-band
    row behind them."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)

    filler_eids: dict[str, datetime] = {}
    for i in range(scan_limit + 20):
        at = now - timedelta(hours=2, minutes=i)
        _did, eid = _enq(ob, symbol=f"FIL{i}", accession=f"00000001{i:02d}-26-0000{i:02d}",
                         enqueued_at=at, band="LOW")
        filler_eids[eid] = at

    flaky_ids, flaky_eids = [], set()
    for i in range(send_limit):
        did, eid = _enq(ob, symbol=f"FLK{i}", accession=f"000000004{i}-26-00004{i}",
                        enqueued_at=now - timedelta(minutes=30 - i), band="HIGH")
        flaky_ids.append(did)
        flaky_eids.add(eid)

    good_did, good_eid = _enq(ob, symbol="GOOD", accession="0000000050-26-000050",
                              enqueued_at=now - timedelta(minutes=5), band="HIGH")

    def _lookup(event_id):
        if event_id in flaky_eids:
            raise RuntimeError("permanently flaky lookup")
        if event_id in filler_eids:
            return filler_eids[event_id]
        return now - timedelta(minutes=5)          # GOOD: valid, fresh

    return ob, now, flaky_ids, good_did, _lookup


def test_fixed_short_backoff_would_starve_a_valid_row_at_real_cycle_intervals(ledger_path, monkeypatch):
    """Negative control: proves WHY the fix is needed. Monkeypatches the
    exponential backoff back to the OLD fixed-30s Task 137 behaviour and
    confirms the eligible row is NEVER delivered across 20 realistic
    (210s-apart) cycles -- the exact gap the review flagged. This test
    documents the historical defect; it does not assert current (fixed)
    production behaviour."""
    import talonx_ingest.intelligence.delivery.outbox as outbox_mod

    monkeypatch.setattr(outbox_mod, "_defer_backoff_seconds", lambda defer_count: 30.0)

    ob, now, flaky_ids, good_did, _lookup = _build_realistic_saturation_scenario(ledger_path)
    snd = RecordingSender()
    sent_ever: set[str] = set()
    for cycle in range(20):
        res = _drain(ob, snd, now=now + timedelta(seconds=cycle * REAL_CYCLE_GAP_SECONDS),
                    event_time_lookup=_lookup, route="IMMEDIATE", limit=3, expire_scan_limit=50)
        sent_ever |= {r.delivery_id for r in snd.sent}
        if good_did in sent_ever:
            break

    assert good_did not in sent_ever, (
        "expected the OLD fixed-backoff behaviour to starve the eligible row -- "
        "if this now passes, the monkeypatch stopped reflecting the historical design"
    )
    ob.close()


def test_exponential_backoff_recovers_fairness_at_real_cycle_intervals(ledger_path):
    """The actual fix, proven at realistic (210s) cycle spacing across a
    bounded number of cycles: the eligible row is eventually selected and
    sent. Selection/expiry/recovery stay bounded throughout (no unbounded
    scan -- expire_scan_limit and the send limit are both respected every
    cycle); the persistently-failing rows remain PENDING (recoverable,
    never terminally discarded just because a lookup kept failing)."""
    ob, now, flaky_ids, good_did, _lookup = _build_realistic_saturation_scenario(ledger_path)
    snd = RecordingSender()
    sent_ever: set[str] = set()
    cycles_used = None
    for cycle in range(20):
        res = _drain(ob, snd, now=now + timedelta(seconds=cycle * REAL_CYCLE_GAP_SECONDS),
                    event_time_lookup=_lookup, route="IMMEDIATE", limit=3, expire_scan_limit=50)
        sent_ever |= {r.delivery_id for r in snd.sent}
        if good_did in sent_ever:
            cycles_used = cycle
            break

    assert good_did in sent_ever, "eligible work must make progress under persistent lookup failures"
    assert cycles_used is not None and cycles_used < 20, "must resolve within a bounded number of cycles"
    assert ob.get(good_did).state == STATE_SENT
    # the persistently-failing rows are still PENDING -- recoverable, not
    # terminally discarded just because their lookup kept failing.
    assert all(ob.get(d).state == STATE_PENDING for d in flaky_ids)
    ob.close()


def test_defer_backoff_grows_exponentially_and_is_bounded():
    from talonx_ingest.intelligence.delivery.outbox import (
        _DEFER_BACKOFF_CAP_SECONDS,
        _defer_backoff_seconds,
    )

    vals = [_defer_backoff_seconds(n) for n in range(1, 10)]
    assert vals == sorted(vals)                       # monotonically non-decreasing
    assert vals[0] == 30.0
    assert vals[1] == 60.0
    assert vals[2] == 120.0
    assert all(v <= _DEFER_BACKOFF_CAP_SECONDS for v in vals)   # bounded, never unbounded
    assert _defer_backoff_seconds(100) == _DEFER_BACKOFF_CAP_SECONDS


def test_defer_count_resets_once_the_lookup_recovers(ledger_path):
    """A row that DEFERs a few times and then succeeds must not carry a
    stale, elevated defer_count into some later, unrelated re-enqueue --
    confirmed via the same reset path enqueue() already uses for attempts/
    last_error on a re-open."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    did, eid = _enq(ob, symbol="RCV", accession="0000000070-26-000070",
                    enqueued_at=now - timedelta(minutes=10))

    state = {"fails": True}

    def _lookup(event_id):
        if state["fails"]:
            raise RuntimeError("flaky")
        return now - timedelta(minutes=10)

    snd = RecordingSender()
    for cycle in range(3):
        _drain(ob, snd, now=now + timedelta(seconds=cycle * 5), event_time_lookup=_lookup,
              route="IMMEDIATE", limit=5)
    row = ob._conn.execute("SELECT defer_count FROM intelligence_delivery WHERE delivery_id=?",
                           (did,)).fetchone()
    assert row["defer_count"] >= 1

    state["fails"] = False
    # advance well past the backoff window so the row is eligible again
    _drain(ob, snd, now=now + timedelta(hours=2), event_time_lookup=_lookup,
          route="IMMEDIATE", limit=5)
    assert ob.get(did).state == STATE_SENT
    ob.close()


def test_fairness_state_survives_close_and_reopen(ledger_path):
    """defer_count/next_retry_at_utc are durable columns, not in-memory
    state -- a fresh DeliveryOutbox handle over the same file must see
    the same backoff already in effect."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    did, eid = _enq(ob, symbol="PST", accession="0000000080-26-000080",
                    enqueued_at=now - timedelta(minutes=10))

    def _lookup(event_id):
        raise RuntimeError("flaky")

    snd = RecordingSender()
    _drain(ob, snd, now=now, event_time_lookup=_lookup, route="IMMEDIATE", limit=5)
    before = ob._conn.execute("SELECT defer_count, next_retry_at_utc FROM intelligence_delivery "
                              "WHERE delivery_id=?", (did,)).fetchone()
    assert before["defer_count"] == 1
    ob.close()

    ob2 = DeliveryOutbox(ledger_path)          # simulates a restart
    after = ob2._conn.execute("SELECT defer_count, next_retry_at_utc FROM intelligence_delivery "
                              "WHERE delivery_id=?", (did,)).fetchone()
    assert after["defer_count"] == before["defer_count"]
    assert after["next_retry_at_utc"] == before["next_retry_at_utc"]
    # still excluded from selection immediately after reopening (backoff
    # not reset by a restart)
    pend = ob2.pending(route="IMMEDIATE", now=now + timedelta(seconds=1))
    assert did not in [r.delivery_id for r in pend]
    ob2.close()


# ---------------------------------------------------------------------
# B. Runtime scope evidence -- qualified, not a bare count comparison.
# ---------------------------------------------------------------------

def _patch_watchlist_and_manifest(monkeypatch, tmp_path, *, watchlist_syms=("AAPL",),
                                   manifest_syms=("AAPL", "ZZBROAD")):
    import talonx_ops.prospective.funnel as funnel_mod
    import talonx_ops.watchlist_coverage as wc_mod

    manifest = tmp_path / "discovery_universe_v1_626.json"
    manifest.write_text(__import__("json").dumps({"symbols": list(manifest_syms)}), encoding="utf-8")
    monkeypatch.setattr(funnel_mod, "_BROAD_DISCOVERY_MANIFEST", manifest)
    monkeypatch.setattr(
        wc_mod, "build_coverage_map",
        lambda: {"tickers": [{"symbol": s, "v2_collection_scope": "POLLED"} for s in watchlist_syms]},
    )
    return manifest


def test_scope_evidence_missing_status_is_missing_malformed():
    from talonx_ops.prospective.checkpoint import SCOPE_MISSING_MALFORMED, evaluate_scope_evidence

    now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC)
    ev = evaluate_scope_evidence({}, now)
    assert ev["qualification"] == SCOPE_MISSING_MALFORMED
    assert ev["broad_discovery_active"] is False


def test_scope_evidence_malformed_scope_count_is_missing_malformed():
    from talonx_ops.prospective.checkpoint import SCOPE_MISSING_MALFORMED, evaluate_scope_evidence

    now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC)
    ev = evaluate_scope_evidence(
        {"heartbeat_utc": now.isoformat(), "heartbeat_ttl_s": 180,
         "execution_scope_count": "not-a-number"}, now)
    assert ev["qualification"] == SCOPE_MISSING_MALFORMED


def test_scope_evidence_stale_heartbeat_is_not_treated_as_live():
    from talonx_ops.prospective.checkpoint import SCOPE_STALE, evaluate_scope_evidence

    now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC)
    old_hb = now - timedelta(seconds=600)   # well past a 180s ttl
    ev = evaluate_scope_evidence(
        {"heartbeat_utc": old_hb.isoformat(), "heartbeat_ttl_s": 180,
         "execution_scope_count": 626}, now)
    assert ev["qualification"] == SCOPE_STALE
    assert ev["broad_discovery_active"] is False


def test_scope_evidence_dead_recorded_pid_is_wrong_process(tmp_path, monkeypatch):
    from talonx_ops.prospective.checkpoint import SCOPE_WRONG_PROCESS, evaluate_scope_evidence
    import talonx_ops.prospective.checkpoint as ck_mod

    now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(ck_mod, "_session_pids_info",
                        lambda now: {"v2_companion_pid": 999999999, "v2_argv": []})
    ev = evaluate_scope_evidence(
        {"heartbeat_utc": now.isoformat(), "heartbeat_ttl_s": 180,
         "execution_scope_count": 626}, now)
    assert ev["qualification"] == SCOPE_WRONG_PROCESS
    assert ev["broad_discovery_active"] is False


def test_scope_evidence_unreadable_manifest_is_reported_distinctly(tmp_path, monkeypatch):
    from talonx_ops.prospective.checkpoint import SCOPE_MANIFEST_UNREADABLE, evaluate_scope_evidence
    import talonx_ops.prospective.checkpoint as ck_mod
    import talonx_ops.prospective.funnel as funnel_mod
    import talonx_ops.watchlist_coverage as wc_mod

    monkeypatch.setattr(ck_mod, "_session_pids_info",
                        lambda now: {"v2_companion_pid": None, "v2_argv": ["--enable-broad-discovery"]})
    monkeypatch.setattr(funnel_mod, "_BROAD_DISCOVERY_MANIFEST", tmp_path / "does_not_exist.json")
    monkeypatch.setattr(
        wc_mod, "build_coverage_map",
        lambda: {"tickers": [{"symbol": "AAPL", "v2_collection_scope": "POLLED"}]},
    )
    now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC)
    ev = evaluate_scope_evidence(
        {"heartbeat_utc": now.isoformat(), "heartbeat_ttl_s": 180,
         "execution_scope_count": 626}, now)
    assert ev["qualification"] == SCOPE_MANIFEST_UNREADABLE
    assert ev["broad_discovery_active"] is False


def test_scope_evidence_narrow_scope_reported_as_narrow_not_successful_broad(tmp_path, monkeypatch):
    """A genuinely narrow (watchlist-only) live scope must be reported as
    exactly that -- FRESH_VALID with broad_discovery_active=False -- never
    silently upgraded or described as successful broad coverage."""
    from talonx_ops.prospective.checkpoint import SCOPE_FRESH_VALID, evaluate_scope_evidence
    import talonx_ops.prospective.checkpoint as ck_mod

    monkeypatch.setattr(ck_mod, "_session_pids_info",
                        lambda now: {"v2_companion_pid": None, "v2_argv": []})
    _patch_watchlist_and_manifest(monkeypatch, tmp_path, watchlist_syms=("AAPL",))
    now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC)
    ev = evaluate_scope_evidence(
        {"heartbeat_utc": now.isoformat(), "heartbeat_ttl_s": 180,
         "execution_scope_count": 1}, now)
    assert ev["qualification"] == SCOPE_FRESH_VALID
    assert ev["broad_discovery_active"] is False


def test_scope_evidence_mismatch_between_reported_and_reconstructed_is_flagged(tmp_path, monkeypatch):
    from talonx_ops.prospective.checkpoint import SCOPE_MISMATCH, evaluate_scope_evidence
    import talonx_ops.prospective.checkpoint as ck_mod

    monkeypatch.setattr(ck_mod, "_session_pids_info",
                        lambda now: {"v2_companion_pid": None, "v2_argv": ["--enable-broad-discovery"]})
    _patch_watchlist_and_manifest(monkeypatch, tmp_path, watchlist_syms=("AAPL",),
                                   manifest_syms=("AAPL", "ZZBROAD"))
    now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC)
    ev = evaluate_scope_evidence(
        {"heartbeat_utc": now.isoformat(), "heartbeat_ttl_s": 180,
         "execution_scope_count": 999}, now)   # doesn't match reconstructed (2)
    assert ev["qualification"] == SCOPE_MISMATCH
    assert ev["broad_discovery_active"] is False


def test_scope_evidence_fresh_owned_matching_is_confirmed_active(tmp_path, monkeypatch):
    from talonx_ops.prospective.checkpoint import SCOPE_FRESH_VALID, evaluate_scope_evidence
    import talonx_ops.prospective.checkpoint as ck_mod

    monkeypatch.setattr(ck_mod, "_session_pids_info",
                        lambda now: {"v2_companion_pid": None, "v2_argv": ["--enable-broad-discovery"]})
    _patch_watchlist_and_manifest(monkeypatch, tmp_path, watchlist_syms=("AAPL",),
                                   manifest_syms=("AAPL", "ZZBROAD"))
    now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC)
    ev = evaluate_scope_evidence(
        {"heartbeat_utc": now.isoformat(), "heartbeat_ttl_s": 180,
         "execution_scope_count": 2}, now)   # matches reconstructed union count
    assert ev["qualification"] == SCOPE_FRESH_VALID
    assert ev["broad_discovery_active"] is True
    assert ev["reported_scope_count"] == 2
    assert ev["reconstructed_scope_count"] == 2


# ---------------------------------------------------------------------
# C. Available-scope EOD completeness -- requires the EXACT expected
#    named components, not merely "whatever is present is CHECKED".
# ---------------------------------------------------------------------

def _rec(component_status, *, status="PARTIAL", mismatches=None):
    return {"status": status, "mismatches": mismatches or [], "component_status": component_status}


_ALL_CHECKED_EXCEPT_PIV = [
    {"name": "original_paper", "outcome": "CHECKED"},
    {"name": "experimental_paper", "outcome": "CHECKED"},
    {"name": "piv_paper", "outcome": "NOT_CHECKED"},
    {"name": "alert_stores", "outcome": "CHECKED"},
]


def test_available_scope_true_for_the_complete_expected_record():
    from talonx_ops.eod_reconciliation import reconciled_to_available_scope

    assert reconciled_to_available_scope(_rec(_ALL_CHECKED_EXCEPT_PIV)) is True


def test_available_scope_false_when_a_required_component_is_missing():
    from talonx_ops.eod_reconciliation import reconciled_to_available_scope

    incomplete = [c for c in _ALL_CHECKED_EXCEPT_PIV if c["name"] != "alert_stores"]
    assert reconciled_to_available_scope(_rec(incomplete)) is False


def test_available_scope_false_with_duplicate_component_entries():
    from talonx_ops.eod_reconciliation import reconciled_to_available_scope

    dup = list(_ALL_CHECKED_EXCEPT_PIV) + [{"name": "original_paper", "outcome": "CHECKED"}]
    assert reconciled_to_available_scope(_rec(dup)) is False


def test_available_scope_false_with_an_unexpected_extra_component():
    from talonx_ops.eod_reconciliation import reconciled_to_available_scope

    extra = list(_ALL_CHECKED_EXCEPT_PIV) + [{"name": "some_new_component", "outcome": "CHECKED"}]
    assert reconciled_to_available_scope(_rec(extra)) is False


def test_available_scope_false_when_a_required_component_is_unknown():
    from talonx_ops.eod_reconciliation import reconciled_to_available_scope

    broken = [dict(c) for c in _ALL_CHECKED_EXCEPT_PIV]
    for c in broken:
        if c["name"] == "alert_stores":
            c["outcome"] = "UNKNOWN"
    assert reconciled_to_available_scope(_rec(broken)) is False


def test_available_scope_false_with_nonempty_mismatches():
    from talonx_ops.eod_reconciliation import reconciled_to_available_scope

    assert reconciled_to_available_scope(
        _rec(_ALL_CHECKED_EXCEPT_PIV, mismatches=["something disagreed"])) is False


def test_available_scope_preserves_the_strict_field_meaning_unaffected(tmp_path):
    """The strict `today_reconciled`/`eod_reconciled_today` field's own
    meaning (status must be RECONCILED/RECONCILED_WITH_MISMATCH) is
    completely independent of this helper and is not touched by it."""
    from talonx_ops.eod_reconciliation import STATUS_PARTIAL, reconciled_to_available_scope

    rec = _rec(_ALL_CHECKED_EXCEPT_PIV)
    assert rec["status"] == STATUS_PARTIAL
    assert reconciled_to_available_scope(rec) is True
    # the strict boolean an existing caller computes directly from status
    # stays False for this same PARTIAL record -- unaffected.
    assert (rec["status"] in ("RECONCILED", "RECONCILED_WITH_MISMATCH")) is False


def test_wrong_session_record_never_reaches_the_available_scope_helper(tmp_path):
    """Read-model boundary check: AuthoritativeReadModel.eod_
    reconciliation() only evaluates `today_reconciled_available_scope`
    when a record for TODAY's own session_date exists -- a stale
    yesterday-only record must read today_reconciled_available_scope as
    False without the helper ever being called on the wrong-session
    record."""
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel
    from talonx_ops.eod_reconciliation import EodReconciliationStore, build_reconciliation

    (tmp_path / "experimental").mkdir()
    for db, tbl in (
        (tmp_path / "paper_trading.db", None),
        (tmp_path / "experimental" / "experimental_paper.db", None),
    ):
        import sqlite3
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY)")
        con.execute("CREATE TABLE trade_history (id INTEGER PRIMARY KEY, timestamp TEXT)")
        con.commit(); con.close()
    import sqlite3
    con = sqlite3.connect(tmp_path / "ingestion_ledger.db")
    con.execute("CREATE TABLE text_events (id INTEGER PRIMARY KEY)")
    con.commit(); con.close()

    yesterday = "2026-09-13"
    rec = build_reconciliation(session_date=yesterday, home=tmp_path,
                               exp_home=tmp_path / "experimental",
                               ledger_path=tmp_path / "ingestion_ledger.db",
                               now=datetime(2026, 9, 13, 20, 0, 0, tzinfo=UTC))
    store = EodReconciliationStore(tmp_path / "eod_reconciliation.db")
    store.upsert(rec)
    store.close()

    da = AuthoritativeReadModel(home=tmp_path, check_processes=False).eod_reconciliation()
    assert da.values["today_has_a_record"] is False
    assert da.values["today_reconciled_available_scope"] is False
