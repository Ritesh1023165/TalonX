"""EVENT_RESPONSE_MAP_V1 LOCK REV 3 metadata stage (METADATA ONLY; Alpaca + SEC under the R5 off-hours guard).

  python -m research.event_response_map_v1.r3_metadata

Builds results/event_response_map_v1/candidates_r3.json:
  * identity resolution (identity.build_identity) -> R1a with the point-in-time S&P 500 exemption -> R1b on the DATED
    SIC (R7) -> kept / removed; R1a counts by source (B, C, D) and reason at three stages:
      rev2 (no exemption, rev-2 identity) | +S&P exemption (rev-2 identity) | +identity resolution (final)
  * dated ticker<->CIK intervals (R6), dated SIC timelines and SIC-6770 exclusion windows (R7)
  * 8-K attribution counts (R6) and the Form 3/4/5 dated-symbol audit, from metadata
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard  # noqa: E402
from research.event_response_map_v1 import identity as I, instrument_filter as R1  # noqa: E402
from research.event_response_map_v1.events import EIGHT_K_ITEMS  # noqa: E402
from research.event_response_map_v1.phase_d import ARCH, FORM345_QUARTERS, FORM345_URL, OUT, Sec  # noqa: E402
from research.event_response_map_v1.universe_source import PIT  # noqa: E402

DEV_LO, DEV_HI = "2019-01-02", "2023-12-29"


def pit_members() -> tuple[set, dict]:
    by_year = defaultdict(set)
    with open(PIT, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            y = int(row["date"][:4])
            if 2019 <= y <= 2023:
                by_year[y] |= {t.strip().upper() for t in row["tickers"].split(",") if t.strip()}
    return set().union(*by_year.values()), dict(by_year)


def sub_main(sec: Sec, cik: str) -> dict:
    return json.loads(sec.get(f"https://data.sec.gov/submissions/CIK{cik}.json", f"sub_CIK{cik}.json"))


def dev_filings(sec: Sec, cik: str) -> list[dict]:
    """Development-period filings of one CIK (main + overlapping older pages); rows outside the period are skipped
    before any other field is read."""
    main = sub_main(sec, cik)
    docs = [main["filings"]["recent"]]
    for f in main["filings"].get("files", []):
        if f.get("filingTo", "9999") >= DEV_LO and f.get("filingFrom", "0000") <= DEV_HI:
            docs.append(json.loads(sec.get(f"https://data.sec.gov/submissions/{f['name']}", "sub_" + f["name"])))
    rows = []
    for b in docs:
        n = len(b.get("form", []))
        for i in range(n):
            fd = b["filingDate"][i]
            if not (DEV_LO <= fd <= DEV_HI):
                continue
            rows.append({"form": b["form"][i], "filingDate": fd, "accessionNumber": b["accessionNumber"][i],
                         "items": (b.get("items") or [""] * n)[i], "acceptanceDateTime": b["acceptanceDateTime"][i]})
    return rows


def header_sic(sec: Sec, cik: str, acc: str) -> str | None:
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}-index-headers.html"
    return I.header_sic(sec.get(url, f"hdr_{acc}.html").decode("latin-1"))


def r1a_reason(sym: str, names: dict, cik: str | None, periodic: set, pit: set, exempt: bool) -> str | None:
    if sym in names or (exempt and sym in pit):
        return None
    if not cik:
        return "R1A_UNNAMED_NO_CIK"
    if cik not in periodic:
        return "R1A_UNNAMED_CIK_NO_10K_10Q_2019_2023"
    return None


def by_source(cand: dict, removed: dict) -> dict:
    out = defaultdict(Counter)
    for s, reason in removed.items():
        for src in cand["symbols"][s]:
            out[src][reason] += 1
    return {k: dict(v) for k, v in sorted(out.items())}


def main() -> dict:
    from research.event_response_map_v1.universe_source import headers
    guard = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
    cand = json.loads((OUT / "candidates.json").read_text())
    names = cand.get("names", {})
    r2 = json.loads((OUT / "candidates_r1.json").read_text())
    sec = Sec(ARCH / "sec")
    pit, pit_by_year = pit_members()
    # ---- identity sources
    post = I.fetch_post2023_renames(headers(), ARCH / "alpaca_meta_renames_post2023.json", guard)
    edges = I.rename_edges(json.loads((OUT / "_renames_2019_2023.json").read_text()) + post)
    tick = json.loads(sec.get("https://www.sec.gov/files/company_tickers.json", "company_tickers.json"))
    sec_tickers = {}
    for v in tick.values():
        t = I.norm_ticker(v["ticker"])
        if t:
            sec_tickers.setdefault(t, str(v["cik_str"]).zfill(10))
    f345 = []
    for q in FORM345_QUARTERS:
        f345 += I.form345_ticker_obs(sec.get(FORM345_URL.format(q), f"{q}_form345.zip"))
    name_index = defaultdict(set)
    for line in sec.get("https://www.sec.gov/Archives/edgar/cik-lookup-data.txt", "cik-lookup-data.txt").decode(
            "latin-1").splitlines():
        parts = line.rstrip(":").rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            name_index[I.norm_name(parts[0])].add(parts[1].zfill(10))
    # two passes: resolve, fetch submissions of new CIKs (their tickers / names / formerNames), resolve again
    for _ in range(2):
        ident = I.build_identity(cand, sec_tickers, edges, f345, name_index, pit)
        for cik in sorted({v["cik"] for v in ident.values() if v["cik"]}):
            m = sub_main(sec, cik)
            for t in m.get("tickers") or []:
                t = I.norm_ticker(t)
                if t:
                    sec_tickers.setdefault(t, cik)
            for nm in [m.get("name")] + [f.get("name") for f in m.get("formerNames") or []]:
                if nm:
                    name_index[I.norm_name(nm)].add(cik)
    ident = I.build_identity(cand, sec_tickers, edges, f345, name_index, pit)
    periodic = set()
    for q in R1.QUARTERS:
        periodic |= R1.parse_master_idx(sec.get(R1.MASTER_URL.format(q), "master_" + q.replace("/", "_") + ".idx")
                                        .decode("latin-1"))[0]
    # ---- R1a at three stages
    rev2_r1a = {s: [r for r in v if r.startswith("R1A")][0] for s, v in r2["removed"].items()
                if any(r.startswith("R1A") for r in v)}
    stage_exempt = {s: r for s, r in rev2_r1a.items() if s not in pit}
    final_r1a = {}
    for s in cand["symbols"]:
        r = r1a_reason(s, names, ident[s]["cik"], periodic, pit, exempt=True)
        if r:
            final_r1a[s] = r
    # ---- R6 dated intervals; R7 dated SIC
    intervals = I.dated_intervals(ident, edges)
    filings = {cik: dev_filings(sec, cik) for cik in sorted(intervals)}
    sic_tl, sic_src = {}, Counter()
    for cik, fl in sorted(filings.items()):
        last = I.last_company_filing(fl, date(2023, 12, 30))
        sic_end = header_sic(sec, cik, last["accessionNumber"]) if last else None
        if sic_end is None:
            sic_end = sub_main(sec, cik).get("sic") or None
            sic_src["CURRENT_SUBMISSIONS_SIC_FALLBACK"] += 1
        else:
            sic_src["HEADER_LAST_DEV_FILING"] += 1
        despac = sorted(f["filingDate"] for f in fl if f["form"] == "8-K" and "5.06" in str(f["items"]).split(","))
        dd, sic_before = None, None
        if despac:
            dd = date.fromisoformat(despac[-1])
            prev = I.last_company_filing(fl, dd)
            sic_before = header_sic(sec, cik, prev["accessionNumber"]) if prev else None
            sic_src["DESPAC_5_06_SPLIT"] += 1 if sic_before else 0
        sic_tl[cik] = I.sic_timeline(sic_end, dd if sic_before else None, sic_before)
    # R1b on the dated SIC: windows where SIC == 6770; a symbol is removed only if 6770 covers its whole validity
    sic6770_windows, final_r1b = {}, {}
    for s, v in ident.items():
        cik = v["cik"]
        if not cik or s in final_r1a:
            continue
        tl = sic_tl.get(cik, [])
        wins = []
        for i, (lo, sic) in enumerate(tl):
            hi = tl[i + 1][0] if i + 1 < len(tl) else I.FAR_FUTURE
            if str(sic) == "6770":
                wins.append((str(max(lo, I.DEV_START)), str(min(hi, date(2023, 12, 30)))))
        if wins:
            if len(tl) == 1:
                final_r1b[s] = "R1B_SIC_6770_WHOLE_PERIOD"
            else:
                sic6770_windows[s] = wins
    removed = {s: [final_r1a[s]] for s in final_r1a}
    for s, r in final_r1b.items():
        removed.setdefault(s, []).append(r)
    kept = sorted(s for s in cand["symbols"] if s not in removed)
    # ---- coverage of PIT S&P 500 per year
    cov = {str(y): {"members": len(m), "kept": len(m & set(kept)),
                    "coverage_pct": round(100 * len(m & set(kept)) / len(m), 2),
                    "removed": sorted(m - set(kept))} for y, m in sorted(pit_by_year.items())}
    # ---- R6 8-K attribution counts (metadata) and Form 3/4/5 audit
    kept_set = set(kept)
    k8 = Counter()
    k8_by_item = defaultdict(Counter)
    for cik, fl in filings.items():
        for f in fl:
            if f["form"] != "8-K":
                continue
            items = {x.strip() for x in str(f["items"]).split(",")} & set(EIGHT_K_ITEMS)
            if not items:
                continue
            sym, status = I.assign(cik, date.fromisoformat(f["filingDate"]), intervals)
            if status == "ASSIGNED" and sym not in kept_set:
                status = "ASSIGNED_TO_REMOVED_SYMBOL"
            k8[status] += 1
            for it in items:
                k8_by_item[it][status] += 1
    f4 = Counter()
    for sym, cik, fd in f345:
        if cik not in intervals:
            f4["CIK_NOT_IN_UNIVERSE"] += 1
            continue
        a, status = I.assign(cik, fd, intervals)
        f4[status if status != "ASSIGNED" else ("MATCH" if a == sym else "DISAGREE")] += 1
    counts = {
        "candidates_in": len(cand["symbols"]), "kept": len(kept), "removed_total": len(removed),
        "R1a_stage_rev2_no_exemption": {"total": len(rev2_r1a), "by_reason": dict(Counter(rev2_r1a.values())),
                                        "by_source": by_source(cand, rev2_r1a)},
        "R1a_stage_plus_sp500_exemption": {"total": len(stage_exempt), "by_reason": dict(Counter(stage_exempt.values())),
                                           "by_source": by_source(cand, stage_exempt)},
        "R1a_stage_plus_identity_resolution_FINAL": {"total": len(final_r1a),
                                                     "by_reason": dict(Counter(final_r1a.values())),
                                                     "by_source": by_source(cand, final_r1a)},
        "R1b_sic6770_whole_period_removed": len(final_r1b),
        "R1b_sic6770_partial_symbols_day_masked": len(sic6770_windows),
        "identity_methods": dict(Counter(v["method"] for v in ident.values())),
        "rev2_identity_methods": r2["counts"].get("cik_methods"),
        "post2023_rename_records": len(post), "rename_edges_total": len(edges),
        "form345_ticker_observations": len(f345),
        "r7_sic_sources": dict(sic_src), "ciks_with_dev_filings": sum(1 for v in filings.values() if v),
        "eight_k_target_items_attribution": dict(k8),
        "eight_k_by_item": {k: dict(v) for k, v in sorted(k8_by_item.items())},
        "form345_dated_symbol_audit": dict(f4),
        "pit_sp500_coverage": {y: {k: v[k] for k in ("members", "kept", "coverage_pct")} for y, v in cov.items()},
        "residual_limitation": "Alpaca renames processed inside the Task75 reserved windows (2024-06-01..09-02, "
                               "2024-10-21..12-20) were not queried; their identities rely on EDGAR sources only",
    }
    doc = {"kept": kept, "removed": removed, "r1a_removed_for_survivorship_diagnostic": sorted(final_r1a),
           "sic6770_windows": sic6770_windows,
           "identity": ident, "intervals": {c: [[s, str(lo), str(hi)] for s, lo, hi in v] for c, v in intervals.items()},
           "sic_timelines": {c: [[str(lo), s] for lo, s in v] for c, v in sic_tl.items()},
           "pit_sp500_coverage_detail": cov, "counts": counts}
    sec.flush()
    (OUT / "candidates_r3.json").write_text(json.dumps(doc, sort_keys=True, indent=0), encoding="utf-8", newline="\n")
    guard.record({"event": "lock_rev3_metadata", "kept": len(kept), "removed": len(removed)})
    return counts


if __name__ == "__main__":
    c = main()
    print(json.dumps(c, indent=1)[:6000])
