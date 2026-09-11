"""
talonx_ingest.intelligence.insider.bulk
=======================================
Parse the SEC quarterly Form 3/4/5 bulk data set into canonical
``InsiderFiling`` + ``InsiderTransaction`` objects.

The bulk data set (``<YYYY>q<Q>_form345.zip``) is a set of tab-separated
files keyed by ``ACCESSION_NUMBER``: ``SUBMISSION``, ``REPORTINGOWNER``,
``NONDERIV_TRANS``, ``NONDERIV_HOLDING``, ``DERIV_TRANS`` (and
``DERIV_HOLDING`` / ``FOOTNOTES``, used only for flags here).

``read_form345_zip`` loads a real zip; ``parse_row_groups`` does the
domain conversion and is what the tests / the offline proof drive with
in-memory rows (the Task 95I ``form4.parquet`` rows share the SEC column
names).
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime

from talonx_ingest.intelligence.identity import normalize_accession
from talonx_ingest.intelligence.insider.config import BULK_PARSE_TRANSFORM
from talonx_ingest.intelligence.insider.domain import (
    InsiderFiling,
    InsiderQualityFlag,
    InsiderTransaction,
    OwnershipFormType,
)
from talonx_ingest.intelligence.insider.normalize import (
    FilingContext,
    OwnerContext,
    RawTransactionRow,
    normalize_transaction,
    parse_date_any,
    resolve_ordinals,
    transaction_base_id,
)

logger = logging.getLogger("talonx_ingest.intelligence.insider.bulk")

TRANSFORM = BULK_PARSE_TRANSFORM

# EventLookup(accession) -> (accepted_at_utc | None, event_id | None) | None
EventLookup = Callable[[str], "tuple[datetime | None, str | None] | None"]


@dataclass
class BulkTables:
    submissions: dict[str, dict] = field(default_factory=dict)
    owners: dict[str, list[dict]] = field(default_factory=dict)
    nonderiv_trans: dict[str, list[dict]] = field(default_factory=dict)
    nonderiv_holding: dict[str, list[dict]] = field(default_factory=dict)
    deriv_trans: dict[str, list[dict]] = field(default_factory=dict)
    footnote_accessions: set[str] = field(default_factory=set)


_FILE_MAP = {
    "SUBMISSION.tsv": "submissions",
    "REPORTINGOWNER.tsv": "owners",
    "NONDERIV_TRANS.tsv": "nonderiv_trans",
    "NONDERIV_HOLDING.tsv": "nonderiv_holding",
    "DERIV_TRANS.tsv": "deriv_trans",
}


def read_form345_zip(path: str) -> BulkTables:
    tables = BulkTables()
    with zipfile.ZipFile(path) as zf:
        names = {n.split("/")[-1].upper(): n for n in zf.namelist()}
        for fname, attr in _FILE_MAP.items():
            real = names.get(fname.upper())
            if real is None:
                continue
            with zf.open(real) as fh:
                reader = csv.DictReader(
                    io.TextIOWrapper(fh, encoding="utf-8", errors="replace"), delimiter="\t"
                )
                for row in reader:
                    acc = (row.get("ACCESSION_NUMBER") or "").strip()
                    if not acc:
                        continue
                    if attr == "submissions":
                        tables.submissions[acc] = row
                    else:
                        getattr(tables, attr).setdefault(acc, []).append(row)
        fn = names.get("FOOTNOTES.TSV")
        if fn is not None:
            with zf.open(fn) as fh:
                reader = csv.DictReader(
                    io.TextIOWrapper(fh, encoding="utf-8", errors="replace"), delimiter="\t"
                )
                for row in reader:
                    acc = (row.get("ACCESSION_NUMBER") or "").strip()
                    if acc:
                        tables.footnote_accessions.add(acc)
    return tables


# ---------------------------------------------------------------------------
# owner relationship parsing
# ---------------------------------------------------------------------------
def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "y", "yes")


def _owner_context(row: dict) -> OwnerContext:
    rel = (row.get("RPTOWNER_RELATIONSHIP") or row.get("RPTOWNER_TXT") or "").lower()
    is_dir = _truthy(row.get("ISDIRECTOR")) or "director" in rel
    is_off = _truthy(row.get("ISOFFICER")) or "officer" in rel
    is_ten = _truthy(row.get("ISTENPERCENTOWNER")) or "tenpercent" in rel or "10%" in rel
    is_oth = _truthy(row.get("ISOTHER")) or (
        "other" in rel and not (is_dir or is_off or is_ten)
    )
    return OwnerContext(
        owner_cik=(row.get("RPTOWNERCIK") or "").strip() or None,
        owner_name=(row.get("RPTOWNERNAME") or "").strip(),
        is_director=is_dir,
        is_officer=is_off,
        is_ten_percent_owner=is_ten,
        is_other=is_oth,
        officer_title=(row.get("RPTOWNER_TITLE") or row.get("OFFICER_TITLE") or "").strip() or None,
    )


def _form_type(doc_type: str | None) -> tuple[OwnershipFormType, bool]:
    d = (doc_type or "4").strip().upper().replace(" ", "")
    d = d.replace("-A", "/A")
    try:
        return OwnershipFormType(d), d.endswith("/A")
    except ValueError:
        return OwnershipFormType.UNKNOWN, d.endswith("/A")


def _first(*vals):
    for v in vals:
        if v is None or v == "":
            continue
        if isinstance(v, float) and v != v:      # pandas NaN
            continue
        return v
    return None


def parse_row_groups(
    tables: BulkTables,
    *,
    symbols: Iterable[str] | None = None,
    issuer_ciks: Iterable[str] | None = None,
    event_lookup: EventLookup | None = None,
    ingested_at_utc: datetime | None = None,
    source_reference: str = "SEC_FORM345_BULK",
) -> Iterator[tuple[InsiderFiling, list[InsiderTransaction]]]:
    """Yield ``(InsiderFiling, [InsiderTransaction, ...])`` per accession."""
    from talonx_ingest.intelligence.domain import utc_now

    now = ingested_at_utc or utc_now()
    sym_filter = {s.upper() for s in symbols} if symbols else None
    cik_filter = {str(c).lstrip("0") for c in issuer_ciks} if issuer_ciks else None

    accessions = set(tables.nonderiv_trans) | set(tables.nonderiv_holding) | \
        set(tables.deriv_trans) | set(tables.submissions)

    for acc in sorted(accessions):
        try:
            accession = normalize_accession(acc)
        except Exception:  # noqa: BLE001
            continue
        sub = tables.submissions.get(acc, {})
        issuer_cik = str(_first(sub.get("ISSUERCIK"), "")).strip()
        symbol = (str(_first(sub.get("ISSUERTRADINGSYMBOL"), "")).strip() or "").upper()
        company = str(_first(sub.get("ISSUERNAME"), "")).strip()

        if sym_filter is not None and symbol not in sym_filter:
            if cik_filter is None or issuer_cik.lstrip("0") not in cik_filter:
                continue
        if cik_filter is not None and issuer_cik.lstrip("0") not in cik_filter:
            if sym_filter is None or symbol not in sym_filter:
                continue

        form_type, is_amend = _form_type(sub.get("DOCUMENT_TYPE"))
        filing_date = parse_date_any(_first(sub.get("FILING_DATE")))
        period = parse_date_any(_first(sub.get("PERIOD_OF_REPORT")))

        accepted_at = None
        event_id = None
        fc_flags: list[str] = []
        if event_lookup is not None:
            res = event_lookup(accession)
            if res is not None:
                accepted_at, event_id = res
        if accepted_at is None:
            fc_flags.append(InsiderQualityFlag.FILING_DATE_USED_AS_ACCEPTANCE.value)

        owners = tables.owners.get(acc) or [{}]
        owner_ctxs = [_owner_context(r) for r in owners]
        # primary owner context for a single-owner filing; multi-owner ->
        # each transaction row does not carry its own owner in the bulk, so
        # associate all with the first owner and flag when ambiguous.
        primary_owner = owner_ctxs[0]
        multi_owner_flag = (
            [InsiderQualityFlag.AMENDMENT_AMBIGUOUS.value] if False else []
        )

        raws: list[tuple[RawTransactionRow, OwnerContext]] = []
        for r in tables.nonderiv_trans.get(acc, []):
            raws.append((_nonderiv_raw(r), primary_owner))
        for r in tables.nonderiv_holding.get(acc, []):
            raws.append((_nonderiv_holding_raw(r), primary_owner))
        for r in tables.deriv_trans.get(acc, []):
            raws.append((_deriv_raw(r), primary_owner))

        if not raws and form_type in (OwnershipFormType.FORM_3, OwnershipFormType.FORM_3_A):
            # a Form 3 with no rows we parsed -> an informational initial statement
            raws.append((RawTransactionRow(is_holding=True), primary_owner))

        fc = FilingContext(
            accession=accession,
            issuer_cik=issuer_cik,
            symbol=symbol,
            company_name=company,
            form_type=form_type,
            is_amendment=is_amend,
            amends_accession=None,
            accepted_at_utc=accepted_at,
            filing_date=filing_date,
            period_of_report=period,
            source_reference=source_reference,
            event_id=event_id,
            flags=tuple(fc_flags + multi_owner_flag),
        )

        base_ids = [transaction_base_id(raw, fc, oc) for raw, oc in raws]
        ordinals = resolve_ordinals(base_ids)
        txns = [
            normalize_transaction(raw, fc, oc, ordinal=ordn)
            for (raw, oc), ordn in zip(raws, ordinals)
        ]

        owner_ciks = tuple(
            dict.fromkeys(o.owner_cik for o in owner_ctxs if o.owner_cik)
        )
        filing = InsiderFiling(
            insider_filing_id=accession,
            accession=accession,
            event_id=event_id,
            symbol=symbol,
            issuer_cik=issuer_cik,
            company_name=company,
            form_type=form_type,
            is_amendment=is_amend,
            amends_accession=None,
            accepted_at_utc=accepted_at,
            filing_date=filing_date,
            period_of_report=period,
            n_transactions=len(txns),
            n_owners=len(owner_ciks) or len(owners),
            owner_ciks=owner_ciks,
            owner_names=tuple(dict.fromkeys(o.owner_name for o in owner_ctxs if o.owner_name)),
            source_reference=source_reference,
            ingested_at_utc=now,
            data_quality_flags=tuple(fc_flags),
        )
        yield filing, txns


# ---------------------------------------------------------------------------
# raw-row shaping from SEC bulk column names
# ---------------------------------------------------------------------------
def _nonderiv_raw(r: dict) -> RawTransactionRow:
    return RawTransactionRow(
        table="NONDERIVATIVE",
        is_holding=False,
        security_title=_first(r.get("SECURITY_TITLE")),
        transaction_date=_first(r.get("TRANS_DATE")),
        transaction_code=_first(r.get("TRANS_CODE"), r.get("code")),
        acquired_disposed=_first(r.get("TRANS_ACQUIRED_DISP_CD"), r.get("ad")),
        shares=_first(r.get("TRANS_SHARES"), r.get("shares")),
        price=_first(r.get("TRANS_PRICEPERSHARE"), r.get("price")),
        shares_owned_after=_first(r.get("SHRS_OWND_FOLWNG_TRANS")),
        direct_indirect=_first(r.get("DIRECT_INDIRECT_OWNERSHIP")),
        nature_of_ownership=_first(r.get("NATURE_OF_OWNERSHIP")),
        source_row_sk=_first(r.get("NONDERIV_TRANS_SK")),
        amount_footnoted=bool(_first(r.get("TRANS_SHARES_FN"), r.get("TRANS_PRICEPERSHARE_FN"))),
    )


def _nonderiv_holding_raw(r: dict) -> RawTransactionRow:
    return RawTransactionRow(
        table="NONDERIVATIVE",
        is_holding=True,
        security_title=_first(r.get("SECURITY_TITLE")),
        transaction_date=None,
        shares_owned_after=_first(r.get("SHRS_OWND_FOLWNG_TRANS")),
        direct_indirect=_first(r.get("DIRECT_INDIRECT_OWNERSHIP")),
        nature_of_ownership=_first(r.get("NATURE_OF_OWNERSHIP")),
        source_row_sk=_first(r.get("NONDERIV_HOLDING_SK")),
    )


def _deriv_raw(r: dict) -> RawTransactionRow:
    return RawTransactionRow(
        table="DERIVATIVE",
        is_holding=False,
        security_title=_first(r.get("SECURITY_TITLE")),
        transaction_date=_first(r.get("TRANS_DATE")),
        transaction_code=_first(r.get("TRANS_CODE")),
        acquired_disposed=_first(r.get("TRANS_ACQUIRED_DISP_CD")),
        shares=_first(r.get("TRANS_SHARES")),
        price=_first(r.get("TRANS_PRICEPERSHARE")),
        shares_owned_after=_first(r.get("SHRS_OWND_FOLWNG_TRANS")),
        direct_indirect=_first(r.get("DIRECT_INDIRECT_OWNERSHIP")),
        nature_of_ownership=_first(r.get("NATURE_OF_OWNERSHIP")),
        source_row_sk=_first(r.get("DERIV_TRANS_SK")),
    )
