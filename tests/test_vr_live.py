"""VR_PAPER_V1 live tracker: restart recovery, no duplicate ENTRY/EXIT, tags, capital, Signal independence, DTU state."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from talonx_paperperf import vr_live as L

UTC = timezone.utc
WID = "2026-09-28"
FLAT = (10, 10.02, 9.98, 10)


def _mk_live(d):
    d.mkdir()
    p = sqlite3.connect(d / "promotion.db")
    p.execute("CREATE TABLE promotions (promotion_id TEXT, candidate_id TEXT, symbol TEXT, direction TEXT, score REAL, "
              "data_as_of_utc TEXT, event_utc TEXT, decision_utc TEXT, reference_price REAL, signal_event_id TEXT, "
              "window_id TEXT, state TEXT)")
    p.execute("INSERT INTO promotions VALUES ('P1','C1','AAA','BULLISH',78.7,'2026-09-28T14:00:00+00:00',"
              "'2026-09-28T14:16:00+00:00','2026-09-28T14:16:05+00:00',10.0,'S1',?, 'PROMOTED_SIGNAL')", (WID,))
    p.commit()
    p.close()
    o = sqlite3.connect(d / "promotion_signal_notifications.db")
    o.execute("CREATE TABLE ops_notification_outbox (event_id TEXT, state TEXT, sent_at_utc TEXT)")
    o.execute("INSERT INTO ops_notification_outbox VALUES ('S1','SENT','2026-09-28T14:16:30+00:00')")
    o.commit()
    o.close()
    return d


def _bars(path):
    base = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
    out = []
    for i, (o, h, lo, c) in enumerate([FLAT] * 60 + list(path)):
        out.append({"t": (base + timedelta(minutes=i)).isoformat(), "o": o, "h": h, "l": lo, "c": c, "v": 1})
    return out


class Env:
    def __init__(self, tmp_path, path):
        from talonx_opportunity.phases import trading_window
        self.live = _mk_live(tmp_path / "live")
        self.root = tmp_path / "vr"
        self.bars = _bars(path)
        self.now = datetime(2026, 9, 28, 14, 20, tzinfo=UTC)
        self.w = trading_window(date(2026, 9, 28))
        self.pw = trading_window(self.w.reference_session)

    def tracker(self):
        return L.VRLive(self.root, live=self.live, bars_fn=lambda s, a, b: {x: self.bars for x in s},
                        spread_fn=lambda s, t: 10.0, now_fn=lambda: self.now, deliver=True,
                        drain_fn=self._drain, dtu_fn=lambda w, s: "ACTIVE_CORE")

    @staticmethod
    def _drain(store):
        for r in store.outbox_due(now_iso="9999", destination="RESEARCH"):
            store.update_outbox(r["event_id"], state="SENT")
        return {}

    def run(self, minutes):
        t = self.tracker()
        end = self.now + timedelta(minutes=minutes)
        while self.now < end:
            t.tick(WID, self.w, self.pw)
            self.now += timedelta(minutes=1)
        t.con.close()


def rows(env):
    c = sqlite3.connect(env.root / "vr_live.db")
    c.row_factory = sqlite3.Row
    return {r["paper_mode"] + ("" if r["promotion_id"] == "P1" else r["promotion_id"]): dict(r)
            for r in c.execute("SELECT * FROM trades")}


def outbox(env):
    c = sqlite3.connect(env.root / "vr_paper_notifications.db")
    return [(r[0], r[1]) for r in c.execute("SELECT event_id, payload_text FROM ops_notification_outbox "
                                            "ORDER BY created_at_utc")]


def test_vr_entry_then_target_exit_with_tagged_alerts(tmp_path):
    env = Env(tmp_path, [FLAT] * 20 + [(10, 12, 10, 11.9)])
    env.run(30)
    vr = rows(env)["VIRTUAL_REALTIME"]
    assert vr["state"] == "EXITED" and vr["exit_reason"] == "TARGET_HIT"
    assert vr["entry_market_time"] == "2026-09-28T14:00:00+00:00" and vr["entry_price"] == 10
    assert vr["dtu_state"] == "ACTIVE_CORE" and vr["cost"] == pytest.approx(0.002)
    ob = outbox(env)
    assert [e for e, _ in ob] == [f"VR_ENTRY:{vr['trade_id']}", f"VR_EXIT:{vr['trade_id']}"]   # ACTIONABLE: no alerts
    assert "#VR_PAPER #INTRADAY #ENTRY" in ob[0][1] and "SIMULATED · no broker order" in ob[0][1]
    assert "Virtual market time 14:00Z" in ob[0][1] and "Feed received ~14:16Z" in ob[0][1]
    assert "#VR_PAPER #INTRADAY #EXIT #TARGET" in ob[1][1]


def test_actionable_entry_after_send_uses_same_levels(tmp_path):
    env = Env(tmp_path, [FLAT] * 20 + [(10, 12, 10, 11.9)])
    env.run(30)
    r = rows(env)
    a, v = r["ACTIONABLE"], r["VIRTUAL_REALTIME"]
    assert a["entry_market_time"] == "2026-09-28T14:17:00+00:00"          # first bar >= ceil(14:16:30)
    assert (a["stop_price"], a["target_price"]) == (v["stop_price"], v["target_price"])


def test_stop_exit(tmp_path):
    env = Env(tmp_path, [FLAT] * 3 + [(10, 10, 5, 5.5)])
    env.run(15)
    vr = rows(env)["VIRTUAL_REALTIME"]
    assert vr["exit_reason"] == "STOP_HIT" and vr["exit_price"] == pytest.approx(vr["stop_price"])


def test_restart_recovers_open_position_without_duplicates(tmp_path):
    env = Env(tmp_path, [FLAT] * 25 + [(10, 12, 10, 11.9)])
    env.run(10)
    assert rows(env)["VIRTUAL_REALTIME"]["state"] == "OPEN"
    env.run(3)                                               # a fresh tracker object on the same durable state
    env.run(20)
    vr = rows(env)["VIRTUAL_REALTIME"]
    assert vr["state"] == "EXITED"
    ids = [e for e, _ in outbox(env)]
    assert len(ids) == len(set(ids)) == 2                    # exactly one ENTRY and one EXIT
    c = sqlite3.connect(env.root / "vr_live.db")
    assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 2
    assert c.execute("SELECT cash FROM capital WHERE paper_mode='VIRTUAL_REALTIME'").fetchone()[0] == \
        pytest.approx(100_000 + 10_000 * vr["net_return"])


def test_session_close_exit(tmp_path):
    env = Env(tmp_path, [FLAT] * 400)
    env.now = datetime(2026, 9, 28, 20, 10, tzinfo=UTC)      # virtual 19:54Z > 15:50 ET flatten
    env.run(1)
    vr = rows(env)["VIRTUAL_REALTIME"]
    assert vr["exit_reason"] == "SESSION_CLOSE" and vr["exit_market_time"] == "2026-09-28T19:50:00+00:00"


def test_capacity_is_enforced(tmp_path):
    env = Env(tmp_path, [FLAT] * 30)
    p = sqlite3.connect(env.live / "promotion.db")
    for i in range(2, 13):
        p.execute("INSERT INTO promotions VALUES (?,?,?,'BULLISH',70,'2026-09-28T14:00:00+00:00',"
                  "'2026-09-28T14:16:00+00:00',?,10.0,?,?, 'PROMOTED_SIGNAL')",
                  (f"P{i}", f"C{i}", f"S{i:02d}", f"2026-09-28T14:16:{i:02d}+00:00", f"S{i}", WID))
    p.commit()
    p.close()
    env.run(3)
    c = sqlite3.connect(env.root / "vr_live.db")
    st = dict(c.execute("SELECT state, COUNT(*) FROM trades WHERE paper_mode='VIRTUAL_REALTIME' GROUP BY state"))
    assert st["OPEN"] == 10 and st["SKIPPED"] == 2
    assert c.execute("SELECT cash FROM capital WHERE paper_mode='VIRTUAL_REALTIME'").fetchone()[0] == 0.0


def test_signal_stores_are_never_written(tmp_path):
    env = Env(tmp_path, [FLAT] * 20 + [(10, 12, 10, 11.9)])
    before = {p.name: p.read_bytes() for p in env.live.iterdir()}
    env.run(30)
    assert {p.name: p.read_bytes() for p in env.live.iterdir()} == before


def test_first_start_mid_session_skips_backlog_without_alerts(tmp_path):
    env = Env(tmp_path, [FLAT] * 20)
    t = L.VRLive(env.root, live=env.live, bars_fn=lambda s, a, b: {x: env.bars for x in s}, spread_fn=lambda s, x: 10.0,
                 now_fn=lambda: env.now, deliver=False, dtu_fn=lambda w, s: None, skip_backlog=True)
    t.tick(WID, env.w, env.pw)
    assert t.con.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
    assert t.con.execute("SELECT v FROM meta WHERE k=?", (f"backlog_skipped:{WID}",)).fetchone() is not None
