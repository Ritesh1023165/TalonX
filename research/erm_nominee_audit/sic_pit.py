"""ERM nominee -- point-in-time SIC per population row (metadata only).

sic_pit = SIC stated in the -index-headers.html of issuer_pit's latest company filing (identity.COMPANY_FORMS) with
EDGAR filing date <= D (accession chosen in pit_rules.py). Header bytes come from the frozen Phase D archive when
present, else from this audit's separate archive (sic_pit_fetch.py). Missing header / no company filing by D /
no issuer -> sic_pit '' (UNRESOLVED_SIC) -> benchmark SPY (the frozen SIC_ETF_MAP_V1 default for unknown SIC) and no
6770 mask. Output: results/erm_nominee_audit/sic_pit.csv, sic_pit_summary.json
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from research.event_response_map_v1 import events as E, identity as I  # noqa: E402

FROZEN = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1\_archive\sec")
OUT = HERE / "results" / "erm_nominee_audit"
MAPPING = json.loads((HERE / "docs/research/preregistration/rs_sector_mapping_v1.json").read_text())["mapping"]


def hdr(acc: str) -> str | None:
    for p in (FROZEN / f"hdr_{acc}.html.gz", OUT / "_sec_pit" / f"hdr_{acc}.html.gz"):
        if p.exists():
            return gzip.decompress(p.read_bytes()).decode("latin-1")
    return None


def main():
    e = pd.read_csv(OUT / "pit_events.csv", dtype=str).fillna("")
    rows = []
    for r in e.itertuples():
        if not r.issuer_pit:
            sic, src = "", "NO_ISSUER"
        elif not r.sic_hdr_acc:
            sic, src = "", "NO_COMPANY_FILING_BY_D"
        else:
            t = hdr(r.sic_hdr_acc)
            sic = (I.header_sic(t) or "") if t else ""
            src = ("HEADER" if sic else "HEADER_WITHOUT_SIC") if t else "HEADER_NOT_ARCHIVED"
        rows.append({"symbol": r.symbol, "entry": r.entry, "status": r.status, "sic_pit": sic, "sic_pit_source": src,
                     "bench_pit": E.sic_benchmark(sic, MAPPING) if sic else "SPY",
                     "bench_used_gateD": r.bench_used_gateD, "current_sic": r.current_sic,
                     "dated_sic_r7": r.dated_sic_r7})
    s = pd.DataFrame(rows)
    s.to_csv(OUT / "sic_pit.csv", index=False)
    v = s[s.status == "VALID"]
    summ = {"source_valid": v.sic_pit_source.value_counts().to_dict(),
            "sic6770_pit_valid": int((v.sic_pit == "6770").sum()),
            "sic_pit_ne_current_valid": int(((v.sic_pit != v.current_sic) & (v.sic_pit != "")).sum()),
            "bench_pit_ne_gateD_valid": int((v.bench_pit != v.bench_used_gateD).sum())}
    (OUT / "sic_pit_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
