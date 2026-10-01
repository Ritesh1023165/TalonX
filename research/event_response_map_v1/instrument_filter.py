"""EVENT_RESPONSE_MAP_V1 LOCK REV 2 -- R1 instrument filter (METADATA ONLY, applied before any price download).

  R1a  a candidate WITHOUT a known name is kept only if it maps to a CIK that filed a 10-K or 10-Q (incl. /A) dated
       2019-01-01..2023-12-31 (EDGAR full-index master.idx, 2019Q1..2023Q4); otherwise EXCLUDED.
  R1b  any candidate whose mapped CIK has SIC 6770 (blank checks) is EXCLUDED. SIC = the CURRENT EDGAR assignment
       (submissions JSON 'sic'); a SPAC that later de-SPACed under the same CIK carries its new SIC (limitation).
Both rules are evaluated independently; counts are reported per rule and for the overlap.
Output: results/event_response_map_v1/candidates_r1.json (kept symbols + every removal with its reason).
"""
from __future__ import annotations

import json
from pathlib import Path

PERIODIC_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A"})
PERIOD = ("2019-01-01", "2023-12-31")
QUARTERS = [f"{y}/QTR{q}" for y in range(2019, 2024) for q in range(1, 5)]
MASTER_URL = "https://www.sec.gov/Archives/edgar/full-index/{}/master.idx"
BLANK_CHECK_SIC = 6770


def parse_master_idx(text: str) -> tuple[set[str], set[str]]:
    """master.idx (CIK|Company Name|Form Type|Date Filed|Filename) -> (CIKs with a periodic filing in PERIOD,
    CIKs with ANY filing in PERIOD). CIKs are zero-padded to 10."""
    periodic, any_ = set(), set()
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or not parts[0].strip().isdigit():
            continue
        cik, form, filed = parts[0].strip().zfill(10), parts[2].strip(), parts[3].strip()
        if not (PERIOD[0] <= filed <= PERIOD[1]):
            continue
        any_.add(cik)
        if form in PERIODIC_FORMS:
            periodic.add(cik)
    return periodic, any_


def apply(cand: dict, cmap: dict, periodic: set[str], sic_by_cik: dict) -> dict:
    """cand: candidates.json doc. cmap: symbol -> (cik|None, method). Returns the candidates_r1 doc."""
    names = cand.get("names", {})
    kept, removed = [], {}
    r1a = r1b = 0
    r1a_no_cik = r1a_cik_not_periodic = 0
    for s in sorted(cand["symbols"]):
        cik = cmap.get(s, (None, "UNMAPPED"))[0]
        reasons = []
        if s not in names:
            if not cik:
                reasons.append("R1A_UNNAMED_NO_CIK")
                r1a_no_cik += 1
            elif cik not in periodic:
                reasons.append("R1A_UNNAMED_CIK_NO_10K_10Q_2019_2023")
                r1a_cik_not_periodic += 1
        if cik and str(sic_by_cik.get(cik, "")).strip() == str(BLANK_CHECK_SIC):
            reasons.append("R1B_SIC_6770")
        r1a += any(r.startswith("R1A") for r in reasons)
        r1b += "R1B_SIC_6770" in reasons
        if reasons:
            removed[s] = reasons
        else:
            kept.append(s)
    return {"kept": kept, "removed": removed,
            "counts": {"candidates_in": len(cand["symbols"]), "kept": len(kept), "removed_total": len(removed),
                       "R1a_unnamed_removed": r1a, "R1a_unnamed_no_cik": r1a_no_cik,
                       "R1a_unnamed_cik_without_10k_10q": r1a_cik_not_periodic,
                       "R1b_sic_6770_removed": r1b,
                       "removed_by_both": sum(1 for v in removed.values() if len(v) == 2),
                       "unnamed_in": sum(1 for s in cand["symbols"] if s not in names),
                       "unnamed_kept": sum(1 for s in kept if s not in names),
                       "mapped_cik_sic_unknown": sum(1 for s in kept if cmap.get(s, (None,))[0]
                                                     and not sic_by_cik.get(cmap[s][0]))}}


def write(doc: dict, out: Path) -> None:
    out.write_text(json.dumps(doc, sort_keys=True, indent=0), encoding="utf-8", newline="\n")
