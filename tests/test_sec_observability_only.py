"""SEC observability-only mode (2026-09-29): production default TALONX_SEC_REFRESH_CAPACITY=OBSERVABILITY_ONLY keeps the
live (cf0cffb) refresher behaviour and adds only raw freshness / stale-fallback evidence. No network: injected fakes."""
from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path

import pytest

from talonx_opportunity import sec_refresh as SR
from talonx_premarket.catalysts import SecSubmissions

REPO = Path(__file__).resolve().parents[1]
MODES = (SR.OBSERVABILITY_ONLY, SR.REMEDIATION_V1)


def _subs(tag=0):
    return {"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-09-24"],
                                   "acceptanceDateTime": ["2026-09-24T12:00:00Z"],
                                   "accessionNumber": [f"0000000000-26-{tag:06d}"], "items": ["2.02"]}}}


def _sec(fail=None):
    t = [0.0]
    calls = {"n": 0}

    def get(url, headers):
        calls["n"] += 1
        if fail and fail.get("on"):
            raise fail["exc"]
        return _subs(calls["n"])
    return SecSubmissions(user_agent="ua", http_get=get, clock=lambda: t[0], ttl_s=600), t, calls


def _scan(w, fn):
    w.begin_scan()
    fn()
    return w.end_scan()


# ------------------------------------------------------------------------------------------------ production default
def test_production_default_is_observability_only_with_no_capacity_change():
    sec, _, _ = _sec()
    w = SR.maybe_wrap(sec, env={SR.FLAG: "1"})
    try:
        assert w.capacity == SR.OBSERVABILITY_ONLY and w.limiter is None
        assert w.scan_refresh_rate_per_s == 0 and w.reuse_window_s == float("inf")
        assert w.detail()["capacity"] == SR.OBSERVABILITY_ONLY
    finally:
        w.stop()
    assert SR.capacity_mode({}) == SR.OBSERVABILITY_ONLY
    with pytest.raises(SystemExit):
        SR.capacity_mode({SR.CAPACITY_ENV: "FAST"})


# ------------------------------------------------------------------------------------------------ failure paths (both)
@pytest.mark.parametrize("mode", MODES)
def test_fresh_hit_and_expired_with_successful_sync_refresh(mode):
    sec, t, _ = _sec()
    w = SR.BackgroundSecCache(sec, start=False, capacity=mode)
    m = _scan(w, lambda: w.get("1"))
    assert (m["sync_refresh_count"], m["cache_fresh_count"]) == (1, 0)
    t[0] = 599.9
    m = _scan(w, lambda: w.get("1"))
    assert (m["cache_fresh_count"], m["max_served_age_raw"], m["count_age_ge_600"]) == (1, 599.9, 0)
    t[0] = 700.0                                           # expired -> synchronous refresh succeeds
    m = _scan(w, lambda: w.get("1"))
    assert (m["sync_refresh_count"], m["stale_fallback_count"], m["max_served_age_raw"]) == (1, 0, 0.0)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("exc,reason", [(RuntimeError("HTTP Error 503"), SR.FETCH_ERROR),
                                        (TimeoutError("The read operation timed out"), SR.TIMEOUT),
                                        (RuntimeError("HTTP Error 429: Too Many Requests"), SR.RATE_LIMIT),
                                        (RuntimeError(""), SR.FETCH_ERROR)])     # any recorded error = FETCH_ERROR
def test_expired_plus_failure_is_a_visible_stale_fallback_at_or_above_600(mode, exc, reason):
    fail = {"on": False, "exc": exc}
    sec, t, _ = _sec(fail)
    w = SR.BackgroundSecCache(sec, start=False, capacity=mode)
    first = w.get("1")
    fail["on"] = True
    t[0] = 600.0                                           # exactly the TTL: not fresh -> fetch -> fails -> stale copy
    m = _scan(w, lambda: w.get("1"))
    assert m["stale_fallback_count"] == 1 and m["cache_fresh_count"] == 0
    assert m["stale_fallback_reasons"] == {f"STALE_FALLBACK:{reason}": 1}
    assert m["max_served_age_raw"] == 600.0 and m["stale_fallback_max_age_raw"] == 600.0
    assert (m["count_age_ge_590"], m["count_age_ge_595"], m["count_age_ge_600"]) == (1, 1, 1)
    assert w.get("1")[0] is first[0]                       # the served payload is the previous copy (semantics kept)


@pytest.mark.parametrize("mode", MODES)
def test_backoff_serves_stale_without_a_request(mode):
    fail = {"on": False, "exc": RuntimeError("HTTP Error 429: Too Many Requests")}
    sec, t, calls = _sec(fail)
    w = SR.BackgroundSecCache(sec, start=False, capacity=mode)
    w.get("1")
    w.get("2")
    fail["on"] = True
    t[0] = 700.0
    w.get("1")
    n = calls["n"]
    m = _scan(w, lambda: w.get("2"))
    assert calls["n"] == n and m["stale_fallback_reasons"] == {"STALE_FALLBACK:RATE_LIMIT_BACKOFF": 1}


