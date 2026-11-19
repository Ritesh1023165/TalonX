"""
POST_DELIVERY_ALERT_MARKOUT_V1 -- post-session acquisition (INACTIVE; no caller is scheduled).

Exact-interval requests only, per selected observation:
  bar   Alpaca SIP 1Min, adjustment=raw, start = target bar start, end = start + 59 s (Alpaca ``end`` is inclusive)
  quote Alpaca SIP NBBO quotes in [target - 60 s, target], sort=desc, bounded pages (stop once every quote sharing the
        latest valid timestamp is in hand)

Every call returns ONE typed outcome -- a failure is never an empty success:
  RETRIEVED (payload may be an empty list = provider confirmed no data in the interval)
  TRANSPORT_FAILURE | RATE_LIMITED | ENTITLEMENT_DENIED | REQUEST_REJECTED | MALFORMED_RESPONSE |
  PAGINATION_BOUND_EXCEEDED | BUDGET_EXHAUSTED | R5_REFUSED
Policy: R5 off-hours rule (refuse weekdays 09:00-16:30 America/New_York, DST-aware), <= 40 requests/minute (shared
production quota), bounded retries (429 / 5xx / transport: 2 retries), bounded pages and a per-run time budget.
TLS: the default ``urllib`` context (certificate verification ON); nothing here weakens it.
Entitlement for historical SIP QUOTES is NOT verified by this package (tests use synthetic transports); it is an
activation preflight item.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
QUOTES_URL = "https://data.alpaca.markets/v2/stocks/quotes"
RETRIEVED, TRANSPORT, RATE, ENTITLE, REJECTED, MALFORMED, PAGES, BUDGET, R5 = (
    "RETRIEVED", "TRANSPORT_FAILURE", "RATE_LIMITED", "ENTITLEMENT_DENIED", "REQUEST_REJECTED", "MALFORMED_RESPONSE",
    "PAGINATION_BOUND_EXCEEDED", "BUDGET_EXHAUSTED", "R5_REFUSED")


def r5_permitted(now: datetime) -> bool:
    """R5 off-hours guard: provider calls are refused on weekdays 09:00-16:30 America/New_York."""
    et = now.astimezone(ET)
    if et.weekday() >= 5:
        return True
    mins = et.hour * 60 + et.minute
    return not (9 * 60 <= mins < 16 * 60 + 30)


def _z(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_http(url: str, params: dict, headers: dict, timeout: float) -> tuple[int | None, bytes | str]:
    """(status, body) for an HTTP answer; (None, reason) for a transport failure. Default TLS verification."""
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:500]
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"{type(e).__name__}: {e}"


class AlpacaAcquirer:
    def __init__(self, *, headers: dict, http=default_http, clock=None, sleep=time.sleep, monotonic=time.monotonic,
                 per_minute: int = 40, retries: int = 2, max_pages: int = 5, budget_s: float = 600.0,
                 timeout_s: float = 30.0, provider: str = "alpaca:sip:v2"):
        self.headers, self.http, self.sleep, self.mono = headers, http, sleep, monotonic
        self.clock = clock or (lambda: datetime.now(UTC))
        self.min_interval = 60.0 / per_minute
        self.retries, self.max_pages, self.timeout, self.provider = retries, max_pages, timeout_s, provider
        self._deadline = self.mono() + budget_s
        self._last = None
        self.requests = 0

    @classmethod
    def from_env(cls, **kw):                                   # pragma: no cover - credentials, never in tests
        from talonx_premarket import __main__ as M
        M._env()
        return cls(headers=dict(M._data()._headers), **kw)

    def permitted(self, now: datetime) -> bool:
        return r5_permitted(now)

    # -- one HTTP call with bounded retries and pacing -----------------------------------------------------------
    def _get(self, url: str, params: dict) -> dict:
        if not r5_permitted(self.clock()):
            return {"outcome": R5, "detail": "weekday 09:00-16:30 America/New_York"}
        last = None
        for attempt in range(self.retries + 1):
            if self.mono() >= self._deadline:
                return {"outcome": BUDGET, "detail": "per-run time budget exhausted"}
            if self._last is not None:
                wait = self.min_interval - (self.mono() - self._last)
                if wait > 0:
                    self.sleep(wait)
            self._last = self.mono()
            self.requests += 1
            status, body = self.http(url, params, self.headers, self.timeout)
            if status is None:
                last = {"outcome": TRANSPORT, "detail": str(body)[:200]}
            elif status == 200:
                try:
                    return {"outcome": RETRIEVED, "json": json.loads(body)}
                except (ValueError, TypeError) as e:
                    return {"outcome": MALFORMED, "detail": f"invalid JSON: {e}"}
            elif status in (401, 403):
                return {"outcome": ENTITLE, "detail": f"HTTP {status}: {str(body)[:160]}"}
            elif status == 422 and b"subscription" in (body if isinstance(body, bytes) else str(body).encode()).lower():
                return {"outcome": ENTITLE, "detail": f"HTTP 422 subscription: {str(body)[:160]}"}
            elif status == 429:
                last = {"outcome": RATE, "detail": "HTTP 429"}
            elif status >= 500:
                last = {"outcome": TRANSPORT, "detail": f"HTTP {status}"}
            else:
                return {"outcome": REJECTED, "detail": f"HTTP {status}: {str(body)[:160]}"}
            if attempt < self.retries:
                self.sleep(2.0 * (attempt + 1))
        return last

    # -- bars ------------------------------------------------------------------------------------------------------
    def bar(self, symbol: str, start: datetime) -> dict:
        scope = {"kind": "bar", "symbol": symbol, "start": _z(start), "end": _z(start + timedelta(seconds=59)),
                 "timeframe": "1Min", "feed": "sip", "adjustment": "raw"}
        params = {"symbols": symbol, "timeframe": "1Min", "start": scope["start"], "end": scope["end"],
                  "feed": "sip", "adjustment": "raw", "limit": 10}
        r = self._get(BARS_URL, params)
        if r["outcome"] != RETRIEVED:
            return {**r, "scope": scope}
        j = r["json"]
        if not isinstance(j, dict) or "bars" not in j or not isinstance(j["bars"], (dict, type(None))):
            return {"outcome": MALFORMED, "detail": "missing 'bars' mapping", "scope": scope}
        rows = (j["bars"] or {}).get(symbol, [])
        if not isinstance(rows, list) or j.get("next_page_token"):
            return {"outcome": MALFORMED, "detail": "unexpected bar payload / pagination for a 1-minute scope",
                    "scope": scope}
        return {"outcome": RETRIEVED, "payload": rows, "scope": scope, "provider": self.provider}

    # -- quotes ----------------------------------------------------------------------------------------------------
    def quote(self, symbol: str, target: datetime, max_age_s: int = 60) -> dict:
        scope = {"kind": "quote", "symbol": symbol, "start": _z(target - timedelta(seconds=max_age_s)),
                 "end": _z(target), "feed": "sip", "sort": "desc"}
        params = {"symbols": symbol, "start": scope["start"], "end": scope["end"], "feed": "sip", "sort": "desc",
                  "limit": 50}
        out, token = [], None
        for page in range(self.max_pages):
            p = dict(params, **({"page_token": token} if token else {}))
            r = self._get(QUOTES_URL, p)
            if r["outcome"] != RETRIEVED:
                return {**r, "scope": scope, "pages": page}
            j = r["json"]
            if not isinstance(j, dict) or "quotes" not in j or not isinstance(j["quotes"], (dict, type(None))):
                return {"outcome": MALFORMED, "detail": "missing 'quotes' mapping", "scope": scope}
            rows = (j["quotes"] or {}).get(symbol, [])
            if not isinstance(rows, list):
                return {"outcome": MALFORMED, "detail": "quotes not a list", "scope": scope}
            out.extend(rows)
            token = j.get("next_page_token")
            if not token or _complete(out):
                return {"outcome": RETRIEVED, "payload": out, "scope": {**scope, "pages": page + 1},
                        "provider": self.provider}
        return {"outcome": PAGES, "detail": f"> {self.max_pages} pages without resolving the latest valid quote",
                "scope": scope}


def _complete(rows: list[dict]) -> bool:
    """Descending pages: done once a valid quote exists AND an older quote follows it (all equal-time quotes seen)."""
    from talonx_paperperf.post_delivery_markout import ts_ns
    latest = None
    for q in rows:
        try:
            bid, ask = float(q.get("bp")), float(q.get("ap"))
            qns = ts_ns(q.get("t"))
        except (TypeError, ValueError):
            continue
        if bid > 0 and ask >= bid:
            latest = qns
            break
    if latest is None:
        return False
    older = []
    for q in rows:
        try:
            older.append(ts_ns(q.get("t")) < latest)
        except (TypeError, ValueError):
            continue
    return any(older)
