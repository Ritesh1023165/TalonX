"""TICKER_SCORECARD_V1, phase 2: SEC bulk data -> fundamental + insider features, data gates 3 and 4.

Reads the phase-1 panel (prices only). Computes no returns. Never touches the live engine.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from talonx_scorecard import config as C            # noqa: E402
from talonx_scorecard import gates, insider as INS, panel, sec_facts as SF, sec_features as SFE, sec_fetch as FETCH  # noqa: E402


def load_sym2cik(path: Path) -> dict[str, int]:
    d = json.loads(path.read_text())
    return {panel.clean_symbol(v["ticker"].upper().replace("-", ".")) or v["ticker"].upper(): int(v["cik_str"])
            for v in d.values() if v.get("ticker")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="results/scorecard_v1/panel/panel_frames.pkl.gz")
    ap.add_argument("--out", default="results/scorecard_v1/sec")
    ap.add_argument("--cache", default="results/scorecard_v1/sec_cache")
    ap.add_argument("--allow-market-hours", action="store_true")
    a = ap.parse_args()
    out, cache = Path(a.out), Path(a.cache)
    out.mkdir(parents=True, exist_ok=True)

    ua = FETCH.user_agent()
    if FETCH.in_us_market_hours() and not a.allow_market_hours:
        print("US market hours: SEC bulk downloads wait for the evening (use --allow-market-hours to override)", file=sys.stderr)
        return 3

    fr = pd.read_pickle(a.panel)
    uni, raw_c = fr["universe"], fr["raw_close"]
    sessions = raw_c.index
    symbols = list(raw_c.columns)
    FETCH.download(FETCH.TICKERS_URL, cache / "company_tickers.json", ua)
    sym2cik_all = load_sym2cik(cache / "company_tickers.json")
    ever = [s for s in symbols if uni[s].any()]
    sym2cik = {s: sym2cik_all[s] for s in ever if s in sym2cik_all}
    print(f"symbols ever in universe: {len(ever)}; with an SEC CIK: {len(sym2cik)}", flush=True)
    want = set(sym2cik.values())

    # ---- XBRL company facts ----
    zpath = cache / "companyfacts.zip"
    t0 = time.time()
    print("companyfacts:", "ok" if FETCH.download(FETCH.COMPANYFACTS_URL, zpath, ua) else "MISSING", f"{time.time() - t0:.0f}s", flush=True)
    parts, n = [], 0
    with zipfile.ZipFile(zpath) as z:
        names = {int(nm[3:13]): nm for nm in z.namelist() if nm.startswith("CIK") and nm.endswith(".json")}
        for cik in sorted(want & set(names)):
            with z.open(names[cik]) as fh:
                d = SF.extract_company(json.load(fh))
            if len(d):
                parts.append(d)
            n += 1
            if n % 1000 == 0:
                print(f"  parsed {n} companies ({time.time() - t0:.0f}s)", flush=True)
    facts = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["cik", "concept", "rank", "start", "end", "val", "filed"])
    print(f"facts rows: {len(facts)} from {n} companies (of {len(want)} wanted; {len(want - set(names))} without a facts file)", flush=True)

    feats, sources = SFE.build_fundamental_features(facts, sessions, raw_c, sym2cik)
    del facts, parts

    # ---- insider (F10) ----
    ev_parts, missing_q = [], []
    for y, q in FETCH.quarters(C.SAMPLE_START, C.SAMPLE_END):
        p = cache / f"{y}q{q}_form345.zip"
        if FETCH.download(FETCH.FORM345_URL.format(y=y, q=q), p, ua):
            ev_parts.append(INS.parse_form345_zip(p.read_bytes()))
        else:
            missing_q.append(f"{y}q{q}")
    print("insider quarters missing (404):", missing_q, flush=True)
    events = pd.concat(ev_parts, ignore_index=True) if ev_parts else pd.DataFrame(columns=["issuer_cik", "owner_cik", "filed", "code"])
    ins = INS.net_buyers_wide(events, sessions, sorted(want))
    feats["F10"] = pd.DataFrame({s: ins[c] if c in ins.columns else np.nan for s, c in sym2cik.items()}, index=sessions).reindex(columns=symbols)

    # ---- gates 3 and 4 ----
    hf = SFE.has_fundamental(feats).reindex(columns=symbols, fill_value=False)
    g3 = gates.gate3_fundamental_coverage(uni, hf)
    ok, checked, detail = SF.audit_no_lookahead(sources, sessions)
    g4 = gates.GateResult("G_DATA_4_no_lookahead", ok, float(checked), 0.0, detail + "; insider verified by unit test; F11 not built yet")
    prev = json.loads((Path(a.panel).parent / "gate_report.json").read_text())
    g12 = [gates.GateResult(**{k: g[k] for k in ("name", "passed", "value", "threshold", "detail")}) for g in prev["gates"][:2]]
    results = g12 + [g3, g4]
    cov = {k: float((v.notna() & uni).to_numpy().sum() / max(int(uni.to_numpy().sum()), 1)) for k, v in feats.items()}
    report = {"spec_fingerprint": C.spec_fingerprint(), "panel_sha256": prev["panel_sha256"], "gates": [r.__dict__ for r in results],
              "feature_coverage_of_universe_days": cov, "insider_quarters_missing": missing_q,
              "companies_parsed": n, "F11": "NOT_BUILT (risk-factor diff engine pending)",
              "overall": "DATA_READY" if gates.all_passed(results) else "DATA_NOT_READY"}
    (out / "sec_stage_report.json").write_text(json.dumps(report, indent=2, default=str))
    pd.to_pickle(feats, out / "raw_features.pkl.gz")
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.name}  value={r.value}  threshold={r.threshold}  {r.detail}")
    print("feature coverage of universe-days:", {k: round(v, 3) for k, v in cov.items()})
    print("overall:", report["overall"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
