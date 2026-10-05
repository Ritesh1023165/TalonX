"""Provider transport. ONE interface for live HTTP, recorded-response replay and test fixtures.

Request(provider, url, params) -> Response(status, body, headers). Live policy (existing provider controls):
  * R5 off-hours for Alpaca and SEC (frozen data.market_hours_blocked): refused weekday 09:00-16:30 America/New_York
  * spacing: alpaca_bars 1.6 s (frozen data.MIN_SPACING_S), alpaca_meta 2.0 s (frozen universe_source.get),
    sec 0.34 s (frozen phase_d.SEC_SPACING_S), github 1.0 s
  * bounded retry: 429 / 5xx / timeout / connection error -> up to 4 attempts, backoff 2, 4, 8 s, Retry-After honoured
    up to 60 s; other 4xx -> returned once (classified by the caller: 404 may be legitimate absence)
  * exhausted -> TransportExhausted (classified TRANSPORT_OR_PROVIDER_FAILURE; never an empty result)
Credentials: Alpaca keys from the existing .env reader (universe_source.headers); SEC UA = frozen phase_d.SEC_UA.
Secrets are never written to the ledger (headers are not recorded).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

SPACING = {"alpaca_bars": 1.6, "alpaca_meta": 2.0, "sec": 0.34, "github": 1.0}
R5_PROVIDERS = ("alpaca_bars", "alpaca_meta", "sec")
RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_ATTEMPTS, BACKOFF, RETRY_AFTER_CAP = 4, (2.0, 4.0, 8.0), 60.0


@dataclass(frozen=True)
class Request:
    provider: str
    url: str
    params: tuple = ()               # sorted (key, value) pairs, no secrets

    @property
    def key(self) -> str:
        return json.dumps([self.provider, self.url, list(self.params)], separators=(",", ":"))

    def full_url(self) -> str:
        return self.url + ("?" + urllib.parse.urlencode(list(self.params)) if self.params else "")


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict = field(default_factory=dict)
    attempts: int = 1


class TransportExhausted(RuntimeError):
    def __init__(self, msg, attempts):
        super().__init__(msg)
        self.attempts = attempts


class OffHoursRefusal(RuntimeError):
    pass


def req(provider: str, url: str, params: dict | None = None) -> Request:
    return Request(provider, url, tuple(sorted((k, str(v)) for k, v in (params or {}).items())))


class HttpTransport:
    """LIVE transport (production). No caller in this task may use it for a protected scope: the acquirer guards
    every request before calling fetch()."""

    def __init__(self, clock=None, sleep=time.sleep, opener=None):
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self.opener = opener or (lambda r, t: urllib.request.urlopen(r, timeout=t))
        self.last: dict = {}
        self._alpaca = None

    def _headers(self, provider: str) -> dict:
        if provider.startswith("alpaca"):
            if self._alpaca is None:
                from research.event_response_map_v1.universe_source import headers
                self._alpaca = headers()
            return dict(self._alpaca)
        if provider == "sec":
            from research.event_response_map_v1.phase_d import SEC_UA
            return dict(SEC_UA)
        return {"User-Agent": "TalonX research"}

    def fetch(self, r: Request) -> Response:
        from research.event_response_map_v1 import data as D
        last_err = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if r.provider in R5_PROVIDERS and D.market_hours_blocked(self.clock()):
                raise OffHoursRefusal(f"R5: {r.provider} refused during weekday 09:00-16:30 America/New_York")
            wait = SPACING.get(r.provider, 1.0) - (time.monotonic() - self.last.get(r.provider, 0.0))
            if wait > 0:
                self.sleep(wait)
            self.last[r.provider] = time.monotonic()
            try:
                with self.opener(urllib.request.Request(r.full_url(), headers=self._headers(r.provider)), 120) as resp:
                    return Response(resp.status, resp.read(), dict(resp.headers), attempt)
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_STATUSES:
                    return Response(e.code, e.read() if hasattr(e, "read") else b"", dict(e.headers or {}), attempt)
                last_err = f"HTTP {e.code}"
                ra = (e.headers or {}).get("Retry-After")
                delay = min(float(ra), RETRY_AFTER_CAP) if ra and str(ra).isdigit() else BACKOFF[min(attempt - 1, 2)]
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last_err = f"{type(e).__name__}: {e}"
                delay = BACKOFF[min(attempt - 1, 2)]
            if attempt < MAX_ATTEMPTS:
                self.sleep(delay)
        raise TransportExhausted(f"{r.provider} {r.url}: {last_err} after {MAX_ATTEMPTS} attempts", MAX_ATTEMPTS)


class RetryingTransport:
    """Applies the same bounded retry policy to a non-HTTP inner transport (replay / fixtures), so the production
    retry semantics are exercised offline. inner.fetch may raise ConnectionError or return 429 / 5xx."""

    def __init__(self, inner, sleep=lambda s: None):
        self.inner, self.sleep, self.calls = inner, sleep, []

    def fetch(self, r: Request) -> Response:
        last = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.calls.append(r.key)
            try:
                resp = self.inner.fetch(r)
            except (ConnectionError, TimeoutError) as e:
                last = f"{type(e).__name__}: {e}"
            else:
                if resp.status not in RETRY_STATUSES:
                    resp.attempts = attempt
                    return resp
                last = f"HTTP {resp.status}"
            if attempt < MAX_ATTEMPTS:
                self.sleep(BACKOFF[min(attempt - 1, 2)])
        raise TransportExhausted(f"{r.provider} {r.url}: {last} after {MAX_ATTEMPTS} attempts", MAX_ATTEMPTS)
