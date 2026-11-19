"""EDGAR closure-calendar classification for the V2@1 forward crawler (2026-10-13 acquisition correction).
Fixtures and fakes only: no network, no study run, no outputs."""
from __future__ import annotations

import io
import json
import urllib.error
from datetime import date
from email.message import Message
from pathlib import Path

import pytest

from talonx_paperperf import edgar_calendar as C
from talonx_paperperf import form4_edgar as E
from talonx_paperperf import forward_runner as FR
from tests.test_v2_forward_edgar_cutoff import IDX_HEAD, XML_P, client, edgar_dir, idx_line  # noqa: F401
from tests.test_v2_forward_reliability import _stage, _write_forward, at, runner_env  # noqa: F401

HTTP403 = urllib.error.HTTPError("u", 403, "Forbidden", Message(), io.BytesIO(b""))


def cal_file(tmp_path, closures=(), exceptional=(), years=(2026,)):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps({"calendar_id": "TEST_CAL", "supported_years": list(years),
                             "scheduled_closures": [{"date": d, "name": "x"} for d in closures],
                             "exceptional_closures": [{"date": d, "name": "notice"} for d in exceptional]}),
                 encoding="utf-8")
    return C.EdgarCalendar(p)


def recording_client(responses):
    c = client(responses)
    seen, real = [], c._urlopen

    def spy(req, timeout):
        seen.append(req.full_url)
        return real(req, timeout)
    c._urlopen, c.seen = spy, seen
    return c


def ok_day(day):
    return {f"form.{day:%Y%m%d}.idx": [IDX_HEAD + idx_line(1)], "0001-26-000001.txt": [XML_P]}


# ============================================================================================ the real calendar
def test_shipped_calendar_matches_the_official_2026_closures():
    cal = C.EdgarCalendar()
    assert cal.calendar_id == "EDGAR_CLOSURES_V1" and cal.years == {2026}
    assert sorted(d.isoformat() for d in cal.closures) == [
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
        "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25"]
    assert cal.classify(date(2026, 10, 12)) == C.SEC_CLOSED and cal.classify(date(2026, 10, 13)) == C.EXPECTED
    assert cal.classify(date(2026, 10, 10)) == C.WEEKEND and cal.classify(date(2027, 1, 4)) == C.UNKNOWN
    assert len(cal.sha256) == 64 and cal.provenance()["path"].endswith("EDGAR_CLOSURES_V1.json")
    raw = json.loads(Path(C.CALENDAR_PATH).read_text(encoding="utf-8"))
    assert "XNYS" in raw["not_derived_from"] and raw["exceptional_closures"] == []


# ============================================================================================ crawl behaviour
def test_official_closure_is_sec_closed_without_any_request_or_fake_files(edgar_dir):
    cal = cal_file(edgar_dir.parent, closures=["2026-10-12"])
    c = recording_client({"form.20261012.idx": [HTTP403]})        # would fail if it were requested
    st = E.crawl(date(2026, 10, 12), date(2026, 10, 12), client=c, calendar=cal)
    assert st["state"] == "COMPLETE" and st["days_sec_closed"] == ["2026-10-12"] and c.seen == []
    assert st["days_completed_this_run"] == [] and st["days_index_not_found"] == [] and st["filings_fetched"] == 0
    assert not (edgar_dir / "20261012.done").exists() and not (edgar_dir / "20261012.jsonl").exists()
    assert st["calendar"]["calendar_id"] == "TEST_CAL" and len(st["calendar"]["sha256"]) == 64
    assert json.loads((edgar_dir / "_crawl_status.json").read_text())["days_sec_closed"] == ["2026-10-12"]


def test_normal_filing_day_is_requested_and_403_still_fails(edgar_dir):
    cal = cal_file(edgar_dir.parent, closures=["2026-10-12"])
    c = recording_client({"form.20261013.idx": [HTTP403]})
    st = E.crawl(date(2026, 10, 13), date(2026, 10, 13), client=c, calendar=cal)
    assert st["state"] == "FAILED" and st["cause"] == "EXHAUSTED:HTTP_403" and st["day_interrupted"] == "2026-10-13"
    assert len(c.seen) == 4 and not (edgar_dir / "20261013.done").exists()      # unchanged retry budget


def test_span_with_open_and_closed_days_still_requires_every_expected_index(edgar_dir):
    cal = cal_file(edgar_dir.parent, closures=["2026-10-12"])
    # Fri 10-09 ok, Sat/Sun weekend, Mon 10-12 closed, Tue 10-13 index 403 -> the run still FAILS
    c = recording_client({**ok_day(date(2026, 10, 9)), "form.20261013.idx": [HTTP403]})
    st = E.crawl(date(2026, 10, 9), date(2026, 10, 13), client=c, calendar=cal)
    assert st["state"] == "FAILED" and st["days_completed_this_run"] == ["2026-10-09"]
    assert st["days_sec_closed"] == ["2026-10-12"] and not any("20261012" in u for u in c.seen)
    assert not any("20261010" in u or "20261011" in u for u in c.seen)            # weekends unchanged
    c2 = recording_client({**ok_day(date(2026, 10, 13))})
    st2 = E.crawl(date(2026, 10, 9), date(2026, 10, 13), client=c2, calendar=cal)
    assert st2["state"] == "COMPLETE" and st2["days_already_done"] == ["2026-10-09"]   # checkpoint resume
    assert st2["days_completed_this_run"] == ["2026-10-13"] and st2["days_sec_closed"] == ["2026-10-12"]


