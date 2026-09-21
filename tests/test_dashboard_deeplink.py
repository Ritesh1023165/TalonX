"""
tests/test_dashboard_deeplink.py
--------------------------------
Task 96G -- deterministic deep-link routes (Phase 15).
"""
from __future__ import annotations

from talonx_ingest.intelligence.dashboard import deeplink as D


def test_routes_are_built_from_deterministic_identity():
    eid = "SEC:0000320193-26-000003:RESTRUCTURING"
    assert D.event_path(eid) == "/event/SEC%3A0000320193-26-000003%3ARESTRUCTURING"
    assert D.company_path("aapl") == "/company/AAPL"
    assert D.filing_path("CMP:a:b:filing_comparison@v1") == "/filing/CMP%3Aa%3Ab%3Afiling_comparison%40v1"
    assert D.event_evidence_path(eid).startswith("/evidence/event/")


def test_absolute_is_safe_with_bad_base():
    assert D.absolute("", "/event/x") == "/event/x"
    assert D.absolute("javascript:evil", "/event/x") == "/event/x"
    assert D.absolute("https://talonx.local", "/event/x") == "https://talonx.local/event/x"
    assert D.absolute("https://talonx.local/", "/x") == "https://talonx.local/x"


def test_round_trip_through_url_unquote():
    from urllib.parse import unquote

    eid = "SEC:0000320193-26-000003:RESTRUCTURING"
    assert unquote(D.event_path(eid)[len("/event/"):]) == eid


def test_api_mirrors_exist():
    assert D.api_today() == "/api/today"
    assert D.api_company("aapl") == "/api/company/AAPL"
    assert D.api_event("x:y").startswith("/api/event/")
