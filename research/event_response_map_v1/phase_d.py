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


def progress(stage: str, **counters) -> None:
    """LOCK REV 3.2: one JSON progress line (stage, counters, UTC) on stdout = the runner's phase_d_run.out.log."""
    from datetime import datetime, timezone
    print(json.dumps({"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "stage": stage, **counters},
                     default=str), flush=True)


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
    if lf_sha256(OUT / "candidates_r3.json") != lock["candidates_r3_sha256"]:
        raise SystemExit("candidates_r3.json differs from the locked revision-3 candidate list")
    LockedRangeGuard(EVENT_RESPONSE_MAP_V1).record({"event": "phase_d_preflight", "fingerprint": fp,
                                                   "lock_revision": lock.get("lock_revision")})
    cand = json.loads(cand_bytes)
    cand["r3"] = json.loads((OUT / "candidates_r3.json").read_text())
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
        if len(self.manifest["files"]) % 100 == 0:
            self.flush()
        return body

    def flush(self) -> None:
        """Write the manifest; any archived file missing from it (interrupted run) is added with its sha256."""
        listed = {f["file"] for f in self.manifest["files"]}
        for p in sorted(self.arch.glob("*.gz")):
            if p.name not in listed:
                self.manifest["files"].append({"file": p.name, "url": None,
                                               "sha256": hashlib.sha256(gzip.decompress(p.read_bytes())).hexdigest()})
        (self.arch / "manifest.json").write_text(json.dumps(self.manifest, indent=1), encoding="utf-8", newline="\n")


def stage_download(cand: dict, headers: dict) -> None:
    syms = sorted(cand["r3"]["kept"])                       # LOCK REV 3: only kept candidates form the universe
    dl = D.Downloader(ARCH / "alpaca", headers)
    dl.pass_(syms + list(D.BENCHMARKS), purpose="RETURNS")
    dl.pass_(syms, purpose="ELIGIBILITY_ONLY")
    diag = sorted(cand["r3"]["r1a_removed_for_survivorship_diagnostic"])   # R1-FIX c (non-gating diagnostic)
    dd = D.Downloader(ARCH / "alpaca_diag", headers)
    dd.pass_(diag, purpose="RETURNS")
    dd.pass_(diag, purpose="ELIGIBILITY_ONLY")
    sec = Sec(ARCH / "sec")
    sec.get("https://www.sec.gov/files/company_tickers.json", "company_tickers.json")
    sec.get("https://www.sec.gov/Archives/edgar/cik-lookup-data.txt", "cik-lookup-data.txt")
    for q in FORM345_QUARTERS:
        sec.get(FORM345_URL.format(q), f"{q}_form345.zip")
    for cik in sorted(cand["r3"]["intervals"]):             # already archived by the rev-3 metadata stage
        for _ in submissions(cik, sec):
            continue
    sec.flush()


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
    progress("loaded", returns_rows=len(bars), eligibility_rows=len(raw))
    sessions = sorted(bars.loc[bars["symbol"] == "SPY", "date"].unique())
    bench = {b: bars[bars["symbol"] == b] for b in D.BENCHMARKS}
    eq = bars[~bars["symbol"].isin(D.BENCHMARKS)]
    elig = U.eligibility(raw, sessions)
    r3 = cand["r3"]
    elig, n_masked = mask_sic6770(elig, r3["sic6770_windows"])              # R1b on the DATED SIC (R7)
    progress("eligibility", rows=len(elig), eligible=int(elig["eligible"].sum()), sic6770_masked=n_masked)
    intervals = {c: [(s_, date.fromisoformat(lo), date.fromisoformat(hi)) for s_, lo, hi in v]
                 for c, v in r3["intervals"].items()}
    from research.event_response_map_v1 import identity as I
    bysym = I.by_symbol(intervals)
    sec = Sec(ARCH / "sec")
    mapping = json.loads((ROOT / "docs/research/preregistration/rs_sector_mapping_v1.json").read_text())["mapping"]
    cur_sic = {c: json.loads(sec.get(f"https://data.sec.gov/submissions/CIK{c}.json", f"sub_CIK{c}.json")).get("sic")
               for c in intervals}

    def bench_of(sym, d):                                 # R6: dated ticker -> CIK, then that CIK's sector ETF
        c = I.symbol_cik_on(sym, d, bysym)
        return E.sic_benchmark(cur_sic.get(c), mapping) if c else "SPY"

    filings = pd.DataFrame([{**f, "cik": c} for c in sorted(intervals) for f in _dev_filings(c, sec)],
                           columns=["cik", "form", "filingDate", "acceptanceDateTime", "items", "accessionNumber"])
    form4_rows = _form4_p_rows(sec)
    progress("inputs", filings=len(filings), form4_p_rows=len(form4_rows))

    def events_for(bars_eq, elig_, tag="main"):
        # LOCK REV 3.2: the symbol set is built ONCE per call (attempt 1 rebuilt it per Form 4 row: phase_d.py:182)
        syms = set(bars_eq["symbol"].unique())
        has_bar = E.bar_presence(bars_eq)
        k8, k8c = E.eight_k_events_dated(filings, intervals, sessions, has_bar)
        k8 = k8[k8["symbol"].isin(syms)]
        progress("events_8k", pass_=tag, rows=len(k8), **k8c)
        f4rows, f4c = E.form4_rows_dated(form4_rows, intervals)
        f4rows = [r for r in f4rows if r["issuer_sym"] in syms]
        progress("events_form4", pass_=tag, rows=len(f4rows), **f4c)
        gaps = E.gap_events(bars_eq, sessions).drop(columns="gap")
        progress("events_gaps", pass_=tag, rows=len(gaps))
        ev_ = pd.concat([gaps, k8.drop(columns="causal_utc"),
                         E.form4_cluster_events(_episodes(f4rows), sessions)], ignore_index=True)
        out = E.attach_bucket(E.dedup(ev_), elig_)
        progress("events_attached", pass_=tag, rows=len(out))
        return out, {"eight_k": k8c, "form4": f4c}

    ev, attribution = events_for(eq, elig)
    ev = pd.concat([ev, E.no_event_control(ev, elig, sessions)], ignore_index=True)
    progress("no_event_control", events_total=len(ev))
    obs, counts = E.outcomes(ev, eq, bench, bench_of, sessions, progress=progress)
    (OUT / "d0_coverage.json").write_text(json.dumps(d0_coverage(eq, elig, cand, obs), indent=1, default=str))
    progress("d0_coverage")
    ledger = M.evaluate(obs, progress=progress)
    calib = M.classify(ledger)                              # LOCK REV 2 (R2)
    progress("classified")
    diag = survivorship_diagnostic(ledger, obs, sessions, bench, bench_of, events_for, guard)   # R1-FIX c
    progress("survivorship_diagnostic")
    cmap = {s_: (v["cik"], v["method"]) for s_, v in r3["identity"].items()}
    inactive = 0
    counts.update({"sic6770_symbol_days_masked": n_masked, "attribution": attribution,
                   "survivorship_diagnostic": diag["summary"]})
    write_outputs(OUT, calib, ledger, counts, {**counts, **dq_all, "eligibility_raw": dq_raw,
                                               "cik_methods": _count(m for _, m in cmap.values()),
                                               "unmapped_inactive_cik": inactive})
    progress("outputs_written")
    guard.record({"event": "phase_d_run_complete", "cells": len(ledger), "observations": len(obs),
                  "classification": calib["classification"]})


def write_outputs(out: Path, calib: dict, ledger: list[dict], counts: dict, integrity: dict) -> None:
    """LOCK REV 3.1 (mechanical): cells.csv and report.md are written FIRST; the one-shot marker trial_ledger.json
    is written LAST, only after every other output is complete. A crash before the marker leaves no marker, so the
    unchanged run-once check in stage_run permits exactly the re-run; once the marker exists a re-run is refused."""
    import pandas as pd
    pd.DataFrame([{"cell": c["cell"], **{k: v for k, v in c["metrics"].items() if k != "per_year"},
                   **c["screen"]["criteria"], "SCREEN_PASS": c["screen"]["SCREEN_PASS"],
                   "nominatable": c["screen"]["nominatable"], "label": c["screen"]["label"]} for c in ledger]
                 ).to_csv(out / "cells.csv", index=False)
    (out / "report.md").write_text(report_md(calib, ledger, counts), encoding="utf-8", newline="\n")
    (out / "trial_ledger.json").write_text(json.dumps({"null_calibration": calib, "cells": ledger,
                                                       "integrity": integrity}, indent=1, default=str))


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
             f"- survivorship diagnostic (non-gating): {json.dumps(counts.get('survivorship_diagnostic', {}).get('EXCLUSION_DEPENDENT_cells'))} SCREEN_PASS cells EXCLUSION_DEPENDENT",
             "", "| cell | n | dates | mean sector-rel | CI | missing exit | label | exclusion-dependent |",
             "|---|---|---|---|---|---|---|---|"]
    for c in passed:
        m = c["metrics"]
        lines.append(f"| {c['cell']} | {m['n']} | {m['distinct_dates']} | {m['mean_sector_relative']:+.4f} | "
                     f"[{m['ci_low']:+.4f}, {m['ci_high']:+.4f}] | {m['missing_exit_rate']:.2%} | {c['screen']['label']} | "
                     f"{c['screen'].get('survivorship_diagnostic', {}).get('EXCLUSION_DEPENDENT', 'n/a')} |")
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