@pytest.mark.parametrize("mode", MODES)
def test_raw_precision_distinguishes_599_9_from_600(mode):
    sec, t, _ = _sec()
    w = SR.BackgroundSecCache(sec, start=False, capacity=mode)
    w.get("1")
    t[0] = 599.95
    m = _scan(w, lambda: w.get("1"))
    assert m["max_served_age_s"] == 600.0                  # legacy rounded field kept for compatibility
    assert m["max_served_age_raw"] == 599.95 and m["count_age_ge_600"] == 0 and m["count_age_ge_595"] == 1
    assert m["served_age_p95_raw"] == 599.95 and m["served_age_p99_raw"] == 599.95


# ------------------------------------------------------------------------------------------------ OBSERVABILITY_ONLY = cf0cffb
def _old_module():
    p = REPO / "docs" / "research" / "evidence" / "2026-09-28_monday_live_acceptance" / "tools" / "sec_refresh_old.py"
    if not p.exists():
        pytest.skip("archived cf0cffb refresher not present")
    spec = importlib.util.spec_from_file_location("sec_refresh_cf0cffb", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _drive(w, sec, t, calls, fail):
    """A deterministic mixed sequence: lookups, time steps, refresher passes, failures. Returns the observable trace."""
    trace = []
    for step in range(60):
        t[0] = step * 37.0
        fail["on"] = step in (20, 21, 40)
        for cik in (str(step % 7), str((step * 3) % 11)):
            res = w.get(cik)
            trace.append(("get", cik, None if res[0] is None else res[0]["filings"]["recent"]["accessionNumber"][0]))
        if step % 5 == 4:
            t[0] += 3.0                                     # discovery idle gap -> refresher may run
            trace.append(("refreshed", w.run_once()))
        trace.append(("req", sec.requests, calls["n"], len(sec.errors)))
    return trace


def test_observability_only_matches_the_live_cf0cffb_refresher_step_for_step():
    old = _old_module()
    traces = []
    for build in (lambda s: old.BackgroundSecCache(s, start=False),
                  lambda s: SR.BackgroundSecCache(s, start=False, capacity=SR.OBSERVABILITY_ONLY)):
        fail = {"on": False, "exc": RuntimeError("HTTP Error 500")}
        sec, t, calls = _sec(fail)
        w = build(sec)
        cache = {k: (v[0], v[1]) for k, v in sorted(sec._cache.items())}       # observed_at is wall clock: excluded
        traces.append((_drive(w, sec, t, calls, fail), cache, dict(w.stats) if hasattr(w, "stats") else None))
    for k in ("stale_fallback", "no_data", "refresh_superseded"):                 # new observability-only counters
        traces[1][2].pop(k, None)
    assert traces[0] == traces[1]


def test_observability_only_refresher_never_runs_while_discovery_is_active():
    sec, t, calls = _sec()
    w = SR.BackgroundSecCache(sec, start=False, capacity=SR.OBSERVABILITY_ONLY)
    for c in "abc":
        w.get(c)
    t[0] = 500.0
    w.get("a")                                              # discovery just looked something up (fresh hit, age 500)
    n = calls["n"]
    assert w.run_once() == 0 and calls["n"] == n and w.stats["yielded_to_discovery"] == 1
    t[0] = 503.0                                            # idle gap passed
    assert w.run_once() == 3                                # a, b, c all within refresh_ahead of the TTL
    assert SR.failure_reason("") == SR.OTHER                # stale with no recorded error -> OTHER


def test_observability_only_refresher_holds_the_lock_during_io_like_the_live_one():
    gate = threading.Event()

    def http(url, headers):
        gate.wait(0.3)
        return _subs()
    sec = SecSubmissions(user_agent="ua", http_get=http, ttl_s=600, clock=time.monotonic)
    sec._cache["1"] = (time.monotonic() - 590, _subs(), None)
    sec._cache["2"] = (time.monotonic(), _subs(), None)
    w = SR.BackgroundSecCache(sec, start=False, capacity=SR.OBSERVABILITY_ONLY)
    th = threading.Thread(target=w.refresh_one, args=("1",))
    th.start()
    time.sleep(0.05)
    a = time.monotonic()
    w.get("2")                                              # waits for the refresher's request (cf0cffb behaviour)
    waited = time.monotonic() - a
    gate.set()
    th.join()
    assert waited > 0.1                                     # i.e. NO capacity change was slipped into the default


def test_discovery_config_fingerprint_is_unchanged_in_observability_only_mode():
    src = (REPO / "talonx_opportunity" / "discovery.py").read_text(encoding="utf-8")
    assert '"BACKGROUND_REFRESH_V1" if sec_refresh.capacity_mode() == \\\n            sec_refresh.OBSERVABILITY_ONLY' in src
