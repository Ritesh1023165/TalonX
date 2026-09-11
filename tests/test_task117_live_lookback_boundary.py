"""
Task 117 final-activation correction (A2): the accepted ``--live-lookback-days``
is 45 (the CLI default in both ``talonx_ops.prospective`` and ``talonx_v2.run``),
not 5. A cluster's FIRST insider filing can legitimately sit well outside a
short window while still being inside the frozen 10-trading-day (~14 calendar
day) cluster window -- a lookback that is too short silently drops that first
filing from the live source read, making a genuine >=2-distinct-owner cluster
look like a single-owner near-miss. This is a live-source-adapter boundary
test, not a strategy-rule change: the frozen cluster window itself is
untouched.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

from talonx_ingest.intelligence.insider.domain import InsiderTransaction, TransactionClass
from talonx_ingest.intelligence.insider.store import InsiderStore
from talonx_v2 import form4_source

SYM = "BNDL"
AS_OF = date(2026, 9, 11)


def _store(tmp_path):
    st = InsiderStore(path=tmp_path / "iso_ingestion_ledger.db")
    # first insider: 7 calendar days before as_of -- inside the 10-trading-day
    # (~14 calendar day) cluster window, but OUTSIDE a 5-calendar-day lookback.
    first_filed = AS_OF - timedelta(days=7)
    # second insider: 2 calendar days before as_of -- inside any lookback.
    second_filed = AS_OF - timedelta(days=2)
    for owner, filed, acc in (
        ("owner-A", first_filed, "0001234567-26-000301"),
        ("owner-B", second_filed, "0001234567-26-000302"),
    ):
        tid = hashlib.sha256(f"{acc}|{owner}".encode()).hexdigest()[:32]
        acc_ts = datetime.combine(filed, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=18)
        st.upsert_transaction(InsiderTransaction(
            transaction_id=tid, accession=acc, issuer_cik="0000555222", symbol=SYM,
            accepted_at_utc=acc_ts, filing_date=filed, transaction_date=filed,
            owner_cik=owner, is_officer=True, transaction_code="P",
            classification=TransactionClass.OPEN_MARKET_PURCHASE, transaction_value=500_000.0))
    st._conn.commit()
    return st


def test_accepted_45_day_lookback_keeps_the_first_insider_in_the_cluster_window(tmp_path):
    st = _store(tmp_path)
    since = AS_OF - timedelta(days=45)          # the accepted CLI default
    cutoff = datetime.combine(AS_OF, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)
    recs = form4_source.from_insider_store(st, since=since, causal_cutoff=cutoff)
    owners = {r.owner_cik for r in recs if r.symbol == SYM}
    assert owners == {"owner-A", "owner-B"}, (
        "both insiders must be visible at the accepted 45-day lookback -- "
        f"got {owners}")
    st.close()


def test_a_five_day_lookback_would_silently_drop_the_first_insider(tmp_path):
    """Demonstrates the exact risk a too-short lookback creates: NOT the
    accepted configuration, but proof of why 45 (not 5) is required."""
    st = _store(tmp_path)
    since = AS_OF - timedelta(days=5)            # deliberately the WRONG value
    cutoff = datetime.combine(AS_OF, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)
    recs = form4_source.from_insider_store(st, since=since, causal_cutoff=cutoff)
    owners = {r.owner_cik for r in recs if r.symbol == SYM}
    assert owners == {"owner-B"}, (
        "a 5-day lookback silently drops owner-A even though its filing is "
        "inside the 10-trading-day cluster window -- this is the defect a "
        "45-day lookback avoids")
    st.close()


def test_cli_default_and_v2service_default_both_match_the_accepted_45(monkeypatch):
    import inspect

    import talonx_ops.prospective.__main__ as m
    from talonx_v2.service import V2Service

    captured = {}
    monkeypatch.setattr(m, "cmd_start", lambda args: captured.setdefault("args", args) or 0)
    m.main(["start"])
    assert captured["args"].live_lookback_days == 45

    sig = inspect.signature(V2Service.__init__)
    assert sig.parameters["live_lookback_days"].default == 45

    import talonx_v2.run as run_mod
    src = inspect.getsource(run_mod.main)
    assert "--live-lookback-days" in src and "default=45" in src
