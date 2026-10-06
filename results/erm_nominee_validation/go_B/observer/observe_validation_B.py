"""READ-ONLY observer for the single ERM nominee validation run, window B (owner GO 2026-10-06).

Reads ONLY operational evidence and writes ONLY into this observer directory:
  * Task Scheduler state of ERM_NOMINEE_VALIDATION_B_GO_2026-10-06 (schtasks /query, read-only)
  * go_B/launcher.log, go_B/LAUNCHED.lock, sizes / mtimes of go_B/run.out.log and run.err.log
  * the attempt ledger (event names and counters only) and the release journal (states only)
  * validation_B/run_record.json: status, stages_done, failed_stage, failure_class, outcome_exposure, attempt fields
  * validation_B/archive/acquisition/acquisition_status.json: stage / complete / per-category state counts
  * validation_B/archive/acquisition/ledger.jsonl: line count, last category, mtime (progress only)
  * existence (never contents) of RUN_COMPLETE.json, report.md, gates.json, obs.csv
It never starts, retries, stops or restarts anything, makes no network request, computes no outcome, does not open
obs.csv / gates.json / diagnostics.json / report.md / manifest.csv, writes nothing outside go_B/observer/, and sends no
message. One poll every POLL_S until a terminal state or the hard deadline (bounded; no indefinite polling).

  python observe_validation_B.py            durable mode (scheduled task)
  python observe_validation_B.py --once --out DIR     one poll into DIR (dry check)
"""
import argparse
import csv
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\workspace\TalonX-erm-val")
R = ROOT / "results/erm_nominee_validation"
GO = R / "go_B"
RUN = R / "validation_B"
TASK = "ERM_NOMINEE_VALIDATION_B_GO_2026-10-06"
LAUNCH_LATEST_UTC = datetime(2026, 10, 6, 23, 30, tzinfo=timezone.utc)
DEADLINE_UTC = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)      # after the task's latest possible 15 h limit
POLL_S = 300
TERMINAL_RUN = ("COMPLETE", "ABORTED_OWNER_DECIDES")


def now():
    return datetime.now(timezone.utc)


def mtime(p: Path):
    return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat() if p.exists() else None


def task_state():
    try:
        out = subprocess.run(["schtasks", "/query", "/tn", TASK, "/v", "/fo", "csv"], capture_output=True, text=True,
                             timeout=60).stdout
        row = next(csv.DictReader(io.StringIO(out)))
        return {k: row.get(k) for k in ("Status", "Next Run Time", "Last Run Time", "Last Result")}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:200]}


def jsonl(p: Path):
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def snapshot():
    s = {"observed_utc": now().isoformat(), "task": task_state()}
    lg = GO / "launcher.log"
    lines = lg.read_text(encoding="utf-8-sig", errors="replace").splitlines() if lg.exists() else []
    s["launcher"] = {"launched_lock": (GO / "LAUNCHED.lock").exists(), "lock_created_utc": mtime(GO / "LAUNCHED.lock"),
                     "log_lines": lines[-6:],
                     "start_line": next((l for l in lines if " START:" in l), None),
                     "end_line": next((l for l in lines if " END:" in l), None),
                     "refused_line": next((l for l in lines if " REFUSED:" in l), None)}
    s["logs"] = {n: {"bytes": (GO / n).stat().st_size if (GO / n).exists() else None, "mtime": mtime(GO / n)}
                 for n in ("run.out.log", "run.err.log", "lock_verify_prerun.json")}
    led = jsonl(R / "ATTEMPT_LEDGER.jsonl")
    s["attempt_ledger"] = {"events": [e.get("event") for e in led],
                           "acquisition_attempts": sum(1 for e in led if e.get("event") == "EXECUTION_STARTED"),
                           "scoring_attempts": sum(1 for e in led if e.get("event") == "SCORING_STARTED"),
                           "failures": [{k: e.get(k) for k in ("stage", "failure_class", "outcome_exposure", "utc")}
                                        for e in led if e.get("event") == "EXECUTION_FAILED"],
                           "complete": any(e.get("event") == "RUN_COMPLETE" for e in led)}
    s["release_journal"] = [e.get("state") for e in jsonl(R / "guard_release/release_journal.jsonl")]
    rr = RUN / "run_record.json"
    if rr.exists():
        try:
            d = json.loads(rr.read_text(encoding="utf-8"))
            s["run_record"] = {k: d.get(k) for k in ("status", "attempt", "acquisition_attempt", "started_utc", "ended_utc",
                                                     "stages_done", "failed_stage", "failure_class", "outcome_exposure",
                                                     "retry_allowed", "error", "reference_date")}
            s["run_record"]["mtime"] = mtime(rr)
        except ValueError:
            s["run_record"] = {"unreadable_mid_write": True, "mtime": mtime(rr)}
    st = RUN / "archive/acquisition/acquisition_status.json"
    if st.exists():
        try:
            d = json.loads(st.read_text(encoding="utf-8"))
            s["acquisition_status"] = {k: d.get(k) for k in ("stage", "complete", "by_category", "reference_date")}
            s["acquisition_status"]["required_failures"] = [{k: f.get(k) for k in ("category", "state", "detail")}
                                                            for f in d.get("required_failures", [])][:5]
        except ValueError:
            s["acquisition_status"] = {"unreadable_mid_write": True}
    al = RUN / "archive/acquisition/ledger.jsonl"
    if al.exists():
        last = None
        with open(al, "rb") as fh:
            n = 0
            for line in fh:
                n += 1
                last = line
        try:
            lr = json.loads(last) if last else {}
        except ValueError:
            lr = {}
        s["acquisition_ledger"] = {"records": n, "last_category": lr.get("category"), "last_state": lr.get("state"),
                                   "mtime": mtime(al)}
    s["outputs_exist"] = {n: (RUN / n).exists() for n in ("RUN_COMPLETE.json", "report.md", "gates.json", "obs.csv")}
    s["last_progress_utc"] = max([t for t in (mtime(al), mtime(rr), mtime(GO / "run.out.log"), mtime(lg)) if t] or [None],
                                 key=lambda x: x or "")
    s["status"] = classify(s)
    return s


