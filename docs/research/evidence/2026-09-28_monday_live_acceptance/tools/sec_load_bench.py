"""OLD (cf0cffb, idle-gated, I/O under the cache lock) vs NEW (2026-09-28 remediation) SEC refresher, same synthetic
load, real threads, time compressed 1:SCALE. No network, no production process touched.

Load model (fitted to 2026-09-28 live): N active CIKs per scan with 15 % churn per scan; discovery scan = lookups
interleaved with compute (5 s + 0.035 s/lookup -> ~50 s at 1,300); cadence 300 s; TTL 600 s.
OLD network: one request at a time, 0.26 s each (0.21 s spacing + ~0.05 s latency, live fit), under the cache lock.
NEW network: 0.05 s latency per request; starts spaced >= 0.21 s by the global limiter (<= 4.76 req/s).
Harness measures (identically for both): scan duration, served-source counts, served age (raw), stale count,
request rate, discovery lookup wait p99/max (hits and fallbacks), refresher throughput.
usage: python sec_load_bench.py [N ...]"""
import json
import random
import sys
import threading
import time

sys.path.insert(0, r"C:\workspace\TalonX")
sys.path.insert(0, r"C:\workspace\TalonX\results\sec_remediation_2026-09-28")
import sec_refresh_old as OLD  # noqa: E402
from talonx_opportunity import sec_refresh as NEW  # noqa: E402
from talonx_premarket.catalysts import SecSubmissions  # noqa: E402

SCALE = 25.0
TTL, CADENCE = 600 / SCALE, 300 / SCALE
BASE, PER_LOOKUP = 5 / SCALE, 0.035 / SCALE
OLD_REQ, NEW_LAT, NEW_SPACING = 0.26 / SCALE, 0.05 / SCALE, 0.21 / SCALE
SCANS, WARM = 9, 2


def run(n, design, seed=7):
    rnd = random.Random(seed)
    net = threading.Lock()
    reqs = [0]

    def old_http(url, headers):
        with net:                                   # strictly serial SEC, fixed cost (live-fitted)
            time.sleep(OLD_REQ)
            reqs[0] += 1
            return {"filings": {"recent": {}}}

    def new_http(url, headers):
        time.sleep(NEW_LAT)                          # latency only; starts are spaced by the limiter
        reqs[0] += 1
        return {"filings": {"recent": {}}}
    sec = SecSubmissions(user_agent="ua", http_get=old_http if design == "OLD" else new_http, ttl_s=TTL,
                         clock=time.perf_counter)
    if design == "OLD":
        w = OLD.BackgroundSecCache(sec, refresh_ahead_s=480 / SCALE, idle_sleep_s=0.02, idle_gap_s=2 / SCALE,
                                   forget_after_s=1800 / SCALE)
    else:
        w = NEW.BackgroundSecCache(sec, refresh_ahead_s=480 / SCALE, idle_sleep_s=0.02, idle_gap_s=2 / SCALE,
                                   forget_after_s=1800 / SCALE, reuse_window_s=660 / SCALE,
                                   min_interval_s=NEW_SPACING, scan_refresh_rate_per_s=2.0 * SCALE)
    pool = [f"{i:010d}" for i in range(n)]
    nxt = n
    t0 = time.perf_counter()
    rows = []
    for k in range(SCANS):
        while time.perf_counter() < t0 + k * CADENCE:
            time.sleep(0.002)
        if k:                                        # 15 % churn: newly gapping names replace old ones
            for _ in range(int(0.15 * n)):
                pool[rnd.randrange(n)] = f"{nxt:010d}"
                nxt += 1
        order = pool[:]
        rnd.shuffle(order)
        r0, ref0 = reqs[0], w.stats["refreshed"]
        w.begin_scan()
        s = time.perf_counter()
        ages, waits, src = [], [], {"fresh": 0, "sync": 0, "stale": 0}
        for i, c in enumerate(order):
            hit = sec._cache.get(c)
            now = time.perf_counter()
            fresh = hit is not None and now - hit[0] < TTL
            a = time.perf_counter()
            w.get(c)
            waits.append((time.perf_counter() - a) * SCALE)
            if fresh:
                src["fresh"] += 1
                ages.append((now - hit[0]) * SCALE)
            else:
                cur = sec._cache.get(c)
                if cur is not None and cur[0] >= now:
                    src["sync"] += 1
                    ages.append(max(0.0, (time.perf_counter() - cur[0]) * SCALE))
                else:
                    src["stale"] += 1
                    if cur is not None:
                        ages.append((time.perf_counter() - cur[0]) * SCALE)
            if i % 25 == 24:
                time.sleep(25 * PER_LOOKUP)
        time.sleep(BASE)
        w.end_scan()
        dur = (time.perf_counter() - s) * SCALE
        ages.sort()
        waits.sort()
        rows.append({"scan": k, "duration_s": round(dur, 1), **src,
                     "max_age_raw": round(ages[-1], 3) if ages else None,
                     "p95_age": round(ages[int(.95 * (len(ages) - 1))], 1) if ages else None,
                     "p99_age": round(ages[int(.99 * (len(ages) - 1))], 1) if ages else None,
                     "ge_590": sum(x >= 590 for x in ages), "ge_600": sum(x >= 600 for x in ages),
                     "requests_in_scan": reqs[0] - r0, "req_rate_in_scan": round((reqs[0] - r0) / dur, 2),
                     "wait_p99_s": round(waits[int(.99 * (len(waits) - 1))], 3), "wait_max_s": round(waits[-1], 3),
                     "refreshed_during_scan": w.stats["refreshed"] - ref0})
    total_s = (time.perf_counter() - t0) * SCALE
    w.stop()
    st = rows[WARM:]
    agg = lambda key, f=max: f(r[key] for r in st)  # noqa: E731
    return {"n": n, "design": design, "scan_p50": sorted(r["duration_s"] for r in st)[len(st) // 2],
            "scan_p90": sorted(r["duration_s"] for r in st)[int(.9 * (len(st) - 1))], "scan_max": agg("duration_s"),
            "cache_fresh": sum(r["fresh"] for r in st), "sync_fallback": sum(r["sync"] for r in st),
            "stale_fallback": sum(r["stale"] for r in st), "max_served_age_raw": agg("max_age_raw"),
            "p95_age_max": agg("p95_age"), "p99_age_max": agg("p99_age"), "scans_with_age_ge_590": sum(r["ge_590"] > 0 for r in st),
            "items_age_ge_600": sum(r["ge_600"] for r in st), "req_rate_in_scan_max": agg("req_rate_in_scan"),
            "req_rate_overall": round(reqs[0] / total_s, 2), "discovery_wait_p99_max_s": agg("wait_p99_s"),
            "discovery_wait_max_s": agg("wait_max_s"),
            "refresh_during_scan_mean": round(sum(r["refreshed_during_scan"] for r in st) / len(st)),
            "scans": rows}


if __name__ == "__main__":
    ns = [int(x) for x in sys.argv[1:]] or [500, 1000, 1250, 1300, 1500, 2000]
    out = []
    for n in ns:
        for d in ("OLD", "NEW"):
            r = run(n, d)
            out.append(r)
            print(json.dumps({k: v for k, v in r.items() if k != "scans"}), flush=True)
    json.dump(out, open(r"C:\workspace\TalonX\results\sec_remediation_2026-09-28\sec_load_bench.json", "w"), indent=1)
