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
* discovery has priority: the refresher only works while discovery is IDLE (no lookup for ``IDLE_GAP_S``), oldest
  entries first, one request at a time -- a scan waits for at most one in-flight refresh request. (2026-09-25 bench:
  a refresher that competed for the lock during scans starved discovery above ~1,000 symbols.);
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
REFRESH_AHEAD_S = 480.0       # an entry becomes refreshable once it is this close to the TTL (i.e. age >= 120 s)
IDLE_GAP_S = 2.0              # the refresher only runs when discovery has made no lookup for this long
FORGET_AFTER_S = 1800.0       # stop refreshing a CIK discovery has not asked for in this long
MAX_TRACKED = 5000            # bound on tracked CIKs (least-recently-requested evicted)


def enabled(env=None) -> bool:
    return str((env if env is not None else os.environ).get(FLAG, "0")).strip().lower() in ("1", "true", "yes", "on")


class BackgroundSecCache:
    """Drop-in for ``SecSubmissions.get`` with a bounded background refresher. Thread-safe."""

    def __init__(self, sec, *, refresh_ahead_s: float = REFRESH_AHEAD_S, forget_after_s: float = FORGET_AFTER_S,
                 max_tracked: int = MAX_TRACKED, clock: Callable[[], float] | None = None, start: bool = True,
                 idle_sleep_s: float = 1.0, idle_gap_s: float = IDLE_GAP_S):
        self.sec = sec
        self.clock = clock or sec.clock
        self.refresh_ahead_s, self.forget_after_s, self.max_tracked = refresh_ahead_s, forget_after_s, max_tracked
        self.idle_sleep_s, self.idle_gap_s = idle_sleep_s, idle_gap_s
        self._last_get = float("-inf")         # time of discovery's most recent lookup
        self._lock = threading.Lock()          # guards sec._cache reads/writes AND every SEC request
        self._wanted: dict[str, float] = {}    # cik -> last time discovery asked for it
        self._stop = threading.Event()
        self.stats = {"served_fresh": 0, "sync_fallback": 0, "refreshed": 0, "refresh_errors": 0,
                      "throttled_skips": 0, "evicted": 0, "yielded_to_discovery": 0}
        self._thread = None
        self._mlock = threading.Lock()         # guards the per-scan metrics only (never held while calling SEC)
        self._scan: dict | None = None
        if start:
            self.start()

    # -- discovery read path ------------------------------------------------------------------------------------------
    def get(self, cik: str):
        t_call = time.monotonic()
        now = self.clock()
        self._last_get = now
        with self._lock:
            self._track(cik, now)
            hit = self.sec._cache.get(cik)
            if hit and now - hit[0] < self.sec.ttl_s:          # identical freshness test to SecSubmissions.get
                self.stats["served_fresh"] += 1
                self._note(t_call, hit=True, age=now - hit[0])
                return hit[1], hit[2]
            self.stats["sync_fallback"] += 1
            res = self.sec.get(cik)                            # absent/expired: exactly today's synchronous path
            cur = self.sec._cache.get(cik)
            age = (self.clock() - cur[0]) if cur is not None and res[0] is not None and cur[1] is res[0] else None
            self._note(t_call, hit=False, age=age)
            return res

    # -- per-scan observability (read-only bookkeeping; never changes what is served) ---------------------------------
    def _note(self, t_call: float, *, hit: bool, age: float | None) -> None:
        with self._mlock:
            m = self._scan
            if m is None:
                return
            (m["hit_waits"] if hit else m["fallback_waits"]).append(time.monotonic() - t_call)
            if age is not None and age > m["max_served_age_s"]:
                m["max_served_age_s"] = age

    def begin_scan(self) -> None:
        with self._mlock:
            self._scan = {"t0": time.monotonic(), "base": dict(self.stats), "req0": self.sec.requests,
                          "hit_waits": [], "fallback_waits": [], "max_served_age_s": 0.0, "refresh_during_scan": 0}

    def end_scan(self) -> dict:
        """Per-scan SEC cache metrics (waits are wall-clock seconds inside ``get``, i.e. what discovery waited)."""
        with self._mlock:
            m, self._scan = self._scan, None
        if m is None:
            return {"mode": "BACKGROUND_REFRESH"}
        dur = max(time.monotonic() - m["t0"], 1e-9)
        hw = sorted(m["hit_waits"])
        fw = m["fallback_waits"]
        d = {k: self.stats[k] - m["base"].get(k, 0) for k in self.stats}
        req = self.sec.requests - m["req0"]
        return {"mode": "BACKGROUND_REFRESH", "lookups": len(hw) + len(fw), "cache_hits": len(hw),
                "cache_misses": len(fw), "sync_fallbacks": d["sync_fallback"],
                "hit_wait_p99_s": round(hw[min(len(hw) - 1, int(0.99 * (len(hw) - 1) + 0.5))], 4) if hw else None,
                "hit_wait_max_s": round(hw[-1], 4) if hw else None,
                "fallback_wait_total_s": round(sum(fw), 2), "max_served_age_s": round(m["max_served_age_s"], 1),
                "sec_requests": req, "sec_request_rate_per_s": round(req / dur, 3),
                "refresher_requests_during_scan": m["refresh_during_scan"],
                "refresher_yields": d["yielded_to_discovery"], "refreshed_total": self.stats["refreshed"],
                "refresh_errors": d["refresh_errors"], "tracked": len(self._wanted)}

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
            try:
                self.sec.get(cik)
                ok = self.sec.requests > before and len(self.sec.errors) == errs
            except Exception:  # noqa: BLE001 -- unexpected (e.g. cache write) failure: treat as a failed refresh
                ok = False
            if not ok and prev is not None:
                self.sec._cache[cik] = prev                    # failure: restore the untouched previous copy
            self.stats["refreshed" if ok else "refresh_errors"] += 1
            with self._mlock:
                if self._scan is not None:                     # a scan began while this request was in flight
                    self._scan["refresh_during_scan"] += 1
            return ok

    def discovery_idle(self) -> bool:
        return self.clock() - self._last_get >= self.idle_gap_s

    def run_once(self) -> int:
        n = 0
        for cik in self.due():
            if self._stop.is_set():
                break
            if not self.discovery_idle():                      # a scan started: yield immediately
                self.stats["yielded_to_discovery"] += 1
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
