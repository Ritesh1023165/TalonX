"""
Task 117 Phase 0 -- source-contract and readiness repairs.

Covers the F3/F4/F5 findings from the source-coverage audit
(results/task117_phase0_source_coverage_audit_20260909T205439Z):

  F5  live mode must NOT silently fall back to the historical research
      parquet when the InsiderStore read fails -- it must raise and the
      status must show DATA_UNAVAILABLE / DEGRADED_SOURCE.
  F4  source readiness is reported separately from the process heartbeat.
  F3  the lookback bound is a *dissemination* window -- a Form 4 filed
      late for an older transaction is kept; a filing disseminated before
      the window, or (in an as-of replay) accepted after the cutoff, is
      excluded.

No strategy semantics change; V2 fingerprint 11107198c5b81237 unchanged
(these edits touch only service.py / form4_source.py -- both plumbing,
not hashed).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from talonx_v2 import form4_source
from talonx_v2.config import V2Config
from talonx_v2.service import V2Service, V2SourceError
from talonx_v2.store import V2Store


# --------------------------------------------------------------------------- #
# a minimal read-only fake of InsiderStore.query_transactions
# --------------------------------------------------------------------------- #
class _Txn:
    def __init__(self, *, symbol, owner_cik, transaction_date, accepted_at_utc,
                 accession="acc", issuer_cik="cik", transaction_code="P"):
        self.symbol = symbol
        self.owner_cik = owner_cik
        self.issuer_cik = issuer_cik
        self.accession = accession
        self.transaction_date = date.fromisoformat(transaction_date)
        self.accepted_at_utc = datetime.fromisoformat(accepted_at_utc)
        self.filing_date = None            # mirrors production: filing_date is NULL
        self.transaction_value = 100_000.0
        self.transaction_code = transaction_code
        self.is_officer = self.is_director = self.is_ten_percent_owner = False


class _FakeStore:
    def __init__(self, txns, *, raise_on_query=False):
        self._txns = txns
        self._raise = raise_on_query

    def query_transactions(self, *, symbol=None, classification=None, since=None,
                           until=None, causal_cutoff=None, newest_first=True, **_):
        if self._raise:
            raise RuntimeError("simulated InsiderStore failure")
        out = []
        for t in self._txns:
            if since is not None and t.transaction_date < since:
                continue
            if causal_cutoff is not None and t.accepted_at_utc > causal_cutoff:
                continue
            out.append(t)
        return out


def _cfg(tmp_path):
    return V2Config(db_path=str(tmp_path / "v2.db"), starting_cash_usd=300_000.0,
                    per_position_allocation_usd=10_000.0)


# --------------------------------------------------------------------------- #
# F3 -- dissemination-window lookback
# --------------------------------------------------------------------------- #
def test_late_filed_old_transaction_is_kept():
    """transaction_date 60d before `since`, but ACCEPTED inside the window."""
    since = date(2026, 7, 26)
    txns = [
        _Txn(symbol="AAA", owner_cik="o1", transaction_date="2026-05-20",
             accepted_at_utc="2026-08-01T14:00:00+00:00", accession="a1"),
        _Txn(symbol="AAA", owner_cik="o2", transaction_date="2026-05-22",
             accepted_at_utc="2026-08-03T14:00:00+00:00", accession="a2"),
    ]
    recs = form4_source.from_insider_store(_FakeStore(txns), since=since)
    assert len(recs) == 2, "late-filed older transactions must not be dropped by a transaction_date filter"
    assert {r.filing_date for r in recs} == {date(2026, 8, 1), date(2026, 8, 3)}


def test_filing_disseminated_before_window_is_excluded():
    since = date(2026, 7, 26)
    txns = [
        _Txn(symbol="BBB", owner_cik="o1", transaction_date="2026-07-01",
             accepted_at_utc="2026-07-02T14:00:00+00:00"),          # before window
        _Txn(symbol="BBB", owner_cik="o2", transaction_date="2026-07-28",
             accepted_at_utc="2026-07-29T14:00:00+00:00"),          # inside window
    ]
    recs = form4_source.from_insider_store(_FakeStore(txns), since=since)
    assert [r.filing_date for r in recs] == [date(2026, 7, 29)]


def test_causal_cutoff_excludes_future_acceptance():
    since = date(2026, 7, 26)
    cutoff = datetime(2026, 9, 9, 23, 59, 59, tzinfo=timezone.utc)
    txns = [
        _Txn(symbol="CCC", owner_cik="o1", transaction_date="2026-09-04",
             accepted_at_utc="2026-09-08T14:00:00+00:00"),          # ok
        _Txn(symbol="CCC", owner_cik="o2", transaction_date="2026-09-05",
             accepted_at_utc="2026-09-10T14:00:00+00:00"),          # after cutoff
    ]
    recs = form4_source.from_insider_store(_FakeStore(txns), since=since, causal_cutoff=cutoff)
    assert [r.owner_cik for r in recs] == ["o1"]


def test_two_rows_one_insider_is_not_a_cluster():
    from talonx_v2.cluster_engine import detect_episodes
    since = date(2026, 7, 26)
    txns = [
        _Txn(symbol="DDD", owner_cik="same", transaction_date="2026-08-10",
             accepted_at_utc="2026-08-11T14:00:00+00:00", accession="x1"),
        _Txn(symbol="DDD", owner_cik="same", transaction_date="2026-08-12",
             accepted_at_utc="2026-08-13T14:00:00+00:00", accession="x2"),
    ]
    recs = form4_source.from_insider_store(_FakeStore(txns), since=since)
    assert detect_episodes(recs, config=V2Config()) == []


# --------------------------------------------------------------------------- #
# F5 -- no silent parquet fallback in live mode
# --------------------------------------------------------------------------- #
def test_live_source_failure_raises_not_fallback(tmp_path, monkeypatch):
    svc = V2Service(config=_cfg(tmp_path), bar_dirs=[tmp_path], form4_kind="insider",
                    status_path=str(tmp_path / "s.json"))
    import talonx_ingest.intelligence.insider.store as _st
    monkeypatch.setattr(_st, "InsiderStore",
                        lambda *a, **k: _FakeStore([], raise_on_query=True))

    with pytest.raises(V2SourceError):
        svc._records(as_of=date(2026, 9, 9))          # noqa: SLF001
    assert svc._source_state["ok"] is False           # noqa: SLF001
    assert svc._source_state["actual"] == "insider"   # noqa: SLF001


def test_tick_with_degraded_source_writes_data_unavailable(tmp_path, monkeypatch):
    import json
    svc = V2Service(config=_cfg(tmp_path), bar_dirs=[tmp_path], form4_kind="insider",
                    status_path=str(tmp_path / "s.json"))
    import talonx_ingest.intelligence.insider.store as _st
    monkeypatch.setattr(_st, "InsiderStore",
                        lambda *a, **k: _FakeStore([], raise_on_query=True))

    status = svc.tick(as_of=date(2026, 9, 9))
    assert status["heartbeat_kind"] == "DEGRADED_SOURCE"
    assert status["data_state"] == "DATA_UNAVAILABLE"
    assert status["source"]["ok"] is False
    assert status["entries_this_tick"] == 0
    on_disk = json.loads((tmp_path / "s.json").read_text())
    assert on_disk["data_state"] == "DATA_UNAVAILABLE"
    # ledger untouched
    assert V2Store(str(tmp_path / "v2.db"), starting_cash=300_000.0).cash() == 300_000.0


def test_explicit_parquet_mode_is_labelled_offline(tmp_path):
    svc = V2Service(config=_cfg(tmp_path), bar_dirs=[tmp_path], form4_kind="parquet",
                    form4_parquet="results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet",
                    status_path=str(tmp_path / "s.json"))
    recs = svc._records(as_of=date(2026, 3, 15))       # noqa: SLF001
    assert svc._source_state["actual"] == "parquet"    # noqa: SLF001
    assert "OFFLINE" in svc._source_state["note"]      # noqa: SLF001
    assert isinstance(recs, list)


# --------------------------------------------------------------------------- #
# F4 -- source readiness distinct from heartbeat
# --------------------------------------------------------------------------- #
def test_healthy_read_sets_source_ok_and_last_ok_ts(tmp_path, monkeypatch):
    txns = [
        _Txn(symbol="AAPL", owner_cik="o1", transaction_date="2026-08-20",
             accepted_at_utc="2026-08-21T14:00:00+00:00"),
        _Txn(symbol="AAPL", owner_cik="o2", transaction_date="2026-08-22",
             accepted_at_utc="2026-08-24T14:00:00+00:00"),
    ]
    svc = V2Service(config=_cfg(tmp_path), bar_dirs=[tmp_path], form4_kind="insider",
                    status_path=str(tmp_path / "s.json"))
    import talonx_ingest.intelligence.insider.store as _st
    monkeypatch.setattr(_st, "InsiderStore", lambda *a, **k: _FakeStore(txns))

    svc._records(as_of=date(2026, 9, 9))              # noqa: SLF001
    ss = svc._source_state                            # noqa: SLF001
    assert ss["ok"] is True and ss["actual"] == "insider" and ss["records"] == 2
    assert ss["last_ok_utc"] and ss["causal_cutoff"].startswith("2026-09-09")
