"""
TASK 120 (B2) -- 39-name live-execution-scope full-history replay of the
frozen INSIDER_BUY_CLUSTER_V2@1 contract.

Protocol written BEFORE this script was run:
docs/research/TASK120_PROTOCOL_39NAME_SCOPE_REPLAY.md

Reuses the exact tested primitives already established at Task 112R/116
(t112rp.runtime_episodes -- the frozen runtime-semantic entry rule;
t107b.build_returns/evaluate -- the net@20bps metric + issuer-block
bootstrap + concentration sensitivity), restricted to the 39-name live
execution scope instead of the 620-name broad panel. Read-only against
the frozen release worktree's already-published free data
(results/task107a_form4_feasibility, results/task95g_broad_cross_sectional)
-- no new data collection, no strategy code change, nothing tuned after
seeing results.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRIMARY = Path(r"C:/workspace/TalonX")  # frozen live release worktree (data + frozen code)
OUT = ROOT / "results" / "task120_39name_scope_replay"
OUT.mkdir(parents=True, exist_ok=True)

FULL_WINDOW = ("2019-01-01", "2026-09-12")           # max available power
T116_WINDOW = ("2024-09-01", "2026-03-31")           # like-for-like vs. Task 116's broad-panel number
HORIZON = 10
COST_BPS = 20
SEED = 118120


def _mod(name, rel, *, data_root=None):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if data_root is not None:
        dr = Path(data_root)
        for a, v in (("ROOT", dr),
                     ("TXN", dr / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"),
                     ("PANEL", dr / "results/task95g_broad_cross_sectional/_daily"),
                     ("PRICES", dr / "results/task107a_form4_feasibility/_prices"),
                     ("A_OUT", dr / "results/task107a_form4_feasibility"),
                     ("BUILD", dr / "results/task107a_form4_feasibility/_build")):
            if hasattr(m, a):
                setattr(m, a, v)
    return m


def _live_39() -> list[str]:
    """The EXACT production 39-name scope, resolved live (not hardcoded),
    reading the same watchlist_coverage module the running V2 service uses."""
    sys.path.insert(0, str(PRIMARY))
    from talonx_ops.watchlist_coverage import build_coverage_map
    cm = build_coverage_map()
    return sorted(c["symbol"] for c in cm["tickers"] if c["v2_collection_scope"] == "POLLED")


def _issuer_block_bootstrap(rr: pd.DataFrame, col: str, *, reps=5000, seed=SEED):
    rng = np.random.default_rng(seed)
    issuers = rr["issuer_sym"].unique()
    if len(issuers) == 0:
        return [float("nan"), float("nan")]
    means = []
    by_issuer = {i: rr.loc[rr.issuer_sym == i, col].to_numpy() for i in issuers}
    for _ in range(reps):
        picked = rng.choice(issuers, size=len(issuers), replace=True)
        vals = np.concatenate([by_issuer[i] for i in picked if len(by_issuer[i])])
        if len(vals):
            means.append(vals.mean())
    if not means:
        return [float("nan"), float("nan")]
    lo, hi = np.percentile(means, [2.5, 97.5])
    return [float(lo), float(hi)]


def main() -> int:
    from talonx_research.versioning import v2_fingerprint

    print("=" * 70)
    print("TASK 120 -- 39-name live-scope full-history replay of INSIDER_BUY_CLUSTER_V2@1")
    print("=" * 70)

    fp = v2_fingerprint()
    print(f"V2@1 fingerprint: {fp}  (frozen 11107198c5b81237)")
    if fp != "11107198c5b81237":
        (OUT / "verdict.json").write_text(json.dumps(
            {"verdict": "TASK120_SCOPE_REPLAY_FAIL",
             "reason": f"fingerprint moved: {fp} != 11107198c5b81237"}, indent=2))
        print("FINGERPRINT MOVED -> TASK120_SCOPE_REPLAY_FAIL")
        return 1

    live39 = _live_39()
    print(f"live execution scope: {len(live39)} names -> {live39}")

    t112rp = _mod("t112rp_120", "research/scripts/task112r_parity.py", data_root=PRIMARY)
    t107b = _mod("t107b_120", "research/scripts/task107b_form4_cluster.py", data_root=PRIMARY)

    P = t112rp.load_P()
    U = t112rp.runtime_episodes(P)
    U["issuer_sym"] = U["issuer_sym"].str.upper()
    U["entry_session"] = pd.to_datetime(U["entry_session"])

    price_panel_syms = {f.stem.upper() for f in (PRIMARY / "results/task95g_broad_cross_sectional/_daily").glob("*.csv")}
    scope_available = sorted(set(live39) & price_panel_syms)
    scope_missing = sorted(set(live39) - price_panel_syms)
    print(f"scope names with local daily-bar price coverage: {len(scope_available)}/{len(live39)}")
    print(f"scope names WITHOUT coverage (excluded, not silently substituted): {scope_missing}")

    scope_episodes = U[U.issuer_sym.isin(scope_available)].copy()

    P2 = P.copy()
    P2["issuer_sym"] = P2["issuer_sym"].str.upper()

    def _eval_window(df, a, b, label):
        w = df[(df.entry_session >= pd.Timestamp(a)) & (df.entry_session <= pd.Timestamp(b))].copy()
        agg = P2.groupby("issuer_sym").agg(any_officer=("is_officer", "any"),
                                           any_director=("is_director", "any"),
                                           any_ten_pct=("is_ten_pct", "any")).reset_index()
        w = w.merge(agg, on="issuer_sym", how="left")
        vals = []
        for r in w.itertuples(index=False):
            sub = P2[(P2.issuer_sym == r.issuer_sym)
                     & (pd.to_datetime(P2.filing_date) <= pd.Timestamp(r.activation_filing_date))
                     & (pd.to_datetime(P2.filing_date) >= pd.Timestamp(r.first_filing))]
            vals.append(float(pd.to_numeric(sub.get("value"), errors="coerce").fillna(0).sum()))
        w["agg_value"] = vals
        for c in ("any_officer", "any_director", "any_ten_pct"):
            w[c] = w[c].fillna(False)
        rr = t107b.build_returns(w).dropna(subset=[f"raw_{HORIZON}"])
        if len(rr) == 0:
            return {"label": label, "N": 0, "note": "no priced episodes in this window/scope"}, rr
        ev = t107b.evaluate(rr, label)
        hb = ev.get(f"h{HORIZON}", {})
        net20 = hb.get("net_20bps", {})
        out = {
            "label": label, "N": len(rr),
            "distinct_issuers": int(rr["issuer_sym"].nunique()),
            "net20_pct": round(100 * net20.get("mean", float("nan")), 3),
            "pf": round(net20.get("profit_factor", float("nan")), 3),
            "win_rate_pct": round(100 * net20.get("win_rate", float("nan")), 1),
            "boot_ci_pct": [round(100 * x, 3) for x in hb.get("boot_ci_net20", [float("nan")] * 2)],
            "drop_top1_pct": round(100 * hb.get("concentration", {}).get("drop_top1_mean_net20", float("nan")), 3),
            "drop_top3_pct": round(100 * hb.get("concentration", {}).get("drop_top3_mean_net20", float("nan")), 3),
        }
        return out, rr

    full_res, full_rr = _eval_window(scope_episodes, FULL_WINDOW[0], FULL_WINDOW[1], "39name_scope_full_window")
    t116_res, t116_rr = _eval_window(scope_episodes, T116_WINDOW[0], T116_WINDOW[1], "39name_scope_t116_window")

    # predeclared: issuer-block bootstrap on the primary (full-window) sample
    net20_col = None
    mstr_share = {}
    if len(full_rr):
        # locate the raw net-return column t107b.evaluate used internally for h10/net_20bps
        cand = [c for c in full_rr.columns if c.startswith(f"net20_{HORIZON}") or c == f"net_20bps_{HORIZON}"]
        if not cand:
            # fall back: recompute net@20bps directly from the raw horizon column
            full_rr = full_rr.copy()
            full_rr["_net20"] = full_rr[f"raw_{HORIZON}"] - 2 * (COST_BPS / 10000.0)
            net20_col = "_net20"
        else:
            net20_col = cand[0]
        ci = _issuer_block_bootstrap(full_rr, net20_col, reps=5000, seed=SEED)
        full_res["issuer_block_ci_pct_verified"] = [round(100 * x, 3) for x in ci]
        mstr_n = int((full_rr["issuer_sym"] == "MSTR").sum())
        mstr_share = {"mstr_episodes": mstr_n, "mstr_share_of_N": round(mstr_n / len(full_rr), 4)}
        if mstr_n and mstr_n < len(full_rr):
            no_mstr = full_rr[full_rr["issuer_sym"] != "MSTR"]
            full_res["drop_mstr_net20_pct"] = round(100 * no_mstr[net20_col].mean(), 3)
            full_res["drop_mstr_N"] = int(len(no_mstr))

    result = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fp,
        "live_scope_names": live39,
        "live_scope_count": len(live39),
        "scope_names_with_price_coverage": scope_available,
        "scope_names_missing_price_coverage": scope_missing,
        "full_window": full_res,
        "full_window_mstr_concentration": mstr_share,
        "t116_comparable_window": t116_res,
        "reference_broad_panel_t116": {
            "N": 170, "net20_pct": 2.196, "pf": 2.228, "window": list(T116_WINDOW),
            "note": "620-name broad panel, Task 115/116, cited not rerun"},
        "reference_live_prospective": {
            "N": 10, "net20_pct": -2.93, "window": "2026-09-08 onward (live only)",
            "note": "Task 118 Deliverable A, cited not rerun"},
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2, default=str))

    ts = "\n".join([
        "=" * 70, "  TASK 120 -- 39-NAME LIVE-SCOPE FULL-HISTORY REPLAY", "=" * 70,
        f"  fingerprint            : {fp}",
        f"  live scope             : {len(live39)} names, {len(scope_available)} with price coverage",
        f"  missing coverage       : {scope_missing}",
        f"  FULL WINDOW ({FULL_WINDOW[0]}..{FULL_WINDOW[1]}):",
        f"    N={full_res.get('N')}  distinct issuers={full_res.get('distinct_issuers')}",
        f"    net@20bps={full_res.get('net20_pct')}%  PF={full_res.get('pf')}  win={full_res.get('win_rate_pct')}%",
        f"    boot CI={full_res.get('issuer_block_ci_pct_verified', full_res.get('boot_ci_pct'))}",
        f"    drop-top1={full_res.get('drop_top1_pct')}%  drop-MSTR={full_res.get('drop_mstr_net20_pct')}% "
        f"(MSTR share of N: {mstr_share.get('mstr_share_of_N')})",
        f"  T116-COMPARABLE WINDOW ({T116_WINDOW[0]}..{T116_WINDOW[1]}):",
        f"    N={t116_res.get('N')}  net@20bps={t116_res.get('net20_pct')}%",
        f"  REFERENCE (cited, not rerun) broad-panel T115/116: N=170, net@20={2.196}%",
        f"  REFERENCE (cited, not rerun) live prospective N=10: net@20={-2.93}%",
        "=" * 70,
    ])
    (OUT / "terminal_summary.txt").write_text(ts)
    print("\n" + ts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
