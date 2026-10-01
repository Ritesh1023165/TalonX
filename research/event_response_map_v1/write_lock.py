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
    r1 = json.loads((OUT / "candidates_r1.json").read_text())
    r3 = json.loads((OUT / "candidates_r3.json").read_text())
    n = len(r3["kept"]) + len(D.BENCHMARKS)
    n_diag = len(r3["r1a_removed_for_survivorship_diagnostic"])
    dlo, dhi = D.estimate_requests(n_diag, coverage=0.5), D.estimate_requests(n_diag, coverage=1.0)
    batches = math.ceil(n / D.BATCH)
    lo, hi = D.estimate_requests(n, coverage=0.5), D.estimate_requests(n, coverage=1.0)
    plan = {
        "alpaca": {"symbols": n, "equity_candidates_after_R1_rev3": len(r3["kept"]), "benchmarks": list(D.BENCHMARKS),
                   "range": [D.DATA_START, D.DATA_END], "timeframe": "1Day", "feed": "sip", "batch": D.BATCH,
                   "batches_per_pass": batches,
                   "passes": {"RETURNS (adjustment=all, equities+benchmarks)": [lo, hi],
                              "ELIGIBILITY_ONLY (adjustment=raw, equities only; needs owner approval)": [lo, hi]},
                   "survivorship_diagnostic_passes (R1-FIX c; RETURNS + ELIGIBILITY_ONLY, archive alpaca_diag)":
                       {"symbols": n_diag, "requests_per_pass": [dlo, dhi]},
                   "requests_total_range": [2 * lo + 2 * dlo, 2 * hi + 2 * dhi], "rate_per_min": 60 / D.MIN_SPACING_S,
                   "minutes_range": [round((2 * lo + 2 * dlo) * D.MIN_SPACING_S / 60),
                                     round((2 * hi + 2 * dhi) * D.MIN_SPACING_S / 60)]},
        "sec": {"company_tickers.json": 1, "cik-lookup-data.txt": 1, "form345_quarterly_zips_2019q1_2023q4": 20,
                "master_idx_2019q1_2023q4": "20 (already archived at lock rev 2)",
                "submissions_json": "main file per mapped CIK already archived at lock rev 2 (R1 SIC); Phase D adds only older pages overlapping 2019-2023",
                "rate_per_s": round(1 / 0.34, 2)},
        "schedule": "OWNER: Sat 2026-10-03 from 14:00Z (live engine CLOSED phase), "
                    "--go --eligibility-raw-approved. Code-enforced R5 guard: weekday 09:00-16:30 America/New_York "
                    "refused for Alpaca and SEC. stage=run reads the archive only.",
        "after_download": "D0 integrity report: per-year bar coverage of candidates and of the PIT S&P 500 reference, "
                          "missing/duplicate sessions, CIK-method counts, unnamed-symbol count",
    }
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    lock = {
        "program": "EVENT_RESPONSE_MAP_V1", "status": f"DESIGN_LOCKED_GATE_C_REV{SPEC['lock_revision']} (no price data exists)",
        "lock_revision": SPEC["lock_revision"], "supersedes": {"rev1_commit": "067ed29", "rev1_fingerprint": "0b3799799c29802711c9ead7daeac5a91cf45fbeea1ecd7feee9ea982508e546",
                                           "rev2_commit": "8a57c33", "rev2_fingerprint": "bdf4a160426650715c772a738d563839804ab28fbb67b59ba0ff57fcc7cb7d22",
                                           "rev3_commit": "ed16b69", "rev3_fingerprint": "94013b3e8f3999b10de7beabf35d24b5953e70f48753fc3691790d278992a0c7"},
        "candidates_r3_sha256": lf_sha256(OUT / "candidates_r3.json"),
        "rev3_counts": r3["counts"],
        "locked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "branch": "research/event_response_map_v1", "base_sha": base,
        "fingerprint": fingerprint(ROOT), "file_sha256": file_hashes(ROOT),
        "candidates_sha256": lf_sha256(OUT / "candidates.json"),
        "candidates_sha256_note": "sha256 of LF-normalized bytes",
        "candidates_r1_sha256": lf_sha256(OUT / "candidates_r1.json"),
        "r1_instrument_filter_counts": r1["counts"],
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
