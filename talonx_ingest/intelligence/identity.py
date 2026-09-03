"""
talonx_ingest.intelligence.identity
===================================
Deterministic, restart-stable logical identity for events and alert cards.

No random UUID is ever the sole identity. Re-fetching the same filing must
yield the same ``event_id``; an amendment (``/A``, which SEC assigns its
own accession) is naturally distinct. See ``EVENT_IDENTITY_SPEC.md``.
"""
from __future__ import annotations

import hashlib
import re

from talonx_ingest.intelligence.domain import EventType, SourceType

# SEC accession canonical form: 10 digits - 2 digits - 6 digits.
_ACCESSION_RE = re.compile(r"^\s*(\d{10})-?(\d{2})-?(\d{6})\s*$")

_SOURCE_PREFIX: dict[SourceType, str] = {
    SourceType.SEC_EDGAR_SUBMISSIONS: "SEC",
    SourceType.SEC_EDGAR_ARCHIVES: "SEC",
    SourceType.SEC_EDGAR_FULLTEXT_RSS: "SEC",
    SourceType.SEC_XBRL: "SEC_XBRL",
    SourceType.SEC_FORM345_BULK: "SEC_F345",
    SourceType.ALPACA_SIP: "ALPACA",
    SourceType.YFINANCE_CALENDAR: "YF_CAL",
}


class AccessionFormatError(ValueError):
    """Raised when a string is not a recognisable SEC accession number."""


def normalize_accession(raw: str) -> str:
    """Return the canonical dashed accession ``NNNNNNNNNN-NN-NNNNNN``.

    Accepts the dashed or undashed 18-digit form. Anything else raises --
    identity must never be derived from a malformed id.
    """
    if raw is None:
        raise AccessionFormatError("accession is None")
    m = _ACCESSION_RE.match(str(raw))
    if not m:
        raise AccessionFormatError(f"not a SEC accession number: {raw!r}")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def event_id(source_type: SourceType, accession: str, event_type: EventType) -> str:
    """``{source_prefix}:{canonical_accession}:{event_type}``.

    Stable across restarts and re-fetches. The ``event_type`` segment is
    what makes a multi-item 8-K resolve to several distinct events that
    still share one accession.
    """
    prefix = _SOURCE_PREFIX.get(source_type, source_type.value)
    return f"{prefix}:{normalize_accession(accession)}:{event_type.value}"


def card_id(symbol: str, accession: str, event_type: EventType) -> str:
    """``{SYMBOL}:{canonical_accession}:{event_type}`` -- the
    ``ALERT_CARD_SPEC.md`` dedup key."""
    return f"{symbol.upper()}:{normalize_accession(accession)}:{event_type.value}"


def alert_id(event_id_value: str) -> str:
    """Deterministic 1:1 alert id for an event id. No randomness -- a
    re-emit of the same event addresses the same card."""
    return f"card:{event_id_value}"


def source_hash(*parts: object) -> str:
    """sha256 hex of the parts joined by ``\\n`` after LF normalisation.

    Used as ``TextEvent.source_hash`` and as ``EvidenceRecord.input_hash``
    so a value can be proven to have been computed from an exact input
    (``EVIDENCE_TRACE_SPEC.md``). Deterministic and order-sensitive.
    """
    norm = "\n".join(
        str("" if p is None else p).replace("\r\n", "\n").replace("\r", "\n")
        for p in parts
    )
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
