"""V2 forward tracker integrity (2026-10-05): EDGAR failure is never an empty sample; run cutoffs are fixed once,
identical for every stage and enforced. Fixtures and fakes only: no network, no study run."""
from __future__ import annotations

import io
import json
import ssl
import sys
import time
import urllib.error
from datetime import date, datetime, timezone
from email.message import Message

import pytest

from talonx_paperperf import form4_edgar as E
from talonx_paperperf import forward_runner as FR

UTC = timezone.utc
REAL_CLIENT = E.Client
HANDSHAKE = urllib.error.URLError(ssl.SSLError("_ssl.c:993: The handshake operation timed out"))
IDX_HEAD = "Form Type   Company Name   CIK   Date Filed   File Name\n" + "-" * 40 + "\n"
XML_P = ("<XML><ownershipDocument><documentType>4</documentType><issuer><issuerCik>1</issuerCik><issuerName>A</issuerName>"
         "<issuerTradingSymbol>AAA</issuerTradingSymbol></issuer><reportingOwner><reportingOwnerId><rptOwnerCik>2"
         "</rptOwnerCik><rptOwnerName>X</rptOwnerName></reportingOwnerId></reportingOwner><nonDerivativeTable>"
         "<nonDerivativeTransaction><transactionDate><value>2026-10-01</value></transactionDate><transactionCoding>"
         "<transactionCode>P</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>100"
         "</value></transactionShares><transactionPricePerShare><value>10</value></transactionPricePerShare>"
         "</transactionAmounts></nonDerivativeTransaction></nonDerivativeTable></ownershipDocument></XML>")


def idx_line(n):
    return f"4          COMPANY {n}          {1000 + n}    20261002    edgar/data/{1000 + n}/0001-26-00000{n}.txt\n"


class Resp:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.text.encode()


def client(responses, *, deadline=None):
    """A Client with the real get() logic and a scripted urlopen (url substring -> list of results)."""
    c = REAL_CLIENT.__new__(REAL_CLIENT)
    c.ua, c.gap, c.last, c.requests, c.deadline = "test", 0.0, 0.0, 0, deadline
    c.sleeps = []
    c._sleep = c.sleeps.append
    script = {k: list(v) for k, v in responses.items()}

    def urlopen(req, timeout):
        for k, seq in script.items():
            if k in req.full_url:
                r = seq.pop(0) if len(seq) > 1 else seq[0]
                if isinstance(r, BaseException):
                    raise r
                return Resp(r)
        raise urllib.error.HTTPError(req.full_url, 404, "nf", Message(), io.BytesIO(b""))
    c._urlopen = urlopen
    return c


@pytest.fixture
def edgar_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "OUT", tmp_path)
    monkeypatch.setenv("TALONX_FWD_RUN_ID", "run-1")
    return tmp_path


D = date(2026, 10, 2)   # a Friday


# ------------------------------------------------------------------------------------------------ EDGAR acquisition
def test_successful_empty_crawl_is_complete_zero_events(edgar_dir):
    st = E.crawl(D, D, client=client({"form.20261002.idx": [IDX_HEAD]}))
    assert st["state"] == "COMPLETE" and st["acquisition_result"] == "COMPLETE_ZERO_EVENTS"
    assert (edgar_dir / "20261002.done").exists() and st["days_completed_this_run"] == ["2026-10-02"]
    m = json.loads((edgar_dir / "_crawl_status.json").read_text())
    assert m["run_id"] == "run-1" and m["end"] == "2026-10-02"


def test_complete_crawl_with_events(edgar_dir):
    st = E.crawl(D, D, client=client({"form.20261002.idx": [IDX_HEAD + idx_line(1)], "0001-26-000001": [XML_P]}))
    assert st["acquisition_result"] == "COMPLETE_WITH_EVENTS" and st["tx_P_S_in_window"] == 1


def test_exhausted_network_retries_fail_and_never_become_an_empty_day(edgar_dir):
    c = client({"form.20261002.idx": [HANDSHAKE]})
    st = E.crawl(D, D, client=c)
    assert st["state"] == "FAILED" and st["cause"] == "EXHAUSTED:TLS_HANDSHAKE_TIMEOUT"
    assert c.requests == 4 and c.sleeps == [1, 2, 4]                       # the unchanged budget, no extra nesting
    assert not (edgar_dir / "20261002.done").exists() and not (edgar_dir / "20261002.jsonl").exists()
    assert E.load()[0] == [] and E.load()[1]["days"] == []                  # nothing counted as acquired


