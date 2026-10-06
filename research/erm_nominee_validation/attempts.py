"""ERM nominee validation -- attempt budget (owner decision D6 / D6a, recorded 2026-10-06).

D6a, exact policy:
  1. An acquisition blockage before any outcome has been computed, persisted, displayed or otherwise exposed does NOT
     consume the single statistical scoring run.
  2. At most ONE acquisition retry under the same locked rules and approved scope (at most two executions in total;
     every execution acquires afresh into its own archive).
  3. The retry needs an explicit, recorded reason. Requests, retrieved data and exposure of every attempt are preserved
     (the attempt's archive ledger, events and quarantine move to attempt_<n>/ and are never deleted).
  4. The budget lives in ONE ledger per hypothesis and window, outside any run directory: a new run id, a renamed
     directory or a restarted process cannot reset it.
  5. No retry of any kind once outcomes may exist (a SCORING_STARTED event exists): the owner decides.
  6. A second failure (of any class) before outcomes stops for owner review.
  7. Separate counters: acquisition_attempts (executions started) and scoring_attempts (OUTCOMES stage entered;
     maximum one, ever).
  8. Reference date: an execution whose acquisition would fall outside the authorised envelope (retrieval after R + 1
     day) is refused BEFORE it starts and consumes nothing; R is never re-pinned and access is never widened -- a
     separate scope decision (new release) is required.
A request-level transport retry (transport.HttpTransport / RetryingTransport: bounded 4 attempts, 2/4/8 s backoff,
Retry-After <= 60 s) is NOT an acquisition attempt: it happens inside one execution and is recorded per request in the
archive ledger (`attempts`).
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MAX_EXECUTIONS = 2                 # first execution + at most one acquisition retry
MAX_SCORING_ATTEMPTS = 1


class AttemptRefused(RuntimeError):
    pass


class AttemptLedger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _events(self, key: str) -> list:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                if e.get("key") == key:
                    out.append(e)
        return out

    def append(self, key: str, event: str, **kw) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"key": key, "event": event, "utc": datetime.now(timezone.utc).isoformat(), **kw}
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return rec

    def counters(self, key: str) -> dict:
        ev = self._events(key)
        starts = [e for e in ev if e["event"] == "EXECUTION_STARTED"]
        return {"acquisition_attempts": len(starts),
                "scoring_attempts": sum(1 for e in ev if e["event"] == "SCORING_STARTED"),
                "completed": any(e["event"] == "RUN_COMPLETE" for e in ev),
                "failures": [e for e in ev if e["event"] == "EXECUTION_FAILED"],
                "last_start": starts[-1] if starts else None}

    def admit(self, key: str, *, retry_reason: str | None, today: date, reference_date: date | None,
              retrieval_window_days: int) -> dict:
        """Decide whether a new execution may start. Refusals consume nothing and write only a REFUSED event."""
        c = self.counters(key)

        def refuse(why):
            self.append(key, "EXECUTION_REFUSED", reason=why, retry_reason=retry_reason)
            raise AttemptRefused(why)
        if c["completed"]:
            refuse("a completed run exists for this hypothesis and window")
        if c["scoring_attempts"] >= MAX_SCORING_ATTEMPTS:
            refuse("outcomes may exist (scoring started): no retry of any kind; owner decides")
        if reference_date is not None and today > reference_date + timedelta(days=retrieval_window_days):
            refuse(f"REFERENCE_WINDOW_EXPIRED: today {today} is after the authorised reference date {reference_date} "
                   f"+ {retrieval_window_days} d; a separate scope decision (new release) is required -- R is never "
                   f"re-pinned")
        n = c["acquisition_attempts"]
        if n >= MAX_EXECUTIONS:
            refuse("second failure before outcomes already recorded: stopped for owner review")
        if n == 1:
            if not (retry_reason and retry_reason.strip()):
                refuse("the single acquisition retry needs an explicit, recorded reason")
            last_fail = c["failures"][-1] if c["failures"] else None
            if last_fail and last_fail.get("outcome_exposure"):
                refuse("the previous execution failed after outcome exposure: no retry")
        return {"execution_no": n + 1, "acquisition_attempts_before": n, "scoring_attempts": c["scoring_attempts"],
                "previous_failure": (c["failures"][-1] if c["failures"] else
                                     ("INTERRUPTED_BEFORE_OUTCOMES" if n else None))}
