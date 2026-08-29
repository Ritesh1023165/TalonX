"""Task 83 §2 -- deterministic, timezone-aware alignment.

Records from the two pipelines are aligned STRICTLY on
``(trading_date, stage, symbol)``. Alignment never:
  - compares two different trading dates,
  - compares two different sessions' records under one key without
    recording the session ids on both sides,
  - compares two different symbols.

The output ordering is fully deterministic (sorted by the alignment key)
so a re-run over the same inputs produces byte-identical comparison
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .divergence import Divergence, classify_divergence
from .identity import ComparisonRecord


@dataclass(frozen=True)
class AlignedPair:
    trading_date: str
    stage: str
    symbol: str
    original: ComparisonRecord | None
    piv: ComparisonRecord | None
    original_session_id: str | None
    piv_session_id: str | None

    def to_dict(self) -> dict:
        return {
            "trading_date": self.trading_date,
            "stage": self.stage,
            "symbol": self.symbol,
            "original_session_id": self.original_session_id,
            "piv_session_id": self.piv_session_id,
            "original": self.original.to_dict() if self.original else None,
            "piv": self.piv.to_dict() if self.piv else None,
        }


def _pick(records: list[ComparisonRecord]) -> ComparisonRecord | None:
    """When multiple records share one alignment key (e.g. several events
    for the same symbol/stage), pick deterministically: latest event_time,
    then highest fingerprint. Late arrivals therefore *replace* an earlier
    projection for the same key rather than being dropped."""
    if not records:
        return None
    return sorted(
        records,
        key=lambda r: (r.event_time or "", r.payload_fingerprint),
    )[-1]


def align(
    original_records: Iterable[ComparisonRecord],
    piv_records: Iterable[ComparisonRecord],
    *,
    restrict_trading_date: str | None = None,
) -> list[AlignedPair]:
    """Group both sides by (trading_date, stage, symbol) and pair them.

    ``restrict_trading_date`` hard-limits the whole operation to one ET
    date -- any record for another date is dropped before pairing, so a
    cross-date comparison is structurally impossible.
    """
    by_key_o: dict[tuple[str, str, str], list[ComparisonRecord]] = {}
    by_key_p: dict[tuple[str, str, str], list[ComparisonRecord]] = {}

    for rec in original_records:
        if restrict_trading_date is not None and rec.trading_date != restrict_trading_date:
            continue
        by_key_o.setdefault(rec.alignment_key(), []).append(rec)
    for rec in piv_records:
        if restrict_trading_date is not None and rec.trading_date != restrict_trading_date:
            continue
        by_key_p.setdefault(rec.alignment_key(), []).append(rec)

    pairs: list[AlignedPair] = []
    for key in sorted(set(by_key_o) | set(by_key_p)):
        td, stage, symbol = key
        o = _pick(by_key_o.get(key, []))
        p = _pick(by_key_p.get(key, []))
        pairs.append(AlignedPair(
            trading_date=td, stage=stage, symbol=symbol,
            original=o, piv=p,
            original_session_id=o.session_id if o else None,
            piv_session_id=p.session_id if p else None,
        ))
    return pairs


def compare(
    original_records: Iterable[ComparisonRecord],
    piv_records: Iterable[ComparisonRecord],
    *,
    restrict_trading_date: str | None = None,
    original_source_health_ok: bool = True,
    piv_source_health_ok: bool = True,
) -> tuple[list[AlignedPair], list[Divergence]]:
    """Align, then classify every pair. Returns (pairs, divergences).
    Divergence order follows the deterministic pair order."""
    pairs = align(original_records, piv_records, restrict_trading_date=restrict_trading_date)
    divergences: list[Divergence] = []
    for pair in pairs:
        d = classify_divergence(
            pair.original, pair.piv,
            original_source_health_ok=original_source_health_ok,
            piv_source_health_ok=piv_source_health_ok,
        )
        if d is not None:
            divergences.append(d)
    return pairs, divergences
