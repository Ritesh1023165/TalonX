"""
READ-ONLY operational view of the V2@1 shadow forward tracker's run records (results/v2_validation/forward_runs/<day>.json)
for the dashboard (2026-10-12, after the 2026-10-11 abandoned-RUNNING incident).

Reads ONLY the structured run records (and the names of persistence-failure diagnostics). Never opens forward/,
evaluation or any other research output. Shows the RECORDED state verbatim next to a conservatively DERIVED observed
state:
  RUNNING                 recorded RUNNING, process identity verified alive, deadline not passed
  OVERDUE_ALIVE           recorded RUNNING, process identity verified alive, deadline passed
  ABANDONED               recorded RUNNING, process verified ABSENT (pid gone, or pid now held by a different process
                          created after the run started) AND deadline passed
  PROCESS_ABSENT          recorded RUNNING, process verified absent, deadline not yet passed
  OVERDUE_UNCONFIRMED     recorded RUNNING, liveness cannot be established, deadline passed
  UNKNOWN                 recorded RUNNING, liveness cannot be established, deadline not passed; or an unknown state
  UNREADABLE              the record cannot be read / parsed (never shown as healthy or successful)
  SUCCESS / PARTIAL / FAILED  terminal recorded states; SUCCESS only when the record itself says the artifact validated
A deadline passing alone never proves the process stopped; a live pid alone never proves the run is alive.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
SLOT_HOUR_UTC = 6
TERMINAL = ("SUCCESS", "PARTIAL", "FAILED")


def _ts(s):
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def process_identity(pid, started_utc: datetime | None, ps=None) -> tuple[str, str]:
    """('ALIVE'|'ABSENT'|'PID_REUSED'|'UNKNOWN', detail). ALIVE needs the pid to exist, to have been created no later
    than the run start (+5 s) and to be a forward_runner process."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return "UNKNOWN", "no pid recorded"
    try:
        ps = ps or __import__("psutil")
    except ImportError:
        return "UNKNOWN", "psutil unavailable"
    try:
        if not ps.pid_exists(pid):
            return "ABSENT", f"pid {pid} not present"
        p = ps.Process(pid)
        created = datetime.fromtimestamp(p.create_time(), UTC)
        cmd = " ".join(p.cmdline() or [])
    except Exception as exc:  # noqa: BLE001 -- NoSuchProcess / AccessDenied / ZombieProcess
        name = type(exc).__name__
        return ("ABSENT", f"pid {pid}: {name}") if name == "NoSuchProcess" else ("UNKNOWN", f"pid {pid}: {name}")
    if started_utc is not None and created > started_utc + timedelta(seconds=5):
        return "PID_REUSED", f"pid {pid} now belongs to a process created {created.isoformat()} (after the run start)"
    if "forward_runner" not in cmd:
        return "PID_REUSED", f"pid {pid} is not a forward_runner process"
    return "ALIVE", f"pid {pid} forward_runner, created {created.isoformat()}"


def derive(rec: dict, now: datetime, ps=None) -> dict:
    recorded = rec.get("state")
    deadline = _ts(rec.get("deadline_utc"))
    passed = deadline is not None and now >= deadline
    out = {"recorded_state": recorded, "deadline_passed": passed if deadline else None}
    if recorded in TERMINAL:
        art = rec.get("artifact") if isinstance(rec.get("artifact"), dict) else {}
        if recorded == "SUCCESS" and art.get("validated") is not True:
            out.update(observed_state="UNKNOWN", reason="recorded SUCCESS without a validated-artifact flag")
        else:
            out.update(observed_state=recorded, reason="terminal recorded state")
        return out
    if recorded != "RUNNING":
        out.update(observed_state="UNKNOWN", reason=f"unrecognised recorded state {recorded!r}")
        return out
    ident, detail = process_identity(rec.get("pid"), _ts(rec.get("started_utc")), ps)
    out["process"] = {"identity": ident, "detail": detail}
    absent = ident in ("ABSENT", "PID_REUSED")
    if ident == "ALIVE":
        out.update(observed_state="OVERDUE_ALIVE" if passed else "RUNNING",
                   reason="process identity verified alive" + ("; deadline passed" if passed else ""))
    elif absent and passed:
        out.update(observed_state="ABANDONED", reason="verified process absent and deadline passed")
    elif absent:
        out.update(observed_state="PROCESS_ABSENT", reason="verified process absent; deadline not yet passed")
    else:
        out.update(observed_state="OVERDUE_UNCONFIRMED" if passed else "UNKNOWN",
                   reason="process liveness could not be established" + ("; deadline passed" if passed else ""))
    return out


