"""Task 83 §3/§6 -- the explicit health-state contract, the QuantStateStore
capability limitation, and the IEX receipt-vs-source-time schema hooks.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from talonx_compare.health import (
    DEGRADED,
    DISCONNECTED,
    HEALTH_STATES,
    HEALTHY,
    MISSING,
    NOT_RUN,
    QUANT_STATE_STORE_LIMITATION,
    RUNNING,
    STALE,
    UNREADABLE,
    WRONG_SESSION,
    classify_json_file,
    classify_jsonl_stream,
    classify_pipeline_run,
    classify_redis,
)
from talonx_compare.identity import ComparisonRecord, EXEC_PIV_PAPER, EXEC_SIMULATED_PAPER, make_record

NOW = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)


def test_all_health_states_defined():
    assert HEALTH_STATES == (
        RUNNING, HEALTHY, DEGRADED, STALE, MISSING, DISCONNECTED, NOT_RUN, UNREADABLE, WRONG_SESSION,
    )
    # exactly the nine the task enumerates -- no more, no fewer
    assert len(set(HEALTH_STATES)) == 9


def test_classify_missing_required_is_missing_not_zero(tmp_path):
    h = classify_json_file(tmp_path / "nope.json", required=True, now=NOW)
    assert h.state == MISSING
    assert h.trustworthy_zero is False  # a UI must NOT print 0 next to this


def test_classify_absent_optional_is_not_run(tmp_path):
    h = classify_json_file(tmp_path / "opt.json", required=False, now=NOW)
    assert h.state == NOT_RUN
    assert h.trustworthy_zero is False


def test_classify_unreadable(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{ not json", encoding="utf-8")
    assert classify_json_file(p, required=True, now=NOW).state == UNREADABLE


def test_classify_wrong_session(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"session_id": "other"}), encoding="utf-8")
    h = classify_json_file(p, required=True, now=NOW, expected_session_id="mine")
    assert h.state == WRONG_SESSION


def test_classify_stale_by_age(tmp_path):
    p = tmp_path / "s.json"
    old = (NOW - timedelta(seconds=600)).isoformat()
    p.write_text(json.dumps({"session_id": "mine", "updated_at": old}), encoding="utf-8")
    h = classify_json_file(p, required=True, now=NOW, stale_seconds=120,
                           expected_session_id="mine", last_update_field="updated_at")
    assert h.state == STALE
    assert h.age_seconds is not None and h.age_seconds > 120


def test_classify_empty_required_without_corroboration_is_not_run(tmp_path):
    p = tmp_path / "e.json"
    p.write_text("{}", encoding="utf-8")
    h = classify_json_file(p, required=True, now=NOW, run_corroborated=False)
    assert h.state == NOT_RUN


def test_classify_empty_with_corroboration_is_a_real_zero(tmp_path):
    p = tmp_path / "e.json"
    p.write_text("{}", encoding="utf-8")
    h = classify_json_file(p, required=True, now=NOW, run_corroborated=True)
    assert h.state == HEALTHY
    assert h.trustworthy_zero is True


def test_jsonl_stream_stale_and_unreadable(tmp_path):
    p = tmp_path / "ev.jsonl"
    old = (NOW - timedelta(hours=2)).isoformat()
    p.write_text(json.dumps({"timestamp": old, "session_id": "s"}) + "\n", encoding="utf-8")
    assert classify_jsonl_stream(p, now=NOW, stale_seconds=120).state == STALE

    p.write_text('{"ok":1}\nnot-json\n', encoding="utf-8")
    assert classify_jsonl_stream(p, now=NOW).state == UNREADABLE


def test_jsonl_stream_wrong_session(tmp_path):
    p = tmp_path / "ev.jsonl"
    p.write_text(json.dumps({"timestamp": NOW.isoformat(), "session_id": "other"}) + "\n", encoding="utf-8")
    h = classify_jsonl_stream(p, now=NOW, scope_field="session_id", expected_scope="mine")
    assert h.state == WRONG_SESSION


def test_classify_redis_states():
    assert classify_redis(None).state == NOT_RUN
    assert classify_redis(True).state == RUNNING
    assert classify_redis(False).state == DISCONNECTED


def test_not_run_is_distinct_from_zero_activity():
    not_run = classify_pipeline_run(corroborated=False, live=False)
    healthy_zero = classify_pipeline_run(corroborated=True, live=False)
    assert not_run.state == NOT_RUN
    assert healthy_zero.state == HEALTHY
    assert not_run.trustworthy_zero is False
    assert healthy_zero.trustworthy_zero is True


def test_quant_state_store_limitation_exposed():
    lim = QUANT_STATE_STORE_LIMITATION
    assert lim["state"] == "NOT_IMPLEMENTED"
    assert lim["persistence_exists"] is False
    assert lim["isolated_path_reserved"] is True
    assert "does not mean persistence exists" in lim["detail"].lower() \
        or "does not mean persistence exists today" in lim["detail"].lower()


def test_isolated_path_not_implied_as_persistence(tmp_path):
    """The projection must state persistence does not exist even if the
    reserved piv_quant.db path happens to be present on disk."""
    from talonx_piv.observability import build_integrated_projection

    (tmp_path / "piv_quant.db").write_bytes(b"SQLite format 3\x00")  # a file at the reserved path
    proj = build_integrated_projection(tmp_path)
    lim = proj["capability_limitations"]["durable_quant_state_store"]
    assert lim["status"] == "NOT_IMPLEMENTED"
    assert lim["persistence_exists"] is False
    assert lim["isolated_path_present_on_disk"] is True  # present...
    assert "does not indicate" in lim["detail"]          # ...but explicitly not persistence


def test_schema_supports_both_bar_timestamps():
    """A comparison record carries event_time AND source_bar_time so the
    unresolved IEX receipt-vs-source question can be displayed later."""
    rec = make_record(
        pipeline="PIV", stage="decision", symbol="AAPL",
        event_time="2026-08-28T14:05:00+00:00", session_id="s1",
        source_bar_time="2026-08-28T14:04:00+00:00",
    )
    d = rec.to_dict()
    assert d["event_time"] == "2026-08-28T14:05:00+00:00"
    assert d["source_bar_time"] == "2026-08-28T14:04:00+00:00"
    # both survive a round trip
    assert ComparisonRecord.from_dict(d).source_bar_time == "2026-08-28T14:04:00+00:00"


def test_pnl_never_merged_execution_classes_are_disjoint():
    sim = make_record(pipeline="ORIGINAL", stage="lifecycle", symbol="AAPL",
                      event_time=NOW.isoformat(), session_id=None,
                      execution_class=EXEC_SIMULATED_PAPER)
    paper = make_record(pipeline="PIV", stage="lifecycle", symbol="AAPL",
                        event_time=NOW.isoformat(), session_id="s1",
                        execution_class=EXEC_PIV_PAPER)
    assert sim.execution_class != paper.execution_class
    # divergence classifier flags this as an execution-mode difference, not agreement
    from talonx_compare.divergence import EXECUTION_MODE_DIFFERENCE, classify_divergence

    d = classify_divergence(sim, paper)
    assert d is not None and d.divergence_class == EXECUTION_MODE_DIFFERENCE
