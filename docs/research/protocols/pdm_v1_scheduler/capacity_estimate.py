"""POST_DELIVERY_ALERT_MARKOUT_V1 processing-capacity ESTIMATE (synthetic; no real data is fetched or read).

Part A drives the REAL acquire() + AlpacaAcquirer pacing/retry/budget code with a simulated clock and a mock transport,
to measure observations completed in one 900 s run under stated transport assumptions.
Part B replays the approved 20-session calendar and the daily 00:15 London schedule with earliest-deadline-first
batching, using per-session demand levels supplied on the command line (counts only), and reports expiries
caused purely by processing capacity.

usage: python docs/research/protocols/pdm_v1_scheduler/capacity_estimate.py [demand ...]
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from talonx_paperperf import post_delivery_acquisition as Q  # noqa: E402
from talonx_paperperf import post_delivery_collector as C  # noqa: E402
from talonx_paperperf import post_delivery_markout as M  # noqa: E402

UTC = timezone.utc


class SimClock:
    def __init__(self):
        self.t = 0.0

    def mono(self):
        return self.t

    def sleep(self, s):
        self.t += s


def mock_http(clock, *, latency_s, quote_pages, fail_rate, rng):
    def http(url, params, headers, timeout):
        clock.t += latency_s
        if rng.random() < fail_rate:
            return 503, b"synthetic"
        sym = params["symbols"]
        if "bars" in url:
            return 200, json.dumps({"bars": {sym: [{"t": params["start"], "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]},
                                    "next_page_token": None}).encode()
        page = 1 + (1 if params.get("page_token") else 0)
        last = page >= quote_pages
        q = [{"t": params["end"], "bp": 1.0, "ap": 1.01}] if last else []
        return 200, json.dumps({"quotes": {sym: q}, "next_page_token": None if last else "tok"}).encode()
    return http


def seed(store, n, now):
    anchor = now - timedelta(hours=8)
    with store.con:
        for i in range(n):
            tg = M.targets(anchor)
            store.con.execute(
                "INSERT INTO observations (obs_id, event_id, symbol, session, segment, protocol_fp, state, reason, "
                "anchor_utc, entry_utc, exit_utc, matures_utc, deadline_utc, cost_state, created_utc, updated_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"o{i}", f"e{i}", f"S{i:04d}", "s", "seg", M.PDM_V1.fingerprint(), M.SELECTED_WAITING, "",
                 M.iso(anchor), M.iso(tg["entry_utc"]), M.iso(tg["exit_utc"]), M.iso(now - timedelta(hours=1)),
                 M.iso(now + timedelta(days=1)), M.COST_PENDING, M.iso(now), M.iso(now)))


def per_run(*, budget_s=900, latency_s=0.3, quote_pages=1, fail_rate=0.0, limit=200, n=400, seed_=7):
    clock, rng = SimClock(), random.Random(seed_)
    now = datetime(2026, 10, 20, 23, 15, tzinfo=UTC)
    acq = Q.AlpacaAcquirer(headers={}, http=mock_http(clock, latency_s=latency_s, quote_pages=quote_pages,
                                                      fail_rate=fail_rate, rng=rng),
                           clock=lambda: now, sleep=clock.sleep, monotonic=clock.mono, budget_s=budget_s)
    with tempfile.TemporaryDirectory() as d:
        store = M.Store(Path(d) / "s")
        seed(store, n, now)
        out = M.acquire(store, acq, now, max_observations=limit)
        measured = store.con.execute("SELECT COUNT(*) FROM observations WHERE state=?", (M.MEASURED,)).fetchone()[0]
        store.con.close()
    return {"processed": out["processed"], "measured": measured, "requests": acq.requests,
            "deferred": out["deferred"], "budget_exhausted": out["budget_exhausted"], "sim_elapsed_s": round(clock.t)}


def calendar_backlog(demand: int, capacity: int):
    """EDF over the approved sessions; runs at 00:15 London daily; deadline = 2nd subsequent close + 60 min."""
    sessions = M.study_sessions(date(2026, 10, 19), 20)
    queue, expired, measured = [], 0, 0                       # entries: [deadline, remaining]
    d = date(2026, 10, 19)
    while d <= date(2026, 11, 18):
        run = datetime.combine(d, C.SCHEDULE_LOCAL, tzinfo=C.LONDON).astimezone(UTC)
        expired += sum(r for dl, r in queue if dl <= run)
        queue = [[dl, r] for dl, r in queue if dl > run]
        for w in sessions:
            if M.maturity(w) <= run and w.close_utc > run - timedelta(days=1) and w.close_utc <= run:
                queue.append([M.deadline(w), demand])
        queue.sort()
        cap = capacity
        for q in queue:
            take = min(cap, q[1])
            q[1] -= take
            cap -= take
            measured += take
        queue = [q for q in queue if q[1] > 0]
        d += timedelta(days=1)
    expired += sum(r for _, r in queue)
    return {"demand_per_session": demand, "capacity_per_run": capacity, "attempted": measured,
            "expired_unprocessed": expired, "total": demand * 20}


def main(argv):
    demands = [int(a) for a in argv] or [130, 170, 205, 250]
    scen = {
        "clean_1_quote_page": per_run(),
        "2_quote_pages": per_run(quote_pages=2),
        "5pct_transient_5xx": per_run(fail_rate=0.05),
        "2_quote_pages_and_5pct_5xx": per_run(quote_pages=2, fail_rate=0.05),
    }
    caps = sorted({v["processed"] for v in scen.values()})
    out = {"label": "ESTIMATE (synthetic transport; not a measurement of the provider)",
           "assumptions": {"budget_s": 900, "provider_rate_per_min": 40, "retries": 2, "max_quote_pages": 5,
                           "latency_s": 0.3, "max_observations_per_run": 200},
           "per_run": scen,
           "calendar": {str(c): [calendar_backlog(dm, c) for dm in demands] for c in caps}}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
