"""
SEC filing-date release-fidelity fix.

SEC's submissions feed first serves a fresh filing's ``acceptanceDateTime`` as New York wall-clock labelled
``Z`` and rewrites it to true UTC hours later, so ``accepted_at_utc`` has mixed semantics and its ``.date()`` can
land on the next day for filings accepted in the evening ET. V2 must map filings to sessions by SEC's
``filingDate`` only: persisted on live ingest, required (fail closed) in release mode.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_ingest.intelligence.insider.store import InsiderStore as _RealInsiderStore
from talonx_v2 import form4_source, pipeline
from talonx_v2.calendar import next_session_strictly_after
from talonx_v2.config import V2Config
from talonx_v2.service import V2Service

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #
def _txn(st, *, symbol, cik, owner, acc, accepted, filing_date, tdate=None, value=500_000.0):
    from talonx_ingest.intelligence.insider.domain import InsiderTransaction, TransactionClass
    tid = hashlib.sha256(f"{acc}|{owner}|{tdate}".encode()).hexdigest()[:32]
    st.upsert_transaction(InsiderTransaction(
        transaction_id=tid, accession=acc, issuer_cik=cik, symbol=symbol,
        accepted_at_utc=datetime.fromisoformat(accepted) if accepted else None,
        filing_date=filing_date, transaction_date=tdate or (filing_date or date(2026, 1, 1)),
        owner_cik=owner, is_officer=True, transaction_code="P",
        classification=TransactionClass.OPEN_MARKET_PURCHASE, transaction_value=value))


def _store(tmp: Path, rows: list[dict]):
    st = _RealInsiderStore(path=tmp / "iso_ingestion_ledger.db")   # never the monkeypatched factory
    for r in rows:
        _txn(st, **r)
    st._conn.commit()
    return st


def _bars(tmp: Path, symbols, start=date(2026, 5, 1), end=date(2026, 12, 31)):
    from talonx_v2 import calendar as vc
    bd = tmp / "bars"
    bd.mkdir(exist_ok=True)
    for sym in symbols:
        with open(bd / f"{sym}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "close", "volume"])
            for s in vc._sessions():
                if start <= s <= end:
                    w.writerow([s.isoformat(), 40.0, 40.5, 1_500_000])
    return bd


def _svc(tmp, store, monkeypatch, symbols, *, require):
    import talonx_ingest.intelligence.insider.store as _stmod
    monkeypatch.setattr(_stmod, "InsiderStore", lambda *a, **k: store)
    cfg = V2Config(db_path=str(tmp / "v2_lane.db"), starting_cash_usd=100_000.0)
    return V2Service(config=cfg, bar_dirs=[_bars(tmp, symbols)], form4_kind="insider",
                     status_path=str(tmp / "status.json"), require_authoritative_filing_date=require)


def _dispositions(tmp):
    con = sqlite3.connect(str(tmp / "v2_lane.db"))
    try:
        return {r[0]: r[1] for r in con.execute("SELECT episode_id, disposition FROM processed_episodes")}
    finally:
        con.close()


def _counts(tmp):
    con = sqlite3.connect(str(tmp / "v2_lane.db"))
    try:
        return (con.execute("SELECT COUNT(*) FROM pending_entry_intents").fetchone()[0],
                con.execute("SELECT COUNT(*) FROM positions").fetchone()[0])
    finally:
        con.close()


def _episodes(tmp, rows, *, require, since):
    st = _store(tmp, rows)
    missing: list = []
    recs = form4_source.from_insider_store(st, since=since, require_filing_date=require,
                                           missing_filing_date=missing)
    return pipeline.detect_episodes(recs, config=V2Config()), missing


def _pair(symbol, d_first, acc_ts_second, filing_second, *, first_ts=None):
    """Two distinct owners; the SECOND (activating) filing's acceptance/filing date is what varies."""
    return [
        dict(symbol=symbol, cik="0000999888", owner="own-A", acc="0000000001-26-000001",
             accepted=first_ts or f"{d_first.isoformat()}T15:00:00+00:00", filing_date=d_first, tdate=d_first),
        dict(symbol=symbol, cik="0000999888", owner="own-B", acc="0000000002-26-000002",
             accepted=acc_ts_second, filing_date=filing_second, tdate=filing_second),
    ]


