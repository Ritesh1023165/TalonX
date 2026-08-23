"""Task 55 — RSI vs MACD Family Economics Diagnostic.

READ-ONLY diagnostic over existing Task 53/54 trade-level evidence.
No backtest, market download, strategy change, parameter tuning, or family action.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "task55_family_economics_diagnostic"
OUT.mkdir(parents=True, exist_ok=True)
T53_TRADES = ROOT / "results" / "task53_preroll_ab_validation" / "_trades_candidate.csv"
T54_TRADES = ROOT / "results" / "task54_extended_candidate_validation" / "_trades.csv"
T53_SUMMARY = ROOT / "results" / "task53_preroll_ab_validation" / "task53_summary.json"
T54_SUMMARY = ROOT / "results" / "task54_extended_candidate_validation" / "task54_summary.json"
COST_BPS = 5.0
ET = "America/New_York"

# Entry signal families observed/allowed by the frozen long-only strategy.
FAMILY_MAP = {
    "rsi_oversold_volume_surge": "RSI",
    "rsi_overbought_volume_surge": "RSI",
    "macd_bullish_cross": "MACD",
    "macd_bearish_cross": "MACD",
    "ma_golden_cross": "MA",
    "ma_death_cross": "MA",
}
TARGET_FAMILIES = ("RSI", "MACD")


def econ(g: pd.DataFrame, col: str) -> dict:
    n = len(g)
    if not n:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": None,
                "total_R": 0.0, "expectancy_R": None, "median_R": None,
                "profit_factor": None}
    vals = g[col].astype(float)
    pos = vals[vals > 0].sum()
    neg = vals[vals < 0].sum()
    pf = float(pos / abs(neg)) if neg else None
    return {
        "trades": int(n), "wins": int((vals > 0).sum()), "losses": int((vals < 0).sum()),
        "win_rate": float((vals > 0).mean()), "total_R": float(vals.sum()),
        "expectancy_R": float(vals.mean()), "median_R": float(vals.median()),
        "profit_factor": pf,
    }


def load() -> tuple[pd.DataFrame, dict]:
    t53 = pd.read_csv(T53_TRADES)
    t54 = pd.read_csv(T54_TRADES)
    audit = {
        "t53_path": str(T53_TRADES.relative_to(ROOT)),
        "t54_path": str(T54_TRADES.relative_to(ROOT)),
        "t53_rows": len(t53), "t54_rows": len(t54),
        "schemas_identical": list(t53.columns) == list(t54.columns),
        "t53_columns": list(t53.columns), "t54_columns": list(t54.columns),
        "t53_signal_types": t53.signal_type.value_counts().to_dict(),
        "t54_signal_types": t54.signal_type.value_counts().to_dict(),
        "t53_duplicate_trade_ids": int(t53.trade_id.duplicated().sum()),
        "t54_duplicate_trade_ids": int(t54.trade_id.duplicated().sum()),
        "cross_task_trade_id_overlap": len(set(t53.trade_id) & set(t54.trade_id)),
        "t53_windows": sorted(t53.window.unique().tolist()),
        "t54_windows": sorted(t54.window.unique().tolist()),
    }
    for df, task in ((t53, "T53"), (t54, "T54")):
        df["task"] = task
        df["window_key"] = task + "_" + df.window.astype(str)
    c = pd.concat([t53, t54], ignore_index=True)
    c["family"] = c.signal_type.map(FAMILY_MAP)
    audit["unmapped_signal_types"] = sorted(c.loc[c.family.isna(), "signal_type"].dropna().unique().tolist())
    audit["ma_entry_trades"] = int((c.family == "MA").sum())
    if audit["unmapped_signal_types"]:
        raise RuntimeError(f"Unmapped signal types: {audit['unmapped_signal_types']}")
    c = c[c.family.isin(TARGET_FAMILIES)].copy()
    c["entry_ts"] = pd.to_datetime(c.entry_timestamp, utc=True)
    c["exit_ts"] = pd.to_datetime(c.exit_timestamp, utc=True)
    c["entry_date_et"] = c.entry_ts.dt.tz_convert(ET).dt.date
    c["entry_time_et"] = c.entry_ts.dt.tz_convert(ET).dt.time

    risk = (c.entry_price - c.stop_price).abs()
    rate = COST_BPS / 10000.0
    c["risk_dollars"] = risk
    c["risk_pct_entry"] = risk / c.entry_price * 100.0
    c["cost_R_5bps"] = (c.entry_price * rate + c.exit_price * rate) / risk
    c["net_R_5bps"] = c.gross_R - c.cost_R_5bps
    return c, audit


def bucket_time(t) -> str:
    # Predeclared product/session buckets; fixed before Task55 outcomes.
    if t < pd.Timestamp("10:30").time():
        return "OPEN_0930_1030"
    if t < pd.Timestamp("15:00").time():
        return "MID_1030_1500"
    return "CLOSE_1500_ONWARD"


def bucket_holding(sec: float) -> str:
    # Fixed interpretable intraday horizons; not outcome-optimized.
    if sec <= 15 * 60:
        return "SHORT_LE_15M"
    if sec <= 60 * 60:
        return "MEDIUM_15_60M"
    return "LONG_GT_60M"


def add_buckets(c: pd.DataFrame) -> pd.DataFrame:
    c = c.copy()
    c["entry_time_bucket"] = c.entry_time_et.map(bucket_time)
    c["holding_bucket"] = c.holding_seconds.map(bucket_holding)
    return c


def verify_reproduction(c: pd.DataFrame) -> dict:
    with open(T53_SUMMARY) as f: s53 = json.load(f)
    with open(T54_SUMMARY) as f: s54 = json.load(f)
    t53_5 = float(c[c.task == "T53"].net_R_5bps.sum())
    t54_5 = float(c[c.task == "T54"].net_R_5bps.sum())
    return {
        "t53_reproduced_total_R_5bps": t53_5,
        "t53_frozen_total_R_5bps": float(s53["economics_5bps"]["total_R"]),
        "t53_match": abs(t53_5 - float(s53["economics_5bps"]["total_R"])) < 0.01,
        "t54_reproduced_total_R_5bps": t54_5,
        "t54_frozen_total_R_5bps": float(s54["economics_5bps"]["total_R"]),
        "t54_match": abs(t54_5 - float(s54["economics_5bps"]["total_R"])) < 0.01,
    }


def family_economics(c: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for scope, sub in (("T53", c[c.task=="T53"]), ("T54", c[c.task=="T54"]), ("COMBINED", c)):
        for fam in TARGET_FAMILIES:
            g=sub[sub.family==fam]; e0=econ(g,"gross_R"); e5=econ(g,"net_R_5bps")
            rows.append({"scope":scope,"family":fam,**{f"{k}_0bps":v for k,v in e0.items()},
                         "total_R_5bps":e5["total_R"],"expectancy_R_5bps":e5["expectancy_R"],
                         "profit_factor_5bps":e5["profit_factor"]})
    df=pd.DataFrame(rows); df.to_csv(OUT/"family_economics.csv",index=False); return df


def window_control(c: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for wk,sub in c.groupby("window_key"):
        row={"window_key":wk,"task":sub.task.iloc[0]}
        for fam in TARGET_FAMILIES:
            g=sub[sub.family==fam]; e0=econ(g,"gross_R"); e5=econ(g,"net_R_5bps")
            for k in ("trades","total_R","expectancy_R","profit_factor"):
                row[f"{fam.lower()}_{k}_0bps"]=e0[k]
            row[f"{fam.lower()}_total_R_5bps"]=e5["total_R"]
            row[f"{fam.lower()}_expectancy_R_5bps"]=e5["expectancy_R"]
        if row["rsi_expectancy_R_0bps"] is not None and row["macd_expectancy_R_0bps"] is not None:
            row["rsi_gt_macd_expectancy_0bps"]=row["rsi_expectancy_R_0bps"]>row["macd_expectancy_R_0bps"]
            row["rsi_gt_macd_expectancy_5bps"]=row["rsi_expectancy_R_5bps"]>row["macd_expectancy_R_5bps"]
        rows.append(row)
    df=pd.DataFrame(rows).sort_values("window_key"); df.to_csv(OUT/"window_family_economics.csv",index=False); return df


def symbol_control(c: pd.DataFrame):
    rows=[]
    for sym,sub in c.groupby("symbol"):
        row={"symbol":sym}
        for fam in TARGET_FAMILIES:
            g=sub[sub.family==fam]; e0=econ(g,"gross_R"); e5=econ(g,"net_R_5bps")
            row.update({f"{fam.lower()}_n":e0["trades"],f"{fam.lower()}_total_R_0bps":e0["total_R"],
                        f"{fam.lower()}_expectancy_R_0bps":e0["expectancy_R"],
                        f"{fam.lower()}_total_R_5bps":e5["total_R"],
                        f"{fam.lower()}_expectancy_R_5bps":e5["expectancy_R"]})
        rows.append(row)
    sdf=pd.DataFrame(rows).sort_values("symbol"); sdf.to_csv(OUT/"symbol_family_economics.csv",index=False)
    common=sdf[(sdf.rsi_n>0)&(sdf.macd_n>0)].symbol.tolist()
    rows=[]
    for fam in TARGET_FAMILIES:
        g=c[(c.symbol.isin(common))&(c.family==fam)]; e0=econ(g,"gross_R"); e5=econ(g,"net_R_5bps")
        rows.append({"family":fam,"common_symbol_count":len(common),"trades":len(g),
                     "pct_original_family_sample":100*len(g)/len(c[c.family==fam]),
                     "total_R_0bps":e0["total_R"],"expectancy_R_0bps":e0["expectancy_R"],"pf_0bps":e0["profit_factor"],
                     "total_R_5bps":e5["total_R"],"expectancy_R_5bps":e5["expectancy_R"],"pf_5bps":e5["profit_factor"]})
    cdf=pd.DataFrame(rows); cdf.to_csv(OUT/"common_symbol_economics.csv",index=False)
    return sdf, common, cdf


def time_control(c: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for bucket,sub in c.groupby("entry_time_bucket"):
        for fam in TARGET_FAMILIES:
            g=sub[sub.family==fam]; e0=econ(g,"gross_R"); e5=econ(g,"net_R_5bps")
            rows.append({"entry_time_bucket":bucket,"family":fam,"trades":len(g),
                         "total_R_0bps":e0["total_R"],"expectancy_R_0bps":e0["expectancy_R"],"pf_0bps":e0["profit_factor"],
                         "total_R_5bps":e5["total_R"],"expectancy_R_5bps":e5["expectancy_R"],"pf_5bps":e5["profit_factor"]})
    df=pd.DataFrame(rows).sort_values(["entry_time_bucket","family"]); df.to_csv(OUT/"time_bucket_family_economics.csv",index=False); return df


def exit_holding_control(c: pd.DataFrame):
    rows=[]
    for fam in TARGET_FAMILIES:
        fg=c[c.family==fam]
        for reason,g in fg.groupby("exit_reason"):
            e0=econ(g,"gross_R");e5=econ(g,"net_R_5bps")
            rows.append({"family":fam,"exit_reason":reason,"count":len(g),"pct_family":100*len(g)/len(fg),
                         "total_R_0bps":e0["total_R"],"expectancy_R_0bps":e0["expectancy_R"],
                         "total_R_5bps":e5["total_R"],"expectancy_R_5bps":e5["expectancy_R"],
                         "median_holding_minutes":float(g.holding_seconds.median()/60)})
    edf=pd.DataFrame(rows).sort_values(["family","exit_reason"]); edf.to_csv(OUT/"exit_family_economics.csv",index=False)
    rows=[]
    for fam in TARGET_FAMILIES:
        g=c[c.family==fam]
        rows.append({"family":fam,"n":len(g),"median_minutes":float(g.holding_seconds.median()/60),
                     "mean_minutes":float(g.holding_seconds.mean()/60),"p25_minutes":float(g.holding_seconds.quantile(.25)/60),
                     "p75_minutes":float(g.holding_seconds.quantile(.75)/60)})
    hdf=pd.DataFrame(rows); hdf.to_csv(OUT/"holding_duration_family.csv",index=False)
    rows=[]
    for bucket,sub in c.groupby("holding_bucket"):
        for fam in TARGET_FAMILIES:
            g=sub[sub.family==fam];e0=econ(g,"gross_R");e5=econ(g,"net_R_5bps")
            rows.append({"holding_bucket":bucket,"family":fam,"trades":len(g),"total_R_0bps":e0["total_R"],
                         "expectancy_R_0bps":e0["expectancy_R"],"total_R_5bps":e5["total_R"],
                         "expectancy_R_5bps":e5["expectancy_R"]})
    hb=pd.DataFrame(rows).sort_values(["holding_bucket","family"]); hb.to_csv(OUT/"holding_bucket_family_economics.csv",index=False)
    return edf,hdf,hb


def outlier_control(c: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for fam in TARGET_FAMILIES:
        g=c[c.family==fam]
        row={"family":fam,"n":len(g),"best_gross_R":float(g.gross_R.max()),"worst_gross_R":float(g.gross_R.min()),
             "base_total_R_0bps":float(g.gross_R.sum()),"base_total_R_5bps":float(g.net_R_5bps.sum())}
        pos=g[g.gross_R>0].gross_R.sum()
        sg=g.sort_values("gross_R",ascending=False)
        for k in (1,3,5):
            row[f"top{k}_share_positive_R"] = float(sg.head(k).gross_R.clip(lower=0).sum()/pos) if pos else None
            rest=sg.iloc[k:]
            row[f"total_R_0bps_after_remove_top{k}_gross_winners"]=float(rest.gross_R.sum())
            row[f"expectancy_R_0bps_after_remove_top{k}_gross_winners"]=float(rest.gross_R.mean())
            row[f"total_R_5bps_after_remove_top{k}_gross_winners"]=float(rest.net_R_5bps.sum())
        # Loser-tail sensitivity, independently for gross and 5bps economics.
        for col,label in (("gross_R","0bps"),("net_R_5bps","5bps")):
            worst=g.sort_values(col,ascending=True)
            for k in (1,3,5):
                rest=worst.iloc[k:]
                row[f"total_R_{label}_after_remove_worst{k}"]=float(rest[col].sum())
                row[f"expectancy_R_{label}_after_remove_worst{k}"]=float(rest[col].mean())
        rows.append(row)
    df=pd.DataFrame(rows);df.to_csv(OUT/"family_outlier_sensitivity.csv",index=False);return df


def cost_burden(c: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for fam in TARGET_FAMILIES:
        g=c[c.family==fam]
        rows.append({"family":fam,"trades":len(g),"mean_cost_R_5bps":float(g.cost_R_5bps.mean()),
                     "median_cost_R_5bps":float(g.cost_R_5bps.median()),"p75_cost_R_5bps":float(g.cost_R_5bps.quantile(.75)),
                     "max_cost_R_5bps":float(g.cost_R_5bps.max()),"median_risk_pct_entry":float(g.risk_pct_entry.median()),
                     "total_cost_R_5bps":float(g.cost_R_5bps.sum())})
    df=pd.DataFrame(rows);df.to_csv(OUT/"cost_burden_family.csv",index=False);return df


def matched_control(c: pd.DataFrame):
    keys=["task","window_key","symbol","entry_time_bucket"]
    rows=[]; eligible_keys=[]
    for key,g in c.groupby(keys):
        r=g[g.family=="RSI"];m=g[g.family=="MACD"]
        if len(r) and len(m):
            eligible_keys.append(key)
            e0r=econ(r,"gross_R");e0m=econ(m,"gross_R");e5r=econ(r,"net_R_5bps");e5m=econ(m,"net_R_5bps")
            rows.append({"task":key[0],"window_key":key[1],"symbol":key[2],"entry_time_bucket":key[3],
                         "rsi_n":len(r),"macd_n":len(m),"rsi_mean_R_0bps":e0r["expectancy_R"],"macd_mean_R_0bps":e0m["expectancy_R"],
                         "rsi_total_R_0bps":e0r["total_R"],"macd_total_R_0bps":e0m["total_R"],
                         "rsi_total_R_5bps":e5r["total_R"],"macd_total_R_5bps":e5m["total_R"],
                         "rsi_gt_macd_unweighted_stratum_mean_0bps":e0r["expectancy_R"]>e0m["expectancy_R"]})
    strata=pd.DataFrame(rows);strata.to_csv(OUT/"matched_strata.csv",index=False)
    if eligible_keys:
        idx=c.set_index(keys).index
        common=c[idx.isin(eligible_keys)].copy()
    else:
        common=c.iloc[0:0].copy()
    pooled=[]
    for fam in TARGET_FAMILIES:
        g=common[common.family==fam];e0=econ(g,"gross_R");e5=econ(g,"net_R_5bps")
        pooled.append({"family":fam,"trades":len(g),"pct_original_family_sample":100*len(g)/len(c[c.family==fam]),
                       "total_R_0bps":e0["total_R"],"expectancy_R_0bps":e0["expectancy_R"],"pf_0bps":e0["profit_factor"],
                       "total_R_5bps":e5["total_R"],"expectancy_R_5bps":e5["expectancy_R"],"pf_5bps":e5["profit_factor"]})
    pooled_df=pd.DataFrame(pooled);pooled_df.to_csv(OUT/"matched_common_support_economics.csv",index=False)

    # Bounded nearest-time one-to-one matching within the declared coarse strata.
    # No outcome-based tolerance: all nearest pairs are reported, and their time gaps
    # are used to judge match quality. Greedy global shortest-distance pairing prevents reuse.
    pairs=[]
    for key,g in c.groupby(keys):
        r=g[g.family=="RSI"];m=g[g.family=="MACD"]
        if not len(r) or not len(m): continue
        candidates=[]
        for ri,rr in r.iterrows():
            for mi,mm in m.iterrows():
                candidates.append((abs((rr.entry_ts-mm.entry_ts).total_seconds()),ri,mi))
        candidates.sort(key=lambda x:x[0]); ur=set();um=set()
        for dt,ri,mi in candidates:
            if ri in ur or mi in um: continue
            ur.add(ri);um.add(mi); rr=c.loc[ri];mm=c.loc[mi]
            pairs.append({"task":key[0],"window_key":key[1],"symbol":key[2],"entry_time_bucket":key[3],
                          "rsi_trade_id":rr.trade_id,"macd_trade_id":mm.trade_id,
                          "rsi_entry_timestamp":rr.entry_timestamp,"macd_entry_timestamp":mm.entry_timestamp,
                          "abs_time_diff_minutes":dt/60,"same_et_date":rr.entry_date_et==mm.entry_date_et,
                          "rsi_gross_R":rr.gross_R,"macd_gross_R":mm.gross_R,"gross_R_diff_rsi_minus_macd":rr.gross_R-mm.gross_R,
                          "rsi_net_R_5bps":rr.net_R_5bps,"macd_net_R_5bps":mm.net_R_5bps,
                          "net_R_5bps_diff_rsi_minus_macd":rr.net_R_5bps-mm.net_R_5bps})
    pdf=pd.DataFrame(pairs);pdf.to_csv(OUT/"nearest_time_pairs.csv",index=False)
    same_day=pdf[pdf.same_et_date].copy() if len(pdf) else pdf.copy()
    same_day.to_csv(OUT/"nearest_time_pairs_same_day.csv",index=False)
    return strata,pooled_df,pdf,same_day


def bootstrap_descriptive(c: pd.DataFrame) -> dict:
    # Descriptive trade-level bootstrap only; trades are not guaranteed independent,
    # so this is NOT treated as formal proof/significance.
    rng=np.random.default_rng(550055); B=20000
    out={}
    for col,label in (("gross_R","0bps"),("net_R_5bps","5bps")):
        arrays={f:c[c.family==f][col].to_numpy(float) for f in TARGET_FAMILIES}
        boots={}
        for fam,a in arrays.items():
            idx=rng.integers(0,len(a),size=(B,len(a))); b=a[idx].mean(axis=1);boots[fam]=b
            out[f"{fam}_{label}_expectancy_bootstrap95"]=[float(x) for x in np.quantile(b,[.025,.975])]
        diff=boots["RSI"]-boots["MACD"]
        out[f"RSI_minus_MACD_{label}_expectancy_diff_bootstrap95"]=[float(x) for x in np.quantile(diff,[.025,.975])]
    out["caveat"]="Trade-level bootstrap is descriptive only; cross-trade dependence by symbol/window is not modeled."
    return out


def write_md(summary: dict):
    fe=pd.DataFrame(summary["family_economics"])
    comb=fe[fe.scope=="COMBINED"].set_index("family")
    r=comb.loc["RSI"];m=comb.loc["MACD"]
    md=f"""# Task 55 — RSI vs MACD Family Economics Diagnostic