def test_partial_acquisition_keeps_completed_filings_and_resumes_without_duplicates(edgar_dir):
    idx = IDX_HEAD + idx_line(1) + idx_line(2) + idx_line(3)
    st = E.crawl(D, D, client=client({"form.20261002.idx": [idx], "0001-26-000001": [XML_P],
                                      "0001-26-000002": [HANDSHAKE], "0001-26-000003": [XML_P]}))
    assert st["state"] == "FAILED" and st["day_interrupted"] == "2026-10-02"
    lines = (edgar_dir / "20261002.jsonl").read_text().splitlines()
    assert [json.loads(x)["_acc"] for x in lines] == ["0001-26-000001"] and not (edgar_dir / "20261002.done").exists()
    st2 = E.crawl(D, D, client=client({"form.20261002.idx": [idx], "0001-26-00000": [XML_P]}))
    accs = [json.loads(x)["_acc"] for x in (edgar_dir / "20261002.jsonl").read_text().splitlines()]
    assert st2["state"] == "COMPLETE" and accs == ["0001-26-000001", "0001-26-000002", "0001-26-000003"]
    assert all(json.loads(x)["_ok"] for x in (edgar_dir / "20261002.jsonl").read_text().splitlines())


def test_torn_final_line_is_refetched_not_trusted(edgar_dir):
    (edgar_dir / "20261002.jsonl").write_text(json.dumps({"_acc": "0001-26-000001", "_ok": True, "tx": []}) +
                                              '\n{"_acc": "0001-26-0000')            # crash mid-write
    st = E.crawl(D, D, client=client({"form.20261002.idx": [IDX_HEAD + idx_line(1) + idx_line(2)],
                                      "0001-26-00000": [XML_P]}))
    accs = [json.loads(x)["_acc"] for x in (edgar_dir / "20261002.jsonl").read_text().splitlines()]
    assert st["state"] == "COMPLETE" and accs == ["0001-26-000001", "0001-26-000002"]