# --------------------------------------------------------------------------- #
# 1-4. live ingest persists SEC filingDate, independent of acceptance rendering #
# --------------------------------------------------------------------------- #
def _poll_once(tmp_path, monkeypatch, *, accepted, filed):
    from talonx_ingest.intelligence.comparison.retrieval import FilingArchiveCache
    from talonx_ingest.intelligence.service.backfill import Backfill
    from talonx_ingest.intelligence.service.cik_directory import CikDirectory
    from talonx_ingest.intelligence.service.config import ServiceConfig
    from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
    from talonx_ingest.intelligence.service.poller import EdgarPoller
    from talonx_ingest.intelligence.service.runner import IntelligenceService
    from talonx_ingest.intelligence.service.scope import resolve_scope
    from talonx_ingest.intelligence.service.stores import StoreBundle
    from tests._service_helpers import FakeEdgarClient, FakeWatchlistStore, make_submissions, wl_row

    cfg = ServiceConfig(ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "state",
                        history_days=3650, poll_base_seconds=0.01)
    svc = IntelligenceService(cfg)
    rows = [{"form": "4", "accn": "0000012345-26-000008", "accepted": accepted, "filed": filed,
             "primary": "xslF345X05/form4.xml"}]
    client = FakeEdgarClient(submissions={"0000012345": make_submissions(rows=rows)})
    directory = CikDirectory.from_company_tickers({"0": {"cik_str": 12345, "ticker": "FAKE", "title": "Fake"}})

    async def _open(with_network=True):
        svc.stores = StoreBundle.open(cfg.ledger())
        svc._watchlist = FakeWatchlistStore([wl_row("FAKE")])
        svc._owns_watchlist = True
        svc.client, svc.directory = client, directory
        svc.scope = resolve_scope(config=cfg, watchlist_store=svc._watchlist, directory=directory)
        svc.enrichment = EnrichmentEngine(svc.stores, client, config=cfg, metrics=svc.metrics,
                                          cache=FilingArchiveCache(client, cache_dir=tmp_path / "c"))
        svc.poller = EdgarPoller(svc.stores, client, config=cfg, scope=svc.scope,
                                 metrics=svc.metrics, enrichment=svc.enrichment)
        svc.backfill = Backfill(svc.stores, client, config=cfg, scope=svc.scope,
                                metrics=svc.metrics, enrichment=svc.enrichment)
        return svc

    monkeypatch.setattr(svc, "open", _open)

    async def _go():
        await svc.open()
        try:
            await svc.poll_cycle()
            return [(t.filing_date, t.accepted_at_utc) for t in svc.stores.insider.query_transactions(symbol="FAKE")]
        finally:
            await svc.close()
    return asyncio.run(_go())


def test_1_morning_et_filing_persists_sec_filing_date_and_maps_to_next_session(tmp_path, monkeypatch):
    got = _poll_once(tmp_path, monkeypatch, accepted="2026-06-11T13:00:00.000Z", filed="2026-06-11")
    assert got and all(fd == date(2026, 6, 11) for fd, _ in got)
    assert next_session_strictly_after(got[0][0]) == date(2026, 6, 12)


@pytest.mark.parametrize("rendering,accepted", [
    ("pre_rewrite_et_wallclock_labelled_z", "2026-06-11T20:30:00.000Z"),   # case 3
    ("post_rewrite_true_utc", "2026-06-12T00:30:00.000Z"),                 # cases 2 and 4
])
def test_2_3_4_evening_filing_keeps_sec_filing_day_under_either_sec_rendering(tmp_path, monkeypatch,
                                                                                rendering, accepted):
    got = _poll_once(tmp_path, monkeypatch, accepted=accepted, filed="2026-06-11")
    assert got and all(fd == date(2026, 6, 11) for fd, _ in got), rendering
    if rendering == "post_rewrite_true_utc":
        assert got[0][1].date() == date(2026, 6, 12)   # the old derivation would have said 06-12


def test_live_ingest_without_sec_filing_date_does_not_fabricate_one(tmp_path, monkeypatch):
    got = _poll_once(tmp_path, monkeypatch, accepted="2026-06-12T00:30:00.000Z", filed="")
    assert got and all(fd is None for fd, _ in got)


def test_all_live_callers_forward_sec_filing_date():
    root = Path(__file__).resolve().parents[1] / "talonx_ingest" / "intelligence" / "service"
    for name, needle in (("poller.py", "filing_date=nf.filing_date"), ("backfill.py", "filing_date=nf.filing_date"),
                         ("replay.py", "filing_date=match.filing_date")):
        assert needle in (root / name).read_text(encoding="utf-8"), name


