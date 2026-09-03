"""
talonx_ingest.intelligence.dashboard.routes
===========================================
Pure route handlers: ``(path, query) -> Response``. No aiohttp import —
``app.py`` adapts these to the server. Every HTML response is
claim-safety scanned before it is returned; a violation is a 500 with a
generic message (fail closed — a bad page never reaches a browser).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from talonx_ingest.intelligence.dashboard import render
from talonx_ingest.intelligence.dashboard.claim_safety import (
    PredictiveLanguageError,
    assert_clean_page,
)
from talonx_ingest.intelligence.dashboard.config import PAGE_SIZE_DEFAULT
from talonx_ingest.intelligence.dashboard.observability import DashboardMetrics
from talonx_ingest.intelligence.dashboard.readapi import IntelligenceReadAPI

_JSON = "application/json"
_HTML = "text/html; charset=utf-8"


@dataclass
class Response:
    status: int
    content_type: str
    body: str
    route: str = "?"
    is_api: bool = False
    is_deep_link: bool = False
    empty: bool = False


def _err_page(code: int, msg: str, route: str) -> Response:
    return Response(code, _HTML, render.render_error(code, msg), route=route)


def _safe_html(html: str, route: str, *, metrics: DashboardMetrics | None = None,
               is_deep_link: bool = False, empty: bool = False) -> Response:
    try:
        assert_clean_page(html)
    except PredictiveLanguageError:
        if metrics is not None:
            metrics.record_claim_safety_rejection()
        return _err_page(500, "This page could not be rendered safely.", route)
    return Response(200, _HTML, html, route=route, is_deep_link=is_deep_link, empty=empty)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _symbols(q: dict) -> list[str]:
    raw = q.get("symbols") or q.get("symbol") or ""
    return [s.strip().upper() for s in raw.replace(" ", ",").split(",") if s.strip()]


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------
def handle(api: IntelligenceReadAPI, method: str, path: str, query: dict,
           *, metrics: DashboardMetrics | None = None) -> Response:
    if method not in ("GET", "HEAD"):
        return _err_page(405, "Method not allowed.", path)
    try:
        resp = _route(api, path, query, metrics=metrics)
    except Exception:  # noqa: BLE001 - never leak a stack trace to the browser
        if metrics is not None:
            metrics.errors += 1
        return _err_page(500, "Something went wrong loading this view.", path)
    if metrics is not None and resp.empty:
        metrics.record_empty()
    if metrics is not None and resp.is_deep_link and resp.status == 200:
        metrics.record_deep_link()
    return resp


def _route(api: IntelligenceReadAPI, path: str, q: dict, *, metrics) -> Response:
    p = path.rstrip("/") or "/"

    # ---- JSON API ---------------------------------------------------
    if p.startswith("/api"):
        return _api(api, p, q)

    # ---- HTML pages ----------------------------------------------
    if p == "/":
        data = api.today()
        if metrics is not None and data["freshness"]["overall"] in ("STALE", "DOWN"):
            metrics.record_stale_view()
        empty = not (data["attention_feed"] or data["earnings"] or data["material_filings"] or data["insider_activity"])
        return _safe_html(render.render_today(data), "/", metrics=metrics, empty=empty)

    if p == "/watchlist":
        syms = _symbols(q)
        pinned = {s for s in _symbols({"symbols": q.get("pinned", "")})}
        rows = api.watchlist_ranked(syms, pinned=pinned) if syms else []
        return _safe_html(render.render_watchlist(rows, symbols=syms), "/watchlist",
                          metrics=metrics, empty=not rows)

    if p == "/filings":
        filters = {
            "symbol": (q.get("symbol") or "").upper() or None,
            "form": q.get("form") or None,
            "item": q.get("item") or None,
            "band": q.get("band") or None,
            "since": q.get("since") or None,
        }
        has_change = None
        if q.get("has_change") in ("1", "true", "yes"):
            has_change = True
        data = api.filings(
            symbol=filters["symbol"], form=filters["form"], item=filters["item"],
            band=filters["band"], since=_parse_dt(filters["since"]), has_change=has_change,
            cursor=q.get("cursor"), limit=int(q.get("limit", PAGE_SIZE_DEFAULT) or PAGE_SIZE_DEFAULT),
        )
        return _safe_html(render.render_filings(data, filters=filters), "/filings",
                          metrics=metrics, empty=not data["items"])

    if p == "/evidence":
        return _safe_html(render.render_evidence_page(), "/evidence", metrics=metrics)

    if p.startswith("/evidence/event/"):
        eid = _unquote(p[len("/evidence/event/"):])
        tr = api.evidence_trace(eid)
        if tr is None:
            return _err_page(404, "No such event.", "/evidence/event")
        return _safe_html(render.render_evidence_trace(tr), "/evidence/event",
                          metrics=metrics, is_deep_link=True)

    if p.startswith("/company/"):
        sym = _unquote(p[len("/company/"):]).upper()
        data = api.company_overview(sym)
        return _safe_html(render.render_company(data), "/company", metrics=metrics,
                          is_deep_link=True, empty=data["event_count"] == 0)

    if p.startswith("/event/"):
        eid = _unquote(p[len("/event/"):])
        row = api.event_detail(eid)
        if row is None:
            return _err_page(404, "No such event.", "/event")
        return _safe_html(render.render_event_detail(row), "/event", metrics=metrics, is_deep_link=True)

    if p.startswith("/filing/"):
        cid = _unquote(p[len("/filing/"):])
        wc = api.comparison_detail(cid)
        if wc is None:
            return _err_page(404, "No such filing comparison.", "/filing")
        return _safe_html(render.render_filing_detail(wc), "/filing", metrics=metrics, is_deep_link=True)

    return _err_page(404, "Page not found.", p)


def _unquote(s: str) -> str:
    from urllib.parse import unquote

    return unquote(s)


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------
def _json(payload, status: int = 200, route: str = "/api") -> Response:
    import json

    disc = {"disclaimer": "Information, not advice. TalonX makes no prediction about future price or returns."}
    if isinstance(payload, dict):
        payload = {**payload, **disc}
    body = json.dumps(payload, default=str, sort_keys=True)
    return Response(status, _JSON, body, route=route, is_api=True)


def _api(api: IntelligenceReadAPI, p: str, q: dict) -> Response:
    limit = int(q.get("limit", PAGE_SIZE_DEFAULT) or PAGE_SIZE_DEFAULT)
    if p == "/api/today":
        return _json(api.today(), route="/api/today")
    if p == "/api/events/ranked":
        return _json(
            api.ranked_events(
                symbols=_symbols(q) or None, min_band=q.get("band") or None,
                event_type=q.get("type") or None, since=_parse_dt(q.get("since")),
                until=_parse_dt(q.get("until")), cursor=q.get("cursor"), limit=limit,
            ),
            route="/api/events/ranked",
        )
    if p == "/api/events":
        return _json({"items": api.latest_events(limit=limit, symbol=(q.get("symbol") or "").upper() or None)},
                     route="/api/events")
    if p.startswith("/api/event/"):
        d = api.event_detail(_unquote(p[len("/api/event/"):]))
        return _json(d, status=200 if d else 404, route="/api/event")
    if p.startswith("/api/company/"):
        return _json(api.company_overview(_unquote(p[len("/api/company/"):]).upper()), route="/api/company")
    if p == "/api/filings":
        return _json(
            api.filings(
                symbol=(q.get("symbol") or "").upper() or None, form=q.get("form") or None,
                item=q.get("item") or None, band=q.get("band") or None,
                since=_parse_dt(q.get("since")), cursor=q.get("cursor"), limit=limit,
            ),
            route="/api/filings",
        )
    if p.startswith("/api/filing/"):
        d = api.comparison_detail(_unquote(p[len("/api/filing/"):]))
        return _json(d, status=200 if d else 404, route="/api/filing")
    if p.startswith("/api/insider/"):
        d = api.insider_activity(_unquote(p[len("/api/insider/"):]).upper())
        return _json(d if d else {"error": "no insider activity"}, status=200 if d else 404, route="/api/insider")
    if p.startswith("/api/evidence/"):
        d = api.evidence_trace(_unquote(p[len("/api/evidence/"):]))
        return _json(d, status=200 if d else 404, route="/api/evidence")
    if p == "/api/freshness":
        return _json(api.freshness_state(), route="/api/freshness")
    if p == "/api/watchlist":
        syms = _symbols(q)
        return _json({"items": api.watchlist_ranked(syms, pinned=set(_symbols({"symbols": q.get("pinned", "")})))
                      if syms else []}, route="/api/watchlist")
    return _json({"error": "unknown endpoint"}, status=404, route="/api")
