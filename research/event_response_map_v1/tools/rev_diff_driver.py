"""Differential driver (NOT part of the design lock): run the REAL phase_d.stage_run of one code root on a deterministic
synthetic fixture store and dump events, outcomes and every output for byte comparison.

  python rev_diff_driver.py <code_root> <dump_dir> [--workers N]

The fixture is written INSIDE <code_root>/results/event_response_map_v1 (a temporary copy of the code), so the run
never touches a real store, guard state or the network (the SEC archive is complete; Sec.get never reaches HTTP).
Bootstrap resamples are reduced to 200 for both revisions alike (identical for both: the comparison is code vs code).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import pickle
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
SEED = 20261004
YEARS = range(2019, 2024)
CIK = {f"S{i:02d}": f"{1000 + i:010d}" for i in range(40)}


def _sessions():
    out, d = [], date(2018, 11, 1)
    while d <= date(2023, 12, 29):
        if d.weekday() < 5 and not (d.month == 12 and d.day == 25) and not (d.month == 1 and d.day == 1):
            out.append(d)
        d += timedelta(days=1)
    return out


def _t(d: date) -> str:                                   # Alpaca daily bar stamp = midnight New York, in UTC
    return datetime(d.year, d.month, d.day, tzinfo=NY).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_fixture(root: Path) -> dict:
    import numpy as np
    rng = np.random.default_rng(SEED)
    out = root / "results" / "event_response_map_v1"
    arch = out / "_archive"
    ss = _sessions()

    def series(sym, base_price, vol, gap_p=0.06, drift_after_gap=0.0, missing=()):
        o, c, rows = base_price, base_price, []
        prev_gap = False
        for i, d in enumerate(ss):
            gap = rng.normal(0, 0.012)
            if rng.random() < gap_p:
                gap = rng.choice([1, -1]) * rng.uniform(0.031, 0.14)
            o = max(1.0, c * (1 + gap))
            intraday = rng.normal(0, 0.015) + (drift_after_gap if prev_gap else 0.0)
            c = max(1.0, o * (1 + intraday))
            if rng.random() < 0.0015:
                c = c * 2.2                              # occasional > 75 % jump -> SUSPECT_ADJUSTMENT path
            prev_gap = gap >= 0.03
            if d in missing:
                continue
            rows.append({"t": _t(d), "o": round(o, 4), "h": round(max(o, c), 4), "l": round(min(o, c), 4),
                         "c": round(c, 4), "v": float(vol)})
        return rows
    syms = sorted(CIK)
    ret = {}
    for i, s in enumerate(syms):
        price = [20, 60, 120][i % 3]
        vol = [1.5e6, 4e6, 2e7][i % 3]                    # L1 / L2 / L3 liquidity
        miss = set(rng.choice(len(ss), 12, replace=False).tolist()) if i % 7 == 0 else set()
        ret[s] = series(s, price, vol, drift_after_gap=0.012 if i % 3 == 2 else 0.0,
                        missing={ss[j] for j in miss})
    if True:                                              # a symbol delisted mid-period -> missing exits
        ret["S05"] = [b for b in ret["S05"] if b["t"] < "2021-06-01"]
    for b, p in (("SPY", 300.0), ("XLK", 120.0), ("XLF", 30.0), ("XLE", 60.0), ("XBI", 90.0), ("XLV", 110.0),
                 ("XLI", 95.0)):
        ret[b] = series(b, p, 5e7, gap_p=0.0)
    raw = {s: [dict(b, c=round(b["c"] * (2.0 if s in ("S03", "S04") and b["t"] < "2020-08-31" else 1.0), 4))
               for b in ret[s]] for s in syms}            # as-traded differs pre-split for S03/S04
    diag_syms = [f"D{i}" for i in range(6)]
    dret = {s: series(s, 40.0, 3e6) for s in diag_syms}

    def write_archive(d: Path, passes: dict):
        d.mkdir(parents=True, exist_ok=True)
        files = []
        for purpose, bars in passes.items():
            body = json.dumps({"bars": bars, "next_page_token": None}).encode()
            name = f"{purpose.lower()}_0000_000.json.gz"
            (d / name).write_bytes(gzip.compress(body, mtime=0))
            files.append({"file": name, "purpose": purpose, "sha256": hashlib.sha256(body).hexdigest()})
        (d / "manifest.json").write_text(json.dumps({"files": files}))
    write_archive(arch / "alpaca", {"RETURNS": ret, "ELIGIBILITY_ONLY": raw})
    write_archive(arch / "alpaca_diag", {"RETURNS": dret, "ELIGIBILITY_ONLY": dret})

    sec = arch / "sec"
    sec.mkdir(parents=True, exist_ok=True)
    put = lambda name, b: (sec / (name + ".gz")).write_bytes(gzip.compress(b, mtime=0))   # noqa: E731
    sics = ["7372", "6021", "1311", "2834", "3711", "9999"]
    items = ["2.02", "1.01", "5.02", "7.01", "8.01", "2.02,9.01", "1.01,7.01"]
    for i, s in enumerate(syms):
        recent = {"form": [], "filingDate": [], "accessionNumber": [], "items": [], "acceptanceDateTime": []}
        for k in range(70):
            d = ss[int(rng.integers(60, len(ss) - 5))]
            hh = int(rng.choice([7, 12, 16, 17, 21]))
            recent["form"].append("8-K" if k % 9 else "8-K/A")
            recent["filingDate"].append(d.isoformat())
            recent["accessionNumber"].append(f"{1000 + i:010d}-{d.year % 100:02d}-{k:06d}")
            recent["items"].append(items[k % len(items)])
            recent["acceptanceDateTime"].append(f"{d.isoformat()}T{hh:02d}:05:00.000Z")
        put(f"sub_CIK{CIK[s]}.json", json.dumps({"sic": sics[i % len(sics)],
                                                 "filings": {"recent": recent, "files": []}}).encode())
    owners = [f"{900000 + k:010d}" for k in range(8)]
    for y in YEARS:
        for q in range(1, 5):
            buf = io.BytesIO()
            sub_rows, own_rows, tr_rows = [], [], []
            n_acc = 0
            for s in syms[:20]:                           # clusters: >= 2 distinct owners within a few days
                for ep in range(2):
                    base = date(y, 3 * q - 2, 5) + timedelta(days=int(rng.integers(0, 60)))
                    for k in range(int(rng.integers(1, 4))):
                        fd = base + timedelta(days=k)
                        acc = f"{CIK[s]}-{y % 100:02d}-{q}{n_acc:05d}"
                        n_acc += 1
                        sub_rows.append({"ACCESSION_NUMBER": acc, "FILING_DATE": fd.strftime("%d-%b-%Y").upper(),
                                         "ISSUERCIK": str(int(CIK[s])), "ISSUERNAME": s,
                                         "ISSUERTRADINGSYMBOL": s if k < 2 else s.lower(), "DOCUMENT_TYPE": "4"})
                        own_rows.append({"ACCESSION_NUMBER": acc, "RPTOWNERCIK": owners[(k + ep) % 8],
                                         "RPTOWNERNAME": "X", "RPTOWNER_RELATIONSHIP": "Director",
                                         "RPTOWNER_TITLE": ""})
                        tr_rows.append({"ACCESSION_NUMBER": acc, "TRANS_CODE": "P" if k < 3 else "S",
                                        "TRANS_DATE": fd.strftime("%d-%b-%Y").upper(), "TRANS_SHARES": "1000",
                                        "TRANS_PRICEPERSHARE": "25", "DIRECT_INDIRECT_OWNERSHIP": "D"})
            with zipfile.ZipFile(buf, "w") as z:
                for fn, rows in (("SUBMISSION.tsv", sub_rows), ("REPORTINGOWNER.tsv", own_rows),
                                 ("NONDERIV_TRANS.tsv", tr_rows)):
                    s_io = io.StringIO()
                    w = csv.DictWriter(s_io, fieldnames=list(rows[0]), delimiter="\t")
                    w.writeheader()
                    w.writerows(rows)
                    z.writestr(f"{y}q{q}_form345/{fn}", s_io.getvalue())
            put(f"{y}q{q}_form345.zip", buf.getvalue())
    pit = out / "_fixture_pit.csv"
    with open(pit, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "tickers"])
        for y in YEARS:
            w.writerow([f"{y}-06-30", ",".join(syms[:10])])
    intervals = {CIK[s]: [[s, "1900-01-01", "9999-12-31"]] for s in syms}
    intervals[CIK["S01"]] = [["S01", "1900-01-01", "2021-03-01"], ["S01B", "2021-03-01", "9999-12-31"]]  # rename
    intervals[CIK["S02"]].append(["S02B", "1900-01-01", "9999-12-31"])                                  # dual class
    cand = {"symbols": {s: ["A"] for s in syms + diag_syms}, "names": {},
            "r3": {"kept": syms, "r1a_removed_for_survivorship_diagnostic": diag_syms,
                   "sic6770_windows": {"S06": [["2019-01-02", "2019-07-01"]]},
                   "intervals": intervals, "identity": {s: {"cik": CIK[s], "method": "SEC_TICKERS"} for s in syms}}}
    return {"cand": cand, "pit": pit}


def main() -> None:
    code_root, dump = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 1
    os.environ["ERM_EVAL_WORKERS"] = str(workers)
    sys.path.insert(0, str(code_root))
    import socket

    def _no_net(*a, **k):
        raise RuntimeError("NETWORK_REFUSED (differential driver)")
    socket.socket.connect = _no_net                      # fail loudly if anything tries the network
    fx = build_fixture(code_root)
    from research.event_response_map_v1 import metrics as M, phase_d as P, universe_source as US
    assert Path(P.__file__).resolve().is_relative_to(code_root), P.__file__
    US.PIT = fx["pit"]
    M.evaluate.__kwdefaults__["n_resamples"] = 200
    M.cell_metrics.__kwdefaults__["n_resamples"] = 200
    dump.mkdir(parents=True, exist_ok=True)
    real_outcomes = P.E.outcomes
    calls = []

    def outcomes(ev, bars, *a, **k):
        obs, counts = real_outcomes(ev, bars, *a, **k)
        calls.append(len(calls))
        n = len(calls)
        ev.reset_index(drop=True).to_csv(dump / f"events_{n}.csv", index=False)
        obs.reset_index(drop=True).to_csv(dump / f"outcomes_{n}.csv", index=False)
        (dump / f"outcome_counts_{n}.json").write_text(json.dumps(counts, sort_keys=True))
        return obs, counts
    P.E.outcomes = outcomes
    P.stage_run(fx["cand"])
    for f in ("cells.csv", "report.md", "trial_ledger.json", "d0_coverage.json"):
        src = P.OUT / f
        (dump / f).write_bytes(src.read_bytes() if src.exists() else b"<MISSING>")
    (dump / "screen.csv").write_bytes((P.OUT / "screen.csv").read_bytes() if (P.OUT / "screen.csv").exists()
                                      else b"<NOT_PRODUCED_BY_THIS_REVISION>")
    print(json.dumps({"code_root": str(code_root), "outcome_calls": len(calls)}))


if __name__ == "__main__":
    main()
