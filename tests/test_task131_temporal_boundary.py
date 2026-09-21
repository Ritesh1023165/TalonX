"""
Task 131 Remediation Directive 3 -- explicit, enforced temporal filing
dissemination boundary. The real SEC EDGAR wall-clock ``accepted_at_utc``
is looked up directly from InsiderStore each tick
(``V2Service._refresh_dissemination_lookup``) and compared against the
entry session's own RTH open (``V2Service._verify_temporal_boundary``)
before any entry is attempted -- entirely within talonx_v2/service.py,
never touching the frozen talonx_v2/cluster_engine.py contract.

Under the frozen entry_offset_sessions=1 rule this boundary should never
be violated in normal operation (activation day's own end-of-day is
always strictly before the NEXT session's own morning open) -- these
tests exercise the DEFENSIVE case: an anomalous/backfilled filing whose
own recorded dissemination timestamp is unexpectedly late, and confirm
it is refused rather than silently entered (look-ahead bias), alongside
the normal, expected-to-pass case.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from talonx_v2.config import V2Config
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store

SYM = "TMPX"
ACT = date(2026, 8, 14)     # Fri: 2nd distinct insider's Form 4 disseminated
ENTRY = date(2026, 8, 17)   # Mon: eligible entry session


def _isolated_insider_store(tmp: Path, *, second_owner_accepted_at: str):
    from talonx_ingest.intelligence.insider.domain import InsiderTransaction, TransactionClass
    from talonx_ingest.intelligence.insider.store import InsiderStore
    st = InsiderStore(path=tmp / "iso_ingestion_ledger.db")
    rows = [
        ("own-A", "2026-08-10", "0001234567-26-000111", "2026-08-13T18:05:00+00:00"),
        ("own-B", "2026-08-12", "0007654321-26-000222", second_owner_accepted_at),
    ]
    for owner, tdate, acc, acc_ts in rows:
        tid = hashlib.sha256(f"{acc}|{owner}".encode()).hexdigest()[:32]
        st.upsert_transaction(InsiderTransaction(
            transaction_id=tid, accession=acc, issuer_cik="0000999888", symbol=SYM,
            accepted_at_utc=datetime.fromisoformat(acc_ts),
            filing_date=ACT,  # both filings land on the SAME activation date
            transaction_date=date.fromisoformat(tdate), owner_cik=owner,
            is_officer=True, transaction_code="P",
            classification=TransactionClass.OPEN_MARKET_PURCHASE, transaction_value=750_000.0))
    st._conn.commit()
    return st


def _bars(tmp: Path):
    import csv
    from talonx_v2 import calendar as vc
    bd = tmp / "bars"
    bd.mkdir()
    sess = [s for s in vc._sessions() if date(2026, 6, 1) <= s <= date(2026, 9, 15)]
    with open(bd / f"{SYM}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "close", "volume"])
        for s in sess:
            w.writerow([s.isoformat(), 40.0, 40.5, 1_500_000])
    return bd


def _svc(tmp, store, monkeypatch):
    import talonx_ingest.intelligence.insider.store as _stmod
    monkeypatch.setattr(_stmod, "InsiderStore", lambda *a, **k: store)
    cfg = V2Config(db_path=str(tmp / "v2_lane.db"), starting_cash_usd=300_000.0)
    return V2Service(config=cfg, bar_dirs=[_bars(tmp)], form4_kind="insider",
                     status_path=str(tmp / "v2_service_status.json"))


def test_normally_timed_filing_passes_the_boundary_check(tmp_path, monkeypatch):
    # accepted well before ENTRY's own RTH open (09:30 ET / 13:30 UTC) --
    # the ordinary, expected case.
    store = _isolated_insider_store(tmp_path, second_owner_accepted_at="2026-08-14T15:20:00+00:00")
    svc = _svc(tmp_path, store, monkeypatch)
    svc.tick(as_of=ACT)
    st = svc.tick(as_of=ENTRY)
    assert st["entries_this_tick"] == 1
    v2 = V2Store(str(tmp_path / "v2_lane.db"), starting_cash=300_000.0)
    assert v2.n_open() == 1
    disp = [r[0] for r in __import__("sqlite3").connect(str(tmp_path / "v2_lane.db")).execute(
        "SELECT disposition FROM processed_episodes")]
    assert "SKIPPED_TEMPORAL_BOUNDARY_VIOLATION" not in disp


def test_anomalously_late_dissemination_is_refused_not_entered(tmp_path, monkeypatch):
    # the activating filing's OWN recorded acceptance timestamp is
    # (anomalously) AFTER the entry session's own RTH open -- a
    # data-quality edge case the boundary check must catch and refuse,
    # never silently enter on. Exercised via a durable PENDING intent
    # created honestly (a normally-timed filing forms the episode/intent
    # first), then the dissemination lookup itself is refreshed with an
    # anomalous late timestamp for the SAME (symbol, activation_filing_date)
    # key on the entry tick -- reproducing exactly what
    # _refresh_dissemination_lookup would populate from a genuinely
    # anomalous/backfilled InsiderStore row, without depending on a
    # specific multi-tick causal_cutoff timing coincidence.
    store = _isolated_insider_store(tmp_path, second_owner_accepted_at="2026-08-14T15:20:00+00:00")
    svc = _svc(tmp_path, store, monkeypatch)
    svc.tick(as_of=ACT)  # creates the durable PENDING intent, normally timed

    import exchange_calendars as xc
    from datetime import timedelta
    rth_open = xc.get_calendar("XNYS").session_open(ENTRY.isoformat()).to_pydatetime()
    svc._refresh_dissemination_lookup = lambda *a, **k: setattr(
        svc, "_dissemination_lookup", {(SYM, ACT.isoformat()): rth_open + timedelta(hours=1)})

    st = svc.tick(as_of=ENTRY)

    assert st["entries_this_tick"] == 0
    v2 = V2Store(str(tmp_path / "v2_lane.db"), starting_cash=300_000.0)
    assert v2.n_open() == 0
    assert v2.cash() == 300_000.0
    disp = [r[0] for r in __import__("sqlite3").connect(str(tmp_path / "v2_lane.db")).execute(
        "SELECT disposition FROM processed_episodes")]
    assert "SKIPPED_TEMPORAL_BOUNDARY_VIOLATION" in disp
    intents = v2.all_entry_intents()
    assert intents[0]["status"] == "REJECTED_TEMPORAL_BOUNDARY_VIOLATION"


def test_verify_temporal_boundary_unit_level(tmp_path, monkeypatch):
    # direct unit coverage of the comparison itself, both sides of the boundary.
    store = _isolated_insider_store(tmp_path, second_owner_accepted_at="2026-08-14T15:20:00+00:00")
    svc = _svc(tmp_path, store, monkeypatch)
    from talonx_v2.cluster_engine import ClusterEpisode
    ep = ClusterEpisode(episode_id="e1", symbol=SYM, issuer_cik="x",
                        distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
                        first_filing_date=ACT, activation_filing_date=ACT, last_filing_date=ACT,
                        aggregate_purchase_value=0.0, any_officer=False, any_director=False,
                        any_ten_percent=False, causal_event_ts=datetime(2026, 8, 14, 23, 59, 59,
                                                                        tzinfo=timezone.utc),
                        eligible_entry_session=ENTRY)
    import exchange_calendars as xc
    from datetime import timedelta
    rth_open = xc.get_calendar("XNYS").session_open(ENTRY.isoformat()).to_pydatetime().astimezone(timezone.utc)

    svc._dissemination_lookup = {(SYM, ACT.isoformat()): rth_open - timedelta(minutes=1)}
    ok, _ = svc._verify_temporal_boundary(ep)
    assert ok is True   # strictly before RTH open -- passes

    svc._dissemination_lookup = {(SYM, ACT.isoformat()): rth_open}
    ok, detail = svc._verify_temporal_boundary(ep)
    assert ok is False and "look-ahead" in detail  # exactly at RTH open -- refused (not strictly before)

    svc._dissemination_lookup = {(SYM, ACT.isoformat()): rth_open + timedelta(minutes=1)}
    ok, _ = svc._verify_temporal_boundary(ep)
    assert ok is False   # after RTH open -- refused


def test_date_only_source_skips_the_check_gracefully(tmp_path):
    # parquet/from_rows sources never fabricate a wall-clock timestamp --
    # the boundary check is a documented no-op (returns ok) for them.
    svc = V2Service(config=V2Config(db_path=str(tmp_path / "v2.db")), bar_dirs=[_bars(tmp_path)],
                    form4_kind="parquet", status_path=str(tmp_path / "s.json"))
    from talonx_v2.cluster_engine import ClusterEpisode
    ep = ClusterEpisode(episode_id="e1", symbol=SYM, issuer_cik="x",
                        distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
                        first_filing_date=ACT, activation_filing_date=ACT, last_filing_date=ACT,
                        aggregate_purchase_value=0.0, any_officer=False, any_director=False,
                        any_ten_percent=False, causal_event_ts=datetime(2026, 8, 14, 23, 59, 59,
                                                                        tzinfo=timezone.utc),
                        eligible_entry_session=ENTRY)
    ok, detail = svc._verify_temporal_boundary(ep)
    assert ok is True and detail == ""
