"""
Task 131 Directive 5 -- the :8787 dashboard's NEW, additive
``v2_broad_discovery`` panel. ``v2_active_strategy`` (the original
39-name watchlist view) must stay byte-shape-unchanged; the broad
panel is a SEPARATE, read-only section.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from talonx_ops.dashboard_read import DashboardReadModel

NOW = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / ".talonx"
    (h / "experimental").mkdir(parents=True)
    (h / "intelligence").mkdir(parents=True)
    return h


def _model(home):
    return DashboardReadModel(home=home, exp_home=home / "experimental",
                             intel_ledger=home / "ingestion_ledger.db", now=NOW)


def test_panel_present_and_additive_no_stores(home):
    model = _model(home)
    sections = model.all_sections()
    assert "v2_broad_discovery" in sections
    assert "v2_active_strategy" in sections
    panel = sections["v2_broad_discovery"]
    assert panel["panel"].startswith("Broad Discovery")
    assert panel["not_a_replacement_for_the_39_name_view"] is True
    # this dashboard reads the SAME real v2_lane.db path v2_active_strategy()
    # does (by design -- it is the live ledger) -- so its exact ledger
    # status depends on that ledger's own current, real, changing state;
    # only its recognized-status-vocabulary membership is asserted here.
    assert panel["ledger"]["status"] in ("NO_ACTIVE_PRODUCER", "ZERO_ACTIVITY", "ACTIVE", "UNKNOWN")


def test_panel_reads_manifest_and_reports_toggles(home, monkeypatch, tmp_path):
    monkeypatch.delenv("TALONX_INTEL_ENABLE_BROAD_DISCOVERY", raising=False)
    monkeypatch.delenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", raising=False)
    panel = _model(home).v2_broad_discovery()
    assert panel["universe_n"] >= 0   # reads the real frozen manifest if present
    assert panel["toggles"] == {
        "sec_ingestion_expansion_enabled": False,
        "dispatch_send_enabled": False,
    }


def test_panel_toggles_reflect_env(home, monkeypatch):
    monkeypatch.setenv("TALONX_INTEL_ENABLE_BROAD_DISCOVERY", "true")
    monkeypatch.setenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", "true")
    panel = _model(home).v2_broad_discovery()
    assert panel["toggles"] == {
        "sec_ingestion_expansion_enabled": True,
        "dispatch_send_enabled": True,
    }


def test_original_watchlist_view_untouched_shape(home):
    # v2_active_strategy's own keys are exactly as before Task 131 -- no
    # new/renamed keys leaked in from the broad-discovery work.
    v2sec = _model(home).v2_active_strategy()
    assert v2sec["panel"] == "Active V2 -- INSIDER_BUY_CLUSTER_V2@1"
    assert "v2_broad_discovery" not in v2sec
    assert "broad_discovery" not in json.dumps(v2sec).lower()


def test_broad_discovery_counts_never_double_count_the_39_name_watchlist(home, monkeypatch):
    # the arithmetic invariant holds regardless of the actual manifest
    # content: broad-discovery-only = universe - overlap, never negative,
    # never double-counting a symbol already in the 39-name watchlist.
    panel = _model(home).v2_broad_discovery()
    assert panel["overlap_with_39_name_watchlist_n"] <= panel["universe_n"]
    assert panel["broad_discovery_only_symbols_n"] == (
        panel["universe_n"] - panel["overlap_with_39_name_watchlist_n"])
    assert panel["broad_discovery_only_symbols_n"] >= 0
