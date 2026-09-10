"""
Task 117 D6 -- lane-scoped candidate/evaluation accounting snapshot.

Original / Experimental / V2 kept separate; the off-counter THROTTLE/COOLDOWN/
revalidation class is recorded; in-flight work is listed; the funnel closes from
the comingled counter when a metrics snapshot is present, and is marked
UNRESOLVED (never "resolved") when it is not.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

import talonx_ops.prospective.lane_accounting as la

NOW = datetime(2026, 9, 10, 22, 0, 0, tzinfo=timezone.utc)


def _mk_v2(tmp_path) -> Path:
    p = tmp_path / "v2_lane.db"
    c = sqlite3.connect(p)
    c.executescript("""
        CREATE TABLE processed_episodes (episode_id TEXT, disposition TEXT);
        INSERT INTO processed_episodes VALUES ('e1','SKIPPED_ENTRY_STALE');
        CREATE TABLE trades (action TEXT);
        CREATE TABLE positions (status TEXT);
        CREATE TABLE pending_entry_intents (id INTEGER);
        CREATE TABLE v2_alert_outbox (state TEXT);
    """)
    c.commit(); c.close()
    return p


def test_lanes_are_separate_and_v2_read(tmp_path, monkeypatch):
    monkeypatch.setattr(la, "_HOME", tmp_path / "nohome")     # dispatch/exp absent -> zeros
    monkeypatch.setattr(la, "_redis_quant_metrics", lambda day: {"present": False})
    out = la.build_lane_accounting(now=NOW, v2_db=_mk_v2(tmp_path))
    lanes = out["lanes"]
    assert set(lanes) == {"original_intraday", "experimental", "v2_trading"}
    assert lanes["v2_trading"]["dispositions"] == {"SKIPPED_ENTRY_STALE": 1}
    assert lanes["v2_trading"]["buys"] == 0 and lanes["v2_trading"]["open_positions"] == 0
    assert lanes["original_intraday"]["off_counter_disposition_class"]["in_metrics_quant_counter"] is False


def test_gap_is_unresolved_without_a_metrics_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(la, "_HOME", tmp_path / "nohome")
    monkeypatch.setattr(la, "_redis_quant_metrics", lambda day: {"present": False})
    out = la.build_lane_accounting(now=NOW, v2_db=_mk_v2(tmp_path))
    assert out["funnel_closure"]["status"] == "NO_METRICS_SNAPSHOT"
    assert out["historical_94_candidate_gap"]["status"] == "UNRESOLVED"


def test_funnel_closes_from_the_comingled_counter_when_present(tmp_path, monkeypatch):
    day = "2026-09-10"
    fake = {
        "present": True, "lane_attributable": False,
        "keys": {
            f"metrics:{day}:quant:evaluated": 158,
            f"metrics:{day}:quant:published": 8,
            f"metrics:{day}:quant:failed_confluence": 104,
            f"metrics:{day}:quant:failed_trend_gate": 4,
            f"metrics:{day}:quant:failed_rr_gate": 2,
            f"metrics:{day}:quant:dropped_opening_blackout": 30,
            f"metrics:{day}:quant:dropped_us_session_closed": 2,
            f"metrics:{day}:quant:dropped_closing_blackout": 4,
            f"metrics:{day}:quant:dropped_duplicate_bars": 45318,   # pre-eval, excluded
            f"metrics:{day}:quant:failed_min_volatility": 22634,    # pre-eval, excluded
            f"metrics:{day}:quant:regime_shadow_BOTH_PASS": 3460,   # not a disposition
        },
    }
    monkeypatch.setattr(la, "_HOME", tmp_path / "nohome")
    monkeypatch.setattr(la, "_redis_quant_metrics", lambda d: fake)
    # experimental WOULD_PASS = 8 to match published
    exp_dir = tmp_path / "nohome" / "experimental"
    exp_dir.mkdir(parents=True)
    c = sqlite3.connect(exp_dir / "exp_alerts.db")
    c.executescript(
        "CREATE TABLE directional_alerts (generated_at TEXT, trade_gate_status TEXT, sent INT);"
        "CREATE TABLE experimental_trades (opened_at TEXT);")
    for _ in range(8):
        c.execute("INSERT INTO directional_alerts VALUES (?,?,0)", (f"{day}T14:00:00Z", "WOULD_PASS"))
    c.commit(); c.close()

    out = la.build_lane_accounting(now=NOW, v2_db=_mk_v2(tmp_path))
    fc = out["funnel_closure"]
    assert fc["status"] == "CLOSED"
    assert fc["evaluated"] == 158 and fc["terminal_with_counter_sum"] == 154
    assert fc["residual"] == 4                                # THROTTLE/COOLDOWN/reval
    assert fc["published_all_experimental"] is True
    assert out["historical_94_candidate_gap"]["status"] == "RESOLVED_WITH_EVIDENCE"


def test_in_flight_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(la, "_HOME", tmp_path / "nohome")
    monkeypatch.setattr(la, "_redis_quant_metrics", lambda day: {"present": False})
    v2 = _mk_v2(tmp_path)
    c = sqlite3.connect(v2)
    c.execute("INSERT INTO pending_entry_intents VALUES (1)")
    c.execute("INSERT INTO v2_alert_outbox VALUES ('PENDING')")
    c.commit(); c.close()
    out = la.build_lane_accounting(now=NOW, v2_db=v2)
    assert out["in_flight"]["v2_pending_entry_intents"] == 1
    assert out["in_flight"]["v2_alert_outbox_pending"] == 1
