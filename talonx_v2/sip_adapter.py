"""
talonx_v2.sip_adapter -- PQ-2B: Alpaca SIP daily-bar runtime adapter (release provider)
=====================================================================================
Read-only market data (``GET /v2/stocks/bars``).  No broker/order endpoint, no websocket, no
trading credentials beyond the market-data key already configured.

Contract (see ``talonx_v2.provider_contract``): ``feed=sip``, ``timeframe=1Day``,
``adjustment=split`` (SPLIT-ONLY -- never dividend-adjusted; PQ-2A pays dividends as explicit cash).

Fail-closed behaviour: a timeout / HTTP error / 429 / 401-403 / malformed body raises a typed
``ProviderError`` (the resolver turns it into an explicit *unavailable* -- never a fabricated or
zero price).  A row that is malformed (non-finite / non-positive price, negative volume, high<low,
timestamp not at New-York midnight) is DROPPED, and two rows for one session that disagree drop that
session -- so a bad row can never be silently replaced by a neighbour.
"""
from __future__ import annotations

import json
import math
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from talonx_v2.provider_contract import (
    RELEASE_CONTRACT, SETTLE_MARGIN_MINUTES, SIP_QUERY_LAG_MINUTES, ReleaseProviderContract)

ET = ZoneInfo("America/New_York")


class ProviderError(RuntimeError):
    reason = "PROVIDER_ERROR"


class ProviderTimeout(ProviderError):
    reason = "PROVIDER_TIMEOUT"


class ProviderRateLimited(ProviderError):
    reason = "PROVIDER_RATE_LIMITED"


class ProviderEntitlementError(ProviderError):
    reason = "PROVIDER_ENTITLEMENT"


class ProviderMalformed(ProviderError):
    reason = "PROVIDER_MALFORMED_RESPONSE"


def default_http_get(key_id: str, secret: str, timeout_s: float) -> Callable[[str, dict], dict]:
    def _get(url: str, params: dict) -> dict:  # pragma: no cover - network
        req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                     headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise ProviderRateLimited("HTTP 429 rate limited") from e
            if e.code in (401, 403):
                raise ProviderEntitlementError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:120]}") from e
            raise ProviderError(f"HTTP {e.code}") from e
        except (socket.timeout, TimeoutError) as e:
            raise ProviderTimeout("timeout") from e
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
                raise ProviderTimeout("timeout") from e
            raise ProviderError(f"network error: {e.reason}") from e
        except ValueError as e:
            raise ProviderMalformed("invalid JSON") from e
    return _get


def _finite_pos(x) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if (math.isfinite(f) and f > 0.0) else None


def session_of(t: str) -> date | None:
    """Session identity of a daily bar = the New-York calendar date of its timestamp, and the
    timestamp must be New-York midnight (Alpaca: ``...T04:00:00Z`` in EDT, ``...T05:00:00Z`` in EST).
    Anything else (an intraday stamp, a wrong zone, garbage) is not a daily-bar identity."""
    try:
        dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    et = dt.astimezone(ET)
    if (et.hour, et.minute, et.second) != (0, 0, 0):
        return None
    return et.date()


