"""
Unattended checkpoint + event daemon for a prospective V2 session
(Task 114 B3/B4).  Runs from ``prospective start`` (spawned detached) or
directly for rehearsal.  Writes:

  <session_dir>/checkpoints/checkpoint_<n>_<utc>.json
  <session_dir>/checkpoints/latest.json
  <session_dir>/events.jsonl                (one JSON object per line)

Stops on: SIGINT/SIGTERM, a ``<session_dir>/stop.flag`` sentinel, or
(if --until-close) ~2h after the XNYS close.
"""
from __future__ import annotations

import json
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from talonx_ops.prospective.checkpoint import capture
from talonx_ops.prospective.events import classify
from talonx_ops.prospective.paths import atomic_write

_STOP = {"v": False}


def _install_signals() -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: _STOP.__setitem__("v", True))
        except (ValueError, OSError):
            pass


def _close_deadline(now: datetime) -> datetime | None:
    try:
        import exchange_calendars as xc
        cal = xc.get_calendar("XNYS")
        d = now.date()
        if not cal.is_session(d):
            return None
        return cal.session_close(d).to_pydatetime() + timedelta(hours=2)
    except Exception:  # noqa: BLE001
        return None


def run_loop(session_dir: str | Path, *, checkpoint_every_s: int = 1800,
             until_close: bool = True, max_iterations: int | None = None,
             clock=None) -> int:
    _install_signals()
    sd = Path(session_dir)
    (sd / "checkpoints").mkdir(parents=True, exist_ok=True)
    events_path = sd / "events.jsonl"
    stop_flag = sd / "stop.flag"
    now_fn = clock or (lambda: datetime.now(timezone.utc))

    prev = None
    n = 0
    # seed prev from latest.json if resuming
    latest = sd / "checkpoints" / "latest.json"
    if latest.exists():
        try:
            prev = json.loads(latest.read_text())
        except Exception:  # noqa: BLE001
            prev = None

    while not _STOP["v"]:
        now = now_fn()
        if stop_flag.exists():
            break
        n += 1
        ck = capture(now=now)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        atomic_write(sd / "checkpoints" / f"checkpoint_{n:04d}_{stamp}.json",
                     json.dumps(ck, indent=2, default=str))
        atomic_write(sd / "checkpoints" / "latest.json", json.dumps(ck, indent=2, default=str))

        evs = classify(prev, ck, session_running=True)
        if evs:
            with events_path.open("a", encoding="utf-8") as fh:
                for e in evs:
                    e = {"ts_utc": now.isoformat(), "checkpoint": n, **e}
                    fh.write(json.dumps(e, default=str) + "\n")
        prev = ck

        if max_iterations is not None and n >= max_iterations:
            break
        dl = _close_deadline(now)
        if until_close and dl is not None and now >= dl:
            break

        # sleep in slices so stop.flag / signals are responsive
        end = time.monotonic() + checkpoint_every_s
        while time.monotonic() < end and not _STOP["v"] and not stop_flag.exists():
            time.sleep(1.0)

    # final checkpoint on the way out
    now = now_fn()
    ck = capture(now=now)
    n += 1
    atomic_write(sd / "checkpoints" / f"checkpoint_{n:04d}_final_{now.strftime('%Y%m%dT%H%M%SZ')}.json",
                 json.dumps(ck, indent=2, default=str))
    atomic_write(sd / "checkpoints" / "latest.json", json.dumps(ck, indent=2, default=str))
    evs = classify(prev, ck, session_running=True)
    if evs:
        with events_path.open("a", encoding="utf-8") as fh:
            for e in evs:
                fh.write(json.dumps({"ts_utc": now.isoformat(), "checkpoint": n, "final": True, **e},
                                    default=str) + "\n")
    return 0
