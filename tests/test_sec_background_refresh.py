"""SEC catalyst-cache background refresh (prepared 2026-09-25, OFF by default).

Proves: OFF = the plain SecSubmissions object; ON serves only copies younger than the TTL (else today's synchronous
path), refreshes due entries in the background through the same instance (same spacing / errors / 429), never loses
the previous copy on a failed refresh, and yields identical discovery output for identical <=TTL snapshots.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_opportunity import sec_refresh as SR
from talonx_opportunity.discovery import Discovery
from talonx_opportunity.ingestion import Ingestion
from talonx_opportunity.store import OpportunityStore
from talonx_premarket.catalysts import SecSubmissions
from tests.test_continuous_opportunity_engine import U, Clock, FakeData, _world


def _subs(form="8-K"):
    return {"filings": {"recent": {"form": [form], "filingDate": ["2026-09-24"], "acceptanceDateTime": ["2026-09-24T12:00:00Z"],
                                   "accessionNumber": ["0000000000-26-000001"], "items": ["2.02"]}}}


def _pair(fail=None, http=None):
    t = [0.0]
    calls = {"n": 0}

    def get(url, headers):
        calls["n"] += 1
        if fail and fail["on"]:
            raise fail.get("exc", TimeoutError("timed out"))
        return _subs()
    sec = SecSubmissions(user_agent="ua", http_get=http or get, clock=lambda: t[0], ttl_s=600)
    return sec, t, calls


def test_off_by_default_returns_the_plain_sec_object():
    sec, _, _ = _pair()
    assert SR.maybe_wrap(sec, env={}) is sec
    assert SR.maybe_wrap(sec, env={SR.FLAG: "0"}) is sec
    w = SR.maybe_wrap(sec, env={SR.FLAG: "1"})
    try:
        assert isinstance(w, SR.BackgroundSecCache)
    finally:
        w.stop()


def test_read_path_is_identical_to_sec_get_without_refresher():
    a, ta, ca = _pair()
    b, tb, cb = _pair()
    w = SR.BackgroundSecCache(b, start=False)
    for when, cik in ((0, "1"), (10, "1"), (599, "1"), (600, "1"), (601, "2"), (1300, "1")):
        ta[0] = tb[0] = when
        ra, rw = a.get(cik), w.get(cik)
        assert ra[0] == rw[0] and ra[1] == rw[1]
        assert ca["n"] == cb["n"]                          # same request decisions, same count


def test_background_refresh_keeps_entries_fresh_so_discovery_does_not_wait():
    sec, t, calls = _pair()
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")                                             # cold -> synchronous fetch (as today)
    assert calls["n"] == 1
    t[0] = 400.0                                           # age >= 120 s -> due; discovery idle since t=0
    assert w.due() == ["1"] and w.run_once() == 1 and calls["n"] == 2
    t[0] = 650.0                                           # plain cache would be expired here
    w.get("1")
    assert calls["n"] == 2 and w.stats["served_fresh"] == 1


def test_never_serves_a_copy_at_or_beyond_the_ttl():
    sec, t, calls = _pair()
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")
    t[0] = 600.0                                           # refresher never ran: exactly TTL old -> synchronous fetch
    w.get("1")
    assert calls["n"] == 2 and w.stats["sync_fallback"] == 2


def test_failed_refresh_keeps_the_previous_copy_and_its_fetch_time():
    fail = {"on": False}
    sec, t, calls = _pair(fail=fail)
    w = SR.BackgroundSecCache(sec, start=False)
    first = w.get("1")
    fetched_at = sec._cache["1"][0]
    fail["on"] = True
    t[0] = 400.0
    assert w.refresh_one("1") is False
    assert sec._cache["1"][0] == fetched_at and sec._cache["1"][1] is first[0]
    t[0] = 700.0                                           # expired + SEC down -> today's stale-copy behaviour
    again = w.get("1")
    assert again[0] is first[0]


def test_refresher_respects_the_429_back_off():
    fail = {"on": False, "exc": RuntimeError("HTTP Error 429: Too Many Requests")}
    sec, t, calls = _pair(fail=fail)
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")
    w.get("2")
    fail["on"] = True
    t[0] = 400.0
    w.refresh_one("1")                                     # 429 -> back-off armed inside SecSubmissions
    n = calls["n"]
    assert w.refresh_one("2") is False and calls["n"] == n and w.stats["throttled_skips"] == 1


def test_forgotten_ciks_are_not_refreshed():
    sec, t, _ = _pair()
    w = SR.BackgroundSecCache(sec, start=False, forget_after_s=1800)
    w.get("1")
    t[0] = 2000.0
    assert w.due() == []


def test_background_thread_starts_and_stops():
    sec, _, _ = _pair()
    w = SR.BackgroundSecCache(sec, start=True, idle_sleep_s=0.01)
    try:
        assert w._thread.is_alive()
    finally:
        w.stop()
    assert not w._thread.is_alive()


def _discover(root, sec):
    minute, daily, members = _world()
    for i, m in enumerate(members):
        m["cik"] = f"000000000{i + 1}"
    clock = Clock(U(9))
    data = FakeData(minute, daily)
    ing = Ingestion(data=data, root=root, clock=clock, universe_loader=lambda: (members, "test"))
    disc = Discovery(root=root, clock=clock, sec=sec)
    for t in (U(9), U(9, 30), U(14, 30)):
        clock.t = t
        ing.tick()
        disc.tick()
    s = OpportunityStore(root, readonly=True)
    try:
        ev = [(e["symbol"], e["event_type"], e["classification"], round(e["score"] or 0, 6), e["catalyst"])
              for e in s.events_after(0, limit=10_000)]
        cands = sorted((c["candidate_id"], c["state"], c["catalyst"]) for c in s.candidates())
    finally:
        s.close()
    return ev, cands


def test_discovery_output_is_identical_off_vs_on_for_the_same_snapshots(tmp_path):
    def sec_for():
        return SecSubmissions(user_agent="ua", http_get=lambda url, headers: _subs(), ttl_s=600,
                              clock=lambda: 0.0)          # frozen clock: every copy stays within the TTL
    off = _discover(tmp_path / "off", sec_for())
    w = SR.BackgroundSecCache(sec_for(), start=False)
    on = _discover(tmp_path / "on", w)
    assert off == on and off[0]                            # same events, scores, catalysts and candidates
    assert any("8-K" in (c or "") for _, _, c in off[1]) or any("8-K" in (e[4] or "") for e in off[0])


def test_refresher_yields_while_discovery_is_scanning():
    sec, t, calls = _pair()
    w = SR.BackgroundSecCache(sec, start=False, idle_gap_s=2.0)
    w.get("1")
    w.get("2")
    t[0] = 400.0
    w.get("3")                                             # a scan is in progress (lookup just now)
    n = calls["n"]
    assert w.run_once() == 0 and calls["n"] == n and w.stats["yielded_to_discovery"] == 1
    t[0] = 403.0                                           # scan over: idle >= 2 s
    assert w.run_once() >= 2


def test_entries_younger_than_120s_are_not_refetched():
    sec, t, _ = _pair()
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")
    t[0] = 100.0
    assert w.due() == []


# ------------------------------------------------------------------ concurrency: discovery priority (real threads)
def test_discovery_waits_at_most_about_one_in_flight_request_while_refresher_is_busy():
    import threading
    import time
    REQ = 0.05                                             # one SEC round trip in this test
    net = threading.Lock()

    def http(url, headers):
        with net:
            time.sleep(REQ)
            return _subs()
    sec = SecSubmissions(user_agent="ua", http_get=http, ttl_s=600, clock=time.monotonic)
    w = SR.BackgroundSecCache(sec, start=False, idle_gap_s=0.2, refresh_ahead_s=600, idle_sleep_s=0.005)
    for i in range(40):                                    # warm 40 entries; all immediately "due" (ahead = TTL)
        sec._cache[str(i)] = (time.monotonic(), _subs(), None)
        w._wanted[str(i)] = time.monotonic() - 10
    w._last_get = time.monotonic() - 10                    # discovery idle -> refresher starts working
    w.start()
    try:
        time.sleep(3 * REQ)                                # refresher is mid-queue now
        assert w.stats["refreshed"] >= 1
        waits = []
        for i in range(40):                                # a discovery scan: every lookup is a fresh cache hit
            a = time.monotonic()
            w.get(str(i))
            waits.append(time.monotonic() - a)
        assert max(waits) <= 2.5 * REQ + 0.05, max(waits)  # <= the in-flight request (+ one racing start), never a queue
        assert w.stats["yielded_to_discovery"] >= 1
    finally:
        w.stop()


# ------------------------------------------------------------------ 600 s freshness contract (property, fake clock)
def test_every_served_copy_is_younger_than_ttl_or_fetched_synchronously():
    import random
    rnd = random.Random(7)
    t = [0.0]
    fetched = {"n": 0}

    def http(url, headers):
        fetched["n"] += 1
        if rnd.random() < 0.1:
            raise TimeoutError("timed out")
        return _subs()
    sec = SecSubmissions(user_agent="ua", http_get=http, clock=lambda: t[0], ttl_s=600)
    w = SR.BackgroundSecCache(sec, start=False, idle_gap_s=2.0)
    for step in range(3000):
        t[0] += rnd.choice([0.3, 0.3, 1, 5, 60, 250])
        if rnd.random() < 0.3:
            w.run_once()
            continue
        cik = str(rnd.randrange(40))
        before = sec._cache.get(cik)
        n0 = fetched["n"]
        w.get(cik)
        if before is not None and t[0] - before[0] < 600:
            continue                                       # served a <600 s copy: allowed
        # otherwise the call MUST have gone through today's synchronous path (fetch attempted, or 429 back-off)
        assert fetched["n"] == n0 + 1 or t[0] < sec._backoff_until


# ------------------------------------------------------------------ failure behaviour
def test_refresher_crash_never_affects_discovery(monkeypatch):
    import time
    sec, t, calls = _pair()
    w = SR.BackgroundSecCache(sec, start=False, idle_sleep_s=0.005)
    w.get("1")
    monkeypatch.setattr(w, "run_once", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    w.start()
    time.sleep(0.05)
    try:
        assert w._thread.is_alive()                        # the loop survives its own crash
        assert w.get("1")[0] is not None                   # discovery path unaffected
    finally:
        w.stop()


def test_cache_write_failure_during_refresh_restores_the_previous_copy(monkeypatch):
    sec, t, calls = _pair()
    w = SR.BackgroundSecCache(sec, start=False)
    first = w.get("1")
    fetched_at = sec._cache["1"][0]
    t[0] = 400.0
    real_get = sec.get
    monkeypatch.setattr(sec, "get", lambda cik: (_ for _ in ()).throw(OSError("write failed")))
    assert w.refresh_one("1") is False                     # no exception escapes the refresher
    monkeypatch.setattr(sec, "get", real_get)
    assert sec._cache["1"] == (fetched_at, first[0], first[1])   # previous copy AND fetch time restored
    t[0] = 450.0
    got = w.get("1")                                       # still served the original copy or refetched synchronously
    assert got[0] is not None


def test_restart_is_cold_and_partially_warm_cache_mixes_hits_and_sync_fetches():
    sec, t, calls = _pair()
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")
    t[0] = 10.0
    sec2, t2, calls2 = _pair()                             # "restart": nothing persisted
    w2 = SR.BackgroundSecCache(sec2, start=False)
    w2.get("1")
    assert calls2["n"] == 1 and w2.stats["sync_fallback"] == 1
    w.get("1")
    w.get("2")                                             # partially warm: 1 hit + 1 synchronous fetch
    assert w.stats["served_fresh"] == 1 and calls["n"] == 2


def test_shutdown_while_the_worker_is_active_is_clean():
    import threading
    import time
    ev = threading.Event()

    def http(url, headers):
        ev.wait(0.2)
        return _subs()
    sec = SecSubmissions(user_agent="ua", http_get=http, ttl_s=600, clock=time.monotonic)
    w = SR.BackgroundSecCache(sec, start=False, refresh_ahead_s=600, idle_gap_s=0.0, idle_sleep_s=0.005)
    for i in range(20):
        sec._cache[str(i)] = (time.monotonic(), _subs(), None)
        w._wanted[str(i)] = time.monotonic()
    w.start()
    time.sleep(0.05)
    w.stop(timeout=2.0)
    assert not w._thread.is_alive()
