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


# ---------------------------------------------------------------------------------------------- study completeness
# Registered schedule (provenance):
#   docs/research/evidence/2026-09-30_v2_validation/forward_daily.sh -- waits for the Jul-Sep EDGAR backfill
#   (edgar/20260929.done), runs a START-UP cycle at once (it ran 2026-09-30), then daily at 06:00Z on EVERY calendar
#   day (no weekday filter) while date.today() <= the stop date (INCLUSIVE). forward_daily_v2.sh (2026-10-05) keeps
#   the same 06:00Z schedule and stop date. Documented interruptions: none skipped a slot (the 2026-10-05 loop
#   replacement happened after that day's cycle; the 2026-10-10 weekend assessment kept the loop running).
START_DAY = "2026-09-30"
START_NOTE = "start-up cycle after the EDGAR backfill marker (not a 06:00Z slot)"
RUN_BUDGET_MIN = 90                          # forward_runner deadline budget: never MISSING inside it
_LOG_KEYS = {"cycle_done", "cycle_end", "day", "state", "exit", "forward_runner", "run_id", "failed_stage",
             "error_class", "wrapper_v2_start", "first_cycle_at", "loop_end", "reason", "deadline_utc", "cutoffs",
             "existing"}
INCOMPLETE = ("FAILED", "PARTIAL", "ABANDONED", "MISSING", "PROCESS_ABSENT", "OVERDUE_ALIVE", "OVERDUE_UNCONFIRMED")