# --------------------------------------------------------------------------- #
# session mapping: filing_date, never accepted_at_utc (release)               #
# --------------------------------------------------------------------------- #
def test_release_mapping_uses_filing_date_not_utc_acceptance_date(tmp_path):
    # 2nd owner accepted Thu 2026-08-13 21:00 ET = Fri 01:00Z (true UTC after SEC rewrite)
    rows = _pair("TMPX", date(2026, 8, 12), "2026-08-14T01:00:00+00:00", date(2026, 8, 13))
    eps, _ = _episodes(tmp_path, rows, require=True, since=date(2026, 7, 1))
    assert [e.eligible_entry_session for e in eps] == [date(2026, 8, 14)]


def test_legacy_mapping_is_unchanged_outside_release_mode(tmp_path):
    rows = _pair("TMPX", date(2026, 8, 12), "2026-08-14T01:00:00+00:00", None)
    rows[0]["filing_date"] = None
    eps, _ = _episodes(tmp_path, rows, require=False, since=date(2026, 7, 1))
    assert [e.eligible_entry_session for e in eps] == [date(2026, 8, 17)]   # old UTC-date behaviour (Fri -> Mon)


# --------------------------------------------------------------------------- #
# 5. cold start: the wrong UTC date used to admit; now correctly rejected      #
# --------------------------------------------------------------------------- #
def test_5_cold_start_previously_admitted_is_now_rejected(tmp_path, monkeypatch):
    rows = _pair("TMPX", date(2026, 8, 12), "2026-08-14T01:00:00+00:00", date(2026, 8, 13))
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    svc = _svc(new_dir, _store(new_dir, rows), monkeypatch, ["TMPX"], require=True)
    svc.tick(as_of=date(2026, 8, 17))         # stack first sees it Monday: contract entry (Fri 08-14) has passed
    svc.tick(as_of=date(2026, 8, 18))
    assert list(_dispositions(new_dir).values()) == ["SKIPPED_NO_PRIOR_INTENT"]
    assert _counts(new_dir) == (0, 0)

    # the pre-fix derivation (accepted_at_utc.date()) would have mapped the entry to Mon 08-17 and admitted it
    old_rows = [dict(r, filing_date=None) for r in rows]
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    old = _svc(old_dir, _store(old_dir, old_rows), monkeypatch, ["TMPX"], require=False)
    old.tick(as_of=date(2026, 8, 17))
    old.tick(as_of=date(2026, 8, 18))
    intents, positions = _counts(old_dir)
    assert intents == 1 and positions == 1


# --------------------------------------------------------------------------- #
# 6. missing filing_date in release mode -> fail closed (issuer-level)        #
# --------------------------------------------------------------------------- #
def test_6_missing_filing_date_fails_closed_and_is_reported(tmp_path, monkeypatch):
    rows = _pair("TMPX", date(2026, 8, 12), "2026-08-13T15:00:00+00:00", None)   # activating row lacks filingDate
    svc = _svc(tmp_path, _store(tmp_path, rows), monkeypatch, ["TMPX"], require=True)
    st = svc.tick(as_of=date(2026, 8, 13))
    svc.tick(as_of=date(2026, 8, 14))
    info = st["source"]["missing_authoritative_filing_date"]
    assert info["reason"] == "MISSING_AUTHORITATIVE_FILING_DATE" and info["count"] == 1
    assert info["blocked_symbols"] == ["TMPX"] and info["required"] is True
    assert _counts(tmp_path) == (0, 0) and _dispositions(tmp_path) == {}


def test_6b_one_missing_row_blocks_the_whole_issuer_no_partial_cluster(tmp_path):
    rows = _pair("TMPX", date(2026, 8, 12), "2026-08-13T15:00:00+00:00", date(2026, 8, 13))
    rows.append(dict(symbol="TMPX", cik="0000999888", owner="own-C", acc="0000000003-26-000003",
                     accepted="2026-08-20T15:00:00+00:00", filing_date=None, tdate=date(2026, 8, 20)))
    eps, missing = _episodes(tmp_path, rows, require=True, since=date(2026, 7, 1))
    assert eps == [] and [m["accession"] for m in missing] == ["0000000003-26-000003"]