def _last_stage(rec: dict) -> dict | None:
    last = None
    for s in rec.get("stages") or []:
        if isinstance(s, dict) and s.get("state") not in (None, "PENDING", "NOT_RUN"):
            last = {"name": s.get("name"), "state": s.get("state"), "started_utc": s.get("started_utc"),
                    "ended_utc": s.get("ended_utc"), "exit_code": s.get("exit_code")}
    return last


def _end_date(repo: Path) -> str | None:
    try:
        sh = (repo / "docs/research/evidence/2026-09-30_v2_validation/forward_daily_v2.sh").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"date\((\d{4}),(\d{1,2}),(\d{1,2})\)", sh)
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def next_slot(now: datetime) -> datetime:
    s = now.astimezone(UTC).replace(hour=SLOT_HOUR_UTC, minute=0, second=0, microsecond=0)
    return s if now < s else s + timedelta(days=1)


def view(repo: Path, now: datetime | None = None, days: int = 7, ps=None) -> dict:
    now = now or datetime.now(UTC)
    runs = Path(repo) / "results" / "v2_validation" / "forward_runs"
    out = {"source": "results/v2_validation/forward_runs/<day>.json (operational records only; no outputs read)",
           "generated_utc": now.isoformat(), "next_scheduled_run_utc": next_slot(now).isoformat(),
           "study_end_date": _end_date(Path(repo)), "runs": []}
    files = sorted(f for f in runs.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f.name))[-days:] \
        if runs.is_dir() else []
    for f in reversed(files):
        day = f.stem
        diags = sorted(x.name for x in runs.glob(f"{day}.*.persistence_failure.*.json"))
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(rec, dict):
                raise ValueError("record is not an object")
        except (OSError, ValueError) as exc:
            out["runs"].append({"day": day, "recorded_state": "UNREADABLE", "observed_state": "UNREADABLE",
                                "reason": f"status record unreadable: {type(exc).__name__}",
                                "persistence_failure_diagnostics": diags})
            continue
        art = rec.get("artifact") if isinstance(rec.get("artifact"), dict) else None
        row = {"day": day, "run_id": rec.get("run_id"), "scheduled_utc": rec.get("scheduled_utc"),
               "started_utc": rec.get("started_utc"), "ended_utc": rec.get("ended_utc"),
               "deadline_utc": rec.get("deadline_utc"), "last_update_utc": rec.get("ended_utc") or rec.get("heartbeat_utc"),
               "last_stage": _last_stage(rec), "pid": rec.get("pid"), "error_class": rec.get("error_class"),
               "failed_stage": rec.get("failed_stage"), "runner_version": rec.get("runner_version"),
               "artifact_validated": art.get("validated") if art else None,
               "persistence_retries": len(rec.get("persistence_retries") or []),
               "persistence_failure_diagnostics": diags}
        row.update(derive(rec, now, ps))
        out["runs"].append(row)
    latest = out["runs"][0] if out["runs"] else None
    out["current_health"] = (
        "NO_RECORDS" if latest is None else
        "HEALTHY" if latest.get("observed_state") in ("SUCCESS", "RUNNING") else
        f"ATTENTION ({latest.get('observed_state')})")
    out["incomplete_days_in_view"] = [r["day"] for r in out["runs"] if r.get("observed_state") != "SUCCESS"
                                      and r.get("observed_state") != "RUNNING"]
    out["note"] = ("current_health reflects the most recent day only; incomplete_days_in_view lists earlier days "
                   "without a SUCCESS observation (study completeness), which a later healthy run does not repair")
    return out


# The dashboard is itself a reader of the run records. On Windows any open read handle (even FILE_SHARE_DELETE) makes
# the runner's os.replace fail with WinError 5 (verified on synthetic files 2026-10-12), so reads are RATE-LIMITED to
# one per VIEW_TTL_S per process (each read is ~ms); the runner's bounded replace retries absorb a residual collision.
VIEW_TTL_S = 60.0
_CACHE: dict = {}


def view_cached(repo: Path, now: datetime | None = None, ttl_s: float = VIEW_TTL_S, clock=None) -> dict:
    import time as _t
    clock = clock or _t.monotonic
    key = str(Path(repo).resolve())
    hit = _CACHE.get(key)
    if hit is not None and clock() - hit[0] < ttl_s:
        return hit[1]
    v = view(repo, now)
    _CACHE[key] = (clock(), v)
    return v
