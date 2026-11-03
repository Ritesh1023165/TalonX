"""
scorecard_build_panel.py -- TICKER_SCORECARD_V1, Phase 1: build the daily panel and run data gates 1 and 2.

Reads NO returns or outcomes. Writes bars, a gate report and the panel SHA-256 under results/scorecard_v1/panel/.
Gates 3 (fundamentals) and 4 (no look-ahead) need the SEC bulk-file stage and are reported NOT_RUN here, so the overall
verdict stays DATA_NOT_READY until that stage exists and passes.

    python scripts/scorecard_build_panel.py --symbols-file universe.csv --max-symbols 60      # smoke test first
    python scripts/scorecard_build_panel.py --symbols-file universe.csv                       # full run (resumable)

universe.csv needs a ``symbol`` column. Run it in the evening (US market closed) and not while PDM is being read.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from talonx_scorecard import alpaca_fetch as AF            # noqa: E402
from talonx_scorecard import config as C                    # noqa: E402
from talonx_scorecard import gates, labels, panel           # noqa: E402

BATCH = 90


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols-file", required=True)
    ap.add_argument("--out", default=str(ROOT / "results" / "scorecard_v1" / "panel"))
    ap.add_argument("--max-symbols", type=int, default=0, help="0 = all; use ~60 for a smoke test")
    a = ap.parse_args()

    out = Path(a.out); cache = out / "_batches"; cache.mkdir(parents=True, exist_ok=True)
    cleaned = {panel.clean_symbol(x) for x in pd.read_csv(a.symbols_file)["symbol"].dropna()}
    syms = sorted(cleaned - {None, "SPY"})
    print(f"symbols after cleaning: {len(syms)}", flush=True)
    if a.max_symbols:
        syms = syms[: a.max_symbols]
    todo = ["SPY"] + syms
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    print(f"{len(syms)} symbols + SPY in {len(batches)} batches; spec {C.spec_fingerprint()[:12]}", flush=True)

    s = AF.session(ROOT)
    print(AF.describe_keys(*AF.load_keys(ROOT)), flush=True)
    print('probe ->', AF.probe_credentials(s), flush=True)
    parts_adj, parts_rc, parts_rv = [], [], []
    split_payload = {"corporate_actions": {"forward_splits": [], "reverse_splits": []}}
    for bi, b in enumerate(batches):
        f = cache / f"batch_{bi:04d}.pkl.gz"
        if f.exists():
            d = pd.read_pickle(f)
        else:
            ba = AF.fetch_bars(s, b, "all", C.SAMPLE_START, "2026-10-31")
            br = AF.fetch_bars(s, b, "raw", C.SAMPLE_START, "2026-10-31")
            d = {"adj": panel.bars_to_wide(ba, "c"), "rawc": panel.bars_to_wide(br, "c"), "rawv": panel.bars_to_wide(br, "v"),
                 "splits": AF.fetch_splits(s, b, C.SAMPLE_START, "2026-10-31")}
            del ba, br                                         # raw bar dicts are large; keep only the compact frames
            pd.to_pickle(d, f)
        parts_adj.append(d["adj"]); parts_rc.append(d["rawc"]); parts_rv.append(d["rawv"])
        for k in ("forward_splits", "reverse_splits"):
            split_payload["corporate_actions"][k].extend(d["splits"]["corporate_actions"][k])
        print(f"  batch {bi + 1}/{len(batches)} done  ({time.strftime('%H:%M:%S')})", flush=True)

    adj, raw_c, raw_v = (pd.concat(x, axis=1).sort_index() for x in (parts_adj, parts_rc, parts_rv))
    del parts_adj, parts_rc, parts_rv
    if "SPY" not in adj:
        print("SPY bars missing; cannot continue", file=sys.stderr); return 2
    sessions = adj["SPY"].dropna().index
    adj, raw_c, raw_v = (x.reindex(sessions) for x in (adj, raw_c, raw_v))
    spy = adj.pop("SPY"); raw_c = raw_c.drop(columns="SPY", errors="ignore"); raw_v = raw_v.drop(columns="SPY", errors="ignore")
    uni = panel.universe_mask(raw_c, raw_v).reindex(columns=adj.columns, fill_value=False)
    avail = {h: labels.label_available(adj, spy, n) for h, n in C.HORIZONS.items()}
    splits = [x for x in panel.parse_splits(split_payload) if x.symbol in adj.columns]

    from talonx_scorecard.splits import classify_splits
    all_splits = panel.parse_splits(split_payload)
    cls = classify_splits(adj, all_splits, C.SAMPLE_START, C.SAMPLE_END, universe=uni)
    pd.DataFrame(cls, columns=["symbol", "ex_date", "status", "ratio", "adj_log_return", "gap_sessions"]).to_csv(out / "split_check_details.csv", index=False)
    for r in [r for r in cls if r[2] not in ("ADJUSTED", "OUT_OF_SAMPLE", "NOT_IN_UNIVERSE")][:200]:
        print(f"  split {r[2]:<15} {r[0]:<6} ex={str(r[1].date())} ratio={r[3]:.4g} adj_logret={r[4]:.3f} gap={r[5]}")
    g1 = gates.gate1_from_classification(cls)
    g2 = gates.gate2_label_coverage(uni, avail)
    not_run = [gates.GateResult("G_DATA_3_fundamental_coverage", False, None, C.GATE_FUNDAMENTAL_COVERAGE, "NOT_RUN: SEC stage pending"),
               gates.GateResult("G_DATA_4_no_lookahead", False, None, 0.0, "NOT_RUN: SEC stage pending")]
    results = [g1, g2] + not_run

    pd.to_pickle({"adj_close": adj, "raw_close": raw_c, "raw_volume": raw_v, "spy": spy, "universe": uni,
                  "splits": splits}, out / "panel_frames.pkl.gz")
    sha = panel.frame_sha256({"adj_close": adj, "raw_close": raw_c, "raw_volume": raw_v, "spy": spy.to_frame("SPY")})
    report = {"spec_fingerprint": C.spec_fingerprint(), "spec_commit": C.SPEC_COMMIT, "code_head": _git_head(),
              "symbols": len(syms), "sessions": len(sessions), "first": str(sessions[0].date()), "last": str(sessions[-1].date()),
              "universe_avg_names_per_day": float(uni.sum(axis=1).mean()), "splits_found": len(all_splits),
              "panel_sha256": sha, "gates": [r.__dict__ for r in results],
              "overall": "DATA_NOT_READY" if not gates.all_passed(results) else "DATA_READY"}
    (out / "gate_report.json").write_text(json.dumps(report, indent=2, default=str))
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.name}  value={r.value}  threshold={r.threshold}  {r.detail}")
    print(f"overall: {report['overall']}   panel sha256: {sha}")
    print(f"report: {out / 'gate_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