def mask_sic6770(elig, windows: dict):
    """R1b point in time (R7): symbol-days inside a SIC-6770 window of the symbol's dated CIK are not eligible."""
    if not windows:
        return elig, 0
    e = elig.copy()
    hit = [any(lo <= str(d) < hi for lo, hi in windows.get(s_, ())) for s_, d in zip(e["symbol"], e["date"])]
    import numpy as np
    hit = np.array(hit, dtype=bool) & e["eligible"].to_numpy(dtype=bool)
    e.loc[hit, "eligible"] = False
    e.loc[hit, "bucket"] = None
    return e, int(hit.sum())


def _dev_filings(cik: str, sec: Sec) -> list[dict]:
    from research.event_response_map_v1.r3_metadata import dev_filings
    return dev_filings(sec, cik)


def _form4_p_rows(sec: Sec) -> list[dict]:
    """V2@1 input rows, unchanged parser (task107a) -> code P, development period."""
    sp = importlib.util.spec_from_file_location("t107a", ROOT / "research/scripts/task107a_form4_build.py")
    t107 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(t107)
    rows = []
    for q in FORM345_QUARTERS:
        p = OUT / "_tmp_form345.zip"
        p.write_bytes(sec.get(FORM345_URL.format(q), f"{q}_form345.zip"))
        rows += t107.parse_zip(p)
        p.unlink()
    return [r for r in rows if str(r.get("code", "")).upper() == "P" and r.get("filing_date")
            and date(2019, 1, 2) <= r["filing_date"] <= date(2023, 12, 29)]