# --------------------------------------------------------------------------- #
# 7-8. ADC and ABCL regressions (real accessions / SEC filingDate)             #
# --------------------------------------------------------------------------- #
ADC_ROWS = [
    dict(symbol="ADC", cik="0000917251", owner="0001528153", acc="0001528153-26-000011",
         accepted="2026-08-31T11:00:11+00:00", filing_date=date(2026, 8, 31), tdate=date(2026, 8, 27)),
    dict(symbol="ADC", cik="0000917251", owner="0001528153", acc="0001528153-26-000013",
         accepted="2026-09-02T20:05:28+00:00", filing_date=date(2026, 9, 2), tdate=date(2026, 8, 31)),
    dict(symbol="ADC", cik="0000917251", owner="0001348490", acc="0001348490-26-000006",
         accepted="2026-09-17T11:00:24+00:00", filing_date=date(2026, 9, 17), tdate=date(2026, 9, 16)),
    dict(symbol="ADC", cik="0000917251", owner="0001528153", acc="0001528153-26-000015",
         accepted="2026-09-17T11:00:41+00:00", filing_date=date(2026, 9, 17), tdate=date(2026, 9, 16)),
]
ABCL_ROWS = [
    dict(symbol="ABCL", cik="0001703057", owner="0001352908", acc="0001628280-26-057007",
         accepted="2026-08-14T15:50:16+00:00", filing_date=date(2026, 8, 14), tdate=date(2026, 8, 13)),
    dict(symbol="ABCL", cik="0001703057", owner="0001834411", acc="0001834411-26-000008",
         accepted="2026-08-14T16:04:25+00:00", filing_date=date(2026, 8, 14), tdate=date(2026, 8, 13)),
    dict(symbol="ABCL", cik="0001703057", owner="0001834423", acc="0001834423-26-000008",
         accepted="2026-08-18T18:45:24+00:00", filing_date=date(2026, 8, 18), tdate=date(2026, 8, 14)),
    dict(symbol="ABCL", cik="0001703057", owner="0001352908", acc="0001628280-26-058684",
         accepted="2026-08-24T21:21:48+00:00", filing_date=date(2026, 8, 24), tdate=date(2026, 8, 21)),
]


def test_7_adc_entry_session_and_late_receipt_rejection_unchanged(tmp_path, monkeypatch):
    eps, missing = _episodes(tmp_path, ADC_ROWS, require=True, since=date(2026, 8, 7))
    assert not missing and len(eps) == 1
    ep = eps[0]
    assert ep.activation_filing_date == date(2026, 9, 17) and ep.eligible_entry_session == date(2026, 9, 18)
    run = tmp_path / "run"
    run.mkdir()
    svc = _svc(run, _store(run, ADC_ROWS), monkeypatch, ["ADC"], require=True)
    svc.tick(as_of=date(2026, 9, 21))         # first RC1 tick able to see it (TalonX receipt 09-21 18:42Z)
    svc.tick(as_of=date(2026, 9, 22))
    assert set(_dispositions(run).values()) == {"SKIPPED_NO_PRIOR_INTENT"}
    assert _counts(run) == (0, 0)


def test_8_abcl_classification_unchanged(tmp_path, monkeypatch):
    eps, missing = _episodes(tmp_path, ABCL_ROWS, require=True, since=date(2026, 8, 7))
    assert not missing and len(eps) == 1 and eps[0].eligible_entry_session == date(2026, 8, 17)
    run = tmp_path / "run"
    run.mkdir()
    svc = _svc(run, _store(run, ABCL_ROWS), monkeypatch, ["ABCL"], require=True)
    svc.tick(as_of=date(2026, 9, 21))
    assert set(_dispositions(run).values()) == {"SKIPPED_ENTRY_STALE"}
    assert _counts(run) == (0, 0)


