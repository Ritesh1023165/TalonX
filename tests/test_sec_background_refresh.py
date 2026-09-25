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
    t[0] = 400.0                                           # within 240 s of the 600 s TTL -> due
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