def _episodes(rows: list[dict]):
    from talonx_v2.cluster_engine import detect_episodes
    from talonx_v2.config import V2Config
    from talonx_v2.form4_source import from_rows
    recs = from_rows([{"symbol": r["issuer_sym"], "issuer_cik": r.get("issuer_cik", ""), "owner_cik": r["owner_cik"],
                       "filing_date": r["filing_date"], "accession": r.get("accession", ""),
                       "transaction_date": r.get("trans_date"), "transaction_value": r.get("value"),
                       "is_officer": bool(r.get("is_officer")), "is_director": bool(r.get("is_director")),
                       "is_ten_percent": bool(r.get("is_ten_pct")), "transaction_code": "P"} for r in rows])
    return detect_episodes(recs, config=V2Config())


def survivorship_diagnostic(ledger, obs, sessions, bench, bench_of, events_for, guard) -> dict:
    """R1-FIX c (NON-GATING). Symbols removed by R1a are downloaded separately (archive alpaca_diag). Reports how
    many pass $5/$20M eligibility by bucket x year; for SCREEN_PASS cells only, re-computes the cell with those
    symbols' events added (same event rules; the NO_EVENT control is not re-drawn) and flags EXCLUSION_DEPENDENT
    when the cell no longer passes."""
    import pandas as pd
    try:
        dbars, _ = D.load(ARCH / "alpaca_diag", purpose="RETURNS", guard=guard)
        draw, _ = D.load(ARCH / "alpaca_diag", purpose="ELIGIBILITY_ONLY", guard=guard)
    except FileNotFoundError:
        return {"summary": {"status": "NO_DIAGNOSTIC_ARCHIVE"}}
    delig = U.eligibility(draw, sessions)
    e = delig[delig["eligible"]]
    by = {}
    for (b, y), g in e.assign(y=[d.year for d in e["date"]]).groupby(["bucket", "y"]):
        by[f"{b}|{y}"] = {"eligible_symbol_days": len(g), "distinct_symbols": int(g["symbol"].nunique())}
    dev, _ = events_for(dbars, delig, "survivorship")
    dobs, _ = E.outcomes(dev, dbars, bench, bench_of, sessions, progress=progress)
    flagged = 0
    ext = pd.concat([obs, dobs], ignore_index=True) if len(dobs) else obs     # LOCK REV 3.2: built once
    for c in ledger:
        if not c["screen"]["SCREEN_PASS"]:
            continue
        sub = ext[(ext["event_type"] == c["event_type"]) & (ext["horizon"] == c["horizon"]) & (ext["bucket"] == c["bucket"])]
        m2 = M.cell_metrics(sub, c["direction"], c["bucket"])
        s2 = M.screen(m2, c["event_type"])
        dep = not s2["SCREEN_PASS"]
        flagged += dep
        c["screen"]["survivorship_diagnostic"] = {"EXCLUSION_DEPENDENT": dep, "n_with_removed": m2.get("n"),
                                                  "mean_sector_relative_with_removed": m2.get("mean_sector_relative"),
                                                  "criteria_with_removed": s2["criteria"]}
    return {"summary": {"diagnostic_symbols_with_bars": int(dbars["symbol"].nunique()),
                        "eligible_by_bucket_year": dict(sorted(by.items())),
                        "diagnostic_events": int(len(dev)), "screen_pass_cells_checked":
                            sum(1 for c in ledger if c["screen"]["SCREEN_PASS"]),
                        "EXCLUSION_DEPENDENT_cells": int(flagged)}}


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
    # LOCK REV 3.2: presence of the ALL bar on each eligible symbol-day via one merge (was a per-row MultiIndex test)
    keys = eq[["symbol", "date"]].drop_duplicates().assign(_have=True)
    e = e.merge(keys, on=["symbol", "date"], how="left")
    e["_have"] = e["_have"].fillna(False).astype(bool)
    res = {}
    for (b, y), g in e.assign(y=[d.year for d in e["date"]]).groupby(["bucket", "y"]):
        pres = int(g["_have"].sum())
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
