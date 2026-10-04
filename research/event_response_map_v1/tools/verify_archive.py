"""Scoring-only preflight (runner tool, NOT part of the design lock): verify the archived Alpaca bytes BEFORE scoring.

  python verify_archive.py <expected_main_aggregate> <expected_diag_aggregate>

For each archive (alpaca, alpaca_diag): every manifest entry's file is re-hashed (sha256 of the decompressed body) and
must equal the manifest; the aggregate (sha256 of the concatenated per-file hashes, in manifest order, exactly as
data.Downloader.write_manifest computes it) must equal BOTH the pinned expected value AND a 'download_manifest'
aggregate recorded in the program's guard audit log. Prints one JSON line; exit 0 only if everything matches.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[3] / "results" / "event_response_map_v1"


def check(name: str, expected: str, audited: set[str]) -> dict:
    d = OUT / "_archive" / name
    man = json.loads((d / "manifest.json").read_text())
    bad = []
    for f in man["files"]:
        body = gzip.decompress((d / f["file"]).read_bytes())
        if hashlib.sha256(body).hexdigest() != f["sha256"]:
            bad.append(f["file"])
    agg = hashlib.sha256("".join(f["sha256"] for f in man["files"]).encode()).hexdigest()
    return {"archive": name, "files": len(man["files"]), "file_hash_mismatches": bad, "aggregate": agg,
            "matches_pinned": agg == expected, "matches_manifest": agg == man.get("aggregate_sha256"),
            "matches_guard_audit": agg in audited}


def main() -> int:
    exp_main, exp_diag = sys.argv[1], sys.argv[2]
    audit = json.loads((OUT / "guard_state.json").read_text())["audit"]
    audited = {e["aggregate"] for e in audit if e.get("event") == "download_manifest"}
    res = [check("alpaca", exp_main, audited), check("alpaca_diag", exp_diag, audited)]
    ok = all(not r["file_hash_mismatches"] and r["matches_pinned"] and r["matches_manifest"] and r["matches_guard_audit"]
             for r in res)
    print(json.dumps({"ARCHIVE_OK": ok, "archives": res}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