# --------------------------------------------------------------------------- #
# 9-11. DST: EDT, EST and around both transitions                              #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label,d_first,accepted_second,filing_day,contract_entry,old_entry", [
    # 9. EDT: 21:30 ET Wed 07-15 = 01:30Z Thu
    ("EDT", date(2026, 7, 14), "2026-07-16T01:30:00+00:00", date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17)),
    # 10. EST: 19:30 ET Thu 12-10 = 00:30Z Fri (the UTC day already flips at 19:00 ET in winter)
    ("EST", date(2026, 12, 9), "2026-12-11T00:30:00+00:00", date(2026, 12, 10), date(2026, 12, 11), date(2026, 12, 14)),
    # 11a. first EST weekday after the 2026-11-01 fall-back: 20:30 ET Mon 11-02 = 01:30Z Tue
    ("EST_after_fall_back", date(2026, 10, 30), "2026-11-03T01:30:00+00:00", date(2026, 11, 2),
     date(2026, 11, 3), date(2026, 11, 4)),
    # 11b. last EDT weekday before it: 20:30 ET Fri 10-30 = 00:30Z Sat -> both map to Mon 11-02
    ("EDT_before_fall_back", date(2026, 10, 29), "2026-10-31T00:30:00+00:00", date(2026, 10, 30),
     date(2026, 11, 2), date(2026, 11, 2)),
    # 11c. first EDT weekday after the 2026-03-08 spring-forward: 20:30 ET Mon 03-09 = 00:30Z Tue
    ("EDT_after_spring_forward", date(2026, 3, 6), "2026-03-10T00:30:00+00:00", date(2026, 3, 9),
     date(2026, 3, 10), date(2026, 3, 11)),
])
def test_9_10_11_dst_cases_map_by_sec_filing_date(tmp_path, label, d_first, accepted_second, filing_day,
                                                   contract_entry, old_entry):
    rows = _pair("TMPX", d_first, accepted_second, filing_day)
    new_dir, old_dir = tmp_path / "n", tmp_path / "o"
    new_dir.mkdir()
    old_dir.mkdir()
    eps, _ = _episodes(new_dir, rows, require=True, since=d_first - timedelta(days=30))
    assert [e.eligible_entry_session for e in eps] == [contract_entry], label
    legacy_rows = [dict(r, filing_date=None) for r in rows]
    old_eps, _ = _episodes(old_dir, legacy_rows, require=False, since=d_first - timedelta(days=30))
    assert [e.eligible_entry_session for e in old_eps] == [old_entry], label


# --------------------------------------------------------------------------- #
# backfill: filing_date only, from SEC metadata, never accepted_at_utc         #
# --------------------------------------------------------------------------- #
def _backfill_db(tmp):
    from talonx_ingest.intelligence.insider.domain import InsiderFiling
    st = _store(tmp, [
        dict(symbol="TMPX", cik="0000999888", owner="o1", acc="0000999888-26-000001",
             accepted="2026-09-10T00:50:00+00:00", filing_date=None, tdate=date(2026, 9, 8)),
        dict(symbol="TMPX", cik="0000999888", owner="o2", acc="0000999888-26-000002",
             accepted="2026-06-01T15:00:00+00:00", filing_date=None, tdate=date(2026, 5, 28)),
        dict(symbol="TMPX", cik="0000999888", owner="o3", acc="0000999888-26-000003",
             accepted="2026-09-01T15:00:00+00:00", filing_date=None, tdate=date(2026, 8, 28)),
        dict(symbol="TMPX", cik="0000999888", owner="o4", acc="0000999888-26-000004",
             accepted="2026-09-02T15:00:00+00:00", filing_date=date(2026, 9, 2), tdate=date(2026, 8, 29)),
    ])
    st.upsert_filing(InsiderFiling(insider_filing_id="0000999888-26-000001", accession="0000999888-26-000001",
                                   symbol="TMPX", issuer_cik="0000999888", form_type="4",
                                   accepted_at_utc=datetime(2026, 9, 10, 0, 50, tzinfo=UTC),
                                   ingested_at_utc=datetime(2026, 9, 10, 7, 0, tzinfo=UTC)))
    st.close()
    return tmp / "iso_ingestion_ledger.db"


def _fake_sec(calls):
    docs = {
        "https://data.sec.gov/submissions/CIK0000999888.json": {"filings": {
            "recent": {"accessionNumber": ["0000999888-26-000001"], "filingDate": ["2026-09-09"]},
            "files": [{"name": "CIK0000999888-submissions-001.json"}]}},
        "https://data.sec.gov/submissions/CIK0000999888-submissions-001.json": {
            "accessionNumber": ["0000999888-26-000002"], "filingDate": ["2026-06-01"]},
    }

    def fetch(url):
        calls.append(url)
        return docs.get(url, {})
    return fetch


