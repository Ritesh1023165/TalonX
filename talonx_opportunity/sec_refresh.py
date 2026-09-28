"""
SEC catalyst cache -- optional BACKGROUND REFRESH (prepared 2026-09-25; enabled 2026-09-26; remediated 2026-09-28).

Why: discovery looks up SEC submissions synchronously for every gapping symbol through ``SecSubmissions`` (in-process
cache keyed by CIK, strict 600 s TTL, serial <= ~5 req/s). Entries fetched together expire together, so every ~3rd
scan re-fetches a block of ~500-600 CIKs and runs 180-250 s (2026-09-25 live: 243.8 s at 15:15Z).

What this does (only when ``TALONX_SEC_BACKGROUND_REFRESH_ENABLED=1``): a daemon thread re-fetches entries that
discovery asked for recently BEFORE they reach the TTL, so discovery normally reads a fresh cached copy instead of
waiting for SEC. The catalyst freshness contract is unchanged:

* discovery is served a cached copy ONLY if it is younger than the TTL (the same strict test ``SecSubmissions.get``
  applies: ``age < ttl``);
* absent / expired entries fall back to the synchronous ``SecSubmissions.get`` path -- byte-for-byte today's behaviour,
  INCLUDING its documented stale-copy-on-failure ("a stale cached copy is preferred over no data if a refresh fails")
  and its 429 back-off. Such a stale serve is now reported explicitly (``served_source=STALE_FALLBACK`` + reason + raw
  age), never folded into cache hits;
* nothing is persisted: a restart starts cold, exactly like today.

2026-09-28 remediation (live acceptance was INCONCLUSIVE: at ~1,250-1,330 lookups/scan served ages rode the 600 s
ceiling because the refresher (a) only ran while discovery was idle and (b) held the cache lock during network I/O,
so one lane delivered ~2.2-2.6 req/s against ~1,500 tracked CIKs = a ~625 s refresh cycle):

* one GLOBAL, thread-safe request-start limiter (``RateLimiter``) spaces EVERY SEC request start (discovery's
  synchronous fallbacks and the refresher alike) by >= ``min_interval_s`` (production 0.21 s -> <= 4.76 req/s, the same
  bound ``SecSubmissions`` already applied to one thread). A waiting discovery request is always served before the
  refresher (priority), so discovery waits at most one start interval for a refresher;
* the refresher performs its network I/O OUTSIDE the cache lock (it only takes the lock to snapshot and to write the
  result), so a discovery cache hit never waits for a refresher request (the 2026-09-25 starvation mechanism is gone);
  it may therefore keep refreshing WHILE a scan runs, paced to ``scan_refresh_rate_per_s`` (default 2.0 req/s) so the
  remaining budget stays with discovery; outside scans it runs up to the global limit;
* only CIKs discovery asked for within ``reuse_window_s`` (default 660 s = two 300 s cadences + margin) are refreshed
  (priority by expected reuse); tracking itself still forgets after ``forget_after_s``.
Still one background thread; no unbounded growth; any refresher failure leaves discovery on today's synchronous path.

Parsing, evaluation, scoring and classification are untouched: the wrapper returns the same ``(submissions,
observed_at)`` tuples ``SecSubmissions.get`` returns. OFF (the default) = discovery uses the plain ``SecSubmissions``.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Callable

log = logging.getLogger("talonx_opportunity.sec_refresh")

FLAG = "TALONX_SEC_BACKGROUND_REFRESH_ENABLED"
REFRESH_AHEAD_S = 480.0       # an entry becomes refreshable once it is this close to the TTL (i.e. age >= 120 s)
IDLE_GAP_S = 2.0              # no discovery lookup for this long (and no open scan) = discovery idle
FORGET_AFTER_S = 1800.0       # stop tracking a CIK discovery has not asked for in this long
REUSE_WINDOW_S = 660.0        # refresh only CIKs discovery asked for within this long (two cadences + margin)
MAX_TRACKED = 5000            # bound on tracked CIKs (least-recently-requested evicted)
MIN_INTERVAL_S = 0.21         # production spacing of SEC request STARTS across all threads (<= 4.76 req/s)
SCAN_REFRESH_RATE_PER_S = 2.0  # refresher budget while a discovery scan is running (rest reserved for discovery)

# served_source values
CACHE_FRESH, SYNC_REFRESH, STALE_FALLBACK, NO_DATA = "CACHE_FRESH", "SYNC_REFRESH", "STALE_FALLBACK", "NO_DATA"
# stale / no-data reasons
FETCH_ERROR, RATE_LIMIT, RATE_LIMIT_BACKOFF, TIMEOUT, OTHER = ("FETCH_ERROR", "RATE_LIMIT", "RATE_LIMIT_BACKOFF",
                                                               "TIMEOUT", "OTHER")


def enabled(env=None) -> bool:
    return str((env if env is not None else os.environ).get(FLAG, "0")).strip().lower() in ("1", "true", "yes", "on")


def failure_reason(error_text: str) -> str:
    """Classify a ``SecSubmissions.errors`` entry (``"<cik>: <ExcType>: <message>"``)."""
    t = error_text or ""
    if "429" in t:
        return RATE_LIMIT
    if "timed out" in t.lower() or "timeout" in t.lower():
        return TIMEOUT
    if t:
        return FETCH_ERROR
    return OTHER


_now = time.perf_counter      # high-resolution monotonic clock for the limiter (see RateLimiter)


class RateLimiter:
    """Thread-safe spacing of request STARTS by slot reservation: every reserved slot is >= ``min_interval_s`` after the
    previous one and a caller never starts before its slot, so the number of starts in any window of W seconds is at most
    W / min_interval_s + 1 (plus one if a start slept past its slot). Timing uses ``time.perf_counter`` and waiting uses
    ``time.sleep`` (both high-resolution on Windows; ``time.monotonic`` and ``Condition.wait`` tick at ~15.6 ms there,
    which delays every start by up to one tick and silently cuts throughput).
    Priority: a high caller (discovery) reserves the next slot at once; a low caller (the refresher) reserves only a slot
    that is free NOW while no high caller is pending, so a waiting discovery request never queues behind the refresher
    and waits at most one interval for a refresher start already reserved."""

    def __init__(self, min_interval_s: float):
        self.min_interval_s = float(min_interval_s)
        self._lock = threading.Lock()
        self._next = 0.0
        self._high_pending = 0
        self.starts: list[float] = []            # bounded record of recent start times (tests / metrics)
        self.total = 0

    def high_waiting(self) -> int:
        return self._high_pending

    def _record(self, t: float) -> None:
        with self._lock:
            self.total += 1
            self.starts.append(t)
            if len(self.starts) > 4096:
                del self.starts[:2048]

    def acquire(self, *, high: bool) -> float:
        if high:
            with self._lock:
                slot = max(_now(), self._next)
                self._next = slot + self.min_interval_s
                self._high_pending += 1
            try:
                while True:
                    d = slot - _now()
                    if d <= 0:
                        break
                    time.sleep(d)
            finally:
                with self._lock:
                    self._high_pending -= 1
            self._record(slot)
            return slot
        while True:
            with self._lock:
                now = _now()
                if self._high_pending == 0 and now >= self._next:
                    self._next = now + self.min_interval_s
                    slot = now
                    break
                wait = max(self._next - now, 0.0)
            time.sleep(min(max(wait, 0.001), 0.05))
        self._record(slot)
        return slot


class BackgroundSecCache:
    """Drop-in for ``SecSubmissions.get`` with a bounded background refresher and per-scan freshness evidence."""

    def __init__(self, sec, *, refresh_ahead_s: float = REFRESH_AHEAD_S, forget_after_s: float = FORGET_AFTER_S,
                 max_tracked: int = MAX_TRACKED, clock: Callable[[], float] | None = None, start: bool = True,
                 idle_sleep_s: float = 1.0, idle_gap_s: float = IDLE_GAP_S, reuse_window_s: float = REUSE_WINDOW_S,
                 min_interval_s: float | None = None, scan_refresh_rate_per_s: float = SCAN_REFRESH_RATE_PER_S):
        self.sec = sec
        self.clock = clock or sec.clock
        self.refresh_ahead_s, self.forget_after_s, self.max_tracked = refresh_ahead_s, forget_after_s, max_tracked
        self.idle_sleep_s, self.idle_gap_s, self.reuse_window_s = idle_sleep_s, idle_gap_s, reuse_window_s
        self.scan_refresh_rate_per_s = scan_refresh_rate_per_s
        self._last_get = float("-inf")         # time of discovery's most recent lookup
        self._lock = threading.Lock()          # guards sec._cache / tracking; held for network I/O ONLY by discovery
        self._wanted: dict[str, float] = {}    # cik -> last time discovery asked for it
        self._stop = threading.Event()
        self._next_scan_refresh = 0.0          # perf_counter: refresher pacing while a scan is open
        self.stats = {"served_fresh": 0, "sync_fallback": 0, "refreshed": 0, "refresh_errors": 0,
                      "throttled_skips": 0, "evicted": 0, "yielded_to_discovery": 0, "stale_fallback": 0,
                      "no_data": 0, "refresh_superseded": 0}
        # one global start limiter for EVERY SEC request (production: maybe_wrap passes MIN_INTERVAL_S). With an
        # injected client and no interval (tests / benches) behaviour is exactly the pre-remediation one.
        self.limiter = RateLimiter(min_interval_s) if min_interval_s else None
        if self.limiter is not None:
            raw_get = sec._get
            sec._get = lambda url, headers: (self.limiter.acquire(high=True), raw_get(url, headers))[1]
            self._raw_get = raw_get
        else:
            self._raw_get = sec._get
        self._thread = None
        self._mlock = threading.Lock()         # guards the per-scan metrics only (never held while calling SEC)
        self._scan: dict | None = None
        if start:
            self.start()

    # -- discovery read path ------------------------------------------------------------------------------------------
    def get(self, cik: str):
        t_call = _now()
        now = self.clock()
        self._last_get = now
        with self._lock:
            self._track(cik, now)
            hit = self.sec._cache.get(cik)
            if hit and now - hit[0] < self.sec.ttl_s:          # identical freshness test to SecSubmissions.get
                self.stats["served_fresh"] += 1
                self._note(t_call, CACHE_FRESH, now - hit[0])
                return hit[1], hit[2]
            self.stats["sync_fallback"] += 1
            req0, err0, thr0 = self.sec.requests, len(self.sec.errors), getattr(self.sec, "throttled", 0)
            res = self.sec.get(cik)                            # absent/expired: exactly today's synchronous path
            cur = self.sec._cache.get(cik)
            new_errs = self.sec.errors[err0:]
            throttled = getattr(self.sec, "throttled", 0) > thr0
            if res[0] is None:                                 # nothing to serve (-> CATALYST UNKNOWN downstream)
                self.stats["no_data"] += 1
                reason = RATE_LIMIT_BACKOFF if throttled else failure_reason(new_errs[-1] if new_errs else "")
                self._note(t_call, NO_DATA, None, reason=reason)
            elif self.sec.requests > req0 and not new_errs:    # fresh synchronous fetch
                self._note(t_call, SYNC_REFRESH, (self.clock() - cur[0]) if cur is not None else 0.0)
            else:                                              # documented stale-copy-on-failure / back-off
                self.stats["stale_fallback"] += 1
                reason = RATE_LIMIT_BACKOFF if throttled else failure_reason(new_errs[-1] if new_errs else "")
                age = (self.clock() - cur[0]) if cur is not None and cur[1] is res[0] else None
                self._note(t_call, STALE_FALLBACK, age, reason=reason)
            return res

    # -- per-scan observability (read-only bookkeeping; never changes what is served) ---------------------------------
    def _note(self, t_call: float, source: str, age: float | None, *, reason: str | None = None) -> None:
        with self._mlock:
            m = self._scan
            if m is None:
                return
            (m["hit_waits"] if source == CACHE_FRESH else m["fallback_waits"]).append(_now() - t_call)
            m["sources"][source] = m["sources"].get(source, 0) + 1
            if age is not None:
                m["ages"].append(age)
                if age > m["max_served_age_s"]:
                    m["max_served_age_s"] = age
            if source in (STALE_FALLBACK, NO_DATA):
                key = f"{source}:{reason or OTHER}"
                m["reasons"][key] = m["reasons"].get(key, 0) + 1
                if source == STALE_FALLBACK and age is not None and age > m["stale_max_age"]:
                    m["stale_max_age"] = age

    def begin_scan(self) -> None:
        with self._mlock:
            self._scan = {"t0": _now(), "base": dict(self.stats), "req0": self.sec.requests,
                          "hit_waits": [], "fallback_waits": [], "max_served_age_s": 0.0, "refresh_during_scan": 0,
                          "sources": {}, "reasons": {}, "ages": [], "stale_max_age": 0.0}

    def end_scan(self) -> dict:
        """Per-scan SEC cache metrics (waits are wall-clock seconds inside ``get``, i.e. what discovery waited).
        ``max_served_age_s`` keeps its historical 0.1 s rounding; ``*_raw`` fields carry full precision."""
        with self._mlock:
            m, self._scan = self._scan, None
        if m is None:
            return {"mode": "BACKGROUND_REFRESH"}
        dur = max(_now() - m["t0"], 1e-9)
        hw = sorted(m["hit_waits"])
        fw = sorted(m["fallback_waits"])
        allw = sorted(hw + fw)
        ages = sorted(m["ages"])
        d = {k: self.stats[k] - m["base"].get(k, 0) for k in self.stats}
        req = self.sec.requests - m["req0"]
        src = m["sources"]

        def q(xs, p, nd=4):
            return round(xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))], nd) if xs else None
        return {"mode": "BACKGROUND_REFRESH", "lookups": len(hw) + len(fw), "cache_hits": len(hw),
                "cache_misses": len(fw), "sync_fallbacks": d["sync_fallback"],
                "hit_wait_p99_s": q(hw, 0.99), "hit_wait_max_s": round(hw[-1], 4) if hw else None,
                "lookup_wait_p99_s": q(allw, 0.99), "lookup_wait_max_s": round(allw[-1], 4) if allw else None,
                "fallback_wait_total_s": round(sum(fw), 2), "max_served_age_s": round(m["max_served_age_s"], 1),
                "sec_requests": req, "sec_request_rate_per_s": round(req / dur, 3),
                "refresher_requests_during_scan": m["refresh_during_scan"],
                "refresher_yields": d["yielded_to_discovery"], "refreshed_total": self.stats["refreshed"],
                "refresh_errors": d["refresh_errors"], "tracked": len(self._wanted),
                # 2026-09-28 raw freshness evidence (full precision; served_source breakdown)
                "cache_fresh_count": src.get(CACHE_FRESH, 0), "sync_refresh_count": src.get(SYNC_REFRESH, 0),
                "stale_fallback_count": src.get(STALE_FALLBACK, 0), "no_data_count": src.get(NO_DATA, 0),
                "stale_fallback_reasons": dict(m["reasons"]),
                "stale_fallback_max_age_raw": round(m["stale_max_age"], 6) if src.get(STALE_FALLBACK) else None,
                "max_served_age_raw": round(ages[-1], 6) if ages else None,
                "served_age_p95_raw": q(ages, 0.95, 6), "served_age_p99_raw": q(ages, 0.99, 6),
                "count_age_ge_590": sum(a >= 590 for a in ages), "count_age_ge_595": sum(a >= 595 for a in ages),
                "count_age_ge_600": sum(a >= 600 for a in ages)}

    def _track(self, cik: str, now: float) -> None:
        self._wanted[cik] = now
        if len(self._wanted) > self.max_tracked:
            oldest = min(self._wanted, key=self._wanted.get)
            self._wanted.pop(oldest, None)
            self.stats["evicted"] += 1

    # -- background refresher ------------------------------------------------------------------------------------------
    def due(self, now: float | None = None) -> list[str]:
        """CIKs discovery asked for within ``reuse_window_s`` whose cached copy is within ``refresh_ahead_s`` of the
        TTL, oldest first."""
        now = self.clock() if now is None else now
        with self._lock:
            for c in [c for c, t in self._wanted.items() if now - t > self.forget_after_s]:
                self._wanted.pop(c, None)
            ages = []
            for c, t in self._wanted.items():
                if now - t > self.reuse_window_s:
                    continue                                   # not requested recently: not worth a request
                hit = self.sec._cache.get(c)
                age = float("inf") if hit is None else now - hit[0]
                if age >= self.sec.ttl_s - self.refresh_ahead_s:
                    ages.append((-age, c))
        return [c for _, c in sorted(ages)]

    def _fetch(self, cik: str):
        """One refresher request, OUTSIDE the cache lock, through the global limiter at LOW priority."""
        from talonx_premarket.catalysts import SUBMISSIONS_URL
        if self.limiter is not None:
            self.limiter.acquire(high=False)
        return self._raw_get(SUBMISSIONS_URL.format(cik=str(cik).zfill(10)),
                             {"User-Agent": getattr(self.sec, "_ua", ""), "Accept-Encoding": "identity"})

    def refresh_one(self, cik: str) -> bool:
        """Re-fetch one CIK (same URL, headers, error bookkeeping and 429 back-off as ``SecSubmissions.get``). The
        network request runs outside the cache lock; a failed refresh never touches the previous cached copy."""
        with self._lock:
            if self.clock() < getattr(self.sec, "_backoff_until", 0.0):
                self.stats["throttled_skips"] += 1
                return False
            self.sec.requests += 1
        scan_open = self._scan is not None
        try:
            j = self._fetch(cik)
        except Exception as exc:  # noqa: BLE001 -- same bookkeeping as SecSubmissions.get's failure branch
            with self._lock:
                self.sec.errors.append(f"{cik}: {type(exc).__name__}: {str(exc)[:80]}")
                if "429" in str(exc):
                    self.sec._backoff_until = self.clock() + getattr(self.sec, "backoff_s", 60.0)
                self.stats["refresh_errors"] += 1
            self._count_scan_refresh(scan_open)
            return False
        fetched_at = self.clock()
        observed = datetime.now(timezone.utc)
        with self._lock:
            cur = self.sec._cache.get(cik)
            if cur is not None and cur[0] > fetched_at:        # a newer synchronous fetch landed meanwhile: keep it
                self.stats["refresh_superseded"] += 1
            else:
                self.sec._cache[cik] = (fetched_at, j, observed)
            self.stats["refreshed"] += 1
        self._count_scan_refresh(scan_open)
        return True

    def _count_scan_refresh(self, scan_open_at_start: bool) -> None:
        """Count a refresher request that overlapped an open scan (it started or finished while one was open)."""
        with self._mlock:
            if self._scan is not None:
                self._scan["refresh_during_scan"] += 1

    def discovery_idle(self) -> bool:
        return self._scan is None and self.clock() - self._last_get >= self.idle_gap_s

    def run_once(self) -> int:
        """Refresh due entries (oldest first). While a scan is running the refresher is paced to
        ``scan_refresh_rate_per_s`` and steps aside whenever discovery has a request waiting."""
        n = 0
        for cik in self.due():
            if self._stop.is_set():
                break
            if self.limiter is not None and self.limiter.high_waiting():
                self.stats["yielded_to_discovery"] += 1
                break
            if not self.discovery_idle():
                if self.scan_refresh_rate_per_s <= 0:          # legacy idle-only mode
                    self.stats["yielded_to_discovery"] += 1
                    break
                now = _now()
                if now < self._next_scan_refresh:
                    self.stats["yielded_to_discovery"] += 1
                    break
                self._next_scan_refresh = now + 1.0 / self.scan_refresh_rate_per_s
            self.refresh_one(cik)
            n += 1
        return n

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self.run_once() == 0:
                    wait = self.idle_sleep_s
                    if not self.discovery_idle() and self.scan_refresh_rate_per_s > 0:
                        wait = min(wait, max(0.01, self._next_scan_refresh - _now()))
                    self._stop.wait(wait)
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
                    "sec_requests": self.sec.requests,
                    "limiter_min_interval_s": self.limiter.min_interval_s if self.limiter else None}


def maybe_wrap(sec, env=None):
    """``sec`` unchanged unless the flag is ON (default OFF)."""
    if sec is None or not enabled(env):
        return sec
    log.warning("SEC BACKGROUND REFRESH ENABLED (%s=1): catalyst freshness bound unchanged (%.0f s TTL); "
                "global request spacing %.2f s; scan-time refresher budget %.1f req/s", FLAG, sec.ttl_s,
                MIN_INTERVAL_S, SCAN_REFRESH_RATE_PER_S)
    return BackgroundSecCache(sec, min_interval_s=MIN_INTERVAL_S)
