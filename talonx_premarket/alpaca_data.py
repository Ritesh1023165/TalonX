"""
Alpaca market-data access for the pre-market engine (read-only; no trading endpoints).

Empirically verified contract (2026-09-23, this subscription; see DATA_CONTRACT.md):
* ``GET https://data.alpaca.markets/v2/stocks/bars`` ``timeframe=1Min`` ``feed=sip`` returns
  extended-hours bars from 04:00 ET (AAPL: 217 bars 08:00Z-13:30Z on 2026-09-23).
* SIP data newer than 15 minutes is refused (HTTP 403 "subscription does not permit querying
  recent SIP data"); with no ``end`` the API returns data up to now-15min. Live scans therefore
  request ``end = now - 15 min`` explicitly and label data as delayed.
* ``feed=iex`` is real-time but has NO extended-hours bars (5 AAPL bars all pre-market) -> unusable.
* multi-symbol requests: ``limit`` caps bars per page ACROSS symbols; ``next_page_token`` paginates.
* rate limit header ``X-Ratelimit-Limit: 200`` per minute.
* bar ``t`` is the bar START (UTC); a 1Min bar is complete at ``t + 1 min``.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig

DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets"


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class RateLimiter:
    def __init__(self, per_minute: int, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.per_minute = per_minute
        self.clock, self.sleep = clock, sleep
        self._hits: deque[float] = deque()
        self.waited_s = 0.0

    def acquire(self) -> None:
        now = self.clock()
        while self._hits and now - self._hits[0] >= 60.0:
            self._hits.popleft()
        if len(self._hits) >= self.per_minute:
            wait = 60.0 - (now - self._hits[0]) + 0.05
            self.waited_s += wait
            self.sleep(wait)
            now = self.clock()
            while self._hits and now - self._hits[0] >= 60.0:
                self._hits.popleft()
        self._hits.append(now)


class AlpacaData:
    """``http_get(url, params, headers) -> dict`` is injectable for tests (no network in tests)."""

    def __init__(self, *, key_id: str, secret: str, cfg: PremarketConfig = PREMARKET_RESEARCH_V1,
                 http_get: Callable[[str, dict, dict], dict] | None = None,
                 limiter: RateLimiter | None = None):
        self.cfg = cfg
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}
        self._get = http_get or self._default_get
        self.limiter = limiter or RateLimiter(cfg.max_requests_per_minute)
        self.requests = 0
        self.errors: list[str] = []

    @staticmethod
    def _default_get(url: str, params: dict, headers: dict) -> dict:  # pragma: no cover - network
        u = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(u, headers=headers)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}") from None
        raise RuntimeError("unreachable")

    def _call(self, url: str, params: dict) -> dict:
        self.limiter.acquire()
        self.requests += 1
        return self._get(url, params, self._headers)

    def assets(self) -> list[dict]:
        return self._call(ASSETS_URL, {"status": "active", "asset_class": "us_equity"})  # type: ignore[return-value]

    def bars(self, symbols: list[str], *, timeframe: str, start: datetime, end: datetime) -> dict[str, list[dict]]:
        """All bars for ``symbols`` in [start, end), batched + paginated. Never requests data newer than
        the SIP delay allows (``end`` is clamped by the caller via ``data_as_of``)."""
        out: dict[str, list[dict]] = {}
        n = self.cfg.bars_symbols_per_request
        for i in range(0, len(symbols), n):
            batch = symbols[i:i + n]
            token = None
            while True:
                params = {"symbols": ",".join(batch), "timeframe": timeframe, "start": iso(start),
                          "end": iso(end), "feed": self.cfg.feed, "adjustment": self.cfg.adjustment,
                          "limit": str(self.cfg.bars_page_limit)}
                if token:
                    params["page_token"] = token
                try:
                    j = self._call(DATA_URL, params)
                except Exception as exc:  # noqa: BLE001 -- a failed batch is reported, never silently empty
                    self.errors.append(f"bars {timeframe} batch@{i}: {exc}")
                    break
                for sym, rows in (j.get("bars") or {}).items():
                    out.setdefault(sym, []).extend(rows)
                token = j.get("next_page_token")
                if not token:
                    break
        return out


def data_as_of(now: datetime, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> datetime:
    """The newest instant whose SIP data this subscription may read (bar must be COMPLETE by then)."""
    return (now - timedelta(minutes=cfg.sip_delay_minutes)).replace(second=0, microsecond=0)


def complete_bars_as_of(rows: list[dict], as_of: datetime) -> list[dict]:
    """Causal filter: keep bars whose interval ended at or before ``as_of`` (t + 1 min <= as_of)."""
    cutoff = as_of - timedelta(minutes=1)
    key = iso(cutoff)   # Alpaca bar times are fixed-format "YYYY-MM-DDTHH:MM:SSZ" -> lexical order == time order
    return [r for r in rows if (r["t"] <= key if len(r["t"]) == 20 and r["t"].endswith("Z")
                                else parse_ts(r["t"]) <= cutoff)]
