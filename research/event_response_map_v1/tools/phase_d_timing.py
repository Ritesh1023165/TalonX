"""Full-scale Phase D TIMING (NOT part of the design lock; owner-approved step 3 before the one allowed re-execution).

Runs the REAL lock-rev-3.2 ``phase_d.stage_run`` on the REAL archive with:
  * REAL event extraction (8-K / Form 4 dated attribution, gaps, NO_EVENT sampling) -> timed, COUNTS only;
  * ``events.outcomes`` fed SYNTHETIC prices (same symbols / dates / event rows, random open/close) -> the outcome
    computation, the 390-cell bootstrap and the survivorship pass run at the real counts on FAKE returns;
  * outputs written to a TEMP dir (no marker in the real results dir), nothing containing returns is kept;
  * the guard's checks stay active; only a 'timing_run' audit event is recorded (no phase_d_run_complete);
  * every socket connect is refused (the archive is complete; anything else fails loudly).
Prints one JSON summary: per-stage durations (from the progress lines) and event counts.
"""
from __future__ import annotations

import io
import json
import socket
import sys
import tempfile
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main() -> None:
    def _no_net(*a, **k):
        raise RuntimeError("NETWORK_REFUSED (timing run)")
    socket.socket.connect = _no_net
    import numpy as np
    from research.common import locked_range_guard as G
    from research.event_response_map_v1 import phase_d as P
    out_tmp = Path(tempfile.mkdtemp(prefix="erm_timing_"))
    P.OUT = out_tmp                                       # outputs + run-once marker go to a temp dir only

    class _Guard(G.LockedRangeGuard):                     # checks unchanged; no run-complete record
        def record(self, event):
            if event.get("event") in ("phase_d_run_complete",):
                return
            super().record(event)
    P.LockedRangeGuard = _Guard
    _Guard(G.EVENT_RESPONSE_MAP_V1).record({"event": "timing_run",
                                            "note": "real event extraction + SYNTHETIC outcomes; outputs to temp"})
    rng = np.random.default_rng(1)
    real_outcomes = P.E.outcomes
    counts = {}

    def fake(df):
        f = df.copy()
        n = len(f)
        f["open"] = 50.0 * np.exp(rng.normal(0, 0.3, n))
        f["close"] = f["open"].to_numpy() * (1 + rng.normal(0, 0.02, n))
        return f

    def outcomes(ev, bars, bench, bench_of, sessions, **k):
        counts.setdefault("outcome_calls", []).append({"events": len(ev), "bars": len(bars),
                                                       "by_type": ev["event_type"].value_counts().to_dict()})
        return real_outcomes(ev, fake(bars), {b: fake(v) for b, v in bench.items()}, bench_of, sessions, **k)
    P.E.outcomes = outcomes
    real_out = ROOT / "results" / "event_response_map_v1"
    cand = json.loads((real_out / "candidates.json").read_text())
    cand["r3"] = json.loads((real_out / "candidates_r3.json").read_text())
    buf = io.StringIO()

    class Tee(io.TextIOBase):
        def write(self, s):
            sys.__stdout__.write(s)
            sys.__stdout__.flush()
            buf.write(s)
            return len(s)
    t0 = time.time()
    with redirect_stdout(Tee()):
        P.stage_run(cand)
    total = time.time() - t0
    lines = [json.loads(x) for x in buf.getvalue().splitlines() if x.startswith("{")]
    stages, prev = [], datetime.fromtimestamp(t0).astimezone()
    for ln in lines:
        t = datetime.fromisoformat(ln["utc"].replace("Z", "+00:00"))
        stages.append({"stage": ln["stage"], "end_utc": ln["utc"], "seconds_since_prev": round((t - prev).total_seconds()),
                       **{k: v for k, v in ln.items() if k not in ("utc", "stage")}})
        prev = t
    summary = {"total_seconds": round(total), "stages": stages, "outcome_inputs": counts.get("outcome_calls"),
               "outputs_dir_temp": str(out_tmp), "note": "synthetic outcomes; temp outputs deleted below"}
    import shutil
    shutil.rmtree(out_tmp, ignore_errors=True)            # nothing containing (fake) returns is kept
    print("TIMING_SUMMARY " + json.dumps(summary, default=str))


if __name__ == "__main__":
    main()
