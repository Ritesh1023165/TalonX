"""
talonx_ingest.intelligence.service.identity_guard
==================================================
Task 131 Directive 4: CIK/accession-level identity validation for the LIVE
ingest pipeline.

Task 130B (research) established, by direct accession-level evidence, that
a shared ticker symbol can legitimately map to more than one issuer CIK
over time (renames, ticker reuse by an unrelated company, parent/
subsidiary Section-16 co-filers) -- and that a naive symbol-only grouping
can silently merge filings from two different corporate entities into one
"cluster" if left unchecked.

This guard applies the SAME principle prospectively, at ingest time: for
every Form 3/4/5 ownership filing about to be persisted, its OWN
``issuer_cik`` (parsed directly from the filing's own XML -- never
inferred) is compared against the issuer CIK the caller already resolved
authoritatively for that ticker (in production,
:class:`~talonx_ingest.intelligence.service.poller.EdgarPoller` passes the
SAME ``ResolvedSymbol.cik`` a filing was fetched with -- the SEC's own
company_tickers.json resolution, via :class:`CikDirectory`). A mismatch
means this specific filing's own declared issuer does not match the
entity currently, authoritatively associated with that ticker -- it is
DROPPED (never persisted under that ticker), not silently force-mapped
and not silently discarded without a trace: every check (pass or drop) is
returned as an explicit, loggable result, never swallowed.

This does not attempt to resolve every historical rename/reorganisation
(that is Task 130B's own, disclosed, accession-level research artifact,
built after the fact with full hindsight -- not a live, real-time
capability) -- it is a narrower, live, forward-looking safety check: never
persist a filing under a ticker if that filing's own declared issuer CIK
does not match this service's current, authoritative resolution for that
ticker.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("talonx_ingest.intelligence.service.identity_guard")


@dataclass(frozen=True)
class IdentityCheckResult:
    ok: bool
    symbol: str
    accession: str
    expected_cik: str
    filing_issuer_cik: str
    reason: str


def normalize_cik(v: str | int | None) -> str:
    """Same normalization Task 130B's own accession-identity research
    script uses (``_norm_cik``): closes the zero-padding false-ambiguity
    bug found there ('701985' vs '0000701985' being treated as different
    issuers)."""
    if v is None:
        return ""
    s = str(v).strip().lstrip("CIK")
    if not s:
        return ""
    if s.isdigit():
        return s.zfill(10)
    return s


def check_filing_issuer_identity(
    *, symbol: str, accession: str, filing_issuer_cik: str, expected_cik: str,
) -> IdentityCheckResult:
    """Returns an explicit pass/drop decision -- never silently mutates or
    force-maps the filing's own declared issuer CIK. ``expected_cik`` is
    the caller's own authoritative resolution for ``symbol`` (in
    production, the same CIK the filing was FETCHED with)."""
    sym = symbol.upper()
    exp = normalize_cik(expected_cik)
    actual = normalize_cik(filing_issuer_cik)

    if not actual:
        return IdentityCheckResult(
            ok=False, symbol=sym, accession=accession, expected_cik=exp,
            filing_issuer_cik=filing_issuer_cik,
            reason="FILING_HAS_NO_PARSEABLE_ISSUER_CIK")
    if not exp:
        return IdentityCheckResult(
            ok=False, symbol=sym, accession=accession, expected_cik=exp,
            filing_issuer_cik=filing_issuer_cik,
            reason="NO_AUTHORITATIVE_CIK_SUPPLIED_BY_CALLER")
    if actual != exp:
        return IdentityCheckResult(
            ok=False, symbol=sym, accession=accession, expected_cik=exp,
            filing_issuer_cik=filing_issuer_cik,
            reason=f"ISSUER_CIK_MISMATCH: filing declares {actual}, expected {exp} for {sym}")
    return IdentityCheckResult(
        ok=True, symbol=sym, accession=accession, expected_cik=exp,
        filing_issuer_cik=filing_issuer_cik, reason="MATCHES_AUTHORITATIVE_RESOLUTION")


def log_identity_check(result: IdentityCheckResult) -> None:
    if result.ok:
        logger.debug("identity_guard PASS symbol=%s accession=%s cik=%s",
                     result.symbol, result.accession, result.filing_issuer_cik)
    else:
        logger.warning("identity_guard DROP symbol=%s accession=%s reason=%s "
                       "filing_cik=%s expected_cik=%s",
                       result.symbol, result.accession, result.reason,
                       result.filing_issuer_cik, result.expected_cik)
