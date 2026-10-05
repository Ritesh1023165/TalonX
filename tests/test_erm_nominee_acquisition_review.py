"""Final acquisition / release-scope review: focused tests for the named issues (fixtures and synthetic data only).

  * submissions history pages: repagination under an unchanged file name, missing / incomplete pages, complete
    history for every event issuer, accession de-duplication
  * broad / dated responses beyond the authorised envelope -> RUN_INVALID with recorded exposure (fail closed)
  * post-window renames: reconstruction of the series' ticker on D only; no future-assisted admission
  * fixed acquisition reference date: resume cannot expand rename coverage or broad-endpoint content
  * S&P coverage as the FIRST prerequisite (ACQUISITION_BLOCKED before any other request)
  * failure classes (IMPLEMENTATION_FAILURE / ACQUISITION_BLOCKED / RUN_INVALID / after outcome exposure)
No real provider, no protected data, temporary paths only; the real guard state is asserted unchanged after each test.
"""
import gzip
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest

from research.erm_nominee_audit import v2_rules as R
from research.erm_nominee_validation import builder as B, release as RL, workflow as W
from research.erm_nominee_validation.acquisition import states as S
from research.erm_nominee_validation.acquisition.acquirer import ProductionAcquirer
from research.erm_nominee_validation.acquisition.period import (PAGE_RULE_FROZEN_DEV, PAGE_RULE_FULL, PERIODS,
                                                                scope_envelopes)
from tests.test_erm_nominee_acquisition_e2e import (CFG, CIK, DD, GUARD_BEFORE, REAL_GUARD_STATE, FixtureProvider,
                                                    auth, components, ledger, make_request, released, sha,
                                                    write_records, zip_tsv)

SAA = CIK["SAA"]
PAGE = f"CIK{SAA}-submissions-001.json"
OLD_ROWS = [("2010-03-01", "10-K", f"{SAA}-10-000001"), ("2015-03-02", "10-K", f"{SAA}-15-000001"),
            ("2019-05-01", "10-Q", f"{SAA}-19-000001")]


def files(rows=OLD_ROWS, frm="2010-03-01", to="2019-05-01"):
    return {SAA: [(PAGE, frm, to, rows)]}


@pytest.fixture(autouse=True)
def real_guard_state_untouched():
    yield
    if GUARD_BEFORE:
        assert sha(REAL_GUARD_STATE) == GUARD_BEFORE, "the real ERM guard state changed"


def status(run):
    return json.loads((run / "archive/acquisition/acquisition_status.json").read_text())


def record(run):
    return json.loads((run / "run_record.json").read_text())


# ================================================================================================ 2 submissions pages
def test_rule_per_window():
    assert PERIODS["DEV"].submissions_page_rule == PAGE_RULE_FROZEN_DEV
    assert PERIODS["A"].submissions_page_rule == PERIODS["B"].submissions_page_rule == PAGE_RULE_FULL


def test_complete_history_fetched_for_every_event_issuer(tmp_path):
    """SAA's CIK is resolved in S2 (R3 reads only overlapping pages); S5 still fetches its pre-window page."""
    g, r = released(tmp_path)
    prov = FixtureProvider(files=files())
    run = tmp_path / "run"
    assert W.run_validation(CFG, auth(r), components(g, prov), run)["status"] == "COMPLETE"
    h = json.loads((run / "archive/acquisition/issuer_history.json").read_text())[SAA]
    assert h == {"rule": PAGE_RULE_FULL, "main": "USABLE", "pages_required": 1, "pages_verified": 1, "complete": True}
    rows = B.subs_reader([run / "archive/sec"], CFG.end.isoformat())(SAA)
    assert ("2010-03-01", "10-K", f"{SAA}-10-000001", "", "") in rows       # pre-window periodic filing is evidence


