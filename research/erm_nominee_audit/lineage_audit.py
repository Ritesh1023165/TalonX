"""ERM nominee GAP_UP_10|SHORT|H10|L1 -- identity / point-in-time / bar-lineage audit (DEVELOPMENT 2019-2023 only).

READ-ONLY over the frozen Phase D archive (C:/workspace/TalonX-erm/results/event_response_map_v1). Uses metadata, bar
DATES and VOLUMES only. Never differences prices: no returns, CIs, screens or rankings are computed. The archive is
loaded through the frozen data.load (sha256-verified, LOAD guard enforced; the guard is never written).

Population = every GAP_UP_10 event attached to bucket L1 at its entry session by the frozen pipeline (incl. rows that
later become DATA_MISSING_ENTRY / DATA_MISSING_EXIT / BEYOND_DEV_END), i.e. the nominee's pre-return event records.

Output: results/erm_nominee_audit/{lineage_events.csv, lineage_summary.json}
usage: python -m research.erm_nominee_audit.lineage_audit   (cwd = this worktree)
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard  # noqa: E402
from research.event_response_map_v1 import data as D, events as E, identity as I, universe as U  # noqa: E402
from research.event_response_map_v1.instrument_filter import PERIODIC_FORMS, QUARTERS  # noqa: E402
from research.event_response_map_v1.phase_d import FORM345_QUARTERS, mask_sic6770  # noqa: E402
from research.event_response_map_v1.universe_source import PIT  # noqa: E402

ERM = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1")   # frozen inputs (read-only)
ARCH = ERM / "_archive"
OUT = HERE / "results" / "erm_nominee_audit"
ET, UTC = ZoneInfo("America/New_York"), ZoneInfo("UTC")
MAPPING = json.loads((HERE / "docs/research/preregistration/rs_sector_mapping_v1.json").read_text())["mapping"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_inputs() -> dict:
    cand = json.loads((ERM / "candidates.json").read_text())
    r3 = json.loads((ERM / "candidates_r3.json").read_text())
    renames = json.loads((ERM / "_renames_2019_2023.json").read_text()) + \
        json.loads((ARCH / "alpaca_meta_renames_post2023.json").read_text())
    return {"cand": cand, "r3": r3, "edges": I.rename_edges(renames)}


def form345_obs() -> tuple[dict, dict]:
    """sym -> sorted [(filing_date, cik)] ; (sym, cik) -> first filing date. Dated point-in-time ticker evidence."""
    by_sym = defaultdict(list)
    for q in FORM345_QUARTERS:
        for s, c, fd in I.form345_ticker_obs(gzip.decompress((ARCH / "sec" / f"{q}_form345.zip.gz").read_bytes())):
            by_sym[s].append((fd, c))
    first = {}
    for s, rows in by_sym.items():
        rows.sort()
        for fd, c in rows:
            first.setdefault((s, c), fd)
    return dict(by_sym), first


def periodic_dates() -> dict:
    """cik -> sorted filing dates of 10-K/10-K/A/10-Q/10-Q/A in master.idx 2019Q1..2023Q4 (archived)."""
    out = defaultdict(set)
    for q in QUARTERS:
        txt = gzip.decompress((ARCH / "sec" / ("master_" + q.replace("/", "_") + ".idx.gz")).read_bytes()).decode("latin-1")
        for line in txt.splitlines():
            p = line.split("|")
            if len(p) == 5 and p[0].strip().isdigit() and p[2].strip() in PERIODIC_FORMS:
                out[p[0].strip().zfill(10)].add(p[3].strip())
    return {c: sorted(v) for c, v in out.items()}


def submissions(cik: str) -> dict | None:
    """Archived submissions JSON rows dated <= 2023-12-29 (later rows skipped before any other field is read)."""
    p = ARCH / "sec" / f"sub_CIK{cik}.json.gz"
    if not p.exists():
        return None
    m = json.loads(gzip.decompress(p.read_bytes()))
    blocks, missing_pages = [m["filings"]["recent"]], []
    for f in m["filings"].get("files", []):
        q = ARCH / "sec" / ("sub_" + f["name"] + ".gz")
        (blocks.append(json.loads(gzip.decompress(q.read_bytes()))) if q.exists()
         else missing_pages.append({"name": f["name"], "from": f.get("filingFrom"), "to": f.get("filingTo")}))
    rows = []
    for b in blocks:
        for i, fd in enumerate(b.get("filingDate", [])):
            if fd > "2023-12-29":
                continue
            rows.append({"filingDate": fd, "form": b["form"][i], "acceptanceDateTime": b["acceptanceDateTime"][i]})
    rows.sort(key=lambda r: r["filingDate"])
    return {"rows": rows, "missing_pages": missing_pages, "current_sic": m.get("sic"),
            "current_tickers": m.get("tickers"), "name": m.get("name"),
            "former_names": m.get("formerNames") or []}


def pit_sp500() -> tuple[list, dict]:
    """Whole fja05680 point-in-time file: sorted [(date, set(tickers))]."""
    rows = []
    with open(PIT, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append((r["date"], {t.strip().upper() for t in r["tickers"].split(",") if t.strip()}))
    rows.sort(key=lambda x: x[0])
    first = {}
    for d_, ts in rows:
        for t in ts:
            first.setdefault(t, d_)
    return rows, first


def main() -> dict:
    inp = load_inputs()
    cand, r3, edges = inp["cand"], inp["r3"], inp["edges"]
    names, ident = cand.get("names", {}), r3["identity"]
    intervals = {c: [(s, date.fromisoformat(lo), date.fromisoformat(hi)) for s, lo, hi in v]
                 for c, v in r3["intervals"].items()}
    bysym = I.by_symbol(intervals)
    out_edges, in_edges = defaultdict(list), defaultdict(list)
    for o, n, d_ in edges:
        out_edges[o].append((d_, n))
        in_edges[n].append((d_, o))
    f345, f345_first = form345_obs()
    per = periodic_dates()
    pit_rows, pit_first = pit_sp500()
    pit_dates = [d_ for d_, _ in pit_rows]

    guard = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
    bars, _ = D.load(ARCH / "alpaca", purpose="RETURNS", guard=guard)
    raw, _ = D.load(ARCH / "alpaca", purpose="ELIGIBILITY_ONLY", guard=guard)
    sessions = sorted(bars.loc[bars["symbol"] == "SPY", "date"].unique())
    idx = {d_: i for i, d_ in enumerate(sessions)}
    eq = bars[~bars["symbol"].isin(D.BENCHMARKS)]
    elig = U.eligibility(raw, sessions)
    elig, _ = mask_sic6770(elig, r3["sic6770_windows"])
    gaps = E.gap_events(eq, sessions)
    gaps = gaps[gaps["event_type"] == "GAP_UP_10"].drop(columns="gap")
    pop = E.attach_bucket(E.dedup(gaps), elig)
    pop = pop[pop["bucket"] == "L1"].reset_index(drop=True)
    syms = set(pop["symbol"])
    vol = {s: dict(zip(g["date"], g["volume"])) for s, g in eq[eq["symbol"].isin(syms)].groupby("symbol")}
    rvol = {s: dict(zip(g["date"], g["volume"])) for s, g in raw[raw["symbol"].isin(syms)].groupby("symbol")}
    first_traded = {s: min((d_ for d_, v in vv.items() if v > 0), default=None) for s, vv in vol.items()}
    last_traded = {s: max((d_ for d_, v in vv.items() if v > 0), default=None) for s, vv in vol.items()}
    n_zero_rows = {s: sum(1 for v in vv.values() if v == 0) for s, vv in vol.items()}
    subs_cache: dict = {}

    def sub(c):
        if c not in subs_cache:
            subs_cache[c] = submissions(c)
        return subs_cache[c]

    def etf(sic):
        return E.sic_benchmark(sic, MAPPING)

    rows = []
    for r in pop.itertuples(index=False):
        s, d0, ent = r.symbol, r.event_date, r.entry_date
        i0 = idx[ent]
        dprev = sessions[idx[d0] - 1]
        ex = sessions[i0 + 10] if i0 + 10 < len(sessions) else None
        if ex is None or ex > E.DEV_END:
            status = "BEYOND_DEV_END"
        elif ent not in vol.get(s, {}):
            status = "DATA_MISSING_ENTRY"
        elif ex not in vol.get(s, {}):
            status = "DATA_MISSING_EXIT"
        else:
            status = "VALID"
        v = vol.get(s, {})
        win = sessions[idx[d0] - 19: idx[d0] + 1]                    # 20 sessions ending D (eligibility window)
        z_prev, z_gap = v.get(dprev) == 0, v.get(d0) == 0
        z_ent = v.get(ent) == 0
        z_exit = (ex is not None and v.get(ex) == 0)
        z_elig = sum(1 for x in win if rvol.get(s, {}).get(x) == 0)
        cik, method = ident[s]["cik"], ident[s]["method"]
        named, src = s in names, cand["symbols"][s]
        cik_on = {k: I.symbol_cik_on(s, dd, bysym) for k, dd in (("D", d0), ("entry", ent), ("exit", ex)) if dd}
        covered = bool(cik) and all(c == cik for c in cik_on.values())
        renamed_out_before = [(str(dd), n) for dd, n in out_edges.get(s, []) if dd <= d0]
        renamed_in_after = [(str(dd), o) for dd, o in in_edges.get(s, []) if dd > d0]
        # dated Form 3/4/5 evidence on or before D
        obs = [(fd, c) for fd, c in f345.get(s, []) if fd <= d0]
        last_obs_cik = obs[-1][1] if obs else None
        pit_link = bool(cik) and any(c == cik for _, c in obs)
        conflict = bool(obs) and last_obs_cik != cik
        later_link = bool(cik) and (s, cik) in f345_first and f345_first[(s, cik)] > d0
        # R1a availability (unnamed, non-exempt)
        k = bisect_right(pit_dates, d0.isoformat()) - 1
        sp_on_D = k >= 0 and s in pit_rows[k][1]
        sp_first = pit_first.get(s)
        sp_ever_by_D = sp_first is not None and sp_first <= d0.isoformat()
        r1a_needed = (not named)
        entry_open = datetime.combine(ent, time(9, 30), ET).astimezone(UTC)
        qual_dates = per.get(cik, []) if cik else []
        q_by_D = any(x <= d0.isoformat() for x in qual_dates)
        q_pre2019, trunc = False, False
        if cik and not q_by_D:
            sb = sub(cik)
            if sb:
                q_pre2019 = any(x["form"] in PERIODIC_FORMS and
                                E.edgar_acceptance_causal(x["acceptanceDateTime"]) < entry_open for x in sb["rows"])
                trunc = bool(sb["missing_pages"]) and not q_pre2019
        sb = sub(cik) if cik else None
        cur_sic = sb["current_sic"] if sb else None
        tl = [(date.fromisoformat(lo) if isinstance(lo, str) else lo, sic) for lo, sic in r3["sic_timelines"].get(cik, [])] if cik else []
        dated_sic = I.sic_on(tl, ent) if tl else None
        bench_used = etf(cur_sic) if I.symbol_cik_on(s, ent, bysym) else "SPY"          # = phase_d.bench_of
        rows.append({
            "symbol": s, "gap_day": d0.isoformat(), "prev_session": dprev.isoformat(), "entry": ent.isoformat(),
            "exit": ex.isoformat() if ex else "", "status": status, "named": named, "sources": "".join(src),
            "cik": cik or "", "id_method": method,
            "vol0_prev": z_prev, "vol0_gap": z_gap, "vol0_entry": z_ent, "vol0_exit": z_exit, "vol0_in_elig20": z_elig,
            "first_traded": str(first_traded.get(s)), "last_traded": str(last_traded.get(s)),
            "symbol_zero_volume_rows": n_zero_rows.get(s, 0),
            "interval_covers_D_entry_exit": covered, "cik_on_entry": cik_on.get("entry") or "",
            "renamed_out_before_D": json.dumps(renamed_out_before), "renamed_in_after_D": json.dumps(renamed_in_after),
            "f345_link_by_D": pit_link, "f345_conflict_by_D": conflict, "f345_link_only_after_D": later_link,
            "f345_last_issuer_by_D": last_obs_cik or "",
            "r1a_needed": r1a_needed, "sp_on_D": sp_on_D, "sp_first": sp_first or "", "sp_ever_by_D": sp_ever_by_D,
            "r1a_qual_2019_by_D": q_by_D, "r1a_qual_pre2019_by_entry": q_pre2019, "r1a_history_truncated": trunc,
            "current_sic": cur_sic or "", "dated_sic_r7": dated_sic or "", "bench_used_gateD": bench_used,
            "bench_assigned_cik_current_sic": etf(cur_sic) if cik else "SPY",
            "bench_dated_sic_r7": etf(dated_sic) if cik else "SPY",
        })
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "lineage_events.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    inputs = {str(p.relative_to(ERM)): sha(p) for p in (ERM / "candidates.json", ERM / "candidates_r3.json",
                                                         ERM / "_renames_2019_2023.json",
                                                         ARCH / "alpaca_meta_renames_post2023.json",
                                                         ARCH / "alpaca" / "manifest.json")}
    inputs["PIT_csv"] = sha(Path(PIT))
    summ = {"population": len(rows), "status": dict(Counter(x["status"] for x in rows)), "inputs_sha256": inputs,
            "pit_csv_span": [pit_rows[0][0], pit_rows[-1][0]]}
    (OUT / "lineage_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))
    return summ


if __name__ == "__main__":
    main()
