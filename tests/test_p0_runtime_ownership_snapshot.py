"""P0 runtime hardening -- reproductions (written FIRST, against the unfixed code) and acceptance tests.

Defect 1, atomic ownership / restart (talonx_opportunity/runtime.py, supervise.py):
  * the PID lock was check-then-write: two processes could both pass the check and both "own" a component;
  * a stale PID file naming a LIVE unrelated process (PID reuse after a reboot) blocked a legitimate start;
  * restart() spawned even when stop() had not confirmed the old process was gone;
  * a CLI restart and the supervisor loop could both spawn the same component;
  * a heartbeat write that raised (e.g. OperationalError: database is locked) killed the component.
Defect 2, mixed-generation snapshots (market.db):
  * read_state() issued separate SELECTs outside one read transaction: a writer commit between them yields as_of
    from one ingestion cycle and aggregates from the next;
  * the DTU active set was committed in its own transaction BEFORE the cycle's aggregates/as_of, so even a reader
    in one transaction could see cycle N+1's universe with cycle N's as_of.
All offline: fake data, temp roots, local processes only.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_opportunity import runtime as RT
from talonx_opportunity import supervise as SV

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]


# ================================================================================================ defect 1: ownership
def _race_child(root: str, name: str, start_at: float, hold_s: float, q) -> None:
    sys.path.insert(0, str(REPO))
    from talonx_opportunity import runtime as R
    while time.time() < start_at:                     # synchronised start: maximise overlap of the acquire path
        pass
    try:
        lk = R.acquire_lock(root, name)
        q.put(("WON", os.getpid()))
        time.sleep(hold_s)                            # hold ownership while the others try
        if hasattr(lk, "release"):
            lk.release()
    except R.AlreadyRunning:
        q.put(("LOST", os.getpid()))


@pytest.mark.parametrize("round_", range(3))
def test_two_processes_racing_for_one_lock_exactly_one_wins(tmp_path, round_):
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    n = 6
    start_at = time.time() + 4.0                      # all children import first, then hit the lock together
    ps = [ctx.Process(target=_race_child, args=(str(tmp_path), "evaluator:INTRADAY", start_at, 3.0, q))
          for _ in range(n)]
    for p in ps:
        p.start()
    res = [q.get(timeout=60) for _ in range(n)]
    for p in ps:
        p.join(30)
    winners = [pid for r, pid in res if r == "WON"]
    assert len(winners) == 1, f"{len(winners)} processes own one component: {res}"


def test_stale_pid_file_of_a_live_unrelated_process_does_not_block_a_start(tmp_path):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])   # a live, unrelated process
    try:
        RT.lock_path(tmp_path, "discovery").write_text(str(other.pid))   # what a reboot + PID reuse leaves behind
        pidf = RT.lock_path(tmp_path, "discovery").with_suffix(".pid")
        pidf.write_text(str(other.pid))
        lk = RT.acquire_lock(tmp_path, "discovery")                       # must succeed: nobody holds the OS lock
        if hasattr(lk, "release"):
            lk.release()
    finally:
        other.kill()


def test_restart_with_a_failed_stop_never_spawns(tmp_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(SV, "stop", lambda root, name, *a, **k: False)
    monkeypatch.setattr(SV, "spawn", lambda root, name, env=None: spawned.append(name) or 4242)
    out = SV.restart(tmp_path, "notifier")
    assert spawned == [], "a component was spawned although the old one was not confirmed gone"
    assert out is None or (isinstance(out, dict) and not out.get("ok"))
    ev = [r["event"] for r in RT.RuntimeStore(tmp_path).con.execute(
        "SELECT event FROM component_events WHERE component='notifier'")]
    assert "RESTART_ABORTED_STOP_FAILED" in ev


def test_cli_restart_while_supervised_never_yields_two_instances(tmp_path, monkeypatch):
    """The CLI and the supervisor are separate processes: the supervisor cannot see the CLI's in-memory spawn
    grace. Model: the component is mid-startup (not yet holding its lock) right after a CLI-driven spawn."""
    spawns = []
    monkeypatch.setattr(SV, "spawn", lambda root, name, env=None: spawns.append(name) or (9000 + len(spawns)))
    monkeypatch.setattr(SV, "stop", lambda root, name, *a, **k: True)
    monkeypatch.setattr(SV, "is_running", lambda root, name: False)          # still starting (no lock yet)
    rt = RT.RuntimeStore(tmp_path)
    rt.set_component("supervisor", pid=os.getpid(), state="RUNNING", heartbeat_utc=RT.iso())   # a live supervisor
    from talonx_opportunity import __main__ as CLI
    monkeypatch.setenv("TALONX_OPP_ROOT", str(tmp_path))
    CLI.main(["restart", "notifier"])                                        # operator CLI (its own process)
    SV._SPAWNED_AT.clear()                                                   # the supervisor process never saw it
    loops = iter([False, True])
    monkeypatch.setattr(SV.time, "sleep", lambda s: None)
    SV.supervise(tmp_path, ("notifier",), env={}, poll_s=0, should_stop=lambda: next(loops))
    assert spawns.count("notifier") == 1, f"notifier spawned {spawns.count('notifier')} times"


def test_heartbeat_write_operational_error_does_not_kill_the_component(tmp_path, monkeypatch):
    real = RT.RuntimeStore.set_component
    calls = {"n": 0}

    def flaky(self, name, **kw):
        if set(kw) == {"heartbeat_utc"}:                 # the sleep-loop heartbeat write
            calls["n"] += 1
            raise sqlite3.OperationalError("database is locked")
        return real(self, name, **kw)
    monkeypatch.setattr(RT.RuntimeStore, "set_component", flaky)
    end = RT.run_component("reporting", tick=lambda: 0.05, root=tmp_path, max_ticks=3,
                           sleep=lambda s: time.sleep(min(s, 0.01)))
    assert end == "STOPPED" and calls["n"] >= 1
    ev = [r["event"] for r in RT.RuntimeStore(tmp_path).con.execute(
        "SELECT event FROM component_events WHERE component='reporting'")]
    assert "HEARTBEAT_WRITE_FAILED" in ev and "CRASH" not in ev


# ================================================================================================ defect 2: snapshots
def _engine(tmp_path):
    from tests.test_continuous_opportunity_engine import Clock, FakeData, U, _world
    from talonx_opportunity.ingestion import Ingestion
    minute, daily, members = _world()
    clock = Clock(U(9))
    data = FakeData(minute, daily)
    ing = Ingestion(data=data, root=tmp_path, clock=clock, universe_loader=lambda: (members, "test"))
    return ing, clock, U


def _mixed(st) -> list[str]:
    """A snapshot is mixed if any aggregate holds a bar at/after the snapshot's own as_of (data newer than as_of)."""
    as_of = st["state"]["as_of_utc"]
    return sorted(s for s, a in st["aggs"].items() if a.last_t and
                  datetime.fromisoformat(a.last_t.replace("Z", "+00:00")) >= datetime.fromisoformat(as_of))