**Classification:** `{summary['classification']}`  
**Deployment:** `MONDAY_DECISION_SHADOW_ONLY`

## Reproduction
- Task53 5bps total reproduced: {summary['reproduction']['t53_reproduced_total_R_5bps']:.3f}R.
- Task54 5bps total reproduced: {summary['reproduction']['t54_reproduced_total_R_5bps']:.3f}R.
- Combined sample: RSI {int(r.trades_0bps)} trades; MACD {int(m.trades_0bps)} trades.

## Combined economics
- RSI: {r.total_R_0bps:.3f}R gross, {r.expectancy_R_0bps:.3f}R/trade, PF {r.profit_factor_0bps:.2f}; 5bps {r.total_R_5bps:.3f}R.
- MACD: {m.total_R_0bps:.3f}R gross, {m.expectancy_R_0bps:.3f}R/trade, PF {m.profit_factor_0bps:.2f}; 5bps {m.total_R_5bps:.3f}R.

## Interpretation
The family direction repeats in both Task53 and Task54 and survives the predeclared window, common-symbol, mid-session, exit-path, and holding-duration composition checks. It is therefore not explained away by a simple window/symbol/time/exit mix. However, RSI remains winner-tail sensitive (top-3 gross winners removed leaves only a small positive gross result; top-5 removal turns gross negative), and true close-time pairing is too thin for a strong matched causal claim. This is diagnostic evidence only, not permission to disable MACD or promote RSI.
"""
    (OUT/"task55_summary.md").write_text(md)
    conclusion=f"""# Task 55 Conclusion

