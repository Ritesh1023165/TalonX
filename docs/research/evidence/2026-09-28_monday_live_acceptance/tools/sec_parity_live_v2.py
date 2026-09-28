"""SEC refresh same-data parity on TODAY'S live data (read-only on live stores; writes only its scratch roots).

Input snapshot: live market.db state for window 2026-09-28 read ONCE at start (identical for every run); decision clock
fixed at start; live insider ledger (read-only); real SEC EDGAR throttled to <= 1 request per INTERVAL_S seconds
(default 0.5 s = 2 req/s, so live discovery (<= 2.9 req/s today) + parity stays < 5 req/s).
  R1 SYNC_REFERENCE   plain SecSubmissions                          (today's synchronous path)
  R2 ON_COLD          BackgroundSecCache, cold                       (every lookup = synchronous fallback)
  R3 ON_REFRESHED     same BackgroundSecCache after the idle-gated refresher re-fetched every due entry
Records RAW (unrounded) served ages and every SEC fetch error of the parity instances.
usage: python sec_parity_live.py <scratch_dir> [interval_s]   -> JSON on stdout
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
sys.path.insert(0, str(REPO))
from talonx_opportunity import sec_refresh as SR  # noqa: E402
from talonx_opportunity.discovery import Discovery  # noqa: E402
from talonx_opportunity.ingestion import read_state  # noqa: E402
from talonx_premarket import __main__ as M  # noqa: E402
from talonx_premarket.catalysts import SecSubmissions  # noqa: E402

LIVE = REPO / "results" / "opportunity"
WID = "2026-09-28"


class Throttled:
    def __init__(self, interval_s: float):
        self.i, self.last, self.n, self.t0 = interval_s, 0.0, 0, None

    def __call__(self, url: str, headers: dict) -> dict:
        wait = self.i - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        self.t0 = self.t0 or self.last
        self.n += 1
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            return json.loads(r.read())


class RawAgeCache(SR.BackgroundSecCache):
    """Parity-only: keep every raw served age (end_scan also reports raw aggregates since 2026-09-28)."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.raw_ages: list[float] = []

    def _note(self, t_call, source, age, *, reason=None):
        if age is not None:
            self.raw_ages.append(age)
        super()._note(t_call, source, age, reason=reason)


def scan(root: Path, sec, state, now) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    for f in root.glob("*.db*"):
        f.unlink()
    d = Discovery(root=root, sec=sec, ledger_path=str(M.DEFAULT_LEDGER), v2_scope=M._v2_scope(None),
                  clock=lambda: now, state_reader=lambda wid: state)
    t0 = time.monotonic()
    d.tick()
    dur = time.monotonic() - t0
    c = sqlite3.connect(root / "opportunity.db")
    latest = {r[0]: (r[1], r[2], r[3]) for r in c.execute("SELECT symbol, cls, gap_pct, score FROM symbol_latest")}
    events = {r[0]: (r[1], r[2], r[3], r[4]) for r in c.execute(
        "SELECT symbol, event_type, classification, score, catalyst FROM candidate_events")}
    cands = {r[0] for r in c.execute("SELECT candidate_id FROM candidates")}
    funnel = json.loads(c.execute("SELECT funnel_json FROM scans ORDER BY decision_utc DESC LIMIT 1").fetchone()[0])
    c.close()
    return {"latest": latest, "events": events, "cands": cands, "funnel": funnel, "wall_s": round(dur, 1)}


def diff(a: dict, b: dict) -> dict:
    both_e = set(a["events"]) & set(b["events"])
    both_l = set(a["latest"]) & set(b["latest"])
    out = {"candidate_identity": sorted(a["cands"] ^ b["cands"]),
           "candidate_presence_events": sorted(set(a["events"]) ^ set(b["events"])),
           "classification": sorted(s for s in both_l if a["latest"][s][0] != b["latest"][s][0]),
           "score": sorted(s for s in both_l if a["latest"][s][2] != b["latest"][s][2]),
           "catalyst": sorted(s for s in both_e if a["events"][s][3] != b["events"][s][3]),
           "lifecycle_event_type": sorted(s for s in both_e if a["events"][s][0] != b["events"][s][0])}
    out["total"] = sum(len(v) for v in out.values())
    out.update(symbols_checked=len(a["latest"]), events_checked=len(a["events"]), candidates_checked=len(a["cands"]))
    out["catalyst_detail"] = {s: (a["events"][s][3], b["events"][s][3]) for s in out["catalyst"][:20]}
    return out


def main(scratch, interval_s=0.5):
    M._env()
    ua = M._sec()._ua
    d = Path(scratch)
    t_start = datetime.now(timezone.utc)
    state = read_state(LIVE, WID)
    now = datetime.now(timezone.utc)
    out = {"parity_start_utc": t_start.isoformat(timespec="seconds"), "decision_clock": now.isoformat(),
           "ingestion_as_of": state["state"]["as_of_utc"], "interval_s": interval_s}
    th1 = Throttled(interval_s)
    s1 = SecSubmissions(user_agent=ua, http_get=th1)
    r1 = scan(d / "r1_sync", s1, state, now)
    th2 = Throttled(interval_s)
    s2 = SecSubmissions(user_agent=ua, http_get=th2)
    w = RawAgeCache(s2, start=False)
    r2 = scan(d / "r2_on_cold", w, state, now)
    time.sleep(125)                                       # every entry >= 120 s old -> due for background refresh
    w._last_get = float("-inf")
    t0 = time.monotonic()
    refreshed = 0
    while True:
        n = w.run_once()
        refreshed += n
        if n == 0:
            break
    refresh_s = time.monotonic() - t0
    w.raw_ages.clear()                                    # R3 ages only
    r3 = scan(d / "r3_on_refreshed", w, state, now)
    ages = sorted(w.raw_ages)
    out["runs"] = {k: {"wall_s": r["wall_s"], "sec_cache": r["funnel"].get("sec_cache"), "events": r["funnel"].get("EVENTS"),
                       "catalyst_unknown": r["funnel"].get("CATALYST_UNKNOWN")}
                   for k, r in (("R1_SYNC_REFERENCE", r1), ("R2_ON_COLD", r2), ("R3_ON_REFRESHED", r3))}
    out["background_refresh"] = {"refreshed": refreshed, "seconds": round(refresh_s, 1), **w.stats}
    out["parity_sec"] = {"r1_requests": th1.n, "r2_plus_refresh_requests": th2.n,
                         "r1_errors": s1.errors[:10], "r2_errors": s2.errors[:10], "r1_throttled": s1.throttled,
                         "r2_throttled": s2.throttled, "max_parity_rate_per_s": round(1 / interval_s, 2)}
    out["r3_raw_served_age"] = {"n": len(ages), "max": ages[-1] if ages else None,
                                "ge_590": sum(a >= 590 for a in ages), "ge_595": sum(a >= 595 for a in ages),
                                "ge_600": sum(a >= 600 for a in ages)}
    out["R1_vs_R2"] = diff(r1, r2)
    out["R1_vs_R3"] = diff(r1, r3)
    out["parity_end_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], float(a[1]) if len(a) > 1 else 0.5)
