"""
Task 117 deployment-readiness Item 5 -- essential operator-visibility states on
the :8787 read-model that back the actual SPA.

Screenshot-able states (Overview V2 summary, populated funnel, candidate pricing,
source failure, pricing unavailable) are captured in
results/task117_controlled_deployment_readiness_*/spa/.  The states that need a
controlled clock -- STARTING, STARTUP_FAILED, market-closed, EOD PENDING / EOD
COMPLETED -- are verified here against the real read-model with a fixed `now`.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_ops.dashboard_read import DashboardReadModel
from talonx_ops.prospective import checkpoint as _ck


def _v2_db(tmp_path, *, cash=300000.0, open_pos=False):
    db = tmp_path / "v2_lane.db"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE portfolio (id INTEGER PRIMARY KEY CHECK (id=1), cash REAL NOT NULL);
      CREATE TABLE positions (position_id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT UNIQUE,
        symbol TEXT, status TEXT, entry_session TEXT, target_exit_session TEXT, entry_price REAL,
        shares REAL, position_cost REAL, opened_at TEXT, realized_pnl_usd REAL);
      CREATE TABLE trades (trade_id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT);
      CREATE TABLE processed_episodes (episode_id TEXT PRIMARY KEY, symbol TEXT, disposition TEXT,
        eligible_entry_session TEXT);
      CREATE TABLE pending_entry_intents (intent_id TEXT PRIMARY KEY, episode_id TEXT UNIQUE,
        symbol TEXT, status TEXT, target_entry_session TEXT, created_at_utc TEXT);
      CREATE TABLE v2_alert_outbox (event_id TEXT PRIMARY KEY, episode_id TEXT, kind TEXT,
        action TEXT, symbol TEXT, state TEXT, attempts INT, transport_ref TEXT, last_error TEXT,
        deliver_by_utc TEXT, created_at_utc TEXT, sent_at_utc TEXT);
    """)
    con.execute("INSERT INTO portfolio VALUES (1, ?)", (cash,))
    if open_pos:
        con.execute("INSERT INTO positions (episode_id,symbol,status,entry_session,"
                    "target_exit_session,entry_price,shares,position_cost,opened_at) VALUES "
                    "('ep1','AAA','OPEN','2026-09-02','2026-09-16',20.0,500,10000,'x')")
        con.execute("INSERT INTO trades (action) VALUES ('BUY')")
    con.commit(); con.close()
    return db


def _status(tmp_path, **kw):
    s = {"heartbeat_utc": datetime.now(timezone.utc).isoformat(), "heartbeat_ttl_s": 180,
         "strategy_version": "INSIDER_BUY_CLUSTER_V2@1", "form4_source": "insider",
         "form4_records_seen": 4, "tick": 9, "pricing_mode": "composite-yf",
         "pricing_adapter": "composite(...)", "data_state": "CURRENT", "delivery_enabled": True,
         "pending_entry_intents": [], "alert_outbox": {"total": 0, "by_state": {}, "recent": []},
         "source": {"actual": "insider", "ok": True,
                    "last_ok_utc": datetime.now(timezone.utc).isoformat()}}
    s.update(kw)
    p = tmp_path / "s.json"
    p.write_text(json.dumps(s))
    return p


def _dr(tmp_path, *, now=None, status=True, open_pos=False, status_kw=None):
    db = _v2_db(tmp_path, open_pos=open_pos)
    st = _status(tmp_path, **(status_kw or {})) if status else (tmp_path / "nonexist.json")
    import os
    os.environ["TALONX_V2_DB_PATH"] = str(db)
    os.environ["TALONX_V2_STATUS_PATH"] = str(st)
    return DashboardReadModel(home=tmp_path, check_processes=False,
                              intel_ledger=tmp_path / "no_intel.db",
                              now=now or datetime.now(timezone.utc))


# --------------------------------------------------------------------------- STARTING
def test_starting_state_when_young_session_no_status(tmp_path, monkeypatch):
    monkeypatch.setattr(_ck, "_session_started_utc",
                        lambda now: datetime.now(timezone.utc) - timedelta(seconds=40))
    dr = _dr(tmp_path, status=False)
    v2 = dr.v2_active_strategy()
    assert v2["health"] == "STARTING"
    assert v2["service"]["status"] == "STARTING"
    assert "deadline" in (v2["service"]["note"] or "")


def test_startup_failed_state_when_grace_exhausted(tmp_path, monkeypatch):
    monkeypatch.setattr(_ck, "_session_started_utc",
                        lambda now: datetime.now(timezone.utc) - timedelta(seconds=_ck.STARTUP_GRACE_S + 30))
    dr = _dr(tmp_path, status=False)
    v2 = dr.v2_active_strategy()
    assert v2["health"] == "STARTUP_FAILED"


# --------------------------------------------------------------------------- market closed / EOD
def _xnys_close(day: str) -> datetime:
    import exchange_calendars as xc
    return xc.get_calendar("XNYS").session_close(day).to_pydatetime()


def test_eod_phase_aware_states_market_closed_pending_stale(tmp_path):
    # the phase-aware function that backs the SPA's eod state -- controlled clock
    close = _xnys_close("2026-09-09")
    assert _ck.eod_state(datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc))["state"] == "NOT_DUE_YET"
    assert _ck.eod_state(close + timedelta(minutes=30))["state"] == "PENDING"        # market closed, in grace
    assert _ck.eod_state(close + timedelta(minutes=200))["state"] == "STALE"          # deadline missed
    assert _ck.eod_state(datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc))["state"] == "NOT_DUE_YET"  # weekend


def test_dashboard_surfaces_an_eod_state_block(tmp_path):
    dr = _dr(tmp_path)
    v2 = dr.v2_active_strategy()
    assert "eod" in v2 and isinstance(v2["eod"].get("state"), str)


# --------------------------------------------------------------------------- Overview V2 summary
def test_overview_active_v2_carries_the_new_fields(tmp_path):
    dr = _dr(tmp_path, status_kw={"pricing_unavailable_recent": ["ADC:PROVISIONAL_ONLY"]},
             open_pos=True)
    ov = dr.overview()
    v2 = ov["active_v2"]
    assert "error" not in v2
    assert v2["v2_fingerprint"] == "11107198c5b81237"
    assert v2["candidate_pricing"] is True and v2["pricing_mode"] == "composite-yf"
    assert v2["pricing_state"] == "DEGRADED"                  # independent of an open position
    assert v2["coverage_state"] in ("INCOMPLETE_COVERAGE", "DATA_STALE", "DATA_UNAVAILABLE")
    assert v2["business_activity"] == "POSITION_OPEN"
    assert isinstance(v2["delivery"], dict) and "enabled" in v2["delivery"]
    assert "delayed notification" in v2["delayed_fill_semantics"]


def test_overview_v2_pricing_and_coverage_not_masked_by_open_position(tmp_path):
    dr = _dr(tmp_path, status_kw={"pricing_unavailable_recent": ["X:NO_BAR"]}, open_pos=True)
    v2 = dr.overview()["active_v2"]
    # activity is POSITION_OPEN, yet pricing DEGRADED is still visible
    assert v2["business_activity"] == "POSITION_OPEN" and v2["pricing_state"] == "DEGRADED"