def test_certificate_and_invalid_request_errors_are_not_retried(edgar_dir):
    cert = urllib.error.URLError(ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED"))
    c = client({"form.20261002.idx": [cert]})
    assert E.crawl(D, D, client=c)["cause"] == "TLS_CERTIFICATE" and c.requests == 1
    bad = urllib.error.HTTPError("u", 400, "bad", Message(), io.BytesIO(b""))
    c = client({"form.20261002.idx": [bad]})
    assert E.crawl(D, D, client=c)["cause"] == "HTTP_400" and c.requests == 1


def test_index_404_keeps_the_preexisting_not_found_policy(edgar_dir):
    st = E.crawl(D, D, client=client({}))                                     # every URL 404
    assert st["state"] == "COMPLETE" and st["days_index_not_found"] == ["2026-10-02"]
    assert not (edgar_dir / "20261002.done").exists()                         # re-tried by a later run, as before


def test_a_backoff_crossing_the_stage_deadline_stops_incomplete(edgar_dir):
    c = client({"form.20261002.idx": [HANDSHAKE]}, deadline=time.monotonic() + 0.5)
    st = E.crawl(D, D, client=c)
    assert st["state"] == "INCOMPLETE" and st["cause"] == "STAGE_DEADLINE" and c.sleeps == []


def test_cli_exit_code_reports_failure_incomplete_and_success(edgar_dir, monkeypatch):
    monkeypatch.setattr(E, "Client", lambda rate: client({"form.20261002.idx": [HANDSHAKE]}))
    assert E.main(["2026-10-02", "2026-10-02", "--rate", "4"]) == 1
    monkeypatch.setattr(E, "Client", lambda rate: client({"form.20261002.idx": [HANDSHAKE]},
                                                        deadline=time.monotonic() + 0.5))
    assert E.main(["2026-10-02", "2026-10-02"]) == 2
    monkeypatch.setattr(E, "Client", lambda rate: client({"form.20261002.idx": [IDX_HEAD]}))
    assert E.main(["2026-10-02", "2026-10-02"]) == 0


# ------------------------------------------------------------------------------------------------ runner integration
def at(day, hh=6, mm=0):
    return lambda: datetime(day.year, day.month, day.day, hh, mm, tzinfo=UTC)


@pytest.fixture
def runner_env(tmp_path, monkeypatch):
    monkeypatch.setattr(FR, "OUT", tmp_path)
    monkeypatch.setattr(FR, "RUNS", tmp_path / "forward_runs")
    monkeypatch.setattr(FR, "REPO", tmp_path)
    (tmp_path / "forward").mkdir()
    (tmp_path / "edgar").mkdir()
    return tmp_path


def py(code):
    return [sys.executable, "-c", code]


def manifest(tmp, state="COMPLETE", run_id="os.environ['TALONX_FWD_RUN_ID']", cause="None", rc=0):
    p = tmp / "edgar" / "_crawl_status.json"
    return py("import json,os,pathlib,sys; pathlib.Path(r'%s').write_text(json.dumps({'run_id':%s,'state':'%s',"
              "'acquisition_result':None,'end':os.environ['TALONX_FWD_INFO_CUTOFF'],'cause':%s,"
              "'error':'/Archives/x: TLS_HANDSHAKE_TIMEOUT after 4 attempts'})); sys.exit(%d)"
              % (p, run_id, state, cause, rc))


def forward_writer(tmp, day):
    p = tmp / "forward" / f"{day}.json"
    return py("import json,pathlib; pathlib.Path(r'%s').write_text(json.dumps({'as_of':'%s','version':'v','freeze':'f',"
              "'episodes_after_freeze':0,'rows':[]}))" % (p, day))


def test_failed_crawl_blocks_every_downstream_stage_and_publication(runner_env):
    day = date(2026, 10, 6)
    st = [("edgar_crawl", manifest(runner_env, "FAILED", cause="'EXHAUSTED:TLS_HANDSHAKE_TIMEOUT'", rc=1), True),
          ("episodes", py("raise SystemExit('must not run')"), True), ("forward", forward_writer(runner_env, day), True)]
    rc = FR.run(stage_list=st, today=day, now_fn=at(day), log=open(runner_env / "l", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-06.json").read_text())
    assert rc == 1 and rec["state"] == "FAILED" and rec["error_class"] == "EDGAR_FAILED:EXHAUSTED:TLS_HANDSHAKE_TIMEOUT"
    assert [s["state"] for s in rec["stages"]] == ["FAILED", "NOT_RUN", "NOT_RUN"]
    assert not (runner_env / "forward" / "2026-10-06.json").exists()
    assert rec["stages"][0]["acquisition"]["state"] == "FAILED"


def test_stale_manifest_or_done_files_never_count_as_this_runs_acquisition(runner_env):
    day = date(2026, 10, 6)
    (runner_env / "edgar" / "20261005.done").write_text("{}")                 # an old completion marker
    st = [("edgar_crawl", manifest(runner_env, run_id="'previous-run'"), True),   # exit 0, but not THIS run
          ("forward", forward_writer(runner_env, day), True)]
    rc = FR.run(stage_list=st, today=day, now_fn=at(day), log=open(runner_env / "l", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-06.json").read_text())
    assert rc == 1 and rec["error_class"] == "EDGAR_STATUS_STALE" and rec["stages"][1]["state"] == "NOT_RUN"
    day = date(2026, 10, 7)                                                    # exit 0 with no manifest at all
    (runner_env / "edgar" / "_crawl_status.json").unlink()
    rc = FR.run(stage_list=[("edgar_crawl", py("pass"), True)], today=day, now_fn=at(day),
                log=open(runner_env / "l2", "w"))
    assert rc == 1 and json.loads((runner_env / "forward_runs" / "2026-10-07.json").read_text())[
        "error_class"] == "EDGAR_STATUS_MISSING"


def test_complete_crawl_then_success_records_invariant_cutoffs(runner_env):
    day = date(2026, 10, 6)
    seen = runner_env / "env.json"
    capture = py("import json,os,pathlib; pathlib.Path(r'%s').open('a').write(json.dumps({k:os.environ[k] for k in "
                 "('TALONX_FWD_INFO_CUTOFF','TALONX_FWD_PRICE_END','TALONX_FWD_AS_OF','TALONX_FWD_RUN_ID')})+'\\n')"
                 % seen)
    st = [("edgar_crawl", manifest(runner_env), True), ("episodes", capture, True), ("prices", capture, True),
          ("forward", forward_writer(runner_env, day), True)]
    rc = FR.run(stage_list=st, today=day, now_fn=at(day), log=open(runner_env / "l", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-06.json").read_text())
    envs = [json.loads(x) for x in seen.read_text().splitlines()]
    assert rc == 0 and rec["state"] == "SUCCESS"
    assert rec["cutoffs"]["info_cutoff_filing_date_max"] == "2026-10-05" == rec["cutoffs"]["price_end_last_completed_session"]
    assert rec["cutoffs"]["as_of"] == "2026-10-06" and envs[0] == envs[1]      # identical for every stage
    assert envs[0]["TALONX_FWD_RUN_ID"] == rec["run_id"]


def test_utc_local_date_gap_fails_instead_of_mixing_cutoffs(runner_env):
    day = date(2026, 10, 6)                          # local (BST) day 10-06 at 23:30Z 10-05: UTC yesterday = 10-04
    marker = runner_env / "ran"
    rc = FR.run(stage_list=[("edgar_crawl", py(f"open(r'{marker}','w')"), True)], today=day,
                now_fn=at(date(2026, 10, 5), 23, 30), log=open(runner_env / "l", "w"))
    rec = json.loads((runner_env / "forward_runs" / "2026-10-06.json").read_text())
    assert rc == 1 and rec["error_class"] == "CUTOFF_DATE_MISMATCH" and not marker.exists()


def test_deadline_is_an_execution_bound_never_past_the_study_day():
    # 06:00Z start -> start + 90 min; a late start is clamped to 23:30 local of the study day
    from datetime import timedelta
    day = date(2026, 10, 6)
    start = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
    eod = datetime.combine(day, datetime.min.time()).astimezone() + timedelta(hours=23, minutes=30)
    assert min(start + timedelta(seconds=FR.RUN_BUDGET_S), eod.astimezone(UTC)) == start + timedelta(minutes=90)
    late = datetime.combine(day, datetime.min.time()).astimezone() + timedelta(hours=23)
    assert min(late.astimezone(UTC) + timedelta(seconds=FR.RUN_BUDGET_S), eod.astimezone(UTC)) == eod.astimezone(UTC)


# ------------------------------------------------------------------------------------------------ stage cutoffs
def test_information_cutoff_excludes_filings_dated_after_it(tmp_path, monkeypatch):
    import pandas as pd
    from talonx_paperperf import v2_validation as V
    hist = tmp_path / "hist.parquet"
    pd.DataFrame([{"issuer_sym": "H", "filing_date": "2026-01-02", "trans_date": "2026-01-01", "code": "P"}]).to_parquet(hist)
    monkeypatch.setattr(V, "HIST", hist)
    monkeypatch.setattr(V, "q2_rows", lambda: [])
    crawled = [{"issuer_sym": "A", "filing_date": "2026-10-05", "code": "P"},
               {"issuer_sym": "B", "filing_date": "2026-10-06", "code": "P"}]
    calls = []
    monkeypatch.setattr(E, "load", lambda start=None, end=None: (calls.append(end), (
        [r for r in crawled if end is None or r["filing_date"] <= end], {"days": [], "filings": 0, "failed": 0}))[1])
    monkeypatch.setenv(V.INFO_CUTOFF_ENV, "2026-10-05")
    rows, _ = V.all_txn_rows()
    assert {r["issuer_sym"] for r in rows} == {"H", "A"} and calls == ["2026-10-05"]
    monkeypatch.delenv(V.INFO_CUTOFF_ENV)
    rows, _ = V.all_txn_rows()                                                 # manual runs: unchanged behaviour
    assert {r["issuer_sym"] for r in rows} == {"H", "A", "B"} and calls[-1] is None


def test_price_end_is_the_last_completed_session_and_invariant(tmp_path, monkeypatch):
    from datetime import timedelta
    from talonx_paperperf import v2_validation as V
    monkeypatch.setattr(V, "OUT", tmp_path)
    (tmp_path / "episodes.json").write_text(json.dumps({"episodes": [{"symbol": "A",
                                                                      "eligible_entry_session": "2026-10-06"}]}))
    got = []
    monkeypatch.setattr(V, "fetch_prices", lambda syms, start, end, refresh=frozenset(): got.append(end))
    monkeypatch.setenv(V.PRICE_END_ENV, "2026-10-05")
    V.main(["prices"])
    monkeypatch.delenv(V.PRICE_END_ENV)
    V.main(["prices"])
    assert got == [date(2026, 10, 5), date.today() - timedelta(days=1)]        # never today's partial session


def test_forward_as_of_is_enforced(tmp_path, monkeypatch):
    from talonx_paperperf import v2_validation as V
    monkeypatch.setattr(V, "OUT", tmp_path)
    monkeypatch.setattr(V, "REPO", tmp_path)
    (tmp_path / "rows.json").write_text("[]")
    monkeypatch.setenv(V.AS_OF_ENV, "2000-01-01")
    with pytest.raises(SystemExit, match="CUTOFF_NOT_ENFORCEABLE"):
        V.forward()
    monkeypatch.setenv(V.AS_OF_ENV, date.today().isoformat())
    assert V.forward()["as_of"] == date.today().isoformat()


def test_todays_missing_run_is_still_never_caught_up(runner_env):
    (runner_env / "forward_runs").mkdir()
    (runner_env / "forward_runs" / "2026-10-05.json").write_text(json.dumps({"state": "PARTIAL",
                                                                              "reconstructed_from_log": True}))
    marker = runner_env / "ran"
    rc = FR.run(stage_list=[("edgar_crawl", py(f"open(r'{marker}','w')"), True)], today=date(2026, 10, 5),
                now_fn=at(date(2026, 10, 5)), log=open(runner_env / "l", "w"))
    assert rc == 3 and not marker.exists()
