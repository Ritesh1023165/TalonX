"""ERM nominee validation plumbing -- runner.

  python -m research.erm_nominee_validation.run --window DEV --parity     (development implementation parity)
  python -m research.erm_nominee_validation.run --window A|B              (fails closed: owner decisions + guard)

Validation windows: `ValidationConfig.require_decided()` rejects every pending owner decision, then the guard refuses
every acquisition intersecting a locked range. There is NO acquisition or scoring path for A/B in this implementation:
guard release requires a later, explicit hypothesis/window-scoped authorisation and a reviewed guard transition.
DEV: builds the V2.1 manifest from ARCHIVED development inputs only (no network, no download), compares it with the
frozen V2.1 manifest, and recomputes the frozen cell metrics / gate estimator from the STORED corrected observations.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from research.erm_nominee_validation import builder as B, gates as G  # noqa: E402
from research.erm_nominee_validation.config import (MIN_SAMPLE_FLOOR, OwnerDecisions, ValidationConfig,  # noqa: E402
                                                     WINDOWS)
from research.erm_nominee_validation.guard import ValidationGuard  # noqa: E402
from research.erm_nominee_validation.inventory import inventory  # noqa: E402

ERM = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1")
AUDIT = Path(r"C:\workspace\TalonX-erm-audit\results\erm_nominee_audit")
FROZEN_MANIFEST = HERE / "results/erm_nominee_audit/v2_1/manifest.csv"
STORED_RUN = HERE / "results/erm_nominee_corrected_run"
OUT = HERE / "results/erm_nominee_validation"
CMP_FIELDS = ("gap_day", "exit", "named", "frozen_cik", "ticker_at_D", "relabel_chain", "identity", "identity_reason",
              "issuer", "evidence_date", "mapping_class", "sp_evidence", "r1a_available", "sic_pit", "sic_source",
              "sic_filing_date", "s506_filed_by_D", "s506_straddle_D", "s506_effective_after_D", "instrument",
              "benchmark_v2", "exit_placeholder_or_missing", "traded_in_window", "sens_stock_leg",
              "sens_etf_cash_dividend_leg", "sens_no_detected_stock_adj_or_etf_cash_div", "flags", "first_reason",
              "v2_status")


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dev_meta():
    from research.event_response_map_v1 import events as E
    from research.event_response_map_v1 import identity as I
    from research.event_response_map_v1.instrument_filter import QUARTERS
    from research.event_response_map_v1.phase_d import FORM345_QUARTERS
    from research.event_response_map_v1.universe_source import PIT
    end = WINDOWS["DEV"][1].isoformat()
    cand = json.loads((ERM / "candidates.json").read_text())
    r3 = json.loads((ERM / "candidates_r3.json").read_text())
    edges = I.rename_edges(json.loads((ERM / "_renames_2019_2023.json").read_text()) +
                           json.loads((ERM / "_archive/alpaca_meta_renames_post2023.json").read_text()))
    f345 = defaultdict(list)
    for q in FORM345_QUARTERS:
        B.f345_parse(gzip.decompress((ERM / "_archive/sec" / f"{q}_form345.zip.gz").read_bytes()), f345, end)
    for q in ("2018q1", "2018q2", "2018q3", "2018q4"):
        B.f345_parse(gzip.decompress((AUDIT / "_sec_v2" / f"{q}_form345.zip.gz").read_bytes()), f345, end)
    f345 = {k: sorted(set(v)) for k, v in f345.items()}
    sp_rows = []
    with open(PIT, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sp_rows.append((r["date"], {t.strip().upper() for t in r["tickers"].split(",") if t.strip()}))
    sp_rows.sort(key=lambda x: x[0])
    from research.event_response_map_v1.instrument_filter import PERIODIC_FORMS
    periodic = defaultdict(set)
    for q in QUARTERS:
        txt = gzip.decompress((ERM / "_archive/sec" / ("master_" + q.replace("/", "_") + ".idx.gz")).read_bytes()).decode("latin-1")
        for line in txt.splitlines():
            p = line.split("|")
            if len(p) == 5 and p[0].strip().isdigit() and p[2].strip() in PERIODIC_FORMS:
                periodic[p[0].strip().zfill(10)].add(p[3].strip())
    etf_div = defaultdict(list)
    for r in json.loads((AUDIT / "_alpaca_v2/etf_cash_dividends.json").read_text()):
        etf_div[r["symbol"]].append(r["ex_date"])
    mapping = json.loads((HERE / "docs/research/preregistration/rs_sector_mapping_v1.json").read_text())["mapping"]
    meta = B.Meta(names=cand.get("names", {}), frozen_cik={s: v.get("cik") for s, v in r3["identity"].items()},
                  edges=edges, f345=f345, sp_rows=sp_rows, periodic=periodic,
                  subs=B.subs_reader([ERM / "_archive/sec", AUDIT / "_sec_v2"], end),
                  header=B.header_reader([ERM / "_archive/sec", AUDIT / "_sec_pit", AUDIT / "_sec_v2"]),
                  etf_div=etf_div, sic_to_etf=lambda x: E.sic_benchmark(x, mapping))
    return meta, set(r3["r1a_removed_for_survivorship_diagnostic"])


def build_dev(cfg: ValidationConfig, guard: ValidationGuard):
    import pandas as pd
    from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard
    from research.event_response_map_v1 import data as D
    meta, removed = dev_meta()
    lg = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
    frames = {}
    for tag, sub in (("alpaca", None), ("alpaca_diag", removed)):
        for purpose in ("RETURNS", "ELIGIBILITY_ONLY"):
            df, _ = D.load(ERM / "_archive" / tag, purpose=purpose, guard=lg)        # frozen LOAD guard
            guard.check_load(df.assign(timestamp=pd.to_datetime(df["date"]).dt.tz_localize("UTC")), f"{tag}/{purpose}")
            frames[(tag, purpose)] = df if sub is None else df[df["symbol"].isin(sub)]
    a_all, a_raw = frames[("alpaca", "RETURNS")], frames[("alpaca", "ELIGIBILITY_ONLY")]
    d_all, d_raw = frames[("alpaca_diag", "RETURNS")], frames[("alpaca_diag", "ELIGIBILITY_ONLY")]
    sessions = sorted(a_all.loc[a_all["symbol"] == "SPY", "date"].unique())
    eq = a_all[~a_all["symbol"].isin(D.BENCHMARKS)]
    pop = (B.population(eq, a_raw, sessions, cfg.start, cfg.end, "MAIN")
           + B.population(d_all, d_raw, sessions, cfg.start, cfg.end, "DIAG"))
    syms = {s for _, s, _, _ in pop}
    ser = B.series(pd.concat([a_all[a_all["symbol"].isin(syms)], d_all[d_all["symbol"].isin(syms)]]),
                   pd.concat([a_raw[a_raw["symbol"].isin(syms)], d_raw[d_raw["symbol"].isin(syms)]]))
    return B.build(pop, ser, sessions, meta, cfg.end)


def manifest_parity(rows: list) -> dict:
    frozen = {(r["symbol"], r["entry"]): r for r in csv.DictReader(open(FROZEN_MANIFEST, encoding="utf-8"))}
    mine = {(r["symbol"], r["entry"]): r for r in rows}
    diffs = []
    for k in sorted(set(frozen) | set(mine)):
        a, b = frozen.get(k), mine.get(k)
        if a is None or b is None:
            diffs.append({"key": k, "issue": "row present on one side only"})
            continue
        st = a["frozen_status"].split(":")[-1].replace("BEYOND_DEV_END", "BEYOND_WINDOW_END")
        if st != b["bar_status"]:
            diffs.append({"key": k, "field": "bar_status", "frozen": st, "plumbing": b["bar_status"]})
        for f in CMP_FIELDS:
            if str(a[f]) != str(b[f]):
                diffs.append({"key": k, "field": f, "frozen": a[f], "plumbing": b[f]})

    def groups(rs, ident):
        g = defaultdict(set)
        for k, r in rs.items():
            if r["dup_group"].startswith("G"):
                g[(ident, r["dup_group"])].add(k)
        return sorted(sorted(v) for v in g.values())
    gd = groups(frozen, "f") != groups(mine, "p")
    unres = sorted(k for k, r in frozen.items() if r["dup_group"] == "UNRESOLVED") != \
        sorted(k for k, r in mine.items() if r["dup_group"] == "UNRESOLVED")
    return {"rows_frozen": len(frozen), "rows_plumbing": len(mine), "field_diffs": diffs[:50], "n_field_diffs": len(diffs),
            "duplicate_group_membership_differs": gd, "unresolved_duplicate_set_differs": unres}


def metric_parity() -> dict:
    """Stored corrected observations -> frozen cell_metrics / gate estimator (implementation check; identical inputs)."""
    import pandas as pd
    from research.event_response_map_v1 import metrics as M
    obs = pd.read_csv(STORED_RUN / "corrected_obs.csv", float_precision="round_trip")   # exact float round trip
    stored = json.loads((STORED_RUN / "corrected_cell.json").read_text())["corrected"]["metrics"]
    m = json.loads(json.dumps(M.cell_metrics(obs, "SHORT", "L1"), default=str))
    diffs = sorted(k for k in set(m) | set(stored) if m.get(k) != stored.get(k))
    x, grp, nmiss = G.pair_net(obs, 0.0, 0.0)                    # zero costs: must equal the frozen SHORT series
    g = G.gates(x, grp, nmiss)
    est = {"mean": g["mean"] == stored["mean_sector_relative"], "ci_low": g["ci_low"] == stored["ci_low"],
           "ci_high": g["ci_high"] == stored["ci_high"], "n": g["n_valid"] == stored["n"],
           "dates": g["distinct_dates"] == stored["distinct_dates"],
           "missing_exit_rate": g["missing_exit_rate"] == stored["missing_exit_rate"],
           "mean_without_top5": g["mean_without_top5"] == stored["mean_without_top5"]}
    return {"cell_metrics_diffs": diffs, "gate_estimator_equal_at_zero_cost": est}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", required=True, choices=sorted(WINDOWS))
    ap.add_argument("--parity", action="store_true")
    a = ap.parse_args(argv)
    cfg = ValidationConfig(a.window, OwnerDecisions())
    guard = ValidationGuard(cfg, HERE)
    if a.window != "DEV":
        cfg.require_decided()                                      # raises OwnerDecisionPending
        guard.check_acquisition(cfg.start, cfg.end, "window bars")  # unreachable today; would raise
        raise SystemExit("no validation acquisition path exists in this implementation")
    out = OUT / "dev_parity"
    if (out / "PARITY_COMPLETE.json").exists():
        raise SystemExit("dev parity already recorded; refusing to overwrite")
    out.mkdir(parents=True, exist_ok=True)
    rec = {"run": "ERM_NOMINEE_VALIDATION_PLUMBING_DEV_PARITY", "started_utc": now(), "config": cfg.canonical(),
           "config_hash": cfg.config_hash(), "guard_release_authorised": guard.release_authorised(),
           "code_sha256": {str(p.relative_to(HERE)): sha(p) for p in sorted((HERE / "research/erm_nominee_validation").glob("*.py"))}
           | {"research/erm_nominee_audit/v2_rules.py": sha(HERE / "research/erm_nominee_audit/v2_rules.py")},
           "frozen_manifest_sha256": sha(FROZEN_MANIFEST), "inventory": inventory(cfg)}
    rows, groups = build_dev(cfg, guard)
    rec["plumbing_manifest_sha256"] = B.write_manifest(rows, groups, out)
    rec["manifest_parity"] = manifest_parity(rows)
    rec["metric_parity"] = metric_parity() if a.parity else None
    mp, xp = rec["manifest_parity"], rec["metric_parity"] or {}
    ok = (mp["n_field_diffs"] == 0 and mp["rows_frozen"] == mp["rows_plumbing"] and not mp["duplicate_group_membership_differs"]
          and not mp["unresolved_duplicate_set_differs"] and not xp.get("cell_metrics_diffs")
          and all(xp.get("gate_estimator_equal_at_zero_cost", {}).values()))
    rec.update(status="PARITY_PASS" if ok else "PARITY_FAIL", ended_utc=now())
    B.atomic(out / "parity_record.json", json.dumps(rec, indent=1, default=str))
    if ok:
        B.atomic(out / "PARITY_COMPLETE.json", json.dumps({"utc": now(), "record_sha256": sha(out / "parity_record.json")}))
    print(json.dumps({k: rec[k] for k in ("status", "plumbing_manifest_sha256")} | {"manifest": {k: v for k, v in mp.items() if k != "field_diffs"}, "metric": xp}, default=str, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
