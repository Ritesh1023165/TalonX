"""POST_DELIVERY_ALERT_MARKOUT_V1: owner-approved second daily trigger (00:15 + 06:30 Europe/London, one logical task)
and the market-calendar integrity binding (2026-10-09). Fixtures + scheduler-definition inspection only."""
from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_paperperf import post_delivery_acquisition as Q
from talonx_paperperf import post_delivery_collector as C
from talonx_paperperf import post_delivery_markout as M
from tests.test_post_delivery_batching import acq_for, go, many, states, count
from tests.test_post_delivery_markout import FakeAcq, sources, t

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]
PROT = REPO / "docs" / "research" / "protocols"
LOCKED = PROT / "POST_DELIVERY_ALERT_MARKOUT_V1_APPROVED_CONFIG.json"
XML = PROT / "pdm_v1_scheduler" / "PDM_V1_Collector.task.xml"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
ENDPOINT = datetime(2026, 11, 17, 22, 0, tzinfo=UTC)


def task():
    return ET.fromstring(XML.read_text(encoding="utf-8").replace('encoding="UTF-16"', ""))


def fired(trig) -> list[datetime]:
    """Every instant a CalendarTrigger fires (local = Europe/London, the machine zone), in UTC."""
    s = datetime.fromisoformat(trig.find("t:StartBoundary", NS).text)
    e = datetime.fromisoformat(trig.find("t:EndBoundary", NS).text)
    assert trig.find("t:ScheduleByDay/t:DaysInterval", NS).text == "1"
    out, cur = [], s
    while cur <= e:
        out.append(cur.replace(tzinfo=C.LONDON).astimezone(UTC))
        cur += timedelta(days=1)
    return out


def all_runs():
    return sorted(x for tr in task().findall("t:Triggers/t:CalendarTrigger", NS) for x in fired(tr))


# ============================================================================================ task definition
def test_one_logical_task_with_exactly_two_daily_london_triggers_and_unchanged_settings():
    root = task()
    trig = root.findall("t:Triggers/t:CalendarTrigger", NS)
    assert len(trig) == 2 and len(list(root.find("t:Triggers", NS))) == 2
    assert [tr.find("t:StartBoundary", NS).text for tr in trig] == ["2026-10-20T00:15:00", "2026-10-20T06:30:00"]
    assert [tr.find("t:EndBoundary", NS).text for tr in trig] == ["2026-11-18T12:00:00", "2026-11-17T12:00:00"]
    execs = root.findall("t:Actions/t:Exec", NS)
    assert len(execs) == 1
    assert execs[0].find("t:Command", NS).text == r"C:\workspace\TalonX\.venv\Scripts\python.exe"
    args = execs[0].find("t:Arguments", NS).text
    assert args == (r"-m talonx_paperperf.post_delivery_collector --config C:\workspace\TalonX\docs\research"
                    r"\protocols\POST_DELIVERY_ALERT_MARKOUT_V1_APPROVED_CONFIG.json --enable --budget-s 900")
    assert execs[0].find("t:WorkingDirectory", NS).text == r"C:\workspace\TalonX"
    st = root.find("t:Settings", NS)
    assert st.find("t:MultipleInstancesPolicy", NS).text == "IgnoreNew"           # no concurrent fetchers
    assert st.find("t:ExecutionTimeLimit", NS).text == "PT30M"
    assert st.find("t:DisallowStartIfOnBatteries", NS).text == "true"
    assert st.find("t:Enabled", NS).text == "false"                                # repo copy installs disabled
    assert root.find("t:Principals/t:Principal/t:LogonType", NS).text == "InteractiveToken"


