"""ERM nominee -- V2.1 metadata-only manifest (DEVELOPMENT 2019-2023). Applies v2_rules deterministically.

Populations (boundaries):
  A  ORIGINAL   every GAP_UP_10 event attached to L1 by the frozen pipeline (Gate D pre-return population)
  B  DIAG_R1A   GAP_UP_10/L1 events of symbols the frozen R1a removed (frozen diagnostic archive; frozen eligibility)
  C  MASKED     GAP_UP_10/L1 events on symbol-days the frozen R7 SIC-6770 mask removed (main archive, mask lifted)
  Out of boundary: symbols removed by frozen R1b whole-period SIC 6770 (no bars archived) and candidates never in the
  frozen candidate list (stated limitation).
Reads bars only for presence, raw volume, and ALL/RAW at the SAME timestamp (adjustment factor) plus raw price equality
between two candidate-duplicate series at the SAME timestamp. No return, CI, screen or ranking.
Output: results/erm_nominee_audit/v2/{manifest.csv, unresolved_manifest.csv, duplicate_groups.csv, summary.json}
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard  # noqa: E402
from research.event_response_map_v1 import data as D, events as E, identity as I, universe as U  # noqa: E402
from research.event_response_map_v1.instrument_filter import PERIODIC_FORMS, QUARTERS  # noqa: E402
from research.event_response_map_v1.phase_d import FORM345_QUARTERS, Sec, mask_sic6770  # noqa: E402
from research.event_response_map_v1.universe_source import PIT  # noqa: E402
from research.erm_nominee_audit import v2_rules as R  # noqa: E402

ERM = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1")
ARCH = ERM / "_archive"
import os

# inputs (archived caches) and output are configurable so an isolated worktree can reconstruct independently
AUD = Path(os.environ.get("ERM_AUDIT_INPUTS", HERE / "results" / "erm_nominee_audit"))
OUT = Path(os.environ.get("ERM_V2_OUT", AUD / "v2_1"))
NO_FETCH = os.environ.get("ERM_NO_FETCH") == "1"      # verification mode: every input must already be archived
MAPPING = json.loads((HERE / "docs/research/preregistration/rs_sector_mapping_v1.json").read_text())["mapping"]
END = "2023-12-29"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def f345_parse(zip_bytes: bytes, out: dict) -> None:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.split("/")[-1].upper() == "SUBMISSION.TSV")
        with z.open(name) as fh:
            for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"), delimiter="\t"):
                sym, cik = I.norm_ticker(r.get("ISSUERTRADINGSYMBOL")), str(r.get("ISSUERCIK") or "").strip()
                raw = str(r.get("FILING_DATE", "")).strip()
                try:
                    fd = datetime.strptime(raw[:11], "%d-%b-%Y").date()
                except ValueError:
                    try:
                        fd = date.fromisoformat(raw[:10])
                    except ValueError:
                        continue
                if sym and cik.isdigit() and fd.isoformat() <= END:
                    out[sym].append((fd, cik.zfill(10)))


def load_meta():
    cand = json.loads((ERM / "candidates.json").read_text())
    r3 = json.loads((ERM / "candidates_r3.json").read_text())
    edges = I.rename_edges(json.loads((ERM / "_renames_2019_2023.json").read_text()) +
                           json.loads((ARCH / "alpaca_meta_renames_post2023.json").read_text()))
    f345 = defaultdict(list)
    for q in FORM345_QUARTERS:
        f345_parse(gzip.decompress((ARCH / "sec" / f"{q}_form345.zip.gz").read_bytes()), f345)
    for q in ("2018q1", "2018q2", "2018q3", "2018q4"):
        f345_parse(gzip.decompress((AUD / "_sec_v2" / f"{q}_form345.zip.gz").read_bytes()), f345)
    f345 = {k: sorted(set(v)) for k, v in f345.items()}
    sp_rows = []
    with open(PIT, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sp_rows.append((r["date"], {t.strip().upper() for t in r["tickers"].split(",") if t.strip()}))
    sp_rows.sort(key=lambda x: x[0])
    periodic = defaultdict(set)
    for q in QUARTERS:
        txt = gzip.decompress((ARCH / "sec" / ("master_" + q.replace("/", "_") + ".idx.gz")).read_bytes()).decode("latin-1")
        for line in txt.splitlines():
            p = line.split("|")
            if len(p) == 5 and p[0].strip().isdigit() and p[2].strip() in PERIODIC_FORMS:
                periodic[p[0].strip().zfill(10)].add(p[3].strip())
    etf_div = defaultdict(list)
    for r in json.loads((AUD / "_alpaca_v2" / "etf_cash_dividends.json").read_text()):
        etf_div[r["symbol"]].append(r["ex_date"])
    return cand, r3, edges, f345, sp_rows, periodic, etf_div


SUBS: dict = {}


def subs(cik: str):
    if cik in SUBS:
        return SUBS[cik]
    base = next((b for b in (ARCH / "sec", AUD / "_sec_v2") if (b / f"sub_CIK{cik}.json.gz").exists()), None)
    p = (base / f"sub_CIK{cik}.json.gz") if base else ARCH / "sec" / "__none__"
    res = None
    if p.exists():
        m = json.loads(gzip.decompress(p.read_bytes()))
        blocks = [m["filings"]["recent"]]
        for f in m["filings"].get("files", []):
            q = base / ("sub_" + f["name"] + ".gz")
            if q.exists():
                blocks.append(json.loads(gzip.decompress(q.read_bytes())))
        rows = []
        for b in blocks:
            n = len(b.get("filingDate", []))
            for i in range(n):
                fd = b["filingDate"][i]
                if fd > END:
                    continue
                rows.append((fd, b["form"][i], b["accessionNumber"][i], str((b.get("items") or [""] * n)[i] or ""),
                             str((b.get("reportDate") or [""] * n)[i] or "")))
        rows.sort()
        res = rows
    SUBS[cik] = res
    return res


def header_sic(acc: str, cik: str, sec: Sec | None, fetch_log: dict) -> tuple[str | None, str]:
    for p in (ARCH / "sec" / f"hdr_{acc}.html.gz", AUD / "_sec_pit" / f"hdr_{acc}.html.gz",
              AUD / "_sec_v2" / f"hdr_{acc}.html.gz"):
        if p.exists():
            return I.header_sic(gzip.decompress(p.read_bytes()).decode("latin-1")), "ARCHIVED"
    if sec is None or NO_FETCH or fetch_log.get("refused"):
        return None, "HEADER_NOT_ARCHIVED"
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}-index-headers.html"
    try:
        t = sec.get(url, f"hdr_{acc}.html").decode("latin-1")
        fetch_log["fetched"] = fetch_log.get("fetched", 0) + 1
        return I.header_sic(t), "FETCHED_V2"
    except D.MarketHoursRefusal:
        fetch_log["refused"] = True
        return None, "HEADER_NOT_ARCHIVED"
    except Exception as e:  # noqa: BLE001
        fetch_log.setdefault("failed", []).append(acc + ":" + type(e).__name__)
        return None, "HEADER_FETCH_FAILED"


def population(eq, raw, sessions, elig, tag):
    g = E.gap_events(eq, sessions)
    g = g[g["event_type"] == "GAP_UP_10"].drop(columns="gap")
    p = E.attach_bucket(E.dedup(g), elig)
    p = p[p["bucket"] == "L1"]
    return [(tag, r.symbol, r.event_date, r.entry_date) for r in p.itertuples(index=False)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cand, r3, edges, f345, sp_rows, periodic, etf_div = load_meta()
    names, ident = cand.get("names", {}), r3["identity"]
    guard = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
    a_all, _ = D.load(ARCH / "alpaca", purpose="RETURNS", guard=guard)
    a_raw, _ = D.load(ARCH / "alpaca", purpose="ELIGIBILITY_ONLY", guard=guard)
    d_all, _ = D.load(ARCH / "alpaca_diag", purpose="RETURNS", guard=guard)
    d_raw, _ = D.load(ARCH / "alpaca_diag", purpose="ELIGIBILITY_ONLY", guard=guard)
    sessions = sorted(a_all.loc[a_all["symbol"] == "SPY", "date"].unique())
    idx = {d_: i for i, d_ in enumerate(sessions)}
    eq = a_all[~a_all["symbol"].isin(D.BENCHMARKS)]
    removed = set(r3["r1a_removed_for_survivorship_diagnostic"])
    d_all, d_raw = d_all[d_all["symbol"].isin(removed)], d_raw[d_raw["symbol"].isin(removed)]
    el_frozen = mask_sic6770(U.eligibility(a_raw, sessions), r3["sic6770_windows"])[0]
    el_unmasked = U.eligibility(a_raw, sessions)
    popA = population(eq, a_raw, sessions, el_frozen, "A")
    keysA = {(s, ent) for _, s, _, ent in popA}
    popC = [x for x in population(eq, a_raw, sessions, el_unmasked, "C") if (x[1], x[3]) not in keysA]
    popB = population(d_all, d_raw, sessions, U.eligibility(d_raw, sessions), "B")
    pop = popA + popB + popC
    syms = {s for _, s, _, _ in pop}
    allb = pd.concat([a_all[a_all["symbol"].isin(syms)], d_all[d_all["symbol"].isin(syms)]])
    rawb = pd.concat([a_raw[a_raw["symbol"].isin(syms)], d_raw[d_raw["symbol"].isin(syms)]])
    m = allb.merge(rawb, on=["symbol", "date"], suffixes=("_a", "_r"), how="outer")
    ser = {}
    for s, g in m.groupby("symbol"):
        ser[s] = {"vol": dict(zip(g["date"], g["volume_r"].fillna(0))),
                  "open": dict(zip(g["date"], g["open_r"])), "close": dict(zip(g["date"], g["close_r"])),
                  "fac": {d_: (oa, orr, ca, cr) for d_, oa, orr, ca, cr in
                          zip(g["date"], g["open_a"], g["open_r"], g["close_a"], g["close_r"])},
                  "has_all": set(g.loc[g["open_a"].notna(), "date"])}
    sec = None if NO_FETCH else Sec(AUD / "_sec_v2")
    flog: dict = {}

    rows = []
    for tag, s, d0, ent in pop:
        S_ = ser[s]
        i0 = idx[ent]
        ex = sessions[i0 + 10] if i0 + 10 < len(sessions) else None
        prev = sessions[idx[d0] - 1]
        win = sessions[idx[d0] - 19: idx[d0] + 1]
        flags = set()
        if ex is None or ex.isoformat() > END:
            flags.add("BEYOND_WINDOW")
        v = S_["vol"]
        if not v.get(prev) or not v.get(d0):
            flags.add("C1_NO_GAP_PLACEHOLDER")
        if any(not v.get(x) for x in win):
            flags.add("C1_NOT_ELIGIBLE_PLACEHOLDER")
        if ent in S_["has_all"] and v.get(ent) == 0:
            flags.add("C1_ENTRY_PLACEHOLDER")
        frozen_status = ("BEYOND_DEV_END" if "BEYOND_WINDOW" in flags else
                         "DATA_MISSING_ENTRY" if ent not in S_["has_all"] else
                         "DATA_MISSING_EXIT" if ex not in S_["has_all"] else "VALID")
        if tag != "A":
            frozen_status = "NOT_IN_FROZEN_SAMPLE:" + frozen_status
        idt = R.identity_at(s, d0, edges, f345, v)
        frozen_cik = (ident.get(s) or {}).get("cik")
        mcls = R.mapping_class(idt, frozen_cik)
        if idt["identity"] != "VERIFIED_HISTORICAL_IDENTITY":
            flags.add("ID_UNRESOLVED")
        issuer = idt["issuer"]
        named = s in names
        sp = R.sp_exempt(idt["ticker_at_D"], issuer, d0, sp_rows, f345, edges)
        per = sorted(periodic.get(issuer, set()) | {fd for fd, f, _, _, _ in (subs(issuer) or []) if f in PERIODIC_FORMS}) if issuer else []
        r1a_ok = R.r1a_available(per, d0)
        if not named and sp != "VERIFIED" and issuer and not r1a_ok:
            flags.add("R1A_NOT_AVAILABLE")
        sic, sic_src, sic_fd, acc, trans = None, "NO_ISSUER", None, "", []
        if issuer:
            sb = subs(issuer) or []
            co = [(fd, a) for fd, f, a, _, _ in sb if fd <= d0.isoformat() and f in I.COMPANY_FORMS]
            # every archived 8-K item 5.06 (filed <= 2023-12-29): (effective lower bound = reportDate, publication)
            trans = [(rd or fd, fd) for fd, f, _, it, rd in sb if f == "8-K" and "5.06" in it.split(",")]
            if co:
                sic_fd, acc = co[-1]
                sic, sic_src = header_sic(acc, issuer, sec, flog)
                sic_src = sic_src if sic else (sic_src if sic_src != "ARCHIVED" else "HEADER_WITHOUT_SIC")
            else:
                sic_src = "NO_COMPANY_FILING_BY_D" if sb else "NO_SUBMISSIONS_ARCHIVED"
        inst, sic_used = R.instrument_status(sic, sic_fd, trans, sp, d0)
        if issuer and inst == "SPAC":
            flags.add("INSTRUMENT_SPAC")
        if issuer and inst == "UNRESOLVED_INSTRUMENT":
            flags.add("INSTRUMENT_UNRESOLVED")
        bench = R.benchmark(inst, sic_used, lambda x: E.sic_benchmark(x, MAPPING)) if issuer else ""
        # descriptive sensitivity evidence (both legs, entire holding interval)
        if ex is not None and ex.isoformat() <= END:
            span = sessions[i0: i0 + 11]
            stock = R.leg_no_adjustment([S_["fac"].get(x) if x in S_["fac"] and all(
                y == y for y in S_["fac"][x]) else None for x in span])
            divs = etf_div.get(bench, None) if bench else None
            etf = ("UNKNOWN" if not bench or divs is None else
                   "ADJUSTED" if any(ent.isoformat() < x <= ex.isoformat() for x in divs) else "NO_ADJUSTMENT")
        else:
            stock = etf = "UNKNOWN"
        rows.append({"pop": tag, "symbol": s, "gap_day": d0.isoformat(), "entry": ent.isoformat(),
                     "exit": ex.isoformat() if ex else "", "frozen_status": frozen_status,
                     "frozen_cik": frozen_cik or "", "named": named, "ticker_at_D": idt["ticker_at_D"] or "",
                     "relabel_chain": json.dumps([(o, n, str(x)) for o, n, x in idt["relabel_chain"]]),
                     "identity": idt["identity"], "identity_reason": idt["reason"], "issuer": issuer or "",
                     "evidence_date": str(idt["evidence_date"] or ""), "mapping_class": mcls,
                     "sp_evidence": sp, "r1a_available": r1a_ok, "sic_pit": sic or "", "sic_source": sic_src,
                     "sic_filing_date": sic_fd or "", "s506_filed_by_D": sum(1 for r_, f_ in trans if f_ <= d0.isoformat()),
                     "s506_straddle_D": sum(1 for r_, f_ in trans if r_ <= d0.isoformat() < f_),
                     "s506_effective_after_D": sum(1 for r_, f_ in trans if r_ > d0.isoformat()), "instrument": inst if issuer else "",
                     "benchmark_v2": bench,
                     "exit_placeholder_or_missing": (ex is not None and (ex not in S_["has_all"] or v.get(ex) == 0)),
                     "traded_in_window": sum(1 for x in win if v.get(x)),
                     "sens_stock_leg": stock, "sens_etf_cash_dividend_leg": etf,
                     "sens_no_detected_stock_adj_or_etf_cash_div": R.sensitivity_member(stock, etf),
                     "_flags": flags})
    # ---------------- duplicates (candidate generation by identical raw volume; corroboration by prices + lineage)
    by_ent = defaultdict(list)
    for k, r in enumerate(rows):
        by_ent[r["entry"]].append(k)
    links, info = {}, {}
    for k, r in enumerate(rows):
        info[k] = {"symbol": r["symbol"], "ticker_at_D": r["ticker_at_D"], "traded_in_window": r["traded_in_window"]}
    for ent, ks in by_ent.items():
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                a, b = rows[ks[x]], rows[ks[y]]
                if a["symbol"] == b["symbol"]:
                    continue
                d0 = date.fromisoformat(a["gap_day"])
                win = sessions[idx[d0] - 19: idx[d0] + 1] + [date.fromisoformat(ent)]
                key = [sessions[idx[d0] - 1], d0, date.fromisoformat(ent)]
                sa, sb_ = ser[a["symbol"]], ser[b["symbol"]]
                ds = R.same_series({**sa, "window": win, "key": key}, {**sb_, "window": win, "key": key})
                if ds == "NOT_CANDIDATE":
                    continue
                ia = {"identity": a["identity"], "ticker_at_D": a["ticker_at_D"], "issuer": a["issuer"]}
                ib = {"identity": b["identity"], "ticker_at_D": b["ticker_at_D"], "issuer": b["issuer"]}
                links[(ks[x], ks[y])] = (R.duplicate_link(ds, ia, ib), ds)   # all three classes kept
    groups, unresolved = R.duplicate_groups(list(range(len(rows))), {k: v[0] for k, v in links.items()})
    gid = {}
    grows = []
    for n, g in enumerate(groups):
        rep, why = R.representative(g, info)
        for mbr in g:
            gid[mbr] = f"G{n:03d}"
            if mbr != rep:
                rows[mbr]["_flags"].add("DUP_NOT_REPRESENTATIVE")
        grows.append({"group": f"G{n:03d}", "members": " ".join(rows[x]["symbol"] for x in g),
                      "entry": rows[g[0]]["entry"], "representative": rows[rep]["symbol"], "reason": why,
                      "ticker_at_D": rows[rep]["ticker_at_D"], "issuer": rows[rep]["issuer"]})
    for mbr in unresolved:
        rows[mbr]["_flags"].add("DUP_UNRESOLVED")
        gid[mbr] = "UNRESOLVED"
    nondup = Counter(v[1] for v in links.values())
    # ---------------- final status
    for k, r in enumerate(rows):
        fr = R.first_reason(r["_flags"])
        r["dup_group"] = gid.get(k, "")
        r["flags"] = "|".join(sorted(r["_flags"]))
        r["first_reason"] = fr
        if fr:
            r["v2_status"] = "BEYOND_WINDOW" if fr == "BEYOND_WINDOW" else "EXCLUDED"
        elif r["frozen_status"].endswith("DATA_MISSING_ENTRY"):
            r["v2_status"] = "DATA_MISSING_ENTRY"
        elif r["exit_placeholder_or_missing"]:
            r["v2_status"] = "DATA_MISSING_EXIT"
        else:
            r["v2_status"] = "VALID"
        del r["_flags"]
    cols = list(rows[0])
    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(OUT / "unresolved_manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows([r for r in rows if r["first_reason"] in ("ID_UNRESOLVED", "DUP_UNRESOLVED", "INSTRUMENT_UNRESOLVED")])
    with open(OUT / "duplicate_groups.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["group", "members", "entry", "representative", "reason", "ticker_at_D", "issuer"])
        w.writeheader()
        w.writerows(grows)
    if sec is not None:
        sec.flush()
    (OUT / "header_fetch_log.json").write_text(json.dumps(flog, indent=1))
    print(json.dumps({"rows": len(rows), "pop": dict(Counter(r["pop"] for r in rows)), "fetch": {k: (v if k != "failed" else len(v)) for k, v in flog.items()},
                      "dup_link_data_status": dict(nondup)}, indent=1))


if __name__ == "__main__":
    main()