def classify(s):
    rr, la = s.get("run_record") or {}, s["launcher"]
    if s["outputs_exist"]["RUN_COMPLETE.json"] and rr.get("status") == "COMPLETE":
        return "COMPLETED"
    if la["refused_line"] and not la["start_line"]:
        return "LAUNCH_REFUSED_BY_LAUNCHER"
    if rr.get("status", "").startswith("INCOMPLETE_") or rr.get("status") == "ABORTED_OWNER_DECIDES":
        if rr.get("outcome_exposure"):
            return "INCOMPLETE_AFTER_OUTCOME_EXPOSURE"
        return "ACQUISITION_BLOCKED" if rr.get("failure_class") == "ACQUISITION_BLOCKED" else f"FAILED_{rr.get('failure_class')}"
    if la["end_line"]:
        return "LAUNCHER_ENDED_WITHOUT_TERMINAL_RUN_RECORD"
    if la["start_line"] or rr:
        return "RUNNING"
    if now() >= LAUNCH_LATEST_UTC and not la["launched_lock"]:
        return "LAUNCH_MISSED"
    return "ARMED_NOT_LAUNCHED"


TERMINAL = ("COMPLETED", "LAUNCH_REFUSED_BY_LAUNCHER", "INCOMPLETE_AFTER_OUTCOME_EXPOSURE", "ACQUISITION_BLOCKED",
            "LAUNCH_MISSED", "LAUNCHER_ENDED_WITHOUT_TERMINAL_RUN_RECORD")


def write(out: Path, s: dict, prev_status):
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "latest.json.tmp"
    tmp.write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, out / "latest.json")
    with open(out / "status_log.jsonl", "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"utc": s["observed_utc"], "status": s["status"],
                             "stage": (s.get("run_record") or {}).get("status"),
                             "acq_records": (s.get("acquisition_ledger") or {}).get("records"),
                             "last_progress_utc": s["last_progress_utc"],
                             "attempts": [s["attempt_ledger"]["acquisition_attempts"],
                                          s["attempt_ledger"]["scoring_attempts"]]}) + "\n")
    if s["status"] != prev_status:                                   # timestamped snapshot on every state change
        (out / f"status_{s['observed_utc'][:19].replace(':', '')}Z_{s['status']}.json").write_text(
            json.dumps(s, indent=1, default=str), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--out", default=str(GO / "observer"))
    a = ap.parse_args()
    out = Path(a.out)
    if a.once:
        s = snapshot()
        write(out, s, None)
        print(json.dumps({"status": s["status"], "task": s["task"]}, default=str))
        return 0
    out.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(out / "OBSERVER.lock"), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, now().isoformat().encode())
        os.close(fd)
    except FileExistsError:
        print("observer already ran / running: OBSERVER.lock exists"); return 4
    prev = None
    while True:
        s = snapshot()
        if s["status"] not in TERMINAL and now() >= DEADLINE_UTC:
            s["status"] = "RUNNING_AT_OBSERVER_DEADLINE" if s["status"] == "RUNNING" else s["status"] + "_AT_OBSERVER_DEADLINE"
        write(out, s, prev)
        prev = s["status"]
        if prev in TERMINAL or prev.endswith("_AT_OBSERVER_DEADLINE"):
            (out / "FINAL_OBSERVATION.json").write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
            return 0
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
