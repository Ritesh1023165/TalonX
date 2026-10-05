"""END-TO-END fixtures for the ERM nominee PRODUCTION acquisition (verification C).

The PRODUCTION orchestration runs for real: workflow.run_validation -> acquisition.acquirer.ProductionAcquirer (S1..S8,
frozen data.Downloader for bars) -> ProductionLoader -> V2.1 builder -> outcomes -> gates -> report -> marker. Only the
provider transport is substituted (FixtureProvider wrapped in the production RetryingTransport) and the guard is a
ReleasedGuard activated in a TEMPORARY release store from TEMPORARY lock / decision / GO records. The synthetic world
lies in window B dates; no real validation-window input is requested, read or counted. Owner choices in the fixture
(DECIDED) exercise a proposed configuration; they approve nothing.
"""
import gzip
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from research.erm_nominee_validation import adapters as A, release as RL, workflow as W
from research.erm_nominee_validation.acquisition import states as S
from research.erm_nominee_validation.acquisition import acquirer as AQ
from research.erm_nominee_validation.acquisition.acquirer import ProductionAcquirer
from research.erm_nominee_validation.acquisition.guards import AcquisitionRefused, DevelopmentAcquisitionGuard
from research.erm_nominee_validation.acquisition.period import PERIODS, scope_envelopes
from research.erm_nominee_validation.acquisition.store import ArchiveStore
from research.erm_nominee_validation.acquisition.transport import (HttpTransport, OffHoursRefusal, Response,
                                                                   RetryingTransport, TransportExhausted, req)
from research.erm_nominee_validation.config import HYPOTHESIS, OwnerDecisionPending, OwnerDecisions, ValidationConfig
from research.erm_nominee_validation.guard import GuardReleaseNotAuthorised, ValidationGuard

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "docs/research/preregistration/rs_sector_mapping_v1.json"
REAL_GUARD_STATE = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1\guard_state.json")
DECIDED = OwnerDecisions(window="B", task75_reserve_acknowledged=True, min_sample_floor_adopted=True, etf_cost_bps=4,
                         procedural_amendments_approved=True, decision_record="fixture -- approves nothing")
CFG = ValidationConfig("B", DECIDED)
DD = date(2026, 10, 5)                                   # fixture download date
OFF_HOURS = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
N_SYM = 70
ETFS = ("SPY", "XLE", "XBI", "XLV", "XLK", "XLI", "XLF")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


GUARD_BEFORE = sha(REAL_GUARD_STATE) if REAL_GUARD_STATE.exists() else None


