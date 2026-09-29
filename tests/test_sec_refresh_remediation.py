"""SEC refresh remediation (2026-09-28): raw freshness evidence, explicit stale-fallback visibility, a global request-start
limiter with discovery priority, refresher I/O outside the cache lock, reuse-window refresh priority.
No network: every SEC client here is an injected fake."""
from __future__ import annotations

import threading
import time

import pytest

from talonx_opportunity import sec_refresh as SR
from talonx_premarket.catalysts import SecSubmissions


def _subs():
    return {"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-09-24"],
                                   "acceptanceDateTime": ["2026-09-24T12:00:00Z"],
                                   "accessionNumber": ["0000000000-26-000001"], "items": ["2.02"]}}}


def _sec(fail=None):
    t = [0.0]
    calls = {"n": 0}

    def get(url, headers):
        calls["n"] += 1
        if fail and fail.get("on"):
            raise fail["exc"]
        return _subs()
    return SecSubmissions(user_agent="ua", http_get=get, clock=lambda: t[0], ttl_s=600), t, calls


def _scan(w, fn):
    w.begin_scan()
    fn()
    return w.end_scan()


# ------------------------------------------------------------------------------------------ served_source + raw age
def test_fresh_hit_and_successful_sync_refresh_are_distinguished():
    sec, t, _ = _sec()
    w = SR.BackgroundSecCache(sec, start=False)
    m = _scan(w, lambda: w.get("1"))                       # cold -> synchronous fetch
    assert (m["sync_refresh_count"], m["cache_fresh_count"], m["stale_fallback_count"]) == (1, 0, 0)
    assert m["max_served_age_raw"] == 0.0
    t[0] = 300.0
    m = _scan(w, lambda: w.get("1"))
    assert (m["cache_fresh_count"], m["sync_refresh_count"]) == (1, 0) and m["max_served_age_raw"] == 300.0


@pytest.mark.parametrize("exc,reason", [(RuntimeError("HTTP Error 500: boom"), SR.FETCH_ERROR),
                                        (TimeoutError("The read operation timed out"), SR.TIMEOUT),
                                        (RuntimeError("HTTP Error 429: Too Many Requests"), SR.RATE_LIMIT)])
def test_expired_entry_with_failed_fetch_is_an_explicit_stale_fallback_with_reason_and_raw_age(exc, reason):
    fail = {"on": False, "exc": exc}
    sec, t, _ = _sec(fail)
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")
    fail["on"] = True
    t[0] = 700.5
    m = _scan(w, lambda: w.get("1"))
    assert m["stale_fallback_count"] == 1 and m["cache_fresh_count"] == 0 and m["sync_refresh_count"] == 0
    assert m["stale_fallback_reasons"] == {f"STALE_FALLBACK:{reason}": 1}
    assert m["stale_fallback_max_age_raw"] == 700.5 and m["max_served_age_raw"] == 700.5
    assert m["count_age_ge_600"] == 1 and w.stats["stale_fallback"] == 1


def test_backoff_serves_stale_without_a_request_and_says_so():
    fail = {"on": False, "exc": RuntimeError("HTTP Error 429: Too Many Requests")}
    sec, t, calls = _sec(fail)
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")
    w.get("2")
    fail["on"] = True
    t[0] = 700.0
    w.get("1")                                             # 429 -> SecSubmissions arms its back-off
    n = calls["n"]
    m = _scan(w, lambda: w.get("2"))                       # during back-off: no request, stale copy
    assert calls["n"] == n and m["stale_fallback_reasons"] == {"STALE_FALLBACK:RATE_LIMIT_BACKOFF": 1}


def test_no_cached_copy_and_failed_fetch_is_no_data_not_stale():
    fail = {"on": True, "exc": RuntimeError("HTTP Error 503")}
    sec, t, _ = _sec(fail)
    w = SR.BackgroundSecCache(sec, start=False)
    m = _scan(w, lambda: w.get("9"))
    assert m["no_data_count"] == 1 and m["stale_fallback_count"] == 0
    assert m["stale_fallback_reasons"] == {"NO_DATA:FETCH_ERROR": 1} and m["max_served_age_raw"] is None


def test_raw_age_distinguishes_just_under_from_at_the_ttl():
    """The historical 0.1 s-rounded metric shows 600.0 for BOTH 599.95 and 600.0; the raw fields do not."""
    sec, t, _ = _sec()
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")
    t[0] = 599.95
    m = _scan(w, lambda: w.get("1"))                       # a legitimate hit (strictly < 600)
    assert m["max_served_age_s"] == 600.0                  # legacy display
    assert m["max_served_age_raw"] == 599.95 and m["count_age_ge_600"] == 0 and m["count_age_ge_595"] == 1
    fail = {"on": True, "exc": RuntimeError("HTTP Error 500")}
    sec2, t2, _ = _sec()
    w2 = SR.BackgroundSecCache(sec2, start=False)
    w2.get("1")
    sec2._get = lambda url, headers: (_ for _ in ()).throw(fail["exc"])
    t2[0] = 600.0
    m2 = _scan(w2, lambda: w2.get("1"))                    # expired exactly at the TTL + failure -> stale 600.0
    assert m2["max_served_age_s"] == 600.0 and m2["max_served_age_raw"] == 600.0
    assert m2["count_age_ge_600"] == 1 and m2["stale_fallback_count"] == 1


