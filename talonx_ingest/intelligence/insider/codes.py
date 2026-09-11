"""
talonx_ingest.intelligence.insider.codes
========================================
Deterministic SEC transaction-code classification.

Discretionary open-market activity is **P and S only**. Grants (A),
exercises/conversions (M/C/X), gifts (G), tax withholding (F), sales to
the issuer (D) and everything else are separate classes and are never
folded into "insider buying / selling". An unrecognised code is
``UNCLASSIFIED`` and stays visible.
"""
from __future__ import annotations

from talonx_ingest.intelligence.insider.config import (
    OPEN_MARKET_DISCRETIONARY_CLASSES,
    TRANSACTION_CODE_CLASS,
)
from talonx_ingest.intelligence.insider.domain import (
    InsiderQualityFlag,
    TransactionClass,
)

__all__ = [
    "classify_transaction_code",
    "is_open_market_discretionary",
    "acquired_disposed_from_code",
]


def classify_transaction_code(
    code: str | None, *, is_holding: bool = False
) -> tuple[TransactionClass, tuple[str, ...]]:
    if is_holding:
        return TransactionClass.INITIAL_HOLDING, (InsiderQualityFlag.INITIAL_HOLDING.value,)
    if not code or not str(code).strip():
        return TransactionClass.UNCLASSIFIED, (InsiderQualityFlag.UNKNOWN_TRANSACTION_CODE.value,)
    c = str(code).strip().upper()[:1]
    cls = TRANSACTION_CODE_CLASS.get(c)
    if cls is None:
        return TransactionClass.UNCLASSIFIED, (InsiderQualityFlag.UNKNOWN_TRANSACTION_CODE.value,)
    return cls, ()


def is_open_market_discretionary(cls: TransactionClass) -> bool:
    return cls in OPEN_MARKET_DISCRETIONARY_CLASSES


_ACQ_CLASSES = {
    TransactionClass.OPEN_MARKET_PURCHASE,
    TransactionClass.GRANT_OR_AWARD,
    TransactionClass.EXERCISE_OR_CONVERSION,
    TransactionClass.SMALL_ACQUISITION,
    TransactionClass.INHERITANCE,
}
_DISP_CLASSES = {
    TransactionClass.OPEN_MARKET_SALE,
    TransactionClass.TAX_WITHHOLDING,
    TransactionClass.SALE_OR_DISPOSITION_TO_ISSUER,
    TransactionClass.GIFT,
    TransactionClass.TENDER_OF_SHARES,
}


def acquired_disposed_from_code(cls: TransactionClass) -> str | None:
    """Best-effort A/D hint from the class, used only when the filing does
    not carry an explicit acquired/disposed code. Returns ``"A"`` / ``"D"``
    / ``None`` (ambiguous -- e.g. M, J)."""
    if cls in _ACQ_CLASSES:
        return "A"
    if cls in _DISP_CLASSES:
        return "D"
    return None
