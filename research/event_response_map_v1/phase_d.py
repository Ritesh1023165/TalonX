"""EVENT_RESPONSE_MAP_V1 Phase D orchestrator -- LOCKED at Gate C, runs only after the owner's "go".

  python -m research.event_response_map_v1.phase_d --go --eligibility-raw-approved --stage download|run
  python -m research.event_response_map_v1.phase_d --stage r1-metadata     (lock rev 2, SEC metadata only, no go)

Refuses unless: --go is given, the design-lock fingerprint verifies, candidates.json matches its locked sha256, and the
raw ELIGIBILITY_ONLY pull is explicitly approved. Alpaca is called only through data.Downloader (guarded, off-hours,
<= 37.5/min). SEC is called at <= 3 req/s with a declared User-Agent; SEC bytes are archived like Alpaca bytes.
`run` reads ONLY the archive and executes the locked pipeline exactly once (refuses if outputs already exist).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard  # noqa: E402
from research.event_response_map_v1 import data as D, events as E, instrument_filter as R1, metrics as M, universe as U  # noqa: E402
from research.event_response_map_v1.fingerprint import lf_sha256, verify  # noqa: E402

OUT = ROOT / "results" / "event_response_map_v1"
ARCH = OUT / "_archive"
SEC_UA = {"User-Agent": "TalonX research ritesh.bgm48@gmail.com"}
SEC_SPACING_S = 0.34
FORM345_QUARTERS = [f"{y}q{q}" for y in range(2019, 2024) for q in range(1, 5)]
FORM345_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{}_form345.zip"


def preflight(args) -> dict:
    if not args.go:
        raise SystemExit("Phase D requires the owner's go (--go)")
    if not args.eligibility_raw_approved:
        raise SystemExit("raw ELIGIBILITY_ONLY pull not approved: V1 is not run (see design lock)")
    fp = verify(ROOT)
    lock = json.loads((OUT / "design_lock.json").read_text())
    cand_bytes = (OUT / "candidates.json").read_bytes()
    if lf_sha256(OUT / "candidates.json") != lock["candidates_sha256"]:
        raise SystemExit("candidates.json differs from the locked candidate list")
    if lf_sha256(OUT / "candidates_r1.json") != lock["candidates_r1_sha256"]:
        raise SystemExit("candidates_r1.json differs from the locked R1-filtered list")
    LockedRangeGuard(EVENT_RESPONSE_MAP_V1).record({"event": "phase_d_preflight", "fingerprint": fp})
    cand = json.loads(cand_bytes)
    cand["r1"] = json.loads((OUT / "candidates_r1.json").read_text())
    return cand


class Sec:
    def __init__(self, arch: Path):
        self.arch, self.last = arch, 0.0
        arch.mkdir(parents=True, exist_ok=True)
        self.manifest = json.loads((arch / "manifest.json").read_text()) if (arch / "manifest.json").exists() else {"files": []}

    def get(self, url: str, name: str) -> bytes:
        p = self.arch / (name + ".gz")
        if p.exists():                                        # archive is authoritative
            return gzip.decompress(p.read_bytes())
        from datetime import datetime, timezone
        if D.market_hours_blocked(datetime.now(timezone.utc)):   # live engine polls SEC from this IP too
            raise D.MarketHoursRefusal("SEC fetch: off-hours only (weekday 09:00-16:30 America/New_York blocked)")
        time.sleep(max(0.0, SEC_SPACING_S - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        body = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=120).read()
        p.write_bytes(gzip.compress(body, mtime=0))
        self.manifest["files"].append({"file": p.name, "url": url, "sha256": hashlib.sha256(body).hexdigest()})
        (self.arch / "manifest.json").write_text(json.dumps(self.manifest, indent=1))
        return body


def stage_download(cand: dict, headers: dict) -> None:
    syms = sorted(cand["r1"]["kept"])                       # LOCK REV 2: only R1-kept candidates are downloaded
    dl = D.Downloader(ARCH / "alpaca", headers)
    dl.pass_(syms + list(D.BENCHMARKS), purpose="RETURNS")
    dl.pass_(syms, purpose="ELIGIBILITY_ONLY")
    sec = Sec(ARCH / "sec")
    sec.get("https://www.sec.gov/files/company_tickers.json", "company_tickers.json")
    sec.get("https://www.sec.gov/Archives/edgar/cik-lookup-data.txt", "cik-lookup-data.txt")
    for q in FORM345_QUARTERS:
        sec.get(FORM345_URL.format(q), f"{q}_form345.zip")
    for cik in sorted({c for c, _ in cik_map(cand, sec).values() if c}):
        for _ in submissions(cik, sec):                     # fetch + archive every overlapping page
            continue


def cik_map(cand: dict, sec: Sec) -> dict:
    tick = json.loads(sec.get("https://www.sec.gov/files/company_tickers.json", "company_tickers.json"))
    sec_tickers = {str(v["ticker"]).upper().replace("-", "."): v["cik_str"] for v in tick.values()}
    lookup = []
    for line in sec.get("https://www.sec.gov/Archives/edgar/cik-lookup-data.txt", "cik-lookup-data.txt").decode(
            "latin-1").splitlines():
        parts = line.rstrip(":").rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            lookup.append((parts[0], parts[1]))
    renames = json.loads((OUT / "_renames_2019_2023.json").read_text())
    return U.map_ciks(cand["symbols"], sec_tickers, renames, cand.get("names", {}), lookup)


def submissions(cik: str, sec: Sec):
    """Yield (name, json) for the main submissions file and every older page overlapping the development period."""
    main = json.loads(sec.get(f"https://data.sec.gov/submissions/CIK{cik}.json", f"sub_CIK{cik}.json"))
    yield f"CIK{cik}", main
    for f in main.get("filings", {}).get("files", []):
        if f.get("filingTo", "9999") >= "2019-01-02" and f.get("filingFrom", "0000") <= "2023-12-29":
            yield f["name"], json.loads(sec.get(f"https://data.sec.gov/submissions/{f['name']}", "sub_" + f["name"]))


def _filings_frame(cik: str, sec: Sec):
    """Development-period filings only (rows outside 2019-01-02..2023-12-29 are skipped before any field is read)."""
    import pandas as pd
    rows = []
    for _, doc in submissions(cik, sec):
        block = doc.get("filings", {}).get("recent", doc)
        n = len(block.get("form", []))
        for i in range(n):
            fd = block["filingDate"][i]
            if not ("2019-01-02" <= fd <= "2023-12-29"):           # dropped before any other field is used
                continue
            rows.append({"cik": cik, "form": block["form"][i], "filingDate": fd,
                         "acceptanceDateTime": block["acceptanceDateTime"][i], "items": block.get("items", [""] * n)[i]})
    return pd.DataFrame(rows)


def stage_run(cand: dict) -> None:
    import pandas as pd
    if (OUT / "trial_ledger.json").exists():
        raise SystemExit("run-once: outputs already exist")
    guard = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
    bars, dq_all = D.load(ARCH / "alpaca", purpose="RETURNS", guard=guard)
    raw, dq_raw = D.load(ARCH / "alpaca", purpose="ELIGIBILITY_ONLY", guard=guard)
    sessions = sorted(bars.loc[bars["symbol"] == "SPY", "date"].unique())
    bench = {b: bars[bars["symbol"] == b] for b in D.BENCHMARKS}
    eq = bars[~bars["symbol"].isin(D.BENCHMARKS)]
    elig = U.eligibility(raw, sessions)
    sec = Sec(ARCH / "sec")
    cmap = cik_map(cand, sec)
    mapping = json.loads((ROOT / "docs/research/preregistration/rs_sector_mapping_v1.json").read_text())["mapping"]
    filings, symbol_bench, cik_to_symbol, inactive = [], {}, {}, 0
    for sym, (cik, how) in sorted(cmap.items()):
        if not cik:
            continue
        main = json.loads(sec.get(f"https://data.sec.gov/submissions/CIK{cik}.json", f"sub_CIK{cik}.json"))
        f = _filings_frame(cik, sec)
        if f.empty:
            cmap[sym] = (None, "UNMAPPED_INACTIVE_CIK")
            inactive += 1
            continue
        symbol_bench[sym] = E.sic_benchmark(main.get("sic"), mapping)
        cik_to_symbol.setdefault(cik, sym)
        filings.append(f)
    filings = pd.concat(filings, ignore_index=True) if filings else pd.DataFrame(
        columns=["cik", "form", "filingDate", "acceptanceDateTime", "items"])
    # FORM4_CLUSTER: V2@1 unchanged (task107a parser -> runtime from_rows -> detect_episodes)
    sp = importlib.util.spec_from_file_location("t107a", ROOT / "research/scripts/task107a_form4_build.py")
    t107 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(t107)
    from talonx_v2.cluster_engine import detect_episodes
    from talonx_v2.config import V2Config
    from talonx_v2.form4_source import from_rows
    rows = []
    for q in FORM345_QUARTERS:
        p = OUT / "_tmp_form345.zip"
        p.write_bytes(sec.get(FORM345_URL.format(q), f"{q}_form345.zip"))
        rows += t107.parse_zip(p)
        p.unlink()
    recs = from_rows([{"symbol": r["issuer_sym"], "issuer_cik": r.get("issuer_cik", ""), "owner_cik": r["owner_cik"],
                       "filing_date": r["filing_date"], "accession": r.get("accession", ""),
                       "transaction_date": r.get("trans_date"), "transaction_value": r.get("value"),
                       "is_officer": bool(r.get("is_officer")), "is_director": bool(r.get("is_director")),
                       "is_ten_percent": bool(r.get("is_ten_pct")), "transaction_code": "P"}
                      for r in rows if str(r.get("code", "")).upper() == "P"
                      and r.get("filing_date") and date(2019, 1, 2) <= r["filing_date"] <= date(2023, 12, 29)])
    ev = pd.concat([E.gap_events(eq, sessions).drop(columns="gap"),
                    E.eight_k_events(filings, cik_to_symbol, sessions).drop(columns="causal_utc"),
                    E.form4_cluster_events(detect_episodes(recs, config=V2Config()), sessions)], ignore_index=True)
    ev = E.attach_bucket(E.dedup(ev), elig)
    ev = pd.concat([ev, E.no_event_control(ev, elig, sessions)], ignore_index=True)
    obs, counts = E.outcomes(ev, eq, bench, symbol_bench, sessions)
    (OUT / "d0_coverage.json").write_text(json.dumps(d0_coverage(eq, elig, cand, obs), indent=1, default=str))
    ledger = M.evaluate(obs)
    calib = M.classify(ledger)                              # LOCK REV 2 (R2)
    (OUT / "trial_ledger.json").write_text(json.dumps({"null_calibration": calib, "cells": ledger, "integrity": {**counts, **dq_all,
        "eligibility_raw": dq_raw, "cik_methods": _count(m for _, m in cmap.values()),
        "unmapped_inactive_cik": inactive}}, indent=1, default=str))
    pd.DataFrame([{"cell": c["cell"], **{k: v for k, v in c["metrics"].items() if k != "per_year"},
                   **c["screen"]["criteria"], "SCREEN_PASS": c["screen"]["SCREEN_PASS"],
                   "nominatable": c["screen"]["nominatable"], "label": c["screen"]["label"]} for c in ledger]
                 ).to_csv(OUT / "cells.csv", index=False)
    (OUT / "report.md").write_text(report_md(calib, ledger, counts), encoding="utf-8", newline="\n")
    guard.record({"event": "phase_d_run_complete", "cells": len(ledger), "observations": len(obs),
                  "classification": calib["classification"]})


def report_md(calib: dict, ledger: list[dict], counts: dict) -> str:
    """LOCK REV 2 (R2): the NO_EVENT SCREEN_PASS count is the FIRST line of report.md."""
    passed = [c for c in ledger if c["screen"]["SCREEN_PASS"]]
    lines = [f"**NO_EVENT SCREEN_PASS: {calib['no_event_screen_pass']} of {calib['no_event_cells']}** -> "
             f"{calib['classification']}" + ("" if calib["nomination_allowed"] else
                                              " (no candidate may be nominated until explained)"),
             "", "# EVENT_RESPONSE_MAP_V1 -- Phase D report", "",
             f"- cells evaluated: {len(ledger)}; SCREEN_PASS: {calib['screen_pass_total']}; "
             f"nominatable: {calib['nominatable_cells']}",
             f"- integrity: {json.dumps(counts)}", "",
             "| cell | n | dates | mean sector-rel | CI | missing exit | label |", "|---|---|---|---|---|---|---|"]
    for c in passed:
        m = c["metrics"]
        lines.append(f"| {c['cell']} | {m['n']} | {m['distinct_dates']} | {m['mean_sector_relative']:+.4f} | "
                     f"[{m['ci_low']:+.4f}, {m['ci_high']:+.4f}] | {m['missing_exit_rate']:.2%} | {c['screen']['label']} |")
    return "\n".join(lines) + "\n"


def r1_metadata() -> dict:
    """LOCK REV 2 (R1), METADATA ONLY: CIK mapping, EDGAR master.idx 2019Q1-2023Q4 (10-K/10-Q filers) and the main
    submissions JSON of every mapped CIK (SIC). Archived in the SEC archive (reused by Phase D). Writes candidates_r1.json."""
    cand = json.loads((OUT / "candidates.json").read_text())
    sec = Sec(ARCH / "sec")
    cmap = cik_map(cand, sec)
    periodic = set()
    for q in R1.QUARTERS:
        body = sec.get(R1.MASTER_URL.format(q), "master_" + q.replace("/", "_") + ".idx")
        periodic |= R1.parse_master_idx(body.decode("latin-1"))[0]
    sic = {}
    for cik in sorted({c for c, _ in cmap.values() if c}):
        sic[cik] = json.loads(sec.get(f"https://data.sec.gov/submissions/CIK{cik}.json", f"sub_CIK{cik}.json")).get("sic")
    doc = R1.apply(cand, cmap, periodic, sic)
    doc["counts"]["cik_methods"] = _count(m for _, m in cmap.values())
    doc["counts"]["mapped_ciks"] = len(sic)
    R1.write(doc, OUT / "candidates_r1.json")
    return doc


def d0_coverage(eq, elig, cand: dict, obs=None) -> dict:
    """D0: per-year bar availability of candidates (by source) and of the PIT S&P 500 reference; eligible names/year.
    LOCK REV 2 (R4): also broken out by LIQUIDITY BUCKET x YEAR: eligible symbol-days, distinct symbols, share of
    eligible symbol-days with an ALL-adjusted bar on D, and the event missing-exit rate."""
    import csv
    from research.event_response_map_v1.universe_source import PIT
    yr = eq.assign(y=[d.year for d in eq["date"]]).groupby("y")["symbol"].apply(set).to_dict()
    members = {}
    with open(PIT, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            y = int(row["date"][:4])
            if 2019 <= y <= 2023:
                members.setdefault(y, set()).update(t.strip().upper() for t in row["tickers"].split(",") if t.strip())
    e = elig[elig["eligible"]]
    ey = e.assign(y=[d.year for d in e["date"]]).groupby("y")["symbol"].nunique().to_dict()
    out = {}
    for y in range(2019, 2024):
        have = yr.get(y, set())
        out[str(y)] = {"candidates_with_bars": len(have),
                       "by_source": {k: sum(1 for s, v in cand["symbols"].items() if k in v and s in have) for k in "ABCD"},
                       "pit_sp500_with_bars_pct": round(100 * len(members.get(y, set()) & have) / max(1, len(members.get(y, set()))), 2),
                       "pit_sp500_without_bars": sorted(members.get(y, set()) - have)[:50],
                       "eligible_symbols": int(ey.get(y, 0))}
    out["by_bucket_year"] = bucket_year_coverage(eq, elig, obs)
    return out


def bucket_year_coverage(eq, elig, obs=None) -> dict:
    e = elig[elig["eligible"]][["symbol", "date", "bucket"]]
    have = set(zip(eq["symbol"], eq["date"]))
    res = {}
    for (b, y), g in e.assign(y=[d.year for d in e["date"]]).groupby(["bucket", "y"]):
        pres = sum((s, d) in have for s, d in zip(g["symbol"], g["date"]))
        res[f"{b}|{y}"] = {"eligible_symbol_days": len(g), "distinct_symbols": int(g["symbol"].nunique()),
                           "all_bar_present_rate": round(pres / len(g), 6)}
    if obs is not None and len(obs):
        o = obs.assign(y=[d.year for d in obs["entry_date"]])
        for (b, y), g in o.groupby(["bucket", "y"]):
            res.setdefault(f"{b}|{y}", {})["missing_exit_rate"] = round(float(g["missing_exit"].mean()), 6)
    return dict(sorted(res.items()))


def _count(it) -> dict:
    out: dict = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--eligibility-raw-approved", action="store_true")
    ap.add_argument("--stage", choices=("download", "run", "r1-metadata"), required=True)
    args = ap.parse_args(argv)
    if args.stage == "r1-metadata":
        print(json.dumps(r1_metadata()["counts"], indent=1))
        return
    cand = preflight(args)
    if args.stage == "download":
        from research.event_response_map_v1.universe_source import headers
        stage_download(cand, headers())
    else:
        stage_run(cand)


if __name__ == "__main__":
    main()
