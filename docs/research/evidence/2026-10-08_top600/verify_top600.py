"""READ-ONLY DTU_V3_TOP600 preview + activation verifier (2026-10-08). Never builds, restarts, rolls back or notifies.

  preview WINDOW   recompute the capped selection IN MEMORY from the window's recorded inputs (market.db universe
                   members, split-adjusted daily, as-traded live daily + its session list) and compare with the
                   snapshot actually published for that window (whatever policy it was built under).
  verify  WINDOW   activation check: the published snapshot must be DTU_V3_TOP600 (fingerprint), <= 600 Core, no
                   EVENT_ELIGIBLE, CAP_RANK_EXCLUDED reasons only above rank 600, and identical to an independent
                   recompute from its recorded inputs; ingestion / discovery runtime details agree; singleton owners.
                   A missing snapshot is reported LATE_OR_NOT_PUBLISHED (distinct from INVALID).
usage: python verify_top600.py preview|verify WINDOW [OUT_JSON]
"""
import json
import sqlite3
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / "talonx_opportunity").is_dir())
sys.path.insert(0, str(REPO))
from talonx_opportunity import universe_tiers as U  # noqa: E402
from talonx_opportunity.phases import trading_window  # noqa: E402

OPP = REPO / "results" / "opportunity"


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def inputs(m, wid):
    row = m.execute("SELECT members_json FROM universe WHERE window_id=?", (wid,)).fetchone()
    st = m.execute("SELECT sessions_json, failed_json FROM dtu_live_daily_state WHERE window_id=?", (wid,)).fetchone()
    if row is None or st is None:
        return None
    members = json.loads(row[0])
    daily = {r[0]: json.loads(r[1]) for r in m.execute("SELECT symbol, bars_json FROM daily WHERE window_id=?", (wid,))}
    live = {r[0]: json.loads(r[1]) for r in m.execute("SELECT symbol, bars_json FROM dtu_live_daily WHERE window_id=?",
                                                     (wid,))}
    return members, daily, live, set(json.loads(st[1] or "[]")), json.loads(st[0])


def recompute(m, wid, policy):
    inp = inputs(m, wid)
    if inp is None:
        return None
    members, daily, live, failed, sessions = inp
    ref = trading_window(date.fromisoformat(wid)).reference_session.isoformat()
    return {r["symbol"]: r for r in U.classify_members(members, daily, ref, policy, live=live, live_failed=failed,
                                                       sessions=sessions)}, sessions


def protections(wid):
    out = {}
    o = OPP / "opportunity.db"
    if o.exists():
        c = ro(o)
        out["open_setups"] = sorted({r[0] for r in c.execute("SELECT symbol FROM candidates WHERE state IN "
                                                             "('BULLISH_SETUP','BEARISH_SETUP')")})
        c.close()
    p = OPP / "promotion.db"
    if p.exists():
        c = ro(p)
        out["signals_window"] = sorted({r[0] for r in c.execute("SELECT symbol FROM promotions WHERE window_id=? AND "
                                                                "state IN ('PROMOTED_SIGNAL','QUEUED')", (wid,))})
        c.close()
    hb = Path.home() / ".talonx" / "intelligence" / "service.heartbeat.json"
    out["v2_scope"] = sorted(json.loads(hb.read_text(encoding="utf-8")).get("effective_symbols", [])) if hb.exists() else []
    v2 = REPO / "v2_release_rc1.db"
    if v2.exists():
        c = ro(v2)
        out["v2_positions_intents"] = sorted({r[0] for r in c.execute(
            "SELECT symbol FROM positions WHERE status NOT IN ('CLOSED') UNION SELECT symbol FROM pending_entry_intents "
            "WHERE status='PENDING'")})
        c.close()
    return out