def _structured_log(repo: Path) -> list[dict]:
    """ONLY whole-line JSON objects made entirely of operational keys (cycle / runner markers). Every other line --
    which may carry research statistics -- is dropped unparsed and never surfaced."""
    out = []
    try:
        text = (repo / "results" / "v2_validation" / "forward.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        t = line.strip()
        if not (t.startswith("{") and t.endswith("}")):
            continue
        try:
            d = json.loads(t)
        except ValueError:
            continue
        if isinstance(d, dict) and d and set(d) <= _LOG_KEYS:
            out.append(d)
    return out


def _slot_time(day: str) -> datetime:
    d = datetime.fromisoformat(day).replace(tzinfo=UTC)
    return d if day == START_DAY else d.replace(hour=SLOT_HOUR_UTC)


def _classify_slot(row: dict, rec: dict | None, ends: list[dict], legacy: list[str], slot: datetime,
                   now: datetime, ps) -> None:
    if rec is not None:
        dv = derive(rec, now, ps)
        art = rec.get("artifact") if isinstance(rec.get("artifact"), dict) else {}
        row.update(recorded_state=dv["recorded_state"], state=dv["observed_state"], reason=dv["reason"],
                   artifact_validated=art.get("validated"),
                   provenance="RECONSTRUCTED" if rec.get("reconstructed_from_log") else "RUNNER_RECORD")
        if dv["observed_state"] == "SUCCESS" and row["output_file"] is None:
            row["conflicts"].append("record SUCCESS but output file absent")
        if dv["observed_state"] in ("FAILED", "PARTIAL") and row["output_file"] and rec.get("started_utc") \
                and row["output_file"] >= str(rec.get("started_utc")):
            row["conflicts"].append("record not SUCCESS but an output file was written after the run start")
        for x in ends:
            if x.get("state") != rec.get("state"):
                row["conflicts"].append(f"loop logged {x.get('state')} but the record says {rec.get('state')}")
    elif now < slot:
        row.update(recorded_state=None, state="NOT_YET_DUE", reason="slot in the future")
    elif legacy or ends:
        row.update(recorded_state=None, state="UNVERIFIED", provenance="LEGACY_LOG" if legacy else "LOOP_LOG",
                   reason="no run record; legacy loop recorded no exit status or validation"
                          + ("; an output file was written during that cycle (not opened; never proof)"
                             if row["output_file"] else "; no output file"))
    elif now < slot + timedelta(minutes=RUN_BUDGET_MIN):
        row.update(recorded_state=None, state="DUE_AWAITING_RECORD", reason="slot passed; inside the run budget")
    else:
        row.update(recorded_state=None, state="MISSING", reason="slot elapsed; no run evidence found")


def completeness(repo: Path, now: datetime, ps=None) -> dict:
    """One row per REGISTERED slot, START_DAY .. stop date inclusive -- built from the schedule, not from whichever
    files exist. Evidence: the modern run record (read), structured legacy loop markers, and the output file's
    existence/mtime (stat only -- outputs are never opened). One state per slot; conflicts are listed, never
    silently resolved in the favourable direction."""
    end = _end_date(repo)
    runs = repo / "results" / "v2_validation" / "forward_runs"
    outd = repo / "results" / "v2_validation" / "forward"
    log = _structured_log(repo)
    rows: list[dict] = []
    d = datetime.fromisoformat(START_DAY).date()
    last = datetime.fromisoformat(end).date() if end else None
    while last is not None and d <= last:
        day = d.isoformat()
        slot = _slot_time(day)
        row = {"day": day, "weekday": d.strftime("%a"), "evidence": [], "conflicts": [],
               "expected_utc": f"{day} ({START_NOTE})" if day == START_DAY else slot.isoformat()}
        rec, rec_p = None, runs / f"{day}.json"
        if rec_p.exists():
            try:
                rec = json.loads(rec_p.read_text(encoding="utf-8"))
                if not isinstance(rec, dict):
                    raise ValueError("not an object")
                row["evidence"].append("run record" + (" (RECONSTRUCTED from log)" if rec.get("reconstructed_from_log")
                                                       else ""))
            except (OSError, ValueError) as exc:
                rec = None
                row.update(recorded_state="UNREADABLE", state="UNREADABLE",
                           reason=f"run record unreadable: {type(exc).__name__}")
        if any(f.name != rec_p.name for f in runs.glob(f"{day}.json*") if f.name.endswith("tmp")):
            row["evidence"].append("orphaned temp record (not authoritative, not read)")
        legacy = [x["cycle_done"] for x in log if str(x.get("cycle_done", "")).startswith(day)]
        ends = [x for x in log if x.get("cycle_end") and x.get("day") == day]
        if legacy:
            row["evidence"].append("legacy cycle_done " + ", ".join(legacy) + " (written unconditionally)")
        if ends:
            row["evidence"].append("loop cycle_end " + ", ".join(f"{x.get('state')}/exit {x.get('exit')}" for x in ends))
        try:
            row["output_file"] = datetime.fromtimestamp((outd / f"{day}.json").stat().st_mtime, UTC).isoformat()
        except OSError:
            row["output_file"] = None
        if row.get("state") != "UNREADABLE":
            _classify_slot(row, rec, ends, legacy, slot, now, ps)
        rows.append(row)
        d += timedelta(days=1)
    counts = {"success": 0, "incomplete_or_missing": 0, "unverified": 0, "running_or_due": 0, "not_yet_due": 0,
              "unreadable_or_unknown": 0}
    for r in rows:
        st = r["state"]
        counts["success" if st == "SUCCESS" else "incomplete_or_missing" if st in INCOMPLETE else
               "unverified" if st == "UNVERIFIED" else "not_yet_due" if st == "NOT_YET_DUE" else
               "running_or_due" if st in ("RUNNING", "DUE_AWAITING_RECORD") else "unreadable_or_unknown"] += 1
    return {"period": f"{START_DAY} .. {end} (inclusive)" if end else "UNKNOWN (stop date unreadable)",
            "schedule": "start-up cycle 2026-09-30, then daily 06:00Z every calendar day (weekends included)",
            "as_of_utc": now.isoformat(), "slots": len(rows), "counts": counts,
            "affected": [{k: r.get(k) for k in ("day", "state", "reason", "provenance", "conflicts")}
                         for r in rows if r["state"] not in ("SUCCESS", "NOT_YET_DUE")],
            "slots_detail": rows}


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
    # 2026-10-12 correction: the former "incomplete_days_in_view" covered only the last ``days`` record files, so
    # 2026-10-05 (8th file back) and the record-less legacy days were never counted. Completeness is now derived from
    # the REGISTERED schedule over the whole study period.
    out["completeness"] = completeness(Path(repo), now, ps)
    out["note"] = ("current_health = the most recent run only (operational); completeness = every registered slot "
                   "of the study period (a later healthy run does not repair an earlier gap)")
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
