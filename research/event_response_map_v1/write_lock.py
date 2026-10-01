"""Writes results/event_response_map_v1/design_lock.json (Gate C). Not part of the fingerprint; it RECORDS it."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.event_response_map_v1 import data as D, metrics as M  # noqa: E402
from research.event_response_map_v1.fingerprint import file_hashes, fingerprint, lf_sha256  # noqa: E402
from research.event_response_map_v1.spec import SPEC  # noqa: E402

OUT = ROOT / "results" / "event_response_map_v1"


def ca_summary(ca: dict, cands: set) -> dict:
    from collections import Counter
    ev = ca["events"]
    sym = lambda e: str(e.get("symbol") or e.get("source_symbol") or e.get("old_symbol") or "").upper()  # noqa: E731
    return {"method": ca["method"], "events": len(ev),
            "by_type": dict(Counter(e.get("type") for e in ev)),
            "by_ex_year": dict(sorted(Counter(str(e.get("ex_date", ""))[:4] for e in ev).items())),
            "events_on_candidate_symbols": sum(1 for e in ev if sym(e) in cands),
            "candidate_symbols_with_split_or_spinoff": len({sym(e) for e in ev} & cands),
            "use": "metadata only: documents why eligibility needs as-traded D-1 values (adjusted floors would be look-ahead)"}


def main() -> dict:
    cand = json.loads((OUT / "candidates.json").read_text())
    audit = json.loads((OUT / "universe_source_audit.json").read_text())
    ca = json.loads((OUT / "ca_audit_v2_development.json").read_text())
    n = len(cand["symbols"]) + len(D.BENCHMARKS)
    batches = math.ceil(n / D.BATCH)
    lo, hi = D.estimate_requests(n, coverage=0.5), D.estimate_requests(n, coverage=1.0)
    plan = {
        "alpaca": {"symbols": n, "equity_candidates": len(cand["symbols"]), "benchmarks": list(D.BENCHMARKS),
                   "range": [D.DATA_START, D.DATA_END], "timeframe": "1Day", "feed": "sip", "batch": D.BATCH,
                   "batches_per_pass": batches,
                   "passes": {"RETURNS (adjustment=all, equities+benchmarks)": [lo, hi],
                              "ELIGIBILITY_ONLY (adjustment=raw, equities only; needs owner approval)": [lo, hi]},
                   "requests_total_range": [2 * lo, 2 * hi], "rate_per_min": 60 / D.MIN_SPACING_S,
                   "minutes_range": [round(2 * lo * D.MIN_SPACING_S / 60), round(2 * hi * D.MIN_SPACING_S / 60)]},
        "sec": {"company_tickers.json": 1, "cik-lookup-data.txt": 1, "form345_quarterly_zips_2019q1_2023q4": 20,
                "submissions_json": "one per mapped CIK + older pages overlapping 2019-2023; estimate 8,000-11,000",
                "rate_per_s": round(1 / 0.34, 2), "minutes_range": [45, 65]},
        "schedule": "OFF-HOURS ONLY, enforced in code for Alpaca AND SEC: weekday 13:00-20:30Z refused. Proposed: "
                    "stage=download on the first evening after go starting >= 21:00Z (or a weekend), ~2-2.5 h worst "
                    "case, finishing well before 13:00Z; stage=run reads the archive only (no network for prices).",
        "after_download": "D0 integrity report: per-year bar coverage of candidates and of the PIT S&P 500 reference, "
                          "missing/duplicate sessions, CIK-method counts, unnamed-symbol count",
    }
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    lock = {
        "program": "EVENT_RESPONSE_MAP_V1", "status": "DESIGN_LOCKED_GATE_C (no price data exists)",
        "locked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "branch": "research/event_response_map_v1", "base_sha": base,
        "fingerprint": fingerprint(ROOT), "file_sha256": file_hashes(ROOT),
        "candidates_sha256": lf_sha256(OUT / "candidates.json"),
        "candidates_sha256_note": "sha256 of LF-normalized bytes",
        "candidates": {"total": len(cand["symbols"]), "source_counts": cand["source_counts"],
                       "only_from": cand["only_from"], "named": len(cand["names"])},
        "universe_coverage_vs_pit_sp500_metadata": {y: {k: v[k] for k in ("sp500_members_any_day", "coverage_pct", "missing")}
                                                    for y, v in audit["coverage_vs_pit_sp500"].items()},
        "universe_source_audit": {k: audit[k] for k in ("assets_total", "assets_listed_common", "assets_listed_common_active",
                                                        "assets_listed_common_inactive", "name_changes_2019_2023",
                                                        "mergers_2019_2023")},
        "corporate_action_audit_v2_development": ca_summary(ca, set(cand["symbols"])),
        "cells": len(M.cells()), "independent_sign_tests": len(M.cells()) // 2,
        "spec": SPEC, "data_plan": plan,
    }
    (OUT / "design_lock.json").write_text(json.dumps(lock, indent=1, default=str))
    return lock


if __name__ == "__main__":
    lk = main()
    print(lk["fingerprint"], lk["candidates_sha256"], lk["cells"])
    print(json.dumps(lk["data_plan"]["alpaca"], indent=1))
    print(json.dumps(lk["corporate_action_audit_v2_development"], default=str)[:800])
