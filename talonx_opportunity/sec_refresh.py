"""
SEC catalyst cache -- optional BACKGROUND REFRESH (prepared 2026-09-25; OFF by default).

Why: discovery looks up SEC submissions synchronously for every gapping symbol through ``SecSubmissions`` (in-process
cache keyed by CIK, strict 600 s TTL, serial <= ~5 req/s). Entries fetched together expire together, so every ~3rd
scan re-fetches a block of ~500-600 CIKs and runs 180-250 s (2026-09-25 live: 243.8 s at 15:15Z).

What this does (only when ``TALONX_SEC_BACKGROUND_REFRESH_ENABLED=1``): a daemon thread re-fetches entries that
discovery asked for recently BEFORE they reach the TTL, so discovery normally reads a fresh cached copy instead of
waiting for SEC. The catalyst freshness contract is unchanged:

* discovery is served a cached copy ONLY if it is younger than the TTL (the same test ``SecSubmissions.get`` applies);
* absent / expired entries fall back to the synchronous ``SecSubmissions.get`` path -- byte-for-byte today's behaviour
  (including its stale-copy-on-failure and 429 back-off);
* every SEC request (refresher or fallback) goes through the one ``SecSubmissions`` instance under one lock, so its
  own >= 0.21 s spacing still bounds the combined rate to today's ~5 req/s;
* nothing is persisted: a restart starts cold, exactly like today.

Parsing, evaluation, scoring and classification are untouched: the wrapper returns the same ``(submissions,
observed_at)`` tuples ``SecSubmissions.get`` returns. OFF (the default) = discovery uses the plain ``SecSubmissions``.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

log = logging.getLogger("talonx_opportunity.sec_refresh")

FLAG = "TALONX_SEC_BACKGROUND_REFRESH_ENABLED"
REFRESH_AHEAD_S = 240.0       # refresh an entry once it is this close to the TTL
FORGET_AFTER_S = 1800.0       # stop refreshing a CIK discovery has not asked for in this long
MAX_TRACKED = 5000            # bound on tracked CIKs (least-recently-requested evicted)


def enabled(env=None) -> bool:
    return str((env if env is not None else os.environ).get(FLAG, "0")).strip().lower() in ("1", "true", "yes", "on")


class BackgroundSecCache:
    """Drop-in for ``SecSubmissions.get`` with a bounded background refresher. Thread-safe."""

    def __init__(self, sec, *, refresh_ahead_s: float = REFRESH_AHEAD_S, forget_after_s: float = FORGET_AFTER_S,
                 max_tracked: int = MAX_TRACKED, clock: Callable[[], float] | None = None, start: bool = True,
                 idle_sleep_s: float = 1.0):
        self.sec = sec
        self.clock = clock or sec.clock
        self.refresh_ahead_s, self.forget_after_s, self.max_tracked = refresh_ahead_s, forget_after_s, max_tracked
        self.idle_sleep_s = idle_sleep_s
        self._lock = threading.Lock()          # guards sec._cache reads/writes AND every SEC request
        self._wanted: dict[str, float] = {}    # cik -> last time discovery asked for it
        self._stop = threading.Event()
        self.stats = {"served_fresh": 0, "sync_fallback": 0, "refreshed": 0, "refresh_errors": 0,
                      "throttled_skips": 0, "evicted": 0}
        self._thread = None
        if start:
            self.start()

    # -- discovery read path ------------------------------------------------------------------------------------------
    def get(self, cik: str):
        now = self.clock()
        with self._lock:
            self._track(cik, now)
            hit = self.sec._cache.get(cik)
            if hit and now - hit[0] < self.sec.ttl_s:          # identical freshness test to SecSubmissions.get
                self.stats["served_fresh"] += 1
                return hit[1], hit[2]
            self.stats["sync_fallback"] += 1
            return self.sec.get(cik)                           # absent/expired: exactly today's synchronous path

    def _track(self, cik: str, now: float) -> None:
        self._wanted[cik] = now
        if len(self._wanted) > self.max_tracked:
            oldest = min(self._wanted, key=self._wanted.get)
            self._wanted.pop(oldest, None)
            self.stats["evicted"] += 1

    # -- background refresher ------------------------------------------------------------------------------------------
    def due(self, now: float | None = None) -> list[str]:
        """CIKs discovery still wants whose cached copy is within ``refresh_ahead_s`` of the TTL, oldest first."""
        now = self.clock() if now is None else now
        with self._lock:
            for c in [c for c, t in self._wanted.items() if now - t > self.forget_after_s]:
                self._wanted.pop(c, None)
            ages = []
            for c in self._wanted:
                hit = self.sec._cache.get(c)
                age = float("inf") if hit is None else now - hit[0]
                if age >= self.sec.ttl_s - self.refresh_ahead_s:
                    ages.append((-age, c))
        return [c for _, c in sorted(ages)]

    def refresh_one(self, cik: str) -> bool:
        """Re-fetch one CIK through ``SecSubmissions.get`` (same request, spacing, error and 429 handling). A failed
        refresh leaves the previous cached copy AND its original fetch time untouched."""
        with self._lock:
            if self.clock() < getattr(self.sec, "_backoff_until", 0.0):
                self.stats["throttled_skips"] += 1
                return False
            prev = self.sec._cache.get(cik)
            if prev is not None:
                self.sec._cache[cik] = (float("-inf"), prev[1], prev[2])   # force a fetch on the next get
            before = self.sec.requests
            errs = len(self.sec.errors)
            self.sec.get(cik)
            ok = self.sec.requests > before and len(self.sec.errors) == errs
            if not ok and prev is not None:
                self.sec._cache[cik] = prev                    # failure: restore the untouched previous copy
            self.stats["refreshed" if ok else "refresh_errors"] += 1
            return ok

    def run_once(self) -> int:
        n = 0
        for cik in self.due():
            if self._stop.is_set():
                break
            self.refresh_one(cik)
            n += 1
        return n

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self.run_once() == 0:
                    self._stop.wait(self.idle_sleep_s)
            except Exception:  # noqa: BLE001 -- the refresher must never take discovery down; sync fallback covers it
                log.exception("SEC background refresh pass failed")
                self._stop.wait(5.0)

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="sec-background-refresh", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def detail(self) -> dict:
        with self._lock:
            return {"mode": "BACKGROUND_REFRESH", "tracked": len(self._wanted), **self.stats,
                    "sec_requests": self.sec.requests}


def maybe_wrap(sec, env=None):
    """``sec`` unchanged unless the flag is ON (default OFF)."""
    if sec is None or not enabled(env):
        return sec
    log.warning("SEC BACKGROUND REFRESH ENABLED (%s=1): catalyst freshness bound unchanged (%.0f s TTL)",
                FLAG, sec.ttl_s)
    return BackgroundSecCache(sec)
