"""
V2@1 SHADOW forward tracker -- one daily cycle with explicit, truthful status (2026-10-05 reliability fix).

Runs the UNCHANGED study stages, in the UNCHANGED order and arguments of docs/research/evidence/2026-09-30_v2_validation/
forward_daily.sh:
    edgar_crawl  python -m talonx_paperperf.form4_edgar 2026-09-30 <UTC yesterday> --rate 4
    episodes     python -m talonx_paperperf.v2_validation episodes
    prices       python -m talonx_paperperf.v2_validation prices        (classified transient retries, see transient_http)
    evaluate     python -m talonx_paperperf.v2_validation evaluate      (stdout discarded, as before)
    forward      python -m talonx_paperperf.v2_validation forward
Nothing about the study's population, stages, cutoffs, end date or acceptance criteria changes.

States (results/v2_validation/forward_runs/<day>.json, written atomically at start and after every stage):
  RUNNING   the cycle is in progress (or its process died: ``pid`` + ``heartbeat_utc`` tell which)
  SUCCESS   every stage exited 0 AND forward/<day>.json was written by THIS run and validates (as_of == day, required
            keys); the only state that counts as an observation
  PARTIAL   at least one stage completed, a later stage failed / timed out / was not reached; no validated artifact.
            Inputs may have advanced (crawl, episodes, price cache) -- all idempotent / resumable -- but NO observation
  FAILED    the first stage failed, the runner itself failed, or all stages exited 0 but the artifact did not validate
A stage is never retried as a whole: request-level retries live inside the stages (transient_http; form4_edgar's own
loop). One cycle per day: a day whose record is SUCCESS or still RUNNING (live pid) is never re-run; a FAILED/PARTIAL
day is not re-run automatically either (the loop only ever runs the CURRENT day at its scheduled slot).
Deadline: every stage must end before ``deadline`` = min(start + 90 min, 23:30 of the study day, local date) -- so no
retry can push the forward snapshot across the study's ``date.today()`` boundary. A stage still running is stopped.
The deadline is an EXECUTION bound only; it is not an information cutoff.
Cutoffs (the study's contract is DATE-based; there is no time-of-day information cutoff in it): fixed ONCE at run start
and passed identically to every stage (TALONX_FWD_INFO_CUTOFF / _PRICE_END / _AS_OF):
  as_of        = the study day (local date.today(), as forward() always used)
  info_cutoff  = UTC yesterday = the crawl end forward_daily.sh always used; filings dated after it never enter
  price_end    = local yesterday = the last completed session date prices always used (end = date.today() - 1)
info_cutoff and price_end must be the same date; if they are not (a run started in the UTC/local-date gap), the run
FAILS (CUTOFF_DATE_MISMATCH) rather than silently mixing dates. Recorded in the run record (``cutoffs``).
EDGAR: the crawl stage must exit 0 AND its _crawl_status.json must carry THIS run's id, state COMPLETE and end ==
info_cutoff; otherwise the stage fails (no stale manifest or .done file is taken as this run's acquisition).
STATUS PERSISTENCE (2026-10-12, after the 2026-10-11 incident: os.replace of the run record failed with WinError 5 just
before ``evaluate`` and the runner died, leaving a dead RUNNING record). ``write_atomic`` keeps atomic replacement and
retries ONLY classified Windows sharing/access errors (5, 32, 33) on a fixed short budget capped by the run deadline. If
the record still cannot be persisted, the runner stops BEFORE the next stage (a stage is never entered unrecorded, a
completed stage is never repeated, nothing is retried or recovered automatically), leaves the last valid record
untouched, writes a best-effort independent diagnostic ``<day>.<run_id>.persistence_failure.<id>.json`` plus one stderr
line, and exits 4. A same-day record that is RUNNING with a dead pid (abandoned) or unreadable is refused, never re-run.
Exit codes: 0 SUCCESS, 2 PARTIAL, 1 FAILED, 3 refused (duplicate / already attempted / abandoned / unreadable),
4 STATUS_PERSISTENCE_FAILED. usage:
  python -m talonx_paperperf.forward_runner run [--scheduled ISO] | next-slot | sleep-to-next-slot
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "results" / "v2_validation"
RUNS = OUT / "forward_runs"
UTC = timezone.utc
SLOT_HOUR_UTC = 6
RUN_BUDGET_S = 90 * 60
REQUIRED_KEYS = ("as_of", "version", "freeze", "episodes_after_freeze", "rows")
CRAWL_STATUS = "edgar/_crawl_status.json"
DEADLINE_ENV = "TALONX_FWD_STAGE_DEADLINE_EPOCH"


def stages(py: str, crawl_end: date) -> list[tuple[str, list[str], bool]]:
    m = [py, "-m"]
    return [("edgar_crawl", m + ["talonx_paperperf.form4_edgar", "2026-09-30", crawl_end.isoformat(), "--rate", "4"], True),
            ("episodes", m + ["talonx_paperperf.v2_validation", "episodes"], True),
            ("prices", m + ["talonx_paperperf.v2_validation", "prices"], True),
            ("evaluate", m + ["talonx_paperperf.v2_validation", "evaluate"], False),     # stdout discarded (as before)
            ("forward", m + ["talonx_paperperf.v2_validation", "forward"], True)]


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def next_slot(now: datetime) -> datetime:
    """The next scheduled 06:00Z strictly in the future: a cycle that just ran (or failed) at 06:0x is never repeated
    the same day -- no catch-up."""
    s = now.astimezone(UTC).replace(hour=SLOT_HOUR_UTC, minute=0, second=0, microsecond=0)
    return s if now < s else s + timedelta(days=1)


RUNNER_VERSION = ("forward_runner v1.2 (2026-10-13: EDGAR closure-calendar provenance recorded; "
                  "v1.1 2026-10-12: bounded status-persistence retries, fail-closed boundaries)")
# Windows errors that can be TRANSIENT when replacing a file another process briefly holds open. Anything else (other
# OSErrors, serialization errors, non-Windows permission errors) is raised immediately, without retry.
RETRYABLE_WINERRORS = {5: "ERROR_ACCESS_DENIED", 32: "ERROR_SHARING_VIOLATION", 33: "ERROR_LOCK_VIOLATION"}
REPLACE_BACKOFF_S = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2)   # waits between attempts: 8 attempts, <= 6.35 s waiting
OUTCOME_STAGES = ("evaluate", "forward")                     # stages that can produce research outputs


class StatusPersistenceError(OSError):
    """The run record could not be atomically replaced; the previous valid record is untouched."""

    def __init__(self, path: Path, history: list[dict], cause: BaseException, retryable: bool):
        super().__init__(f"status persistence failed for {path.name}: {type(cause).__name__}")
        self.path, self.history, self.cause, self.retryable = path, history, cause, retryable


def write_atomic(path: Path, obj: dict, *, deadline: datetime | None = None, replace=os.replace, sleep=time.sleep,
                 monotonic=time.monotonic, now_fn=lambda: datetime.now(UTC)) -> list[dict]:
    """Serialize to a UNIQUE temp file in the same directory (closed + fsynced), then os.replace it over ``path``.
    Classified transient Windows errors are retried on REPLACE_BACKOFF_S (never past ``deadline``); the destination is
    never truncated or deleted. Returns the retry history ([] = first attempt succeeded); raises StatusPersistenceError
    when it cannot persist. Only this call's own temp file is ever removed."""
    data = json.dumps(obj, indent=1, default=str)        # serialization errors raise here: nothing written, no retry
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    history: list[dict] = []
    t0 = monotonic()
    try:
        with open(tmp, "x", encoding="utf-8") as fh:      # exclusive create: never another writer's temp file
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(1, len(REPLACE_BACKOFF_S) + 2):
            try:
                replace(tmp, path)
                return history
            except OSError as exc:
                code = getattr(exc, "winerror", None)
                history.append({"op": "replace", "attempt": attempt, "winerror": code, "errno": exc.errno,
                                "error": RETRYABLE_WINERRORS.get(code, type(exc).__name__),
                                "elapsed_s": round(monotonic() - t0, 3)})
                if code not in RETRYABLE_WINERRORS:
                    raise StatusPersistenceError(path, history, exc, retryable=False) from exc
                if attempt > len(REPLACE_BACKOFF_S):
                    history[-1]["stopped"] = "RETRY_BUDGET_EXHAUSTED"
                    raise StatusPersistenceError(path, history, exc, retryable=True) from exc
                wait = REPLACE_BACKOFF_S[attempt - 1]
                if deadline is not None and now_fn() + timedelta(seconds=wait) >= deadline:
                    history[-1]["stopped"] = "RUN_DEADLINE"
                    raise StatusPersistenceError(path, history, exc, retryable=True) from exc
                sleep(wait)
        raise AssertionError("unreachable")              # pragma: no cover
    finally:
        try:
            if tmp.exists():                              # only THIS call's temp file (unique name)
                tmp.unlink()
        except OSError:
            pass


