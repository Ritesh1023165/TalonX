"""
POST_DELIVERY_ALERT_MARKOUT_V1 -- the single scheduled collector invocation (one bounded run, then exit).

usage: python -m talonx_paperperf.post_delivery_collector --config LOCKED_CONFIG.json [--enable]
                                                           [--store DIR] [--budget-s 900] [--max-observations N]
The per-run observation PROCESSING budget is authoritative in the locked config
(``collector.max_observations_per_run``); it is a batch size, never a sample-size cap -- unprocessed work stays pending
for the next run. ``--max-observations`` is optional and must EQUAL the locked value; a different or invalid value
refuses the run (CONFIG_REJECTED) instead of being silently ignored.
Each run:
  1. singleton lock (refuses an overlapping run; a lock whose pid is gone is recorded and replaced);
  2. revalidates the LOCKED config: owner approval, protocol fingerprint AND implementation file hashes;
  3. records scheduled vs actual start (daily 00:15 Europe/London) and missed calendar days since the last run;
  4. post_delivery_markout.run(): deadlines reconciled FIRST; register/select; bounded acquisition (none before the
     activation boundary, none at/after the endpoint, never outside R5 / before close + 60 min); deadlines again;
  5. writes OPERATIONAL status only (counts, states, errors -- never a return value) and exits.
Without --enable it records a DISABLED run and makes no request and no study write.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
REPO = Path(__file__).resolve().parents[1]
# Europe/London triggers (owner-approved 2026-10-09): 00:15 = 23:15Z (BST) / 00:15Z (GMT);
#                                                     06:30 = 05:30Z (BST) / 06:30Z (GMT)
SCHEDULE_LOCAL_TIMES = (dtime(0, 15), dtime(6, 30))


def slots_between(a: datetime, b: datetime) -> list[datetime]:
    """Scheduled trigger instants s with a < s <= b (UTC), in order."""
    out, d = [], a.astimezone(LONDON).date() - timedelta(days=1)
    while d <= b.astimezone(LONDON).date():
        for tm in SCHEDULE_LOCAL_TIMES:
            s = datetime.combine(d, tm, tzinfo=LONDON).astimezone(UTC)
            if a < s <= b:
                out.append(s)
        d += timedelta(days=1)
    return out


def scheduled_for(now: datetime) -> datetime:
    """The scheduled trigger this invocation belongs to (the most recent trigger instant at or before now)."""
    return slots_between(now - timedelta(days=2), now)[-1]


class Lock:
    def __init__(self, path: Path):
        self.path, self.held, self.note = Path(path), False, None

    def acquire(self, pid: int = None, alive=None) -> bool:
        pid = pid or os.getpid()
        if alive is None:
            import psutil
            alive = psutil.pid_exists
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, json.dumps({"pid": pid, "at": datetime.now(UTC).isoformat()}).encode())
                os.close(fd)
                self.held = True
                return True
            except FileExistsError:
                try:
                    other = json.loads(self.path.read_text(encoding="utf-8")).get("pid")
                except (OSError, ValueError):
                    other = None
                if other and alive(int(other)):
                    return False                                   # a live run holds it: refuse to overlap
                self.note = f"stale lock of pid {other} replaced"
                try:
                    self.path.unlink()
                except OSError:
                    return False
        return False

    def release(self):
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass


def missed_slots(log_path: Path, now: datetime) -> list[str]:
    """Trigger instants that passed with no recorded run between the previous run and this one (lateness of THIS run
    is reported separately as late_s)."""
    last = _last_actual(log_path)
    if last is None:
        return []
    prev = scheduled_for(last)
    return [s.isoformat() for s in slots_between(prev, scheduled_for(now))[:-1]]


def _last_actual(log_path: Path):
    if not log_path.exists():
        return None
    last = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            last = json.loads(line).get("actual_utc") or last
        except ValueError:
            continue
    return datetime.fromisoformat(last) if last else None


def missed_days(log_path: Path, now: datetime) -> list[str]:
    """London dates with no recorded run between the previous run and this one."""
    if not log_path.exists():
        return []
    last = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            last = json.loads(line).get("actual_utc") or last
        except ValueError:
            continue
    if not last:
        return []
    prev = datetime.fromisoformat(last).astimezone(LONDON).date()
    cur = now.astimezone(LONDON).date()
    return [(prev + timedelta(days=i)).isoformat() for i in range(1, (cur - prev).days)]


def resolve_max_observations(config: Path, requested: int | None) -> int:
    """The single effective value: the locked config's collector.max_observations_per_run. Raises ValueError when it is
    missing/invalid or when an explicitly requested value conflicts with it."""
    from talonx_paperperf.post_delivery_markout import validate_max_observations
    try:
        locked = json.loads(Path(config).read_text(encoding="utf-8"))["collector"]["max_observations_per_run"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"locked collector.max_observations_per_run unreadable: {exc.__class__.__name__}") from None
    locked = validate_max_observations(locked)
    if requested is not None and validate_max_observations(requested) != locked:
        raise ValueError(f"--max-observations {requested} conflicts with locked collector.max_observations_per_run "
                         f"{locked}")
    return locked


def collect(*, config: Path, enable: bool, store: Path, budget_s: float, max_observations: int | None = None,
            now: datetime | None = None, acquirer=None, outbox_path: Path | None = None,
            promotion_path: Path | None = None, trace_path: Path | None = None, repo: Path = REPO,
            lock_alive=None) -> dict:
    from talonx_paperperf import post_delivery_markout as M
    now = now or datetime.now(UTC)
    store = Path(store)
    ops = store.parent / (store.name + "_ops")                     # operational files never in the study store
    ops.mkdir(parents=True, exist_ok=True)
    lock = Lock(ops / "collector.lock")
    sched = scheduled_for(now)
    rec = {"scheduled_utc": sched.isoformat(), "actual_utc": now.isoformat(),
           "late_s": round((now - sched).total_seconds(), 1), "missed_days": missed_days(ops / "runs.jsonl", now),
           "missed_slots": missed_slots(ops / "runs.jsonl", now)}
    if not lock.acquire(alive=lock_alive):
        rec["state"] = "REFUSED_OVERLAP"
        _log(ops, rec)
        return rec
    try:
        rec["lock_note"] = lock.note
        try:
            rec["max_observations"] = resolve_max_observations(config, max_observations)
        except ValueError as exc:
            rec["state"], rec["reason"] = "CONFIG_REJECTED", str(exc)
            return rec
        if not enable:
            rec["state"] = "DISABLED"
            return rec
        opp = repo / "results" / "opportunity"
        ob = outbox_path or opp / "promotion_signal_notifications.db"
        pc = promotion_path or opp / "promotion.db"
        tp = trace_path or opp / "promotion_delivery_trace.db"
        from talonx_opportunity.delivery_trace import make_trace_lookup
        if acquirer is None:
            from talonx_paperperf.post_delivery_acquisition import AlpacaAcquirer
            acquirer = _LazyAcquirer(lambda: AlpacaAcquirer.from_env(budget_s=budget_s))
        out = M.run({M.ENABLE_ENV: "1", M.CONFIG_ENV: str(config)}, store_root=store, acquirer=acquirer, now=now,
                    outbox_path=ob, promotion_path=pc, trace_lookup=make_trace_lookup(ob, tp),
                    require_integrity=True, repo=repo, max_observations=rec["max_observations"])
        rec.update(state=out.get("state"), reason=out.get("reason"),
                   summary={k: out.get(k) for k in ("expired_before", "registered", "observations_created",
                                                    "acquisition", "expired_after")},
                   health=out.get("health"))
        if out.get("health") is not None:
            (ops / "status_latest.json").write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
        return rec
    finally:
        _log(ops, rec)
        lock.release()


class _LazyAcquirer:
    """Credentials / client are created only if a request is actually due (no request before activation)."""
    def __init__(self, factory):
        self._f, self._a = factory, None

    def _get(self):
        if self._a is None:
            self._a = self._f()
        return self._a

    def permitted(self, now):
        from talonx_paperperf.post_delivery_acquisition import r5_permitted
        return r5_permitted(now)

    def bar(self, sym, start):
        return self._get().bar(sym, start)

    def quote(self, sym, target):
        return self._get().quote(sym, target)


def _log(ops: Path, rec: dict) -> None:
    with (ops / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({k: v for k, v in rec.items() if k != "health"}, default=str) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--enable", action="store_true")
    ap.add_argument("--store", default=str(REPO / "results" / "post_delivery_markout"))
    ap.add_argument("--budget-s", type=float, default=900.0)
    ap.add_argument("--max-observations", type=int, default=None,
                    help="optional; must equal the locked collector.max_observations_per_run")
    a = ap.parse_args(argv)
    from talonx_premarket import __main__ as M
    M._env()
    rec = collect(config=Path(a.config), enable=a.enable, store=Path(a.store), budget_s=a.budget_s,
                  max_observations=a.max_observations)
    print(json.dumps({k: rec.get(k) for k in ("state", "reason", "scheduled_utc", "actual_utc", "late_s",
                                              "missed_days", "missed_slots", "max_observations")}, default=str))
    return 0 if rec.get("state") in ("ENABLED", "DISABLED", "BEFORE_ACTIVATION") else 3


if __name__ == "__main__":
    sys.exit(main())
