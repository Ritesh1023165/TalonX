"""
tests/test_task137_overnight_continuity.py
-------------------------------------------
Task 137: overnight continuity, scope accuracy and delivery fairness.

Sections:
1. EOD reconciliation "PARTIAL solely because PIV is never checked in
   this deployment" is a standing, permanent condition, not evidence of a
   real problem -- ``reconciled_to_available_scope`` distinguishes it
   from a genuinely incomplete/broken reconciliation, as a SEPARATE,
   explicitly-named signal (never a silent reclassification of the
   existing strict `today_reconciled`/`eod_reconciled_today`).
2. Deferred-lookup SATURATION (not merely one failing row alongside an
   eligible one): a small selection limit filled entirely by repeatedly-
   failing, higher-priority rows must not starve a valid eligible row
   sitting behind them, across multiple drain cycles with a controlled
   clock, and the row must recover normally once the lookup succeeds.
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


# ---------------------------------------------------------------------
# 1. EOD reconciliation scope-accuracy signal
# ---------------------------------------------------------------------

def _enq_piv_only_partial(tmp_path, session):
    """Build the EXACT real-world pattern: original_paper/experimental_
    paper/alert_stores all CHECKED, piv_paper NOT_CHECKED (no piv_reader
    injected -- this deployment never wires PIV up), no mismatches."""
    from talonx_ops.eod_reconciliation import build_reconciliation

    (tmp_path / "experimental").mkdir(exist_ok=True)
    import sqlite3
    for db, tbl in (
        (tmp_path / "paper_trading.db", None),
        (tmp_path / "experimental" / "experimental_paper.db", None),
    ):
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY)")
        con.execute("CREATE TABLE trade_history (id INTEGER PRIMARY KEY, timestamp TEXT)")
        con.commit()
        con.close()
    con = sqlite3.connect(tmp_path / "ingestion_ledger.db")
    con.execute("CREATE TABLE text_events (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()

    return build_reconciliation(
        session_date=session, home=tmp_path, exp_home=tmp_path / "experimental",
        ledger_path=tmp_path / "ingestion_ledger.db",
        now=datetime(2026, 9, 14, 20, 13, 32, tzinfo=UTC),
    )


def test_reconciled_to_available_scope_true_for_piv_only_partial(tmp_path):
    from talonx_ops.eod_reconciliation import STATUS_PARTIAL, reconciled_to_available_scope

    rec = _enq_piv_only_partial(tmp_path, "2026-09-14")
    assert rec.status == STATUS_PARTIAL            # reproduces the real Task 136 pattern
    assert reconciled_to_available_scope(rec) is True


def test_reconciled_to_available_scope_false_for_a_genuinely_broken_component():
    """A PARTIAL caused by something OTHER than piv_paper being NOT_CHECKED
    (e.g. alert_stores itself came back UNKNOWN -- a real local read
    problem) must NOT be reported as available-scope-reconciled."""
    from talonx_ops.eod_reconciliation import STATUS_PARTIAL, reconciled_to_available_scope

    rec = {
        "status": STATUS_PARTIAL,
        "mismatches": [],
        "component_status": [
            {"name": "original_paper", "outcome": "CHECKED"},
            {"name": "experimental_paper", "outcome": "CHECKED"},
            {"name": "piv_paper", "outcome": "NOT_CHECKED"},
            {"name": "alert_stores", "outcome": "UNKNOWN"},   # the real problem
        ],
    }
    assert reconciled_to_available_scope(rec) is False


def test_reconciled_to_available_scope_false_when_mismatches_present():
    from talonx_ops.eod_reconciliation import STATUS_PARTIAL, reconciled_to_available_scope

    rec = {
        "status": STATUS_PARTIAL,
        "mismatches": ["original_paper: 1 open position(s) but 0 trades recorded ever"],
        "component_status": [
            {"name": "original_paper", "outcome": "CHECKED"},
            {"name": "experimental_paper", "outcome": "CHECKED"},
            {"name": "piv_paper", "outcome": "NOT_CHECKED"},
            {"name": "alert_stores", "outcome": "CHECKED"},
        ],
    }
    assert reconciled_to_available_scope(rec) is False


def test_reconciled_to_available_scope_false_for_fully_reconciled_status():
    """The new field is meaningless (and stays False) once `status` is
    already RECONCILED -- it exists ONLY to rescue the PARTIAL-because-
    PIV-only case, never as an alternate route to "true" generally."""
    from talonx_ops.eod_reconciliation import STATUS_RECONCILED, reconciled_to_available_scope

    rec = {
        "status": STATUS_RECONCILED,
        "mismatches": [],
        "component_status": [
            {"name": "original_paper", "outcome": "CHECKED"},
            {"name": "experimental_paper", "outcome": "CHECKED"},
            {"name": "piv_paper", "outcome": "CHECKED"},
            {"name": "alert_stores", "outcome": "CHECKED"},
        ],
    }
    assert reconciled_to_available_scope(rec) is False


def test_authoritative_read_model_exposes_the_narrower_signal_without_changing_the_strict_one(tmp_path):
    """End-to-end through the real read path: `today_reconciled` keeps its
    existing strict (False) meaning for a PIV-only-PARTIAL record, while
    the new `today_reconciled_available_scope` is True -- both present,
    neither silently overwriting the other."""
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel
    from talonx_ops.eod_reconciliation import EodReconciliationStore

    session = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rec = _enq_piv_only_partial(tmp_path, session)
    store = EodReconciliationStore(tmp_path / "eod_reconciliation.db")
    store.upsert(rec)
    store.close()

    da = AuthoritativeReadModel(home=tmp_path, check_processes=False).eod_reconciliation()
    assert da.values["today_record_status"] == "PARTIAL"
    assert da.values["today_reconciled"] is False             # unchanged, strict
    assert da.values["today_reconciled_available_scope"] is True   # new, narrower signal


# ---------------------------------------------------------------------
# 2. Deferred-lookup SATURATION -- a bounded selection limit filled
#    entirely by repeatedly-failing rows must not starve a valid row.
# ---------------------------------------------------------------------

def _enq(ob, *, symbol, accession, enqueued_at, event_type=EventType.EARNINGS_RESULTS,
         on_watchlist=True):
    card, _ = make_card(symbol=symbol, accession=accession, event_type=event_type,
                        on_watchlist=on_watchlist, now=enqueued_at)
    r = enqueue_card(card, outbox=ob, now=enqueued_at).row
    return r.delivery_id, r.event_id, r.route


def _drain(ob, sender, **kw):
    kw.setdefault("mode", "enabled")
    kw.setdefault("enforce_age_cutoff", True)
    return asyncio.run(process_pending(ob, sender, **kw))


def test_saturated_batch_of_failing_lookups_does_not_permanently_starve_a_valid_row(ledger_path):
    """A bounded per-cycle selection `limit` is entirely filled by rows
    whose lookup ALWAYS raises (DEFER every time) and which sort AHEAD of
    one valid, eligible row (older enqueue time -> selected first by
    ``pending()``'s band+enqueue ordering). The eligible row must still
    reach SENT within a bounded number of drain cycles -- proving
    fairness ACROSS cycles, not merely "does not stop mid-batch"."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    LIMIT = 3

    flaky_ids = []
    flaky_eids = set()
    for i in range(LIMIT):
        did, eid, _ = _enq(ob, symbol=f"FLK{i}", accession=f"000000004{i}-26-00004{i}",
                           enqueued_at=now - timedelta(minutes=30 - i))
        flaky_ids.append(did)
        flaky_eids.add(eid)

    good_did, good_eid, _ = _enq(ob, symbol="GOOD", accession="0000000050-26-000050",
                                 enqueued_at=now - timedelta(minutes=5))

    def _lookup(event_id):
        if event_id in flaky_eids:
            raise RuntimeError("permanently flaky lookup")
        return now - timedelta(minutes=5)          # GOOD: valid, fresh

    snd = RecordingSender()
    sent_ever: set[str] = set()
    for cycle in range(6):
        res = _drain(ob, snd, now=now + timedelta(seconds=cycle), event_time_lookup=_lookup,
                    route="IMMEDIATE", limit=LIMIT)
        sent_ever |= {r.delivery_id for r in snd.sent}
        if good_did in sent_ever:
            break

    assert good_did in sent_ever, (
        "the eligible row was never sent across repeated cycles -- a "
        "saturated batch of permanently-failing lookups starved it"
    )
    assert ob.get(good_did).state == STATE_SENT
    # every flaky row is still PENDING and recoverable -- never terminally
    # discarded just because its lookup temporarily (repeatedly) failed
    assert all(ob.get(d).state == STATE_PENDING for d in flaky_ids)
    ob.close()


def test_saturated_batch_row_recovers_once_its_lookup_succeeds(ledger_path):
    """One of the LIMIT-filling flaky rows starts failing, then its
    lookup starts succeeding on a later cycle -- it must be delivered
    normally afterward, exactly-once, with no special-cased state."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 14, 16, 0, 0, tzinfo=UTC)
    LIMIT = 2
    did_a, eid_a, _ = _enq(ob, symbol="RCA", accession="0000000060-26-000060",
                           enqueued_at=now - timedelta(minutes=20))
    did_b, eid_b, _ = _enq(ob, symbol="RCB", accession="0000000061-26-000061",
                           enqueued_at=now - timedelta(minutes=19))

    state = {"a_fails": True}

    def _lookup(event_id):
        if event_id == eid_a and state["a_fails"]:
            raise RuntimeError("transient failure")
        if event_id == eid_a:
            return now - timedelta(minutes=20)
        return now - timedelta(minutes=19)          # B always valid

    snd = RecordingSender()
    _drain(ob, snd, now=now, event_time_lookup=_lookup, route="IMMEDIATE", limit=LIMIT)
    assert ob.get(did_a).state == STATE_PENDING     # DEFER'd, not terminal
    assert ob.get(did_b).state == STATE_SENT

    state["a_fails"] = False                        # the lookup recovers
    # past the fixed DEFER backoff window (_DEFER_BACKOFF_SECONDS=30) set
    # on the first cycle -- otherwise the row is correctly still excluded
    # from selection by its own bounded retry delay, independent of
    # whether the lookup itself would now succeed.
    _drain(ob, snd, now=now + timedelta(seconds=31), event_time_lookup=_lookup,
          route="IMMEDIATE", limit=LIMIT)
    assert ob.get(did_a).state == STATE_SENT
    # exactly-once: B was never re-sent on the second cycle
    assert [r.delivery_id for r in snd.sent].count(did_b) == 1
    ob.close()


# ---------------------------------------------------------------------
# 3. Scope accuracy -- the observational V2 near-miss funnel must match
#    the actual live companion's (possibly broad-discovery-widened)
#    execution scope, not silently keep recomputing a narrower one.
#    Uses an isolated, synthetic "broad-only" symbol -- never live state.
# ---------------------------------------------------------------------

def test_resolved_execution_scope_excludes_broad_only_symbol_by_default(tmp_path, monkeypatch):
    import talonx_ops.prospective.funnel as funnel_mod

    manifest = tmp_path / "discovery_universe_v1_626.json"
    manifest.write_text('{"symbols": ["ZZBROADONLY"]}', encoding="utf-8")
    monkeypatch.setattr(funnel_mod, "_BROAD_DISCOVERY_MANIFEST", manifest)
    # the real import site is inside the function (`from talonx_ops.
    # watchlist_coverage import build_coverage_map`) -- patch the module
    # actually imported from, not the funnel module's own namespace.
    import talonx_ops.watchlist_coverage as wc_mod
    monkeypatch.setattr(
        wc_mod, "build_coverage_map",
        lambda: {"tickers": [{"symbol": "AAPL", "v2_collection_scope": "POLLED"}]},
    )

    narrow = funnel_mod._resolved_execution_scope(include_broad_discovery=False)
    assert narrow == ["AAPL"]
    assert "ZZBROADONLY" not in narrow


def test_resolved_execution_scope_includes_broad_only_symbol_when_requested(tmp_path, monkeypatch):
    import talonx_ops.prospective.funnel as funnel_mod
    import talonx_ops.watchlist_coverage as wc_mod

    manifest = tmp_path / "discovery_universe_v1_626.json"
    manifest.write_text('{"symbols": ["ZZBROADONLY"]}', encoding="utf-8")
    monkeypatch.setattr(funnel_mod, "_BROAD_DISCOVERY_MANIFEST", manifest)
    monkeypatch.setattr(
        wc_mod, "build_coverage_map",
        lambda: {"tickers": [{"symbol": "AAPL", "v2_collection_scope": "POLLED"}]},
    )

    wide = funnel_mod._resolved_execution_scope(include_broad_discovery=True)
    assert set(wide) == {"AAPL", "ZZBROADONLY"}


def test_build_funnel_reports_both_the_narrow_and_resolved_scope_explicitly(tmp_path, monkeypatch):
    """The intended end-to-end path: build_funnel(include_broad_discovery=
    True) must report BOTH counts, explicitly labelled -- never silently
    substituting the wider one for the narrower one, and never claiming a
    wide scope while a caller who asked for the narrow (default) behaviour
    still gets exactly that."""
    import talonx_ops.prospective.funnel as funnel_mod
    import talonx_ops.watchlist_coverage as wc_mod

    manifest = tmp_path / "discovery_universe_v1_626.json"
    manifest.write_text('{"symbols": ["ZZBROADONLY"]}', encoding="utf-8")
    monkeypatch.setattr(funnel_mod, "_BROAD_DISCOVERY_MANIFEST", manifest)
    monkeypatch.setattr(
        wc_mod, "build_coverage_map",
        lambda: {"tickers": [{"symbol": "AAPL", "v2_collection_scope": "POLLED"}]},
    )
    empty_db = tmp_path / "empty_v2_lane.db"
    import sqlite3
    sqlite3.connect(empty_db).close()

    narrow = funnel_mod.build_funnel(db_path=empty_db, include_broad_discovery=False)
    assert narrow["scope"]["execution_scope_count"] == 1        # AAPL only
    assert narrow["scope"]["watchlist_only_count"] == 1
    assert narrow["scope"]["broad_discovery_included"] is False

    wide = funnel_mod.build_funnel(db_path=empty_db, include_broad_discovery=True)
    assert wide["scope"]["execution_scope_count"] == 2           # AAPL + ZZBROADONLY
    assert wide["scope"]["watchlist_only_count"] == 1            # unchanged, still explicit
    assert wide["scope"]["broad_discovery_included"] is True


def test_live_companion_broad_discovery_detected_from_its_own_reported_scope():
    """SUPERSEDED by Task 138: the bare boolean `_live_companion_uses_
    broad_discovery` this test originally covered has been replaced by
    the qualified `evaluate_scope_evidence` (talonx_ops/prospective/
    checkpoint.py) -- it adds freshness (heartbeat) and process-ownership
    (session.pids.json PID + argv) checks this Task 137 version did not
    have, per a direct review finding. See tests/test_task138_
    operational_corrections.py for the full replacement coverage (fresh/
    stale/missing/wrong-process/manifest-unreadable/mismatch cases). This
    stub only confirms the function still exists and returns the shape
    the newer tests exercise in depth."""
    from talonx_ops.prospective.checkpoint import evaluate_scope_evidence

    assert callable(evaluate_scope_evidence)
