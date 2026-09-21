"""
talonx_ingest.intelligence.insider.store
========================================
``InsiderStore`` -- persistence for insider filings and transactions.

Additive tables in the SAME SQLite file the Task 96A ``EventStore`` /
Task 96C ``FilingComparisonStore`` use (``settings.ledger.path``).
``CREATE TABLE IF NOT EXISTS`` only; no existing table or row is touched.

Idempotency: ``transaction_id`` is content-addressed, so the same
transaction seen through the quarterly bulk and through the per-filing XML
resolves to one id. ``upsert_transaction`` replaces on conflict (both
routes are deterministic; XML carries fuller relationship flags), so the
row count never grows on re-ingest or on bulk/XML overlap.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from talonx_ingest.config import settings
from talonx_ingest.intelligence.domain import EvidenceRecord, SourceType
from talonx_ingest.intelligence.insider.config import INSIDER_STORE_SCHEMA_VERSION
from talonx_ingest.intelligence.insider.domain import (
    AcquiredDisposed,
    InsiderFiling,
    InsiderRole,
    InsiderTransaction,
    OwnershipFormType,
    OwnershipNature,
    TransactionClass,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS insider_filings (
    insider_filing_id   TEXT PRIMARY KEY,
    accession           TEXT NOT NULL,
    event_id            TEXT,
    symbol              TEXT NOT NULL,
    issuer_cik          TEXT NOT NULL,
    company_name        TEXT NOT NULL DEFAULT '',
    form_type           TEXT NOT NULL,
    is_amendment        INTEGER NOT NULL DEFAULT 0,
    amends_accession    TEXT,
    accepted_at_utc     TEXT,
    filing_date         TEXT,
    period_of_report    TEXT,
    n_transactions      INTEGER NOT NULL DEFAULT 0,
    n_owners            INTEGER NOT NULL DEFAULT 0,
    owner_ciks          TEXT NOT NULL DEFAULT '[]',
    owner_names         TEXT NOT NULL DEFAULT '[]',
    source_reference    TEXT NOT NULL DEFAULT '',
    ingested_at_utc     TEXT NOT NULL,
    data_quality_flags  TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_if_symbol ON insider_filings (symbol);
CREATE INDEX IF NOT EXISTS idx_if_accepted ON insider_filings (accepted_at_utc);

CREATE TABLE IF NOT EXISTS insider_transactions (
    transaction_id          TEXT PRIMARY KEY,
    schema_version          TEXT NOT NULL,
    event_id                TEXT,
    accession               TEXT NOT NULL,
    issuer_cik              TEXT NOT NULL,
    symbol                  TEXT NOT NULL,
    company_name            TEXT NOT NULL DEFAULT '',
    accepted_at_utc         TEXT,
    filing_date             TEXT,
    transaction_date        TEXT,
    period_of_report        TEXT,
    owner_cik               TEXT,
    owner_name              TEXT NOT NULL DEFAULT '',
    owner_role              TEXT NOT NULL,
    owner_roles             TEXT NOT NULL DEFAULT '[]',
    is_director             INTEGER NOT NULL DEFAULT 0,
    is_officer              INTEGER NOT NULL DEFAULT 0,
    is_ten_percent_owner    INTEGER NOT NULL DEFAULT 0,
    is_other                INTEGER NOT NULL DEFAULT 0,
    officer_title           TEXT,
    form_type               TEXT NOT NULL,
    is_amendment            INTEGER NOT NULL DEFAULT 0,
    amends_accession        TEXT,
    table_kind              TEXT NOT NULL DEFAULT 'NONDERIVATIVE',
    is_derivative           INTEGER NOT NULL DEFAULT 0,
    transaction_code        TEXT,
    classification          TEXT NOT NULL,
    security_title          TEXT,
    transaction_shares      REAL,
    price_per_share         REAL,
    transaction_value       REAL,
    acquired_disposed       TEXT NOT NULL,
    ownership_nature        TEXT NOT NULL,
    nature_of_ownership_text TEXT,
    shares_owned_after      REAL,
    signed_open_market_shares REAL,
    signed_open_market_value  REAL,
    source_row_sk           TEXT,
    source_reference        TEXT NOT NULL DEFAULT '',
    data_quality_flags      TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_it_symbol ON insider_transactions (symbol);
CREATE INDEX IF NOT EXISTS idx_it_accession ON insider_transactions (accession);
CREATE INDEX IF NOT EXISTS idx_it_owner ON insider_transactions (owner_cik);
CREATE INDEX IF NOT EXISTS idx_it_txn_date ON insider_transactions (transaction_date);
CREATE INDEX IF NOT EXISTS idx_it_symbol_date ON insider_transactions (symbol, transaction_date);
CREATE INDEX IF NOT EXISTS idx_it_class ON insider_transactions (classification);

CREATE TABLE IF NOT EXISTS insider_filing_evidence (
    accession        TEXT NOT NULL,
    transform        TEXT NOT NULL,
    source_provider  TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_url       TEXT,
    exact_timestamp  TEXT,
    retrieved_at     TEXT NOT NULL,
    input_hash       TEXT,
    notes            TEXT,
    PRIMARY KEY (accession, transform)
);
"""