def preview(wid):
    m = ro(OPP / "market.db")
    pub = m.execute("SELECT snapshot_version, reference_session, created_utc, policy_fp FROM dtu_snapshots WHERE "
                    "window_id=?", (wid,)).fetchone()
    got = recompute(m, wid, U.DTU_V3_TOP600)
    if got is None:
        return {"window_id": wid, "status": "NO_RECORDED_INPUTS"}
    rows, sessions = got
    core = sorted((r for r in rows.values() if r["state"] == U.CORE), key=lambda r: r["core_rank"])
    capped = sorted((r for r in rows.values() if (r["reason"] or "").startswith(U.CAP_RANK)), key=lambda r: r["core_rank"])
    pubrows = {r["symbol"]: dict(r) for r in m.execute("SELECT * FROM dtu_snapshot WHERE window_id=?", (wid,))}
    pub_adm = {s for s, r in pubrows.items() if r["state"] in (U.CORE, U.EVENT_ELIGIBLE)}
    sel = {r["symbol"] for r in core}
    prot = protections(wid)
    protected = set().union(*[set(v) for v in prot.values()])
    adv = [r["adv20"] for r in core]
    px = [r["price"] for r in core]
    exch = {}
    for mm in json.loads(m.execute("SELECT members_json FROM universe WHERE window_id=?", (wid,)).fetchone()[0]):
        if mm["symbol"] in sel:
            exch[mm.get("exchange") or "UNKNOWN"] = exch.get(mm.get("exchange") or "UNKNOWN", 0) + 1
    cyc = m.execute("SELECT fetched_symbols, batches FROM cycles WHERE window_id=? AND phase='REGULAR'", (wid,)).fetchall()
    m.close()
    est_total = len(sel | protected)
    return {
        "window_id": wid, "published_snapshot": dict(zip(("version", "reference_session", "created_utc", "policy_fp"),
                                                         pub)) if pub else None,
        "published_policy": (U.policy_by_fingerprint(pub[3]).version if pub and U.policy_by_fingerprint(pub[3]) else None),
        "input_sessions": [sessions[0], sessions[-1]], "cutoff_session_d_minus_1": sessions[-1],
        "qualifying_both_floors": len(core) + len(capped), "selected": len(core),
        "adv20_boundary": {"last_selected": {"symbol": core[-1]["symbol"], "adv20": round(core[-1]["adv20"])} if core else None,
                           "first_excluded": {"symbol": capped[0]["symbol"], "adv20": round(capped[0]["adv20"])} if capped else None},
        "vs_published_admissible": {"published_admissible": len(pub_adm), "retained": len(sel & pub_adm),
                                    "removed": len(pub_adm - sel), "added": len(sel - pub_adm)},
        "close_usd": {"min": round(min(px), 2), "median": round(statistics.median(px), 2), "max": round(max(px), 2)} if px else None,
        "adv20_usd": {"min": round(min(adv)), "median": round(statistics.median(adv)), "max": round(max(adv))} if adv else None,
        "exchange": exch, "sector": "UNKNOWN (no sector/SIC metadata stored)",
        "protected_subscriptions": {k: len(v) for k, v in prot.items()},
        "protected_outside_top600": len(protected - sel),
        "estimated_total_monitored": est_total,
        "workload_estimate": {"LABEL": "ESTIMATE (assumes fetch requests scale with symbols / ~190 per request)",
                              "observed_regular_fetched_median": statistics.median(x[0] for x in cyc) if cyc else None,
                              "observed_regular_batches_median": statistics.median(x[1] for x in cyc) if cyc else None,
                              "estimated_batches": -(-est_total // 190)},
        "selected_symbols": sorted(sel), "removed_symbols": sorted(pub_adm - sel),
    }


def verify(wid):
    rep = {"window_id": wid, "checked_utc": datetime.now(timezone.utc).isoformat(), "expected_policy": U.DTU_V3_TOP600.version,
           "expected_fp": U.DTU_V3_TOP600.fingerprint(), "checks": {}}
    m = ro(OPP / "market.db")
    pub = m.execute("SELECT snapshot_version, created_utc, policy_fp, counts_json FROM dtu_snapshots WHERE window_id=?",
                    (wid,)).fetchone()
    if pub is None:
        rep["status"] = "LATE_OR_NOT_PUBLISHED"
        return rep
    rep["published"] = {"version": pub[0], "created_utc": pub[1], "policy_fp": pub[2], "counts": json.loads(pub[3])}
    rows = {r["symbol"]: dict(r) for r in m.execute("SELECT * FROM dtu_snapshot WHERE window_id=?", (wid,))}
    c = rep["checks"]
    c["policy_fp_is_v3"] = pub[2] == U.DTU_V3_TOP600.fingerprint()
    core = [r for r in rows.values() if r["state"] == U.CORE]
    c["core_le_600"] = len(core) <= 600
    c["no_event_eligible"] = not any(r["state"] == U.EVENT_ELIGIBLE for r in rows.values())
    c["cap_reasons_only_above_600"] = all((r["core_rank"] or 0) > 600 for r in rows.values()
                                          if (r["reason"] or "").startswith(U.CAP_RANK))
    re_ = recompute(m, wid, U.DTU_V3_TOP600)
    c["independent_recompute_matches"] = (re_ is not None and all(
        (rows[s]["state"], rows[s]["reason"]) == (r["state"], r["reason"]) for s, r in re_[0].items() if s in rows)
        and set(re_[0]) == set(rows))
    act = m.execute("SELECT cycle_utc, n_active, counts_json, policy_fp FROM dtu_active WHERE window_id=? ORDER BY "
                    "cycle_utc DESC LIMIT 1", (wid,)).fetchone()
    rep["latest_active"] = dict(zip(("cycle_utc", "n_active", "counts", "policy_fp"),
                                    (act[0], act[1], json.loads(act[2]), act[3]))) if act else None
    m.close()
    rt = ro(OPP / "runtime.db")
    comps = {r["name"]: dict(r) for r in rt.execute("SELECT name, pid, state, version, detail_json, config_fps_json "
                                                    "FROM components WHERE name IN ('ingestion','discovery','sentinel')")}
    rt.close()
    ing = json.loads(comps.get("ingestion", {}).get("detail_json") or "{}")
    c["ingestion_reports_v3"] = ing.get("dtu_policy") == U.DTU_V3_TOP600.version
    disc_fps = json.loads(comps.get("discovery", {}).get("config_fps_json") or "{}")
    c["discovery_schedule_loaded"] = "DTU_SCHEDULE" in disc_fps
    try:
        import psutil
        owners = {n: sorted(p.info["pid"] for p in psutil.process_iter(["pid", "cmdline"])
                            if (p.info["cmdline"] or [])[-2:] == ["component", n]) for n in ("ingestion", "discovery")}
        c["singleton_owners"] = all(len(v) <= 2 for v in owners.values())        # venv shim + interpreter
        rep["owners"] = owners
    except Exception as exc:  # noqa: BLE001
        rep["owners"] = {"error": repr(exc)}
    rep["status"] = "VALID" if all(c.values()) else "INVALID"
    return rep


if __name__ == "__main__":
    mode, wid = sys.argv[1], sys.argv[2]
    res = preview(wid) if mode == "preview" else verify(wid)
    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("selected_symbols", "removed_symbols")}, indent=1,
                     default=str))
