"""Verification A -- recorded DEVELOPMENT replay through the production orchestration.

  python -m research.erm_nominee_validation.acquisition.dev_replay --out <dir>

ProductionAcquirer (S1..S8, unchanged production code) + RetryingTransport(ReplayTransport) + DevelopmentAcquisitionGuard
(frozen LockedRangeGuard for dated requests; broad endpoints authorised because only ARCHIVED development bytes are
served) -> ARCHIVE_MANIFEST -> ProductionLoader (sha256 verify, frozen data.load + LOAD guard) -> workflow.build_rows
(the BUILD stage) -> compare with the frozen development evidence:
  * scope parity     candidates (symbols + sources) vs candidates.json; kept / R1a-removed / R1b vs candidates_r3.json
  * request parity   every bar page served is a frozen Phase D page; bar manifest aggregates vs the frozen manifests
  * manifest parity  run.manifest_parity vs the frozen V2.1 manifest (every compared field, duplicate groups)
No outcome, gate or metric is computed (no research scoring).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HERE))
from research.erm_nominee_validation import builder as B  # noqa: E402
from research.erm_nominee_validation.acquisition.acquirer import ProductionAcquirer  # noqa: E402
from research.erm_nominee_validation.acquisition.guards import DevelopmentAcquisitionGuard  # noqa: E402
from research.erm_nominee_validation.acquisition.period import BROAD_ENDPOINTS  # noqa: E402
from research.erm_nominee_validation.acquisition.replay import ERM, ReplayTransport  # noqa: E402
from research.erm_nominee_validation.acquisition.transport import RetryingTransport  # noqa: E402
from research.erm_nominee_validation.adapters import ProductionLoader  # noqa: E402
from research.erm_nominee_validation.config import ValidationConfig  # noqa: E402

MAPPING = HERE / "docs/research/preregistration/rs_sector_mapping_v1.json"
OFF_HOURS = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)          # a Sunday: the frozen R5 check passes


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def scope_parity(arc: Path) -> dict:
    mine = json.loads((arc / "candidates.json").read_text())
    fc = json.loads((ERM / "candidates.json").read_text())
    r3 = json.loads((ERM / "candidates_r3.json").read_text())
    sm, sf = mine["symbols"], fc["symbols"]
    out = {"candidates_mine": len(sm), "candidates_frozen": len(sf),
           "only_mine": sorted(set(sm) - set(sf))[:20], "only_frozen": sorted(set(sf) - set(sm))[:20],
           "source_diffs": sorted(s for s in set(sm) & set(sf) if sorted(sm[s]) != sorted(sf[s]))[:20],
           "names_equal": mine["names"] == fc["names"]}
    sc = mine["scope"]
    r1b_frozen = sorted(s for s, v in r3["removed"].items() if any(str(x).startswith("R1B") for x in v))
    for k, fz in (("kept", sorted(r3["kept"])), ("r1a_removed", sorted(r3["r1a_removed_for_survivorship_diagnostic"])),
                  ("r1b_removed", r1b_frozen)):
        out[k] = {"mine": len(sc[k]), "frozen": len(fz), "equal": sorted(sc[k]) == fz,
                  "only_mine": sorted(set(sc[k]) - set(fz))[:10], "only_frozen": sorted(set(fz) - set(sc[k]))[:10]}
    ic = mine["identity_cik"]
    out["identity_cik_diffs"] = sum(1 for s, v in r3["identity"].items() if ic.get(s) != v.get("cik"))
    return out


def bars_parity(arc: Path) -> dict:
    out = {}
    for g, fz in (("KEPT", "alpaca"), ("R1A_REMOVED", "alpaca_diag")):
        a = json.loads((arc / "bars" / g / "manifest.json").read_text())
        b = json.loads((ERM / "_archive" / fz / "manifest.json").read_text())
        out[g] = {"pages": len(a["files"]), "frozen_pages": len(b["files"]),
                  "aggregate_equal": a["aggregate_sha256"] == b["aggregate_sha256"],
                  "page_sha_equal": [f["sha256"] for f in a["files"]] == [f["sha256"] for f in b["files"]]}
    return out


def main(argv=None) -> int:
    from research.erm_nominee_validation import run as RUN, workflow as W
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    if (out / "replay_record.json").exists():
        raise SystemExit("replay already recorded here; refusing to overwrite")
    out.mkdir(parents=True, exist_ok=True)
    cfg = ValidationConfig("DEV")
    guard = DevelopmentAcquisitionGuard(authorised_broad=tuple(BROAD_ENDPOINTS) + ("identity_renames",))
    rt = ReplayTransport()
    acq = ProductionAcquirer(guard, RetryingTransport(rt), bars_clock=lambda: OFF_HOURS, bars_sleep=lambda s: None,
                             download_date=date.today())
    rec = {"run": "ERM_ACQUISITION_DEV_RECORDED_REPLAY", "started_utc": now(), "window": "DEV",
           "transport": "RetryingTransport(ReplayTransport) -- archived development bytes only, no network"}
    arc = out / "archive"
    try:
        man = acq.acquire(cfg, arc)
        rec["archive_manifest"] = {"complete": man["complete"], "missing": man["missing"], "files": len(man["files"]),
                                   "sha256": hashlib.sha256((arc / "ARCHIVE_MANIFEST.json").read_bytes()).hexdigest()}
        rec["acquisition_status"] = json.loads((arc / "acquisition/acquisition_status.json").read_text())
        rec["guard_requests_checked"] = len(guard.log)
        rec["scope_parity"] = scope_parity(arc)
        rec["bars_parity"] = bars_parity(arc)
        loaded = ProductionLoader(guard, MAPPING).load(arc, cfg)
        rows, groups = W.build_rows(loaded, cfg)
        rec["manifest_sha256"] = B.write_manifest(rows, groups, out)
        rec["manifest_parity"] = RUN.manifest_parity(rows)
        ev = json.loads((arc / "acquisition/candidate_events.json").read_text())["events"]
        rec["candidate_events"] = {"n": len(ev), "manifest_rows": len(rows),
                                   "same_keys": sorted((e["symbol"], e["entry"]) for e in ev) ==
                                   sorted((r["symbol"], r["entry"]) for r in rows)}
        mp, sp, bp = rec["manifest_parity"], rec["scope_parity"], rec["bars_parity"]
        ok = (mp["n_field_diffs"] == 0 and mp["rows_frozen"] == mp["rows_plumbing"]
              and not mp["duplicate_group_membership_differs"] and not mp["unresolved_duplicate_set_differs"]
              and all(sp[k]["equal"] for k in ("kept", "r1a_removed", "r1b_removed"))
              and all(v["page_sha_equal"] for v in bp.values()) and rec["candidate_events"]["same_keys"])
        rec["status"] = "REPLAY_PARITY_PASS" if ok else "REPLAY_PARITY_DIFFERENCES"
    except Exception as e:  # noqa: BLE001 -- recorded
        import traceback
        rec["status"] = "REPLAY_FAILED"
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["traceback"] = traceback.format_exc(limit=8)
        st = arc / "acquisition/acquisition_status.json"
        rec["acquisition_status"] = json.loads(st.read_text()) if st.exists() else None
    rec["replay_requests_served"] = len(rt.served)
    rec["ended_utc"] = now()
    B.atomic(out / "replay_record.json", json.dumps(rec, indent=1, default=str))
    print(json.dumps({k: rec.get(k) for k in ("status", "error", "archive_manifest", "candidate_events")}, default=str,
                     indent=1))
    return 0 if rec["status"] == "REPLAY_PARITY_PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
