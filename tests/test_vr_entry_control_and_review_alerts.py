"""2026-10-07 owner direction: VR_PAPER_V1 entry interruption enforced in code (both arms, restart-safe, fail-safe),
SENT_AFTER_FLATTEN, and future-only restoration of Opportunity promotions as UNVALIDATED research-review alerts.
No network, no Telegram."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_opportunity import promotion as P
from talonx_ops import opportunity_read as R
from talonx_paperperf import vr_live as L
from talonx_paperperf import vr_paper as V
from tests.test_opportunity_promotion import Clock, T, _NoData, rows, seed
from tests.test_promotion_signal_pause import PAUSE, Drains, outbox, pause, signal_promoter
from tests.test_vr_live import FLAT, WID, Env, rows as vr_rows

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]


def control(env, body):
    (env.root).mkdir(parents=True, exist_ok=True)
    (env.root / L.ENTRY_CONTROL).write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")


def add_promotion(env, pid, sym, decision, sid=None, sent=None):
    p = sqlite3.connect(env.live / "promotion.db")
    p.execute("INSERT INTO promotions VALUES (?,?,?,'BULLISH',80,?,?,?,10.0,?,?,'PROMOTED_SIGNAL')",
              (pid, "C" + pid, sym, (datetime.fromisoformat(decision) - timedelta(minutes=16)).isoformat(),
               decision, decision, sid, WID))
    p.commit()
    p.close()
    if sid and sent:
        o = sqlite3.connect(env.live / "promotion_signal_notifications.db")
        o.execute("INSERT INTO ops_notification_outbox VALUES (?, 'SENT', ?)", (sid, sent))
        o.commit()
        o.close()


def heartbeat(env):
    c = sqlite3.connect(env.root / "vr_live.db")
    return json.loads(c.execute("SELECT detail_json FROM heartbeat").fetchone()[0])


# ------------------------------------------------------------------------------------------------ VR entry control
def test_both_arms_refuse_signals_at_or_after_the_boundary_including_after_restart(tmp_path):
    env = Env(tmp_path, [FLAT] * 60)
    control(env, {"entries_blocked": True, "boundary_utc": "2026-09-28T14:16:05+00:00"})   # == P1's decision
    env.run(5)
    assert vr_rows(env) == {}
    assert heartbeat(env)["entry_control"] == "BLOCKED"
    env.run(5)                                                         # a fresh tracker object = restart
    assert vr_rows(env) == {}
    c = sqlite3.connect(env.root / "vr_live.db")
    assert json.loads(c.execute("SELECT v FROM meta WHERE k=?", (f"entry_control_blocked:{WID}",)).fetchone()[0])[
        "signals"] == 1                                                # recorded once; the cursor moved past it
    (env.root / L.ENTRY_CONTROL).unlink()                              # even a rollback of the control ...
    env.run(3)
    assert vr_rows(env) == {}                                          # ... cannot replay the blocked Signal


def test_signals_before_the_boundary_and_open_positions_are_still_managed(tmp_path):
    env = Env(tmp_path, [FLAT] * 25 + [(10, 12, 10, 11.9)])
    env.run(10)
    assert vr_rows(env)["VIRTUAL_REALTIME"]["state"] == "OPEN"
    control(env, {"entries_blocked": True, "boundary_utc": env.now.isoformat()})
    add_promotion(env, "P2", "BBB", (env.now + timedelta(minutes=1)).isoformat(), "S2",
                  (env.now + timedelta(minutes=1, seconds=2)).isoformat())
    env.run(20)
    r = vr_rows(env)
    assert r["VIRTUAL_REALTIME"]["state"] == "EXITED" and r["VIRTUAL_REALTIME"]["exit_reason"] == "TARGET_HIT"
    assert not any(k.endswith("P2") for k in r)


def test_pending_row_after_boundary_never_opens(tmp_path):
    env = Env(tmp_path, [FLAT] * 60)
    env.now = datetime(2026, 9, 28, 14, 16, 30, tzinfo=UTC)          # virtual 14:00:30: entry bar not closed yet
    env.run(1)                                                         # P1 ingested as PAPER_ENTRY_PENDING (both arms)
    assert {r["state"] for r in vr_rows(env).values()} == {"PAPER_ENTRY_PENDING"}
    control(env, {"entries_blocked": True, "boundary_utc": "2026-09-28T14:00:00+00:00"})
    env.run(30)
    assert {r["state"] for r in vr_rows(env).values()} == {"PAPER_ENTRY_PENDING"}


def test_malformed_control_blocks_new_entries_reports_it_and_still_manages_exits(tmp_path):
    env = Env(tmp_path, [FLAT] * 25 + [(10, 12, 10, 11.9)])
    env.run(10)
    assert vr_rows(env)["VIRTUAL_REALTIME"]["state"] == "OPEN"
    control(env, "{not json")
    add_promotion(env, "P2", "BBB", (env.now + timedelta(minutes=1)).isoformat(), "S2",
                  (env.now + timedelta(minutes=1, seconds=2)).isoformat())
    env.run(20)
    r = vr_rows(env)
    assert r["VIRTUAL_REALTIME"]["state"] == "EXITED" and not any(k.endswith("P2") for k in r)
    hb = heartbeat(env)
    assert hb["entry_control"] == "MALFORMED_BLOCKING" and "JSONDecodeError" in hb["entry_control_detail"]


@pytest.mark.parametrize("body", [{"entries_blocked": "yes"}, {"entries_blocked": True},
                                  {"entries_blocked": True, "boundary_utc": "2026-10-07T11:25:41"}, []])
def test_invalid_control_shapes_fail_safe(tmp_path, body):
    (tmp_path / L.ENTRY_CONTROL).write_text(json.dumps(body), encoding="utf-8")
    ctl = L.entry_control(tmp_path)
    assert ctl["state"] == "MALFORMED_BLOCKING" and L.entry_blocked(ctl, "2000-01-01T00:00:00+00:00")


def test_no_control_keeps_original_behaviour():
    ctl = L.entry_control(Path("/nonexistent-dir-for-test"))
    assert ctl["state"] == "OPEN" and not L.entry_blocked(ctl, "2026-10-08T14:00:00+00:00")


# ------------------------------------------------------------------------------------------- SENT_AFTER_FLATTEN
@pytest.mark.parametrize("sent,expect_after_flatten", [
    ("2026-09-28T19:49:59+00:00", False), ("2026-09-28T19:50:00+00:00", True), ("2026-09-28T19:55:00+00:00", True)])
def test_actionable_send_at_or_after_flatten_is_ineligible(tmp_path, sent, expect_after_flatten):
    env = Env(tmp_path, [FLAT] * 420)
    o = sqlite3.connect(env.live / "promotion_signal_notifications.db")
    o.execute("UPDATE ops_notification_outbox SET sent_at_utc=? WHERE event_id='S1'", (sent,))
    o.commit()
    o.close()
    env.now = datetime(2026, 9, 28, 20, 12, tzinfo=UTC)                 # virtual 19:56Z: past the 19:50Z flatten
    env.run(1)
    a = vr_rows(env)["ACTIONABLE"]
    assert (a["skip_reason"] == "SENT_AFTER_FLATTEN") is expect_after_flatten
    assert a["entry_market_time"] is None and a["state"] in ("SKIPPED", "PAPER_ENTRY_PENDING")


def test_flatten_boundary_follows_the_session_and_timezone():
    from talonx_opportunity.phases import trading_window
    assert V.flatten_utc(trading_window(date(2026, 9, 28)).close_utc) == datetime(2026, 9, 28, 19, 50, tzinfo=UTC)
    assert V.flatten_utc(trading_window(date(2026, 11, 2)).close_utc) == datetime(2026, 11, 2, 20, 50, tzinfo=UTC)
    half = trading_window(date(2026, 11, 27)).close_utc                 # day after Thanksgiving: 13:00 ET close
    assert V.flatten_utc(half) == half == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)


# ------------------------------------------------------------------------------------ review-alert restoration
def restore(root, boundary):
    pause(root, {**PAUSE, "paused": False, "delivery_mode": "RESEARCH_REVIEW",
                 "delivery_boundary_utc": boundary.isoformat()})


def test_restoration_is_future_only_no_paused_period_or_old_outbox_replay(tmp_path):
    from tests.test_promotion_signal_pause import _make_outbox_rows
    _make_outbox_rows(tmp_path)                                         # SENT + AMBIGUOUS + PENDING history
    pr = signal_promoter(tmp_path, T(15, 6), Drains(), paused=True)     # pause: PENDING suppressed
    seed(tmp_path, [dict(sym=f"Q{i}", at=T(15, 6), asof=T(14, 50), score=60 + i) for i in range(5)])
    pr.tick()                                                           # 3 record-only + 2 queued while paused
    before = outbox(tmp_path)
    restore(tmp_path, T(15, 12))
    pr2 = P.Promoter(root=tmp_path, clock=Clock(T(15, 12)), data=_NoData(), mode=P.PAPER_SIGNAL, drain=Drains())
    pr2.tick()
    assert outbox(tmp_path) == before                                   # nothing replayed, nothing re-sent
    assert rows(pr2, "SELECT COUNT(*) FROM promotions WHERE reason_code='SIGNAL_DELIVERY_PAUSED'") == [(3,)]
    seed(tmp_path, [dict(sym="NEW1", at=T(15, 13), asof=T(14, 57))])
    pr2.clock.t = T(15, 13)
    pr2.tick()
    new = {k: v for k, v in outbox(tmp_path).items() if k not in before}
    assert list(new) == ["OPPORTUNITY_ENGINE:2026-09-24:NEW1:GAP_UP"] and new[list(new)[0]][0] == "PENDING"
    c = sqlite3.connect(P.signal_outbox_path(tmp_path))
    assert c.execute("SELECT event_type FROM ops_notification_outbox WHERE dedup_key LIKE '%NEW1%'").fetchone() == \
        ("RESEARCH_OPPORTUNITY",)
    assert rows(pr2, "SELECT state, reason_code FROM promotions WHERE symbol='NEW1'") == \
        [("PROMOTED_SIGNAL", "RESEARCH_REVIEW_ALERT")]


def test_queue_rows_from_before_the_boundary_are_record_only_even_in_signal_mode(tmp_path):
    pr = signal_promoter(tmp_path, T(15), Drains())                     # legacy PAPER_SIGNAL, no control file
    seed(tmp_path, [dict(sym=f"S{i}", at=T(15), score=60 + i) for i in range(4)])
    pr.tick()                                                           # 3 sent-mode + 1 QUEUED (PAPER_SIGNAL mode)
    n_before = len(outbox(tmp_path))
    restore(tmp_path, T(15, 6))
    pr2 = P.Promoter(root=tmp_path, clock=Clock(T(15, 6)), data=_NoData(), mode=P.PAPER_SIGNAL, drain=Drains())
    pr2.tick()
    assert len(outbox(tmp_path)) == n_before
    assert rows(pr2, "SELECT state, reason_code FROM promotions WHERE symbol='S0'") == \
        [("PROMOTED_SHADOW", "PRE_RESTORATION_RECORD_ONLY")]


@pytest.mark.parametrize("boundary", ["", "2026-10-07T12:00:00", "not-a-date"])
def test_resumption_without_a_valid_aware_boundary_stays_paused(tmp_path, boundary):
    pause(tmp_path, {**PAUSE, "paused": False, "delivery_mode": "RESEARCH_REVIEW", "delivery_boundary_utc": boundary})
    d = Drains()
    pr = signal_promoter(tmp_path, T(15), d)
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    assert pr.mode == P.SHADOW and d.calls == 0 and not P.signal_outbox_path(tmp_path).exists()


def test_review_message_labels_times_and_verdict():
    q = {"symbol": "ABC", "score": 72.34, "reference_price": 12.5, "processing_phase": "REGULAR",
         "data_as_of_utc": "2026-10-08T13:49:00+00:00", "horizons_json": '["INTRADAY", "SAME_DAY"]'}
    txt = P.render_review(q, datetime(2026, 10, 8, 14, 5, 30, tzinfo=UTC), "OPPORTUNITY_PROMOTION_V1")
    lines = txt.splitlines()
    assert lines[0] == "🔎 TALONX — RESEARCH OPPORTUNITY" and lines[1] == "⚠️ UNVALIDATED — not a buy instruction"
    assert "Signal 14:05Z · REGULAR · data 13:49Z (age 16m)" in txt
    assert "Horizon INTRADAY / SAME_DAY" in txt and "Policy OPPORTUNITY_PROMOTION_V1" in txt
    assert "Research verdict: NEGATIVE" in txt and "negative after costs" in txt
    assert "not a trade event" in txt and "no order placed" in txt
    rest = txt.upper().replace("NOT A BUY INSTRUCTION", "")
    assert "BUY" not in rest and "SELL" not in rest and "PROFIT" not in rest


def test_review_message_unknown_data_is_unknown_not_invented():
    q = {"symbol": "ABC", "score": None, "reference_price": None, "processing_phase": None, "data_as_of_utc": None,
         "horizons_json": None}
    txt = P.render_review(q, datetime(2026, 10, 8, 14, 5, tzinfo=UTC), "OPPORTUNITY_PROMOTION_V1")
    assert "data UNKNOWN (age UNKNOWN)" in txt and "Horizon UNKNOWN" in txt and "· UNKNOWN ·" in txt


def test_review_delivery_is_independent_of_paper_admission(tmp_path):
    vr = tmp_path / "vr_paper"
    vr.mkdir()
    (vr / L.ENTRY_CONTROL).write_text(json.dumps({"entries_blocked": True, "boundary_utc": "2026-01-01T00:00:00Z"}))
    restore(tmp_path, T(14))
    pr = signal_promoter(tmp_path, T(15), Drains())
    seed(tmp_path, [dict(sym="AAA", at=T(15))])
    pr.tick()
    assert [v[0] for v in outbox(tmp_path).values()] == ["PENDING"]     # enqueued although VR entries are blocked
    src = (REPO / "talonx_opportunity" / "promotion.py").read_text(encoding="utf-8")
    for banned in ("talonx_paperperf", "talonx_v2", "paper_trading", "vr_live"):
        assert banned not in src, banned


# ------------------------------------------------------------------------------------------------------ dashboard
def _runtime_row(root, fps, det):
    from talonx_opportunity.runtime import RuntimeStore
    rs = RuntimeStore(root)
    rs.con.execute("INSERT OR REPLACE INTO components (name, pid, state, heartbeat_utc, version, config_fps_json, "
                   "commit_sha, detail_json) VALUES ('promotion', 1, 'RUNNING', ?, 'v', ?, 'x', ?)",
                   (datetime.now(UTC).isoformat(), json.dumps(fps), json.dumps(det)))
    rs.con.commit()
    rs.con.close()


def test_dashboard_shows_review_delivery_counts_by_type_and_vr_interrupted(tmp_path):
    root = tmp_path / "opp"
    root.mkdir()
    restore(root, T(14))
    pr = signal_promoter(root, T(15), Drains())
    seed(root, [dict(sym="AAA", at=T(15))])
    pr.tick()
    pr.con.close()
    _runtime_row(root, {"mode": "PAPER_SIGNAL", "signal_delivery": "RESEARCH_REVIEW@" + T(14).isoformat()},
                 {"signal_delivery": "RESEARCH_REVIEW", "delivery_boundary_utc": T(14).isoformat()})
    vr = tmp_path / "results" / "vr_paper"
    vr.mkdir(parents=True)
    (vr / L.ENTRY_CONTROL).write_text(json.dumps({"entries_blocked": True, "boundary_utc": "2026-10-07T11:25:41Z"}))
    c = sqlite3.connect(vr / "vr_live.db")
    c.executescript(L.SCHEMA)
    c.execute("INSERT INTO heartbeat VALUES ('vr_paper', 'x', 'x', ?)", (json.dumps({"entry_control": "BLOCKED"}),))
    c.commit()
    c.close()
    lanes = R.notification_lanes(root, now=T(15, 30), repo=tmp_path, home=tmp_path)["lanes"]
    p = lanes[0]
    assert p["mode"].startswith("RESEARCH_REVIEW_DELIVERY_ENABLED") and p["alert_class"].startswith("RESEARCH_REVIEW")
    assert p["notifications"]["by_event_type"]["RESEARCH_OPPORTUNITY"]["PENDING"] == 1
    assert p["notifications"]["by_event_type"]["PAPER_OPPORTUNITY"]["SENT"] == 0
    assert p["promotions"]["review_alerts_promoted"] == 1
    assert "UNVALIDATED" in p["research_status"]["statement"] and p["research_status"]["status"] == "NEGATIVE"
    vrl = next(x for x in lanes if x["lane"] == "VR_PAPER")
    assert vrl["mode"].startswith("ENTRY COLLECTION INTERRUPTED") and vrl["entry_control_configured"].startswith(
        "ENTRIES_BLOCKED")


def test_dashboard_reports_review_configured_but_not_loaded(tmp_path):
    root = tmp_path / "opp"
    root.mkdir()
    _runtime_row(root, {"mode": "PAPER_SIGNAL", "signal_delivery": "PAUSED"}, {"signal_delivery": "PAUSED"})
    restore(root, T(14))
    p = R.notification_lanes(root, now=T(15), repo=tmp_path, home=tmp_path)["lanes"][0]
    assert p["mode"].startswith("REVIEW_DELIVERY_CONFIGURED_NOT_YET_LOADED")
