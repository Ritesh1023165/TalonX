"""POST_DELIVERY_ALERT_MARKOUT_V1 -- full-calendar processing-capacity ESTIMATE for the one- vs two-trigger schedule.

Synthetic only: synthetic deliveries, mock HTTP transport, simulated clock. No real market data, no real alerts,
no returns. Extends capacity_estimate.py (which measured one isolated run) by driving the REAL post_delivery_markout.run()
-- deadline reconciliation, registration, first-per-symbol selection, processing order, acquire(), restarts -- over the
approved 20-session calendar with every scheduled trigger at its actual UTC instant, a persistent study store across
invocations, and a fresh AlpacaAcquirer (900 s budget, 40/min pacing, 2 retries, <= 5 quote pages) per invocation.

Not modelled (disclosed): real provider latency variance (fixed 0.3 s per request), provider-side 429s, machine
sleep/late starts (StartWhenAvailable), trace-policy exclusions (all synthetic deliveries are clean), and SQLite speed of
the production disk (the store runs with synchronous=OFF here; local work before the first request does not consume
the 900 s budget because the acquirer is created lazily at the first request; local wall time is measured and reported).

usage: python docs/research/protocols/pdm_v1_scheduler/capacity_two_triggers.py [--quick] > out.json
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
import tempfile
import time as wall
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from talonx_paperperf import post_delivery_acquisition as Q  # noqa: E402
from talonx_paperperf import post_delivery_collector as C  # noqa: E402
from talonx_paperperf import post_delivery_markout as M  # noqa: E402

UTC = timezone.utc
FIRST, LAST_T1, LAST_T2 = date(2026, 10, 20), date(2026, 11, 18), date(2026, 11, 17)   # task trigger boundaries
TRANSPORT = {"clean_1_quote_page": (1, 0.0), "2_quote_pages": (2, 0.0), "5pct_transient_5xx": (1, 0.05),
             "2_quote_pages_and_5pct_5xx": (2, 0.05)}
DEMANDS = (133, 170, 203, 205)
MISSED_RUN = datetime(2026, 10, 27, 0, 15, tzinfo=UTC)          # 00:15 London (GMT) after Mon 2026-10-26
MISSED_DAY = date(2026, 11, 4)                                   # both London triggers on Wed 2026-11-04


def triggers(two: bool, miss: str) -> list[datetime]:
    out = []
    d = FIRST
    while d <= LAST_T1:
        for tm in (C.SCHEDULE_LOCAL_TIMES if two else C.SCHEDULE_LOCAL_TIMES[:1]):
            if tm.hour == 6 and d > LAST_T2:
                continue
            s = datetime.combine(d, tm, tzinfo=C.LONDON).astimezone(UTC)
            if miss == "missed_run" and s == MISSED_RUN:
                continue
            if miss == "missed_day" and d == MISSED_DAY:
                continue
            out.append(s)
        d += timedelta(days=1)
    return out


def build_sources(root: Path, demand: int):
    sessions = M.study_sessions(date(2026, 10, 19), 20)
    ob = sqlite3.connect(root / "outbox.db")
    ob.execute("CREATE TABLE ops_notification_outbox (event_id TEXT PRIMARY KEY, destination TEXT, event_type TEXT, "
               "producer TEXT, dedup_key TEXT, payload_text TEXT, state TEXT, attempts INT, last_error TEXT, "
               "created_at_utc TEXT, updated_at_utc TEXT, sent_at_utc TEXT)")
    pc = sqlite3.connect(root / "promotion.db")
    pc.execute("CREATE TABLE promotions (promotion_id TEXT, symbol TEXT, window_id TEXT, state TEXT, reason_code TEXT, "
               "policy_fp TEXT, signal_event_id TEXT)")
    for w in sessions:
        lo, hi = w.open_utc + timedelta(minutes=2), w.close_utc - timedelta(minutes=45)
        for i in range(demand):
            a = lo + (hi - lo) * (i / max(demand - 1, 1))
            assert M.targets(a)["eligible"], a
            eid = f"SIM:{w.window_id}:S{i:04d}"
            ob.execute("INSERT INTO ops_notification_outbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (eid, "TRADE_EVENT", M.EVENT_TYPE, "sim", eid, "synthetic", "SENT", 1, None,
                        (a - timedelta(seconds=1)).isoformat(), a.isoformat(), a.isoformat()))
            pc.execute("INSERT INTO promotions VALUES (?,?,?,?,?,?,?)",
                       (eid, f"S{i:04d}", w.window_id, "PROMOTED_SIGNAL", M.REVIEW_REASON, "PFP", eid))
    ob.commit()
    pc.commit()
    return root / "outbox.db", root / "promotion.db"


class SimClock:
    def __init__(self):
        self.t = 0.0

    def mono(self):
        return self.t

    def sleep(self, s):
        self.t += s


def mock_http(clock, quote_pages, fail_rate, rng, latency_s=0.3):
    def http(url, params, headers, timeout):
        clock.t += latency_s
        if rng.random() < fail_rate:
            return 503, b"synthetic"
        sym = params["symbols"]
        if "bars" in url:
            return 200, json.dumps({"bars": {sym: [{"t": params["start"], "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]},
                                    "next_page_token": None}).encode()
        page = 2 if params.get("page_token") else 1
        last = page >= quote_pages
        q = [{"t": params["end"], "bp": 1.0, "ap": 1.01}] if last else []
        return 200, json.dumps({"quotes": {sym: q}, "next_page_token": None if last else "tok"}).encode()
    return http


class FastStore(M.Store):
    def __init__(self, root):
        super().__init__(root)
        self.con.execute("PRAGMA synchronous=OFF")


def simulate(args):
    transport, demand, two, miss = args
    pages, fail = TRANSPORT[transport]
    rng = random.Random(f"{transport}:{demand}:{two}:{miss}")
    M.Store = FastStore                                          # simulation-only speed-up (same schema/logic)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        root = Path(d)
        ob, pc = build_sources(root, demand)
        act = root / "act.json"
        act.write_text(json.dumps({
            "approved": True, "approved_by": "simulation", "approved_utc": "2026-10-09T00:00:00Z",
            "protocol_fingerprint": M.PDM_V1.fingerprint(), "first_session": "2026-10-19",
            "delivery_trace_policy": "NOT_AVAILABLE_ACCEPTED", "implementation_sha256": {}}), encoding="utf-8")
        env = {M.ENABLE_ENV: "1", M.CONFIG_ENV: str(act)}
        max_backlog, max_wall, runs, stops, max_due = (0, None), 0.0, 0, {"budget": 0, "limit": 0}, 0
        for now in triggers(two, miss):
            clock = SimClock()
            acq = Q.AlpacaAcquirer(headers={}, http=mock_http(clock, pages, fail, rng),
                                   clock=lambda now=now, clock=clock: now + timedelta(seconds=clock.t),
                                   sleep=clock.sleep, monotonic=clock.mono, budget_s=900)
            t0 = wall.perf_counter()
            out = M.run(env, store_root=root / "pdm", acquirer=acq, now=now, outbox_path=ob, promotion_path=pc,
                        max_observations=200)
            max_wall = max(max_wall, wall.perf_counter() - t0)
            runs += 1
            a = out.get("acquisition") or {}
            max_due = max(max_due, a.get("due") or 0)
            stops["budget"] += bool(a.get("budget_exhausted"))
            stops["limit"] += bool(a.get("deferred")) and not a.get("budget_exhausted")
            s = M.Store(root / "pdm")
            bl = s.con.execute("SELECT COUNT(*) FROM observations WHERE state=? AND matures_utc<=?",
                               (M.SELECTED_WAITING, M.iso(now))).fetchone()[0]
            if bl > max_backlog[0]:
                max_backlog = (bl, now.isoformat())
            s.con.close()
        s = M.Store(root / "pdm")
        st = dict(s.con.execute("SELECT state, COUNT(*) FROM observations GROUP BY state").fetchall())
        first_try = {r[0]: r[1] for r in s.con.execute(
            "SELECT obs_id, MIN(at) FROM (SELECT obs_id, retrieved_utc AS at FROM inputs UNION ALL "
            "SELECT obs_id, at_utc AS at FROM acquisition_errors) GROUP BY obs_id")}
        ages, exp_attempted, exp_unattempted = [], 0, 0
        for o in s.q("SELECT obs_id, state, matures_utc, terminal_utc, attempts FROM observations"):
            if o["state"] == M.MEASURED:
                ages.append((M.ts(o["terminal_utc"]) - M.ts(o["matures_utc"])).total_seconds() / 3600)
            elif o["state"] == M.EXPIRED:
                if o["obs_id"] in first_try:
                    exp_attempted += 1
                else:
                    exp_unattempted += 1
        exp_by_session = dict(s.con.execute("SELECT session, COUNT(*) FROM observations WHERE state=? GROUP BY session",
                                            (M.EXPIRED,)).fetchall())
        s.con.close()
    return {"transport": transport, "demand_per_session": demand, "schedule": "two_triggers" if two else "one_trigger",
            "missed": miss, "invocations": runs, "selected": demand * 20, "states": st,
            "acquired_measured": st.get(M.MEASURED, 0), "expired": st.get(M.EXPIRED, 0),
            "expired_attempted": exp_attempted, "expired_never_attempted": exp_unattempted,
            "expired_by_session": exp_by_session, "max_due_at_a_trigger": max_due,
            "max_matured_backlog_after_a_run": max_backlog[0],
            "max_backlog_at_utc": max_backlog[1],
            "max_maturity_to_measured_h": round(max(ages), 1) if ages else None,
            "runs_stopped_by_time_budget": stops["budget"], "runs_stopped_by_200_limit": stops["limit"],
            "max_local_wall_s_per_invocation": round(max_wall, 2)}


def main(argv):
    quick = "--quick" in argv
    jobs = []
    for tr in TRANSPORT:
        for dm in DEMANDS:
            jobs.append((tr, dm, False, "none"))
            for miss in ("none", "missed_run", "missed_day"):
                jobs.append((tr, dm, True, miss))
    if quick:
        jobs = jobs[:2]
    with ProcessPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(simulate, jobs))
    print(json.dumps({"label": "ESTIMATE (synthetic deliveries, mock transport, simulated clock; not a provider "
                               "measurement; doubling triggers does not guarantee complete coverage)",
                      "assumptions": {"budget_s": 900, "provider_rate_per_min": 40, "retries": 2, "max_quote_pages": 5,
                                      "max_observations_per_run": 200, "latency_s_per_request": 0.3,
                                      "missed_run_utc": MISSED_RUN.isoformat(),
                                      "missed_day_london": MISSED_DAY.isoformat(),
                                      "trigger_window": "00:15 London 2026-10-20..2026-11-18; 06:30 London "
                                                        "2026-10-20..2026-11-17"},
                      "results": res}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
