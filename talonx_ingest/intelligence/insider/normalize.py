"""
talonx_ingest.intelligence.insider.normalize
============================================
Shared canonicalisation: a raw parsed transaction row (from ``bulk`` or
``ownership_xml``) + its filing / owner context -> a canonical
``InsiderTransaction``.

Deterministic. Value = ``shares * price`` for a non-derivative transaction
with a usable positive price; otherwise ``None`` + an explicit flag
(``missing_price`` for a P/S trade, ``not_applicable_price`` for a grant /
exercise / tax row, ``derivative_not_valued`` for Table II). Nothing is
fabricated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from talonx_ingest.intelligence.insider.codes import (
    acquired_disposed_from_code,
    classify_transaction_code,
)
from talonx_ingest.intelligence.insider.config import MONTH_ABBR
from talonx_ingest.intelligence.insider.domain import (
    AcquiredDisposed,
    InsiderQualityFlag,
    InsiderTransaction,
    OwnershipFormType,
    OwnershipNature,
    TransactionClass,
)
from talonx_ingest.intelligence.insider.identity import transaction_id_base, with_ordinal
from talonx_ingest.intelligence.insider.roles import normalize_role


# ---------------------------------------------------------------------------
# raw inputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OwnerContext:
    owner_cik: str | None
    owner_name: str
    is_director: bool = False
    is_officer: bool = False
    is_ten_percent_owner: bool = False
    is_other: bool = False
    officer_title: str | None = None


@dataclass(frozen=True)
class FilingContext:
    accession: str
    issuer_cik: str
    symbol: str
    company_name: str = ""
    form_type: OwnershipFormType = OwnershipFormType.FORM_4
    is_amendment: bool = False
    amends_accession: str | None = None
    accepted_at_utc: datetime | None = None
    filing_date: date | None = None
    period_of_report: date | None = None
    source_reference: str = ""
    event_id: str | None = None
    flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RawTransactionRow:
    table: str = "NONDERIVATIVE"                # NONDERIVATIVE | DERIVATIVE
    is_holding: bool = False
    security_title: str | None = None
    transaction_date: str | None = None        # "DD-MON-YYYY" (bulk) | "YYYY-MM-DD" (xml)
    transaction_code: str | None = None
    acquired_disposed: str | None = None       # "A" | "D" | None
    shares: str | float | None = None
    price: str | float | None = None
    shares_owned_after: str | float | None = None
    direct_indirect: str | None = None         # "D" | "I" | None
    nature_of_ownership: str | None = None
    source_row_sk: str | None = None
    amount_footnoted: bool = False


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------
def parse_date_any(raw: str | None) -> date | None:
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # DD-MON-YYYY  (SEC bulk)
    parts = s.replace("/", "-").split("-")
    if len(parts) == 3 and parts[1].upper()[:3] in MONTH_ABBR:
        try:
            return date(int(parts[2]), MONTH_ABBR[parts[1].upper()[:3]], int(parts[0]))
        except ValueError:
            return None
    # ISO YYYY-MM-DD  (possibly with a time component)
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _to_float(raw) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        v = float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return None if v != v else v          # drop NaN


def _s(raw) -> str | None:
    """String field or None -- nulls empty / whitespace / pandas NaN."""
    if raw is None:
        return None
    if isinstance(raw, float) and raw != raw:
        return None
    s = str(raw).strip()
    return s or None


def resolve_ordinals(base_ids: list[str]) -> list[int]:
    """0 for the first occurrence of a base id in a filing, 1, 2, ... for
    each repeat -- so genuinely-identical transactions get distinct ids."""
    seen: dict[str, int] = {}
    out: list[int] = []
    for bid in base_ids:
        n = seen.get(bid, 0)
        out.append(n)
        seen[bid] = n + 1
    return out


# ---------------------------------------------------------------------------
# canonicalisation
# ---------------------------------------------------------------------------
def transaction_base_id(raw: RawTransactionRow, fc: FilingContext, oc: OwnerContext) -> str:
    return transaction_id_base(
        accession=fc.accession,
        owner_cik=oc.owner_cik,
        transaction_date=parse_date_any(raw.transaction_date),
        transaction_code=raw.transaction_code,
        security_title=raw.security_title,
        shares=_to_float(raw.shares),
        price=_to_float(raw.price),
        acquired_disposed=raw.acquired_disposed or "?",
        ownership_nature=(raw.direct_indirect or "?"),
        is_derivative=(raw.table.upper() == "DERIVATIVE"),
    )


def normalize_transaction(
    raw: RawTransactionRow,
    fc: FilingContext,
    oc: OwnerContext,
    *,
    ordinal: int = 0,
) -> InsiderTransaction:
    flags: list[str] = list(fc.flags)
    is_derivative = raw.table.upper() == "DERIVATIVE"

    classification, code_flags = classify_transaction_code(
        raw.transaction_code, is_holding=raw.is_holding
    )
    flags.extend(code_flags)

    role = normalize_role(
        is_director=oc.is_director,
        is_officer=oc.is_officer,
        is_ten_percent_owner=oc.is_ten_percent_owner,
        is_other=oc.is_other,
        officer_title=oc.officer_title,
    )
    flags.extend(role.flags)

    shares = _to_float(raw.shares)
    price = _to_float(raw.price)
    tx_date = parse_date_any(raw.transaction_date)
    if tx_date is None and not raw.is_holding:
        flags.append(InsiderQualityFlag.MISSING_TRANSACTION_DATE.value)

    # --- value -------------------------------------------------------
    value: float | None = None
    if raw.is_holding or classification is TransactionClass.INITIAL_HOLDING:
        pass
    elif is_derivative:
        value = None
        flags.append(InsiderQualityFlag.DERIVATIVE_NOT_VALUED.value)
    elif shares is None:
        flags.append(InsiderQualityFlag.MISSING_SHARES.value)
    elif price is None or price <= 0.0:
        if classification in (
            TransactionClass.OPEN_MARKET_PURCHASE,
            TransactionClass.OPEN_MARKET_SALE,
        ):
            flags.append(InsiderQualityFlag.MISSING_PRICE.value)
        else:
            flags.append(InsiderQualityFlag.NOT_APPLICABLE_PRICE.value)
    else:
        value = round(shares * price, 2)

    # --- acquired / disposed -------------------------------------
    ad_raw = (raw.acquired_disposed or "").strip().upper()[:1]
    if ad_raw == "A":
        acquired_disposed = AcquiredDisposed.ACQUIRED
    elif ad_raw == "D":
        acquired_disposed = AcquiredDisposed.DISPOSED
    else:
        hint = acquired_disposed_from_code(classification)
        acquired_disposed = (
            AcquiredDisposed.ACQUIRED if hint == "A"
            else AcquiredDisposed.DISPOSED if hint == "D"
            else AcquiredDisposed.UNKNOWN
        )

    # --- ownership nature -------------------------------------
    di = (raw.direct_indirect or "").strip().upper()[:1]
    if di == "D":
        ownership_nature = OwnershipNature.DIRECT
    elif di == "I":
        ownership_nature = OwnershipNature.INDIRECT
        flags.append(InsiderQualityFlag.INDIRECT_OWNERSHIP.value)
    else:
        ownership_nature = OwnershipNature.UNKNOWN

    # --- signed open-market flow --------------------------------
    signed_shares = signed_value = None
    if classification is TransactionClass.OPEN_MARKET_PURCHASE and shares is not None:
        signed_shares = shares
        signed_value = value
    elif classification is TransactionClass.OPEN_MARKET_SALE and shares is not None:
        signed_shares = -shares
        signed_value = None if value is None else -value

    if oc.owner_cik is None or not str(oc.owner_cik).strip():
        flags.append(InsiderQualityFlag.OWNER_CIK_MISSING.value)
    if not fc.symbol:
        flags.append(InsiderQualityFlag.SYMBOL_UNRESOLVED.value)
    if fc.is_amendment:
        flags.append(InsiderQualityFlag.AMENDMENT.value)
    if raw.amount_footnoted:
        flags.append(InsiderQualityFlag.FOOTNOTED_AMOUNT.value)
    if fc.accepted_at_utc is None:
        flags.append(InsiderQualityFlag.MISSING_ACCEPTANCE_TIMESTAMP.value)

    base_id = transaction_id_base(
        accession=fc.accession,
        owner_cik=oc.owner_cik,
        transaction_date=tx_date,
        transaction_code=raw.transaction_code,
        security_title=raw.security_title,
        shares=shares,
        price=price,
        acquired_disposed=raw.acquired_disposed or "?",
        ownership_nature=raw.direct_indirect or "?",
        is_derivative=is_derivative,
    )
    tid = with_ordinal(base_id, ordinal)
    if ordinal > 0:
        flags.append(InsiderQualityFlag.ID_COLLISION_ORDINAL.value)

    return InsiderTransaction(
        transaction_id=tid,
        event_id=fc.event_id,
        accession=fc.accession,
        issuer_cik=fc.issuer_cik,
        symbol=fc.symbol,
        company_name=fc.company_name,
        accepted_at_utc=fc.accepted_at_utc,
        filing_date=fc.filing_date,
        transaction_date=tx_date,
        period_of_report=fc.period_of_report,
        owner_cik=(str(oc.owner_cik).strip() or None) if oc.owner_cik is not None else None,
        owner_name=oc.owner_name or "",
        owner_role=role.primary_role,
        owner_roles=role.roles,
        is_director=oc.is_director,
        is_officer=oc.is_officer,
        is_ten_percent_owner=oc.is_ten_percent_owner,
        is_other=oc.is_other,
        officer_title=role.raw_title,
        form_type=fc.form_type,
        is_amendment=fc.is_amendment,
        amends_accession=fc.amends_accession,
        table="DERIVATIVE" if is_derivative else "NONDERIVATIVE",
        is_derivative=is_derivative,
        transaction_code=(_s(raw.transaction_code).upper()[:1] if _s(raw.transaction_code) else None),
        classification=classification,
        security_title=_s(raw.security_title),
        transaction_shares=shares,
        price_per_share=price,
        transaction_value=value,
        acquired_disposed=acquired_disposed,
        ownership_nature=ownership_nature,
        nature_of_ownership_text=_s(raw.nature_of_ownership),
        shares_owned_after=_to_float(raw.shares_owned_after),
        signed_open_market_shares=signed_shares,
        signed_open_market_value=signed_value,
        source_row_sk=(raw.source_row_sk or None),
        source_reference=fc.source_reference,
        data_quality_flags=_dedupe(flags),
    )


def _dedupe(items) -> tuple[str, ...]:
    out: list[str] = []
    for x in items:
        if x and x not in out:
            out.append(x)
    return tuple(out)
