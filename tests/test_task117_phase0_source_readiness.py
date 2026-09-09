"""
Task 117 Phase 0 -- Acceptance closure Phase 6: real source readiness.

`status.source.last_ok_utc` measures **DB-read success**, not upstream-poll
completion. These are separate signals; a fresh process heartbeat is not proof
of a current/complete filing read. Coverage, pricing readiness and event-source
readiness are independent.

Isolated stores / status files / caches only. No production DB, Redis, network.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from talonx_v2.config import V2Config
from talonx_v2.service import V2Service, V2SourceError


class _RaisingStore:
    def query_transactions(self, **_):
        raise RuntimeError("ingestion_ledger.db locked")


class _EmptyStore:
    def query_transactions(self, **_):
        return []


def _svc(tmp_path, kind="insider"):
    cfg = V2Config(db_path=str(tmp_path / "v.db"), starting_cash_usd=300_000.0)
    return V2Service(config=cfg, bar_dirs=[tmp_path], form4_kind=kind,
                     status_path=str(tmp_path / "s.json"))


def _patch_store(monkeypatch, obj):
    import talonx_ingest.intelligence.insider.store as _st
    monkeypatch.setattr(_st, "InsiderStore", lambda *a, **k: obj)


# --------------------------------------------------------------------------- S2
def test_s2_insider_read_failure_is_DATA_UNAVAILABLE_not_silent_fallback(tmp_path, monkeypatch):
    _patch_store(monkeypatch, _RaisingStore())
    svc = _svc(tmp_path)
    st = svc.tick(as_of=date(2026, 9, 9))
    assert st["heartbeat_kind"] == "DEGRADED_SOURCE"
    assert st["data_state"] == "DATA_UNAVAILABLE"
    assert st["entries_this_tick"] == 0 and st["form4_records_seen"] == 0
    assert st["source"]["ok"] is False and st["source"]["actual"] == "insider"
    assert "ingestion_ledger.db locked" in (st["source"]["error"] or "")
    # ledger untouched
    from talonx_v2.store import V2Store
    assert V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0).cash() == 300_000.0


def test_s2_raises_v2sourceerror_from_records_directly(tmp_path, monkeypatch):
    _patch_store(monkeypatch, _RaisingStore())
    svc = _svc(tmp_path)
    with pytest.raises(V2SourceError):
        svc._records(as_of=date(2026, 9, 9))


# --------------------------------------------------------------------------- S3
def test_s3_healthy_read_zero_filings_is_not_DATA_UNAVAILABLE(tmp_path, monkeypatch):
    _patch_store(monkeypatch, _EmptyStore())
    svc = _svc(tmp_path)
    st = svc.tick(as_of=date(2026, 9, 9))
    assert st["heartbeat_kind"] == "TICK"
    assert st["data_state"] == "CURRENT"
    assert st["source"]["ok"] is True and st["source"]["records"] == 0
    assert st["source"]["last_ok_utc"] is not None      # DB read succeeded


# --------------------------------------------------------------------------- S1
def test_s1_last_ok_utc_is_a_db_read_timestamp_only(tmp_path, monkeypatch):
    """`last_ok_utc` advances on every successful InsiderStore read even when
    the store returns nothing -- it certifies the READ, not upstream freshness."""
    _patch_store(monkeypatch, _EmptyStore())
    svc = _svc(tmp_path)
    st = svc.tick(as_of=date(2026, 9, 9))
    t1 = st["source"]["last_ok_utc"]
    import time as _t
    _t.sleep(0.01)
    st2 = svc.tick(as_of=date(2026, 9, 9))
    assert st2["source"]["last_ok_utc"] != t1           # bumped purely by a re-read
    assert st2["source"]["records"] == 0                # ...with no new filings


def test_s1_dashboard_splits_db_read_from_upstream_poll(tmp_path, monkeypatch):
    from talonx_ops.dashboard_read import DashboardReadModel
    # isolated status file: DB read OK 30 s ago, but no intel ledger -> poll UNKNOWN
    status = {
        "heartbeat_utc": datetime.now(timezone.utc).isoformat(), "heartbeat_ttl_s": 180,
        "strategy_version": "INSIDER_BUY_CLUSTER_V2@1", "form4_source": "insider",
        "form4_records_seen": 12, "tick": 4, "pricing_mode": "csv",
        "pricing_adapter": "csv:frozen_bar_dirs", "data_state": "CURRENT",
        "source": {"actual": "insider", "ok": True,
                   "last_ok_utc": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()},
    }
    (tmp_path / "s.json").write_text(json.dumps(status))
    (tmp_path / "v2_lane.db")  # absent -> ledger NO_ACTIVE_PRODUCER, fine
    monkeypatch.setenv("TALONX_V2_STATUS_PATH", str(tmp_path / "s.json"))
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(tmp_path / "v2_lane.db"))
    dr = DashboardReadModel(home=tmp_path, check_processes=False, intel_ledger=tmp_path / "nope.db")
    r = dr.v2_active_strategy()["readiness"]
    assert r["source_db_read_last_ok_utc"] == status["source"]["last_ok_utc"]
    assert r["source_db_read_age_s"] is not None and r["source_db_read_age_s"] < 120
    assert r["source_poll_last_ok_utc"] is None          # no intel ledger -> distinct, not conflated
    assert r["coverage"]["completeness"] == "INCOMPLETE"
    assert "UNKNOWN" in r["coverage"]["eligible_universe_denominator"]
    assert r["v2_fingerprint_frozen"] == "11107198c5b81237"


# --------------------------------------------------------------------------- S6
def test_s6_degraded_source_not_hidden_by_a_later_lightweight_heartbeat(tmp_path, monkeypatch):
    _patch_store(monkeypatch, _RaisingStore())
    svc = _svc(tmp_path)
    svc.tick(as_of=date(2026, 9, 9))                     # -> DEGRADED_SOURCE / DATA_UNAVAILABLE
    svc._write_heartbeat()                               # lightweight refresh
    s = json.loads((tmp_path / "s.json").read_text())
    assert s["heartbeat_kind"] == "LIGHTWEIGHT"
    assert s["data_state"] == "DATA_UNAVAILABLE"         # NOT reset to CURRENT
    assert s["source"]["ok"] is False


# --------------------------------------------------------------------------- S7
def test_s7_pricing_readiness_independent_of_event_source(tmp_path, monkeypatch):
    _patch_store(monkeypatch, _EmptyStore())
    svc = _svc(tmp_path)
    st = svc.tick(as_of=date(2026, 9, 9))
    assert st["pricing_mode"] == "csv"
    assert st["pricing_adapter"] == "csv:frozen_bar_dirs"
    assert "source" in st and "pricing_mode" in st       # distinct top-level fields
    assert st["source"].get("degraded") is None


def test_s7_open_position_does_not_mask_coverage_or_pricing_state(tmp_path, monkeypatch):
    """D2: an OPEN position sets activity=POSITION_OPEN, but coverage_state and
    pricing_state are still reported independently."""
    from talonx_ops.dashboard_read import DashboardReadModel
    import sqlite3
    db = tmp_path / "v2_lane.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE portfolio (id INTEGER PRIMARY KEY CHECK (id=1), cash REAL NOT NULL);
        INSERT INTO portfolio VALUES (1, 290000.0);
        CREATE TABLE positions (position_id INTEGER PRIMARY KEY, episode_id TEXT, symbol TEXT,
            status TEXT, entry_session TEXT, target_exit_session TEXT, entry_price REAL,
            shares REAL, position_cost REAL, opened_at TEXT, realized_pnl_usd REAL);
        INSERT INTO positions VALUES (1,'ep1','AAA','OPEN','2026-09-02','2026-09-16',
            10.0,1000.0,10000.0,'2026-09-02T14:00:00Z',NULL);
        CREATE TABLE trades (trade_id INTEGER PRIMARY KEY, action TEXT);
        INSERT INTO trades (action) VALUES ('BUY');
    """)
    con.commit()
    con.close()
    status = {
        "heartbeat_utc": datetime.now(timezone.utc).isoformat(), "heartbeat_ttl_s": 180,
        "strategy_version": "INSIDER_BUY_CLUSTER_V2@1", "form4_source": "insider",
        "form4_records_seen": 5, "tick": 9, "pricing_mode": "composite-yf",
        "pricing_adapter": "composite(csv+yfinance:1d)", "data_state": "CURRENT",
        "pricing_unavailable_recent": ["AAA:PROVISIONAL_ONLY"],
        "source": {"actual": "insider", "ok": True,
                   "last_ok_utc": datetime.now(timezone.utc).isoformat()},
    }
    (tmp_path / "s.json").write_text(json.dumps(status))
    monkeypatch.setenv("TALONX_V2_STATUS_PATH", str(tmp_path / "s.json"))
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(db))
    dr = DashboardReadModel(home=tmp_path, check_processes=False, intel_ledger=tmp_path / "nope.db")
    v = dr.v2_active_strategy()
    assert v["activity"] == "POSITION_OPEN"
    assert v["coverage_state"] in ("INCOMPLETE_COVERAGE", "DATA_STALE", "DATA_UNAVAILABLE")
    assert v["pricing_state"] == "DEGRADED"              # surfaced despite an open position
