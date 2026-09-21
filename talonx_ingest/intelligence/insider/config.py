"""
talonx_ingest.intelligence.insider.config
=========================================
Frozen constants for the insider-intelligence pipeline: SEC
transaction-code -> class mapping, insider-role title patterns, and the
descriptive rolling-window / cluster defaults.

Nothing here is a live tunable. The windows and cluster threshold are the
values in ``INSIDER_INTELLIGENCE_SPEC.md`` and were never fitted to a
return history.
"""
from __future__ import annotations

import re

from talonx_ingest.intelligence.insider.domain import InsiderRole, TransactionClass

# ---------------------------------------------------------------------------
# transform / schema versions
# ---------------------------------------------------------------------------
INSIDER_SCHEMA_VERSION = "insider_transaction@v1"
INSIDER_ACTIVITY_SCHEMA_VERSION = "insider_activity@v1"
INSIDER_STORE_SCHEMA_VERSION = 1

BULK_PARSE_TRANSFORM = "form345_bulk_parse@v1"
XML_PARSE_TRANSFORM = "ownership_xml_parse@v1"
NORMALIZE_TRANSFORM = "insider_transaction_normalize@v1"
CODE_CLASSIFY_TRANSFORM = "transaction_code_classify@v1"
ROLE_NORMALIZE_TRANSFORM = "insider_role_normalize@v1"
VALUE_TRANSFORM = "insider_value_calc@v1"
AGGREGATE_TRANSFORM = "insider_rolling_aggregate@v1"
CLUSTER_TRANSFORM = "insider_cluster@v1"
IDENTITY_TRANSFORM = "insider_transaction_identity@v1"

# ---------------------------------------------------------------------------
# SEC Form 4 transaction codes -> explainable class.
# Discretionary open-market activity is P and S ONLY. Everything else is
# compensation / exercise / gift / tax / other and is shown separately,
# never mixed into "insider buying / selling" counts.
# (SEC Form 4 General Instruction / Table I & II code list.)
# ---------------------------------------------------------------------------
TRANSACTION_CODE_CLASS: dict[str, TransactionClass] = {
    "P": TransactionClass.OPEN_MARKET_PURCHASE,
    "S": TransactionClass.OPEN_MARKET_SALE,
    "A": TransactionClass.GRANT_OR_AWARD,
    "D": TransactionClass.SALE_OR_DISPOSITION_TO_ISSUER,
    "F": TransactionClass.TAX_WITHHOLDING,
    "M": TransactionClass.EXERCISE_OR_CONVERSION,
    "C": TransactionClass.EXERCISE_OR_CONVERSION,
    "X": TransactionClass.EXERCISE_OR_CONVERSION,
    "G": TransactionClass.GIFT,
    "W": TransactionClass.INHERITANCE,
    "L": TransactionClass.SMALL_ACQUISITION,
    "I": TransactionClass.PLAN_DISCRETIONARY,   # Rule 16b-3(f) discretionary transaction
    "J": TransactionClass.OTHER_ACQ_DISP,
    "K": TransactionClass.EQUITY_SWAP,
    "U": TransactionClass.TENDER_OF_SHARES,
    "Z": TransactionClass.OTHER_ACQ_DISP,       # voting-trust deposit/withdrawal
    "E": TransactionClass.EXERCISE_OR_CONVERSION,
    "H": TransactionClass.EXERCISE_OR_CONVERSION,
    "O": TransactionClass.EXERCISE_OR_CONVERSION,
    "V": TransactionClass.OTHER_ACQ_DISP,       # voluntary early report (usually a modifier)
}

OPEN_MARKET_DISCRETIONARY_CLASSES: frozenset[TransactionClass] = frozenset(
    {TransactionClass.OPEN_MARKET_PURCHASE, TransactionClass.OPEN_MARKET_SALE}
)

# ---------------------------------------------------------------------------
# role normalisation -- title regex -> role, tried in order. Only applied
# when the SEC relationship flags mark the owner as an officer. An officer
# whose title matches nothing keeps role OFFICER + the raw title. No role
# is ever inferred that the filing's flags do not support.
# ---------------------------------------------------------------------------
_ROLE_TITLE_RULES: list[tuple[str, InsiderRole]] = [
    (r"\bchief\s+exec", InsiderRole.CEO),
    (r"\bceo\b", InsiderRole.CEO),
    (r"principal\s+executive\s+officer", InsiderRole.CEO),
    (r"\bchief\s+financial", InsiderRole.CFO),
    (r"\bcfo\b", InsiderRole.CFO),
    (r"principal\s+financial\s+officer", InsiderRole.CFO),
    (r"\bchief\s+operating", InsiderRole.COO),
    (r"\bcoo\b", InsiderRole.COO),
    (r"\bchief\s+accounting", InsiderRole.CHIEF_ACCOUNTING_OFFICER),
    (r"principal\s+accounting\s+officer", InsiderRole.CHIEF_ACCOUNTING_OFFICER),
    (r"general\s+counsel", InsiderRole.GENERAL_COUNSEL),
    (r"\bchief\s+legal", InsiderRole.GENERAL_COUNSEL),
    (r"\bpresident\b", InsiderRole.PRESIDENT),
    (r"\bchair(man|woman|person)?\b", InsiderRole.CHAIR),
]
ROLE_TITLE_PATTERNS: list[tuple[re.Pattern, InsiderRole]] = [
    (re.compile(p, re.IGNORECASE), r) for p, r in _ROLE_TITLE_RULES
]

# precedence when an owner has several roles (most specific/senior first)
ROLE_PRECEDENCE: list[InsiderRole] = [
    InsiderRole.CEO,
    InsiderRole.CFO,
    InsiderRole.COO,
    InsiderRole.PRESIDENT,
    InsiderRole.CHIEF_ACCOUNTING_OFFICER,
    InsiderRole.GENERAL_COUNSEL,
    InsiderRole.CHAIR,
    InsiderRole.OFFICER,
    InsiderRole.DIRECTOR,
    InsiderRole.TEN_PERCENT_OWNER,
    InsiderRole.OTHER,
]

# ---------------------------------------------------------------------------
# descriptive rolling aggregation -- CALENDAR days, from INSIDER_INTELLIGENCE_SPEC.md
# ("a rolling window (e.g. 10 and 30 calendar days)"). 90 added for context.
# ---------------------------------------------------------------------------
ROLLING_WINDOWS_CALENDAR_DAYS: tuple[int, ...] = (10, 30, 90)
CLUSTER_WINDOW_CALENDAR_DAYS: int = 30
CLUSTER_MIN_DISTINCT_OWNERS: int = 2
RECENT_TRANSACTIONS_WINDOW_DAYS: int = 90
LATEST_FILINGS_LIMIT: int = 20

ROLE_SUBSETS: tuple[str, ...] = ("CEO", "CFO", "CEO_CFO", "DIRECTORS", "ALL_OFFICERS")

# ---------------------------------------------------------------------------
# SEC bulk DD-MON-YYYY date parsing
# ---------------------------------------------------------------------------
MONTH_ABBR: dict[str, int] = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# form-345 bulk data set URL (historical). Not fetched automatically in
# Task 96D -- the parser takes rows; the URL is documented for 96B backfill.
BULK_URL_TEMPLATE = "https://www.sec.gov/files/dera/data/form-345/{year}q{quarter}_form345.zip"
