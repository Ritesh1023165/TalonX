"""
talonx_ingest.intelligence.insider.identity
===========================================
Deterministic, restart-stable identity for insider filings and
transactions.

``transaction_id`` is **content-addressed**: a sha256 over the identifying
fields of the transaction (accession, owner, date, code, security, shares,
price, acquired/disposed, ownership nature, derivative flag). The same
transaction reaching the pipeline through the quarterly **bulk** route and
through the per-filing **XML** route therefore resolves to the *same* id,
so the two sources deduplicate. When one filing genuinely reports two
identical transactions (same everything), a deterministic ``#ordinal``
suffix disambiguates and the row is flagged ``id_collision_ordinal``.
No random UUID is ever the sole identity.
"""
from __future__ import annotations

from datetime import date

from talonx_ingest.intelligence.identity import normalize_accession, source_hash

__all__ = ["transaction_id_base", "with_ordinal", "insider_filing_id"]


def _num(x: float | None) -> str:
    return "?" if x is None else f"{float(x):.6f}"


def insider_filing_id(accession: str) -> str:
    return normalize_accession(accession)


def transaction_id_base(
    *,
    accession: str,
    owner_cik: str | None,
    transaction_date: date | None,
    transaction_code: str | None,
    security_title: str | None,
    shares: float | None,
    price: float | None,
    acquired_disposed: str,
    ownership_nature: str,
    is_derivative: bool,
) -> str:
    acc = normalize_accession(accession)
    payload = "|".join(
        [
            acc,
            (owner_cik or "?").strip(),
            transaction_date.isoformat() if transaction_date else "?",
            (transaction_code or "?").strip().upper(),
            (security_title or "?").strip().lower(),
            _num(shares),
            _num(price),
            str(acquired_disposed),
            str(ownership_nature),
            "D" if is_derivative else "ND",
        ]
    )
    return f"F4TX:{acc}:{source_hash(payload)[:24]}"


def with_ordinal(base_id: str, ordinal: int) -> str:
    return base_id if ordinal == 0 else f"{base_id}#{ordinal}"