def test_trigger_instants_across_uk_and_us_dst_are_outside_r5_and_inside_the_authorised_period():
    runs = all_runs()
    assert runs[0] == datetime(2026, 10, 19, 23, 15, tzinfo=UTC)                   # first: after session 1 close+60
    assert datetime(2026, 10, 20, 5, 30, tzinfo=UTC) in runs                      # 06:30 BST
    assert datetime(2026, 10, 26, 6, 30, tzinfo=UTC) in runs                      # 06:30 GMT after the UK change
    assert datetime(2026, 11, 2, 0, 15, tzinfo=UTC) in runs                       # after the US change
    assert runs[-1] == datetime(2026, 11, 18, 0, 15, tzinfo=UTC)                  # last permitted invocation
    assert [r for r in runs if r >= ENDPOINT] == [runs[-1]]                       # one reconcile-only run, no 06:30
    assert max(r for r in runs if r.astimezone(C.LONDON).hour == 6) == datetime(2026, 11, 17, 6, 30, tzinfo=UTC)
    assert all(r.date() >= date(2026, 10, 19) for r in runs)
    for r in runs:
        assert Q.r5_permitted(r)
        assert not (r.weekday() < 5 and 13 * 60 <= r.hour * 60 + r.minute < 20 * 60 + 30)   # fixed-UTC R5 form
    for tr in task().findall("t:Triggers/t:CalendarTrigger", NS):                 # latest possible late start
        end = datetime.fromisoformat(tr.find("t:EndBoundary", NS).text).replace(tzinfo=C.LONDON)
        assert Q.r5_permitted(end.astimezone(UTC))


def test_every_session_gets_at_least_four_trigger_chances_before_its_original_deadline():
    runs = all_runs()
    for w in M.study_sessions(date(2026, 10, 19), 20):
        n = sum(M.maturity(w) <= r < M.deadline(w) for r in runs)
        assert n >= 4, w.window_id


def test_scheduled_slot_and_missed_slots_across_the_uk_change(tmp_path):
    assert C.scheduled_for(datetime(2026, 10, 21, 5, 40, tzinfo=UTC)) == datetime(2026, 10, 21, 5, 30, tzinfo=UTC)
    assert C.scheduled_for(datetime(2026, 10, 26, 6, 29, tzinfo=UTC)) == datetime(2026, 10, 26, 0, 15, tzinfo=UTC)
    log = tmp_path / "runs.jsonl"
    log.write_text(json.dumps({"actual_utc": "2026-10-24T23:16:00+00:00"}) + "\n", encoding="utf-8")
    assert C.missed_slots(log, datetime(2026, 10, 26, 0, 20, tzinfo=UTC)) == ["2026-10-25T06:30:00+00:00"]


# ============================================================================================ late start / overlap
def test_late_start_inside_r5_makes_no_request_and_mid_run_r5_stops_cleanly(tmp_path):
    rows = many(6)
    ob, pc = sources(tmp_path, rows)
    blocked = FakeAcq(permit=False)
    r = go(tmp_path, ob, pc, blocked, t(14, 0, d=13))                             # a delayed run woke during R5
    assert blocked.calls == [] and r["acquisition"]["skipped_window"] == r["acquisition"]["due"] == 6

    class R5After(FakeAcq):
        def _gate(self):
            return {"outcome": Q.R5, "detail": "synthetic"} if len(self.calls) > 8 else super()._gate()
    g = acq_for(rows)
    a = go(tmp_path, ob, pc, R5After(g.bars, g.quotes), t(23, 15, d=13))["acquisition"]
    assert a["r5_stopped"] and a["processed"] == 2 and a["deferred"] == 4 and a["errors"] == 0
    assert count(tmp_path, "SELECT COUNT(*) FROM acquisition_errors") == 0


def test_overlapping_trigger_is_refused_by_the_collector_lock(tmp_path):
    ops = tmp_path / "pdm_ops"
    ops.mkdir()
    (ops / "collector.lock").write_text(json.dumps({"pid": 777}), encoding="utf-8")
    r = C.collect(config=LOCKED, enable=True, store=tmp_path / "pdm", budget_s=60, now=t(5, 30, d=13),
                  acquirer=FakeAcq(), lock_alive=lambda pid: pid == 777)
    assert r["state"] == "REFUSED_OVERLAP" and not (tmp_path / "pdm").exists()


def test_added_trigger_processes_pending_work_without_duplicates(tmp_path):
    rows = many(8)
    ob, pc = sources(tmp_path, rows)
    acq = acq_for(rows)
    go(tmp_path, ob, pc, acq, t(23, 15), limit=3)                                 # 00:15 London (BST)
    r = go(tmp_path, ob, pc, acq, t(5, 30, d=13), limit=3)                        # 06:30 London (BST)
    assert r["registered"] == 0 and r["observations_created"] == 0
    assert r["acquisition"]["processed"] == 3 and states(tmp_path) == {M.MEASURED: 6, M.SELECTED_WAITING: 2}
    go(tmp_path, ob, pc, acq, t(23, 15, d=13), limit=3)
    assert states(tmp_path) == {M.MEASURED: 8}
    assert count(tmp_path, "SELECT COUNT(*) FROM observations") == 8 == count(tmp_path, "SELECT COUNT(*) FROM deliveries")
    assert count(tmp_path, "SELECT COUNT(*) FROM inputs") == 32


