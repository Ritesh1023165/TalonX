"""SEC refresh parity shadow on the SAME data (read-only on live stores; each run writes only its own scratch root).

Input: the final 2026-09-25 ingestion state (live market.db, read-only), decision clock fixed at 23:59Z (AFTER_HOURS,
data as of 23:44Z), the live insider ledger (read-only), real SEC EDGAR (free; one SecSubmissions per run, <= ~5 req/s).
  R1 SYNC_REFERENCE    plain SecSubmissions (today's path)
  R2 ON_COLD           BackgroundSecCache, cold cache (every lookup falls back to the synchronous path)
  R3 ON_REFRESHED      the SAME BackgroundSecCache after its background refresher re-fetched every due entry
                       (entries aged >= 120 s, idle-gated) -> scan served from refreshed copies
Compares symbol_latest (classification, gap, score) and candidate_events (event type, classification, score, catalyst).
usage: python sec_parity.py <scratch_dir>  -> JSON on stdout
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
sys.path.insert(0, str(REPO))
from talonx_opportunity import sec_refresh as SR  # noqa: E402
from talonx_opportunity.discovery import Discovery  # noqa: E402
from talonx_opportunity.ingestion import read_state  # noqa: E402
from talonx_premarket import __main__ as M  # noqa: E402

LIVE = REPO / "results" / "opportunity"
WID = "2026-09-25"
NOW = datetime(2026, 9, 25, 23, 59, tzinfo=timezone.utc)


def scan(root: Path, sec, state) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    for f in root.glob("*.db*"):
        f.unlink()
    d = Discovery(root=root, sec=sec, ledger_path=str(M.DEFAULT_LEDGER), v2_scope=M._v2_scope(None),
                  clock=lambda: NOW, state_reader=lambda wid: state)
    t0 = time.monotonic()
    d.tick()
    dur = time.monotonic() - t0
    c = sqlite3.connect(root / "opportunity.db")
    latest = {r[0]: (r[1], r[2], r[3]) for r in c.execute("SELECT symbol, cls, gap_pct, score FROM symbol_latest")}
    events = {r[0]: (r[1], r[2], r[3], r[4]) for r in c.execute(
        "SELECT symbol, event_type, classification, score, catalyst FROM candidate_events")}
    funnel = json.loads(c.execute("SELECT funnel_json FROM scans ORDER BY decision_utc DESC LIMIT 1").fetchone()[0])
    c.close()
    return {"latest": latest, "events": events, "funnel": funnel, "wall_s": round(dur, 1)}


def diff(a: dict, b: dict) -> dict:
    lat = [s for s in set(a["latest"]) | set(b["latest"]) if a["latest"].get(s) != b["latest"].get(s)]
    ev = [s for s in set(a["events"]) | set(b["events"]) if a["events"].get(s) != b["events"].get(s)]
    cat = [s for s in set(a["events"]) & set(b["events"]) if a["events"][s][3] != b["events"][s][3]]
    cls = [s for s in set(a["latest"]) & set(b["latest"]) if a["latest"][s][0] != b["latest"][s][0]]
    sc = [s for s in set(a["latest"]) & set(b["latest"]) if a["latest"][s][2] != b["latest"][s][2]]
    return {"candidate_identity_mismatch": sorted(set(a["events"]) ^ set(b["events"])),
            "classification_mismatch": sorted(cls), "score_mismatch": sorted(sc), "catalyst_mismatch": sorted(cat),
            "event_mismatch": sorted(ev), "symbol_latest_mismatch": sorted(lat)[:50],
            "n_latest": len(a["latest"]), "n_events": len(a["events"])}


def main(scratch):
    M._env()
    d = Path(scratch)
    state = read_state(LIVE, WID)
    out = {"now": NOW.isoformat(), "ingestion_as_of": state["state"]["as_of_utc"]}
    r1 = scan(d / "r1_sync", M._sec(), state)
    w = SR.BackgroundSecCache(M._sec(), start=False)
    r2 = scan(d / "r2_on_cold", w, state)
    time.sleep(125)                                     # every entry now >= 120 s old -> due for background refresh
    w._last_get = float("-inf")                         # discovery idle
    t0 = time.monotonic()
    refreshed = 0
    while True:
        n = w.run_once()
        refreshed += n
        if n == 0:
            break
    out["background_refresh"] = {"refreshed": refreshed, "seconds": round(time.monotonic() - t0, 1), **w.stats}
    r3 = scan(d / "r3_on_refreshed", w, state)
    out["runs"] = {k: {"wall_s": r["wall_s"], "sec_cache": r["funnel"].get("sec_cache"),
                       "events": r["funnel"].get("EVENTS"), "alert_worthy": r["funnel"].get("ALERT_WORTHY"),
                       "catalyst_unknown": r["funnel"].get("CATALYST_UNKNOWN")}
                   for k, r in (("R1_SYNC_REFERENCE", r1), ("R2_ON_COLD", r2), ("R3_ON_REFRESHED", r3))}
    out["R1_vs_R2"] = diff(r1, r2)
    out["R1_vs_R3"] = diff(r1, r3)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
