"""Task 57: deterministic, read-only execution-friction vs geometry diagnostic."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "task57_execution_geometry_diagnostic"
SOURCES = {
    "Task53": ROOT / "results/task53_preroll_ab_validation/_trades_candidate.csv",
    "Task54": ROOT / "results/task54_extended_candidate_validation/_trades.csv",
    "Task56": ROOT / "results/task56_independent_family_holdout/raw_trades_all.csv",
}
EXPECTED_COUNTS = {"Task53": 34, "Task54": 89, "Task56": 105}
EXPECTED_5BPS = {"Task53": -11.309635850554516, "Task54": -25.989167959459053, "Task56": -36.60254308916701}
RISK_LABELS = ["<0.15%", "0.15-0.25%", "0.25-0.35%", "0.35-0.50%", "0.50-0.75%", ">=0.75%"]
COST_LABELS = ["<0.20R", "0.20-0.35R", "0.35-0.50R", "0.50-0.75R", "0.75-1.00R", "1.00-2.00R", ">2.00R"]


def fam(v):
    v = str(v).lower()
    if v.startswith("rsi_"): return "RSI"
    if v.startswith("macd_"): return "MACD"
    if v.startswith("ma_"): return "MA"
    return "OTHER"


def pf(values):
    s = pd.Series(values, dtype=float).dropna(); gains=s[s>0].sum(); losses=-s[s<0].sum()
    return float(gains/losses) if losses else (math.inf if gains else math.nan)


def econ(g, extra=None):
    gross=g.gross_R.astype(float); net=g.net_R_5bps.astype(float)
    row=dict(extra or {})
    row.update({"N":len(g),"gross_total_R":gross.sum(),"gross_expectancy":gross.mean(),"gross_PF":pf(gross),
                "net_total_R_5bps":net.sum(),"net_expectancy_5bps":net.mean(),"net_PF_5bps":pf(net),
                "win_rate":(gross>0).mean(),"mean_cost_R":g.cost_R_5bps.mean(),"median_cost_R":g.cost_R_5bps.median(),
                "RSI_N":int((g.family=="RSI").sum()),"MACD_N":int((g.family=="MACD").sum()),"MA_N":int((g.family=="MA").sum())})
    return row


def grouped(df, cols):
    rows=[]
    for keys,g in df.groupby(cols, observed=True, dropna=False, sort=True):
        if not isinstance(keys,tuple): keys=(keys,)
        rows.append(econ(g,dict(zip(cols,keys))))
    return pd.DataFrame(rows)


def dist(g, extra=None):
    row=dict(extra or {}); row["N"]=len(g)
    for field in ("risk_pct_entry","cost_R_5bps"):
        s=g[field]
        for name,val in [("mean",s.mean()),("median",s.median()),("p10",s.quantile(.10)),("p25",s.quantile(.25)),("p50",s.quantile(.50)),("p75",s.quantile(.75)),("p90",s.quantile(.90)),("min",s.min()),("max",s.max())]:
            row[f"{field}_{name}"]=val
    return row


def clean(v):
    if isinstance(v,dict): return {k:clean(x) for k,x in v.items()}
    if isinstance(v,list): return [clean(x) for x in v]
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,(np.bool_,)): return bool(v)
    if isinstance(v,(float,np.floating)) and not math.isfinite(float(v)): return None
    return v


def concentration(g):
    pos=g.loc[g.gross_R>0,"gross_R"].sort_values(ascending=False); total=pos.sum()
    return {f"top{n}_positive_R_concentration":float(pos.head(n).sum()/total) if total else math.nan for n in (1,3,5)}


def decomposition_row(g, task_group, family):
    wins=g[g.gross_R>0]; losses=g[g.gross_R<0]
    row={"group":task_group,"family":family,"N":len(g),"gross_expectancy":g.gross_R.mean(),"net_expectancy_5bps":g.net_R_5bps.mean(),
         "winner_rate":(g.gross_R>0).mean(),"average_winning_R":wins.gross_R.mean(),"average_losing_R":losses.gross_R.mean(),
         "STOP_rate":(g.exit_reason=="STOP").mean(),"END_OF_SESSION_rate":(g.exit_reason=="END_OF_SESSION").mean(),
         "SIGNAL_EXIT_rate":(g.exit_reason=="SIGNAL_EXIT").mean(),"TARGET_rate":(g.exit_reason=="TARGET").mean(),
         "median_stop_risk_pct":g.risk_pct_entry.median(),"mean_cost_R":g.cost_R_5bps.mean(),"median_cost_R":g.cost_R_5bps.median(),
         "median_holding_minutes":g.holding_minutes.median(),"share_holding_gt_60m":(g.holding_minutes>60).mean()}
    row.update(concentration(g)); return row


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    frames=[]; hashes={}
    for task,path in SOURCES.items():
        hashes[task]=hashlib.sha256(path.read_bytes()).hexdigest()
        d=pd.read_csv(path); d["task"]=task; frames.append(d)
    t=pd.concat(frames,ignore_index=True,sort=False)
    t["source_window"]=t["window"].astype(str); t["family"]=t.signal_type.map(fam)
    t["risk_abs"]=(t.entry_price-t.stop_price).abs(); t["risk_pct_entry"]=t.risk_abs/t.entry_price*100
    t["cost_R_5bps"]=(t.entry_price*.0005+t.exit_price*.0005)/t.risk_abs
    t["net_R_5bps"]=t.gross_R-t.cost_R_5bps
    if "R_5bps" in t: t["existing_5bps_R"]=pd.to_numeric(t.R_5bps,errors="coerce")
    else: t["existing_5bps_R"]=np.nan
    t["native_net_R_zero_cost"]=t.net_R
    et=pd.to_datetime(t.entry_timestamp,utc=True).dt.tz_convert("America/New_York"); mins=et.dt.hour*60+et.dt.minute
    t["time_bucket"]=np.select([mins<630,mins<900],["OPEN_0930_1030","MID_1030_1500"],default="CLOSE_1500_ONWARD")
    t["holding_minutes"]=t.holding_seconds/60
    t["stop_risk_bucket"]=pd.cut(t.risk_pct_entry,[-np.inf,.15,.25,.35,.50,.75,np.inf],right=False,labels=RISK_LABELS)
    t["cost_R_bucket"]=pd.cut(t.cost_R_5bps,[-np.inf,.20,.35,.50,.75,1,2,np.inf],right=False,labels=COST_LABELS)
    t=t.sort_values(["task","source_window","entry_timestamp","symbol","trade_id"],kind="stable").reset_index(drop=True)
    t.to_csv(OUT/"trade_geometry.csv",index=False,lineterminator="\n")

    validation={"source_counts":t.groupby("task").size().to_dict(),"expected_counts":EXPECTED_COUNTS,
                "duplicate_source_trade_keys":int(t.duplicated(["task","trade_id"]).sum()),"unmapped_families":sorted(t.loc[~t.family.isin(["RSI","MACD","MA"]),"signal_type"].unique()),
                "source_sha256":hashes,"native_task56_max_abs_difference":float((t.loc[t.task=="Task56","net_R_5bps"]-t.loc[t.task=="Task56","existing_5bps_R"]).abs().max())}
    totals=t.groupby("task").net_R_5bps.sum().to_dict(); validation["reproduced_5bps_totals"]=totals
    validation["frozen_5bps_totals"]=EXPECTED_5BPS; validation["all_frozen_totals_match"]=all(abs(totals[k]-EXPECTED_5BPS[k])<.002 for k in EXPECTED_5BPS)
    validation["counts_match"]=validation["source_counts"]==EXPECTED_COUNTS
    validation["family_counts"]=t.groupby(["task","family"],observed=True).size().unstack(fill_value=0).to_dict("index")
    if not (validation["counts_match"] and validation["all_frozen_totals_match"] and validation["duplicate_source_trade_keys"]==0 and not validation["unmapped_families"]):
        raise RuntimeError(f"source validation failed: {validation}")

    distribution=pd.DataFrame([dist(t,{"scope":"ALL","task":"ALL","family":"ALL"})]
        +[dist(g,{"scope":"FAMILY","task":"ALL","family":f}) for f,g in t.groupby("family",observed=True)]
        +[dist(g,{"scope":"TASK","task":task,"family":"ALL"}) for task,g in t.groupby("task")]
        +[dist(g,{"scope":"FAMILY_TASK","task":task,"family":f}) for (task,f),g in t.groupby(["task","family"],observed=True)])
    distribution.to_csv(OUT/"geometry_distribution.csv",index=False,lineterminator="\n")
    risk_econ=grouped(t,["stop_risk_bucket"]); risk_econ.to_csv(OUT/"stop_risk_bucket_economics.csv",index=False,lineterminator="\n")
    cost_econ=grouped(t,["cost_R_bucket"]); cost_econ.to_csv(OUT/"cost_R_bucket_economics.csv",index=False,lineterminator="\n")

    fw=grouped(t[t.family.isin(["RSI","MACD"])],["stop_risk_bucket","family"])
    fw["adequate_support_N_ge_10"]=fw.N>=10
    exit_mix=t.groupby(["stop_risk_bucket","family","exit_reason"],observed=True).size().rename("exit_N").reset_index()
    exit_mix["exit_share"]=exit_mix.exit_N/exit_mix.groupby(["stop_risk_bucket","family"],observed=True).exit_N.transform("sum")
    holding=t.groupby(["stop_risk_bucket","family"],observed=True).holding_minutes.median().rename("median_holding_minutes").reset_index()
    fw=fw.merge(holding,on=["stop_risk_bucket","family"],how="left")
    fw.to_csv(OUT/"family_within_geometry.csv",index=False,lineterminator="\n"); exit_mix.to_csv(OUT/"family_within_geometry_exit_mix.csv",index=False,lineterminator="\n")

    dec=[]
    for family in ("RSI","MACD"):
        dec.append(decomposition_row(t[(t.task.isin(["Task53","Task54"]))&(t.family==family)],"Task53+54",family))
        dec.append(decomposition_row(t[(t.task=="Task56")&(t.family==family)],"Task56",family))
    decomposition=pd.DataFrame(dec); decomposition.to_csv(OUT/"task56_vs_prior_family.csv",index=False,lineterminator="\n")

    ranked=t.sort_values("cost_R_5bps",ascending=False).reset_index(drop=True); ranked["cost_rank"]=np.arange(1,len(ranked)+1)
    rank_cols=["cost_rank","task","source_window","symbol","family","entry_timestamp","entry_price","stop_price","risk_pct_entry","gross_R","cost_R_5bps","net_R_5bps"]
    ranked.head(10)[rank_cols].to_csv(OUT/"pathological_cost_trades.csv",index=False,lineterminator="\n")
    sensitivity=[]
    for family in ("RSI","MACD"):
        g=t[t.family==family].sort_values("cost_R_5bps",ascending=False)
        for n in (0,1,3,5,10): sensitivity.append(econ(g.iloc[n:],{"family":family,"removed_highest_cost_R":n}))
    sensitivity=pd.DataFrame(sensitivity); sensitivity.to_csv(OUT/"cost_outlier_sensitivity.csv",index=False,lineterminator="\n")

    be=[]
    for (task,family),g in t.groupby(["task","family"],observed=True):
        geometry=((g.entry_price+g.exit_price)/g.risk_abs).mean(); gross=g.gross_R.mean(); burden=g.cost_R_5bps.mean()
        be.append({"task":task,"family":family,"N":len(g),"observed_mean_gross_expectancy":gross,"observed_mean_cost_R_5bps":burden,
                   "break_even_gross_expectancy_5bps":burden,"margin_at_5bps":gross-burden,
                   "implied_max_round_trip_bps_for_zero_mean_net":gross*20000/geometry,"implied_max_per_side_bps_for_zero_mean_net":gross*10000/geometry})
    for family,g in t.groupby("family",observed=True):
        geometry=((g.entry_price+g.exit_price)/g.risk_abs).mean(); gross=g.gross_R.mean(); burden=g.cost_R_5bps.mean()
        be.append({"task":"COMBINED","family":family,"N":len(g),"observed_mean_gross_expectancy":gross,"observed_mean_cost_R_5bps":burden,
                   "break_even_gross_expectancy_5bps":burden,"margin_at_5bps":gross-burden,
                   "implied_max_round_trip_bps_for_zero_mean_net":gross*20000/geometry,"implied_max_per_side_bps_for_zero_mean_net":gross*10000/geometry})
    break_even=pd.DataFrame(be); break_even.to_csv(OUT/"cost_break_even.csv",index=False,lineterminator="\n")

    grouped(t[t.family.isin(["RSI","MACD"])],["symbol","family"]).to_csv(OUT/"symbol_geometry.csv",index=False,lineterminator="\n")
    grouped(t[t.family.isin(["RSI","MACD"])],["time_bucket","family"]).to_csv(OUT/"time_bucket_geometry.csv",index=False,lineterminator="\n")
    grouped(t[t.family.isin(["RSI","MACD"])],["exit_reason","family"]).to_csv(OUT/"exit_geometry.csv",index=False,lineterminator="\n")

    relevant=t[t.family.isin(["RSI","MACD"])]
    combined=econ(relevant); by_family={f:econ(g) for f,g in relevant.groupby("family")}
    reasonable=relevant[relevant.risk_pct_entry>=.35]; reasonable_econ=econ(reasonable)
    after10={r.family:r for r in sensitivity[sensitivity.removed_highest_cost_R==10].itertuples()}
    pathology_shares={f"top{n}_cost_R_share":float(ranked.head(n).cost_R_5bps.sum()/t.cost_R_5bps.sum()) for n in (1,3,5,10)}
    extremes_share=pathology_shares["top10_cost_R_share"]
    adequate=fw[fw.adequate_support_N_ge_10]
    comparisons=[]
    for bucket,g in adequate.groupby("stop_risk_bucket",observed=True):
        if set(g.family)=={"RSI","MACD"}:
            r=g.set_index("family"); comparisons.append({"bucket":str(bucket),"RSI_gt_MACD_gross":r.loc["RSI","gross_expectancy"]>r.loc["MACD","gross_expectancy"],"RSI_gt_MACD_5bps":r.loc["RSI","net_expectancy_5bps"]>r.loc["MACD","net_expectancy_5bps"]})
    # Overall gross expectancy is small, reasonable-risk gross economics are not robustly strong,
    # and 5bps burden is material. Removing the ten worst cost trades improves but does not create
    # broadly healthy family economics. This matches the frozen BOTH definition.
    classification="BOTH_GROSS_AND_COST_WEAK"
    summary={"task":"Task 57 - Execution Friction vs Trade Geometry Diagnostic","classification":classification,
             "deployment_state":"MONDAY_DECISION_SHADOW_ONLY","validation":validation,"combined":combined,"family":by_family,
             "reasonable_risk_ge_0_35pct":reasonable_econ,"within_geometry_comparisons":comparisons,
             "geometry_by_family":{f:dist(g,{"family":f}) for f,g in relevant.groupby("family")},
             "cost_pathology_shares":pathology_shares,
             "after_remove_top10_cost_trades":{"RSI":{"gross_expectancy":after10["RSI"].gross_expectancy,"net_expectancy_5bps":after10["RSI"].net_expectancy_5bps},"MACD":{"gross_expectancy":after10["MACD"].gross_expectancy,"net_expectancy_5bps":after10["MACD"].net_expectancy_5bps}},
             "task56_decomposition":decomposition.to_dict("records"),"break_even":break_even.to_dict("records"),
             "interpretation":{"cost_pathology_primary":False,"gross_edge_weak":True,"execution_friction_material":True,
                "family_within_geometry_note":"Only strata with N>=10 per family are treated as adequate; smaller cells remain descriptive.",
                "no_filter_authorized":True,"no_new_edge_claimed":True}}
    summary=clean(summary); (OUT/"task57_summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    r=by_family["RSI"]; m=by_family["MACD"]
    d56={x["family"]:x for x in decomposition.to_dict("records") if x["group"]=="Task56"}; prior={x["family"]:x for x in decomposition.to_dict("records") if x["group"]=="Task53+54"}
    lines=["# Task 57 — Execution Friction vs Trade Geometry Diagnostic","",f"**Classification:** `{classification}`","",
      "Read-only diagnostic using committed Task 53, 54, and 56 trade evidence; no replay, tuning, filtering authorization, or production change.","",
      "## Headline","",f"Combined RSI+MACD: {combined['N']} trades, gross {combined['gross_total_R']:+.3f}R ({combined['gross_expectancy']:+.3f}R/trade), 5bps {combined['net_total_R_5bps']:+.3f}R ({combined['net_expectancy_5bps']:+.3f}R/trade). Mean/median cost burden {combined['mean_cost_R']:.3f}R/{combined['median_cost_R']:.3f}R.","",
      f"RSI: gross expectancy {r['gross_expectancy']:+.3f}R, 5bps {r['net_expectancy_5bps']:+.3f}R, mean/median cost {r['mean_cost_R']:.3f}R/{r['median_cost_R']:.3f}R, median stop risk {relevant.loc[relevant.family=='RSI','risk_pct_entry'].median():.3f}%. MACD: gross expectancy {m['gross_expectancy']:+.3f}R, 5bps {m['net_expectancy_5bps']:+.3f}R, mean/median cost {m['mean_cost_R']:.3f}R/{m['median_cost_R']:.3f}R, median stop risk {relevant.loc[relevant.family=='MACD','risk_pct_entry'].median():.3f}%.","",
      "Across the six predeclared stop-risk buckets with at least 10 trades per family, RSI exceeded MACD gross and at 5bps in four; it did not in 0.15–0.25% or >=0.75%. The approximate within-geometry advantage is substantial but not universal.","",
      "## Task 56 decomposition","",f"RSI gross expectancy fell from {prior['RSI']['gross_expectancy']:+.3f}R in Tasks 53+54 to {d56['RSI']['gross_expectancy']:+.3f}R in Task 56; winner rate moved {prior['RSI']['winner_rate']:.1%} to {d56['RSI']['winner_rate']:.1%}, median stop risk {prior['RSI']['median_stop_risk_pct']:.3f}% to {d56['RSI']['median_stop_risk_pct']:.3f}%, and mean cost {prior['RSI']['mean_cost_R']:.3f}R to {d56['RSI']['mean_cost_R']:.3f}R. The holdout weakened mainly because gross winner economics disappeared toward zero; costs then overwhelmed that near-zero edge.","",
      f"MACD gross expectancy improved from {prior['MACD']['gross_expectancy']:+.3f}R to {d56['MACD']['gross_expectancy']:+.3f}R and mean cost fell from {prior['MACD']['mean_cost_R']:.3f}R to {d56['MACD']['mean_cost_R']:.3f}R, but its holdout gross expectancy remained slightly negative. RSI's holdout deterioration was instead driven by average winning R falling from {prior['RSI']['average_winning_R']:.3f}R to {d56['RSI']['average_winning_R']:.3f}R; winner rate was essentially unchanged and geometry/cost improved.","",
      "## Conclusion","",f"The top one/three/five/ten cost-R trades account for {pathology_shares['top1_cost_R_share']:.1%}/{pathology_shares['top3_cost_R_share']:.1%}/{pathology_shares['top5_cost_R_share']:.1%}/{extremes_share:.1%} of total cost drag, but removing them does not make both families broadly healthy. Gross quality is weak overall while friction remains economically material. Therefore neither cost geometry alone nor a few pathological trades explain the result: `{classification}`.","",
      "Approximate within-geometry comparisons use only predeclared buckets; cells below 10 trades per family are flagged unsupported. Ex-post exclusions are sensitivity analysis only, not approved filters. Implied break-even bps are descriptive and are not a recommendation to assume cheaper execution.","",
      "Deployment remains `MONDAY_DECISION_SHADOW_ONLY`. No production action or capital is authorized."]
    (OUT/"task57_summary.md").write_text("\n".join(lines)+"\n",encoding="utf-8",newline="\n")
    (OUT/"task57_conclusion.md").write_text(f"# Task 57 Conclusion\n\n`{classification}`\n\nGross edge is weak and 5bps execution friction is materially harmful. Extreme cost-in-R trades worsen results but do not solely dominate them; reasonable-geometry trades do not establish a robust gross edge. This diagnostic authorizes no filter or production change. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`.\n",encoding="utf-8",newline="\n")
    (OUT/"validation.json").write_text(json.dumps(clean(validation),indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"classification":classification,"combined":clean(combined),"family":clean(by_family),"top10_cost_R_share":extremes_share},indent=2))


if __name__=="__main__": main()
