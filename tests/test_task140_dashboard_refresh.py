"""
tests/test_task140_dashboard_refresh.py
=========================================
Task 140 -- real-browser behavioural verification that a background
dashboard refresh no longer interrupts reading. Every scenario below
drives the ACTUAL shipped JS in ``dashboard_web_static/index.html``
inside a real (headless) Chrome, against a real, in-process
``dashboard_web.build_app()`` aiohttp server bound to a real localhost
port. Section data is served from deterministic, synthetic fixtures
(``_Fixtures`` below) -- no live production trades/campaign/ledger data
is read, created or altered anywhere in this file.

Skips cleanly (not a failure, not an error) if no Chrome/Chromium binary
is found on this machine, so the rest of the suite stays green in an
environment without a browser installed -- see _dashboard_browser.py's
own docstring for why this drives Chrome's own DevTools Protocol
directly rather than adding Playwright/Selenium/Node as a new
dependency (none of those are installed here; Chrome already is).
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest
from aiohttp import web

from _dashboard_browser import CDPPage, find_chrome

CHROME_PATH = find_chrome()
pytestmark = pytest.mark.skipif(
    CHROME_PATH is None, reason="no Chrome/Chromium binary found on this machine"
)


# ---------------------------------------------------------------------
# synthetic, deterministic section fixtures -- never live data
# ---------------------------------------------------------------------
def _events(n, *, offset=0, symbol_prefix="SYM"):
    return [{
        "event_id": f"EVT-{i:05d}",
        "symbol": f"{symbol_prefix}{i:03d}",
        "event_type": "REGULATION_FD",
        "accepted_at": f"2026-09-15T{9 + ((i+offset)//30) % 12:02d}:{(i+offset)%60:02d}:00Z",
    } for i in range(offset, offset + n)]


def _intelligence_payload(events, sig_events=None):
    return {
        "status": "ACTIVE",
        "producer": {"live": True, "heartbeat_at": "2026-09-15T10:00:00Z"},
        "newest_event": "2026-09-15T10:00:00Z",
        "note": "synthetic fixture -- Task 140 dashboard refresh verification, not live data",
        "authoritative_source": "test fixture",
        "deep_link": "http://127.0.0.1:8760/",
        "counts": {"total": len(events)},
        "deep_links": {},
        "card_delivery": None,
        "latest_events": events,
        # kept independent of `events` by default -- a caller can pin this
        # to isolate a test to changes in exactly ONE table at a time.
        "significance_ranked": (sig_events if sig_events is not None else events[:10]),
    }


def _overview_payload():
    return {
        "runtime": {"overall": "READY"},
        "market": {},
        "alerts": {},
        "active_v2": {"error": "not applicable to this synthetic fixture"},
        "source_status": [],
    }


class _Fixtures:
    """Thread-safe, test-controlled stand-in for DashboardReadModel --
    lets a test change what the server returns between successive
    /api/section/<name> polls, deterministically, to prove real request/
    response behaviour (new rows arriving, a stale delayed response, a
    failed request) without depending on real backend timing."""

    def __init__(self):
        self.lock = threading.Lock()
        self.intelligence_events = _events(60)
        self.intelligence_sig_events = self.intelligence_events[:10]
        self.call_count: dict[str, int] = {}
        self.fail_next: set[str] = set()
        self.delay_next: dict[str, float] = {}

    def section(self, name: str) -> dict:
        with self.lock:
            self.call_count[name] = self.call_count.get(name, 0) + 1
            if name in self.fail_next:
                self.fail_next.discard(name)
                return {"error": "SIMULATED_FAILURE", "section": name}
            delay = self.delay_next.pop(name, 0.0)
            events = list(self.intelligence_events)
            sig_events = list(self.intelligence_sig_events)
        if delay:
            time.sleep(delay)
        if name == "intelligence":
            return _intelligence_payload(events, sig_events)
        if name == "overview":
            return _overview_payload()
        return {}


class _CurrentFixtures:
    """One mutable slot _section_block's monkeypatched replacement reads
    through -- lets each test install a fresh _Fixtures() without
    re-patching/rebuilding the (expensive) app+server per test."""
    obj: _Fixtures | None = None


_current = _CurrentFixtures()


def _patched_section_block(name: str) -> dict:
    assert _current.obj is not None, "test must set _current.obj before serving requests"
    return _current.obj.section(name)


# ---------------------------------------------------------------------
# module-scoped server (background thread, its own event loop) + browser
# ---------------------------------------------------------------------
class _ServerHandle:
    def __init__(self, loop, runner, port):
        self.loop = loop
        self.runner = runner
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"


@pytest.fixture(scope="module")
def dashboard_server(tmp_path_factory):
    import dashboard_web

    # Module-scoped monkeypatch (pytest's own `monkeypatch` fixture is
    # function-scoped and can't span this module-scoped server) --
    # restored explicitly in the finalizer below so this never leaks
    # into other test files/sessions that import the same module.
    original_section_block = dashboard_web._section_block
    dashboard_web._section_block = _patched_section_block  # type: ignore[attr-defined]

    state_dir = tmp_path_factory.mktemp("task140_dash_piv")
    app = dashboard_web.build_app(piv_state_dir=state_dir)

    loop = asyncio.new_event_loop()
    ready = threading.Event()
    handle: dict = {}

    def _run_loop():
        asyncio.set_event_loop(loop)

        async def _start():
            runner = web.AppRunner(app)
            await runner.setup()
            import socket as _socket
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            s.close()
            site = web.TCPSite(runner, "127.0.0.1", port)
            await site.start()
            handle["runner"] = runner
            handle["port"] = port
            ready.set()

        loop.run_until_complete(_start())
        loop.run_forever()

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    assert ready.wait(timeout=10), "dashboard server did not start"

    srv = _ServerHandle(loop, handle["runner"], handle["port"])
    yield srv

    async def _stop():
        await handle["runner"].cleanup()
    fut = asyncio.run_coroutine_threadsafe(_stop(), loop)
    fut.result(timeout=10)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=10)
    dashboard_web._section_block = original_section_block  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def browser():
    # A deliberately small viewport (not the default large window) so
    # even a section's own bounded-table row cap (e.g. boundedTable's
    # 15-row cap on Intelligence's "Latest events") reliably overflows
    # it and the page is genuinely scrollable -- the real defect this
    # task fixes only manifests when there is more content than fits.
    page = CDPPage(CHROME_PATH, headless=True, window=(900, 500))
    yield page
    page.close()


@pytest.fixture()
def dash(dashboard_server, browser):
    """Fresh fixtures + a fresh page load for every test -- avoids one
    test's timers/DOM state leaking into the next."""
    _current.obj = _Fixtures()
    browser.navigate(dashboard_server.base_url + "/", wait_load=True)
    # loadSection('overview') fires on load; give the very first fetch a
    # moment to land before a test starts issuing its own.
    _wait_until(lambda: browser.eval_js("document.querySelector('#section-view h2') != null"))
    return browser