def _iso(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _dt(raw):
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _d(raw):
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _b(v):
    return 1 if v else 0


class InsiderStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else Path(settings.ledger.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES "
            "('insider_store_schema_version', ?) ON CONFLICT(key) DO NOTHING",
            (str(INSIDER_STORE_SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def schema_version(self) -> int:
        r = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key='insider_store_schema_version'"
        ).fetchone()
        return int(r[0]) if r else 0

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------
    def upsert_filing(self, f: InsiderFiling) -> bool:
        existed = self._conn.execute(
            "SELECT 1 FROM insider_filings WHERE insider_filing_id = ?", (f.insider_filing_id,)
        ).fetchone() is not None
        self._conn.execute(
            """
            INSERT OR REPLACE INTO insider_filings (
                insider_filing_id, accession, event_id, symbol, issuer_cik, company_name,
                form_type, is_amendment, amends_accession, accepted_at_utc, filing_date,
                period_of_report, n_transactions, n_owners, owner_ciks, owner_names,
                source_reference, ingested_at_utc, data_quality_flags
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f.insider_filing_id, f.accession, f.event_id, f.symbol.upper(), f.issuer_cik,
                f.company_name, f.form_type.value, _b(f.is_amendment), f.amends_accession,
                _iso(f.accepted_at_utc), _iso(f.filing_date), _iso(f.period_of_report),
                f.n_transactions, f.n_owners, json.dumps(list(f.owner_ciks)),
                json.dumps(list(f.owner_names)), f.source_reference, _iso(f.ingested_at_utc),
                json.dumps(list(f.data_quality_flags)),
            ),
        )
        self._conn.commit()
        return not existed

    def upsert_transaction(self, t: InsiderTransaction) -> bool:
        prior = self.get_transaction(t.transaction_id)
        existed = prior is not None
        if existed:
            t = self._merge(prior, t)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO insider_transactions (
                transaction_id, schema_version, event_id, accession, issuer_cik, symbol,
                company_name, accepted_at_utc, filing_date, transaction_date, period_of_report,
                owner_cik, owner_name, owner_role, owner_roles, is_director, is_officer,
                is_ten_percent_owner, is_other, officer_title, form_type, is_amendment,
                amends_accession, table_kind, is_derivative, transaction_code, classification,
                security_title, transaction_shares, price_per_share, transaction_value,
                acquired_disposed, ownership_nature, nature_of_ownership_text, shares_owned_after,
                signed_open_market_shares, signed_open_market_value, source_row_sk,
                source_reference, data_quality_flags
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                t.transaction_id, t.schema_version, t.event_id, t.accession, t.issuer_cik,
                t.symbol.upper(), t.company_name, _iso(t.accepted_at_utc), _iso(t.filing_date),
                _iso(t.transaction_date), _iso(t.period_of_report), t.owner_cik, t.owner_name,
                t.owner_role.value, json.dumps([r.value for r in t.owner_roles]),
                _b(t.is_director), _b(t.is_officer), _b(t.is_ten_percent_owner), _b(t.is_other),
                t.officer_title, t.form_type.value, _b(t.is_amendment), t.amends_accession,
                t.table, _b(t.is_derivative), t.transaction_code, t.classification.value,
                t.security_title, t.transaction_shares, t.price_per_share, t.transaction_value,
                t.acquired_disposed.value, t.ownership_nature.value, t.nature_of_ownership_text,
                t.shares_owned_after, t.signed_open_market_shares, t.signed_open_market_value,
                t.source_row_sk, t.source_reference, json.dumps(list(t.data_quality_flags)),
            ),
        )
        self._conn.commit()
        return not existed

    # fields that are backfilled from an existing row when the incoming
    # row is missing them -- so ingest order (bulk then XML, or the
    # reverse) does not lose information.
    _BACKFILL_FIELDS = (
        "accepted_at_utc", "event_id", "filing_date", "period_of_report",
        "company_name", "owner_cik", "owner_name", "officer_title",
        "security_title", "transaction_shares", "price_per_share",
        "transaction_value", "shares_owned_after", "nature_of_ownership_text",
        "source_row_sk", "signed_open_market_shares", "signed_open_market_value",
    )
    _COMPLETENESS_FLAGS = frozenset(
        {
            "missing_acceptance_timestamp", "filing_date_used_as_acceptance",
            "owner_cik_missing", "missing_price", "missing_shares",
            "role_unresolved", "missing_transaction_date", "symbol_unresolved",
        }
    )

    def _merge(self, prior: InsiderTransaction, incoming: InsiderTransaction) -> InsiderTransaction:
        """Order-independent merge on ``transaction_id`` conflict: prefer
        the row with fewer 'incompleteness' flags; backfill still-null key
        fields from either side; drop a completeness flag once the field it
        described is populated."""
        p_incomplete = len(set(prior.data_quality_flags) & self._COMPLETENESS_FLAGS)
        i_incomplete = len(set(incoming.data_quality_flags) & self._COMPLETENESS_FLAGS)
        if i_incomplete < p_incomplete:
            base, other = incoming, prior
        elif p_incomplete < i_incomplete:
            base, other = prior, incoming
        elif incoming.source_reference.startswith("SEC_EDGAR_ARCHIVES"):
            base, other = incoming, prior
        else:
            base, other = prior, incoming

        updates: dict = {}
        for fld in self._BACKFILL_FIELDS:
            bv = getattr(base, fld)
            if bv in (None, "", 0.0) and getattr(other, fld) not in (None, ""):
                updates[fld] = getattr(other, fld)
        merged = base.model_copy(update=updates) if updates else base

        flags = set(merged.data_quality_flags)
        if merged.accepted_at_utc is not None:
            flags.discard("missing_acceptance_timestamp")
            flags.discard("filing_date_used_as_acceptance")
        if merged.owner_cik:
            flags.discard("owner_cik_missing")
        if merged.price_per_share not in (None, 0.0):
            flags.discard("missing_price")
        if merged.transaction_shares is not None:
            flags.discard("missing_shares")
        ordered = tuple(f for f in (*prior.data_quality_flags, *incoming.data_quality_flags) if f in flags)
        return merged.model_copy(update={"data_quality_flags": ordered})

    def upsert_batch(
        self,
        filing: InsiderFiling,
        transactions: list[InsiderTransaction],
        evidence: list[EvidenceRecord] | None = None,
    ) -> tuple[int, int]:
        """Returns (new_transactions, total_transactions)."""
        new = sum(1 for t in transactions if self.upsert_transaction(t))
        self.upsert_filing(filing)
        for ev in evidence or []:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO insider_filing_evidence
                    (accession, transform, source_provider, source_record_id, source_url,
                     exact_timestamp, retrieved_at, input_hash, notes)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    filing.accession, ev.transform, ev.source_provider.value,
                    ev.source_record_id, ev.source_url, _iso(ev.exact_timestamp),
                    _iso(ev.retrieved_at), ev.input_hash, ev.notes,
                ),
            )
        self._conn.commit()
        return new, len(transactions)

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def has_transaction(self, tid: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM insider_transactions WHERE transaction_id = ?", (tid,)
        ).fetchone() is not None

    def count_transactions(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0]

    def count_filings(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM insider_filings").fetchone()[0]

    def get_transaction(self, tid: str) -> InsiderTransaction | None:
        r = self._conn.execute(
            "SELECT * FROM insider_transactions WHERE transaction_id = ?", (tid,)
        ).fetchone()
        return self._row_to_txn(r) if r else None

    def get_filing(self, accession: str) -> InsiderFiling | None:
        r = self._conn.execute(
            "SELECT * FROM insider_filings WHERE insider_filing_id = ?", (accession,)
        ).fetchone()
        return self._row_to_filing(r) if r else None

    def query_transactions(
        self,
        *,
        symbol: str | None = None,
        owner_cik: str | None = None,
        accession: str | None = None,
        classification: TransactionClass | str | None = None,
        open_market_only: bool = False,
        since: date | None = None,
        until: date | None = None,
        causal_cutoff: datetime | None = None,
        limit: int | None = None,
        newest_first: bool = True,
    ) -> list[InsiderTransaction]:
        where: list[str] = []
        params: list = []
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())
        if owner_cik:
            where.append("owner_cik = ?")
            params.append(owner_cik)
        if accession:
            where.append("accession = ?")
            params.append(accession)
        if classification is not None:
            where.append("classification = ?")
            params.append(
                classification.value
                if isinstance(classification, TransactionClass)
                else str(classification)
            )
        if open_market_only:
            where.append("classification IN (?, ?)")
            params.extend(
                [
                    TransactionClass.OPEN_MARKET_PURCHASE.value,
                    TransactionClass.OPEN_MARKET_SALE.value,
                ]
            )
        if since is not None:
            where.append("transaction_date >= ?")
            params.append(since.isoformat())
        if until is not None:
            where.append("transaction_date <= ?")
            params.append(until.isoformat())
        if causal_cutoff is not None:
            where.append("(accepted_at_utc IS NULL OR accepted_at_utc <= ?)")
            params.append(_iso(causal_cutoff))
        sql = "SELECT * FROM insider_transactions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY transaction_date " + ("DESC" if newest_first else "ASC")
        sql += ", transaction_id " + ("DESC" if newest_first else "ASC")
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._row_to_txn(r) for r in self._conn.execute(sql, params).fetchall()]

    def latest_filings(self, symbol: str, *, limit: int = 20) -> list[InsiderFiling]:
        rows = self._conn.execute(
            "SELECT * FROM insider_filings WHERE symbol = ? "
            "ORDER BY COALESCE(accepted_at_utc, filing_date) DESC, insider_filing_id DESC LIMIT ?",
            (symbol.upper(), int(limit)),
        ).fetchall()
        return [self._row_to_filing(r) for r in rows]

    def get_filing_evidence(self, accession: str) -> list[EvidenceRecord]:
        rows = self._conn.execute(
            "SELECT * FROM insider_filing_evidence WHERE accession = ? ORDER BY transform",
            (accession,),
        ).fetchall()
        return [
            EvidenceRecord(
                source_provider=SourceType(r["source_provider"]),
                source_record_id=r["source_record_id"],
                source_url=r["source_url"],
                exact_timestamp=_dt(r["exact_timestamp"]),
                retrieved_at=_dt(r["retrieved_at"]),
                transform=r["transform"],
                input_hash=r["input_hash"],
                notes=r["notes"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # hydration
    # ------------------------------------------------------------------
    def _row_to_txn(self, r: sqlite3.Row) -> InsiderTransaction:
        try:
            roles = tuple(InsiderRole(x) for x in json.loads(r["owner_roles"] or "[]"))
        except (ValueError, TypeError):
            roles = ()
        try:
            flags = tuple(json.loads(r["data_quality_flags"] or "[]"))
        except (ValueError, TypeError):
            flags = ()
        return InsiderTransaction(
            transaction_id=r["transaction_id"],
            schema_version=r["schema_version"],
            event_id=r["event_id"],
            accession=r["accession"],
            issuer_cik=r["issuer_cik"],
            symbol=r["symbol"],
            company_name=r["company_name"],
            accepted_at_utc=_dt(r["accepted_at_utc"]),
            filing_date=_d(r["filing_date"]),
            transaction_date=_d(r["transaction_date"]),
            period_of_report=_d(r["period_of_report"]),
            owner_cik=r["owner_cik"],
            owner_name=r["owner_name"],
            owner_role=InsiderRole(r["owner_role"]),
            owner_roles=roles,
            is_director=bool(r["is_director"]),
            is_officer=bool(r["is_officer"]),
            is_ten_percent_owner=bool(r["is_ten_percent_owner"]),
            is_other=bool(r["is_other"]),
            officer_title=r["officer_title"],
            form_type=OwnershipFormType(r["form_type"]),
            is_amendment=bool(r["is_amendment"]),
            amends_accession=r["amends_accession"],
            table=r["table_kind"],
            is_derivative=bool(r["is_derivative"]),
            transaction_code=r["transaction_code"],
            classification=TransactionClass(r["classification"]),
            security_title=r["security_title"],
            transaction_shares=r["transaction_shares"],
            price_per_share=r["price_per_share"],
            transaction_value=r["transaction_value"],
            acquired_disposed=AcquiredDisposed(r["acquired_disposed"]),
            ownership_nature=OwnershipNature(r["ownership_nature"]),
            nature_of_ownership_text=r["nature_of_ownership_text"],
            shares_owned_after=r["shares_owned_after"],
            signed_open_market_shares=r["signed_open_market_shares"],
            signed_open_market_value=r["signed_open_market_value"],
            source_row_sk=r["source_row_sk"],
            source_reference=r["source_reference"],
            data_quality_flags=flags,
        )

    def _row_to_filing(self, r: sqlite3.Row) -> InsiderFiling:
        try:
            flags = tuple(json.loads(r["data_quality_flags"] or "[]"))
        except (ValueError, TypeError):
            flags = ()
        return InsiderFiling(
            insider_filing_id=r["insider_filing_id"],
            accession=r["accession"],
            event_id=r["event_id"],
            symbol=r["symbol"],
            issuer_cik=r["issuer_cik"],
            company_name=r["company_name"],
            form_type=OwnershipFormType(r["form_type"]),
            is_amendment=bool(r["is_amendment"]),
            amends_accession=r["amends_accession"],
            accepted_at_utc=_dt(r["accepted_at_utc"]),
            filing_date=_d(r["filing_date"]),
            period_of_report=_d(r["period_of_report"]),
            n_transactions=r["n_transactions"],
            n_owners=r["n_owners"],
            owner_ciks=tuple(json.loads(r["owner_ciks"] or "[]")),
            owner_names=tuple(json.loads(r["owner_names"] or "[]")),
            source_reference=r["source_reference"],
            ingested_at_utc=_dt(r["ingested_at_utc"]),
            data_quality_flags=flags,
        )