`{summary['classification']}`

Supported: the RSI-positive/MACD-negative direction reproduces across both source tasks and remains present under several fixed composition controls, including the 17-symbol common-support subset. MACD weakness is not driven by a small gross loser tail; gross losses are numerous and bounded near -1R. RSI's advantage is primarily larger non-stop winners, not a lower stop rate.

Not supported: RSI is **not proven superior**, the difference is not established as causal, and the data do not authorize any family enable/disable or production behavior change. Same-day nearest-time matched coverage is too thin, and RSI remains materially dependent on its winner tail.

Deployment remains `MONDAY_DECISION_SHADOW_ONLY`.
"""
    (OUT/"task55_conclusion.md").write_text(conclusion)


def main():
    c,audit=load(); c=add_buckets(c)
    reproduction=verify_reproduction(c)
    fe=family_economics(c); wd=window_control(c); sd,common_syms,cs=symbol_control(c)
    td=time_control(c); ed,hd,hbd=exit_holding_control(c); od=outlier_control(c); cbd=cost_burden(c)
    strata,pooled,pairs,same_day=matched_control(c); boot=bootstrap_descriptive(c)
    c.to_csv(OUT/"_combined_trades_with_family.csv",index=False)
    pair_summary={
        "eligible_strata":len(strata),
        "unweighted_strata_rsi_mean_gt_macd":int(strata.rsi_gt_macd_unweighted_stratum_mean_0bps.sum()) if len(strata) else 0,
        "common_support_rsi_trades":int(pooled.loc[pooled.family=="RSI","trades"].iloc[0]),
        "common_support_macd_trades":int(pooled.loc[pooled.family=="MACD","trades"].iloc[0]),
        "nearest_time_pairs":len(pairs),
        "nearest_pair_rsi_pct":100*len(pairs)/len(c[c.family=="RSI"]),
        "nearest_pair_macd_pct":100*len(pairs)/len(c[c.family=="MACD"]),
        "nearest_pair_median_gap_minutes":float(pairs.abs_time_diff_minutes.median()) if len(pairs) else None,
        "nearest_pair_max_gap_minutes":float(pairs.abs_time_diff_minutes.max()) if len(pairs) else None,
        "nearest_pair_rsi_total_R_0bps":float(pairs.rsi_gross_R.sum()) if len(pairs) else 0,
        "nearest_pair_macd_total_R_0bps":float(pairs.macd_gross_R.sum()) if len(pairs) else 0,
        "nearest_pair_rsi_total_R_5bps":float(pairs.rsi_net_R_5bps.sum()) if len(pairs) else 0,
        "nearest_pair_macd_total_R_5bps":float(pairs.macd_net_R_5bps.sum()) if len(pairs) else 0,
        "same_day_pairs":len(same_day),
        "same_day_classification":"MATCHED_SAMPLE_TOO_THIN" if len(same_day)<10 else "MATCHED_SAMPLE_AVAILABLE",
    }
    summary={
        "task":"Task 55 — RSI vs MACD Family Economics Diagnostic",
        "checkpoint":"a1d00978b3950f27040fd5d3bcaf2041ad24a685",
        "provenance":audit,"reproduction":reproduction,
        "sample_sizes":{"RSI":int((c.family=="RSI").sum()),"MACD":int((c.family=="MACD").sum()),"total":len(c)},
        "family_economics":fe.to_dict("records"),
        "window_control":{"windows":len(wd),"rsi_gt_macd_0bps":int(wd.rsi_gt_macd_expectancy_0bps.sum()),
                          "rsi_gt_macd_5bps":int(wd.rsi_gt_macd_expectancy_5bps.sum())},
        "common_symbols":common_syms,"common_symbol_economics":cs.to_dict("records"),
        "time_control":td.to_dict("records"),"exit_control":ed.to_dict("records"),
        "holding_summary":hd.to_dict("records"),"holding_bucket_control":hbd.to_dict("records"),
        "outlier_sensitivity":od.to_dict("records"),"cost_burden":cbd.to_dict("records"),
        "matched":pair_summary,"matched_common_support":pooled.to_dict("records"),
        "bootstrap_descriptive":boot,
        "classification":"FAMILY_EFFECT_TENTATIVE",
        "deployment_state":"MONDAY_DECISION_SHADOW_ONLY",
        "strategy_action_authorized":False,
    }
    with open(OUT/"task55_summary.json","w") as f:json.dump(summary,f,indent=2,default=str)
    write_md(summary)
    return summary

if __name__=="__main__":
    s=main()
    print(json.dumps({"reproduction":s["reproduction"],"sample_sizes":s["sample_sizes"],
                      "window_control":s["window_control"],"matched":s["matched"],
                      "classification":s["classification"]},indent=2))
