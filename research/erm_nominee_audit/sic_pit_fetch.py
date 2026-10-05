"""Narrow SEC METADATA acquisition for point-in-time SIC: the -index-headers.html of each nominee issuer's latest
company filing dated on/before the gap day (list from pit_rules.py -> sic_header_todo.json). Only filings dated
<= 2023-12-29 are requested (development period). No price, no outcome.

Uses the frozen phase_d.Sec client: R5 off-hours refusal (weekday 09:00-16:30 America/New_York), declared User-Agent,
<= 3 req/s, bytes archived with sha256 manifest -- but in a SEPARATE archive (results/erm_nominee_audit/_sec_pit/);
the frozen Phase D archive is read, never written. Resumable: archived headers are not re-requested.
Provenance: these are RETROSPECTIVE retrievals (2026) of documents that were PUBLIC at their filing date <= D, so the
SIC they state was available at the decision time.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from research.event_response_map_v1 import data as D, identity as I  # noqa: E402
from research.event_response_map_v1.phase_d import Sec  # noqa: E402

FROZEN = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1\_archive\sec")
OUT = HERE / "results" / "erm_nominee_audit"
ARCH = OUT / "_sec_pit"


def header_text(sec: Sec, cik: str, acc: str) -> str:
    p = FROZEN / f"hdr_{acc}.html.gz"
    if p.exists():
        return gzip.decompress(p.read_bytes()).decode("latin-1")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}-index-headers.html"
    return sec.get(url, f"hdr_{acc}.html").decode("latin-1")


def main():
    todo = json.loads((OUT / "sic_header_todo.json").read_text())
    sec = Sec(ARCH)
    got, refused, failed = 0, None, []
    try:
        for t in todo:
            try:
                header_text(sec, t["cik"], t["accession"])
                got += 1
            except D.MarketHoursRefusal as e:
                refused = str(e)
                break
            except Exception as e:  # noqa: BLE001 -- recorded, never retried silently
                failed.append({**t, "error": type(e).__name__ + ": " + str(e)[:120]})
    finally:
        sec.flush()
    res = {"todo": len(todo), "fetched_or_cached": got, "failed": failed, "stopped_by_R5": refused}
    (OUT / "sic_pit_fetch_result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: (v if k != "failed" else len(v)) for k, v in res.items()}, indent=1))


if __name__ == "__main__":
    main()
