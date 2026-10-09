"""POST_DELIVERY_ALERT_MARKOUT_V1 collector + schedule + locked config (synthetic only; nothing is fetched)."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from talonx_paperperf import post_delivery_acquisition as Q
from talonx_paperperf import post_delivery_collector as C
from talonx_paperperf import post_delivery_markout as M
from tests.test_post_delivery_markout import FakeAcq, good_data, sources, t

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
REPO = Path(__file__).resolve().parents[1]
LOCKED = REPO / "docs" / "research" / "protocols" / "POST_DELIVERY_ALERT_MARKOUT_V1_APPROVED_CONFIG.json"


def r5_fixed_utc_form(now: datetime) -> bool:
    """The older UTC rendering of R5 (13:00-20:30 UTC on weekdays) -- the schedule must avoid it too."""
    return not (now.weekday() < 5 and (13 * 60) <= now.hour * 60 + now.minute < (20 * 60 + 30))


# ============================================================================================ calendar + schedule
def test_approved_period_is_twenty_xnys_sessions_and_the_deadline_is_calendar_derived():
    s = M.study_sessions(date(2026, 10, 19), 20)
    assert s[0].window_id == "2026-10-19" and s[-1].window_id == "2026-11-13" and len(s) == 20
    assert M.deadline(s[-1]) == datetime(2026, 11, 17, 22, 0, tzinfo=UTC)          # EST close 21:00Z + 60 min


def test_daily_schedule_is_after_close_plus_60_and_outside_both_r5_forms_across_uk_and_us_dst():
    sessions = M.study_sessions(date(2026, 10, 19), 20)
    runs = []
    d = date(2026, 10, 19)
    while d <= date(2026, 11, 19):
        runs.append(datetime.combine(d, C.SCHEDULE_LOCAL, tzinfo=C.LONDON).astimezone(UTC))
        d += timedelta(days=1)
    assert runs[0] == datetime(2026, 10, 18, 23, 15, tzinfo=UTC)                   # BST: 00:15 London = 23:15Z
    assert datetime(2026, 10, 26, 0, 15, tzinfo=UTC) in runs                       # after the UK change (25 Oct)
    for r in runs:
        assert Q.r5_permitted(r) and r5_fixed_utc_form(r)
    for w in sessions:                                                              # covers US change (1 Nov)
        mat, dl = M.maturity(w), M.deadline(w)
        eligible = [r for r in runs if mat <= r < dl]
        assert len(eligible) >= 2, w.window_id                                      # >= 2 chances before expiry


def test_scheduled_instant_and_lateness_are_recorded():
    assert C.scheduled_for(datetime(2026, 10, 20, 23, 40, tzinfo=UTC)) == datetime(2026, 10, 20, 23, 15, tzinfo=UTC)
    assert C.scheduled_for(datetime(2026, 11, 3, 2, 0, tzinfo=UTC)) == datetime(2026, 11, 3, 0, 15, tzinfo=UTC)


# ============================================================================================ locked configuration
def test_locked_config_matches_the_committed_code_and_the_approval():
    d = json.loads(LOCKED.read_text(encoding="utf-8"))
    assert d["approved"] is True and d["protocol_fingerprint"] == M.PDM_V1.fingerprint()
    assert d["first_session"] == "2026-10-19" and d["delivery_trace_policy"] == "REQUIRED"
    assert M.verify_integrity(d) == []
    act = M.load_activation(LOCKED, require_integrity=True)
    assert act["last_session"] == "2026-11-13" and act["boundary_utc"] == datetime(2026, 10, 19, tzinfo=UTC)
    assert act["endpoint_utc"] == datetime(2026, 11, 17, 22, 0, tzinfo=UTC)


def test_changed_implementation_is_refused(tmp_path):
    for rel in M.IMPLEMENTATION_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, tmp_path / rel)
    d = json.loads(LOCKED.read_text(encoding="utf-8"))
    assert M.verify_integrity(d, tmp_path) == []
    f = tmp_path / M.IMPLEMENTATION_FILES[0]
    f.write_text(f.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    assert M.verify_integrity(d, tmp_path) == [f"IMPLEMENTATION_CHANGED:{M.IMPLEMENTATION_FILES[0]}"]
    with pytest.raises(M.NotApproved):
        M.load_activation(LOCKED, require_integrity=True, repo=tmp_path)


# ============================================================================================ collector runs
def cfg(tmp_path, **over):
    d = {"approved": True, "approved_by": "owner", "approved_utc": "2026-10-10T12:00:00Z",
         "protocol_fingerprint": M.PDM_V1.fingerprint(), "first_session": "2026-10-12",
         "delivery_trace_policy": "NOT_AVAILABLE_ACCEPTED", "implementation_sha256": M.implementation_hashes(), **over}
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def collect(tmp_path, now, acq=None, enable=True, ob=None, pc=None, alive=lambda pid: False, **over):
    return C.collect(config=cfg(tmp_path, **over), enable=enable, store=tmp_path / "pdm", budget_s=60,
                     max_observations=50, now=now, acquirer=acq, outbox_path=ob, promotion_path=pc,
                     trace_path=tmp_path / "trace.db", lock_alive=alive)


def test_disabled_collector_makes_no_request_and_no_study_store(tmp_path):
    acq = FakeAcq()
    r = collect(tmp_path, t(23, 15), acq, enable=False)
    assert r["state"] == "DISABLED" and acq.calls == [] and not (tmp_path / "pdm").exists()


def test_before_activation_no_request_and_no_store(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="E", sym="AAA", sent=t(14, 10))])
    acq = FakeAcq(*good_data("AAA", t(14, 10)))
    r = collect(tmp_path, t(23, 15, d=11), acq, ob=ob, pc=pc)
    assert r["state"] == "BEFORE_ACTIVATION" and acq.calls == [] and not (tmp_path / "pdm").exists()


def test_overlapping_run_is_refused(tmp_path):
    ops = tmp_path / "pdm_ops"
    ops.mkdir()
    (ops / "collector.lock").write_text(json.dumps({"pid": 4242}), encoding="utf-8")
    r = collect(tmp_path, t(23, 15), FakeAcq(), alive=lambda pid: pid == 4242)
    assert r["state"] == "REFUSED_OVERLAP"
    r2 = collect(tmp_path, t(23, 16), FakeAcq(), enable=False, alive=lambda pid: False)   # stale lock replaced
    assert r2["state"] == "DISABLED" and "stale lock" in r2["lock_note"]


def test_missed_scheduled_runs_and_lateness_are_logged(tmp_path):
    collect(tmp_path, datetime(2026, 10, 12, 23, 15, tzinfo=UTC), enable=False)
    r = collect(tmp_path, datetime(2026, 10, 16, 1, 0, tzinfo=UTC), enable=False)        # 3 London days missed
    assert r["missed_days"] == ["2026-10-14", "2026-10-15"] or r["missed_days"] == ["2026-10-13", "2026-10-14",
                                                                                     "2026-10-15"]
    assert r["late_s"] == pytest.approx((datetime(2026, 10, 16, 1, 0, tzinfo=UTC) -
                                         datetime(2026, 10, 15, 23, 15, tzinfo=UTC)).total_seconds())


def test_end_to_end_run_records_operational_status_without_returns(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="A", sym="AAA", sent=t(14, 10))])
    r = collect(tmp_path, t(23, 15), FakeAcq(*good_data("AAA", t(14, 10))), ob=ob, pc=pc)
    assert r["state"] == "ENABLED" and r["health"]["observations_by_state"] == {M.MEASURED: 1}
    status = (tmp_path / "pdm_ops" / "status_latest.json").read_text(encoding="utf-8")
    assert "gross" not in status and "cost_adjusted" not in status            # no return values in ops output


def test_after_the_endpoint_only_reconciliation_runs_and_nothing_is_fetched(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="Z", sym="AAA", sent=t(14, 10))])
    collect(tmp_path, t(15, 0), None, ob=ob, pc=pc)                          # registered; worker then down
    late = FakeAcq(*good_data("AAA", t(14, 10)))
    r = collect(tmp_path, datetime(2026, 11, 20, tzinfo=UTC), late, ob=ob, pc=pc)
    assert late.calls == [] and r["summary"]["acquisition"] == {"skipped": "AFTER_ENDPOINT"}
    assert r["health"]["observations_by_state"] == {M.EXPIRED: 1}


def test_integrity_failure_refuses_the_run(tmp_path):
    bad = {k: "0" * 64 for k in M.IMPLEMENTATION_FILES}
    r = collect(tmp_path, t(23, 15), FakeAcq(), implementation_sha256=bad)
    assert r["state"] == "NOT_APPROVED" and r["reason"].startswith("INTEGRITY_FAILED")


# ============================================================================================ final report gating
def test_final_report_requires_every_completion_check(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="F", sym="AAA", sent=t(14, 10)),
                                dict(id="P", sym="BBB", sent=t(14, 11), state="PENDING")])
    collect(tmp_path, t(23, 15), FakeAcq(*good_data("AAA", t(14, 10))), ob=ob, pc=pc)
    act = M.load_activation(cfg(tmp_path))
    s = M.Store(tmp_path / "pdm")
    early = M.final_report(s, act, t(23, 30), outbox_path=ob, promotion_path=pc)
    assert early["status"] == "NOT_AVAILABLE_BEFORE_ENDPOINT"
    late = M.final_report(s, act, act["endpoint_utc"], outbox_path=ob, promotion_path=pc)
    assert late["status"] == "INCOMPLETE" and late["checks"]["sources_reconciled"] is False   # a row still in flight
    import sqlite3
    c = sqlite3.connect(ob)
    c.execute("UPDATE ops_notification_outbox SET state='FAILED' WHERE event_id='P'")
    c.commit()
    c.close()
    done = M.final_report(s, act, act["endpoint_utc"], outbox_path=ob, promotion_path=pc)
    assert "status" not in done and next(iter(done.values()))["gross_measured"] == 1


def test_unregistered_delivery_blocks_completion(tmp_path):
    ob, pc = sources(tmp_path, [dict(id="U", sym="AAA", sent=t(14, 10))])
    act = M.load_activation(cfg(tmp_path))
    s = M.Store(tmp_path / "pdm")                                            # nothing registered
    cc = M.completion_checks(s, act, act["endpoint_utc"], outbox_path=ob, promotion_path=pc)
    assert not cc["complete"] and cc["reconciliation"]["unregistered_deliveries"] == 1


# ============================================================================================ isolation
def test_vr_entry_interruption_and_alert_independence_are_untouched():
    src = (REPO / "talonx_opportunity" / "promotion.py").read_text(encoding="utf-8")
    for banned in ("talonx_paperperf", "talonx_v2", "vr_live", "post_delivery"):
        assert banned not in src, banned                                     # measurement never gates delivery
    from talonx_paperperf import vr_live
    assert hasattr(vr_live, "entry_control")
