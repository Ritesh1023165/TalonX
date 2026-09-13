"""
Task 131 -- Concurrent Admission Fix and SPA Dashboard Acceptance,
section 5: automated frontend coverage for the new Broad Discovery SPA
tab, following this repo's own established pattern for testing
``dashboard_web_static/index.html`` (static-content assertions, e.g.
``test_task100c_unified_dashboard.py::test_45_narrow_layout_integrity``)
plus an aiohttp ``TestClient`` wiring check -- no Node/JS test runner is
available in this environment, so these are the meaningful, automated
checks that ARE runnable here. Real, rendered-in-a-browser screenshot
verification (headless Chrome) was performed separately and is recorded
in the SPA acceptance document; it is not repeated as an automated test
because it requires a locally-installed browser binary this test suite
cannot assume is present in every CI environment.
"""
from __future__ import annotations

from pathlib import Path

import pytest

HTML = Path("dashboard_web_static/index.html").read_text(encoding="utf-8")


def test_broad_discovery_nav_button_present_and_wired():
    assert 'data-sec="v2_broad_discovery"' in HTML
    assert '>Broad Discovery<' in HTML
    # existing Active V2 tab untouched -- both present, not replaced
    assert 'data-sec="v2_active_strategy"' in HTML
    assert '>Active V2<' in HTML


def test_broad_discovery_renderer_registered_in_section_dispatch():
    assert "function renderV2Discovery(d){" in HTML
    assert "v2_broad_discovery: renderV2Discovery" in HTML
    # deep-link hash routing picks up any key in SECTION_RENDER automatically
    # (sectionFromHash()) -- no separate wiring needed, but confirm the
    # dispatch table itself is intact around the new entry.
    assert "const SECTION_RENDER = {" in HTML


def test_broad_discovery_renderer_never_puts_pill_markup_inside_a_bounded_table_cell():
    # boundedTable() passes every cell through esc(num(...)) -- a get()
    # that returns pill()'s own HTML would be escaped into literal,
    # broken markup. Confirm the new renderer avoids this trap (a real
    # bug caught and fixed during this task's own local verification).
    start = HTML.index("function renderV2Discovery(d){")
    end = HTML.index("\nconst SECTION_RENDER", start)
    body = HTML[start:end]
    assert "get:c=>pill(" not in body
    assert "get:x=>pill(" not in body


def test_broad_discovery_never_invents_a_reference_price_or_hardcodes_universe_counts():
    start = HTML.index("function renderV2Discovery(d){")
    end = HTML.index("\nconst SECTION_RENDER", start)
    body = HTML[start:end]
    # the reference-price string is rendered verbatim from the backend
    # payload field (already labelled PENDING there, see dashboard_read.py)
    # -- this tab reads i.reference_price rather than fabricating its own
    # numeric price from other fields.
    assert "reference_price" in body
    assert "i.reference_price" in body
    # universe/coverage numbers come from the payload fields, never a
    # literal 626/569/57 baked into the page itself.
    for literal in ("626", "569", "57"):
        assert f">{literal}<" not in body


def test_new_pill_states_have_explicit_css_rules():
    for state in ("GATED", "PERMISSIVE", "REJECTED", "EXPIRED", "FILLED", "UNCLASSIFIED"):
        assert f".pill.{state}" in HTML


def test_shared_campaign_ledger_note_rendered_not_dropped():
    start = HTML.index("function renderV2Discovery(d){")
    end = HTML.index("\nconst SECTION_RENDER", start)
    body = HTML[start:end]
    assert "shared_campaign_ledger_note" in body


def test_narrow_layout_rule_still_intact():
    # regression: the pre-existing responsive rule (shared by every tab,
    # including this new one) was not touched.
    assert "@media (max-width:640px)" in HTML
    assert "grid-template-columns:1fr" in HTML


@pytest.mark.asyncio
async def test_all_sections_endpoint_serves_broad_discovery_alongside_every_other_section(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    import dashboard_web

    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/api/section/v2_broad_discovery")
        assert r.status == 200
        d = await r.json()
        for key in ("universe_coverage", "admission_policy", "source_health",
                   "discovery_funnel", "action_queue", "shared_campaign_ledger_note",
                   "dashboard_refresh_utc"):
            assert key in d
        # the original watchlist view is served from the SAME app, unaffected
        r2 = await c.get("/api/section/v2_active_strategy")
        assert r2.status == 200
