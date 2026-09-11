"""
talonx_ingest.intelligence.dashboard.readapi
============================================
``IntelligenceReadAPI`` — a thin, read-only service layer over the
canonical intelligence stores. Returns plain JSON-able dicts.

**No recomputation.** Significance bands / scores / reasons come straight
from the Task 96E ``SignificanceStore``; ranking uses
``significance.ranking``; ``what_changed`` comes from Task 96C; insider
activity from Task 96D. This layer never derives a new band, a direction,
or a return — it reads, joins, paginates and projects.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from talonx_ingest.intelligence.comparison.store import FilingComparisonStore
from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed
from talonx_ingest.intelligence.dashboard.config import (
    COMPANY_TIMELINE_LIMIT,
    PAGE_SIZE_DEFAULT,
    PAGE_SIZE_MAX,
    RULESET_VERSION,
    TODAY_FEED_LIMIT,
    TODAY_PANEL_LIMIT,
    TODAY_WINDOW_HOURS,
    WATCHLIST_TRAILING_DAYS,
)
from talonx_ingest.intelligence.domain import EventType, SignificanceBand, SourceType
from talonx_ingest.intelligence.freshness import SourceFreshnessTracker
from talonx_ingest.intelligence.insider.pipeline import build_insider_activity
from talonx_ingest.intelligence.significance.ranking import rank_watchlist_symbols
from talonx_ingest.intelligence.significance.store import SignificanceStore
from talonx_ingest.intelligence.store import EventStore

_UNSET = object()
_PERIODIC = (EventType.QUARTERLY_FILING, EventType.ANNUAL_FILING)
_MATERIAL_FORMS = ("8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A")
_INSIDER_SOURCE_TYPES = (SourceType.SEC_FORM345_BULK,)
_EDGAR_SOURCE_TYPES = (SourceType.SEC_EDGAR_SUBMISSIONS, SourceType.SEC_EDGAR_ARCHIVES)


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    return str(dt)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _encode_cursor(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()


def _decode_cursor(cur: str | None) -> dict | None:
    if not cur:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(cur.encode()).decode())
    except Exception:  # noqa: BLE001 - a bad cursor just means "from the top"
        return None


class IntelligenceReadAPI:
    def __init__(
        self,
        *,
        ledger_path: str | Path | None = None,
        event_store: EventStore | None = None,
        comparison_store: FilingComparisonStore | None = None,
        insider_store=None,
        significance_store: SignificanceStore | None = None,
        now: datetime | None = None,
        ruleset_version: str = RULESET_VERSION,
    ):
        self._owns = event_store is None
        self.events = event_store or EventStore(ledger_path)
        self.comparisons = comparison_store or FilingComparisonStore(ledger_path)
        if insider_store is None:
            from talonx_ingest.intelligence.insider.store import InsiderStore

            insider_store = InsiderStore(ledger_path)
        self.insider = insider_store
        self.significance = significance_store or SignificanceStore(ledger_path)
        self.freshness = SourceFreshnessTracker(self.events)
        self._now = now
        self.ruleset_version = ruleset_version

    # ------------------------------------------------------------------
    def now(self) -> datetime:
        return _as_utc(self._now) or datetime.now(timezone.utc)

    def close(self) -> None:
        if self._owns:
            for s in (self.events, self.comparisons, self.insider, self.significance):
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass

    def __enter__(self) -> "IntelligenceReadAPI":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    # projection helpers
    # ------------------------------------------------------------------
    def _sig_for(self, event_id: str):
        return self.significance.get_for_event(event_id, ruleset_version=self.ruleset_version)

    def _has_comparison(self, event_id: str) -> str | None:
        fc = self.comparisons.get_comparison_for_current_event(event_id)
        return fc.comparison_id if fc else None

    def _sig_map(self, *, since=None) -> dict:
        """One query -> {event_id: InformationSignificance} for the current
        ruleset (optionally since a time). Avoids an N+1 in list views."""
        rows = self.significance.query(
            ruleset_version=self.ruleset_version, since=_as_utc(since), limit=None
        )
        return {r.event_id: r for r in rows}

    def _comparison_map(self, *, since=None) -> dict:
        """One query -> {current_event_id: comparison_id}."""
        rows = self.comparisons.query_comparisons(since=_as_utc(since), limit=None)
        return {r.current_event_id: r.comparison_id for r in rows}

    def event_row(
        self,
        event,
        *,
        with_comparison_flag: bool = True,
        sig=_UNSET,
        comparison_id=_UNSET,
    ) -> dict:
        sig = self._sig_for(event.event_id) if sig is _UNSET else sig
        if comparison_id is _UNSET:
            cmp_id = self._has_comparison(event.event_id) if with_comparison_flag else None
        else:
            cmp_id = comparison_id
        return {
            "event_id": event.event_id,
            "symbol": event.symbol,
            "company_name": event.company_name,
            "event_type": event.event_type.value,
            "form_type": event.form_type,
            "filing_items": list(event.filing_items or ()),
            "accession": event.accession,
            "accepted_at_utc": _iso(event.accepted_at_utc),
            "filing_date": _iso(event.filing_date),
            "report_period_end": _iso(event.report_period_end),
            "session_bucket": event.session_bucket.value,
            "session_reason": event.session_reason,
            "is_amendment": bool(event.is_amendment),
            "primary_document_url": event.primary_document_url,
            "filing_index_url": event.filing_index_url,
            "freshness": event.freshness.value,
            "data_quality_flags": list(event.data_quality_flags or ()),
            "band": sig.band.value if sig else None,
            "score": sig.score if sig else None,
            "significance_reasons": [r.description for r in sig.reasons] if sig else [],
            "significance_reason_objects": (
                [
                    {
                        "code": r.code,
                        "description": r.description,
                        "points": r.points,
                        "component": r.component,
                        "evidence_ref": r.evidence_ref,
                    }
                    for r in sig.reasons
                ]
                if sig
                else []
            ),
            "significance_ruleset": sig.ruleset_version if sig else None,
            "significance_notes": list(sig.band_caps_applied) if sig else [],
            "has_comparison": cmp_id is not None,
            "comparison_id": cmp_id,
        }

    # ------------------------------------------------------------------
    # events / ranking
    # ------------------------------------------------------------------
    def _event_lookup(self, events: list) -> dict:
        return {e.event_id: e for e in events}

    def _rows_for(self, events: list, *, since=None) -> list[dict]:
        """Build event rows for a list of events with ONE significance query
        and ONE comparison query (no N+1). ``since`` defaults to the oldest
        event's acceptance time so the two batch queries stay bounded."""
        if not events:
            return []
        if since is None:
            oldest = min(
                (_as_utc(e.accepted_at_utc) for e in events if e.accepted_at_utc is not None),
                default=None,
            )
            since = oldest - timedelta(days=1) if oldest else None
        sig_map = self._sig_map(since=since)
        cmp_map = self._comparison_map(since=since)
        return [
            self.event_row(e, sig=sig_map.get(e.event_id), comparison_id=cmp_map.get(e.event_id))
            for e in events
        ]

    def latest_events(self, *, limit: int = PAGE_SIZE_DEFAULT, symbol: str | None = None) -> list[dict]:
        limit = max(1, min(int(limit), PAGE_SIZE_MAX))
        evs = self.events.query_events(symbol=symbol, limit=limit, newest_first=True)
        return self._rows_for(evs)

    def ranked_events(
        self,
        *,
        symbols: list[str] | None = None,
        min_band: str | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: str | None = None,
        limit: int = PAGE_SIZE_DEFAULT,
    ) -> dict:
        """Deterministic page of events ranked by significance.
        Sort: score DESC, accepted_at DESC, event_id ASC (unscored events
        sort last). Cursor is opaque and stable."""
        limit = max(1, min(int(limit), PAGE_SIZE_MAX))
        et = EventType(event_type) if event_type else None
        mb_rank = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
        mb_floor = mb_rank.get(min_band, -1) if min_band else -1
        sym_set = {s.upper() for s in symbols} if symbols else None

        # ONE bounded candidate window + ONE significance map + ONE comparison map
        evs = self.events.query_events(
            symbol=(symbols[0] if symbols and len(symbols) == 1 else None),
            event_type=et,
            since=_as_utc(since),
            until=_as_utc(until),
            limit=PAGE_SIZE_MAX * 8,
            newest_first=True,
        )
        sig_map = self._sig_map(since=since)
        cmp_map = self._comparison_map(since=since)

        keyed: list[tuple[tuple, object, object, str | None]] = []
        for ev in evs:
            if sym_set and ev.symbol not in sym_set:
                continue
            sig = sig_map.get(ev.event_id)
            if mb_floor >= 0 and (sig is None or mb_rank.get(sig.band.value, -1) < mb_floor):
                continue
            ts = _as_utc(ev.accepted_at_utc) or datetime.min.replace(tzinfo=timezone.utc)
            score = sig.score if sig else None
            # scored events first (score DESC), then unscored (score None) by recency
            key = (0 if score is not None else 1, -(score or 0), -ts.timestamp(), ev.event_id)
            keyed.append((key, ev, sig, cmp_map.get(ev.event_id)))

        keyed.sort(key=lambda x: x[0])
        cur = _decode_cursor(cursor)
        start = 0
        if cur is not None:
            after = cur.get("k", [])
            for i, (k, *_r) in enumerate(keyed):
                if list(k) > list(after):
                    start = i
                    break
            else:
                start = len(keyed)
        window = keyed[start : start + limit]
        items = [
            self.event_row(ev, sig=sig, comparison_id=cid) for (_k, ev, sig, cid) in window
        ]
        next_cursor = (
            _encode_cursor({"k": list(window[-1][0])})
            if len(window) == limit and start + limit < len(keyed)
            else None
        )
        return {
            "items": items,
            "next_cursor": next_cursor,
            "count": len(items),
            "total_candidates": len(keyed),
        }

    def event_detail(self, event_id: str) -> dict | None:
        ev = self.events.get_event(event_id)
        if ev is None:
            return None
        row = self.event_row(ev)
        row["exhibits"] = [
            {
                "filename": x.filename,
                "source_url": x.source_url,
                "document_type": x.document_type,
                "description": x.description,
            }
            for x in ev.exhibits
        ]
        row["evidence"] = self._evidence_records(ev.evidence)
        if row["comparison_id"]:
            row["comparison"] = self.comparison_detail(row["comparison_id"])
        if ev.event_type is EventType.INSIDER_TRANSACTION:
            row["insider_activity"] = self.insider_activity(ev.symbol)
        return row

    @staticmethod
    def _evidence_records(records) -> list[dict]:
        return [
            {
                "source_provider": getattr(r.source_provider, "value", r.source_provider),
                "source_record_id": r.source_record_id,
                "source_url": r.source_url,
                "exact_timestamp": _iso(r.exact_timestamp),
                "retrieved_at": _iso(r.retrieved_at),
                "transform": r.transform,
                "input_hash": r.input_hash,
                "notes": r.notes,
            }
            for r in (records or ())
        ]

    # ------------------------------------------------------------------
    # filing comparison
    # ------------------------------------------------------------------
    def latest_comparisons(self, *, symbol: str | None = None, limit: int = PAGE_SIZE_DEFAULT) -> list[dict]:
        limit = max(1, min(int(limit), PAGE_SIZE_MAX))
        fcs = self.comparisons.query_comparisons(symbol=symbol, limit=limit, newest_first=True)
        out = []
        for fc in fcs:
            wc = build_what_changed(fc)
            out.append(
                {
                    "comparison_id": fc.comparison_id,
                    "symbol": fc.symbol,
                    "company_name": fc.company_name,
                    "form_type": fc.form_type,
                    "base_form": fc.base_form,
                    "current_accession": fc.current_accession,
                    "prior_accession": fc.prior_accession,
                    "current_accepted_at_utc": _iso(fc.current_accepted_at_utc),
                    "has_prior": fc.prior_accession is not None,
                    "notable_changes": wc.get("notable_changes", []),
                    "quality_flags": list(fc.data_quality_flags or ()),
                }
            )
        return out

    def comparison_detail(self, comparison_id: str) -> dict | None:
        fc = self.comparisons.get_comparison(comparison_id)
        if fc is None:
            return None
        wc = build_what_changed(fc)
        wc["evidence"] = self._evidence_records(fc.evidence)
        wc["current_document_url"] = fc.current_document_url
        wc["prior_document_url"] = fc.prior_document_url
        wc["current_event_id"] = fc.current_event_id
        wc["prior_event_id"] = fc.prior_event_id
        return wc

    # ------------------------------------------------------------------
    # insider
    # ------------------------------------------------------------------
    def insider_activity(self, symbol: str) -> dict | None:
        try:
            act = build_insider_activity(
                self.insider, symbol.upper(), now=self.now()
            )
        except Exception:  # noqa: BLE001
            return None
        if not act.transactions and not act.latest_filings:
            return None
        return {
            "symbol": act.symbol,
            "company_name": act.company_name,
            "as_of_date": _iso(act.as_of_date),
            "open_market_aggregates": [
                {
                    "window_calendar_days": a.window_calendar_days,
                    "total_purchase_value": a.total_purchase_value,
                    "total_sale_value": a.total_sale_value,
                    "net_value": a.net_value,
                    "net_shares": a.net_shares,
                    "distinct_purchasers": a.distinct_purchasers,
                    "distinct_sellers": a.distinct_sellers,
                    "transaction_count": a.transaction_count,
                    "largest_single_transaction_value": a.largest_single_transaction_value,
                    "value_coverage_note": a.value_coverage_note,
                }
                for a in act.open_market_aggregates
            ],
            "clusters": [
                {
                    "kind": c.kind,
                    "window_calendar_days": c.window_calendar_days,
                    "distinct_owners": c.distinct_owners,
                    "transaction_count": c.transaction_count,
                    "total_value": c.total_value,
                }
                for c in act.clusters
            ],
            "role_subsets": [
                {
                    "subset": r.subset,
                    "window_calendar_days": r.window_calendar_days,
                    "purchase_count": r.purchase_count,
                    "sale_count": r.sale_count,
                    "net_value": r.net_value,
                }
                for r in act.role_subsets
                if r.purchase_count or r.sale_count
            ],
            "open_market_transactions": [
                self._txn_row(t) for t in act.transactions if t.is_open_market_discretionary
            ],
            "other_transactions": [
                self._txn_row(t) for t in act.transactions if not t.is_open_market_discretionary
            ],
            "data_quality_flags": list(act.data_quality_flags or ()),
        }

    @staticmethod
    def _txn_row(t) -> dict:
        return {
            "transaction_id": t.transaction_id,
            "accession": t.accession,
            "owner_name": t.owner_name,
            "owner_role": t.owner_role.value,
            "owner_roles": [r.value for r in t.owner_roles],
            "form_type": t.form_type.value,
            "is_amendment": bool(t.is_amendment),
            "transaction_date": _iso(t.transaction_date),
            "transaction_code": t.transaction_code,
            "classification": t.classification.value,
            "security_title": t.security_title,
            "transaction_shares": t.transaction_shares,
            "price_per_share": t.price_per_share,
            "transaction_value": t.transaction_value,
            "acquired_disposed": t.acquired_disposed.value,
            "ownership_nature": t.ownership_nature.value,
            "data_quality_flags": list(t.data_quality_flags or ()),
        }

    # ------------------------------------------------------------------
    # evidence trace
    # ------------------------------------------------------------------
    def evidence_trace(self, event_id: str) -> dict | None:
        ev = self.events.get_event(event_id)
        if ev is None:
            return None
        out = {
            "event_id": event_id,
            "symbol": ev.symbol,
            "company_name": ev.company_name,
            "accession": ev.accession,
            "event_type": ev.event_type.value,
            "accepted_at_utc": _iso(ev.accepted_at_utc),
            "source_hash": ev.source_hash,
            "filing_index_url": ev.filing_index_url,
            "primary_document_url": ev.primary_document_url,
            "event_evidence": self._evidence_records(ev.evidence),
            "exhibits": [
                {"filename": x.filename, "source_url": x.source_url, "document_type": x.document_type}
                for x in ev.exhibits
            ],
        }
        sig = self._sig_for(event_id)
        if sig:
            out["significance"] = {
                "band": sig.band.value,
                "score": sig.score,
                "ruleset_version": sig.ruleset_version,
                "input_fingerprint": sig.input_fingerprint,
                "reasons": [
                    {"code": r.code, "description": r.description, "points": r.points,
                     "evidence_ref": r.evidence_ref}
                    for r in sig.reasons
                ],
                "band_caps_applied": list(sig.band_caps_applied),
            }
        cmp_id = self._has_comparison(event_id)
        if cmp_id:
            fc = self.comparisons.get_comparison(cmp_id)
            out["comparison_evidence"] = {
                "comparison_id": cmp_id,
                "current_document_url": fc.current_document_url,
                "prior_document_url": fc.prior_document_url,
                "prior_accession": fc.prior_accession,
                "records": self._evidence_records(fc.evidence),
            }
        if ev.event_type is EventType.INSIDER_TRANSACTION:
            out["insider_filing_evidence"] = self._evidence_records(
                self.insider.get_filing_evidence(ev.accession)
            )
        return out

    # ------------------------------------------------------------------
    # freshness
    # ------------------------------------------------------------------
    def freshness_state(self) -> dict:
        sources = []
        for st in (
            SourceType.SEC_EDGAR_SUBMISSIONS,
            SourceType.SEC_XBRL,
            SourceType.SEC_FORM345_BULK,
        ):
            snap = self.freshness.snapshot(st)
            sources.append(
                {
                    "source": st.value,
                    "status": snap.status.value,
                    "reason": snap.reason,
                    "last_poll_success_utc": _iso(snap.last_poll_success_utc),
                    "last_poll_attempt_utc": _iso(snap.last_poll_attempt_utc),
                    "latest_source_event_utc": _iso(snap.latest_source_event_utc),
                    "consecutive_failures": snap.consecutive_failures,
                    "age_seconds": snap.age_seconds,
                }
            )
        worst = "FRESH"
        order = {"FRESH": 0, "UNKNOWN": 1, "STALE": 2, "DOWN": 3}
        for s in sources:
            if order.get(s["status"], 1) > order.get(worst, 0):
                worst = s["status"]
        return {
            "overall": worst,
            "sources": sources,
            "counts": {
                "events": self.events.count_events(),
                "filing_comparisons": self.comparisons.count(),
                "insider_transactions": self.insider.count_transactions(),
                "scored_events": self.significance.count(),
            },
            "comparison_availability": (
                "available" if self.comparisons.count() > 0 else "no filing comparisons stored yet"
            ),
            "as_of_utc": _iso(self.now()),
        }

    # ------------------------------------------------------------------
    # watchlist
    # ------------------------------------------------------------------
    def watchlist_ranked(
        self, symbols: list[str], *, pinned: set[str] | None = None, trailing_days: int = WATCHLIST_TRAILING_DAYS
    ) -> list[dict]:
        pinned = {s.upper() for s in (pinned or set())}
        wide = self.events.query_events(limit=PAGE_SIZE_MAX * 8, newest_first=True)
        lookup = self._event_lookup(wide)
        rows = rank_watchlist_symbols(
            self.significance,
            watchlist=[s.upper() for s in symbols],
            pinned=pinned,
            trailing_days=trailing_days,
            now=self.now(),
            ruleset_version=self.ruleset_version,
            event_lookup=lookup.get,
        )
        out = []
        for r in rows:
            latest_fc = self.comparisons.latest_for_symbol(r.symbol)
            latest_earn = self.events.query_events(
                symbol=r.symbol, event_type=EventType.EARNINGS_RESULTS, limit=1
            )
            top_ev = lookup.get(r.top_event.significance.event_id) if r.top_event else None
            out.append(
                {
                    "symbol": r.symbol,
                    "company_name": (top_ev.company_name if top_ev else ""),
                    "band": r.band.value,
                    "score": r.score,
                    "distinct_event_types": r.distinct_event_types,
                    "latest_event_utc": _iso(r.latest_event_utc),
                    "pinned": r.pinned,
                    "why": list(r.why),
                    "latest_significant_event": (self.event_row(top_ev) if top_ev else None),
                    "last_material_filing": (
                        {
                            "comparison_id": latest_fc.comparison_id,
                            "form_type": latest_fc.form_type,
                            "current_accepted_at_utc": _iso(latest_fc.current_accepted_at_utc),
                            "notable_change_count": len(build_what_changed(latest_fc).get("notable_changes", [])),
                        }
                        if latest_fc
                        else None
                    ),
                    "last_earnings_event_utc": (
                        _iso(latest_earn[0].accepted_at_utc) if latest_earn else None
                    ),
                    "insider_state": self._insider_state_summary(r.symbol),
                    "is_quiet": not r.events,
                }
            )
        return out

    def _insider_state_summary(self, symbol: str) -> dict | None:
        act = self.insider_activity(symbol)
        if act is None:
            return None
        a30 = next((a for a in act["open_market_aggregates"] if a["window_calendar_days"] == 30), None)
        if a30 is None:
            return None
        return {
            "window_calendar_days": 30,
            "net_open_market_value": a30["net_value"],
            "distinct_purchasers": a30["distinct_purchasers"],
            "distinct_sellers": a30["distinct_sellers"],
            "transaction_count": a30["transaction_count"],
            "has_cluster": bool(act["clusters"]),
        }

    # ------------------------------------------------------------------
    # today
    # ------------------------------------------------------------------
    def today(self) -> dict:
        now = self.now()
        since = now - timedelta(hours=TODAY_WINDOW_HOURS)
        feed = self.ranked_events(since=since, limit=TODAY_FEED_LIMIT)
        window_events = self.events.query_events(since=since, until=now, newest_first=True)
        window_rows = self._rows_for(window_events, since=since)

        def _panel(pred, limit):
            return [r for e, r in zip(window_events, window_rows) if pred(e)][:limit]

        earnings = _panel(
            lambda e: e.event_type in (EventType.EARNINGS_RESULTS, EventType.EARNINGS_EXPECTED),
            TODAY_PANEL_LIMIT,
        )
        material = _panel(
            lambda e: e.form_type in _MATERIAL_FORMS
            and e.event_type
            not in (EventType.SHAREHOLDER_VOTE_RESULT, EventType.CHARTER_BYLAW_AMENDMENT,
                    EventType.INSIDER_TRANSACTION),
            TODAY_PANEL_LIMIT,
        )
        insider = _panel(lambda e: e.event_type is EventType.INSIDER_TRANSACTION, TODAY_PANEL_LIMIT)
        return {
            "as_of_utc": _iso(now),
            "window_hours": TODAY_WINDOW_HOURS,
            "attention_feed": feed["items"],
            "attention_feed_next_cursor": feed["next_cursor"],
            "earnings": earnings,
            "material_filings": material,
            "insider_activity": insider,
            "freshness": self.freshness_state(),
        }

    # ------------------------------------------------------------------
    # company
    # ------------------------------------------------------------------
    def company_overview(self, symbol: str) -> dict:
        symbol = symbol.upper()
        evs = self.events.query_events(symbol=symbol, limit=COMPANY_TIMELINE_LIMIT, newest_first=True)
        timeline = self._rows_for(evs)
        latest_scored = next((r for r in timeline if r["band"]), None)
        latest_fc = self.comparisons.latest_for_symbol(symbol)
        return {
            "symbol": symbol,
            "company_name": (evs[0].company_name if evs else ""),
            "latest_band": latest_scored["band"] if latest_scored else None,
            "latest_band_event_id": latest_scored["event_id"] if latest_scored else None,
            "event_count": len(timeline),
            "timeline": timeline,
            "latest_comparison": (
                self.comparison_detail(latest_fc.comparison_id) if latest_fc else None
            ),
            "insider_activity": self.insider_activity(symbol),
            "freshness": self.freshness_state(),
        }

    # ------------------------------------------------------------------
    # filings explorer
    # ------------------------------------------------------------------
    def filings(
        self,
        *,
        form: str | None = None,
        item: str | None = None,
        band: str | None = None,
        symbol: str | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        has_change: bool | None = None,
        cursor: str | None = None,
        limit: int = PAGE_SIZE_DEFAULT,
    ) -> dict:
        limit = max(1, min(int(limit), PAGE_SIZE_MAX))
        et = EventType(event_type) if event_type else None
        evs = self.events.query_events(
            symbol=symbol,
            event_type=et,
            form_type=form,
            since=_as_utc(since),
            until=_as_utc(until),
            limit=PAGE_SIZE_MAX * 8,
            newest_first=True,
        )
        sig_map = self._sig_map(since=since)
        cmp_map = self._comparison_map(since=since)
        keyed: list[tuple[tuple, object, object, str | None]] = []
        for e in evs:
            if e.form_type not in _MATERIAL_FORMS:
                continue
            if item and item not in (e.filing_items or ()):
                continue
            sig = sig_map.get(e.event_id)
            cid = cmp_map.get(e.event_id)
            if band and (sig is None or sig.band.value != band):
                continue
            if has_change is not None and (cid is not None) is not has_change:
                continue
            ts = _as_utc(e.accepted_at_utc) or datetime.min.replace(tzinfo=timezone.utc)
            score = sig.score if sig else None
            key = (0 if score is not None else 1, -(score or 0), -ts.timestamp(), e.event_id)
            keyed.append((key, e, sig, cid))
        keyed.sort(key=lambda x: x[0])
        cur = _decode_cursor(cursor)
        start = 0
        if cur is not None:
            after = cur.get("k", [])
            for i, (k, *_r) in enumerate(keyed):
                if list(k) > list(after):
                    start = i
                    break
            else:
                start = len(keyed)
        window = keyed[start : start + limit]
        items = [self.event_row(e, sig=sig, comparison_id=cid) for (_k, e, sig, cid) in window]
        next_cursor = (
            _encode_cursor({"k": list(window[-1][0])})
            if len(window) == limit and start + limit < len(keyed)
            else None
        )
        return {"items": items, "next_cursor": next_cursor, "count": len(items),
                "total_candidates": len(keyed)}
