"""
talonx_v2.form4_source -- read-only Form 4 authority accessor (Phase 3)
==================================================================
V2 does NOT run its own SEC ingestion.  It consumes authoritative,
already-persisted insider data:

  live      -> talonx_ingest.intelligence.insider.store.InsiderStore
               (ingestion_ledger.db, Task 96B/96D)  -- code-P open-market
               purchases only, read side
  offline   -> the Task 107A research parquet
               (results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet)
  replay    -> an explicit list of row dicts (fixtures / Task 111 E2E)

All three normalise to ``cluster_engine.PurchaseRecord``.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from talonx_v2.cluster_engine import PurchaseRecord


def _to_date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v)
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:len(fmt) + 2] if "%b" in fmt else s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def from_rows(rows: list[dict]) -> list[PurchaseRecord]:
    """Row dicts with keys: symbol, issuer_cik, owner_cik, filing_date,
    [accession, transaction_date, transaction_value, is_officer,
    is_director, is_ten_percent, transaction_code]."""
    out: list[PurchaseRecord] = []
    for r in rows:
        fd = _to_date(r.get("filing_date"))
        if fd is None or not r.get("symbol") or not r.get("owner_cik"):
            continue
        out.append(PurchaseRecord(
            symbol=str(r["symbol"]).upper(),
            issuer_cik=str(r.get("issuer_cik", "")),
            owner_cik=str(r["owner_cik"]),
            filing_date=fd,
            accession=str(r.get("accession", "")),
            transaction_date=_to_date(r.get("transaction_date")),
            transaction_value=(float(r["transaction_value"])
                               if r.get("transaction_value") not in (None, "") else None),
            is_officer=bool(r.get("is_officer", False)),
            is_director=bool(r.get("is_director", False)),
            is_ten_percent=bool(r.get("is_ten_percent", r.get("is_ten_pct", False))),
            transaction_code=str(r.get("transaction_code", "P")).upper()[:1] or "P",
        ))
    return out


def from_research_parquet(
    path: str | Path = "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet",
    *,
    symbols: set[str] | None = None,
    since: date | None = None,
) -> list[PurchaseRecord]:
    import pandas as pd

    df = pd.read_parquet(path)
    df = df[df["code"].astype(str).str.upper() == "P"]
    if symbols:
        up = {s.upper() for s in symbols}
        df = df[df["issuer_sym"].astype(str).str.upper().isin(up)]
    if since is not None:
        df = df[pd.to_datetime(df["filing_date"]).dt.date >= since]
    rows = []
    for r in df.itertuples(index=False):
        rows.append({
            "symbol": r.issuer_sym, "issuer_cik": getattr(r, "issuer_cik", ""),
            "owner_cik": r.owner_cik, "filing_date": r.filing_date,
            "accession": getattr(r, "accession", ""),
            "transaction_date": getattr(r, "trans_date", None),
            "transaction_value": getattr(r, "value", None),
            "is_officer": bool(getattr(r, "is_officer", False)),
            "is_director": bool(getattr(r, "is_director", False)),
            "is_ten_percent": bool(getattr(r, "is_ten_pct", False)),
            "transaction_code": "P",
        })
    return from_rows(rows)


def from_insider_store(store, *, symbols: list[str] | None = None,
                       since: date | None = None,
                       causal_cutoff: datetime | None = None) -> list[PurchaseRecord]:
    """``store`` = talonx_ingest.intelligence.insider.store.InsiderStore."""
    from talonx_ingest.intelligence.insider.domain import TransactionClass

    syms = symbols or [None]
    recs: list[PurchaseRecord] = []
    for sym in syms:
        txns = store.query_transactions(
            symbol=sym, classification=TransactionClass.OPEN_MARKET_PURCHASE,
            since=since, causal_cutoff=causal_cutoff, newest_first=False,
        )
        for t in txns:
            fd = t.filing_date or (t.accepted_at_utc.date() if t.accepted_at_utc else None)
            if fd is None or not t.symbol or not t.owner_cik:
                continue
            recs.append(PurchaseRecord(
                symbol=t.symbol.upper(), issuer_cik=t.issuer_cik or "",
                owner_cik=t.owner_cik, filing_date=fd, accession=t.accession or "",
                transaction_date=t.transaction_date,
                transaction_value=t.transaction_value,
                is_officer=bool(t.is_officer), is_director=bool(t.is_director),
                is_ten_percent=bool(t.is_ten_percent_owner),
                transaction_code=(t.transaction_code or "P").upper()[:1] or "P",
            ))
    return recs
