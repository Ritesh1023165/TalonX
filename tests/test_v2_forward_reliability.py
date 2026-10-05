"""V2 forward tracker reliability (2026-10-05): classified transient retries, explicit run states, truthful terminal
status, atomic/idempotent stage writes, next-slot scheduling without catch-up. Mocks and fixtures only: the study is
never run and no network is touched."""
from __future__ import annotations

import io
import json
import socket
import ssl
import sys
import urllib.error
from datetime import date, datetime, timezone
from email.message import Message

import pytest

from talonx_paperperf import forward_runner as FR
from talonx_paperperf import transient_http as T

UTC = timezone.utc
HANDSHAKE = urllib.error.URLError(ssl.SSLError("_ssl.c:993: The handshake operation timed out"))


class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def flaky(fails):
    seq = list(fails)

    def fn():
        if seq:
            raise seq.pop(0)
        return "ok"
    return fn


def http_error(code, retry_after=None):
    h = Message()
    if retry_after is not None:
        h["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("https://x/y", code, "err", h, io.BytesIO(b'{"message":"invalid symbol: ZZZ"}'))


# ------------------------------------------------------------------------------------------------ classification
@pytest.mark.parametrize("exc,cls,retry", [
    (HANDSHAKE, "TLS_HANDSHAKE_TIMEOUT", True),
    (urllib.error.URLError(socket.timeout("timed out")), "TIMEOUT", True),
    (ConnectionResetError(10054, "reset"), "CONNECTION", True),
    (http_error(503), "HTTP_503", True),
    (http_error(429, 5), "HTTP_429", True),
    (urllib.error.URLError(ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED")), "TLS_CERTIFICATE", False),
    (http_error(401), "HTTP_401", False),
    (http_error(403), "HTTP_403", False),
    (http_error(400), "HTTP_400", False),
    (ValueError("bad json"), "VALUEERROR", False)])
def test_classification_retries_only_transient_failures(exc, cls, retry):
    c, r, _ = T.classify(exc)
    assert (c, r) == (cls, retry)


def test_transient_failure_then_success():
    ck = Clock()
    acquired = []
    out = T.call_with_retry(flaky([HANDSHAKE, ConnectionResetError()]), sleep=ck.sleep, clock=ck,
                            before_retry=lambda: acquired.append(1))
    assert out == "ok" and ck.sleeps == [2.0, 4.0] and len(acquired) == 2      # limiter re-acquired per retry


def test_retry_exhaustion_within_attempt_and_time_budget():
    ck = Clock()
    with pytest.raises(T.TransientExhausted) as e:
        T.call_with_retry(flaky([HANDSHAKE] * 10), policy=T.RetryPolicy(max_attempts=5), sleep=ck.sleep, clock=ck)
    assert e.value.attempts == 5 and e.value.error_class == "TLS_HANDSHAKE_TIMEOUT"
    assert sum(ck.sleeps) <= T.RetryPolicy().budget_s
    ck2 = Clock()                                                                 # time budget binds before attempts
    with pytest.raises(T.TransientExhausted):
        T.call_with_retry(flaky([HANDSHAKE] * 10), policy=T.RetryPolicy(max_attempts=10, budget_s=10),
                          sleep=ck2.sleep, clock=ck2)
    assert sum(ck2.sleeps) <= 10
    ck3 = Clock()                                                                 # absolute stage deadline binds too
    with pytest.raises(T.TransientExhausted):
        T.call_with_retry(flaky([HANDSHAKE] * 10), deadline=3.0, sleep=ck3.sleep, clock=ck3)
    assert ck3.t <= 3.0


def test_non_retryable_certificate_and_auth_failures_fail_on_first_attempt():
    ck = Clock()
    cert = urllib.error.URLError(ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED"))
    with pytest.raises(urllib.error.URLError):
        T.call_with_retry(flaky([cert]), sleep=ck.sleep, clock=ck)
    with pytest.raises(urllib.error.HTTPError):
        T.call_with_retry(flaky([http_error(401)]), sleep=ck.sleep, clock=ck)
    assert ck.sleeps == []


def test_retry_after_is_honoured_and_never_shortened():
    ck = Clock()
    assert T.call_with_retry(flaky([http_error(429, 7)]), sleep=ck.sleep, clock=ck) == "ok" and ck.sleeps == [7.0]
    ck2 = Clock()
    with pytest.raises(T.TransientExhausted, match="exceeds the cap"):
        T.call_with_retry(flaky([http_error(429, 600)]), sleep=ck2.sleep, clock=ck2)
    assert ck2.sleeps == []


def test_resilient_alpaca_get_keeps_tls_and_the_runtimeerror_contract():
    ck = Clock()
    calls = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"bars": {}}'

    def urlopen(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise HANDSHAKE
        return Resp()
    get = T.resilient_alpaca_get(urlopen=urlopen, sleep=ck.sleep, clock=ck)
    assert get("https://data.alpaca.markets/v2/stocks/bars", {"symbols": "A"}, {}) == {"bars": {}}
    assert len(calls) == 2 and "context" not in T.resilient_alpaca_get.__code__.co_varnames  # no custom TLS context

    def bad(req, timeout):
        raise http_error(400)
    with pytest.raises(RuntimeError, match=r"HTTP 400: .*invalid symbol"):            # fetch_prices parses this
        T.resilient_alpaca_get(urlopen=bad, sleep=ck.sleep, clock=ck)("https://x/v2", {}, {})


# ------------------------------------------------------------------------------------------------ prices stage
def test_prices_stage_partial_failure_keeps_previous_cache_and_resumes_without_duplicates(tmp_path, monkeypatch):
    from talonx_paperperf import v2_validation as V
    monkeypatch.setattr(V, "OUT", tmp_path)
    (tmp_path / "daily_bars.json").write_text(json.dumps({"OLD": [["2026-10-01", 1, 1, 1, 1, 1]]}))
    state = {"fail": True, "calls": []}

    class Data:
        limiter = None

        def _call(self, url, params):
            state["calls"].append(params["symbols"])
            if state["fail"] and len(state["calls"]) > 1:
                raise T.TransientExhausted("x", error_class="TLS_HANDSHAKE_TIMEOUT", attempts=5)
            return {"bars": {s: [{"t": "2026-10-02T04:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]
                             for s in params["symbols"].split(",")}}
    import talonx_paperperf.rs_phase_a as R
    monkeypatch.setattr(R, "_alpaca", lambda n: Data())
    syms = [f"S{i:03d}" for i in range(150)]                                      # 2 batches of 100
    with pytest.raises(T.TransientExhausted):
        V.fetch_prices(syms, date(2026, 9, 1), date(2026, 10, 4))
    kept = json.loads((tmp_path / "daily_bars.json").read_text())
    assert kept == {"OLD": [["2026-10-01", 1, 1, 1, 1, 1]]}                       # intact, valid, no partial merge
    assert not (tmp_path / "daily_bars.json.tmp").exists()
    state.update(fail=False, calls=[])
    V.fetch_prices(syms, date(2026, 9, 1), date(2026, 10, 4))
    after = json.loads((tmp_path / "daily_bars.json").read_text())
    assert set(after) == set(syms) | {"OLD"} and all(len(after[s]) == 1 for s in syms)   # no duplicate bars
    state["calls"] = []
    V.fetch_prices(syms, date(2026, 9, 1), date(2026, 10, 4))
    assert state["calls"] == []                                                   # resumable: nothing re-fetched


# ------------------------------------------------------------------------------------------------ runner states
def _stage(code: str, ok=True):
    return [sys.executable, "-c", code]


@pytest.fixture
def runner_env(tmp_path, monkeypatch):
    monkeypatch.setattr(FR, "OUT", tmp_path)
    monkeypatch.setattr(FR, "RUNS", tmp_path / "forward_runs")
    monkeypatch.setattr(FR, "REPO", tmp_path)
    (tmp_path / "forward").mkdir()
    return tmp_path


def _write_forward(tmp, day):
    p = tmp / "forward" / f"{day}.json"
    return ("import json,pathlib; pathlib.Path(r'%s').write_text(json.dumps({'as_of':'%s','version':'v','freeze':'f',"
            "'episodes_after_freeze':1,'rows':[]}))" % (p, day))


def test_runner_failure_propagates_and_later_stages_never_run(runner_env):
    day = date(2026, 10, 6)
    st = [("edgar_crawl", _stage("pass"), True), ("episodes", _stage("pass"), True),
          ("prices", _stage("import sys; sys.stderr.write('urllib.error.URLError: <urlopen error _ssl.c:993: The "
                            "handshake operation timed out>\\n'); sys.exit(1)"), True),
          ("evaluate", _stage("raise SystemExit('must not run')"), False), ("forward", _stage(_write_forward(runner_env, day)), True)]
    rc = FR.run(scheduled="2026-10-06T06:00:00+00:00", stage_list=st, today=day, log=open(runner_env / "log", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-06.json").read_text())
    assert rc == 2 and rec["state"] == "PARTIAL" and rec["failed_stage"] == "prices"
    assert rec["error_class"] == "TLS_HANDSHAKE_TIMEOUT" and "handshake" in rec["stages"][2]["error"]
    assert [s["state"] for s in rec["stages"]] == ["SUCCESS", "SUCCESS", "FAILED", "NOT_RUN", "NOT_RUN"]
    assert not (runner_env / "forward" / "2026-10-06.json").exists() and rec["artifact"]["validated"] is False
    assert '"state": "PARTIAL"' in (runner_env / "log").read_text()


def test_runner_first_stage_failure_is_failed_and_success_needs_a_validated_artifact(runner_env):
    day = date(2026, 10, 7)
    rc = FR.run(stage_list=[("edgar_crawl", _stage("import sys; sys.exit(3)"), True)], today=day,
                log=open(runner_env / "l1", "w"))
    assert rc == 1 and json.loads((runner_env / "forward_runs" / "2026-10-07.json").read_text())["state"] == "FAILED"
    day = date(2026, 10, 8)                                     # all stages exit 0 but nothing written -> FAILED
    rc = FR.run(stage_list=[("forward", _stage("pass"), True)], today=day, log=open(runner_env / "l2", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-08.json").read_text())
    assert rc == 1 and rec["state"] == "FAILED" and rec["error_class"] == "ARTIFACT_INVALID"
    day = date(2026, 10, 9)
    rc = FR.run(stage_list=[("forward", _stage(_write_forward(runner_env, "2026-10-09")), True)], today=day,
                log=open(runner_env / "l3", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-09.json").read_text())
    assert rc == 0 and rec["state"] == "SUCCESS" and rec["artifact"]["validated"] is True


def test_preexisting_or_wrong_day_artifact_never_counts(runner_env):
    import os
    day = date(2026, 10, 10)
    p = runner_env / "forward" / "2026-10-10.json"
    p.write_text(json.dumps({"as_of": "2026-10-10", "version": "v", "freeze": "f", "episodes_after_freeze": 1,
                             "rows": []}))
    os.utime(p, (1, 1))                                         # an old file: existence alone is no checkpoint
    rc = FR.run(stage_list=[("forward", _stage("pass"), True)], today=day, log=open(runner_env / "l", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-10.json").read_text())
    assert rc == 1 and "NOT_WRITTEN_BY_THIS_RUN" in rec["artifact"]["problems"]


def test_duplicate_runs_are_refused(runner_env):
    day = date(2026, 10, 9)
    FR.run(stage_list=[("forward", _stage(_write_forward(runner_env, "2026-10-09")), True)], today=day,
           log=open(runner_env / "a", "w"))
    marker = runner_env / "ran"
    rc = FR.run(stage_list=[("forward", _stage(f"open(r'{marker}','w')"), True)], today=day, log=open(runner_env / "b", "w"))
    assert rc == 3 and not marker.exists()                      # SUCCESS day: no second run, no stage executed
    (runner_env / "forward_runs").mkdir(exist_ok=True)
    (runner_env / "forward_runs" / "2026-10-05.json").write_text(json.dumps({"state": "PARTIAL",
                                                                              "reconstructed_from_log": True}))
    rc = FR.run(stage_list=[("forward", _stage(f"open(r'{marker}','w')"), True)], today=date(2026, 10, 5),
                log=open(runner_env / "c", "w"))
    assert rc == 3 and not marker.exists()                      # today's failed day is never re-run / backfilled


def test_stage_deadline_stops_a_hung_stage(runner_env):
    day = date(2026, 10, 11)
    rc = FR.run(stage_list=[("prices", _stage("import time; time.sleep(30)"), True)], today=day,
                log=open(runner_env / "l", "w"), budget_s=2)
    rec = json.loads((runner_env / "forward_runs" / "2026-10-11.json").read_text())
    assert rc == 1 and rec["stages"][0]["state"] == "TIMEOUT" and rec["error_class"] == "STAGE_DEADLINE"


def test_next_slot_after_a_failed_run_is_tomorrow_never_an_immediate_catch_up():
    assert FR.next_slot(datetime(2026, 10, 5, 6, 1, 2, tzinfo=UTC)) == datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
    assert FR.next_slot(datetime(2026, 10, 5, 7, 4, tzinfo=UTC)) == datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
    assert FR.next_slot(datetime(2026, 10, 5, 5, 59, tzinfo=UTC)) == datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
    assert FR.next_slot(datetime(2026, 10, 5, 6, 0, tzinfo=UTC)) == datetime(2026, 10, 6, 6, 0, tzinfo=UTC)


def test_sanitize_masks_queries_and_secrets():
    s = FR.sanitize("RuntimeError: GET https://data.alpaca.markets/v2/stocks/bars?symbols=A&page_token=xyz failed\n"
                    "APCA-API-SECRET-KEY leaked bot123456:ABC-def")
    assert "page_token" not in s and "<query>" in s and "ABC-def" not in s


def test_loop_script_logs_true_state_and_sleeps_to_next_slot():
    src = open("docs/research/evidence/2026-09-30_v2_validation/forward_daily_v2.sh", encoding="utf-8").read()
    assert "cycle_done" not in src.replace('old "cycle_done"', "") and '"cycle_end"' in src and '\\"state\\"' in src
    assert "forward_runner run" in src and "sleep-to-next-slot" in src and "date(2026,10,31)" in src
    old = open("docs/research/evidence/2026-09-30_v2_validation/forward_daily.sh", encoding="utf-8").read()
    assert "2026-09-30" in old and "--rate 4" in old                       # original kept for provenance
    stg = FR.stages("py", date(2026, 10, 5))
    assert [s[1][2:] for s in stg] == [["talonx_paperperf.form4_edgar", "2026-09-30", "2026-10-05", "--rate", "4"],
                                       ["talonx_paperperf.v2_validation", "episodes"],
                                       ["talonx_paperperf.v2_validation", "prices"],
                                       ["talonx_paperperf.v2_validation", "evaluate"],
                                       ["talonx_paperperf.v2_validation", "forward"]]   # identical study commands
