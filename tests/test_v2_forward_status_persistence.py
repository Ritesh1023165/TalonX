"""V2@1 forward runner: bounded status-persistence retries, fail-closed stage boundaries, and the read-only dashboard
status view (2026-10-12). Synthetic files, mocked errors and test processes only -- the real study record is never
opened or held, and no study stage is run."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_paperperf import forward_runner as FR
from talonx_paperperf import forward_status as FS
from tests.test_v2_forward_reliability import _ok_crawl, _stage, _write_forward, at, runner_env  # noqa: F401

UTC = timezone.utc


def denied(code=5):
    e = PermissionError(13, "Access is denied")
    e.winerror = code
    return e


class Replacer:
    """os.replace stand-in: fails with the scripted exceptions, then performs the real replace."""
    def __init__(self, *errors):
        self.errors, self.calls = list(errors), []

    def __call__(self, src, dst):
        self.calls.append((Path(src), Path(dst)))
        os.rename(src, Path(src).with_name(Path(src).name + ".closedprobe"))   # fails on Windows if a handle is open
        os.rename(Path(src).with_name(Path(src).name + ".closedprobe"), src)
        if self.errors:
            raise self.errors.pop(0)
        os.replace(src, dst)


# ============================================================================================ write_atomic
def test_transient_denied_then_success_keeps_atomicity_and_reports_history(tmp_path):
    dst = tmp_path / "rec.json"
    dst.write_text('{"state": "OLD"}', encoding="utf-8")
    r, sleeps = Replacer(denied(5), denied(32)), []
    hist = FR.write_atomic(dst, {"state": "NEW"}, replace=r, sleep=sleeps.append)
    assert json.loads(dst.read_text())["state"] == "NEW"
    assert [h["error"] for h in hist] == ["ERROR_ACCESS_DENIED", "ERROR_SHARING_VIOLATION"] and sleeps == [0.05, 0.1]
    assert len({c[0].name for c in r.calls}) == 1 and r.calls[0][0].name.startswith("rec.json.")   # one unique temp
    assert list(tmp_path.glob("*.tmp")) == []                                                      # temp consumed


def test_budget_exhausted_preserves_previous_record_and_removes_only_own_temp(tmp_path):
    dst = tmp_path / "rec.json"
    dst.write_text('{"state": "OLD"}', encoding="utf-8")
    other = tmp_path / "rec.json.999.deadbeef.tmp"                     # another writer's temp file: never touched
    other.write_text("x")
    r, sleeps = Replacer(*[denied(5)] * 20), []
    with pytest.raises(FR.StatusPersistenceError) as ei:
        FR.write_atomic(dst, {"state": "NEW"}, replace=r, sleep=sleeps.append)
    e = ei.value
    assert e.retryable and len(e.history) == len(FR.REPLACE_BACKOFF_S) + 1 == 8
    assert e.history[-1]["stopped"] == "RETRY_BUDGET_EXHAUSTED" and sleeps == list(FR.REPLACE_BACKOFF_S)
    assert sum(sleeps) == pytest.approx(6.35)
    assert json.loads(dst.read_text())["state"] == "OLD"                # last valid record untouched
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rec.json", "rec.json.999.deadbeef.tmp"]


def test_deadline_stops_retrying_honestly(tmp_path):
    dst = tmp_path / "rec.json"
    dst.write_text("{}")
    now = datetime(2026, 10, 13, 7, 29, 59, 980000, tzinfo=UTC)          # the first 0.05 s wait would cross it
    with pytest.raises(FR.StatusPersistenceError) as ei:
        FR.write_atomic(dst, {"a": 1}, deadline=datetime(2026, 10, 13, 7, 30, tzinfo=UTC), now_fn=lambda: now,
                        replace=Replacer(denied(5), denied(5)), sleep=lambda s: None)
    assert ei.value.history[-1]["stopped"] == "RUN_DEADLINE" and len(ei.value.history) == 1


@pytest.mark.parametrize("exc", [FileNotFoundError(2, "no such dir"), OSError(22, "Invalid argument"),
                                 PermissionError(13, "denied (no winerror)")])
def test_permanent_or_unclassified_errors_are_not_retried(tmp_path, exc):
    dst = tmp_path / "rec.json"
    dst.write_text('{"state": "OLD"}')
    sleeps = []
    with pytest.raises(FR.StatusPersistenceError) as ei:
        FR.write_atomic(dst, {"a": 1}, replace=Replacer(exc), sleep=sleeps.append)
    assert not ei.value.retryable and len(ei.value.history) == 1 and sleeps == []
    assert json.loads(dst.read_text())["state"] == "OLD" and list(tmp_path.glob("*.tmp")) == []


def test_serialization_error_writes_nothing_and_is_not_retried(tmp_path):
    dst = tmp_path / "rec.json"
    dst.write_text('{"state": "OLD"}')

    class Bad:
        def __str__(self):
            raise RuntimeError("cannot serialize")
    with pytest.raises(RuntimeError):
        FR.write_atomic(dst, {"x": Bad()})
    assert json.loads(dst.read_text())["state"] == "OLD" and list(tmp_path.glob("*.tmp")) == []


# ============================================================================================ fail-closed run()
def _fail_on(monkeypatch, boundary_index: int, n_fail=99):
    """Make the Nth status write (1-based) fail permanently; earlier/later writes behave normally."""
    real, count = FR.write_atomic, {"n": 0}

    def fake(path, obj, **kw):
        count["n"] += 1
        if count["n"] == boundary_index:
            return real(path, obj, replace=Replacer(*[denied(5)] * n_fail), sleep=lambda s: None,
                        **{k: v for k, v in kw.items() if k != "replace"})
        return real(path, obj, **kw)
    monkeypatch.setattr(FR, "write_atomic", fake)


def stages5(env, day, marks):
    """Five fake stages; each appends its name to ``marks`` so execution is observable."""
    def mk(name, extra=""):
        return _stage(f"import pathlib; pathlib.Path(r'{marks}').open('a').write('{name}\\n'); {extra}")
    return [("edgar_crawl", mk("edgar_crawl", _ok_crawl(env)), True), ("episodes", mk("episodes"), True),
            ("prices", mk("prices"), True), ("evaluate", mk("evaluate"), False),
            ("forward", mk("forward", _write_forward(env, day.isoformat())), True)]


def test_pre_stage_write_failure_prevents_the_stage_and_never_reruns_completed_ones(runner_env, monkeypatch, capsys):
    day, marks = date(2026, 10, 11), runner_env / "marks.txt"
    # writes: 1 START, 2 before edgar, 3 after edgar, 4 before episodes, 5 after, 6 before prices, 7 after,
    #         8 BEFORE evaluate  <- the 2026-10-11 boundary
    _fail_on(monkeypatch, 8)
    rc = FR.run(stage_list=stages5(runner_env, day, marks), today=day, now_fn=at(day), log=open(runner_env / "log", "w"))
    assert rc == 4
    assert marks.read_text().split() == ["edgar_crawl", "episodes", "prices"]          # evaluate never entered
    rec = json.loads((runner_env / "forward_runs" / "2026-10-11.json").read_text())
    assert rec["state"] == "RUNNING" and rec["stages"][2]["state"] == "SUCCESS"         # last VALID record preserved
    assert rec["stages"][3]["state"] == "PENDING"
    diags = list((runner_env / "forward_runs").glob("2026-10-11.*.persistence_failure.*.json"))
    d = json.loads(diags[0].read_text())
    assert len(diags) == 1 and d["boundary"] == "BEFORE_STAGE:evaluate"
    assert d["outcome_exposure"] == "NO_OUTCOME_STAGE_STARTED" and d["observed_stage"] == "prices"
    assert d["automatic_recovery"].startswith("REFUSED") and len(d["persistence_attempts"]) == 8
    assert "STATUS_PERSISTENCE_FAILED" in capsys.readouterr().err
    # the same day is never re-run automatically: the record is RUNNING with a dead pid -> refused
    monkeypatch.setattr(FR, "_live", lambda pid: False)
    assert FR.run(stage_list=stages5(runner_env, day, marks), today=day, now_fn=at(day), log=open(runner_env / "l2", "w")) == 3
    assert marks.read_text().split() == ["edgar_crawl", "episodes", "prices"]


def test_failure_after_outcome_stage_exposure_is_recorded_and_refuses_recovery(runner_env, monkeypatch):
    day, marks = date(2026, 10, 14), runner_env / "marks.txt"
    _fail_on(monkeypatch, 9)                                      # AFTER evaluate completed
    rc = FR.run(stage_list=stages5(runner_env, day, marks), today=day, now_fn=at(day), log=open(runner_env / "log", "w"))
    assert rc == 4 and marks.read_text().split() == ["edgar_crawl", "episodes", "prices", "evaluate"]
    d = json.loads(next((runner_env / "forward_runs").glob("2026-10-14.*.persistence_failure.*.json")).read_text())
    assert d["outcome_exposure"] == "OUTCOME_STAGE_STARTED_OR_WRITTEN:evaluate" and d["boundary"] == "AFTER_STAGE:evaluate"
    assert d["in_memory_stage_states"]["evaluate"] == "SUCCESS" and d["automatic_recovery"].startswith("REFUSED")


def test_transient_failure_recovers_and_is_recorded_in_the_next_write(runner_env, monkeypatch):
    day, marks = date(2026, 10, 15), runner_env / "marks.txt"
    _fail_on(monkeypatch, 8, n_fail=2)                            # two denials, then success
    rc = FR.run(stage_list=stages5(runner_env, day, marks), today=day, now_fn=at(day), log=open(runner_env / "log", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-15.json").read_text())
    assert rc == 0 and rec["state"] == "SUCCESS" and marks.read_text().split()[-2:] == ["evaluate", "forward"]
    assert rec["persistence_retries"][0]["boundary"] == "BEFORE_STAGE:evaluate"
    assert len(rec["persistence_retries"][0]["attempts"]) == 2 and rec["runner_version"] == FR.RUNNER_VERSION
    assert not list((runner_env / "forward_runs").glob("*.persistence_failure.*"))


def test_diagnostic_write_failure_preserves_the_original_failure(runner_env, monkeypatch, capsys):
    day, marks = date(2026, 10, 16), runner_env / "marks.txt"
    _fail_on(monkeypatch, 1)                                      # the START write
    real_open = open

    def guarded_open(f, mode="r", *a, **k):
        if "persistence_failure" in str(f):
            raise OSError(28, "No space left on device")
        return real_open(f, mode, *a, **k)
    monkeypatch.setattr("builtins.open", guarded_open)
    rc = FR.run(stage_list=stages5(runner_env, day, marks), today=day, now_fn=at(day), log=real_open(runner_env / "log", "w"))
    err = capsys.readouterr().err
    assert rc == 4 and not marks.exists()                         # nothing ran
    assert "STATUS_PERSISTENCE_FAILED" in err and "DIAGNOSTIC_WRITE_FAILED" in err
    assert not (runner_env / "forward_runs" / "2026-10-16.json").exists()


def test_unreadable_same_day_record_is_refused_not_overwritten(runner_env):
    day = date(2026, 10, 17)
    p = runner_env / "forward_runs" / "2026-10-17.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json")
    assert FR.run(stage_list=[("forward", _stage("pass"), True)], today=day, now_fn=at(day),
                  log=open(runner_env / "log", "w")) == 3
    assert p.read_text() == "{ not json"


# ============================================================================================ dashboard view
def rec(day, state="RUNNING", pid=4242, start="2026-10-11T06:00:00+00:00", deadline="2026-10-11T07:30:00+00:00", **kw):
    return {"run_id": f"{day}-x", "day": day, "state": state, "pid": pid, "started_utc": start,
            "scheduled_utc": start, "deadline_utc": deadline, "heartbeat_utc": start, "stages":
                [{"name": "prices", "state": "SUCCESS", "exit_code": 0}, {"name": "evaluate", "state": "PENDING"}], **kw}


class PS:
    """psutil stand-in."""
    def __init__(self, exists=True, created=None, cmd="python -m talonx_paperperf.forward_runner run", raise_=None):
        self.exists, self.created, self.cmd, self.raise_ = exists, created, cmd, raise_

    def pid_exists(self, pid):
        return self.exists

    def Process(self, pid):                                                    # noqa: N802
        if self.raise_:
            raise self.raise_
        outer = self

        class P:
            def create_time(self):
                return outer.created.timestamp()

            def cmdline(self):
                return outer.cmd.split()
        return P()


LATE = datetime(2026, 10, 11, 15, 0, tzinfo=UTC)
EARLY = datetime(2026, 10, 11, 6, 5, tzinfo=UTC)
T0 = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize("ps,now,expect", [
    (PS(exists=False), LATE, "ABANDONED"),
    (PS(created=T0 + timedelta(hours=3)), LATE, "ABANDONED"),                 # pid reused by a later process
    (PS(created=T0 - timedelta(seconds=1), cmd="notepad.exe"), LATE, "ABANDONED"),   # not a forward_runner
    (PS(created=T0 - timedelta(seconds=1)), LATE, "OVERDUE_ALIVE"),           # live, deadline passed
    (PS(created=T0 - timedelta(seconds=1)), EARLY, "RUNNING"),
    (PS(exists=False), EARLY, "PROCESS_ABSENT"),
    (PS(raise_=type("AccessDenied", (Exception,), {})()), LATE, "OVERDUE_UNCONFIRMED"),
    (PS(raise_=type("AccessDenied", (Exception,), {})()), EARLY, "UNKNOWN"),
])
def test_derived_state_is_conservative(ps, now, expect):
    d = FS.derive(rec("2026-10-11"), now, ps)
    assert d["recorded_state"] == "RUNNING" and d["observed_state"] == expect


def test_success_needs_the_recorded_validated_flag_and_unknown_states_are_not_healthy():
    assert FS.derive(rec("d", state="SUCCESS", artifact={"validated": True}), LATE)["observed_state"] == "SUCCESS"
    assert FS.derive(rec("d", state="SUCCESS"), LATE)["observed_state"] == "UNKNOWN"
    assert FS.derive(rec("d", state="WEIRD"), LATE)["observed_state"] == "UNKNOWN"


def test_view_marks_abandoned_and_malformed_runs_and_separates_health_from_completeness(tmp_path):
    runs = tmp_path / "results" / "v2_validation" / "forward_runs"
    runs.mkdir(parents=True)
    (runs / "2026-10-10.json").write_text("{ broken")
    (runs / "2026-10-11.json").write_text(json.dumps(rec("2026-10-11", pid=999999)))
    (runs / "2026-10-12.json").write_text(json.dumps(rec("2026-10-12", state="SUCCESS", artifact={"validated": True},
                                                         start="2026-10-12T06:00:00+00:00")))
    (runs / "2026-10-11.json.tmp").write_text("{}")                             # never read as a day record
    out = FS.view(tmp_path, now=datetime(2026, 10, 12, 16, 0, tzinfo=UTC), ps=PS(exists=False))
    by = {r["day"]: r for r in out["runs"]}
    assert set(by) == {"2026-10-10", "2026-10-11", "2026-10-12"}
    assert by["2026-10-10"]["observed_state"] == "UNREADABLE" and by["2026-10-10"]["recorded_state"] == "UNREADABLE"
    assert by["2026-10-11"]["recorded_state"] == "RUNNING" and by["2026-10-11"]["observed_state"] == "ABANDONED"
    assert by["2026-10-11"]["last_stage"]["name"] == "prices"
    assert out["current_health"] == "HEALTHY"                                   # the later run is healthy...
    assert out["incomplete_days_in_view"] == ["2026-10-11", "2026-10-10"]       # ...but history stays visible
    assert out["next_scheduled_run_utc"] == "2026-10-13T06:00:00+00:00"


def test_view_never_opens_outcome_files(tmp_path, monkeypatch):
    runs = tmp_path / "results" / "v2_validation" / "forward_runs"
    runs.mkdir(parents=True)
    (tmp_path / "results" / "v2_validation" / "forward").mkdir()
    (tmp_path / "results" / "v2_validation" / "forward" / "2026-10-12.json").write_text('{"rows": "SECRET OUTCOME"}')
    (runs / "2026-10-12.json").write_text(json.dumps(rec("2026-10-12", state="SUCCESS", artifact={"validated": True,
                                                                                                  "path": "x"})))
    opened = []
    real = Path.read_text

    def spy(self, *a, **k):
        opened.append(str(self))
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", spy)
    out = FS.view(tmp_path, now=LATE, ps=PS(exists=False))
    assert all("forward_runs" in p or p.endswith("forward_daily_v2.sh") for p in opened)
    assert "SECRET" not in json.dumps(out)


def test_cached_view_rate_limits_reads(tmp_path):
    (tmp_path / "results" / "v2_validation" / "forward_runs").mkdir(parents=True)
    t = {"v": 0.0}
    FS._CACHE.clear()
    a = FS.view_cached(tmp_path, clock=lambda: t["v"])
    t["v"] = 30.0
    assert FS.view_cached(tmp_path, clock=lambda: t["v"]) is a                 # within TTL: no re-read
    t["v"] = 61.0
    assert FS.view_cached(tmp_path, clock=lambda: t["v"]) is not a


def test_real_test_process_identity_alive_then_absent():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)  # forward_runner test double"])
    try:
        started = datetime.now(UTC)
        ident, _ = FS.process_identity(p.pid, started)
        assert ident == "ALIVE"
    finally:
        p.kill()
        p.wait()
    time.sleep(0.2)
    assert FS.process_identity(p.pid, started)[0] in ("ABSENT", "PID_REUSED")


def test_dashboard_validation_section_carries_the_forward_view(monkeypatch):
    from talonx_ops import dashboard_read as DR
    sentinel = {"runs": [], "current_health": "NO_RECORDS"}
    monkeypatch.setattr(FS, "view_cached", lambda repo: sentinel)
    src = Path(DR.__file__).read_text(encoding="utf-8")
    assert "_fs.view_cached(" in src and "never opens forward/" in src
    html = (Path(DR.__file__).resolve().parents[1] / "dashboard_web_static" / "index.html").read_text(encoding="utf-8")
    assert "V2@1 forward tracker runs" in html and "r.observed_state" in html and "r.recorded_state" in html