def _wait_until(predicate, *, timeout=10, interval=0.1):
    deadline = time.time() + timeout
    last = False
    while time.time() < deadline:
        last = predicate()
        if last:
            return
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s (last value={last!r})")


def _goto_intelligence(page):
    page.eval_js("document.querySelector('#primary button[data-sec=\"intelligence\"]').click()")
    _wait_until(lambda: page.eval_js(
        "document.querySelectorAll('#section-view [data-key]').length > 0"))


# ---------------------------------------------------------------------
# scenario 1 -- scroll midway, 3 automatic updates, no jump
# ---------------------------------------------------------------------
def test_scroll_position_survives_three_automatic_refreshes(dash):
    _goto_intelligence(dash)
    dash.eval_js("window.scrollTo(0, 900)")
    scroll_before = dash.eval_js("window.scrollY")
    assert scroll_before > 0, "test setup: page must actually be scrollable"
    top_key_before = dash.eval_js(
        "(document.elementFromPoint(50, 60)||{}).closest ? "
        "(document.elementFromPoint(50,60).closest('[data-key]')||{}).dataset && "
        "document.elementFromPoint(50,60).closest('[data-key]').dataset.key : null"
    )

    for _ in range(3):
        dash.eval_js("refreshActive(true)", await_promise=True)

    scroll_after = dash.eval_js("window.scrollY")
    assert abs(scroll_after - scroll_before) <= 2, (
        f"scroll jumped during auto-refresh: {scroll_before} -> {scroll_after}")
    top_key_after = dash.eval_js(
        "(document.elementFromPoint(50, 60)||{}).closest ? "
        "(document.elementFromPoint(50,60).closest('[data-key]')||{}).dataset && "
        "document.elementFromPoint(50,60).closest('[data-key]').dataset.key : null"
    )
    assert top_key_after == top_key_before, "the row visible at the same screen position changed identity"


