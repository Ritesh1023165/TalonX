"""ONE development-only corrected run for the ERM nominee GAP_UP_10|SHORT|H10|L1 (correction spec V2.1).

Stages (each must pass before the next; corrected outcomes are computed only in stage 4):
  1 SCOPE   frozen design-lock fingerprint, offline network guard active, development archives only (LOAD guard +
            max bar date <= 2023-12-29), run-once marker absent.
  2 PARITY  original rules (frozen code path: gap events, frozen eligibility + R7 mask, frozen 2026-SIC bench_of,
            events.outcomes, metrics.cell_metrics, metrics.screen) must reproduce the Gate D trial_ledger entry for the
            nominee EXACTLY (json-identical metrics incl. per-year, top-k, CI, missing-exit bounds; identical screen).
  3 MANIFEST the V2.1 manifest is REBUILT from archived inputs by the frozen builder (no network, no fetch) into this
            run's directory; sha256 must equal the frozen value, and every scored row must have entry/exit/benchmark
            bars present (presence only).
  4 SCORE   frozen metrics + frozen screen on the corrected rows (VALID + DATA_MISSING_EXIT; benchmark_v2), the frozen
            survivorship diagnostic under corrected eligibility (rows excluded SOLELY by R1A_NOT_AVAILABLE added; no
            unresolved row is ever added or scored) and the predeclared descriptive subset
            NO_DETECTED_STOCK_ADJUSTMENT_OR_ETF_CASH_DIVIDEND (never gating).
Outputs (atomic writes) in results/erm_nominee_corrected_run/; RUN_COMPLETE.json is written LAST. No retry.
usage (scoring worktree root, offline guard on PYTHONPATH):
  PYTHONPATH=research/event_response_map_v1/offline python research/erm_nominee_audit/score_corrected.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import socket
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
ERM = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1")          # frozen Phase D archive (read only)
AUDIT_INPUTS = Path(r"C:\workspace\TalonX-erm-audit\results\erm_nominee_audit")  # archived acquired metadata caches
OUT = HERE / "results" / "erm_nominee_corrected_run"
FREEZE = HERE / "docs/research/preregistration/ERM_NOMINEE_CORRECTION_V2_1_FREEZE.json"   # committed freeze record
FROZEN_MANIFEST_SHA256 = json.loads(FREEZE.read_text())["manifest_sha256"] if FREEZE.exists() else ""
FROZEN_FINGERPRINT = "12a909e795986ff3abeac9ca92906a64c3387a5e3c64734f2b72031b781cb8ad"
CELL = "GAP_UP_10|SHORT|H10|L1"
DEV_END = date(2023, 12, 29)


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def jnorm(x):
    return json.loads(json.dumps(x, default=str))


def log(rec: dict, **kv) -> None:
    rec["log"].append({"utc": now(), **kv})
    print(json.dumps({"utc": now(), **kv}, default=str), flush=True)
    atomic(OUT / "run_record.json", json.dumps(rec, indent=1, default=str))


def stop(rec: dict, status: str, **kv) -> None:
    rec.update(status=status, ended_utc=now(), **kv)
    atomic(OUT / "run_record.json", json.dumps(rec, indent=1, default=str))
    print(json.dumps({"STOP": status, **kv}, default=str), flush=True)
    sys.exit(2)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "RUN_COMPLETE.json").exists() or (OUT / "corrected_cell.json").exists():
        raise SystemExit("run-once: corrected outputs already exist; refusing")
    import numpy as np
    import pandas as pd
    code = {p: sha(HERE / p) for p in ("research/erm_nominee_audit/score_corrected.py",
                                       "research/erm_nominee_audit/v2_rules.py",
                                       "research/erm_nominee_audit/v2_manifest.py")}
    rec = {"run": "ERM_NOMINEE_CORRECTED_DEV_RUN_V2.1", "cell": CELL, "started_utc": now(), "status": "RUNNING",
           "freeze_record_sha256": sha(FREEZE) if FREEZE.exists() else None,
           "code_sha256": code, "frozen_manifest_sha256": FROZEN_MANIFEST_SHA256,
           "env": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
                   "pandas": pd.__version__}, "log": []}
    # ------------------------------------------------------------------------------------------------ 1 SCOPE
    from research.event_response_map_v1 import data as D, events as E, fingerprint as F, metrics as M, universe as U
    from research.event_response_map_v1 import identity as I
    from research.event_response_map_v1.phase_d import mask_sic6770
    from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard
    fp = F.fingerprint(HERE)
    offline = getattr(socket.create_connection, "__name__", "") == "_refuse"
    rec["scope"] = {"fingerprint": fp, "fingerprint_ok": fp == FROZEN_FINGERPRINT, "offline_guard": offline,
                    "manifest_sha_set": bool(FROZEN_MANIFEST_SHA256),
                    "guard_state_sha256": sha(ERM / "guard_state.json")}
    if not (fp == FROZEN_FINGERPRINT and offline and FROZEN_MANIFEST_SHA256):
        stop(rec, "BLOCKED_SCOPE", detail=rec["scope"])
    guard = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
    bars, _ = D.load(ERM / "_archive" / "alpaca", purpose="RETURNS", guard=guard)
    raw, _ = D.load(ERM / "_archive" / "alpaca", purpose="ELIGIBILITY_ONLY", guard=guard)
    dbars, _ = D.load(ERM / "_archive" / "alpaca_diag", purpose="RETURNS", guard=guard)
    rec["scope"]["max_bar_date"] = str(max(bars["date"].max(), raw["date"].max(), dbars["date"].max()))
    if max(bars["date"].max(), raw["date"].max(), dbars["date"].max()) > DEV_END:
        stop(rec, "BLOCKED_SCOPE", detail="bar beyond development end")
    log(rec, stage="scope", ok=True, **rec["scope"])
    # ------------------------------------------------------------------------------------------------ 2 PARITY
    sessions = sorted(bars.loc[bars["symbol"] == "SPY", "date"].unique())
    bench = {b: bars[bars["symbol"] == b] for b in D.BENCHMARKS}
    eq = bars[~bars["symbol"].isin(D.BENCHMARKS)]
    cand = json.loads((ERM / "candidates.json").read_text())
    cand["r3"] = json.loads((ERM / "candidates_r3.json").read_text())
    r3 = cand["r3"]
    elig, _ = mask_sic6770(U.eligibility(raw, sessions), r3["sic6770_windows"])
    intervals = {c: [(s_, date.fromisoformat(lo), date.fromisoformat(hi)) for s_, lo, hi in v]
                 for c, v in r3["intervals"].items()}
    bysym = I.by_symbol(intervals)
    mapping = json.loads((HERE / "docs/research/preregistration/rs_sector_mapping_v1.json").read_text())["mapping"]
    cur_sic = {c: json.loads(gzip.decompress((ERM / "_archive/sec" / f"sub_CIK{c}.json.gz").read_bytes())).get("sic")
               for c in intervals}

    def bench_of(sym, d):                                    # frozen phase_d.bench_of (current SIC; dated CIK)
        c = I.symbol_cik_on(sym, d, bysym)
        return E.sic_benchmark(cur_sic.get(c), mapping) if c else "SPY"

    gaps = E.gap_events(eq, sessions)
    gaps = gaps[gaps["event_type"] == "GAP_UP_10"].drop(columns="gap")
    ev = E.attach_bucket(E.dedup(gaps), elig)
    obs, _ = E.outcomes(ev, eq, bench, bench_of, sessions)
    sub = obs[(obs["event_type"] == "GAP_UP_10") & (obs["horizon"] == "H10") & (obs["bucket"] == "L1")]
    m0 = M.cell_metrics(sub, "SHORT", "L1")
    s0 = M.screen(m0, "GAP_UP_10")
    led = json.loads((ERM / "trial_ledger.json").read_text())
    g = next(c for c in led["cells"] if c["cell"] == CELL)
    gate = {k: v for k, v in g["screen"].items() if k in ("criteria", "SCREEN_PASS", "nominatable", "label")}
    diffs = sorted(k for k in set(jnorm(m0)) | set(g["metrics"]) if jnorm(m0).get(k) != g["metrics"].get(k))
    sdiff = jnorm(s0) != jnorm(gate)
    rec["parity"] = {"metric_keys_compared": len(set(g["metrics"])), "metric_diffs": diffs, "screen_diff": sdiff,
                     "n": m0.get("n"), "distinct_dates": m0.get("distinct_dates"),
                     "distinct_symbols": m0.get("distinct_symbols")}
    atomic(OUT / "parity_original_cell.json", json.dumps({"recomputed": jnorm(m0), "gate_d": g["metrics"],
                                                          "screen_recomputed": jnorm(s0), "screen_gate_d": gate},
                                                         indent=1))
    if diffs or sdiff:
        stop(rec, "BLOCKED_PARITY", detail=rec["parity"])
    log(rec, stage="parity", ok=True, **rec["parity"])
    del obs, sub, raw, elig, ev, gaps, cur_sic
    import gc
    gc.collect()
    # ------------------------------------------------------------------------------------------------ 3 MANIFEST
    os.environ.update(ERM_AUDIT_INPUTS=str(AUDIT_INPUTS), ERM_V2_OUT=str(OUT / "reconstructed_manifest"),
                      ERM_NO_FETCH="1")
    (OUT / "reconstructed_manifest").mkdir(exist_ok=True)
    import importlib
    vm = importlib.import_module("research.erm_nominee_audit.v2_manifest")
    vm.main()
    msha = sha(OUT / "reconstructed_manifest" / "manifest.csv")
    man = pd.read_csv(OUT / "reconstructed_manifest" / "manifest.csv", dtype=str).fillna("")
    scored = man[man["v2_status"].isin(["VALID", "DATA_MISSING_EXIT"])].copy()
    valid = scored[scored["v2_status"] == "VALID"]
    allb = pd.concat([eq, dbars[~dbars["symbol"].isin(D.BENCHMARKS)]])
    pres = set(zip(allb["symbol"], allb["date"]))
    bpres = {b: set(bench[b]["date"]) for b in bench}
    missing = []
    for r in valid.itertuples():
        en, ex = date.fromisoformat(r.entry), date.fromisoformat(r.exit)
        if (r.symbol, en) not in pres or (r.symbol, ex) not in pres or not r.benchmark_v2 \
                or en not in bpres.get(r.benchmark_v2, ()) or ex not in bpres.get(r.benchmark_v2, ()) \
                or en not in bpres["SPY"] or ex not in bpres["SPY"]:
            missing.append((r.symbol, r.entry))
    rec["manifest"] = {"sha256": msha, "match_frozen": msha == FROZEN_MANIFEST_SHA256, "rows": len(man),
                       "valid": int(len(valid)), "missing_exit": int((scored["v2_status"] == "DATA_MISSING_EXIT").sum()),
                       "presence_failures": missing}
    if msha != FROZEN_MANIFEST_SHA256 or missing:
        stop(rec, "BLOCKED_MANIFEST", detail=rec["manifest"])
    log(rec, stage="manifest", ok=True, **{k: v for k, v in rec["manifest"].items() if k != "presence_failures"})
    # ------------------------------------------------------------------------------------------------ 4 SCORE (once)
    rec["status"] = "SCORING"
    atomic(OUT / "run_record.json", json.dumps(rec, indent=1, default=str))
    try:
        bmap = {(r.symbol, date.fromisoformat(r.entry)): r.benchmark_v2 for r in man.itertuples() if r.benchmark_v2}

        def obs_for(rows):
            evc = pd.DataFrame({"event_type": "GAP_UP_10", "symbol": rows["symbol"].tolist(),
                                "event_date": [date.fromisoformat(x) for x in rows["gap_day"]],
                                "entry_date": [date.fromisoformat(x) for x in rows["entry"]], "bucket": "L1"})
            evc = evc.sort_values(["entry_date", "symbol"]).reset_index(drop=True)     # frozen event ordering
            o, cnt = E.outcomes(evc, allb, bench, lambda s_, d_: bmap[(s_, d_)], sessions)
            return o[o["horizon"] == "H10"].reset_index(drop=True), cnt

        def with_missing(o, rows_me):
            me = pd.DataFrame({"event_type": "GAP_UP_10", "symbol": rows_me["symbol"].tolist(),
                               "entry_date": [date.fromisoformat(x) for x in rows_me["entry"]], "bucket": "L1",
                               "horizon": "H10", "ret_raw": np.nan, "ret_spy_rel": np.nan, "ret_sector_rel": np.nan,
                               "benchmark": None, "suspect_adjustment": False, "missing_exit": True})
            return pd.concat([o, me], ignore_index=True) if len(me) else o

        oc, cnt_c = obs_for(valid)
        if len(oc) != len(valid) or oc["missing_exit"].any():
            raise RuntimeError(f"corrected outcomes inconsistent with manifest: {len(oc)} vs {len(valid)}; {cnt_c}")
        cell_obs = with_missing(oc, scored[scored["v2_status"] == "DATA_MISSING_EXIT"])
        atomic(OUT / "corrected_obs.csv", cell_obs.to_csv(index=False))
        mc = M.cell_metrics(cell_obs, "SHORT", "L1")
        sc = M.screen(mc, "GAP_UP_10")
        # survivorship diagnostic under corrected eligibility: rows excluded SOLELY by R1A_NOT_AVAILABLE
        r1 = man[man["flags"] == "R1A_NOT_AVAILABLE"]
        r1v = r1[~r1["exit_placeholder_or_missing"].isin(["True"])]
        add_o = obs_for(r1v)[0] if len(r1v) else oc.iloc[0:0]
        ext = with_missing(pd.concat([oc, add_o], ignore_index=True),
                           pd.concat([scored[scored["v2_status"] == "DATA_MISSING_EXIT"],
                                      r1[r1["exit_placeholder_or_missing"].isin(["True"])]]))
        m2 = M.cell_metrics(ext, "SHORT", "L1")
        s2 = M.screen(m2, "GAP_UP_10")
        surv = {"rows_added": int(len(r1)), "symbols_added": sorted(r1["symbol"].unique().tolist()),
                "EXCLUSION_DEPENDENT": bool(sc["SCREEN_PASS"] and not s2["SCREEN_PASS"]),
                "screen_with_added": jnorm(s2), "metrics_with_added": jnorm(m2)}
        # predeclared descriptive subset (never gating)
        sub_rows = valid[valid["sens_no_detected_stock_adj_or_etf_cash_div"] == "IN_SUBSET"]
        keys = set(zip(sub_rows["symbol"], sub_rows["entry"]))
        so = oc[[(s_, str(d_)) in keys for s_, d_ in zip(oc["symbol"], oc["entry_date"])]]
        ms = M.cell_metrics(so, "SHORT", "L1")
        result = {"cell": CELL, "spec": "ERM_NOMINEE_CORRECTION_SPEC_V2.1", "population": "evidence-covered (V2.1)",
                  "metric_note": "adjusted-return research proxy (ALL-adjusted ratio), not executable short P&L",
                  "original_gate_d": {"metrics": g["metrics"], "screen": gate},
                  "corrected": {"metrics": jnorm(mc), "screen": jnorm(sc), "outcome_counts": cnt_c},
                  "survivorship_diagnostic": surv,
                  "descriptive_subset": {"label": "NO_DETECTED_STOCK_ADJUSTMENT_OR_ETF_CASH_DIVIDEND",
                                         "gating": False, "rows": int(len(so)), "metrics": jnorm(ms)},
                  "neighbour_support": "NOT_RECHECKED (would require scoring other cells)"}
        verdict = ("CORRECTED_DEVELOPMENT_SCREEN_PASS" if sc["SCREEN_PASS"] and not surv["EXCLUSION_DEPENDENT"]
                   else "CORRECTED_DEVELOPMENT_SCREEN_FAIL")
        result["verdict"] = verdict
        atomic(OUT / "corrected_cell.json", json.dumps(result, indent=1, default=str))
        rec.update(status="COMPLETE", verdict=verdict, ended_utc=now(),
                   outputs={p.name: sha(p) for p in sorted(OUT.glob("*.json")) if p.name != "run_record.json"}
                   | {"corrected_obs.csv": sha(OUT / "corrected_obs.csv")})
        log(rec, stage="score", ok=True, verdict=verdict)
        atomic(OUT / "RUN_COMPLETE.json", json.dumps({"utc": now(), "verdict": verdict,
                                                      "corrected_cell_sha256": sha(OUT / "corrected_cell.json")}))
    except Exception as e:  # noqa: BLE001 -- preserve, never retry
        rec.update(status="INCOMPLETE_AFTER_SCORING_STARTED", error=f"{type(e).__name__}: {e}",
                   traceback=traceback.format_exc(), ended_utc=now())
        atomic(OUT / "run_record.json", json.dumps(rec, indent=1, default=str))
        raise


if __name__ == "__main__":
    main()