# ------------------------------------------------------------------------------------------ global request limiter
def test_limiter_spaces_every_start_across_threads_and_bounds_the_rate():
    lim = SR.RateLimiter(0.02)
    stop = time.monotonic() + 0.6

    def worker(high):
        while time.monotonic() < stop:
            lim.acquire(high=high)
    ts = [threading.Thread(target=worker, args=(h,)) for h in (True, False, False)]
    for x in ts:
        x.start()
    for x in ts:
        x.join()
    s = sorted(lim.starts)                                 # reserved slots
    gaps = [b - a for a, b in zip(s, s[1:])]
    assert min(gaps) >= 0.02 - 1e-9                        # every reserved slot is >= one interval apart (by design)
    assert len(s) <= (s[-1] - s[0]) / 0.02 + 1 + 1e-6    # count bounded by the span of reserved slots
    for i in range(len(s)):                                # any 0.2 s window holds <= 0.2/0.02 + 1 starts
        assert sum(1 for x in s if s[i] <= x < s[i] + 0.2) <= 11


def test_waiting_discovery_request_goes_before_the_refresher():
    lim = SR.RateLimiter(0.1)
    order = []
    lim.acquire(high=True)                                 # occupy the current slot

    def low():
        lim.acquire(high=False)
        order.append("refresher")

    def high():
        lim.acquire(high=True)
        order.append("discovery")
    tl = threading.Thread(target=low)
    tl.start()
    time.sleep(0.01)
    th = threading.Thread(target=high)
    th.start()
    tl.join()
    th.join()
    assert order == ["discovery", "refresher"]


def test_production_wrap_installs_the_global_limiter_on_every_sec_request(monkeypatch):
    sec, t, calls = _sec()
    monkeypatch.setattr(SR, "MIN_INTERVAL_S", 0.01)
    w = SR.maybe_wrap(sec, env={SR.FLAG: "1", SR.CAPACITY_ENV: SR.REMEDIATION_V1})    # opt-in capacity mode
    try:
        assert w.limiter is not None and w.limiter.min_interval_s == 0.01
        w.get("1")                                         # discovery synchronous path -> limiter (high)
        t[0] = 400.0
        w.refresh_one("1")                                 # refresher path -> limiter (low)
        assert w.limiter.total == 2 == calls["n"]
    finally:
        w.stop()
    assert SR.MIN_INTERVAL_S == 0.01 and 1 / 0.21 < 5      # production spacing 0.21 s -> 4.76 req/s < 5


def test_concurrent_discovery_fallbacks_and_refresher_never_exceed_the_cap():
    net_times = []

    def http(url, headers):
        net_times.append(time.monotonic())
        time.sleep(0.005)
        return _subs()
    sec = SecSubmissions(user_agent="ua", http_get=http, ttl_s=600, clock=time.monotonic)
    w = SR.BackgroundSecCache(sec, start=False, min_interval_s=0.02, refresh_ahead_s=600, idle_sleep_s=0.001,
                              scan_refresh_rate_per_s=1000)
    for i in range(30):
        w._wanted[str(i)] = time.monotonic()
    w.start()
    try:
        w.begin_scan()
        for i in range(30, 50):                            # discovery cold lookups (synchronous fallbacks)
            w.get(str(i))
        w.end_scan()
        time.sleep(0.3)
    finally:
        w.stop()
    s = sorted(net_times)                                  # actual network starts (>= their reserved slots)
    for i in range(len(s)):
        assert sum(1 for x in s if s[i] <= x < s[i] + 0.2) <= 12      # 0.2/0.02 + 1 (+1 for a late-sleeping start)
    assert len(w.limiter.starts) == len(s) and w.stats["refreshed"] >= 5


# ------------------------------------------------------------------------------------------ refresher behaviour
def test_cache_hits_never_wait_for_refresher_network_io():
    gate = threading.Event()

    def http(url, headers):
        gate.wait(0.5)                                     # a very slow SEC response
        return _subs()
    sec = SecSubmissions(user_agent="ua", http_get=http, ttl_s=600, clock=time.monotonic)
    for i in range(20):
        sec._cache[str(i)] = (time.monotonic(), _subs(), None)
    w = SR.BackgroundSecCache(sec, start=False)
    th = threading.Thread(target=w.refresh_one, args=("0",))
    th.start()
    time.sleep(0.05)                                       # refresher is now blocked inside its network request
    waits = []
    for i in range(1, 20):
        a = time.monotonic()
        w.get(str(i))
        waits.append(time.monotonic() - a)
    gate.set()
    th.join()
    assert max(waits) < 0.05


def test_reuse_window_skips_ciks_not_requested_recently():
    sec, t, _ = _sec()
    w = SR.BackgroundSecCache(sec, start=False, reuse_window_s=660)
    w.get("old")
    t[0] = 400.0
    w.get("new")
    t[0] = 1100.0                                          # "old" asked 1100 s ago, "new" 700 s ago
    assert w.due() == []
    w.get("new")
    t[0] = 1300.0
    assert w.due() == ["new"]


def test_a_newer_synchronous_fetch_is_never_overwritten_by_an_older_refresh():
    sec, t, _ = _sec()
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")
    t[0] = 400.0
    real = w._fetch

    def racing_fetch(cik):
        j = real(cik)
        sec._cache[cik] = (999.0, {"newer": True}, None)   # discovery landed a newer copy mid-request
        return j
    w._fetch = racing_fetch
    assert w.refresh_one("1") is True
    assert sec._cache["1"][1] == {"newer": True} and w.stats["refresh_superseded"] == 1


def test_refresher_failure_keeps_previous_copy_and_discovery_keeps_working():
    fail = {"on": False, "exc": TimeoutError("timed out")}
    sec, t, _ = _sec(fail)
    w = SR.BackgroundSecCache(sec, start=False)
    first = w.get("1")
    fetched = sec._cache["1"][0]
    fail["on"] = True
    t[0] = 300.0
    assert w.refresh_one("1") is False and sec._cache["1"][0] == fetched and w.stats["refresh_errors"] == 1
    assert w.get("1")[0] is first[0]                       # still a fresh hit (age 300)