def test_reader_racing_writer_never_observes_a_mixed_generation(tmp_path, monkeypatch):
    from talonx_opportunity import ingestion as I
    ing, clock, U = _engine(tmp_path)
    clock.t = U(9)
    ing.tick()                                           # generation N committed
    wid = ing._window_id
    real_connect = I.connect

    class Proxy:                                         # the reader's connection; the writer commits N+1 mid-read
        def __init__(self, con):
            self._c, self.fired = con, False

        def execute(self, sql, *a):
            cur = self._c.execute(sql, *a)
            if "ingestion_state" in sql and not self.fired:
                cur = list(cur)                          # materialise this statement's result first
                self.fired = True
                clock.t = U(9, 30)
                ing.tick()                               # writer pause injected between the reader's statements
                return _Rows(cur)
            return cur

        def __getattr__(self, k):
            return getattr(self._c, k)

    class _Rows(list):
        def fetchone(self):
            return self[0] if self else None

    monkeypatch.setattr(I, "connect", lambda p, **kw: Proxy(real_connect(p, **kw)) if kw.get("readonly")
                        else real_connect(p, **kw))
    st = I.read_state(tmp_path, wid)
    assert _mixed(st) == [], f"as_of {st['state']['as_of_utc']} but newer aggregates for {_mixed(st)}"


def test_dtu_active_set_and_as_of_are_published_under_one_generation(tmp_path, monkeypatch):
    """Inject a reader at the writer's pause between the OLD separate writes (DTU active commit -> fetch ->
    aggregates/as_of commit). The reader (one read transaction) must never see the next cycle's active set with
    the previous cycle's as_of."""
    from talonx_opportunity import ingestion as I, universe_tiers as UT
    from tests.test_dtu_universe import policy, universe
    members, daily = universe()
    t = {"now": datetime(2026, 9, 29, 15, 0, tzinfo=UTC)}
    seen = []

    class Data:
        _headers, requests, errors = {}, 0, []

        def bars_ex(self, syms, **kw):
            if t.get("probe_reader"):
                seen.append(I.read_state(tmp_path, "2026-09-29"))      # reader inside the writer's pause
            from talonx_premarket.alpaca_data import FetchResult
            return FetchResult()

        def assets(self):
            return []
    ing = I.Ingestion(data=Data(), root=tmp_path, clock=lambda: t["now"], universe_loader=lambda: (members, "t"),
                      dtu_mode=UT.ACTIVE, dtu=None)
    ing._dtu = UT.DTU(ing.con, policy=policy(2), clock=lambda: t["now"], snapshot_fetch=lambda s: ({}, 1, []),
                      edgar_fetch=lambda: [], readers={"open_candidates": lambda w: [], "signals_today": lambda w: [],
                                                       "positions": lambda w: set()})
    with ing.con:
        for s, bars in daily.items():
            ing.con.execute("INSERT OR REPLACE INTO daily VALUES (?,?,?)", ("2026-09-29", s, json.dumps(bars)))
        ing.con.execute("INSERT OR REPLACE INTO daily_state VALUES (?,?,?)", ("2026-09-29", t["now"].isoformat(), "[]"))
    monkeypatch.setattr(I.C, "effective_capability", lambda phase, probe: type("Cap", (), {
        "usable_for_discovery": True, "availability": "AVAILABLE", "evidence": ""})())
    monkeypatch.setattr(ing, "probe", lambda phase, now: {"ok": True})
    import talonx_premarket.__main__ as M
    monkeypatch.setattr(M, "_v2_scope", lambda x: set())
    ing.tick()                                            # cycle N published
    t["now"] += timedelta(minutes=1)
    t["probe_reader"] = True
    ing.tick()                                            # cycle N+1: reader runs inside the writer's pause
    st = seen[-1]
    assert st["dtu"] is not None and st["state"] is not None
    assert st["dtu"]["cycle_utc"] == st["state"]["cycle_utc"], \
        f"active set of cycle {st['dtu']['cycle_utc']} served with as_of of cycle {st['state']['cycle_utc']}"
