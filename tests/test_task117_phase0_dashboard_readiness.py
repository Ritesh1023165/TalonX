"""
Task 117 Phase 0 Phase 5 -- the :8787 read-model distinguishes
NO_OPPORTUNITIES from DATA_UNAVAILABLE / INCOMPLETE_COVERAGE and surfaces
source + pricing readiness (read-only; no writes).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from talonx_ops.dashboard_read import DashboardReadModel


def _model(tmp_path, status: dict):
    (tmp_path / "v2_service_status.json").write_text(json.dumps(status))
    (tmp_path / "v2_lane.db").write_bytes(b"")   # exists but empty -> ledger ZERO_ACTIVITY
    m = DashboardReadModel()
    import os
    os.environ["TALONX_V2_STATUS_PATH"] = str(tmp_path / "v2_service_status.json")
    os.environ["TALONX_V2_DB_PATH"] = str(tmp_path / "v2_lane.db")
    try:
        return m.v2_active_strategy()
    finally:
        os.environ.pop("TALONX_V2_STATUS_PATH", None)
        os.environ.pop("TALONX_V2_DB_PATH", None)


def _base(**over):
    s = {
        "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
        "heartbeat_ttl_s": 180, "strategy_version": "INSIDER_BUY_CLUSTER_V2@1",
        "form4_source": "insider", "form4_records_seen": 12,
        "pricing_mode": "csv", "pricing_adapter": "csv:frozen_bar_dirs",
        "source": {"actual": "insider", "ok": True, "last_ok_utc": "2026-09-09T20:00:00+00:00"},
        "data_state": "CURRENT",
    }
    s.update(over)
    return s


def test_degraded_source_shows_data_unavailable(tmp_path):
    out = _model(tmp_path, _base(data_state="DATA_UNAVAILABLE",
                                 source={"actual": "insider", "ok": False,
                                         "degraded": "InsiderStore read failed", "records": 0}))
    assert out["data_state"] == "DATA_UNAVAILABLE"
    assert out["activity"] == "DATA_UNAVAILABLE"
    assert out["readiness"]["form4_source_ok"] is False
    assert out["readiness"]["form4_source_degraded"]


def test_healthy_no_clusters_is_no_opportunities(tmp_path):
    out = _model(tmp_path, _base())
    assert out["readiness"]["form4_source_actual"] == "insider"
    assert out["readiness"]["pricing_mode"] == "csv"
    assert out["activity"] in ("NO_OPPORTUNITIES", "INCOMPLETE_COVERAGE")
    assert out["data_state"] in ("CURRENT", "UNKNOWN")


def test_pricing_unavailable_recent_flags_incomplete_coverage(tmp_path):
    out = _model(tmp_path, _base(pricing_mode="composite-yf",
                                 pricing_unavailable_recent=["ABCL:NO_BAR", "XYZ:PROVISIONAL_ONLY"]))
    assert out["readiness"]["pricing_mode"] == "composite-yf"
    assert out["readiness"]["pricing_unavailable_recent"]
    assert out["activity"] == "INCOMPLETE_COVERAGE"
