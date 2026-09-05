"""
talonx_ingest.intelligence.service.replay
=========================================
Phase 26 — take a *known historical* SEC filing, feed it through the exact
production ingest chain as if it had just been discovered, and return a
step-by-step trace:

    EDGAR discovery
      -> 96A TextEvent (stored)
      -> 96C comparison  /  96D insider  (whichever applies)
      -> 96E significance
      -> AlertCard
      -> 96F durable outbox row
      -> 96G dashboard visibility

No external Telegram send. Intended to run against a throwaway ledger DB.
This is the core end-to-end proof for Task 96B.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_ingest.edgar.client import EdgarClient
from talonx_ingest.intelligence.dashboard.readapi import IntelligenceReadAPI
from talonx_ingest.intelligence.domain import EventType, SourceType
from talonx_ingest.intelligence.edgar_normalize import iter_normalized_filings
from talonx_ingest.intelligence.identity import event_id as make_event_id
from talonx_ingest.intelligence.service._ingest import ingest_symbol_filings
from talonx_ingest.intelligence.service._insider import ingest_form_ownership
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
from talonx_ingest.intelligence.service.stores import StoreBundle

_PERIODIC = (EventType.QUARTERLY_FILING, EventType.ANNUAL_FILING)
_INSIDER_FORMS = {"3", "4", "5"}


async def replay_filing(
    *,
    cik: str,
    accession: str,
    symbol: str,
    ledger_path: str,
    config: ServiceConfig | None = None,
    now: datetime | None = None,
) -> dict:
    config = config or ServiceConfig()
    now = now or datetime.now(timezone.utc)
    trace: dict = {"input": {"cik": cik, "accession": accession, "symbol": symbol}, "steps": []}

    stores = StoreBundle.open(ledger_path)
    try:
        async with EdgarClient() as client:
            subs = await client.get_submissions(cik)
            match = next(
                (
                    nf
                    for nf in iter_normalized_filings(subs, symbol=symbol, forms=None)
                    if nf.accession == accession
                ),
                None,
            )
            if match is None:
                trace["error"] = "accession not found in submissions feed"
                return trace
            trace["steps"].append(
                {"step": "edgar_discovery", "form": match.form,
                 "acceptance_utc": match.acceptance_datetime.isoformat()
                 if match.acceptance_datetime else None,
                 "items": list(match.items)}
            )

            base_form = match.form.split("/")[0].upper()
            new_ids: list[str] = []

            if base_form in _INSIDER_FORMS:
                outcome = await ingest_form_ownership(
                    client, stores.insider, stores.events,
                    cik=cik, accession=accession, symbol=symbol,
                    form_type=match.form, accepted_at_utc=match.acceptance_datetime,
                    primary_document=match.primary_document,
                )
                eid = make_event_id(
                    SourceType.SEC_EDGAR_SUBMISSIONS, accession, EventType.INSIDER_TRANSACTION
                )
                trace["steps"].append(
                    {"step": "96D_insider_ingest", "ok": outcome.ok,
                     "transactions_total": outcome.transactions_total,
                     "parent_event_created": outcome.parent_event_created,
                     "error": outcome.error}
                )
                if stores.events.has_event(eid):
                    new_ids.append(eid)
            else:
                si = ingest_symbol_filings(
                    stores.events, subs, symbol=symbol,
                    forms=(base_form,), now=now,
                )
                new_ids.extend(si.new_event_ids or si.all_event_ids)
                trace["steps"].append(
                    {"step": "96A_event_store", "new_event_ids": si.new_event_ids,
                     "all_event_ids": si.all_event_ids}
                )

            engine = EnrichmentEngine(stores, client, config=config)
            outcomes = []
            for eid in dict.fromkeys(new_ids):
                oc = await engine.process_event(eid, origin="replay", now=now)
                outcomes.append(
                    {"event_id": eid, "stage": oc.stage.value,
                     "comparison_state": oc.comparison_state,
                     "insider_state": oc.insider_state,
                     "significance_state": oc.significance_state,
                     "delivery_state": oc.delivery_state,
                     "band": oc.significance_band, "errors": oc.errors}
                )
            trace["steps"].append({"step": "enrichment", "outcomes": outcomes})

        # -- read back through the canonical stores + dashboard read API --
        for eid in dict.fromkeys(new_ids):
            ev = stores.events.get_event(eid)
            sig = stores.significance.get_for_event(eid)
            fc = stores.comparisons.get_comparison_for_current_event(eid)
            trace["steps"].append(
                {
                    "step": "readback",
                    "event_id": eid,
                    "event_in_store": ev is not None,
                    "significance_band": sig.band.value if sig else None,
                    "significance_score": sig.score if sig else None,
                    "has_comparison": fc is not None,
                    "comparison_notable_changes": (
                        len(_notable(fc)) if fc is not None else None
                    ),
                }
            )

        api = IntelligenceReadAPI(ledger_path=ledger_path, now=now)
        try:
            for eid in dict.fromkeys(new_ids):
                detail = api.event_detail(eid)
                trace_row = {
                    "step": "96G_dashboard",
                    "event_id": eid,
                    "visible_in_event_detail": detail is not None,
                    "band": detail.get("band") if detail else None,
                    "in_today_feed": any(
                        i["event_id"] == eid for i in api.today()["attention_feed"]
                    ),
                    "in_company_timeline": any(
                        i["event_id"] == eid
                        for i in api.company_overview(symbol)["timeline"]
                    ),
                }
                trace["steps"].append(trace_row)
        finally:
            api.close()

        outbox_rows = []
        for eid in dict.fromkeys(new_ids):
            for r in stores.outbox.query(limit=200):
                if r.event_id == eid:
                    outbox_rows.append(
                        {"event_id": eid, "delivery_id": r.delivery_id,
                         "state": r.state, "band": r.band, "disposition": r.disposition}
                    )
        trace["steps"].append({"step": "96F_outbox", "rows": outbox_rows})
        trace["new_event_ids"] = list(dict.fromkeys(new_ids))
        return trace
    finally:
        stores.close()


def _notable(fc) -> list:
    from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed

    return build_what_changed(fc).get("notable_changes", [])