def test_backfill_dry_run_writes_nothing(tmp_path):
    db = _backfill_db(tmp_path)
    rep = __import__("talonx_ingest.intelligence.insider.filing_date_backfill",
                     fromlist=["backfill"]).backfill(db, fetch=_fake_sec([]), apply=False)
    assert rep["accessions_resolved"] == 2 and rep["accessions_unresolved"] == 1
    con = sqlite3.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM insider_transactions WHERE filing_date IS NULL").fetchone()[0] == 3


def test_backfill_sets_only_filing_date_from_sec_is_idempotent_and_never_uses_acceptance(tmp_path):
    from talonx_ingest.intelligence.insider.filing_date_backfill import backfill
    db = _backfill_db(tmp_path)
    con = sqlite3.connect(str(db))
    before = con.execute("SELECT accession, accepted_at_utc, ingested_at_utc FROM insider_filings").fetchall()
    rep = backfill(db, fetch=_fake_sec([]), apply=True)
    got = dict(con.execute("SELECT accession, filing_date FROM insider_transactions"))
    # recent + older shard resolved; SEC's ET filing day (09-09), NOT date(accepted_at_utc) (09-10)
    assert got["0000999888-26-000001"] == "2026-09-09"
    assert got["0000999888-26-000002"] == "2026-06-01"
    assert got["0000999888-26-000003"] is None                    # not listed by SEC -> stays unresolved
    assert got["0000999888-26-000004"] == "2026-09-02"            # already populated -> untouched
    assert con.execute("SELECT filing_date FROM insider_filings").fetchone()[0] == "2026-09-09"
    assert con.execute("SELECT accession, accepted_at_utc, ingested_at_utc FROM insider_filings").fetchall() == before
    assert rep["rows"]["insider_transactions"]["backfilled"] == 2
    assert rep["unresolved_code_p_accessions"] == ["0000999888-26-000003"]
    again = backfill(db, fetch=_fake_sec([]), apply=True)
    assert again["rows"]["insider_transactions"]["backfilled"] == 0


# --------------------------------------------------------------------------- #
# release gate readiness                                                       #
# --------------------------------------------------------------------------- #
def test_release_gate_filing_date_readiness(tmp_path):
    from talonx_v2.release_gate import _filing_date_readiness
    now = datetime(2026, 9, 23, 12, tzinfo=UTC)
    rows = _pair("TMPX", date(2026, 9, 10), "2026-09-11T15:00:00+00:00", date(2026, 9, 11))
    ok_dir, bad_dir = tmp_path / "ok", tmp_path / "bad"
    ok_dir.mkdir()
    bad_dir.mkdir()
    _store(ok_dir, rows).close()
    _store(bad_dir, [dict(r, filing_date=None) for r in rows]).close()
    assert _filing_date_readiness(ok_dir / "iso_ingestion_ledger.db", now=now)[1] == "PASS"
    name, status, detail = _filing_date_readiness(bad_dir / "iso_ingestion_ledger.db", now=now)
    assert (name, status) == ("authoritative_filing_date_readiness", "FAIL") and "filing_date_backfill" in detail
    assert _filing_date_readiness(None, now=now)[1] == "WARN"
    assert _filing_date_readiness(tmp_path / "absent.db", now=now)[1] == "FAIL"


# --------------------------------------------------------------------------- #
# freeze allowlist guard                                                       #
# --------------------------------------------------------------------------- #
def test_release_fidelity_fix_allowlist_is_closed_and_strategy_free():
    from talonx_ops.prospective.preflight import FREEZE_RELEASE_FIDELITY_FIX_FILES as files
    v2 = {Path(f).name for f in files if f.startswith("talonx_v2/")}
    assert v2 == {"form4_source.py", "service.py"}
    fp_mod = __import__("research.scripts.task112_v2_release_fingerprint", fromlist=["_STRATEGY_FILES"])
    fp_files = {str(p.relative_to(Path(fp_mod.__file__).resolve().parents[2])).replace("\\", "/")
                for p in fp_mod._STRATEGY_FILES}
    assert not fp_files & set(files)
    forbidden_v2 = ("config.py", "cluster_engine.py", "liquidity", "quant_bridge", "brain_bridge", "pricing",
                    "provider_contract", "sip_adapter", "paper", "store.py", "pipeline.py", "corporate_actions",
                    "dividends", "sizing", "calendar")
    assert not [f for f in files if f.startswith("talonx_v2/") and any(x in Path(f).name for x in forbidden_v2)]
    assert all(f.startswith(("talonx_ingest/intelligence/", "talonx_v2/")) for f in files)