# ------------------------------------------------------------------------------------------------ synthetic world
def sessions():
    out, d = [], date(2023, 11, 1)
    while len(out) < 180:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def ts(d):
    return datetime(d.year, d.month, d.day, 5, 0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def world():
    ss, bars = sessions(), {}
    for k in range(N_SYM):
        sym = "S" + chr(65 + k // 26) + chr(65 + k % 26)
        p, vol, rows, decline = 10.0 + 0.12 * k, 3_000_000 + 7919 * k, [], {}
        gaps = {45 + (k % 50), 105 + (k % 50)}
        for i, d in enumerate(ss):
            o = p
            if i in gaps:
                o = p * 1.12
                for j in range(1, 12):
                    decline[i + j] = 0.97 ** (1 / 11)
            c = o * decline.get(i, 1.0)
            rows.append((d, o, max(o, c) * 1.001, min(o, c) * 0.999, c, vol))
            p = c
        bars[sym] = rows
    for etf in ETFS:
        bars[etf] = [(d, 100.0, 100.1, 99.9, 100.0, 50_000_000) for d in ss]
    return ss, bars


SS, BARS = world()
STOCKS = sorted(s for s in BARS if s not in ETFS)
CIK = {s: str(1000 + i).zfill(10) for i, s in enumerate(STOCKS)}


def zip_tsv(rows):
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("SUBMISSION.TSV", "ACCESSION_NUMBER\tFILING_DATE\tISSUERCIK\tISSUERTRADINGSYMBOL\n" + "".join(rows))
    return zb.getvalue()


def page_doc(rows):
    """rows: [(filingDate, form, accession)] -> SEC history-page columns."""
    return {"filingDate": [r[0] for r in rows], "form": [r[1] for r in rows], "accessionNumber": [r[2] for r in rows],
            "items": [""] * len(rows), "reportDate": [""] * len(rows),
            "acceptanceDateTime": [r[0] + "T16:00:00.000Z" for r in rows]}


class FixtureProvider:
    """Answers every production request for the synthetic world. `faults`: request-key substring -> list of actions
    consumed per call ('429', '503', 'conn', 'malformed', '404', 'ok'); `bar_page` = bars per page (pagination)."""

    def __init__(self, faults=None, bar_page=4000, ca_pages=2, sp_last="2026-10-02", f345_404=(), mutate=None,
                 files=None, page_overrides=None):
        self.faults = {k: list(v) for k, v in (faults or {}).items()}
        self.bar_page, self.ca_pages, self.sp_last, self.f345_404 = bar_page, ca_pages, sp_last, set(f345_404)
        self.mutate = mutate or {}                  # url substring -> fn(body) -> body (broader / repaginated responses)
        self.files = files                          # cik -> [(name, filingFrom, filingTo, rows)] advertised history pages
        self.page_overrides = page_overrides or {}  # page name -> rows actually served (repagination)
        self.calls = []

    def sp_csv(self):
        return f"date,tickers\n2023-12-29,SAA\n2024-01-02,SAA\n{self.sp_last},SAA\n".encode()

    def fault(self, key):
        for k, acts in self.faults.items():
            if k in key and acts:
                return acts.pop(0)
        return None

    def fetch(self, r):
        self.calls.append(r.key)
        f = self.fault(r.key + r.url)
        if f == "429":
            return Response(429, b"")
        if f == "503":
            return Response(503, b"")
        if f == "conn":
            raise ConnectionError("fixture connection reset")
        if f == "404":
            return Response(404, b"")
        body = self.body(r)
        for k, fn in self.mutate.items():
            if k in r.key + r.url:
                body = fn(body)
        if f == "malformed":
            body = body[: len(body) // 2]
        return Response(200, body)

    def body(self, r):
        p, u = dict(r.params), r.url
        if r.provider == "alpaca_bars":
            syms = p["symbols"].split(",")
            flat = [(s, row) for s in syms for row in BARS.get(s, [])]
            i = int(p.get("page_token") or 0)
            chunk, nxt = flat[i:i + self.bar_page], (str(i + self.bar_page) if i + self.bar_page < len(flat) else None)
            out = {}
            for s, (d, o, h, l, c, v) in chunk:
                out.setdefault(s, []).append({"t": ts(d), "o": o, "h": h, "l": l, "c": c, "v": v})
            return json.dumps({"bars": out, "next_page_token": nxt}).encode()
        if u.endswith("/v2/assets"):
            return json.dumps([{"symbol": s, "exchange": "NYSE", "name": f"{s} Inc", "status": "active"}
                               for s in STOCKS] if p["status"] == "active" else []).encode()
        if "corporate-actions" in u:
            page = int(p.get("page_token") or 0)
            ca = {}
            if p["types"] == "cash_dividend" and page == 0 and p["start"] <= "2024-03-15" <= p["end"]:
                ca = {"cash_dividends": [{"symbol": "XLK", "ex_date": "2024-03-15", "process_date": "2024-03-15"}]}
            nxt = str(page + 1) if page + 1 < self.ca_pages else None
            return json.dumps({"corporate_actions": ca, "next_page_token": nxt}).encode()
        if u.endswith("company_tickers.json"):
            return json.dumps({str(i): {"cik_str": int(CIK[s]), "ticker": s, "title": f"{s} Inc"}
                               for i, s in enumerate(STOCKS)}).encode()
        if u.endswith("cik-lookup-data.txt"):
            return "".join(f"{s} INC:{CIK[s]}:\n" for s in STOCKS).encode("latin-1")
        if u.endswith("_form345.zip"):
            q = u.rsplit("/", 1)[-1].split("_")[0]
            if q in self.f345_404:
                return b""
            rows = [f"x{i}\t01-OCT-2023\t{int(CIK[s])}\t{s}\n" for i, s in enumerate(STOCKS)] if q == "2023q4" else []
            return zip_tsv(rows)
        if "/full-index/" in u:
            y, qq = u.split("/full-index/")[1].split("/")[:2]
            m = 3 * int(qq[-1]) - 1
            return ("CIK|Company Name|Form Type|Date Filed|Filename\n" + "".join(
                f"{int(CIK[s])}|{s} Inc|10-Q|{y}-{m:02d}-01|x\n" for s in STOCKS)).encode("latin-1")
        if "/submissions/" in u and "-submissions-" in u:                  # an advertised history page
            name = u.rsplit("/", 1)[-1]
            rows = self.page_overrides.get(name)
            if rows is None:
                rows = next(p[3] for ps in (self.files or {}).values() for p in ps if p[0] == name)
            return json.dumps(page_doc(rows)).encode()
        if "/submissions/" in u:
            c = u.rsplit("CIK", 1)[1].split(".")[0]
            s = next(x for x, v in CIK.items() if v == c)
            adv = [{"name": n, "filingCount": len(rw), "filingFrom": a, "filingTo": b}
                   for n, a, b, rw in (self.files or {}).get(c, [])]
            return json.dumps({"cik": c, "name": f"{s} Inc", "tickers": [s], "sic": "3571", "formerNames": [],
                               "filings": {"recent": {
                                   "filingDate": ["2024-05-01", "2024-02-01", "2023-08-01"],
                                   "form": ["10-Q", "10-Q", "10-Q"],
                                   "accessionNumber": [f"0000000001-24-{c[-4:]}2", f"0000000001-24-{c[-4:]}1",
                                                       f"0000000001-23-{c[-4:]}0"],
                                   "items": ["", "", ""], "reportDate": ["2024-03-31", "2023-12-31", "2023-06-30"],
                                   "acceptanceDateTime": ["2024-05-01T16:00:00.000Z"] * 3},
                                   "files": adv}}).encode()
        if u.endswith("-index-headers.html"):
            return b"<html>STANDARD INDUSTRIAL CLASSIFICATION: ELECTRONIC COMPUTERS [3571]\n</html>"
        if u.endswith("/contents"):
            b = self.sp_csv()
            return json.dumps([{"name": "README.md", "sha": "x", "size": 1, "download_url": "https://raw.example/r"},
                               {"name": AQ.SP500_FILE, "sha": AQ.ProductionAcquirer.git_blob_sha(b), "size": len(b),
                                "download_url": "https://raw.example/sp500.csv"}]).encode()
        if u == "https://raw.example/sp500.csv":
            return self.sp_csv()
        raise AssertionError(f"unexpected fixture request {u}")


# ------------------------------------------------------------------------------------------------ fixture release
def write_records(root: Path, cfg=CFG, **go_over):
    d = root / "docs/research/preregistration"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ERM_NOMINEE_PROTOCOL_LOCK.json").write_text(json.dumps({"fixture": "protocol lock"}))
    (d / f"ERM_NOMINEE_OWNER_DECISIONS_{cfg.window_id}.json").write_text(json.dumps({"fixture": "decisions"}))
    cur = RL.current_hashes(cfg, root)
    r = make_request(cfg, cur)
    go = {"owner_go": True, "hypothesis": r.hypothesis, "window_id": r.window_id, "config_hash": r.config_hash,
          "protocol_lock_sha256": r.protocol_lock_sha256, "implementation_sha256": r.implementation_sha256,
          "scope": r.scope}
    go.update(go_over)
    (d / f"ERM_NOMINEE_VALIDATION_GO_{cfg.window_id}.json").write_text(json.dumps(go))
    return RL.current_hashes(cfg, root)


def make_request(cfg, cur, **over):
    kw = dict(hypothesis=HYPOTHESIS, window_id=cfg.window_id, config_hash=cfg.config_hash(),
              protocol_lock_sha256=cur["protocol_lock_sha256"] or "", implementation_sha256=cur["implementation_sha256"],
              owner_decisions_sha256=cur["owner_decisions_sha256"] or "", go_record_sha256=cur["go_record_sha256"] or "",
              download_date=DD.isoformat(), scope=scope_envelopes(PERIODS[cfg.window_id], DD))
    kw.update(over)
    return RL.ReleaseRequest(**kw)


def released(tmp_path, cfg=CFG):
    cur = write_records(tmp_path / "root", cfg)
    r = make_request(cfg, cur)
    g = RL.activate(RL.ReleaseStore(tmp_path / "store"), r, cfg, cur)
    return g, r


def auth(r, cfg=CFG, **over):
    a = {"hypothesis": HYPOTHESIS, "window_id": cfg.window_id, "config_hash": cfg.config_hash(), "owner_go": True,
         "release_id": r.release_id}
    a.update(over)
    return a


NOW = datetime(2026, 10, 5, 21, 0, tzinfo=timezone.utc)          # acquisition session on the reference date DD


def components(guard, provider, *, clock=lambda: NOW, reference=DD):
    acq = ProductionAcquirer(guard, RetryingTransport(provider), bars_clock=lambda: OFF_HOURS,
                             bars_sleep=lambda s: None, reference_date=reference, clock=clock)
    return W.Components(guard=guard, acquirer=acq, loader=A.ProductionLoader(guard, MAPPING))


def ledger(run):
    return [json.loads(x) for x in (run / "archive/acquisition/ledger.jsonl").read_text().splitlines()]


@pytest.fixture(autouse=True)
def real_guard_state_untouched():
    yield
    if GUARD_BEFORE:
        assert sha(REAL_GUARD_STATE) == GUARD_BEFORE, "the real ERM guard state changed"


# ------------------------------------------------------------------------------------------------ success
def test_success_through_report_and_marker_with_staging_order(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider()
    run = tmp_path / "run"
    rec = W.run_validation(CFG, auth(r), components(g, prov), run)
    assert rec["status"] == "COMPLETE" and (run / "RUN_COMPLETE.json").exists() and (run / "report.md").exists()
    st = json.loads((run / "archive/acquisition/acquisition_status.json").read_text())
    assert st["complete"] and not st["required_failures"] and st["etf_cash_dividends"] == "USABLE"
    led = ledger(run)
    assert all(x["state"] == S.USABLE for x in led) and all(x["sha256"] for x in led)
    assert all(x["retrieved_utc"] and x["category"] and x["url"] for x in led)
    # staging: S1/S2 metadata -> bars -> S5 headers; candidate events carry no outcome field
    cats = [x["category"] for x in led]
    first_bar = prov.calls.index(next(k for k in prov.calls if '"alpaca_bars"' in k))
    assert all('"alpaca_bars"' not in k for k in prov.calls[:first_bar])
    assert "assets_current" in cats[:5] and cats[-1] == "etf_cash_dividends"
    ev = json.loads((run / "archive/acquisition/candidate_events.json").read_text())["events"]
    assert ev and set(ev[0]) == {"group", "symbol", "gap_day", "entry", "issuer", "identity"}
    man = json.loads((run / "archive/ARCHIVE_MANIFEST.json").read_text())
    assert man["complete"] and {"bars", "form345", "filing_headers", "sp500_pit"} <= {f["input"] for f in man["files"]}
    sp = (run / "archive/sp500.csv").read_text()
    assert "2026-10-02" not in sp and "2024-01-02" in sp            # rows beyond the scope end never materialised
    assert json.loads((run / "gates.json").read_text())["gates"]["n_valid"] >= 100


def test_bars_and_corporate_actions_paginate(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(bar_page=900, ca_pages=3)
    run = tmp_path / "run"
    W.run_validation(CFG, auth(r), components(g, prov), run)
    pages = json.loads((run / "archive/bars/KEPT/manifest.json").read_text())["files"]
    assert len([f for f in pages if f["purpose"] == "RETURNS"]) > 10
    assert sum(1 for k in prov.calls if "corporate-actions" in k and '"page_token","2"' in k) >= 3


def test_truncated_pagination_is_malformed_not_empty(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(faults={'"page_token","1"': ["malformed"]})
    run = tmp_path / "run"
    with pytest.raises(W.StageFailure) as e:
        W.run_validation(CFG, auth(r), components(g, prov), run)
    assert isinstance(e.value.cause, S.AcquisitionFailure)
    st = json.loads((run / "archive/acquisition/acquisition_status.json").read_text())
    assert st["stage"] == "S1_BASE" and any(f["state"] == S.MALFORMED for f in st["required_failures"])
    assert not any('"alpaca_bars"' in k for k in prov.calls)          # stopped before bars
    assert json.loads((run / "run_record.json").read_text())["outcome_exposure"] is False


# ------------------------------------------------------------------------------------------------ retries / failures
def test_rate_limit_retried_then_succeeds(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(faults={"company_tickers": ["429", "429"], '"alpaca_bars"': ["429", "conn"]})
    rec = W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    assert rec["status"] == "COMPLETE"
    t = [x for x in ledger(tmp_path / "run") if x["url"].endswith("company_tickers.json")]
    assert t[-1]["attempts"] == 3 and t[-1]["state"] == S.USABLE


def test_exhausted_retries_are_transport_failure_never_absence(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(faults={"company_tickers": ["503"] * 4})
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    t = [x for x in ledger(tmp_path / "run") if x["url"].endswith("company_tickers.json")]
    assert t[-1]["state"] == S.TRANSPORT and t[-1]["path"] is None
    assert not (tmp_path / "run/archive/candidates.json").exists()      # no empty universe was written


def test_bars_transport_failure_stops_before_events(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(faults={'"alpaca_bars"': ["503"] * 4})
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    st = json.loads((tmp_path / "run/archive/acquisition/acquisition_status.json").read_text())
    assert st["stage"] == "S3_BARS" and not (tmp_path / "run/archive/acquisition/candidate_events.json").exists()


def test_malformed_submissions_is_required_failure(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(faults={"CIK0000001003.json": ["malformed"]})
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    st = json.loads((tmp_path / "run/archive/acquisition/acquisition_status.json").read_text())
    assert st["stage"] == "S2_SCOPE" and st["required_failures"][0]["state"] == S.MALFORMED
    assert any(x["path"] and x["path"].startswith("acquisition/malformed/") for x in ledger(tmp_path / "run"))


def test_incomplete_sp500_coverage_rejected(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(sp_last="2026-06-30")                       # last membership row before 2026-09-30
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    st = json.loads((tmp_path / "run/archive/acquisition/acquisition_status.json").read_text())
    assert st["required_failures"][0]["category"] == "sp500_pit"
    assert st["required_failures"][0]["state"] == S.INSUFFICIENT


def test_sp500_coverage_exactly_at_scope_end_accepted(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(sp_last="2026-09-30")
    assert W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")["status"] == "COMPLETE"


def test_unpublished_form345_quarter_is_insufficient_coverage(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(faults={"2026q3_form345": ["404"]})
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    st = json.loads((tmp_path / "run/archive/acquisition/acquisition_status.json").read_text())
    assert st["required_failures"][0]["state"] == S.INSUFFICIENT


# ------------------------------------------------------------------------------------------------ required vs optional
def test_optional_etf_dividends_failure_recorded_and_run_completes(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(faults={'"cash_dividend"': ["503"] * 4})
    rec = W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    st = json.loads((tmp_path / "run/archive/acquisition/acquisition_status.json").read_text())
    assert rec["status"] == "COMPLETE" and st["optional_failures"] and st["etf_cash_dividends"].startswith("OPTIONAL_FAILED")
    import csv
    rows = list(csv.DictReader(open(tmp_path / "run/manifest.csv", encoding="utf-8")))
    assert {x["sens_etf_cash_dividend_leg"] for x in rows if x["v2_status"] == "VALID"} <= {"UNKNOWN", "NO_ADJUSTMENT"}


def test_header_404_is_legitimate_absence_under_frozen_policy(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(faults={"-index-headers.html": ["404"] * 1000})
    rec = W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    st = json.loads((tmp_path / "run/archive/acquisition/acquisition_status.json").read_text())
    assert rec["status"] == "COMPLETE" and st["legitimate_absences"]
    import csv
    rows = list(csv.DictReader(open(tmp_path / "run/manifest.csv", encoding="utf-8")))
    # frozen V2.1 instrument rules 5/6 on ABSENT dated SIC: verified S&P member -> OPERATING_SECTOR_UNKNOWN (explicit
    # frozen SPY benchmark); everyone else -> UNRESOLVED_INSTRUMENT (excluded). Recorded, never silent.
    assert all(x["sic_source"] == "HEADER_NOT_ARCHIVED" for x in rows if x["issuer"])
    assert all(x["v2_status"] != "VALID" for x in rows if x["sp_evidence"] != "VERIFIED")
    assert all(x["benchmark_v2"] == "SPY" for x in rows if x["v2_status"] == "VALID")
    assert any(x["first_reason"] == "INSTRUMENT_UNRESOLVED" for x in rows)


def test_required_header_transport_failure_stops(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(faults={"-index-headers.html": ["503"] * 4})
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    assert json.loads((tmp_path / "run/run_record.json").read_text())["status"] == "INCOMPLETE_ACQUIRE"


# ------------------------------------------------------------------------------------------------ resume / revisions
def test_resume_without_duplicate_requests_or_replaced_bytes(tmp_path):
    g, r = released(tmp_path)
    arc = tmp_path / "arc"
    p1 = FixtureProvider(faults={"-index-headers.html": ["503"] * 4})
    with pytest.raises(S.AcquisitionFailure):
        components(g, p1).acquirer.acquire(CFG, arc)
    done = {json.loads(x)["request_key"] for x in (arc / "acquisition/ledger.jsonl").read_text().splitlines()
            if json.loads(x)["state"] == S.USABLE}
    before = {p: p.read_bytes() for p in (arc / "sec").glob("*.gz")}
    p2 = FixtureProvider()
    man = components(g, p2).acquirer.acquire(CFG, arc)
    assert man["complete"]
    assert not (set(p2.calls) & done)                                   # nothing USABLE re-requested
    assert all(p.read_bytes() == b for p, b in before.items())          # nothing replaced
    assert not (arc / "bars_incomplete").exists()                       # bars completed in run 1 were kept


def test_partial_bar_group_preserved_and_redone(tmp_path):
    g, r = released(tmp_path)
    arc = tmp_path / "arc"
    p1 = FixtureProvider(bar_page=900, faults={'"page_token","1800"': ["503"] * 4})
    with pytest.raises(S.AcquisitionFailure):
        components(g, p1).acquirer.acquire(CFG, arc)
    assert (arc / "bars/KEPT").exists()
    man = components(g, FixtureProvider(bar_page=900)).acquirer.acquire(CFG, arc)
    assert man["complete"] and (arc / "bars_incomplete/KEPT_1").exists()


def test_revised_bytes_preserved_alongside_earlier(tmp_path):
    st = ArchiveStore(tmp_path)
    rq = req("sec", "https://www.sec.gov/files/company_tickers.json")
    st.record(rq, "sec_reference_current", (None, DD), S.TRANSPORT, detail="first attempt failed")
    a = st.record(rq, "sec_reference_current", (None, DD), S.USABLE, body=b"one", rel_path="sec/x.json.gz")
    b = st.record(rq, "sec_reference_current", (None, DD), S.USABLE, body=b"two", rel_path="sec/x.json.gz")
    assert a["path"] == "sec/x.json.gz" and b["path"].startswith("sec/x.json.gz.rev-")
    assert gzip.decompress((tmp_path / a["path"]).read_bytes()) == b"one"
    assert "REVISION_PRESERVED" in b["detail"] and len((tmp_path / "acquisition/ledger.jsonl").read_text().splitlines()) == 3


# ------------------------------------------------------------------------------------------------ hashes / staleness
def test_archive_hash_mismatch_fails_at_load(tmp_path):
    g, r = released(tmp_path)
    run = tmp_path / "run"
    comps = components(g, FixtureProvider())
    real = comps.acquirer.acquire

    def acquire_then_tamper(cfg, arc):
        m = real(cfg, arc)
        p = arc / "renames.json"
        p.write_bytes(p.read_bytes() + b" ")
        return m
    comps.acquirer.acquire = acquire_then_tamper
    with pytest.raises(W.StageFailure) as e:
        W.run_validation(CFG, auth(r), comps, run)
    assert isinstance(e.value.cause, A.InputHashMismatch)


def test_stale_configuration_rejected(tmp_path):
    g, r = released(tmp_path)
    other = ValidationConfig("B", OwnerDecisions(**{**DECIDED.__dict__, "etf_cost_bps": 12}))
    with pytest.raises(GuardReleaseNotAuthorised):
        RL.load_release(RL.ReleaseStore(tmp_path / "store"), other, RL.current_hashes(other, tmp_path / "root"))
    with pytest.raises(GuardReleaseNotAuthorised):
        W.run_validation(other, auth(r, other), components(g, FixtureProvider()), tmp_path / "run")


@pytest.mark.parametrize("what", ["protocol", "implementation", "go", "decisions"])
def test_changed_hash_after_release_rejected(tmp_path, monkeypatch, what):
    g, r = released(tmp_path)
    d = tmp_path / "root/docs/research/preregistration"
    if what == "protocol":
        (d / "ERM_NOMINEE_PROTOCOL_LOCK.json").write_text("{}")
    elif what == "go":
        (d / "ERM_NOMINEE_VALIDATION_GO_B.json").write_text("{}")
    elif what == "decisions":
        (d / "ERM_NOMINEE_OWNER_DECISIONS_B.json").write_text("{}")
    else:
        monkeypatch.setattr(RL, "implementation_hash", lambda root=RL.HERE: ("changed", {}))
    with pytest.raises(RL.ReleaseInvalid, match="mismatch"):
        RL.load_release(RL.ReleaseStore(tmp_path / "store"), CFG, RL.current_hashes(CFG, tmp_path / "root"))


# ------------------------------------------------------------------------------------------------ release scope
def _scope(**over):
    s = scope_envelopes(PERIODS["B"], DD)
    s.update(over)
    return s


@pytest.mark.parametrize("over,msg", [
    ({"scope": _scope(bars=[["2023-11-01", "2026-12-31"]])}, "WIDER"),
    ({"scope": _scope(bars=[["2024-01-01", "2026-09-30"]])}, "differs"),
    ({"scope": {**_scope(), "eight_k_text": [[None, "2026-09-30"]]}}, "other input categories"),
    ({"scope": {k: v for k, v in _scope().items() if k != "form345"}}, "incomplete scope"),
    ({"hypothesis": "GAP_DOWN_10|LONG|H10|L1"}, "hypothesis"),
    ({"window_id": "A"}, "window"),
    ({"config_hash": "0" * 64}, "config hash"),
])
def test_wrong_scope_release_rejected(tmp_path, over, msg):
    cur = write_records(tmp_path / "root")
    with pytest.raises(RL.ReleaseInvalid, match=msg):
        RL.activate(RL.ReleaseStore(tmp_path / "store"), make_request(CFG, cur, **over), CFG, cur)
    assert not (tmp_path / "store/release_journal.jsonl").exists()


def test_go_record_must_name_this_scope(tmp_path):
    cur = write_records(tmp_path / "root", scope={"bars": [["2023-11-01", "2026-12-31"]]})
    with pytest.raises(RL.ReleaseInvalid, match="GO record"):
        RL.activate(RL.ReleaseStore(tmp_path / "store"), make_request(CFG, cur), CFG, cur)


def test_authorisation_naming_another_release_rejected(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider()
    with pytest.raises(GuardReleaseNotAuthorised):
        W.run_validation(CFG, auth(r, release_id="f" * 64), components(g, prov), tmp_path / "run")
    assert prov.calls == [] and not (tmp_path / "run").exists()


def test_released_guard_refuses_outside_scope(tmp_path):
    g, _ = released(tmp_path)
    g.check_acquisition(date(2023, 11, 1), date(2026, 9, 30), "bars")
    with pytest.raises(AcquisitionRefused):
        g.check_acquisition(date(2023, 11, 1), date(2026, 10, 30), "bars")      # past the window
    with pytest.raises(AcquisitionRefused):
        g.check_acquisition(date(2024, 1, 1), date(2024, 12, 31), "eight_k_text")  # category not released
    g.check_acquisition(date(2019, 1, 1), date(2019, 3, 31), "bars")              # unprotected, released category
    with pytest.raises(AcquisitionRefused):
        g.check_acquisition(date(2019, 1, 1), date(2019, 3, 31), "unknown_category")  # unknown categories never pass


@pytest.mark.parametrize("crash", ["PREPARED", "ERM_AUDIT_WRITTEN", "TASK75_LEDGER_WRITTEN"])
def test_interrupted_transition_fails_closed(tmp_path, crash):
    cur = write_records(tmp_path / "root")
    store = RL.ReleaseStore(tmp_path / "store")
    with pytest.raises(RuntimeError, match="simulated interruption"):
        RL.activate(store, make_request(CFG, cur), CFG, cur, _crash_after=crash)
    with pytest.raises(RL.ReleaseInvalid, match="incomplete"):
        RL.load_release(store, CFG, cur)
    with pytest.raises(RL.ReleaseInvalid, match="already holds"):
        RL.activate(store, make_request(CFG, cur), CFG, cur)                # no second activation / overwrite
    prod = tmp_path / "prod"
    (prod / RL.PRODUCTION_STORE).mkdir(parents=True)
    for x in store.root.iterdir():
        (prod / RL.PRODUCTION_STORE / x.name).write_bytes(x.read_bytes())
    with pytest.raises(RL.ReleaseInvalid, match="incomplete"):
        RL.production_guard(CFG, prod)                                     # production wiring also fails closed


def test_task75_ledger_consistent_and_records_only_erm(tmp_path):
    released(tmp_path)
    t75 = json.loads((tmp_path / "store/task75_reserve_consumption.json").read_text())
    erm = json.loads((tmp_path / "store/erm_guard_release_audit.json").read_text())
    assert t75["release_id"] == erm["release_id"]
    assert [c["reserved_window"] for c in t75["consumed"]] == [["2024-06-01", "2024-09-02"], ["2024-10-21", "2024-12-20"]]
    assert "not modified" in t75["note"]


def test_tampered_audit_record_invalidates_release(tmp_path):
    released(tmp_path)
    p = tmp_path / "store/task75_reserve_consumption.json"
    p.write_text(p.read_text().replace("2024-06-01", "2024-06-02"))
    cur = RL.current_hashes(CFG, tmp_path / "root")
    with pytest.raises(RL.ReleaseInvalid, match="changed"):
        RL.load_release(RL.ReleaseStore(tmp_path / "store"), CFG, cur)


# ------------------------------------------------------------------------------------------------ after outcomes
def test_failure_after_outcomes_no_automatic_retry(tmp_path, monkeypatch):
    from research.erm_nominee_validation import diagnostics as DG
    g, r = released(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("diagnostics failure")
    monkeypatch.setattr(DG, "unit_book", boom)
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, FixtureProvider()), tmp_path / "run")
    rr = json.loads((tmp_path / "run/run_record.json").read_text())
    assert rr["outcome_exposure"] is True and rr["retry_allowed"] is False
    monkeypatch.undo()
    prov = FixtureProvider()
    with pytest.raises(W.RunRefused, match="after outcomes"):
        W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    assert prov.calls == []


# ------------------------------------------------------------------------------------------------ nothing before auth
def test_no_protected_request_before_authorisation(tmp_path):
    prov = FixtureProvider()
    g = ValidationGuard(CFG)
    with pytest.raises(GuardReleaseNotAuthorised):
        W.run_validation(CFG, auth(make_request(CFG, {"implementation_sha256": "x", "protocol_lock_sha256": None,
                                                        "owner_decisions_sha256": None, "go_record_sha256": None})),
                         components(g, prov), tmp_path / "run")
    with pytest.raises(GuardReleaseNotAuthorised):
        components(g, prov).acquirer.acquire(CFG, tmp_path / "arc")
    assert prov.calls == []


def test_production_guard_inactive_and_runner_refuses(tmp_path):
    assert isinstance(RL.production_guard(CFG), ValidationGuard)          # no production release store exists
    assert not (RL.HERE / RL.PRODUCTION_STORE).exists() and not (RL.HERE / RL.PROTOCOL_LOCK).exists()
    cur = RL.current_hashes(CFG)
    assert cur["protocol_lock_sha256"] is None and cur["go_record_sha256"] is None
    from research.erm_nominee_validation import run as RUN
    with pytest.raises(OwnerDecisionPending):
        RUN.main(["--window", "B", "--execute"])
    with pytest.raises(OwnerDecisionPending):
        RL.activate(RL.ReleaseStore(tmp_path / "s"), make_request(ValidationConfig("B"), cur), ValidationConfig("B"), cur)


def test_development_guard_refuses_protected_and_unauthorised_broad():
    g = DevelopmentAcquisitionGuard()
    g.check_acquisition(date(2018, 11, 1), date(2023, 12, 29), "bars")
    for a, b, c in ((date(2023, 11, 1), date(2024, 1, 31), "bars"), (None, DD, "submissions"),
                    (date(2025, 1, 1), date(2025, 12, 31), "identity_renames")):
        with pytest.raises(AcquisitionRefused):
            g.check_acquisition(a, b, c)
    g2 = DevelopmentAcquisitionGuard(authorised_broad=("identity_renames",))
    g2.check_acquisition(date(2025, 1, 1), date(2025, 12, 31), "identity_renames")
    with pytest.raises(AcquisitionRefused):
        g2.check_acquisition(date(2024, 6, 1), date(2024, 9, 2), "identity_renames")   # Task75 reserved window


# ------------------------------------------------------------------------------------------------ live transport policy
class _Resp:
    def __init__(self, status, body=b"", headers=None):
        self.status, self._b, self.headers = status, body, headers or {}

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_transport_off_hours_refusal_before_any_request():
    calls = []
    t = HttpTransport(clock=lambda: datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc), sleep=lambda s: None,
                      opener=lambda r, to: calls.append(r))
    with pytest.raises(OffHoursRefusal):
        t.fetch(req("sec", "https://www.sec.gov/files/company_tickers.json"))
    assert calls == []


def test_http_transport_retry_after_and_exhaustion():
    import urllib.error
    slept, seq = [], []

    def opener(r, to):
        seq.append(1)
        raise urllib.error.HTTPError(r.full_url, 429, "rate", {"Retry-After": "7"}, None)
    t = HttpTransport(clock=lambda: OFF_HOURS, sleep=slept.append, opener=opener)
    with pytest.raises(TransportExhausted):
        t.fetch(req("github", "https://api.github.com/x"))
    assert len(seq) == 4 and slept.count(7.0) == 3


def test_http_transport_404_returned_for_classification():
    import urllib.error

    def opener(r, to):
        raise urllib.error.HTTPError(r.full_url, 404, "nf", {}, io.BytesIO(b""))
    t = HttpTransport(clock=lambda: OFF_HOURS, sleep=lambda s: None, opener=opener)
    assert t.fetch(req("github", "https://api.github.com/x")).status == 404
