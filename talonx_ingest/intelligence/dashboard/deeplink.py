"""
talonx_ingest.intelligence.dashboard.deeplink
=============================================
Deterministic dashboard routes. Every deep link is built from a **stable
deterministic identity** (96A ``event_id``, symbol, 96C ``comparison_id``)
— never a mutable autoincrement row id — so a link in a Task 96F Telegram
message (or anywhere else) stays valid across restarts and re-ingestion.
"""
from __future__ import annotations

from urllib.parse import quote

ROUTE_TODAY = "/"
ROUTE_WATCHLIST = "/watchlist"
ROUTE_FILINGS = "/filings"
ROUTE_EVIDENCE = "/evidence"
ROUTE_COMPANY = "/company/{symbol}"
ROUTE_EVENT = "/event/{event_id}"
ROUTE_FILING = "/filing/{comparison_id}"
ROUTE_EVENT_EVIDENCE = "/evidence/event/{event_id}"

_API_PREFIX = "/api"


def _seg(s: str) -> str:
    return quote(str(s), safe="")


def company_path(symbol: str) -> str:
    return f"/company/{_seg(symbol.upper())}"


def event_path(event_id: str) -> str:
    return f"/event/{_seg(event_id)}"


def filing_path(comparison_id: str) -> str:
    return f"/filing/{_seg(comparison_id)}"


def event_evidence_path(event_id: str) -> str:
    return f"/evidence/event/{_seg(event_id)}"


def absolute(base_url: str, path: str) -> str:
    """Join a configured public base URL with a dashboard path. ``base_url``
    with no scheme, or a non-http(s) scheme, yields just the path (safe
    default — a bad base never produces a bad link)."""
    b = (base_url or "").strip().rstrip("/")
    if not b.lower().startswith(("http://", "https://")):
        return path
    return b + path


def event_url(event_id: str, *, base_url: str = "") -> str:
    return absolute(base_url, event_path(event_id))


def company_url(symbol: str, *, base_url: str = "") -> str:
    return absolute(base_url, company_path(symbol))


# ---- API mirrors (JSON) ----------------------------------------------
def api_today() -> str:
    return f"{_API_PREFIX}/today"


def api_ranked_events() -> str:
    return f"{_API_PREFIX}/events/ranked"


def api_events() -> str:
    return f"{_API_PREFIX}/events"


def api_event(event_id: str) -> str:
    return f"{_API_PREFIX}/event/{_seg(event_id)}"


def api_company(symbol: str) -> str:
    return f"{_API_PREFIX}/company/{_seg(symbol.upper())}"


def api_filings() -> str:
    return f"{_API_PREFIX}/filings"


def api_filing(comparison_id: str) -> str:
    return f"{_API_PREFIX}/filing/{_seg(comparison_id)}"


def api_insider(symbol: str) -> str:
    return f"{_API_PREFIX}/insider/{_seg(symbol.upper())}"


def api_evidence(event_id: str) -> str:
    return f"{_API_PREFIX}/evidence/{_seg(event_id)}"


def api_freshness() -> str:
    return f"{_API_PREFIX}/freshness"


def api_watchlist() -> str:
    return f"{_API_PREFIX}/watchlist"