def _write_diagnostic(rec: dict, boundary: str, exc: StatusPersistenceError, executed: list[str], log) -> str | None:
    """Best-effort, independent record of a persistence failure (NOT via write_atomic; never recursive). Returns the
    path written or None. Failure here never hides the original error."""
    exposure = [n for n in executed if n in OUTCOME_STAGES]
    diag = {"forward_runner": "STATUS_PERSISTENCE_FAILED", "run_id": rec.get("run_id"), "day": rec.get("day"),
            "boundary": boundary, "stages_executed": executed,
            "observed_stage": executed[-1] if executed else None,
            "outcome_exposure": ("OUTCOME_STAGE_STARTED_OR_WRITTEN:" + ",".join(exposure)) if exposure
            else "NO_OUTCOME_STAGE_STARTED",
            "automatic_recovery": "REFUSED (no stage is retried or re-run; the day must not be backfilled)",
            "last_valid_status": f"{exc.path.name} (left untouched; may show an earlier state)",
            "in_memory_stage_states": {s["name"]: s.get("state") for s in rec.get("stages", [])},
            "retryable": exc.retryable, "persistence_attempts": exc.history,
            "exception": sanitize(f"{type(exc.cause).__name__}: {exc.cause}"),
            "recorded_utc": iso(datetime.now(UTC)), "runner_version": RUNNER_VERSION,
            "durability": "best-effort diagnostic; not proof of any stage outcome"}
    line = json.dumps({k: diag[k] for k in ("forward_runner", "run_id", "day", "boundary", "outcome_exposure",
                                            "retryable")} | {"attempts": len(exc.history),
                                                             "exception": diag["exception"]})
    print(line, file=sys.stderr, flush=True)
    try:
        print(line, file=log, flush=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        dp = exc.path.with_name(f"{rec.get('day')}.{rec.get('run_id')}.persistence_failure.{uuid.uuid4().hex[:8]}.json")
        with open(dp, "x", encoding="utf-8") as fh:
            fh.write(json.dumps(diag, indent=1, default=str))
        return str(dp)
    except Exception as dexc:  # noqa: BLE001 -- diagnostics are best-effort; the original failure stands
        print(json.dumps({"forward_runner": "DIAGNOSTIC_WRITE_FAILED", "error": type(dexc).__name__}),
              file=sys.stderr, flush=True)
        return None


_SECRET = re.compile(r"(APCA-API-[A-Z-]+|api[_-]?key|secret|token|bot\d+:[\w-]+)", re.I)


def sanitize(text: str, limit: int = 400) -> str:
    """Last error line(s) only; URLs lose their query strings; anything key/token-like is masked."""
    lines = [x.strip() for x in (text or "").splitlines() if x.strip() and not x.strip().startswith(("^", "~"))]
    tail = " | ".join(lines[-2:])
    tail = re.sub(r"(https?://[^\s?'\"]+)\?[^\s'\"]*", r"\1?<query>", tail)
    tail = _SECRET.sub("<redacted>", tail)
    return tail[:limit]


def error_class(stderr: str) -> str:
    m = re.findall(r'"class": "([A-Z0-9_]+)", "attempt": \d+, (?:"[a-z_]+": [\d.]+, )?"outcome": "EXHAUSTED', stderr or "")
    if m:
        return f"TRANSIENT_EXHAUSTED:{m[-1]}"
    if "handshake operation timed out" in (stderr or ""):
        return "TLS_HANDSHAKE_TIMEOUT"
    if "CERTIFICATE_VERIFY_FAILED" in (stderr or ""):
        return "TLS_CERTIFICATE"
    m = re.search(r"HTTP (\d{3})", stderr or "")
    if m:
        return f"HTTP_{m.group(1)}"
    m = re.findall(r"^(\w+(?:Error|Exception|Exhausted))\b", stderr or "", re.M)
    return m[-1] if m else "NONZERO_EXIT"


def validate_artifact(day: date, not_before: float) -> tuple[bool, list[str]]:
    p = OUT / "forward" / f"{day.isoformat()}.json"
    why = []
    if not p.exists():
        return False, ["MISSING"]
    if p.stat().st_mtime < not_before:
        why.append("NOT_WRITTEN_BY_THIS_RUN")                 # a file's mere existence never proves completion
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, [f"UNPARSEABLE:{type(exc).__name__}"]
    if d.get("as_of") != day.isoformat():
        why.append(f"AS_OF_MISMATCH:{d.get('as_of')}")
    why += [f"MISSING_KEY:{k}" for k in REQUIRED_KEYS if k not in d]
    return not why, why


def _crawl_status_problem(run_id: str, crawl_end: date, stage: dict) -> str | None:
    """None iff the EDGAR manifest was written by THIS run and reports a COMPLETE acquisition through info_cutoff."""
    p = OUT / CRAWL_STATUS
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "EDGAR_STATUS_MISSING"
    stage["acquisition"] = {k: m.get(k) for k in ("state", "acquisition_result", "cause", "error", "end",
                                                  "day_interrupted", "days_index_not_found", "days_sec_closed",
                                                  "calendar", "tx_P_S_in_window")}
    if m.get("run_id") != run_id:
        return "EDGAR_STATUS_STALE"                     # a previous run's manifest never counts
    if m.get("end") != crawl_end.isoformat():
        return "EDGAR_STATUS_WRONG_WINDOW"
    if m.get("state") != "COMPLETE":
        return f"EDGAR_{m.get('state')}:{m.get('cause')}"
    return None


def _live(pid) -> bool:
    try:
        import psutil  # noqa: F401
        return psutil.pid_exists(int(pid))
    except Exception:  # noqa: BLE001
        r = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True)
        return str(int(pid)) in r.stdout


