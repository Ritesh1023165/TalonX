"""VR_PAPER_V1 endpoint (2026-10-16) stop semantics -- synthetic clocks, fixture stores and a fake tracker only.
The live tracker is never run; no market data, no outcomes."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from talonx_paperperf import vr_live as L
from tests.test_vr_live import WID, Env, rows

UTC = timezone.utc


class Clock:
    def __init__(self, t):
        self.t = t


def run_main(monkeypatch, start: datetime, argv, tick_cost=timedelta(0)):
    """Drive the REAL vr_live.main loop on a synthetic clock with a fake VRLive; returns the recorded ticks."""
    clock, ticks = Clock(start), []

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.t if tz else clock.t.replace(tzinfo=None)

    class FakeVR:
        def __init__(self, **kw):
            pass

        def tick(self, wid, window, prev_window):
            ticks.append((wid, clock.t))
            clock.t += tick_cost
            return {}

    def fake_sleep(s):
        clock.t += timedelta(seconds=s)

    import talonx_premarket.__main__ as M
    monkeypatch.setattr(M, "_env", lambda: None)
    monkeypatch.setattr(L, "datetime", FakeDT)
    monkeypatch.setattr(L.time, "sleep", fake_sleep)
    monkeypatch.setattr(L, "VRLive", FakeVR)
    L.main(argv)
    return ticks, clock.t


ARGV = ["run", "--until", "2026-10-16"]                      # the registered wrapper command


def test_endpoint_day_is_collected_through_close_plus_21_min_then_the_child_exits_at_utc_midnight(monkeypatch):
    ticks, end = run_main(monkeypatch, datetime(2026, 10, 16, 3, 0, tzinfo=UTC), ARGV)
    assert ticks and {w for w, _ in ticks} == {"2026-10-16"}
    assert min(t for _, t in ticks) >= datetime(2026, 10, 16, 8, 0, tzinfo=UTC)          # premarket 04:00 ET
    assert max(t for _, t in ticks) <= datetime(2026, 10, 16, 20, 21, tzinfo=UTC)        # close 20:00Z + 16 + 5 min
    assert datetime(2026, 10, 17, 0, 0, tzinfo=UTC) <= end <= datetime(2026, 10, 17, 0, 1, tzinfo=UTC)


@pytest.mark.parametrize("start", [datetime(2026, 10, 17, 0, 0, 30, tzinfo=UTC),      # just after the endpoint
                                   datetime(2026, 10, 19, 13, 0, tzinfo=UTC)])        # Monday session, relaunched
def test_relaunch_after_expiry_collects_nothing_and_exits_at_once(monkeypatch, start):
    ticks, end = run_main(monkeypatch, start, ARGV)
    assert ticks == [] and end == start                       # no tick, not even one sleep


def test_default_end_date_is_the_registered_2026_10_16(monkeypatch):
    ticks, _ = run_main(monkeypatch, datetime(2026, 10, 19, 13, 0, tzinfo=UTC), ["run"])
    assert ticks == []
    ticks, _ = run_main(monkeypatch, datetime(2026, 10, 16, 19, 0, tzinfo=UTC), ["run"])
    assert ticks and all(w == "2026-10-16" for w, _ in ticks)


def test_a_slow_tick_crossing_midnight_cannot_extend_collection(monkeypatch):
    ticks, end = run_main(monkeypatch, datetime(2026, 10, 16, 20, 15, tzinfo=UTC), ARGV,
                          tick_cost=timedelta(hours=4))       # one pathological tick lasting into 2026-10-17
    assert len(ticks) == 1 and end <= datetime(2026, 10, 17, 0, 16, tzinfo=UTC)


def test_session_bounds_come_from_the_exchange_calendar_half_day(monkeypatch):
    """Not the registered endpoint (a normal Friday); proves the per-day bound is calendar-derived."""
    ticks, _ = run_main(monkeypatch, datetime(2026, 11, 27, 3, 0, tzinfo=UTC), ["run", "--until", "2026-11-27"])
    assert max(t for _, t in ticks) <= datetime(2026, 11, 27, 18, 21, tzinfo=UTC)        # 13:00 ET close (EST)


def test_registered_wrapper_runs_once_with_the_fixed_end_date():
    from pathlib import Path
    sh = (Path(L.REPO) / "results/ops_restore_20261004/tracker_vr.sh")
    if not sh.exists():
        pytest.skip("machine-local wrapper not present in this checkout")
    text = sh.read_text(encoding="utf-8")
    cmd = [x for x in text.splitlines() if "vr_live run" in x]
    assert len(cmd) == 1 and "--until 2026-10-16" in cmd[0]
    assert "while" not in text and "until " not in text.replace("--until", "")         # no relaunch loop


# ============================================================================================ entry control / pending
def control(env, boundary: datetime):
    env.root.mkdir(parents=True, exist_ok=True)
    (env.root / "entry_control.json").write_text(json.dumps({"entries_blocked": True,
                                                             "boundary_utc": boundary.isoformat()}), encoding="utf-8")


def test_entries_after_the_boundary_never_open_and_an_existing_position_is_still_managed_to_exit(tmp_path):
    env = Env(tmp_path, [(10, 10.02, 9.98, 10)] * 500)        # flat: no stop/target -> session-close flatten
    control(env, datetime(2026, 9, 28, 14, 30, tzinfo=UTC))   # P1 decided 14:16:05 (before) -> may open
    p = sqlite3.connect(env.live / "promotion.db")            # P2 decided after the boundary -> must never open
    p.execute("INSERT INTO promotions VALUES ('P2','C2','BBB','BULLISH',80,'2026-09-28T14:40:00+00:00',"
              "'2026-09-28T14:56:00+00:00','2026-09-28T14:56:05+00:00',10.0,'S2',?, 'PROMOTED_SIGNAL')", (WID,))
    p.commit()
    p.close()
    env.run(30)                                               # 14:20 .. 14:50: P1 enters
    env.now = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
    env.run(360)                                              # through the 15:50 ET flatten
    r = rows(env)
    assert r["VIRTUAL_REALTIME"]["state"] == "EXITED" and r["VIRTUAL_REALTIME"]["exit_reason"] == "SESSION_CLOSE"
    assert not any(k.endswith("P2") for k in r)               # post-boundary Signal: no trade row at all


def test_legacy_pending_row_of_a_past_window_is_never_touched_by_current_ticks(tmp_path):
    env = Env(tmp_path, [(10, 10.02, 9.98, 10)] * 120)
    control(env, datetime(2026, 9, 28, 14, 30, tzinfo=UTC))
    env.run(1)                                                # creates the store
    c = sqlite3.connect(env.root / "vr_live.db")
    c.execute("INSERT INTO trades (trade_id, promotion_id, window_id, symbol, paper_mode, state, signal_market_time, "
              "created_utc, updated_utc) VALUES ('legacy','OPPORTUNITY_ENGINE:2026-09-25:NVCT:GAP_UP','2026-09-25',"
              "'NVCT','ACTIONABLE','PAPER_ENTRY_PENDING','2026-09-25T19:38:00+00:00','2026-09-25T20:03:48+00:00',"
              "'2026-09-25T20:03:48+00:00')")
    c.commit()
    before = c.execute("SELECT * FROM trades WHERE trade_id='legacy'").fetchone()
    c.close()
    env.run(60)
    c = sqlite3.connect(env.root / "vr_live.db")
    assert c.execute("SELECT * FROM trades WHERE trade_id='legacy'").fetchone() == before   # byte-for-byte unchanged


def test_restart_does_not_extend_dates_or_reset_the_block(tmp_path):
    env = Env(tmp_path, [(10, 10.02, 9.98, 10)] * 120)
    control(env, datetime(2026, 9, 28, 14, 0, tzinfo=UTC))    # P1 (14:16:05) after the boundary -> blocked
    env.run(10)
    env.run(10)                                               # a "restart": fresh VRLive on the same stores
    assert rows(env) == {}
    assert L.entry_control(env.root)["state"] == "BLOCKED"
