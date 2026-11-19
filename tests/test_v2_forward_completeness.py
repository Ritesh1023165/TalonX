"""V2@1 forward-study completeness over the REGISTERED schedule (2026-10-12 correction: the dashboard counted only the
last 7 record files, omitting 2026-10-05 and the record-less legacy days). Synthetic fixtures only; outputs never
opened."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_paperperf import forward_status as FS
from tests.test_v2_forward_status_persistence import PS, rec

UTC = timezone.utc
NOW = datetime(2026, 10, 12, 19, 52, tzinfo=UTC)


def repo(tmp_path, end="2026,10,31"):
    sh = tmp_path / "docs/research/evidence/2026-09-30_v2_validation/forward_daily_v2.sh"
    sh.parent.mkdir(parents=True)
    sh.write_text(f"while ... d.date.today()<=d.date({end}) ...\n", encoding="utf-8")
    (tmp_path / "results/v2_validation/forward_runs").mkdir(parents=True)
    (tmp_path / "results/v2_validation/forward").mkdir(parents=True)
    return tmp_path


def put(r, day, obj):
    p = r / "results/v2_validation/forward_runs" / f"{day}.json"
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


def out_file(r, day, when: datetime):
    p = r / "results/v2_validation/forward" / f"{day}.json"
    p.write_text('{"rows": "OUTCOME -- must never be read"}', encoding="utf-8")
    os.utime(p, (when.timestamp(), when.timestamp()))


def log(r, *lines):
    (r / "results/v2_validation/forward.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def ok(day):
    return rec(day, state="SUCCESS", artifact={"validated": True}, start=f"{day}T06:00:00+00:00",
               deadline=f"{day}T07:30:00+00:00")


def by_day(c):
    return {s["day"]: s for s in c["slots_detail"]}


def build(tmp_path):
    r = repo(tmp_path)
    for d in ("2026-09-30", "2026-10-01"):                                       # legacy, output written in cycle
        out_file(r, d, datetime.fromisoformat(f"{d}T06:04:00+00:00"))
    log(r, '{"cycle_done": "2026-09-30T15:02:15Z"}', "research statistic line: hit rate 0.61 -- MUST NOT surface",
        '{"cycle_done": "2026-10-01T06:04:01Z"}', '{"cycle_done": "2026-10-02T06:05:29Z"}',
        '{"cycle_done": "2026-10-05T06:01:02Z"}', '{"cycle_end": "2026-10-11T06:01:33Z", "day": "2026-10-11", '
        '"state": "RUNNING", "exit": 1}', '{"rows": [1, 2], "mean_ret": 0.5}')
    put(r, "2026-10-05", {**rec("2026-10-05", state="PARTIAL", deadline=None), "reconstructed_from_log": True,
                          "artifact": {"validated": False, "problems": ["NOT_PRODUCED"]}})
    for d in ("2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10", "2026-10-12"):
        put(r, d, ok(d))
        out_file(r, d, datetime.fromisoformat(f"{d}T06:03:00+00:00"))
    put(r, "2026-10-11", rec("2026-10-11", pid=772))
    (r / "results/v2_validation/forward_runs/2026-10-11.json.tmp").write_text("{}")
    return r


def test_full_period_reconciliation_counts_and_named_dates(tmp_path):
    c = FS.completeness(build(tmp_path), NOW, PS(exists=False))
    s = by_day(c)
    assert c["period"] == "2026-09-30 .. 2026-10-31 (inclusive)" and c["slots"] == 32
    assert s["2026-10-05"]["state"] == "PARTIAL" and s["2026-10-05"]["provenance"] == "RECONSTRUCTED"
    assert s["2026-10-11"]["recorded_state"] == "RUNNING" and s["2026-10-11"]["state"] == "ABANDONED"
    assert "orphaned temp record (not authoritative, not read)" in s["2026-10-11"]["evidence"]
    assert s["2026-10-06"]["state"] == "SUCCESS"
    assert s["2026-09-30"]["state"] == s["2026-10-01"]["state"] == "UNVERIFIED"      # output exists: never proof
    assert s["2026-10-02"]["state"] == "UNVERIFIED" and "no output file" in s["2026-10-02"]["reason"]
    assert s["2026-10-03"]["state"] == s["2026-10-04"]["state"] == "MISSING"          # no evidence at all
    assert s["2026-10-13"]["state"] == "NOT_YET_DUE" and s["2026-10-31"]["state"] == "NOT_YET_DUE"
    assert c["counts"] == {"success": 6, "incomplete_or_missing": 4, "unverified": 3, "running_or_due": 0,
                           "not_yet_due": 19, "unreadable_or_unknown": 0}
    assert sum(c["counts"].values()) == c["slots"]                                     # one state per slot
    assert [a["day"] for a in c["affected"]] == ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03",
                                                 "2026-10-04", "2026-10-05", "2026-10-11"]


def test_weekends_are_registered_slots_and_end_date_is_inclusive(tmp_path):
    c = FS.completeness(repo(tmp_path, end="2026,10,31"), datetime(2026, 11, 2, tzinfo=UTC))
    s = by_day(c)
    assert s["2026-10-03"]["weekday"] == "Sat" and s["2026-10-04"]["weekday"] == "Sun"
    assert max(s) == "2026-10-31" and "2026-11-01" not in s and s["2026-10-31"]["state"] == "MISSING"
    assert s["2026-09-30"]["expected_utc"].startswith("2026-09-30 (start-up")
    assert s["2026-10-01"]["expected_utc"] == "2026-10-01T06:00:00+00:00"


def test_today_slot_due_running_and_future(tmp_path):
    r = repo(tmp_path)
    at = datetime(2026, 10, 13, 6, 10, tzinfo=UTC)
    assert by_day(FS.completeness(r, at))["2026-10-13"]["state"] == "DUE_AWAITING_RECORD"
    assert by_day(FS.completeness(r, datetime(2026, 10, 13, 5, 59, tzinfo=UTC)))["2026-10-13"]["state"] == "NOT_YET_DUE"
    put(r, "2026-10-13", rec("2026-10-13", start="2026-10-13T06:00:00+00:00", deadline="2026-10-13T07:30:00+00:00"))
    live = PS(created=datetime(2026, 10, 13, 5, 59, 59, tzinfo=UTC))
    c = FS.completeness(r, at, live)
    assert by_day(c)["2026-10-13"]["state"] == "RUNNING" and c["counts"]["running_or_due"] == 1
    assert by_day(FS.completeness(r, datetime(2026, 10, 13, 8, 0, tzinfo=UTC)))["2026-10-14"]["state"] == "NOT_YET_DUE"


def test_conflicting_evidence_is_listed_not_resolved_favourably(tmp_path):
    r = repo(tmp_path)
    put(r, "2026-10-06", ok("2026-10-06"))                                    # record SUCCESS, output absent
    put(r, "2026-10-07", rec("2026-10-07", state="PARTIAL", start="2026-10-07T06:00:00+00:00"))
    out_file(r, "2026-10-07", datetime(2026, 10, 7, 6, 5, tzinfo=UTC))        # PARTIAL but output written in run
    log(r, '{"cycle_end": "2026-10-08T06:03:28Z", "day": "2026-10-08", "state": "SUCCESS", "exit": 0}')
    put(r, "2026-10-08", rec("2026-10-08", state="FAILED", start="2026-10-08T06:00:00+00:00"))
    s = by_day(FS.completeness(r, NOW))
    assert s["2026-10-06"]["state"] == "SUCCESS" and s["2026-10-06"]["conflicts"] == ["record SUCCESS but output file absent"]
    assert s["2026-10-07"]["state"] == "PARTIAL" and "output file was written" in s["2026-10-07"]["conflicts"][0]
    assert s["2026-10-08"]["state"] == "FAILED" and s["2026-10-08"]["conflicts"] == \
        ["loop logged SUCCESS but the record says FAILED"]                     # the less favourable record stands


def test_unreadable_record_is_counted_once_and_never_success(tmp_path):
    r = repo(tmp_path)
    put(r, "2026-10-06", "{ broken")
    log(r, '{"cycle_end": "2026-10-06T06:14:18Z", "day": "2026-10-06", "state": "SUCCESS", "exit": 0}')
    out_file(r, "2026-10-06", datetime(2026, 10, 6, 6, 14, tzinfo=UTC))
    c = FS.completeness(r, NOW)
    assert by_day(c)["2026-10-06"]["state"] == "UNREADABLE" and c["counts"]["unreadable_or_unknown"] == 1
    assert c["counts"]["success"] == 0


def test_health_stays_distinct_from_completeness_in_the_view(tmp_path):
    v = FS.view(build(tmp_path), now=NOW, ps=PS(exists=False))
    assert v["current_health"] == "HEALTHY"                                    # latest run SUCCESS
    assert v["completeness"]["counts"]["incomplete_or_missing"] == 4           # history still incomplete
    assert len(v["runs"]) == 7 and "2026-10-05" not in {x["day"] for x in v["runs"]}   # recent table stays bounded
    assert "2026-10-05" in {a["day"] for a in v["completeness"]["affected"]}   # ...but 10-05 is no longer omitted


def test_no_output_file_is_ever_opened_and_no_statistic_surfaces(tmp_path, monkeypatch):
    r = build(tmp_path)
    opened = []
    real_rt, real_open = Path.read_text, open

    def spy_rt(self, *a, **k):
        opened.append(str(self))
        return real_rt(self, *a, **k)

    def spy_open(f, *a, **k):
        opened.append(str(f))
        return real_open(f, *a, **k)
    monkeypatch.setattr(Path, "read_text", spy_rt)
    monkeypatch.setattr("builtins.open", spy_open)
    c = FS.completeness(r, NOW, PS(exists=False))
    assert not [p for p in opened if os.sep + "forward" + os.sep in p or p.replace("\\", "/").endswith("/forward")]
    assert all(p.replace("\\", "/").split("/results/v2_validation/")[-1].startswith(("forward_runs/", "forward.log"))
               or p.endswith("forward_daily_v2.sh") for p in opened)
    blob = json.dumps(c)
    assert "OUTCOME" not in blob and "hit rate" not in blob and "mean_ret" not in blob


def test_structured_log_keeps_only_operational_markers(tmp_path):
    r = repo(tmp_path)
    log(r, '{"cycle_done": "2026-10-01T06:04:01Z"}', '{"cycle_done": "x", "mean_ret": 0.4}', "plain text 0.61",
        '{"forward_runner": "END", "state": "SUCCESS", "day": "2026-10-06"}', '[1,2]')
    assert FS._structured_log(r) == [{"cycle_done": "2026-10-01T06:04:01Z"},
                                     {"forward_runner": "END", "state": "SUCCESS", "day": "2026-10-06"}]


def test_missing_stop_date_is_reported_not_guessed(tmp_path):
    (tmp_path / "results/v2_validation/forward_runs").mkdir(parents=True)
    c = FS.completeness(tmp_path, NOW)
    assert c["slots"] == 0 and c["period"].startswith("UNKNOWN")
