"""
talonx_ingest.intelligence.insider.domain
=========================================
Immutable value objects for the insider-intelligence pipeline.

Hard rule (``PRODUCT_CLAIM_POLICY.md`` / ``RISK_LANGUAGE_POLICY.md`` /
Task 95K): nothing here encodes a prediction, direction, sentiment,
"insider signal" or expected return. Fields describe *what was reported*.
``extra="forbid"`` rejects any stray field.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from talonx_ingest.intelligence.domain import EvidenceRecord

_FROZEN = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------
class OwnershipFormType(str, Enum):
    FORM_3 = "3"
    FORM_4 = "4"
    FORM_5 = "5"
    FORM_3_A = "3/A"
    FORM_4_A = "4/A"
    FORM_5_A = "5/A"
    UNKNOWN = "UNKNOWN"


class TransactionClass(str, Enum):
    OPEN_MARKET_PURCHASE = "OPEN_MARKET_PURCHASE"          # code P  (discretionary)
    OPEN_MARKET_SALE = "OPEN_MARKET_SALE"                  # code S  (discretionary)
    GRANT_OR_AWARD = "GRANT_OR_AWARD"                      # code A  (compensation)
    EXERCISE_OR_CONVERSION = "EXERCISE_OR_CONVERSION"      # codes M/C/X/E/H/O
    GIFT = "GIFT"                                          # code G
    TAX_WITHHOLDING = "TAX_WITHHOLDING"                    # code F
    SALE_OR_DISPOSITION_TO_ISSUER = "SALE_OR_DISPOSITION_TO_ISSUER"  # code D
    INHERITANCE = "INHERITANCE"                            # code W
    SMALL_ACQUISITION = "SMALL_ACQUISITION"               # code L
    PLAN_DISCRETIONARY = "PLAN_DISCRETIONARY"             # code I (Rule 16b-3(f))
    EQUITY_SWAP = "EQUITY_SWAP"                            # code K
    TENDER_OF_SHARES = "TENDER_OF_SHARES"                 # code U
    OTHER_ACQ_DISP = "OTHER_ACQ_DISP"                     # codes J/Z/V
    INITIAL_HOLDING = "INITIAL_HOLDING"                   # Form 3 holding row, no transaction
    UNCLASSIFIED = "UNCLASSIFIED"                          # code present but unrecognised


class AcquiredDisposed(str, Enum):
    ACQUIRED = "ACQUIRED"
    DISPOSED = "DISPOSED"
    UNKNOWN = "UNKNOWN"


class OwnershipNature(str, Enum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    UNKNOWN = "UNKNOWN"


class InsiderRole(str, Enum):
    CEO = "CEO"
    CFO = "CFO"
    COO = "COO"
    PRESIDENT = "PRESIDENT"
    CHAIR = "CHAIR"
    GENERAL_COUNSEL = "GENERAL_COUNSEL"
    CHIEF_ACCOUNTING_OFFICER = "CHIEF_ACCOUNTING_OFFICER"
    OFFICER = "OFFICER"
    DIRECTOR = "DIRECTOR"
    TEN_PERCENT_OWNER = "TEN_PERCENT_OWNER"
    OTHER = "OTHER"


class InsiderQualityFlag(str, Enum):
    MISSING_PRICE = "missing_price"
    NOT_APPLICABLE_PRICE = "not_applicable_price"
    MISSING_SHARES = "missing_shares"
    DERIVATIVE_NOT_VALUED = "derivative_not_valued"
    MISSING_TRANSACTION_DATE = "missing_transaction_date"
    MISSING_ACCEPTANCE_TIMESTAMP = "missing_acceptance_timestamp"
    FILING_DATE_USED_AS_ACCEPTANCE = "filing_date_used_as_acceptance"
    AMENDMENT = "amendment"
    AMENDMENT_AMBIGUOUS = "amendment_ambiguous"
    SUPERSEDED_BY_AMENDMENT = "superseded_by_amendment"
    ROLE_UNRESOLVED = "role_unresolved"
    UNKNOWN_TRANSACTION_CODE = "unknown_transaction_code"
    INITIAL_HOLDING = "initial_holding"
    INDIRECT_OWNERSHIP = "indirect_ownership"
    OWNER_CIK_MISSING = "owner_cik_missing"
    SYMBOL_UNRESOLVED = "symbol_unresolved"
    FOOTNOTED_AMOUNT = "footnoted_amount"
    ID_COLLISION_ORDINAL = "id_collision_ordinal"


# ---------------------------------------------------------------------------
# value objects
# ---------------------------------------------------------------------------
class InsiderTransaction(BaseModel):
    model_config = _FROZEN

    transaction_id: str
    schema_version: str = "insider_transaction@v1"

    event_id: str | None = None                # parent INSIDER_TRANSACTION text_events id
    accession: str
    issuer_cik: str
    symbol: str
    company_name: str = ""

    accepted_at_utc: datetime | None = None    # filing acceptance -- the causal instant
    filing_date: date | None = None
    transaction_date: date | None = None
    period_of_report: date | None = None

    owner_cik: str | None = None
    owner_name: str = ""
    owner_role: InsiderRole = InsiderRole.OTHER
    owner_roles: tuple[InsiderRole, ...] = ()
    is_director: bool = False
    is_officer: bool = False
    is_ten_percent_owner: bool = False
    is_other: bool = False
    officer_title: str | None = None

    form_type: OwnershipFormType = OwnershipFormType.FORM_4
    is_amendment: bool = False
    amends_accession: str | None = None

    table: str = "NONDERIVATIVE"               # NONDERIVATIVE | DERIVATIVE
    is_derivative: bool = False

    transaction_code: str | None = None
    classification: TransactionClass = TransactionClass.UNCLASSIFIED
    security_title: str | None = None

    transaction_shares: float | None = None
    price_per_share: float | None = None
    transaction_value: float | None = None     # shares * price, non-derivative + valid price only
    acquired_disposed: AcquiredDisposed = AcquiredDisposed.UNKNOWN

    ownership_nature: OwnershipNature = OwnershipNature.UNKNOWN
    nature_of_ownership_text: str | None = None
    shares_owned_after: float | None = None

    # signed open-market flow: +shares/value for P, -shares/value for S, else None
    signed_open_market_shares: float | None = None
    signed_open_market_value: float | None = None

    source_row_sk: str | None = None           # bulk NONDERIV/DERIV_TRANS surrogate key
    source_reference: str = ""                  # "SEC_FORM345_BULK:<zip>" | "SEC_EDGAR_ARCHIVES:<url>"
    data_quality_flags: tuple[str, ...] = ()

    @property
    def is_open_market_discretionary(self) -> bool:
        return self.classification in (
            TransactionClass.OPEN_MARKET_PURCHASE,
            TransactionClass.OPEN_MARKET_SALE,
        )


class InsiderFiling(BaseModel):
    model_config = _FROZEN

    insider_filing_id: str                      # == accession
    accession: str
    event_id: str | None = None
    symbol: str
    issuer_cik: str
    company_name: str = ""

    form_type: OwnershipFormType = OwnershipFormType.FORM_4
    is_amendment: bool = False
    amends_accession: str | None = None

    accepted_at_utc: datetime | None = None
    filing_date: date | None = None
    period_of_report: date | None = None

    n_transactions: int = 0
    n_owners: int = 0
    owner_ciks: tuple[str, ...] = ()
    owner_names: tuple[str, ...] = ()

    source_reference: str = ""
    ingested_at_utc: datetime
    data_quality_flags: tuple[str, ...] = ()


class RollingOpenMarketAggregate(BaseModel):
    model_config = _FROZEN

    window_calendar_days: int
    as_of_date: date
    total_purchase_value: float = 0.0
    total_sale_value: float = 0.0
    net_value: float = 0.0                      # purchase - sale (descriptive arithmetic)
    net_shares: float = 0.0
    distinct_purchasers: int = 0
    distinct_sellers: int = 0
    transaction_count: int = 0
    largest_single_transaction_value: float | None = None
    largest_single_transaction_id: str | None = None
    purchaser_ciks: tuple[str, ...] = ()
    seller_ciks: tuple[str, ...] = ()
    value_coverage_note: str | None = None      # e.g. "3 of 5 transactions had a usable price"


class InsiderCluster(BaseModel):
    model_config = _FROZEN

    kind: str                                   # MULTIPLE_OPEN_MARKET_BUYERS | MULTIPLE_OPEN_MARKET_SELLERS
    window_calendar_days: int
    as_of_date: date
    distinct_owners: int
    owner_ciks: tuple[str, ...] = ()
    transaction_count: int = 0
    total_value: float | None = None


class RoleSubsetAggregate(BaseModel):
    model_config = _FROZEN

    subset: str                                 # CEO | CFO | CEO_CFO | DIRECTORS | ALL_OFFICERS
    window_calendar_days: int
    as_of_date: date
    purchase_count: int = 0
    sale_count: int = 0
    net_value: float = 0.0
    net_shares: float = 0.0
    distinct_owners: int = 0
    owner_ciks: tuple[str, ...] = ()


class InsiderActivity(BaseModel):
    """Canonical machine-readable insider-activity struct (Phase 17).
    Feeds Task 96E / 96F / 96G. No prose recommendation, no direction."""

    model_config = _FROZEN

    symbol: str
    issuer_cik: str
    company_name: str = ""
    as_of_date: date
    schema_version: str = "insider_activity@v1"

    latest_filings: tuple[InsiderFiling, ...] = ()
    transactions: tuple[InsiderTransaction, ...] = ()      # recent window
    open_market_aggregates: tuple[RollingOpenMarketAggregate, ...] = ()
    clusters: tuple[InsiderCluster, ...] = ()
    role_subsets: tuple[RoleSubsetAggregate, ...] = ()

    data_quality_flags: tuple[str, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()
