"""Window-parameterised ports of the frozen candidate (universe_source.build_candidates) and R3 identity / R1 scope
(r3_metadata.main) logic. PURE given parsed inputs + fetch callbacks; the frozen modules stay untouched and their
helpers are reused (identity.build_identity / rename_edges / dated_intervals / last_company_filing / header_sic /
sic_timeline / norm_ticker / norm_name, r3_metadata.r1a_reason, universe.candidates, universe_source.name_excluded).

Only the hard-coded period constants are replaced by the explicit AcquisitionPeriod fields:
  frozen 2019..2023 calendar years (sources B/C, D, R1a periodic, PIT exemption) -> corporate_actions_from/to,
                                                                                    sp500_from/to
  frozen DEV_START/DEV_END (Form 3/4/5 ticker observations)                     -> events_from/to
  frozen DEV_LO/DEV_HI, date(2023, 12, 30) (dev_filings, R7 sic_end)            -> filings_from/to (+1 day)
"""
from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from research.event_response_map_v1 import identity as I
from research.event_response_map_v1.instrument_filter import PERIODIC_FORMS
from research.event_response_map_v1.universe import SYMBOL_RE, candidates as U_candidates
from research.event_response_map_v1.universe_source import LISTED, name_excluded

BLANK_CHECK_SIC = "6770"


def form345_obs(zip_bytes: bytes, lo: date, hi: date) -> list[tuple[str, str, date]]:
    """= identity.form345_ticker_obs with the DEV_START/DEV_END filter made explicit."""
    out = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.split("/")[-1].upper() == "SUBMISSION.TSV")
        with z.open(name) as fh:
            for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"), delimiter="\t"):
                sym, cik = I.norm_ticker(r.get("ISSUERTRADINGSYMBOL")), str(r.get("ISSUERCIK") or "").strip()
                try:
                    fd = datetime.strptime(str(r.get("FILING_DATE", "")).strip()[:11], "%d-%b-%Y").date()
                except ValueError:
                    try:
                        fd = date.fromisoformat(str(r.get("FILING_DATE", "")).strip()[:10])
                    except ValueError:
                        continue
                if sym and cik.isdigit() and lo <= fd <= hi:
                    out.append((sym, cik.zfill(10), fd))
    return out


def master_periodic(text: str, lo: str, hi: str) -> set[str]:
    """= instrument_filter.parse_master_idx(...)[0] with PERIOD made explicit."""
    out = set()
    for line in text.splitlines():
        p = line.split("|")
        if len(p) != 5 or not p[0].strip().isdigit():
            continue
        if lo <= p[3].strip() <= hi and p[2].strip() in PERIODIC_FORMS:
            out.add(p[0].strip().zfill(10))
    return out


def sp_members(sp_csv_text: str, lo: date, hi: date) -> set[str]:
    """Any-day point-in-time S&P 500 members on list rows dated in [lo, hi] (frozen: calendar years 2019..2023)."""
    out = set()
    for r in csv.DictReader(io.StringIO(sp_csv_text)):
        if lo.isoformat() <= r["date"][:10] <= hi.isoformat():
            out |= {t.strip().upper() for t in r["tickers"].split(",") if t.strip()}
    return out


def build_candidates(assets: list[dict], renames: list[dict], mergers: list[dict], sp_csv_text: str, period) -> dict:
    """= universe_source.build_candidates with the period explicit. A: listed common assets (current list);
    B: pre-rename tickers of in-period name changes; C: in-period merger acquirees; D: in-period PIT S&P members."""
    a_common, names = set(), {}
    for a in assets:
        sym, ex = str(a.get("symbol", "")).upper(), a.get("exchange")
        if ex in LISTED and SYMBOL_RE.match(sym) and not name_excluded(a.get("name", "")):
            a_common.add(sym)
            names[sym] = a.get("name")
    b = {str(r["old_symbol"]).upper() for r in renames if r.get("old_symbol")}
    c = {str(r["acquiree_symbol"]).upper() for r in mergers if r.get("acquiree_symbol")}
    d = sp_members(sp_csv_text, period.sp500_from, period.sp500_to)
    cand = U_candidates(a_common, b, c, d)
    for r in renames:
        o, n = str(r.get("old_symbol", "")).upper(), str(r.get("new_symbol", "")).upper()
        if o and o not in names and n in names:
            names[o] = names[n]
    return {"symbols": cand, "names": {s: names[s] for s in cand if s in names},
            "source_counts": {k: sum(1 for v in cand.values() if k in v) for k in "ABCD"},
            "only_from": {k: sum(1 for v in cand.values() if v == [k]) for k in "ABCD"}}


@dataclass
class ScopeResult:
    candidates: dict
    identity: dict
    intervals: dict
    r1a_removed: list
    r1b_removed: list
    kept: list
    sic_timelines: dict
    submissions_ciks: list
    header_accessions: list