# ---------------------------------------------------------------------
# scenario 2 -- new content prepended above while scrolled down
# ---------------------------------------------------------------------
def test_new_rows_above_do_not_auto_jump_and_show_an_indicator(dash):
    _goto_intelligence(dash)
    dash.eval_js("window.scrollTo(0, 900)")
    scroll_before = dash.eval_js("window.scrollY")

    _current.obj.intelligence_events = _events(10, offset=1000, symbol_prefix="NEW") + _current.obj.intelligence_events
    dash.eval_js("refreshActive(true)", await_promise=True)

    scroll_after = dash.eval_js("window.scrollY")
    # This is a genuine content restructure (10 rows inserted above, 10
    # different rows evicted from the same bounded table by its own row
    # cap), not the "identical content, no reflow" case scenario 1 covers
    # -- some residual drift is expected here even with a correctly-
    # working anchor (Chrome's own native `overflow-anchor` scroll
    # anchoring and this fix's explicit correction can each account for
    # only part of a genuinely-evicted anchor's neighbourhood). The bar
    # this asserts is the one the spec actually sets: no LARGE, dis-
    # orienting jump (in particular, never back near the top) -- not
    # pixel-perfect restoration when the anchored row itself is gone.
    drift = abs(scroll_after - scroll_before)
    assert drift <= 150, f"a background refresh moved the reader by {drift}px -- too large to be unnoticed"
    assert scroll_after > 500, "reader was pulled back up toward the top by a background refresh"
    has_pill = dash.eval_js("document.querySelector('.new-items-pill') != null")
    assert has_pill, "expected a 'new items' indicator, operator was not auto-moved"


# ---------------------------------------------------------------------
# scenario 3 -- expanded <details> survives a refresh
# ---------------------------------------------------------------------
def test_expanded_details_state_survives_refresh(dash):
    dash.eval_js("document.querySelector('#primary button[data-sec=\"overview\"]').click()")
    _wait_until(lambda: dash.eval_js("document.querySelector('#section-view details') != null"))
    dash.eval_js("document.querySelector('#section-view details').open = true")
    assert dash.eval_js("document.querySelector('#section-view details').open") is True

    dash.eval_js("refreshActive(true)", await_promise=True)

    assert dash.eval_js("document.querySelector('#section-view details').open") is True, (
        "a user-expanded <details> was collapsed by an automatic refresh")


# ---------------------------------------------------------------------
# scenario 4 -- keyboard focus survives a refresh
# ---------------------------------------------------------------------
def test_focus_outside_the_refreshed_region_is_not_disturbed(dash):
    dash.eval_js("document.querySelector('#primary button[data-sec=\"intelligence\"]').focus()")
    assert dash.eval_js("document.activeElement.dataset.sec") == "intelligence"

    dash.eval_js("refreshActive(true)", await_promise=True)

    assert dash.eval_js("document.activeElement.dataset.sec") == "intelligence", (
        "focus moved off the nav button during a background refresh")


# ---------------------------------------------------------------------
# scenario 5 -- pause stops updates; timestamp stays honest
# ---------------------------------------------------------------------
def test_pause_stops_automatic_updates_and_timestamp_freezes(dash):
    _goto_intelligence(dash)
    dash.eval_js("document.getElementById('refresh-pause-btn').click()")
    assert dash.eval_js("paused") is True
    assert dash.eval_js("refreshTimer") is None, "pause must stop the scheduled timer"

    ts_before = dash.eval_js("lastSuccessAt ? lastSuccessAt.getTime() : null")

    # an auto tick fired while paused must be a genuine no-op
    dash.eval_js("refreshActive(true)", await_promise=True)

    ts_after = dash.eval_js("lastSuccessAt ? lastSuccessAt.getTime() : null")
    assert ts_after == ts_before, "an automatic refresh applied data while paused"
    status = dash.eval_js("document.getElementById('refresh-status').textContent")
    assert "paused" in status.lower()


# ---------------------------------------------------------------------
# scenario 6 -- manual refresh works while paused, stays paused
# ---------------------------------------------------------------------
def test_manual_refresh_works_while_paused_and_stays_paused(dash):
    _goto_intelligence(dash)
    dash.eval_js("document.getElementById('refresh-pause-btn').click()")
    assert dash.eval_js("paused") is True
    ts_before = dash.eval_js("lastSuccessAt ? lastSuccessAt.getTime() : null")

    dash.eval_js("document.getElementById('refresh-manual-btn').click()")
    _wait_until(lambda: dash.eval_js("lastSuccessAt ? lastSuccessAt.getTime() : null") != ts_before)

    assert dash.eval_js("paused") is True, "manual refresh must not itself resume auto-refresh"
    assert dash.eval_js("refreshTimer") is None


# ---------------------------------------------------------------------
# scenario 7 -- resume re-arms exactly one timer (no duplicates)
# ---------------------------------------------------------------------
def test_resume_does_not_create_duplicate_timers(dash):
    dash.eval_js("document.getElementById('refresh-pause-btn').click()")   # pause
    dash.eval_js("document.getElementById('refresh-pause-btn').click()")   # resume
    assert dash.eval_js("paused") is False
    first_timer_id = dash.eval_js("refreshTimer")
    assert first_timer_id is not None

    # armRefreshTimer() must be idempotent -- calling it again (as a
    # double-click or a redundant resume would) must not replace the
    # handle with a second, duplicate interval.
    dash.eval_js("armRefreshTimer()")
    second_timer_id = dash.eval_js("refreshTimer")
    assert second_timer_id == first_timer_id, "resume/re-arm created a duplicate timer"


