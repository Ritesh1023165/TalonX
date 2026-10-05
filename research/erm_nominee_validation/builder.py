"""ERM nominee validation plumbing -- window-parameterised V2.1 manifest builder.

Applies the FROZEN V2.1 rules (research/erm_nominee_audit/v2_rules.py, imported unchanged) and the FROZEN map event /
eligibility functions (research/event_response_map_v1/{events,universe}.py, unchanged). The only window-specific
inputs are the gap-day bounds [start, end] (= the frozen DEV_START/DEV_END substituted for the window, [MAP->W]) and
the metadata evidence end (= window end). This module performs NO network access and NO download: every source is a
local, already-archived file passed in by the caller; a missing source is reported as absent evidence exactly as the
frozen no-fetch builder does.

Population = every GAP_UP_10 event attached to bucket L1 by the frozen (unmasked) eligibility, over every supplied bar
archive. For DEV this equals the frozen V2.1 populations A u B u C (A u C = unmasked main archive; B = diagnostic).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import threading
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from research.erm_nominee_audit import v2_rules as R
from research.event_response_map_v1 import events as E, identity as I, universe as U
from research.event_response_map_v1.instrument_filter import PERIODIC_FORMS


# ------------------------------------------------------------------------------------------------ window bounds
_BOUNDS_LOCK = threading.RLock()


@contextmanager
def window_bounds(start: date, end: date):
    """[MAP->W]: the frozen gap-day / exit bound is the module constant pair events.DEV_START/DEV_END. Substitute the
    window for the duration of the call and always restore it. Serialised by a process-wide lock so no two windows
    can ever share the substituted constants (separate processes have separate module state)."""
    with _BOUNDS_LOCK:
        old = (E.DEV_START, E.DEV_END)
        E.DEV_START, E.DEV_END = start, end
        try:
            yield
        finally:
            E.DEV_START, E.DEV_END = old


def population(eq, raw, sessions, start: date, end: date, tag: str) -> list[tuple]:
    with window_bounds(start, end):
        g = E.gap_events(eq, sessions)
    g = g[g["event_type"] == "GAP_UP_10"].drop(columns="gap")
    p = E.attach_bucket(E.dedup(g), U.eligibility(raw, sessions))
    p = p[p["bucket"] == "L1"]
    return [(tag, r.symbol, r.event_date, r.entry_date) for r in p.itertuples(index=False)]


def series(all_df, raw_df) -> dict:
    """symbol -> raw volume, raw open/close, (ALL/raw) factor tuples, set of dates with an ALL bar."""
    m = all_df.merge(raw_df, on=["symbol", "date"], suffixes=("_a", "_r"), how="outer")
    out = {}
    for s, g in m.groupby("symbol"):
        out[s] = {"vol": dict(zip(g["date"], g["volume_r"].fillna(0))),
                  "open": dict(zip(g["date"], g["open_r"])), "close": dict(zip(g["date"], g["close_r"])),
                  "fac": {d_: (oa, orr, ca, cr) for d_, oa, orr, ca, cr in
                          zip(g["date"], g["open_a"], g["open_r"], g["close_a"], g["close_r"])},
                  "has_all": set(g.loc[g["open_a"].notna(), "date"])}
    return out


# ------------------------------------------------------------------------------------------------ metadata (local only)
@dataclass
class Meta:
    names: dict
    frozen_cik: dict                      # symbol -> frozen CIK (provenance / mapping class only)
    edges: list
    f345: dict
    sp_rows: list
    periodic: dict
    subs: Callable                        # cik -> sorted [(filingDate, form, accession, items, reportDate)] | None
    header: Callable                      # accession -> (sic | None, source)
    etf_div: dict
    sic_to_etf: Callable


def f345_parse(zip_bytes: bytes, out: dict, end: str) -> None:
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
                if sym and cik.isdigit() and fd.isoformat() <= end:
                    out[sym].append((fd, cik.zfill(10)))


def subs_reader(dirs: list[Path], end: str) -> Callable:
    cache: dict = {}

    def subs(cik: str):
        if cik in cache:
            return cache[cik]
        base = next((b for b in dirs if (b / f"sub_CIK{cik}.json.gz").exists()), None)
        res = None
        if base is not None:
            m = json.loads(gzip.decompress((base / f"sub_CIK{cik}.json.gz").read_bytes()))
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
                    if fd > end:
                        continue
                    rows.append((fd, b["form"][i], b["accessionNumber"][i], str((b.get("items") or [""] * n)[i] or ""),
                                 str((b.get("reportDate") or [""] * n)[i] or "")))
            rows.sort()
            res = rows
        cache[cik] = res
        return res
    return subs


def header_reader(dirs: list[Path]) -> Callable:
    def header(acc: str):
        for b in dirs:
            p = b / f"hdr_{acc}.html.gz"
            if p.exists():
                return I.header_sic(gzip.decompress(p.read_bytes()).decode("latin-1")), "ARCHIVED"
        return None, "HEADER_NOT_ARCHIVED"            # never fetched: absent evidence
    return header


# ------------------------------------------------------------------------------------------------ rows
def build(pop: list, ser: dict, sessions: list, meta: Meta, end: date) -> tuple[list, list]:
    """Pure V2.1 manifest construction (no I/O). Returns (rows, duplicate_groups) sorted deterministically."""
    END = end.isoformat()
    idx = {d_: i for i, d_ in enumerate(sessions)}
    rows = []
    for tag, s, d0, ent in sorted(pop, key=lambda x: (x[3], x[1], x[0])):
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
        bar_status = ("BEYOND_WINDOW_END" if "BEYOND_WINDOW" in flags else
                      "DATA_MISSING_ENTRY" if ent not in S_["has_all"] else
                      "DATA_MISSING_EXIT" if ex not in S_["has_all"] else "VALID")
        idt = R.identity_at(s, d0, meta.edges, meta.f345, v)
        frozen_cik = meta.frozen_cik.get(s)
        mcls = R.mapping_class(idt, frozen_cik)
        if idt["identity"] != "VERIFIED_HISTORICAL_IDENTITY":
            flags.add("ID_UNRESOLVED")
        issuer = idt["issuer"]
        named = s in meta.names
        sp = R.sp_exempt(idt["ticker_at_D"], issuer, d0, meta.sp_rows, meta.f345, meta.edges)
        per = sorted(meta.periodic.get(issuer, set()) | {fd for fd, f, _, _, _ in (meta.subs(issuer) or [])
                                                         if f in PERIODIC_FORMS}) if issuer else []
        r1a_ok = R.r1a_available(per, d0)
        if not named and sp != "VERIFIED" and issuer and not r1a_ok:
            flags.add("R1A_NOT_AVAILABLE")
        sic, sic_src, sic_fd, acc, trans = None, "NO_ISSUER", None, "", []
        if issuer:
            sb = meta.subs(issuer) or []
            co = [(fd, a) for fd, f, a, _, _ in sb if fd <= d0.isoformat() and f in I.COMPANY_FORMS]
            trans = [(rd or fd, fd) for fd, f, _, it, rd in sb if f == "8-K" and "5.06" in it.split(",")]
            if co:
                sic_fd, acc = co[-1]
                sic, sic_src = meta.header(acc)
                sic_src = sic_src if sic else (sic_src if sic_src != "ARCHIVED" else "HEADER_WITHOUT_SIC")
            else:
                sic_src = "NO_COMPANY_FILING_BY_D" if sb else "NO_SUBMISSIONS_ARCHIVED"
        inst, sic_used = R.instrument_status(sic, sic_fd, trans, sp, d0)
        if issuer and inst == "SPAC":
            flags.add("INSTRUMENT_SPAC")
        if issuer and inst == "UNRESOLVED_INSTRUMENT":
            flags.add("INSTRUMENT_UNRESOLVED")
        bench = R.benchmark(inst, sic_used, meta.sic_to_etf) if issuer else ""
        if ex is not None and ex.isoformat() <= END:
            span = sessions[i0: i0 + 11]
            stock = R.leg_no_adjustment([S_["fac"].get(x) if x in S_["fac"] and all(
                y == y for y in S_["fac"][x]) else None for x in span])
            divs = meta.etf_div.get(bench, None) if bench else None
            etf = ("UNKNOWN" if not bench or divs is None else
                   "ADJUSTED" if any(ent.isoformat() < x <= ex.isoformat() for x in divs) else "NO_ADJUSTMENT")
        else:
            stock = etf = "UNKNOWN"
        rows.append({"archive": tag, "symbol": s, "gap_day": d0.isoformat(), "entry": ent.isoformat(),
                     "exit": ex.isoformat() if ex else "", "bar_status": bar_status, "frozen_cik": frozen_cik or "",
                     "named": named, "ticker_at_D": idt["ticker_at_D"] or "",
                     "relabel_chain": json.dumps([(o, n, str(x)) for o, n, x in idt["relabel_chain"]]),
                     "identity": idt["identity"], "identity_reason": idt["reason"], "issuer": issuer or "",
                     "evidence_date": str(idt["evidence_date"] or ""), "mapping_class": mcls, "sp_evidence": sp,
                     "r1a_available": r1a_ok, "sic_pit": sic or "", "sic_source": sic_src,
                     "sic_filing_date": sic_fd or "",
                     "s506_filed_by_D": sum(1 for r_, f_ in trans if f_ <= d0.isoformat()),
                     "s506_straddle_D": sum(1 for r_, f_ in trans if r_ <= d0.isoformat() < f_),
                     "s506_effective_after_D": sum(1 for r_, f_ in trans if r_ > d0.isoformat()),
                     "instrument": inst if issuer else "", "benchmark_v2": bench,
                     "exit_placeholder_or_missing": (ex is not None and (ex not in S_["has_all"] or v.get(ex) == 0)),
                     "traded_in_window": sum(1 for x in win if v.get(x)),
                     "sens_stock_leg": stock, "sens_etf_cash_dividend_leg": etf,
                     "sens_no_detected_stock_adj_or_etf_cash_div": R.sensitivity_member(stock, etf), "_flags": flags})
    groups_out = duplicates(rows, ser, sessions, idx)
    for r in rows:
        fr = R.first_reason(r["_flags"])
        r["flags"] = "|".join(sorted(r["_flags"]))
        r["first_reason"] = fr
        if fr:
            r["v2_status"] = "BEYOND_WINDOW" if fr == "BEYOND_WINDOW" else "EXCLUDED"
        elif r["bar_status"] == "DATA_MISSING_ENTRY":
            r["v2_status"] = "DATA_MISSING_ENTRY"
        elif r["exit_placeholder_or_missing"]:
            r["v2_status"] = "DATA_MISSING_EXIT"
        else:
            r["v2_status"] = "VALID"
        del r["_flags"]
    return rows, groups_out


def duplicates(rows: list, ser: dict, sessions: list, idx: dict) -> list:
    by_ent = defaultdict(list)
    for k, r in enumerate(rows):
        by_ent[r["entry"]].append(k)
    links, info = {}, {k: {"symbol": r["symbol"], "ticker_at_D": r["ticker_at_D"],
                           "traded_in_window": r["traded_in_window"]} for k, r in enumerate(rows)}
    for ent, ks in by_ent.items():
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                a, b = rows[ks[x]], rows[ks[y]]
                if a["symbol"] == b["symbol"]:
                    continue
                d0 = date.fromisoformat(a["gap_day"])
                win = sessions[idx[d0] - 19: idx[d0] + 1] + [date.fromisoformat(ent)]
                key = [sessions[idx[d0] - 1], d0, date.fromisoformat(ent)]
                ds = R.same_series({**ser[a["symbol"]], "window": win, "key": key},
                                   {**ser[b["symbol"]], "window": win, "key": key})
                if ds == "NOT_CANDIDATE":
                    continue
                ia = {k_: a[k_] for k_ in ("identity", "ticker_at_D", "issuer")}
                ib = {k_: b[k_] for k_ in ("identity", "ticker_at_D", "issuer")}
                links[(ks[x], ks[y])] = R.duplicate_link(ds, ia, ib)
    groups, unresolved = R.duplicate_groups(list(range(len(rows))), links)
    out = []
    for n, g in enumerate(groups):
        rep, why = R.representative(g, info)
        for mbr in g:
            rows[mbr]["dup_group"] = f"G{n:03d}"
            if mbr != rep:
                rows[mbr]["_flags"].add("DUP_NOT_REPRESENTATIVE")
        out.append({"group": f"G{n:03d}", "members": " ".join(rows[x]["symbol"] for x in g), "entry": rows[g[0]]["entry"],
                    "representative": rows[rep]["symbol"], "reason": why, "ticker_at_D": rows[rep]["ticker_at_D"],
                    "issuer": rows[rep]["issuer"]})
    for mbr in unresolved:
        rows[mbr]["_flags"].add("DUP_UNRESOLVED")
        rows[mbr]["dup_group"] = "UNRESOLVED"
    for r in rows:
        r.setdefault("dup_group", "")
    return out


# ------------------------------------------------------------------------------------------------ output
def atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def write_manifest(rows: list, groups: list, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    cols = [c for c in rows[0] if c != "_flags"]
    for name, data, fields in (("manifest.csv", rows, cols), ("duplicate_groups.csv", groups,
                                                              ["group", "members", "entry", "representative", "reason",
                                                               "ticker_at_D", "issuer"])):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(data)
        atomic(out / name, buf.getvalue())
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob("*.csv"))}
