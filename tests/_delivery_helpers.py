"""
tests/_delivery_helpers.py
--------------------------
Shared builders for the Task 96F Telegram-delivery tests. Not a test module.
Builds a fully-populated Task 96A ``AlertCard`` already carrying the Task
96E band + reasons, plus the optional 96C ``what_changed`` / 96D
``InsiderActivity`` fact inputs.
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed
from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.pipeline import build_alert_card
from talonx_ingest.intelligence.significance import evaluate_significance
from talonx_ingest.intelligence.significance.alert_integration import apply_significance
from _significance_helpers import (  # noqa: F401  (re-exported for convenience)
    NOW,
    mk_comparison,
    mk_event,
    mk_insider_activity,
)


def make_card(
    *,
    event_type: EventType = EventType.EARNINGS_RESULTS,
    symbol: str = "MSFT",
    company: str | None = None,
    items: tuple[str, ...] = ("2.02", "9.01"),
    form_type: str = "8-K",
    accession: str | None = None,
    age_hours: float = 1.0,
    on_watchlist: bool = False,
    pinned: bool = False,
    comparison=None,
    insider_activity=None,
    quality_flags: tuple[str, ...] = (),
    now=NOW,
):
    """Return (card, what_changed_dict_or_None)."""
    kw = dict(
        event_type=event_type,
        symbol=symbol,
        items=items,
        form_type=form_type,
        age_hours=age_hours,
        quality_flags=quality_flags,
        now=now,
    )
    if accession is not None:
        kw["accession"] = accession
    ev = mk_event(**kw)
    if company is not None:
        ev = ev.model_copy(update={"company_name": company})
    # give it a real filing index url for evidence rendering
    ev = ev.model_copy(
        update={
            "filing_index_url": (
                f"https://www.sec.gov/Archives/edgar/data/789019/"
                f"{ev.accession.replace('-', '')}/{ev.accession}-index.htm"
            )
        }
    )
    sig = evaluate_significance(
        ev,
        comparison=comparison,
        insider_activity=insider_activity,
        on_watchlist=on_watchlist,
        pinned=pinned,
        now=now,
    )
    card = apply_significance(build_alert_card(ev), sig)
    wc = build_what_changed(comparison) if comparison is not None else None
    return card, wc