@pytest.mark.parametrize("served,why", [
    (OLD_ROWS[1:], "rows"),                                                       # page shrank (repaginated)
    ([("2010-02-01",) + OLD_ROWS[0][1:]] + OLD_ROWS[1:], "first filing"),          # same count, range moved
    (OLD_ROWS[:2] + [("2019-06-03", "10-Q", f"{SAA}-19-000001")], "last filing"),  # ran past filingTo + 1 d
])
def test_repaginated_page_with_unchanged_name_blocks(tmp_path, served, why):
    g, r = released(tmp_path)
    prov = FixtureProvider(files=files(), page_overrides={PAGE: served})
    run = tmp_path / "run"
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), run)
    st, rr = status(run), record(run)
    f = st["required_failures"][0]
    assert f["state"] == S.MALFORMED and "REPAGINATION_OR_INCOMPLETE_PAGE" in f["detail"] and why in f["detail"]
    assert rr["failure_class"] == S.ACQUISITION_BLOCKED and rr["outcome_exposure"] is False
    assert not (run / "manifest.csv").exists()                                   # never an exclusion: no build


def test_page_last_row_one_day_after_advertised_is_accepted(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(files=files(to="2019-04-30"))                        # SEC filingTo lags by <= 1 day
    assert W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")["status"] == "COMPLETE"


def test_missing_advertised_page_is_incomplete_pagination_not_absence(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(files=files(), faults={PAGE: ["404"]})
    run = tmp_path / "run"
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), run)
    st = status(run)
    assert st["required_failures"][0]["state"] == S.MALFORMED
    assert "incomplete pagination" in st["required_failures"][0]["detail"]
    assert not any(PAGE in a["request"] for a in st["legitimate_absences"])


