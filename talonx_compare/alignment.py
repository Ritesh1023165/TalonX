"""Task 83 §2 / Task 83-R1 §3 -- deterministic, session- and event-safe
alignment.

Alignment:
  - partitions PIV records by ``run_scope`` (the PIV session id) and
    compares EACH PIV session independently -- records from two different
    PIV sessions are never aligned against one another;
  - keys events on ``(trading_date, stage, symbol, event_identity)`` so
    two different decisions / two same-symbol events on one day stay
    distinct, and a late arrival re-aligns onto its OWN key without
    replacing an unrelated event;
  - keys aggregates on ``(trading_date, stage, "", "agg:<name>")`` and
    compares aggregate VALUES -- never collapses arbitrary events into a
    single "latest" record;
  - only asserts event-level agreement when the Original run scope is a
    verified, collector-derived scope. If it is ``UNSCOPED`` the pair is
    surfaced but classified ``SOURCE_UNAVAILABLE`` (no agreement claim).

Output ordering is fully deterministic (sorted keys) so a re-run over the
same inputs produces byte-identical comparison evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .divergence import Divergence, classify_divergence
from .identity import KIND_AGGREGATE, UNSCOPED, ComparisonRecord


@dataclass(frozen=True)
class AlignedPair:
    trading_date: str
    stage: str
    symbol: str
    event_identity: str
    record_kind: str
    piv_run_scope: str | None
    original_run_scope: str | None
    original: ComparisonRecord | None
    piv: ComparisonRecord | None

    @property
    def original_session_id(self) -> str | None:
        return self.original.session_id if self.original else None

    @property
    def piv_session_id(self) -> str | None:
        return self.piv.session_id if self.piv else None

    def to_dict(self) -> dict:
        return {
            "trading_date": self.trading_date,
            "stage": self.stage,
            "symbol": self.symbol,
            "event_identity": self.event_identity,
            "record_kind": self.record_kind,
            "piv_run_scope": self.piv_run_scope,
            "original_run_scope": self.original_run_scope,
            "original_session_id": self.original_session_id,
            "piv_session_id": self.piv_session_id,
            "original": self.original.to_dict() if self.original else None,
            "piv": self.piv.to_dict() if self.piv else None,
        }


def _pick(records: list[ComparisonRecord]) -> ComparisonRecord | None:
    """Multiple records under ONE (session, date, stage, symbol,
    event_identity) key means the SAME event was re-projected in a later
    state (e.g. a decision whose status advanced) -- pick the latest by
    event_time then fingerprint. Genuinely different events have different
    event_identity and never land here together."""
    if not records:
        return None
    return sorted(records, key=lambda r: (r.event_time or "", r.payload_fingerprint))[-1]


def _resolve_original_scope(
    original_records: list[ComparisonRecord], explicit: str | None,
) -> str:
    if explicit:
        return explicit
    scopes = {r.run_scope for r in original_records if r.run_scope}
    if len(scopes) == 1:
        return next(iter(scopes))
    return UNSCOPED


def align(
    original_records: Iterable[ComparisonRecord],
    piv_records: Iterable[ComparisonRecord],
    *,
    restrict_trading_date: str | None = None,
    original_run_scope: str | None = None,
) -> list[AlignedPair]:
    o_recs = [
        r for r in original_records
        if restrict_trading_date is None or r.trading_date == restrict_trading_date
    ]
    p_recs = [
        r for r in piv_records
        if restrict_trading_date is None or r.trading_date == restrict_trading_date
    ]
    orig_scope = _resolve_original_scope(o_recs, original_run_scope)

    by_key_o: dict[tuple, list[ComparisonRecord]] = {}
    for rec in o_recs:
        by_key_o.setdefault(rec.alignment_key(), []).append(rec)

    # every distinct PIV session gets its OWN alignment against Original
    piv_by_session: dict[str, list[ComparisonRecord]] = {}
    for rec in p_recs:
        piv_by_session.setdefault(rec.run_scope or "-", []).append(rec)

    pairs: list[AlignedPair] = []
    seen_keys_with_piv: set[tuple] = set()

    for session in sorted(piv_by_session):
        by_key_p: dict[tuple, list[ComparisonRecord]] = {}
        for rec in piv_by_session[session]:
            by_key_p.setdefault(rec.alignment_key(), []).append(rec)
        for key in sorted(set(by_key_o) | set(by_key_p)):
            p = _pick(by_key_p.get(key, []))
            o = _pick(by_key_o.get(key, []))
            if p is None and o is None:
                continue
            if p is not None:
                seen_keys_with_piv.add(key)
            td, stage, symbol, eid = key
            kind = (p or o).record_kind
            pairs.append(AlignedPair(
                trading_date=td, stage=stage, symbol=symbol, event_identity=eid, record_kind=kind,
                piv_run_scope=session if p is not None else None,
                original_run_scope=orig_scope if o is not None else None,
                original=o, piv=p,
            ))

    # Original-only keys not covered by any PIV session (still worth
    # surfacing as LATE_OR_MISSING_STAGE against no PIV session).
    if not piv_by_session:
        for key in sorted(by_key_o):
            o = _pick(by_key_o[key])
            td, stage, symbol, eid = key
            pairs.append(AlignedPair(
                trading_date=td, stage=stage, symbol=symbol, event_identity=eid,
                record_kind=o.record_kind, piv_run_scope=None,
                original_run_scope=orig_scope, original=o, piv=None,
            ))

    return pairs


def compare(
    original_records: Iterable[ComparisonRecord],
    piv_records: Iterable[ComparisonRecord],
    *,
    restrict_trading_date: str | None = None,
    original_run_scope: str | None = None,
    original_source_health_ok: bool = True,
    piv_source_health_ok: bool = True,
) -> tuple[list[AlignedPair], list[Divergence]]:
    """Align, then classify every pair. Returns (pairs, divergences)."""
    pairs = align(
        original_records, piv_records,
        restrict_trading_date=restrict_trading_date, original_run_scope=original_run_scope,
    )
    divergences: list[Divergence] = []
    for pair in pairs:
        # An Original record whose run scope is UNSCOPED can never support
        # an event-level agreement claim.
        if pair.original is not None and pair.piv is not None \
                and (pair.original_run_scope in (None, UNSCOPED)):
            divergences.append(Divergence(
                pair.trading_date, pair.stage, pair.symbol, "SOURCE_UNAVAILABLE",
                "Original run scope is UNSCOPED -- event-level agreement not asserted",
                pair.original.payload_fingerprint, pair.piv.payload_fingerprint,
            ))
            continue
        # Aggregates: compare values, not fingerprints.
        if pair.record_kind == KIND_AGGREGATE:
            d = _classify_aggregate(pair)
            if d is not None:
                divergences.append(d)
            continue
        d = classify_divergence(
            pair.original, pair.piv,
            original_source_health_ok=original_source_health_ok,
            piv_source_health_ok=piv_source_health_ok,
        )
        if d is not None:
            divergences.append(d)
    return pairs, divergences


def _classify_aggregate(pair: AlignedPair) -> Divergence | None:
    o, p = pair.original, pair.piv
    if o is None or p is None:
        # a one-sided aggregate is reported in per_stage_totals; it is not
        # itself a divergence (the other pipeline simply has no equivalent
        # rolled-up counter).
        return None
    if (o.aggregate_value or 0) == (p.aggregate_value or 0):
        return None
    from .divergence import _STAGE_CLASS, DECISION_DIFFERENCE

    return Divergence(
        pair.trading_date, pair.stage, pair.symbol,
        _STAGE_CLASS.get(pair.stage, DECISION_DIFFERENCE),
        f"aggregate {o.aggregate_name!r} differs: ORIGINAL={o.aggregate_value} PIV={p.aggregate_value}",
        o.payload_fingerprint, p.payload_fingerprint,
    )
