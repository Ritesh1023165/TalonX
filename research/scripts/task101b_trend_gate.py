"""Task 101B — 15-minute trend-gate counter-trend dip-reclaim study.

OFFLINE RESEARCH ONLY. Zero live wiring. Single pre-registered hypothesis
(results/task101b_trend_gate/preregistration.md): does the frozen Original
15-minute trend gate reject a real positive-expectancy subset of long-only
prior-day-low sweep/reclaim setups?

Reuses the Task 101A candidate parquet (F3 = PDL sweep/reclaim) + a light
1-minute re-pass for sweep depth and 15-minute SMA slope, adds a chronological
discovery/holdout split, trend-distance bins, counter-trend structure bins,
bootstrap robustness, and a secondary DAILY universe-bias diagnostic on the
delisted-inclusive point-in-time S&P 500 universe (Task 95F/95G).

Usage:
    python research/scripts/task101b_trend_gate.py build     # attach sweep depth / slope / split
    python research/scripts/task101b_trend_gate.py analyze
    python research/scripts/task101b_trend_gate.py daily      # secondary daily diagnostic
    python research/scripts/task101b_trend_gate.py all
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
for _p in (str(REPO), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

A_OUT = REPO / "results" / "task101a_event_first"
OUT = REPO / "results" / "task101b_trend_gate"
OUT.mkdir(parents=True, exist_ok=True)
DATA_DIR = REPO / "results" / "task95a_regime_expansion" / "_expanded_data"
DAILY_DIR = REPO / "results" / "task95g_broad_cross_sectional" / "_daily"
MEMBERSHIP = REPO / "results" / "task95f_historical_universe" / "historical_membership_by_date.parquet"

HOLDOUT_START = "2024-01-01"
COST_BPS = [0.0, 5.0, 10.0, 20.0]
ET = "America/New_York"

import task101a_event_first as A  # noqa: E402  (reuse indicator + session helpers)


# ----------------------------------------------------------------------------- #
# BUILD: F3 slice + sweep depth + 15m slope + split
# ----------------------------------------------------------------------------- #
def build() -> pd.DataFrame:
    df = pd.read_parquet(A_OUT / "directional_candidates.parquet")
    f3 = df[df["trigger_type"] == "F3_PDL_RECLAIM"].copy()
    f3["same_bar_ambiguous"] = f3["same_bar_ambiguous"].fillna(False).astype(bool)

    # per-symbol 1m re-pass: sweep_low (low at sweep_bar_idx within the session) + 15m SMA slope
    sweep_low = np.full(len(f3), np.nan)
    sma_slope = np.full(len(f3), np.nan)
    f3 = f3.reset_index(drop=True)
    for sym, gi in f3.groupby("symbol"):
        path = DATA_DIR / f"{sym}.csv"
        if not path.exists():
            continue
        rth = A._load_symbol(str(path))
        if rth is None:
            continue
        # 15m RTH SMA200 series (same construction as task101a) for slope
        r = rth.set_index("et")
        htf = r["close"].resample("15min", label="right", closed="right",
                                  origin="start_day").last().dropna()
        htf_sma = htf.rolling(A.HTF_SMA).mean()
        slope = (htf_sma / htf_sma.shift(4) - 1.0) * 1e4  # bps over 4 prior 15m buckets
        by_date = {d: g.reset_index(drop=True) for d, g in rth.groupby("date")}
        for idx in gi.index:
            row = f3.loc[idx]
            d = dt.date.fromisoformat(row["session_date"])
            g = by_date.get(d)
            if g is None:
                continue
            si = int(row["sweep_bar_idx"])
            if 0 <= si < len(g):
                sweep_low[idx] = float(g["low"].values[si])
            # slope at the trigger bar's most-recent completed 15m bucket
            ti = int(row["trigger_bar_idx"])
            if 0 <= ti < len(g):
                tet = g["et"].values[ti]
                pos = np.searchsorted(slope.index.values, tet, side="right") - 1
                if 0 <= pos < len(slope):
                    sma_slope[idx] = float(slope.values[pos])
    f3["sweep_low"] = sweep_low
    f3["sma_slope_bps"] = sma_slope

    # derived structure
    f3["dist_to_sma_bps"] = (f3["reference_price"] / f3["htf_sma200"] - 1.0) * 1e4
    f3["trend_state"] = np.where(
        f3["htf_sma200"].isna(), "UNKNOWN",
        np.where(f3["reference_price"] > f3["htf_sma200"], "BULLISH_ALIGNED", "BEARISH_COUNTER"))
    f3["sweep_depth_atr"] = (f3["prior_day_low"] - f3["sweep_low"]) / f3["atr"]
    f3["sweep_depth_bps"] = (f3["prior_day_low"] - f3["sweep_low"]) / f3["prior_day_low"] * 1e4
    f3["reclaim_dist_bps"] = (f3["trigger_close"] - f3["prior_day_low"]) / f3["prior_day_low"] * 1e4
    f3["split"] = np.where(f3["session_date"] >= HOLDOUT_START, "holdout", "discovery")
    g = f3["overnight_gap"]
    f3["gap_dir"] = np.where(~np.isfinite(g), "unknown",
                             np.where(g.abs() < 25 / 1e4, "flat",
                                      np.where(f3["reference_price"] >= f3["trigger_close"], "gap_up", "gap_dn")))
    # sign of raw overnight gap where finite (open/close_prior); we only have |gap| in task101a -> approximate via na
    f3["gap_dir"] = np.where(~np.isfinite(g), "unknown", np.where(g.abs() < 25 / 1e4, "flat", "move"))

    # populations
    hg = ["orig_atr_pass", "orig_conf_pass", "orig_rr_pass", "orig_openblk_pass", "orig_closeblk_pass"]
    f3["other_headline_pass"] = f3[hg].all(axis=1)
    f3["is_trend_fail"] = f3["trend_state"] == "BEARISH_COUNTER"
    f3["is_trend_pass"] = ~f3["is_trend_fail"]  # UNKNOWN grouped with pass, matching Original
    f3["pop_trend_only_reject"] = f3["is_trend_fail"] & f3["other_headline_pass"]
    f3["pop_trend_fail_other_fail"] = f3["is_trend_fail"] & (~f3["other_headline_pass"])

    f3.to_parquet(OUT / "pdl_reclaim_candidates.parquet", index=False)
    print(f"BUILD: {len(f3)} F3 PDL reclaim rows "
          f"(unambiguous {int((~f3['same_bar_ambiguous']).sum())}, "
          f"has_next {int(f3['has_next_bar'].sum())})")
    print(f"  trend_state: {f3['trend_state'].value_counts().to_dict()}")
    print(f"  sweep_low attached: {f3['sweep_low'].notna().mean():.1%}   "
          f"sma_slope attached: {f3['sma_slope_bps'].notna().mean():.1%}")
    return f3


# ----------------------------------------------------------------------------- #
# analysis helpers
# ----------------------------------------------------------------------------- #
def _row(s: pd.DataFrame, h="ret_30m") -> dict:
    s = s[s["has_next_bar"] & s[h].notna()]
    if len(s) == 0:
        return dict(N=0)
    r = s[h].values
    eod = s["ret_eod"].dropna().values
    Rc = "R_eod" if "R_eod" in s else None
    wins = (r > 0).mean()
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    p1r = s["pos_1r_before_stop"] if "pos_1r_before_stop" in s else None
    return dict(
        N=int(len(s)),
        mean_30m_bps=float(r.mean() * 1e4),
        median_30m_bps=float(np.median(r) * 1e4),
        eod_bps=float(eod.mean() * 1e4) if len(eod) else np.nan,
        net5_bps=float(r.mean() * 1e4 - 5),
        net10_bps=float(r.mean() * 1e4 - 10),
        net20_bps=float(r.mean() * 1e4 - 20),
        win_pct=float(wins * 100),
        pf=float(gains / losses) if losses > 0 else np.inf,
        median_mfe_bps=float(s["mfe"].median() * 1e4),
        median_mae_bps=float(s["mae"].median() * 1e4),
        p1r_before_stop=float(p1r.mean() * 100) if p1r is not None and p1r.notna().any() else np.nan,
    )


def _boot_ci(s: pd.DataFrame, h="ret_30m", cost=10.0, n=2000, seed=101):
    s = s[s["has_next_bar"] & s[h].notna()]
    if len(s) < 20:
        return [np.nan, np.nan]
    groups = [g[h].values for _, g in s.groupby("session_date")]
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        v = np.concatenate([groups[i] for i in pick])
        out.append(v.mean() * 1e4 - cost)
    return [float(np.percentile(out, 5)), float(np.percentile(out, 95))]


def analyze() -> None:
    f3 = pd.read_parquet(OUT / "pdl_reclaim_candidates.parquet")
    prim = f3[~f3["same_bar_ambiguous"]].copy()          # headline = unambiguous
    ambig = f3[f3["same_bar_ambiguous"]].copy()

    pops = {
        "1_ALL": lambda d: d,
        "2_TREND_PASS": lambda d: d[d["is_trend_pass"]],
        "3_TREND_FAIL": lambda d: d[d["is_trend_fail"]],
        "4_TREND_ONLY_REJECT": lambda d: d[d["pop_trend_only_reject"]],
        "5_TREND_FAIL+OTHER_FAIL": lambda d: d[d["pop_trend_fail_other_fail"]],
        "6_ORIGINAL_PASS": lambda d: d[d["orig_would_pass"]],
        "7_EXP_WOULD_PASS": lambda d: d[d["exp_would_pass"]],
    }
    rows = []
    for split_name, dd in (("full", prim), ("discovery", prim[prim["split"] == "discovery"]),
                           ("holdout", prim[prim["split"] == "holdout"])):
        for pname, fn in pops.items():
            r = _row(fn(dd))
            r.update(split=split_name, population=pname)
            if pname == "4_TREND_ONLY_REJECT":
                lo, hi = _boot_ci(fn(dd))
                r["boot_ci90_net10_lo"], r["boot_ci90_net10_hi"] = lo, hi
            rows.append(r)
    mat = pd.DataFrame(rows)
    cols = ["split", "population", "N", "mean_30m_bps", "median_30m_bps", "eod_bps",
            "net5_bps", "net10_bps", "net20_bps", "win_pct", "pf", "median_mfe_bps",
            "median_mae_bps", "p1r_before_stop", "boot_ci90_net10_lo", "boot_ci90_net10_hi"]
    mat = mat.reindex(columns=cols)
    mat.to_csv(OUT / "primary_matrix.csv", index=False)
    (OUT / "primary_matrix.md").write_text(
        "# Task 101B primary comparison matrix (PDL sweep/reclaim, +30m unless noted)\n\n"
        + _md(mat.round(2)) + "\n", encoding="utf-8")

    # ---- trend-distance bins (BEARISH_COUNTER + BULLISH_ALIGNED, primary pop) ----
    edges = [(-1e9, -100), (-100, -50), (-50, -25), (-25, 0), (0, 25), (25, 50), (50, 100), (100, 1e9)]
    td = []
    base = prim[prim["has_next_bar"] & prim["ret_30m"].notna()]
    for lo, hi in edges:
        sub = base[(base["dist_to_sma_bps"] >= lo) & (base["dist_to_sma_bps"] < hi)]
        r = _row(sub); r.update(bin=f"[{lo:.0f},{hi:.0f})")
        td.append(r)
    pd.DataFrame(td).reindex(columns=["bin", "N", "mean_30m_bps", "median_30m_bps", "eod_bps",
                                      "net10_bps", "win_pct", "median_mfe_bps", "median_mae_bps",
                                      "p1r_before_stop"]).to_csv(
        OUT / "trend_distance_analysis.csv", index=False)

    # ---- counter-trend structure bins (on TREND_FAIL primary pop) ----
    ct = prim[prim["is_trend_fail"] & prim["has_next_bar"] & prim["ret_30m"].notna()]
    struct_rows = []

    def bins(col, edges_, label):
        for lo, hi in edges_:
            sub = ct[(ct[col] >= lo) & (ct[col] < hi)]
            r = _row(sub); r.update(dim=label, bin=f"[{lo:g},{hi:g})")
            struct_rows.append(r)

    bins("sweep_depth_atr", [(0, .25), (.25, .5), (.5, 1), (1, 2), (2, 1e9)], "sweep_depth_atr")
    bins("sweep_depth_bps", [(0, 25), (25, 50), (50, 100), (100, 250), (250, 1e9)], "sweep_depth_bps")
    bins("reclaim_dist_bps", [(0, 10), (10, 25), (25, 50), (50, 100), (100, 1e9)], "reclaim_dist_bps")
    bins("vol_surge", [(0, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 1e9)], "rvol")
    bins("atr_pct", [(0, .10), (.10, .15), (.15, .20), (.20, .25), (.25, .30), (.30, 1e9)], "atr_pct")
    for lag in (1, 2, 3):
        sub = ct[ct["reclaim_lag"] == lag]
        r = _row(sub); r.update(dim="reclaim_lag", bin=str(lag)); struct_rows.append(r)
    for lo, hi, lbl in ((dt.time(9, 45), dt.time(10, 30), "0945-1030"),
                        (dt.time(10, 30), dt.time(12, 0), "1030-1200"),
                        (dt.time(12, 0), dt.time(14, 0), "1200-1400"),
                        (dt.time(14, 0), dt.time(15, 30), "1400-1530")):
        tt = pd.to_datetime(ct["tod"].astype(str)).dt.time
        sub = ct[(tt >= lo) & (tt < hi)]
        r = _row(sub); r.update(dim="tod", bin=lbl); struct_rows.append(r)
    pd.DataFrame(struct_rows).reindex(columns=["dim", "bin", "N", "mean_30m_bps", "median_30m_bps",
                                               "eod_bps", "net10_bps", "win_pct", "median_mfe_bps",
                                               "median_mae_bps", "p1r_before_stop"]).to_csv(
        OUT / "countertrend_structure_analysis.csv", index=False)

    # ---- robustness on TREND_ONLY_REJECT (and TREND_FAIL) ----
    rob = {}
    for pname, sub in (("TREND_ONLY_REJECT", prim[prim["pop_trend_only_reject"]]),
                       ("TREND_FAIL", prim[prim["is_trend_fail"]])):
        s = sub[sub["has_next_bar"] & sub["ret_30m"].notna()].copy()
        if len(s) < 10:
            rob[pname] = {"N": int(len(s)), "note": "insufficient"}
            continue
        r = s["ret_30m"].values
        by_year = (s.groupby("year")["ret_30m"].mean() * 1e4 - 10)
        by_sym = s.groupby("symbol")["ret_30m"].agg(["size", "mean"])
        by_sym["contrib"] = by_sym["size"] * by_sym["mean"]
        top_sym = by_sym["contrib"].abs().idxmax() if len(by_sym) else None
        s_sorted = s.sort_values("ret_30m", ascending=False)

        def reg(y):
            return "2020-21" if y <= 2021 else ("2022" if y == 2022 else "2023-26")
        by_reg = (s.assign(rg=s["year"].map(reg)).groupby("rg")["ret_30m"].mean() * 1e4 - 10)
        disc = s[s["split"] == "discovery"]["ret_30m"]
        hold = s[s["split"] == "holdout"]["ret_30m"]
        rob[pname] = dict(
            N=int(len(s)),
            full_net10=float(r.mean() * 1e4 - 10),
            full_net20=float(r.mean() * 1e4 - 20),
            full_median_bps=float(np.median(r) * 1e4),
            boot_ci90_net10=_boot_ci(s),
            discovery_N=int(len(disc)), discovery_net10=float(disc.mean() * 1e4 - 10) if len(disc) else None,
            discovery_ci90=_boot_ci(s[s["split"] == "discovery"]),
            holdout_N=int(len(hold)), holdout_net10=float(hold.mean() * 1e4 - 10) if len(hold) else None,
            holdout_ci90=_boot_ci(s[s["split"] == "holdout"]),
            by_year_net10={int(k): round(float(v), 1) for k, v in by_year.items()},
            by_regime_net10={k: round(float(v), 1) for k, v in by_reg.items()},
            n_symbols=int(s["symbol"].nunique()),
            symbol_herfindahl=float(((by_sym["size"] / by_sym["size"].sum()) ** 2).sum()),
            top_symbol=top_sym,
            net10_wo_top_symbol=float(s[s["symbol"] != top_sym]["ret_30m"].mean() * 1e4 - 10),
            net10_wo_top3=float(s_sorted.iloc[3:]["ret_30m"].mean() * 1e4 - 10),
            net10_wo_top5=float(s_sorted.iloc[5:]["ret_30m"].mean() * 1e4 - 10),
            cost_sensitivity_bps={c: round(float(r.mean() * 1e4 - c), 2) for c in COST_BPS},
        )
    (OUT / "robustness_report.md").write_text(
        "# Task 101B robustness (primary horizon +30m)\n\n```json\n"
        + json.dumps(rob, indent=2) + "\n```\n", encoding="utf-8")

    # ---- candidate counts ----
    cc = {
        "F3_total": int(len(f3)),
        "F3_unambiguous_headline": int(len(prim)),
        "F3_same_bar_ambiguous": int(len(ambig)),
        "with_next_bar": int(prim["has_next_bar"].sum()),
        "TREND_PASS": int(prim["is_trend_pass"].sum()),
        "TREND_FAIL": int(prim["is_trend_fail"].sum()),
        "TREND_UNKNOWN": int((prim["trend_state"] == "UNKNOWN").sum()),
        "TREND_ONLY_REJECT": int(prim["pop_trend_only_reject"].sum()),
        "TREND_FAIL_OTHER_FAIL": int(prim["pop_trend_fail_other_fail"].sum()),
        "ORIGINAL_PASS": int(prim["orig_would_pass"].sum()),
        "EXP_WOULD_PASS": int(prim["exp_would_pass"].sum()),
        "discovery_rows": int((prim["split"] == "discovery").sum()),
        "holdout_rows": int((prim["split"] == "holdout").sum()),
        "TREND_ONLY_REJECT_discovery": int(prim[(prim["pop_trend_only_reject"]) & (prim["split"] == "discovery")].shape[0]),
        "TREND_ONLY_REJECT_holdout": int(prim[(prim["pop_trend_only_reject"]) & (prim["split"] == "holdout")].shape[0]),
    }
    (OUT / "candidate_counts.md").write_text(
        "# Task 101B candidate counts\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in cc.items())
        + "\n", encoding="utf-8")
    print("analyze: wrote primary_matrix, trend_distance, countertrend_structure, robustness, counts")
    print(json.dumps(cc, indent=1))


def _md(d: pd.DataFrame) -> str:
    cols = list(d.columns)
    out = ["| " + " | ".join(map(str, cols)) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in d.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


# ----------------------------------------------------------------------------- #
# SECONDARY: daily universe-bias diagnostic (delisted-inclusive S&P 500)
# ----------------------------------------------------------------------------- #
def daily() -> None:
    mem = pd.read_parquet(MEMBERSHIP)
    mem["date"] = pd.to_datetime(mem["date"]).dt.date
    member_dates = mem.groupby("symbol")["date"].agg(["min", "max"])
    files = sorted(glob.glob(str(DAILY_DIR / "*.csv")))
    rows = []
    n_used = 0
    for f in files:
        sym = os.path.basename(f)[:-4]
        if sym not in member_dates.index:
            continue
        d = pd.read_csv(f, parse_dates=["date"])
        d["date"] = d["date"].dt.date
        d = d.sort_values("date").reset_index(drop=True)
        if len(d) < 260:
            continue
        # restrict to point-in-time membership window (+/- a small buffer already implicit)
        mn, mx = member_dates.loc[sym, "min"], member_dates.loc[sym, "max"]
        d = d[(d["date"] >= mn) & (d["date"] <= mx)].reset_index(drop=True)
        if len(d) < 260:
            continue
        n_used += 1
        c = d["close"].values
        lo = d["low"].values
        sma200 = pd.Series(c).rolling(200).mean().values
        pdl = np.concatenate([[np.nan], lo[:-1]])          # prior-session low
        pcl = np.concatenate([[np.nan], c[:-1]])
        for i in range(200, len(d) - 5):
            if not (np.isfinite(pdl[i]) and np.isfinite(sma200[i])):
                continue
            if lo[i] < pdl[i] and c[i] > pdl[i]:            # daily sweep + reclaim
                trend_fail = c[i] < sma200[i]
                ref = c[i]                                   # daily proxy entry = reclaim close
                fwd1 = c[i + 1] / ref - 1.0
                fwd3 = c[i + 3] / ref - 1.0
                fwd5 = c[i + 5] / ref - 1.0
                rows.append(dict(symbol=sym, date=str(d["date"].iloc[i]),
                                 year=d["date"].iloc[i].year,
                                 trend_fail=bool(trend_fail),
                                 dist_sma_bps=(ref / sma200[i] - 1.0) * 1e4,
                                 fwd1=fwd1, fwd3=fwd3, fwd5=fwd5))
    dd = pd.DataFrame(rows)
    dd.to_parquet(OUT / "_daily_diagnostic_candidates.parquet", index=False)

    def summ(s):
        return dict(N=int(len(s)),
                    fwd1_bps=float(s["fwd1"].mean() * 1e4), fwd1_net10=float(s["fwd1"].mean() * 1e4 - 10),
                    fwd3_bps=float(s["fwd3"].mean() * 1e4), fwd3_net10=float(s["fwd3"].mean() * 1e4 - 10),
                    fwd5_bps=float(s["fwd5"].mean() * 1e4), fwd5_net10=float(s["fwd5"].mean() * 1e4 - 10),
                    fwd1_med_bps=float(s["fwd1"].median() * 1e4),
                    win1_pct=float((s["fwd1"] > 0).mean() * 100))
    res = dict(
        symbols_used=n_used,
        date_span=[str(dd["date"].min()), str(dd["date"].max())] if len(dd) else None,
        ALL=summ(dd),
        TREND_PASS=summ(dd[~dd["trend_fail"]]),
        TREND_FAIL=summ(dd[dd["trend_fail"]]),
        TREND_FAIL_discovery=summ(dd[dd["trend_fail"] & (dd["date"] < HOLDOUT_START)]),
        TREND_FAIL_holdout=summ(dd[dd["trend_fail"] & (dd["date"] >= HOLDOUT_START)]),
        TREND_FAIL_by_year_fwd1_net10={int(y): round(float(g["fwd1"].mean() * 1e4 - 10), 1)
                                       for y, g in dd[dd["trend_fail"]].groupby("year")},
    )
    (OUT / "universe_bias_analysis.md").write_text(
        "# Task 101B — secondary DAILY universe-bias diagnostic\n\n"
        "Delisted-inclusive point-in-time S&P 500 (Task 95F membership x Task 95G split/dividend-\n"
        "adjusted daily bars). Daily proxy: session low < prior-session low (sweep) AND close >\n"
        "prior-session low (reclaim); daily trend gate FAIL = close < 200-day SMA. Forward = next /\n"
        "+3 / +5 session close return from the reclaim close. **This is a survivorship diagnostic\n"
        "only -- it cannot confirm or refute the 1-minute primary claim.**\n\n"
        "```json\n" + json.dumps(res, indent=2) + "\n```\n", encoding="utf-8")
    print("daily: wrote universe_bias_analysis.md")
    print(json.dumps({k: v for k, v in res.items() if k in ("symbols_used", "ALL", "TREND_FAIL",
                                                            "TREND_FAIL_holdout")}, indent=1))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("build", "all"):
        build()
    if mode in ("analyze", "all"):
        analyze()
    if mode in ("daily", "all"):
        daily()