def test_malformed_page_blocks(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(files=files(), faults={PAGE: ["malformed"]})
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    assert status(tmp_path / "run")["required_failures"][0]["state"] == S.MALFORMED


def _subs_dir(tmp_path, page_rows):
    main = {"filings": {"recent": {"filingDate": ["2024-02-01"], "form": ["10-Q"], "accessionNumber": ["A-2"],
                                   "items": [""], "reportDate": [""]},
                        "files": [{"name": "CIKX-submissions-001.json"}]}}
    (tmp_path / "sub_CIKX.json.gz").write_bytes(gzip.compress(json.dumps(main).encode()))
    pg = {"filingDate": [x[0] for x in page_rows], "form": [x[1] for x in page_rows],
          "accessionNumber": [x[2] for x in page_rows], "items": [""] * len(page_rows), "reportDate": [""] * len(page_rows)}
    (tmp_path / "sub_CIKX-submissions-001.json.gz").write_bytes(gzip.compress(json.dumps(pg).encode()))
    return B.subs_reader([tmp_path], "2026-09-30")


def test_identical_duplicate_accession_deduplicated(tmp_path):
    rows = _subs_dir(tmp_path, [("2010-01-04", "10-K", "A-1"), ("2024-02-01", "10-Q", "A-2")])("X")
    assert [r[2] for r in rows] == ["A-1", "A-2"]


def test_conflicting_duplicate_accession_rejected(tmp_path):
    with pytest.raises(ValueError, match="conflicting"):
        _subs_dir(tmp_path, [("2024-02-01", "8-K", "A-2")])("X")


# ================================================================================================ 3 response scope
def _ca_add(row, typ="name_changes"):
    def fn(body):
        j = json.loads(body)
        j["corporate_actions"].setdefault(typ, []).append(row)
        return json.dumps(j).encode()
    return fn


def _main_add(date_):
    def fn(body):
        j = json.loads(body)
        rc = j["filings"]["recent"]
        for k, v in (("filingDate", date_), ("form", "8-K"), ("accessionNumber", "late"), ("items", ""),
                     ("reportDate", ""), ("acceptanceDateTime", date_ + "T16:00:00.000Z")):
            rc[k].insert(0, v)
        return json.dumps(j).encode()
    return fn


def _bars_add(body):
    j = json.loads(body)
    s = next(iter(j["bars"]))
    j["bars"][s].append({"t": "2026-10-01T05:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1})
    return json.dumps(j).encode()


CA24 = '["start","2024-01-01"],["types","name_change"]'
DIV24 = '["start","2024-01-01"],["symbols"'


@pytest.mark.parametrize("mutate,provider_kw,category", [
    ({CA24: _ca_add({"old_symbol": "ZZA", "new_symbol": "ZZB", "process_date": "2025-02-01"})}, {}, "corporate_actions"),
    ({CA24: _ca_add({"old_symbol": "ZZA", "new_symbol": "ZZB", "process_date": "2024-05-01",
                     "announce_date": "2025-01-15"})}, {}, "corporate_actions"),          # unknown date field late
    ({DIV24: _ca_add({"symbol": "XLK", "ex_date": "2024-12-20", "process_date": "2024-12-20",
                                  "payable_date": "2025-03-31"}, "cash_dividends")}, {}, "etf_cash_dividends"),
    ({f"CIK{SAA}.json": _main_add("2026-10-09")}, {}, "submissions"),            # after reference + 1 d
    ({"2024q1_form345": lambda b: zip_tsv([f"x\t15-MAY-2024\t1000\tSAA\n"])}, {}, "form345"),
    ({"-index-headers.html": lambda b: b"FILED AS OF DATE:\t\t20261015\nSTANDARD INDUSTRIAL CLASSIFICATION: X [3571]"},
     {}, "filing_headers"),
    ({}, {"sp_last": "2026-10-09"}, "sp500_pit"),
])
def test_response_beyond_authorised_scope_is_run_invalid(tmp_path, mutate, provider_kw, category):
    g, r = released(tmp_path)
    prov = FixtureProvider(mutate=mutate, **provider_kw)
    run = tmp_path / "run"
    with pytest.raises(W.StageFailure) as e:
        W.run_validation(CFG, auth(r), components(g, prov), run)
    assert isinstance(e.value.cause, S.ScopeExceeded)
    rr = record(run)
    assert rr["failure_class"] == S.RUN_INVALID and rr["outcome_exposure"] is False
    bad = [x for x in ledger(run) if x["state"] == S.SCOPE_EXCEEDED]
    assert bad and bad[0]["category"] == category and bad[0]["path"].startswith("acquisition/scope_exceeded/")
    ev = (run / "archive/acquisition/events.jsonl").read_text()
    assert "RESPONSE_EXCEEDS_AUTHORISED_SCOPE" in ev                             # exposure recorded, bytes kept


def test_attribute_dates_within_declared_lag_accepted(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(mutate={DIV24: _ca_add(
        {"symbol": "XLK", "ex_date": "2024-12-20", "process_date": "2024-12-20", "payable_date": "2025-01-30"},
        "cash_dividends")})
    assert W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")["status"] == "COMPLETE"


def test_bars_beyond_window_end_is_run_invalid(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider(mutate={'"alpaca_bars"': _bars_add})
    with pytest.raises(W.StageFailure) as e:
        W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    assert isinstance(e.value.cause, S.ScopeExceeded) and record(tmp_path / "run")["failure_class"] == S.RUN_INVALID


# ================================================================================================ 4 post-window renames
D0 = date(2024, 6, 3)


def test_post_window_rename_reconstructs_ticker_on_d():
    edges = [("OLD", "NEW", D0 + timedelta(days=30))]                            # processed after the window
    f345 = {"OLD": [(D0 - timedelta(days=10), "0000000042")]}
    idt = R.identity_at("NEW", D0, edges, f345, {})
    assert idt["ticker_at_D"] == "OLD" and idt["identity"] == "VERIFIED_HISTORICAL_IDENTITY"
    assert idt["issuer"] == "0000000042" and idt["evidence_date"] <= D0


def test_future_evidence_never_admits():
    edges = [("OLD", "NEW", D0 + timedelta(days=30))]
    # Form 3/4/5 evidence exists only under the NEW ticker, dated after D: identity stays unresolved
    idt = R.identity_at("NEW", D0, edges, {"NEW": [(D0 + timedelta(days=40), "0000000042")]}, {})
    assert idt["identity"] == "UNRESOLVED_IDENTITY" and idt["issuer"] is None
    # an S&P list or link dated after D is never membership evidence on D
    sp_rows = [((D0 + timedelta(days=5)).isoformat(), {"OLD", "NEW"})]
    f345 = {"OLD": [(D0 - timedelta(days=10), "0000000042")]}
    assert R.sp_exempt("OLD", "0000000042", D0, sp_rows, f345, edges) == "NO_MEMBERSHIP_BY_D"
    # a periodic filing after D never makes R1a available on D
    assert R.r1a_available([(D0 + timedelta(days=1)).isoformat()], D0) is False
    # a 5.06 reported after D cannot establish operating status on D (rule 4 -> unresolved)
    st, _ = R.instrument_status("3571", (D0 - timedelta(days=20)).isoformat(),
                                [((D0 + timedelta(days=10)).isoformat(), (D0 + timedelta(days=12)).isoformat())],
                                "UNVERIFIED_LINK", D0)
    assert st == "UNRESOLVED_INSTRUMENT"


def test_ticker_reuse_is_not_chained_through():
    # OLD renamed to NEW (D+30); later a DIFFERENT security takes OLD (X->OLD at D+60). The NEW series on D traded as
    # OLD; the later reuse of OLD is not chained back (frozen V2.1 bound on predecessor edges).
    edges = [("OLD", "NEW", D0 + timedelta(days=30)), ("X", "OLD", D0 + timedelta(days=60))]
    t, chain, prob = R.ticker_at("NEW", D0, edges)
    assert (t, prob) == ("OLD", None) and [c[:2] for c in chain] == [("OLD", "NEW")]


def test_identity_rename_end_is_the_reference_date_not_today(tmp_path):
    g, r = released(tmp_path)
    run = tmp_path / "run"
    later = lambda: datetime(2026, 10, 6, 22, 0, tzinfo=timezone.utc)          # still inside R + 1 d
    W.run_validation(CFG, auth(r), components(g, FixtureProvider(), clock=later), run)
    ends = {dict(x["params"])["end"] for x in ledger(run) if x["category"] == "identity_renames"}
    assert ends == {DD.isoformat()}
    assert json.loads((run / "archive/acquisition/reference.json").read_text())["reference_date"] == DD.isoformat()


# ================================================================================================ reference date / resume
def test_resume_after_reference_window_blocks_before_any_request(tmp_path):
    g, r = released(tmp_path)
    arc = tmp_path / "arc"
    with pytest.raises(S.AcquisitionBlocked):
        components(g, FixtureProvider(faults={"/v2/assets": ["503"] * 4})).acquirer.acquire(CFG, arc)
    late = FixtureProvider()
    with pytest.raises(S.AcquisitionBlocked, match="RESUME_AFTER_REFERENCE_WINDOW"):
        components(g, late, clock=lambda: datetime(2026, 10, 8, 21, tzinfo=timezone.utc)).acquirer.acquire(CFG, arc)
    assert late.calls == []                                                     # refused before it was sent
    ok = FixtureProvider()
    man = components(g, ok, clock=lambda: datetime(2026, 10, 6, 21, tzinfo=timezone.utc)).acquirer.acquire(CFG, arc)
    assert man["complete"] and not any("contents" in k for k in ok.calls)       # S0 not repeated on resume


def test_resume_with_another_reference_date_blocks(tmp_path):
    g, r = released(tmp_path)
    arc = tmp_path / "arc"
    with pytest.raises(S.AcquisitionBlocked):
        components(g, FixtureProvider(faults={"/v2/assets": ["503"] * 4})).acquirer.acquire(CFG, arc)
    prov = FixtureProvider()
    with pytest.raises(S.AcquisitionBlocked, match="REFERENCE_DATE_MISMATCH"):
        components(g, prov, reference=DD + timedelta(days=2)).acquirer.acquire(CFG, arc)
    assert prov.calls == []


def test_reference_date_must_equal_the_release(tmp_path):
    g, r = released(tmp_path)
    prov = FixtureProvider()
    with pytest.raises(S.AcquisitionBlocked, match="release names"):
        components(g, prov, reference=DD + timedelta(days=1)).acquirer.acquire(CFG, tmp_path / "arc")
    assert prov.calls == []


def test_release_with_wider_broad_retrieval_bound_rejected(tmp_path):
    cur = write_records(tmp_path / "root")
    sc = scope_envelopes(PERIODS["B"], DD)
    assert sc["submissions"] == [[None, (DD + timedelta(days=1)).isoformat()]]
    sc["submissions"] = [[None, (DD + timedelta(days=5)).isoformat()]]
    with pytest.raises(RL.ReleaseInvalid, match="WIDER"):
        RL.activate(RL.ReleaseStore(tmp_path / "store"), make_request(CFG, cur, scope=sc), CFG, cur)


# ================================================================================================ 5 S&P prerequisite
@pytest.mark.parametrize("kw,state", [({"sp_last": "2026-09-29"}, S.INSUFFICIENT),
                                      ({"mutate": {"raw.example/sp500.csv": lambda b: b + b"2026-09-30,SAA\n"}},
                                       S.MALFORMED)])
def test_sp500_prerequisite_blocks_before_any_other_request(tmp_path, kw, state):
    g, r = released(tmp_path)
    prov = FixtureProvider(**kw)
    run = tmp_path / "run"
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), run)
    assert prov.calls and all('"github"' in k for k in prov.calls)            # no Alpaca / SEC / bars request
    st, rr = status(run), record(run)
    assert st["stage"] == "S0_SP500_COVERAGE" and st["required_failures"][0]["state"] == state
    assert rr["failure_class"] == S.ACQUISITION_BLOCKED and rr["retry_allowed"] is True
    assert not (run / "gates.json").exists() and not (run / "obs.csv").exists()   # not scored, not FAIL


def test_sp500_file_missing_from_listing_blocks(tmp_path):
    g, r = released(tmp_path)

    def drop(body):
        return json.dumps([x for x in json.loads(body) if x["name"] == "README.md"]).encode()
    prov = FixtureProvider(mutate={"/contents": drop})
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, prov), tmp_path / "run")
    assert "not published" in status(tmp_path / "run")["required_failures"][0]["detail"]


# ================================================================================================ 6 failure classes
def test_failure_classes(tmp_path, monkeypatch):
    from research.erm_nominee_validation import adapters as A
    g, r = released(tmp_path)
    # IMPLEMENTATION_FAILURE: a code error after a complete acquisition, before outcomes
    real = B.build

    def boom(*a, **k):
        raise TypeError("synthetic builder defect")
    monkeypatch.setattr(B, "build", boom)
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, FixtureProvider()), tmp_path / "r1")
    assert record(tmp_path / "r1")["failure_class"] == S.IMPLEMENTATION_FAILURE
    monkeypatch.setattr(B, "build", real)
    # RUN_INVALID: archive verification fails
    comps = components(g, FixtureProvider())
    acq = comps.acquirer.acquire

    def tamper(cfg, arc):
        m = acq(cfg, arc)
        (arc / "renames.json").write_bytes((arc / "renames.json").read_bytes() + b" ")
        return m
    comps.acquirer.acquire = tamper
    with pytest.raises(W.StageFailure) as e:
        W.run_validation(CFG, auth(r), comps, tmp_path / "r2")
    assert isinstance(e.value.cause, A.InputHashMismatch) and record(tmp_path / "r2")["failure_class"] == S.RUN_INVALID
    # INCOMPLETE_AFTER_OUTCOME_EXPOSURE
    from research.erm_nominee_validation import diagnostics as DG
    monkeypatch.setattr(DG, "unit_book", boom)
    with pytest.raises(W.StageFailure):
        W.run_validation(CFG, auth(r), components(g, FixtureProvider()), tmp_path / "r3")
    rr = record(tmp_path / "r3")
    assert rr["failure_class"] == S.INCOMPLETE_AFTER_OUTCOME_EXPOSURE and rr["retry_allowed"] is False


def test_acquisition_blocked_keeps_r9_reexecution_rule_and_preserves_records(tmp_path):
    """Behaviour unchanged pending D6: attempt 1 ACQUISITION_BLOCKED -> one re-execution, attempt_1/ preserved with its
    ledger; a second block -> ABORTED_OWNER_DECIDES (r10 proposes that pre-scoring blocks not consume it)."""
    g, r = released(tmp_path)
    run = tmp_path / "run"
    for _ in range(2):
        with pytest.raises(W.StageFailure):
            W.run_validation(CFG, auth(r), components(g, FixtureProvider(sp_last="2026-06-30")), run)
    assert (run / "attempt_1/archive/acquisition/ledger.jsonl").exists()
    rr = record(run)
    assert rr["status"] == "ABORTED_OWNER_DECIDES" and rr["failure_class"] == S.ACQUISITION_BLOCKED