def build_scope(cand: dict, period, *, renames_in_period: list, renames_identity: list, company_tickers: dict,
                cik_lookup_text: str, f345_zips: list[bytes], master_texts: list[str], sp_csv_text: str,
                submissions_main, submissions_page, header_text) -> ScopeResult:
    """= r3_metadata.main (identity resolution, R1a, R6 intervals, R7 dated SIC, R1b) with the period explicit.
    Callbacks: submissions_main(cik) -> dict|None, submissions_page(name) -> dict|None, header_text(cik, acc) -> str|None.
    Every callback is a GUARDED, RECORDED acquisition supplied by the acquirer."""
    from research.event_response_map_v1.r3_metadata import r1a_reason
    names = cand.get("names", {})
    pit = sp_members(sp_csv_text, period.sp500_from, period.sp500_to)
    edges = I.rename_edges(renames_in_period + renames_identity)
    sec_tickers = {}
    for v in company_tickers.values():
        t = I.norm_ticker(v["ticker"])
        if t:
            sec_tickers.setdefault(t, str(v["cik_str"]).zfill(10))
    f345 = []
    for zb in f345_zips:
        f345 += form345_obs(zb, period.events_from, period.events_to)
    name_index = defaultdict(set)
    for line in cik_lookup_text.splitlines():
        parts = line.rstrip(":").rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            name_index[I.norm_name(parts[0])].add(parts[1].zfill(10))
    fetched = []
    for _ in range(2):                                            # frozen: two resolution passes
        ident = I.build_identity(cand, sec_tickers, edges, f345, name_index, pit)
        for cik in sorted({v["cik"] for v in ident.values() if v["cik"]}):
            m = submissions_main(cik)
            if cik not in fetched:
                fetched.append(cik)
            if not m:
                continue
            for t in m.get("tickers") or []:
                t = I.norm_ticker(t)
                if t:
                    sec_tickers.setdefault(t, cik)
            for nm in [m.get("name")] + [f.get("name") for f in m.get("formerNames") or []]:
                if nm:
                    name_index[I.norm_name(nm)].add(cik)
    ident = I.build_identity(cand, sec_tickers, edges, f345, name_index, pit)
    lo, hi = period.corporate_actions_from.isoformat(), period.corporate_actions_to.isoformat()
    periodic = set()
    for t in master_texts:
        periodic |= master_periodic(t, lo, hi)
    final_r1a = {}
    for s in cand["symbols"]:
        r = r1a_reason(s, names, ident[s]["cik"], periodic, pit, exempt=True)
        if r:
            final_r1a[s] = r
    intervals = I.dated_intervals(ident, edges)
    flo, fhi = period.filings_from.isoformat(), period.filings_to.isoformat()

    def dev_filings(cik):
        main = submissions_main(cik)
        if not main:
            return []
        docs = [main["filings"]["recent"]]
        for f in main["filings"].get("files", []):
            if f.get("filingTo", "9999") >= flo and f.get("filingFrom", "0000") <= fhi:
                pg = submissions_page(f["name"])
                if pg is not None:
                    docs.append(pg)
        rows = []
        for b in docs:
            n = len(b.get("form", []))
            for i in range(n):
                fd = b["filingDate"][i]
                if not (flo <= fd <= fhi):
                    continue
                rows.append({"form": b["form"][i], "filingDate": fd, "accessionNumber": b["accessionNumber"][i],
                             "items": (b.get("items") or [""] * n)[i], "acceptanceDateTime": b["acceptanceDateTime"][i]})
        return rows

    end_excl = period.filings_to + timedelta(days=1)
    sic_tl, headers = {}, []
    for cik in sorted(intervals):
        fl = dev_filings(cik)
        last = I.last_company_filing(fl, end_excl)
        sic_end = None
        if last:
            headers.append((cik, last["accessionNumber"]))
            t = header_text(cik, last["accessionNumber"])
            sic_end = I.header_sic(t) if t else None
        if sic_end is None:
            m = submissions_main(cik) or {}
            sic_end = m.get("sic") or None
        despac = sorted(f["filingDate"] for f in fl if f["form"] == "8-K" and "5.06" in str(f["items"]).split(","))
        dd, sic_before = None, None
        if despac:
            dd = date.fromisoformat(despac[-1])
            prev = I.last_company_filing(fl, dd)
            if prev:
                headers.append((cik, prev["accessionNumber"]))
                t = header_text(cik, prev["accessionNumber"])
                sic_before = I.header_sic(t) if t else None
        sic_tl[cik] = I.sic_timeline(sic_end, dd if sic_before else None, sic_before)
    final_r1b = {}
    for s, v in ident.items():
        cik = v["cik"]
        if not cik or s in final_r1a:
            continue
        tl = sic_tl.get(cik, [])
        if any(str(sic) == BLANK_CHECK_SIC for _, sic in tl) and len(tl) == 1:
            final_r1b[s] = "R1B_SIC_6770_WHOLE_PERIOD"
    removed = set(final_r1a) | set(final_r1b)
    kept = sorted(s for s in cand["symbols"] if s not in removed)
    return ScopeResult(candidates=cand, identity=ident, intervals=intervals, r1a_removed=sorted(final_r1a),
                       r1b_removed=sorted(final_r1b), kept=kept, sic_timelines=sic_tl, submissions_ciks=fetched,
                       header_accessions=sorted(set(headers)))
