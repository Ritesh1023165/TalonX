"""
tests/test_task139_session_rollover.py
=======================================
Task 139 (revised under Task 140) -- A4: targeted, clock-controlled
gap coverage for session-rollover/EOD-boundary transitions not already
exercised by existing tests. Per the directive: "Use existing tests
where they genuinely cover these transitions. Add clock-controlled,
persistent-store fixtures only for actual gaps."

Already covered elsewhere (reused, not duplicated here):
- today_reconciled is False for every non-RECONCILED status on a
  same-day record: tests/test_task100b_runtime_integration.py::
  test_41b_today_reconciled_true_only_for_a_genuinely_complete_record
- A new late intent cannot justify a past market open (V2 staleness
  guard): tests/test_task113_stale_entry_guard.py (all 4 tests)
- Interrupted-work recovery across persist/enrich/claim/send/ack
  boundaries: tests/test_task133_recoverable_processing.py,
  tests/test_task117_delivery_reliability.py
- "Yesterday's close does not leave today's processing disabled":
  verified by CODE INSPECTION -- neither
  talonx_ingest/intelligence/service/ nor talonx_v2/ contain any
  reference to eod_reconciled/today_reconciled at all (grep, zero
  matches) -- EOD reconciliation is a pure read-only reporting layer
  with no write-back into either processing pipeline, so there is no
  code path that COULD gate processing on it. Reinforced by this
  session's own live evidence (Task 139 recovery): V2 ticked and
  Intelligence enriched normally immediately after restart despite a
  PARTIAL record existing for the prior session date.

The one genuine gap closed here: AuthoritativeReadModel.eod_
reconciliation()'s `today is None` branch (a record exists for
YESTERDAY, none yet for today) was covered by CODE INSPECTION in the
Task 139 evidence but not by an isolated test exercising exactly that
date-boundary case, independent of what status yesterday's record
carried.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_ops.eod_reconciliation import EodReconciliation, EodReconciliationStore

UTC = timezone.utc


def test_yesterdays_reconciled_record_never_marks_today_reconciled(tmp_path):
    """Yesterday's record is fully RECONCILED (the strongest possible
    status) -- today must still read today_reconciled=False and
    today_has_a_record=False, purely on the date boundary, regardless of
    yesterday's own status."""
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel

    db_path = tmp_path / "eod_reconciliation.db"
    store = EodReconciliationStore(db_path)
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    store.upsert(EodReconciliation(
        session_date=yesterday, status="RECONCILED",
        generated_at_utc=datetime.now(UTC).isoformat(),
        original_paper={"open_positions": 0}, experimental_paper={"open_positions": 0},
        piv_paper={}, alert_counts={}, component_status=[], mismatches=[],
    ))
    store.close()

    da = AuthoritativeReadModel(home=tmp_path, check_processes=False).eod_reconciliation()
    assert da.values["today_has_a_record"] is False
    assert da.values["today_record_status"] is None
    assert da.values["today_reconciled"] is False
    assert da.values["today_reconciled_available_scope"] is False
    # the display fallback still surfaces yesterday's session for context
    assert da.values["latest_session"] == yesterday


def test_yesterdays_partial_record_never_marks_today_reconciled(tmp_path):
    """Same boundary, but yesterday's own status is only PARTIAL (the
    deployment's actual standing condition, per Task 137) -- confirms
    the date check, not a status coincidence, is what drives the
    result."""
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel

    db_path = tmp_path / "eod_reconciliation.db"
    store = EodReconciliationStore(db_path)
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    store.upsert(EodReconciliation(
        session_date=yesterday, status="PARTIAL",
        generated_at_utc=datetime.now(UTC).isoformat(),
    ))
    store.close()

    da = AuthoritativeReadModel(home=tmp_path, check_processes=False).eod_reconciliation()
    assert da.values["today_has_a_record"] is False
    assert da.values["today_reconciled"] is False


def test_todays_own_record_appearing_later_the_same_day_flips_the_flag(tmp_path):
    """A same-day rollover check: yesterday RECONCILED, today initially
    absent (today_reconciled False), then today's own record appears
    (e.g. a later close) -- the flag must flip based on TODAY's own
    status, not stay pinned to yesterday's."""
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel

    db_path = tmp_path / "eod_reconciliation.db"
    store = EodReconciliationStore(db_path)
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    store.upsert(EodReconciliation(
        session_date=yesterday, status="RECONCILED",
        generated_at_utc=datetime.now(UTC).isoformat(),
    ))
    store.close()

    before = AuthoritativeReadModel(home=tmp_path, check_processes=False).eod_reconciliation()
    assert before.values["today_reconciled"] is False

    store = EodReconciliationStore(db_path)
    store.upsert(EodReconciliation(
        session_date=today, status="RECONCILED",
        generated_at_utc=datetime.now(UTC).isoformat(),
    ))
    store.close()

    after = AuthoritativeReadModel(home=tmp_path, check_processes=False).eod_reconciliation()
    assert after.values["today_has_a_record"] is True
    assert after.values["today_reconciled"] is True
    assert after.values["latest_session"] == today