def test_unknown_calendar_coverage_fails_before_any_request(edgar_dir):
    cal = cal_file(edgar_dir.parent, years=(2026,))
    c = recording_client({})
    st = E.crawl(date(2026, 12, 31), date(2027, 1, 4), client=c, calendar=cal)
    assert st["state"] == "FAILED" and st["cause"] == "CALENDAR_COVERAGE_UNKNOWN" and c.seen == []
    assert "2027-01-01" in st["error"] and st["requests"] == 0


def test_invalid_calendar_fails_explicitly(edgar_dir, monkeypatch):
    bad = edgar_dir.parent / "bad.json"
    bad.write_text('{"calendar_id": "X"}', encoding="utf-8")
    monkeypatch.setattr(C, "CALENDAR_PATH", bad)
    st = E.crawl(date(2026, 10, 13), date(2026, 10, 13), client=recording_client({}))
    assert st["state"] == "FAILED" and st["cause"] == "CALENDAR_INVALID"


def test_exceptional_closure_uses_the_same_mechanism(edgar_dir):
    cal = cal_file(edgar_dir.parent, exceptional=["2026-10-14"])
    c = recording_client({})
    st = E.crawl(date(2026, 10, 14), date(2026, 10, 14), client=c, calendar=cal)
    assert st["state"] == "COMPLETE" and st["days_sec_closed"] == ["2026-10-14"] and c.seen == []
    assert cal.closures[date(2026, 10, 14)]["kind"] == "exceptional_closures"


def test_conflicting_archived_data_is_preserved_and_stops_for_reconciliation(edgar_dir):
    (edgar_dir / "20261012.jsonl").write_text('{"_acc": "a", "_ok": true, "tx": []}\n', encoding="utf-8")
    (edgar_dir / "20261012.done").write_text('{"filings": 1}', encoding="utf-8")
    before = {p.name: p.read_bytes() for p in edgar_dir.iterdir()}
    cal = cal_file(edgar_dir.parent, closures=["2026-10-12"])
    c = recording_client({})
    st = E.crawl(date(2026, 10, 12), date(2026, 10, 13), client=c, calendar=cal)
    assert st["state"] == "FAILED" and st["cause"] == "CALENDAR_CONFLICT" and "2026-10-12" in st["error"]
    assert c.seen == [] and {p.name: p.read_bytes() for p in edgar_dir.iterdir() if p.name in before} == before


def test_closure_never_becomes_index_not_found_or_fetched_empty(edgar_dir):
    cal = cal_file(edgar_dir.parent, closures=["2026-10-12"])
    st = E.crawl(date(2026, 10, 12), date(2026, 10, 12), client=recording_client({}), calendar=cal)
    assert st["acquisition_result"] == "COMPLETE_ZERO_EVENTS"       # window result is from DONE days only
    assert st["days_index_not_found"] == [] and st["filings_not_found"] == 0
    rows, cov = E.load("2026-10-12", "2026-10-12")
    assert rows == [] and cov["days"] == []                          # no fake day in coverage


def test_404_policy_on_expected_day_is_unchanged(edgar_dir):
    cal = cal_file(edgar_dir.parent)
    st = E.crawl(date(2026, 10, 13), date(2026, 10, 13), client=recording_client({}), calendar=cal)  # default 404
    assert st["days_index_not_found"] == ["2026-10-13"] and not (edgar_dir / "20261013.done").exists()


# ============================================================================================ runner integration
def test_closure_does_not_suppress_the_scheduled_run_and_provenance_reaches_the_run_record(runner_env, monkeypatch):
    """The forward run still happens on a closure-affected day; the crawl's calendar fields are copied into the
    operational run record."""
    day = date(2026, 10, 14)
    crawl_status = runner_env / "edgar" / "_crawl_status.json"
    code = ("import json,os,pathlib; p=pathlib.Path(r'%s'); p.parent.mkdir(exist_ok=True); p.write_text(json.dumps("
            "{'run_id':os.environ['TALONX_FWD_RUN_ID'],'state':'COMPLETE','acquisition_result':'COMPLETE_WITH_EVENTS',"
            "'end':os.environ['TALONX_FWD_INFO_CUTOFF'],'cause':None,'days_sec_closed':['2026-10-12'],"
            "'calendar':{'calendar_id':'EDGAR_CLOSURES_V1','sha256':'abc','supported_years':[2026]}}))" % crawl_status)
    st = [("edgar_crawl", _stage(code), True), ("forward", _stage(_write_forward(runner_env, day.isoformat())), True)]
    rc = FR.run(stage_list=st, today=day, now_fn=at(day), log=open(runner_env / "log", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-14.json").read_text())
    assert rc == 0 and rec["state"] == "SUCCESS" and rec["runner_version"].startswith("forward_runner v1.2")
    acq = rec["stages"][0]["acquisition"]
    assert acq["days_sec_closed"] == ["2026-10-12"] and acq["calendar"]["calendar_id"] == "EDGAR_CLOSURES_V1"


def test_cutoffs_are_unchanged_by_the_calendar(runner_env):
    day = date(2026, 10, 14)
    FR.run(stage_list=[("forward", _stage("pass"), True)], today=day, now_fn=at(day), log=open(runner_env / "l", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-14.json").read_text())
    assert rec["cutoffs"]["info_cutoff_filing_date_max"] == "2026-10-13"
    assert rec["cutoffs"]["price_end_last_completed_session"] == "2026-10-13"