# ---------------------------------------------------------------------
# scenario 8 -- a delayed (stale) response cannot overwrite newer state
# ---------------------------------------------------------------------
def test_delayed_response_cannot_overwrite_newer_state(dash):
    _goto_intelligence(dash)
    # Inject a controlled fetch: the FIRST call to /api/section/intelligence
    # resolves slowly with OLD-looking data; a SECOND call issued right
    # after resolves fast with NEW-looking data. The real generation-guard
    # in fetchAndApplySection (not reimplemented here) must ensure the
    # late-arriving first response never overwrites the second.
    dash.eval_js("""
      window.__origFetch = window.fetch;
      window.__callN = 0;
      window.fetch = function(url, opts){
        if (String(url).indexOf('/api/section/intelligence') !== -1){
          window.__callN += 1;
          const n = window.__callN;
          if (n === 1){
            return new Promise(res => setTimeout(() => {
              res(new Response(JSON.stringify({latest_events:[{event_id:'STALE-1',symbol:'STALE',event_type:'X',accepted_at:'2020-01-01T00:00:00Z'}]}), {status:200}));
            }, 400));
          }
          return Promise.resolve(new Response(JSON.stringify({latest_events:[{event_id:'FRESH-1',symbol:'FRESH',event_type:'X',accepted_at:'2026-09-15T10:00:00Z'}]}), {status:200}));
        }
        return window.__origFetch(url, opts);
      };
    """)
    # fire the slow (stale) request, then immediately the fast (fresh) one
    dash.eval_js("fetchAndApplySection('intelligence', {auto:false})")
    dash.eval_js("fetchAndApplySection('intelligence', {auto:false})", await_promise=True)
    time.sleep(0.6)  # let the stale, slower first response arrive and attempt to apply

    html = dash.eval_js("document.getElementById('section-view').innerHTML")
    assert "FRESH-1" in html, "the fresher response should be the one shown"
    assert "STALE-1" not in html, "a late-arriving stale response overwrote newer state"
    dash.eval_js("window.fetch = window.__origFetch;")


# ---------------------------------------------------------------------
# scenario 9 -- a failed request keeps old content, recovers honestly
# ---------------------------------------------------------------------
def test_failed_request_keeps_content_and_recovers_without_losing_position(dash):
    _goto_intelligence(dash)
    dash.eval_js("window.scrollTo(0, 700)")
    scroll_before = dash.eval_js("window.scrollY")
    html_before = dash.eval_js("document.getElementById('section-view').innerHTML")

    _current.obj.fail_next.add("intelligence")
    dash.eval_js("refreshActive(true)", await_promise=True)

    status = dash.eval_js("document.getElementById('refresh-status').textContent")
    assert "error" in status.lower() or "fail" in status.lower()
    html_after_fail = dash.eval_js("document.getElementById('section-view').innerHTML")
    assert html_after_fail == html_before, "old content must be retained after a failed refresh"
    scroll_after_fail = dash.eval_js("window.scrollY")
    assert abs(scroll_after_fail - scroll_before) <= 2

    # recovery
    dash.eval_js("refreshActive(true)", await_promise=True)
    status2 = dash.eval_js("document.getElementById('refresh-status').textContent")
    assert "error" not in status2.lower() and "fail" not in status2.lower()
    scroll_after_recovery = dash.eval_js("window.scrollY")
    assert abs(scroll_after_recovery - scroll_before) <= 2, "recovery must not reset scroll"


# ---------------------------------------------------------------------
# scenario 10 -- tab change during an in-flight refresh keeps the RIGHT view
# ---------------------------------------------------------------------
def test_tab_switch_during_in_flight_refresh_shows_the_new_tab(dash):
    _goto_intelligence(dash)
    _current.obj.delay_next["intelligence"] = 1.0
    # kick off a slow refresh of intelligence, then switch to overview
    # before it can possibly resolve
    dash.eval_js("fetchAndApplySection('intelligence', {auto:true})")
    dash.eval_js("document.querySelector('#primary button[data-sec=\"overview\"]').click()")
    _wait_until(lambda: dash.eval_js(
        "document.querySelector('#primary button[data-sec=\"overview\"]').classList.contains('active')"))
    time.sleep(1.3)  # let the stale intelligence response arrive well after the switch

    active_tab = dash.eval_js(
        "document.querySelector('#primary button.active').dataset.sec")
    assert active_tab == "overview", "a stale in-flight response from the old tab took over the view"
    assert dash.eval_js("document.querySelector('#section-view h2').textContent").startswith("Overview")