def run(*, scheduled: str | None = None, py: str | None = None, stage_list=None, today: date | None = None,
        now_fn=lambda: datetime.now(UTC), log=sys.stdout, budget_s: float = RUN_BUDGET_S) -> int:
    day = today or date.today()                      # the study's own as_of (forward() uses date.today())
    rec_path = RUNS / f"{day.isoformat()}.json"
    if rec_path.exists():
        try:
            prev = json.loads(rec_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:             # never overwrite an unreadable record of the same day
            print(json.dumps({"forward_runner": "REFUSED_UNREADABLE_RECORD", "day": day.isoformat(),
                              "error": type(exc).__name__}), file=log, flush=True)
            return 3
        if prev.get("state") == "RUNNING" and not _live(prev.get("pid", -1)):
            print(json.dumps({"forward_runner": "REFUSED_ABANDONED", "day": day.isoformat(),
                              "run_id": prev.get("run_id")}), file=log, flush=True)
            return 3                                     # a dead RUNNING day is never re-run automatically
        if prev.get("state") == "SUCCESS" or (prev.get("state") == "RUNNING" and _live(prev.get("pid", -1))):
            print(json.dumps({"forward_runner": "REFUSED_DUPLICATE", "day": day.isoformat(), "existing": prev["state"],
                              "run_id": prev.get("run_id")}), file=log, flush=True)
            return 3
        if prev.get("state") in ("FAILED", "PARTIAL") or prev.get("reconstructed_from_log"):
            print(json.dumps({"forward_runner": "REFUSED_ALREADY_ATTEMPTED", "day": day.isoformat(),
                              "existing": prev.get("state")}), file=log, flush=True)
            return 3
    start = now_fn()
    wall_start = time.time()                         # artifact mtimes are wall-clock: compare against wall time
    end_of_day = datetime.combine(day, datetime.min.time()).astimezone() + timedelta(hours=23, minutes=30)
    deadline = min(start + timedelta(seconds=budget_s), end_of_day.astimezone(UTC))
    py = py or sys.executable
    crawl_end = (start.astimezone(UTC) - timedelta(days=1)).date()  # as forward_daily.sh: UTC yesterday
    cutoffs = {"as_of": day.isoformat(), "info_cutoff_filing_date_max": crawl_end.isoformat(),
               "price_end_last_completed_session": (day - timedelta(days=1)).isoformat(),
               "basis": "date-based study contract; deadline is an execution bound only"}
    st = stage_list or stages(py, crawl_end)
    rec = {"run_id": f"{start:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}", "day": day.isoformat(), "cutoffs": cutoffs,
           "scheduled_utc": scheduled, "started_utc": iso(start), "ended_utc": None, "deadline_utc": iso(deadline),
           "state": "RUNNING", "pid": os.getpid(), "heartbeat_utc": iso(start), "failed_stage": None,
           "error_class": None, "artifact": None, "runner_version": RUNNER_VERSION,
           "stages": [{"name": n, "state": "PENDING"} for n, _, _ in st]}
    executed: list[str] = []                             # stages actually launched (not merely marked)

    def persist(boundary: str) -> bool:
        try:
            hist = write_atomic(rec_path, rec, deadline=deadline, now_fn=now_fn)   # the run's own clock
        except StatusPersistenceError as exc:
            _write_diagnostic(rec, boundary, exc, executed, log)
            return False
        if hist:                                         # recorded in the NEXT persisted write (honest ordering)
            rec.setdefault("persistence_retries", []).append({"boundary": boundary, "attempts": hist,
                                                              "at_utc": iso(now_fn())})
            print(json.dumps({"forward_runner": "STATUS_WRITE_RETRIED", "run_id": rec["run_id"], "boundary": boundary,
                              "attempts": len(hist) + 1}), file=log, flush=True)
        return True

    if not persist("START"):
        return 4
    print(json.dumps({"forward_runner": "START", "run_id": rec["run_id"], "day": rec["day"],
                      "deadline_utc": rec["deadline_utc"], "cutoffs": cutoffs}), file=log, flush=True)
    if cutoffs["info_cutoff_filing_date_max"] != cutoffs["price_end_last_completed_session"]:
        rec.update(state="FAILED", error_class="CUTOFF_DATE_MISMATCH", ended_utc=iso(now_fn()),
                   failed_stage=st[0][0] if st else None)
        for s in rec["stages"]:
            s["state"] = "NOT_RUN"
        if not persist("END:CUTOFF_DATE_MISMATCH"):
            return 4
        print(json.dumps({"forward_runner": "END", "run_id": rec["run_id"], "state": "FAILED",
                          "error_class": "CUTOFF_DATE_MISMATCH"}), file=log, flush=True)
        return 1
    completed = 0
    for i, (name, cmd, keep_stdout) in enumerate(st):
        s = rec["stages"][i]
        t0 = now_fn()
        s.update(state="RUNNING", started_utc=iso(t0), cmd=" ".join(cmd[2:]) if len(cmd) > 2 else " ".join(cmd))
        rec["heartbeat_utc"] = iso(t0)
        if not persist(f"BEFORE_STAGE:{name}"):          # a stage is never entered unrecorded
            return 4
        executed.append(name)
        err_path = RUNS / f"{day.isoformat()}.{rec['run_id']}.{name}.stderr.log"
        env = dict(os.environ, **{DEADLINE_ENV: str(deadline.timestamp()), "PYTHONIOENCODING": "utf-8",
                                  "TALONX_FWD_RUN_ID": rec["run_id"], "TALONX_FWD_AS_OF": cutoffs["as_of"],
                                  "TALONX_FWD_INFO_CUTOFF": cutoffs["info_cutoff_filing_date_max"],
                                  "TALONX_FWD_PRICE_END": cutoffs["price_end_last_completed_session"]})
        remaining = (deadline - now_fn()).total_seconds()
        try:
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, 0)
            with err_path.open("w", encoding="utf-8") as ef:
                p = subprocess.run(cmd, cwd=REPO, env=env, stdout=log if keep_stdout else subprocess.DEVNULL,
                                   stderr=ef, timeout=remaining)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = None
        stderr = err_path.read_text(encoding="utf-8", errors="replace") if err_path.exists() else ""
        s.update(ended_utc=iso(now_fn()), exit_code=rc, stderr_log=str(err_path.relative_to(REPO)),
                 retries=stderr.count('"outcome": "RETRY"'))
        crawl_problem = None
        if name == "edgar_crawl":
            crawl_problem = _crawl_status_problem(rec["run_id"], crawl_end, s)
        if rc == 0 and crawl_problem is None:
            s["state"] = "SUCCESS"
            completed += 1
            if not persist(f"AFTER_STAGE:{name}"):       # completed stage is never repeated; stop here
                return 4
            continue
        s["state"] = "TIMEOUT" if rc is None else "FAILED"
        s["error_class"] = "STAGE_DEADLINE" if rc is None else (crawl_problem or error_class(stderr))
        s["error"] = "stopped at the run deadline" if rc is None else (
            sanitize(s.get("acquisition", {}).get("error") or "") or sanitize(stderr) or crawl_problem)
        rec.update(failed_stage=name, error_class=s["error_class"])
        for later in rec["stages"][i + 1:]:
            later["state"] = "NOT_RUN"
        break
    if rec["failed_stage"] is None:
        ok, why = validate_artifact(day, not_before=wall_start - 1)
        rec["artifact"] = {"path": f"results/v2_validation/forward/{day.isoformat()}.json", "validated": ok,
                           "problems": why}
        rec["state"] = "SUCCESS" if ok else "FAILED"
        if not ok:
            rec["error_class"] = "ARTIFACT_INVALID"
    else:
        rec["artifact"] = {"path": f"results/v2_validation/forward/{day.isoformat()}.json", "validated": False,
                           "problems": ["NOT_PRODUCED_BY_THIS_RUN"]}
        rec["state"] = "PARTIAL" if completed > 0 else "FAILED"
    rec["ended_utc"] = iso(now_fn())
    if not persist(f"END:{rec['state']}"):
        return 4
    print(json.dumps({"forward_runner": "END", "run_id": rec["run_id"], "day": rec["day"], "state": rec["state"],
                      "failed_stage": rec["failed_stage"], "error_class": rec["error_class"]}), file=log, flush=True)
    return {"SUCCESS": 0, "PARTIAL": 2}.get(rec["state"], 1)


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "run"
    if cmd == "run":
        sched = argv[argv.index("--scheduled") + 1] if "--scheduled" in argv else None
        return run(scheduled=sched)
    if cmd == "next-slot":
        print(iso(next_slot(datetime.now(UTC))))
        return 0
    if cmd == "sleep-to-next-slot":
        t = next_slot(datetime.now(UTC))
        while (left := (t - datetime.now(UTC)).total_seconds()) > 0:
            time.sleep(min(left, 300))
        return 0
    raise SystemExit(f"unknown command {cmd!r}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
