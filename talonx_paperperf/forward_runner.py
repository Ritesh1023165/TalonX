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
Exit codes: 0 SUCCESS, 2 PARTIAL, 1 FAILED, 3 refused (duplicate). usage:
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


def write_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


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
        prev = json.loads(rec_path.read_text(encoding="utf-8"))
        if prev.get("state") == "SUCCESS" or (prev.get("state") == "RUNNING" and _live(prev.get("pid", -1))):
            print(json.dumps({"forward_runner": "REFUSED_DUPLICATE", "day": day.isoformat(), "existing": prev["state"],
                              "run_id": prev.get("run_id")}), file=log, flush=True)
            return 3
        if prev.get("state") in ("FAILED", "PARTIAL") or prev.get("reconstructed_from_log"):
            print(json.dumps({"forward_runner": "REFUSED_ALREADY_ATTEMPTED", "day": day.isoformat(),
                              "existing": prev.get("state")}), file=log, flush=True)
            return 3
    start = now_fn()
    end_of_day = datetime.combine(day, datetime.min.time()).astimezone() + timedelta(hours=23, minutes=30)
    deadline = min(start + timedelta(seconds=budget_s), end_of_day.astimezone(UTC))
    py = py or sys.executable
    crawl_end = (start.astimezone(UTC) - timedelta(days=1)).date()  # as forward_daily.sh: UTC yesterday
    st = stage_list or stages(py, crawl_end)
    rec = {"run_id": f"{start:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}", "day": day.isoformat(),
           "scheduled_utc": scheduled, "started_utc": iso(start), "ended_utc": None, "deadline_utc": iso(deadline),
           "state": "RUNNING", "pid": os.getpid(), "heartbeat_utc": iso(start), "failed_stage": None,
           "error_class": None, "artifact": None, "runner_version": "forward_runner v1 (2026-10-05)",
           "stages": [{"name": n, "state": "PENDING"} for n, _, _ in st]}
    write_atomic(rec_path, rec)
    print(json.dumps({"forward_runner": "START", "run_id": rec["run_id"], "day": rec["day"],
                      "deadline_utc": rec["deadline_utc"]}), file=log, flush=True)
    completed = 0
    for i, (name, cmd, keep_stdout) in enumerate(st):
        s = rec["stages"][i]
        t0 = now_fn()
        s.update(state="RUNNING", started_utc=iso(t0), cmd=" ".join(cmd[2:]) if len(cmd) > 2 else " ".join(cmd))
        rec["heartbeat_utc"] = iso(t0)
        write_atomic(rec_path, rec)
        err_path = RUNS / f"{day.isoformat()}.{rec['run_id']}.{name}.stderr.log"
        env = dict(os.environ, **{DEADLINE_ENV: str(deadline.timestamp()), "PYTHONIOENCODING": "utf-8"})
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
        if rc == 0:
            s["state"] = "SUCCESS"
            completed += 1
            write_atomic(rec_path, rec)
            continue
        s["state"] = "TIMEOUT" if rc is None else "FAILED"
        s["error_class"] = "STAGE_DEADLINE" if rc is None else error_class(stderr)
        s["error"] = "stopped at the run deadline" if rc is None else sanitize(stderr)
        rec.update(failed_stage=name, error_class=s["error_class"])
        for later in rec["stages"][i + 1:]:
            later["state"] = "NOT_RUN"
        break
    if rec["failed_stage"] is None:
        ok, why = validate_artifact(day, not_before=start.timestamp() - 1)
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
    write_atomic(rec_path, rec)
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
