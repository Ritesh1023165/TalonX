"""Targeted SEC METADATA: submissions JSON (and older pages overlapping <= 2023-12-29) for VERIFIED V2 issuers whose
submissions were never archived by Phase D (needed for availability-based R1a and point-in-time SIC accessions).
Frozen phase_d.Sec (R5 off-hours, declared UA, <= 3 req/s); separate archive results/erm_nominee_audit/_sec_v2/."""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from research.event_response_map_v1.phase_d import Sec  # noqa: E402

AUD = HERE / "results" / "erm_nominee_audit"
m = pd.read_csv(AUD / "v2" / "manifest.csv", dtype=str).fillna("")
ciks = sorted(set(m.loc[m.sic_source == "NO_SUBMISSIONS_ARCHIVED", "issuer"]) - {""})
sec, got = Sec(AUD / "_sec_v2"), {}
try:
    for c in ciks:
        j = json.loads(sec.get(f"https://data.sec.gov/submissions/CIK{c}.json", f"sub_CIK{c}.json"))
        n = 1
        for f in j["filings"].get("files", []):
            if f.get("filingFrom", "9999") <= "2023-12-29":
                sec.get(f"https://data.sec.gov/submissions/{f['name']}", "sub_" + f["name"])
                n += 1
        got[c] = n
finally:
    sec.flush()
(AUD / "subs_v2_fetch_result.json").write_text(json.dumps({"ciks": len(ciks), "files": got}, indent=1))
print(len(ciks), sum(got.values()))