class AlpacaSipBarAdapter:
    """Release daily-bar provider.  ``history()``/``session()`` return rows in the same shape the
    V2 pipeline already consumes, plus provenance keys (``_feed``, ``_source_timestamp`` = provider
    bar ``t``, ``_basis_as_of`` = fetch date, ``_adjustment_state`` = ``SPLIT_ADJUSTED``,
    ``_receipt_timestamp``).  Finality/usability is NOT decided here (the resolver's
    ``FinalityPolicy`` does it) -- this adapter only reports what the provider returned."""
    CONFORMANT = True
    adjustment_state = "SPLIT_ADJUSTED"

    def __init__(self, *, key_id: str | None = None, secret: str | None = None,
                 http_get: Callable[[str, dict], dict] | None = None,
                 now: Callable[[], datetime] | None = None,
                 contract: ReleaseProviderContract = RELEASE_CONTRACT, lookback_sessions: int = 60):
        import os
        self.contract = contract
        self.name = f"alpaca:{contract.feed}:{contract.timeframe}:adjustment={contract.adjustment}"
        self._kid = key_id or os.environ.get("APCA_API_KEY_ID", "")
        self._sec = secret or os.environ.get("APCA_API_SECRET_KEY", "")
        self._get = http_get or default_http_get(self._kid, self._sec, contract.timeout_s)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lb = lookback_sessions
        self._cache: dict[str, tuple[datetime, list[dict]]] = {}
        self.rejected: list[dict] = []          # diagnostics only -- never used as prices

    # ------------------------------------------------------------------ fetch
    def _fetch(self, symbol: str) -> list[dict]:
        sym = symbol.upper()
        now = self._now()
        hit = self._cache.get(sym)
        if hit is not None and (now - hit[0]).total_seconds() < self.contract.cache_ttl_s:
            return hit[1]
        c = self.contract
        params = {"symbols": sym, "timeframe": c.timeframe, "feed": c.feed, "adjustment": c.adjustment,
                  "start": (now.date() - timedelta(days=int(self._lb * 1.6) + 10)).isoformat(),
                  # free-tier SIP: `end` must be >= 15 min old; explicit, never "now"
                  "end": (now - timedelta(minutes=SIP_QUERY_LAG_MINUTES + SETTLE_MARGIN_MINUTES)
                          ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "limit": "1000", "sort": "asc"}
        raw: list[dict] = []
        token = None
        for _ in range(c.max_pages):
            p = dict(params)
            if token:
                p["page_token"] = token
            body = self._get(c.endpoint, p)
            if not isinstance(body, dict) or not isinstance(body.get("bars"), (dict, type(None))):
                raise ProviderMalformed("unexpected response shape")
            raw += list((body.get("bars") or {}).get(sym) or [])
            token = body.get("next_page_token")
            if not token:
                break
        else:
            raise ProviderMalformed("pagination bound exceeded")
        rows = self._rows(sym, raw, receipt=now)
        self._cache[sym] = (now, rows)
        return rows

    def _rows(self, sym: str, raw: list[dict], *, receipt: datetime) -> list[dict]:
        by_date: dict[str, list[dict]] = {}
        basis = receipt.astimezone(timezone.utc).date().isoformat()
        for b in raw:
            if not isinstance(b, dict):
                self.rejected.append({"symbol": sym, "why": "not an object"})
                continue
            d = session_of(b.get("t"))
            o, h, l, cl = (_finite_pos(b.get(k)) for k in ("o", "h", "l", "c"))
            try:
                v = float(b.get("v"))
                v_ok = math.isfinite(v) and v >= 0
            except (TypeError, ValueError):
                v_ok, v = False, 0.0
            if d is None or None in (o, h, l, cl) or not v_ok or h < l:
                self.rejected.append({"symbol": sym, "t": b.get("t"), "why": "malformed daily bar"})
                continue
            by_date.setdefault(d.isoformat(), []).append({
                "date": d.isoformat(), "open": o, "high": h, "low": l, "close": cl, "volume": v,
                "_source_timestamp": str(b["t"]), "_adjustment_state": self.adjustment_state,
                "_basis_as_of": basis, "_feed": self.contract.feed,
                "_receipt_timestamp": receipt.astimezone(timezone.utc).isoformat()})
        rows = []
        for ds, cands in sorted(by_date.items()):
            first = cands[0]
            if any((x["open"], x["close"], x["volume"]) != (first["open"], first["close"], first["volume"])
                   for x in cands[1:]):
                self.rejected.append({"symbol": sym, "date": ds, "why": "conflicting duplicate rows"})
                continue
            rows.append(first)
        return rows

    # -------------------------------------------------------------- interface
    def history(self, symbol: str) -> list[dict]:
        return [dict(r) for r in self._fetch(symbol)]

    def session(self, symbol: str, session: date) -> dict | None:
        s = session.isoformat()
        return next((dict(r) for r in self._fetch(symbol) if r["date"] == s), None)
