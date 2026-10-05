"""ERM nominee -- point-in-time R1a / S&P / SIC metadata (DEVELOPMENT only; no prices differenced, no returns).

Inputs: classified_events.csv (this audit), frozen archived SEC metadata, frozen DIAGNOSTIC bar archive (symbols the
frozen R1a removed; used only to find events a corrected rule could ADD -- bar presence/volume/eligibility only).

Per population row:
  issuer_pit      issuer used by the corrected rules (assigned CIK; re-mapped to the dated Form 3/4/5 issuer for
                  VERIFIED_DIFFERENT_SECURITY rows when that issuer is unique; '' if none)
  r1a_avail       unnamed: a 10-K/10-K/A/10-Q/10-Q/A of issuer_pit with EDGAR filing date <= D exists (any year;
                  master.idx 2019-2023 + archived submissions history <= 2023-12-29)
  r1a_recent365   unnamed: such a filing exists with filing date in [D-365, D]
  r1a_hist_trunc  the archived submissions history has unarchived older pages AND nothing qualifying was found
  sp_ever_by_D / sp_on_D / sp_frozen (any day 2019-2023)
  sic_hdr_acc     accession of issuer_pit's latest company filing (identity.COMPANY_FORMS) with filing date <= D
                  -> the point-in-time SIC source; sic_hdr_archived: whether the frozen archive already holds it
Additions: GAP_UP_10 events attached to L1 among frozen-R1a-REMOVED symbols that a corrected rule would admit.
Output: results/erm_nominee_audit/{pit_events.csv, pit_additions.csv, pit_summary.json, sic_header_todo.json}
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard  # noqa: E402
from research.event_response_map_v1 import data as D, events as E, identity as I, universe as U  # noqa: E402
from research.event_response_map_v1.instrument_filter import PERIODIC_FORMS, QUARTERS  # noqa: E402
from research.event_response_map_v1.universe_source import PIT  # noqa: E402

ERM = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1")
ARCH = ERM / "_archive"
OUT = HERE / "results" / "erm_nominee_audit"


def subs(cik: str):
    p = ARCH / "sec" / f"sub_CIK{cik}.json.gz"
    if not p.exists():
        return None
    m = json.loads(gzip.decompress(p.read_bytes()))
    blocks, missing = [m["filings"]["recent"]], []
    for f in m["filings"].get("files", []):
        q = ARCH / "sec" / ("sub_" + f["name"] + ".gz")
        (blocks.append(json.loads(gzip.decompress(q.read_bytes()))) if q.exists() else missing.append(f.get("filingTo")))
    rows = []
    for b in blocks:
        for i, fd in enumerate(b.get("filingDate", [])):
            if fd > "2023-12-29":
                continue
            rows.append((fd, b["form"][i], b["accessionNumber"][i]))
    rows.sort()
    return {"rows": rows, "missing_pages_to": missing}


def master_periodic():
    out = {}
    for q in QUARTERS:
        txt = gzip.decompress((ARCH / "sec" / ("master_" + q.replace("/", "_") + ".idx.gz")).read_bytes()).decode("latin-1")
        for line in txt.splitlines():
            p = line.split("|")
            if len(p) == 5 and p[0].strip().isdigit() and p[2].strip() in PERIODIC_FORMS:
                out.setdefault(p[0].strip().zfill(10), set()).add(p[3].strip())
    return out


def pit_sp():
    rows = []
    with open(PIT, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append((r["date"], {t.strip().upper() for t in r["tickers"].split(",") if t.strip()}))
    rows.sort(key=lambda x: x[0])
    first, frozen = {}, set()
    for d_, ts in rows:
        for t in ts:
            first.setdefault(t, d_)
        if "2019" <= d_[:4] <= "2023":
            frozen |= ts
    return rows, first, frozen


def main():
    ev = pd.read_csv(OUT / "classified_events.csv", dtype=str).fillna("")
    mp = master_periodic()
    sp_rows, sp_first, sp_frozen = pit_sp()
    sp_dates = [d_ for d_, _ in sp_rows]
    cache = {}

    def S(c):
        if c not in cache:
            cache[c] = subs(c) if c else None
        return cache[c]

    def r1a(cik, d0):
        """(avail, recent365, last_qual, truncated)"""
        if not cik:
            return False, False, "", False
        ds = set(mp.get(cik, ()))
        sb = S(cik)
        if sb:
            ds |= {fd for fd, f, _ in sb["rows"] if f in PERIODIC_FORMS}
        prior = sorted(x for x in ds if x <= d0)
        last = prior[-1] if prior else ""
        rec = bool(last) and last >= (date.fromisoformat(d0) - timedelta(days=365)).isoformat()
        trunc = (not prior) and bool(sb and sb["missing_pages_to"])
        return bool(prior), rec, last, trunc

    def sic_acc(cik, d0):
        sb = S(cik)
        if not sb:
            return ""
        best = [a for fd, f, a in sb["rows"] if fd <= d0 and f in I.COMPANY_FORMS]
        return best[-1] if best else ""

    out = []
    for r in ev.itertuples():
        issuer = r.cik
        if r.mapping == "VERIFIED_DIFFERENT_SECURITY":
            issuer = r.f345_last_issuer_by_D if (r.f345_conflict_by_D == "True" and r.f345_last_issuer_by_D) else ""
        d0 = r.gap_day
        av, rec, last, trunc = r1a(issuer, d0)
        k = bisect_right(sp_dates, d0) - 1
        acc = sic_acc(issuer, d0) if issuer else ""
        out.append({**r._asdict(), "issuer_pit": issuer, "r1a_avail": av, "r1a_recent365": rec,
                    "r1a_last_qual_by_D": last, "r1a_hist_trunc": trunc,
                    "sp_frozen": r.symbol in sp_frozen, "sp_on_D_": k >= 0 and r.symbol in sp_rows[k][1],
                    "sp_ever_by_D_": bool(sp_first.get(r.symbol)) and sp_first[r.symbol] <= d0,
                    "sic_hdr_acc": acc,
                    "sic_hdr_archived": bool(acc) and (ARCH / "sec" / f"hdr_{acc}.html.gz").exists()})
    pe = pd.DataFrame(out).drop(columns=["Index"])
    pe.to_csv(OUT / "pit_events.csv", index=False)

    # ---------------- additions from frozen-R1a-removed symbols (diagnostic archive)
    r3 = json.loads((ERM / "candidates_r3.json").read_text())
    removed = set(r3["r1a_removed_for_survivorship_diagnostic"])
    guard = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
    main_bars, _ = D.load(ARCH / "alpaca", purpose="RETURNS", guard=guard)
    sessions = sorted(main_bars.loc[main_bars["symbol"] == "SPY", "date"].unique())
    del main_bars
    db, _ = D.load(ARCH / "alpaca_diag", purpose="RETURNS", guard=guard)
    dr, _ = D.load(ARCH / "alpaca_diag", purpose="ELIGIBILITY_ONLY", guard=guard)
    db, dr = db[db["symbol"].isin(removed)], dr[dr["symbol"].isin(removed)]
    dr_traded = dr[dr["volume"] > 0]
    elig_frozen = U.eligibility(dr, sessions)
    elig_traded = U.eligibility(dr_traded, sessions)
    gaps = E.gap_events(db, sessions)
    gaps = gaps[gaps["event_type"] == "GAP_UP_10"].drop(columns="gap")
    vol = {s: dict(zip(g["date"], g["volume"])) for s, g in db.groupby("symbol")}
    adds = []
    for tag, el in (("frozen_bar_rule", elig_frozen), ("traded_bar_rule", elig_traded)):
        a = E.attach_bucket(E.dedup(gaps), el)
        a = a[a["bucket"] == "L1"]
        for x in a.itertuples(index=False):
            cik = r3["identity"].get(x.symbol, {}).get("cik") or ""
            d0 = x.event_date.isoformat()
            av, rec, last, trunc = r1a(cik, d0)
            k = bisect_right(sp_dates, d0) - 1
            prev = sessions[sessions.index(x.event_date) - 1]
            adds.append({"bar_rule": tag, "symbol": x.symbol, "gap_day": d0, "entry": x.entry_date.isoformat(),
                         "cik": cik, "r1a_avail": av, "r1a_recent365": rec, "r1a_last_qual_by_D": last,
                         "r1a_hist_trunc": trunc,
                         "sp_ever_by_D": bool(sp_first.get(x.symbol)) and sp_first[x.symbol] <= d0,
                         "sp_on_D": k >= 0 and x.symbol in sp_rows[k][1],
                         "vol0_prev_or_gap": vol[x.symbol].get(prev) == 0 or vol[x.symbol].get(x.event_date) == 0})
    ad = pd.DataFrame(adds)
    ad.to_csv(OUT / "pit_additions.csv", index=False)
    todo = sorted({(r.issuer_pit, r.sic_hdr_acc) for r in pe.itertuples() if r.sic_hdr_acc and not r.sic_hdr_archived})
    (OUT / "sic_header_todo.json").write_text(json.dumps([{"cik": c, "accession": a} for c, a in todo], indent=0))
    summ = {"rows": len(pe), "sic_header_needed_distinct": int(pe.loc[pe.sic_hdr_acc != "", "sic_hdr_acc"].nunique()),
            "sic_header_already_archived": int(pe.loc[pe.sic_hdr_archived, "sic_hdr_acc"].nunique()),
            "sic_header_to_fetch": len(todo), "rows_without_any_company_filing_by_D": int((pe.sic_hdr_acc == "").sum()),
            "diag_removed_symbols_with_bars": int(db["symbol"].nunique()), "additions_candidates": len(ad)}
    (OUT / "pit_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