# ============================================================================================ calendar integrity
def locked():
    return json.loads(LOCKED.read_text(encoding="utf-8"))


def test_calendar_code_is_bound_and_the_deployed_calendar_reproduces_the_locked_table():
    d = locked()
    assert {"talonx_opportunity/phases.py", "talonx_premarket/session.py"} <= set(d["implementation_sha256"])
    assert set(d["implementation_sha256"]) == set(M.IMPLEMENTATION_FILES)
    assert d["calendar_sha256"] == M.calendar_fingerprint("2026-10-19")
    tbl = M.calendar_table("2026-10-19")
    assert d["calendar_table"] == tbl and len(tbl) == 20
    assert tbl[0][0] == "2026-10-19" and tbl[-1][0] == "2026-11-13" and tbl[-1][4] == "2026-11-17T22:00:00+00:00"
    assert set(d["calendar_provenance"]) >= {"exchange_calendars", "tzdata", "python"}
    assert M.verify_integrity(d) == []


def _copy_repo(tmp_path):
    for rel in M.IMPLEMENTATION_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, tmp_path / rel)
    return tmp_path


@pytest.mark.parametrize("rel", ["talonx_opportunity/phases.py", "talonx_premarket/session.py"])
def test_changed_calendar_file_is_refused_before_any_request(tmp_path, rel):
    repo = _copy_repo(tmp_path / "repo")
    f = repo / rel
    f.write_text(f.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    acq = FakeAcq()
    r = C.collect(config=LOCKED, enable=True, store=tmp_path / "pdm", budget_s=60,
                  now=datetime(2026, 10, 20, 23, 15, tzinfo=UTC), acquirer=acq, outbox_path=tmp_path / "o.db",
                  promotion_path=tmp_path / "p.db", trace_path=tmp_path / "t.db", repo=repo,
                  lock_alive=lambda pid: False)
    assert r["state"] == "NOT_APPROVED" and f"IMPLEMENTATION_CHANGED:{rel}" in r["reason"]
    assert acq.calls == [] and not (tmp_path / "pdm").exists()


def test_changed_or_unavailable_calendar_result_is_refused(monkeypatch):
    d = locked()
    assert M.verify_integrity({**d, "calendar_sha256": "0" * 64}) == ["CALENDAR_CHANGED"]
    assert M.verify_integrity({k: v for k, v in d.items() if k != "calendar_sha256"}) == ["CALENDAR_NOT_LOCKED"]
    monkeypatch.setattr(M, "study_sessions", lambda *a: (_ for _ in ()).throw(ImportError("no exchange_calendars")))
    assert M.verify_integrity(d) == ["CALENDAR_UNAVAILABLE:ImportError"]


# ============================================================================================ research unchanged
def test_protocol_sampling_deadlines_costs_and_budgets_are_unchanged():
    d = locked()
    assert d["protocol_fingerprint"] == "c812a3e65e4018a5" == M.PDM_V1.fingerprint()
    p = d["protocol_parameters"]
    assert (p["reaction_delay_s"], p["horizon_min"], p["quote_max_age_s"], p["assumed_additional_cost"],
            p["maturity_lag_min"], p["expiry_sessions"], p["observation_sessions"]) == (300, 30, 60, 0.0005, 60, 2, 20)
    assert d["first_session"] == "2026-10-19" and d["delivery_trace_policy"] == "REQUIRED"
    c = d["collector"]
    assert (c["budget_s"], c["max_observations_per_run"], c["provider_rate_per_min"]) == (900, 200, 40)
    assert [h["kind"].split(" ")[0] for h in d["lock_history"]] == ["OPERATIONAL_CORRECTION", "OPERATIONAL_AMENDMENT"]
    act = M.load_activation(LOCKED, require_integrity=True)
    assert act["endpoint_utc"] == ENDPOINT and act["last_session"] == "2026-11-13"
