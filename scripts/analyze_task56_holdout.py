"""Generate the frozen Task 56 family diagnostics and classification."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "task56_independent_family_holdout"
WINDOWS = ["H1_early", "H2_middle", "H3_late"]
FAMILIES = ["RSI", "MACD"]


def family(signal):
    value = str(signal).lower()
    if value.startswith("rsi_"): return "RSI"
    if value.startswith("macd_"): return "MACD"
    if value.startswith("ma_"): return "MA"
    return "OTHER"


def pf(values):
    values = pd.Series(values).dropna().astype(float)
    gains = values[values > 0].sum(); losses = -values[values < 0].sum()
    if losses == 0: return math.inf if gains > 0 else math.nan
    return float(gains / losses)


def metrics(df, scope=None):
    gross = df.gross_R.astype(float) if len(df) else pd.Series(dtype=float)
    cost = df.R_5bps.astype(float) if len(df) else pd.Series(dtype=float)
    row = dict(scope or {})
    row.update({
        "trades": int(len(df)), "wins": int((gross > 0).sum()), "losses": int((gross < 0).sum()),
        "gross_total_R": float(gross.sum()), "gross_expectancy_R": float(gross.mean()) if len(df) else math.nan,
        "gross_profit_factor": pf(gross), "total_R_5bps": float(cost.sum()),
        "expectancy_R_5bps": float(cost.mean()) if len(df) else math.nan, "profit_factor_5bps": pf(cost),
    })
    return row


def grouped(df, columns):
    rows = []
    for keys, group in df.groupby(columns, dropna=False):
        if not isinstance(keys, tuple): keys = (keys,)
        rows.append(metrics(group, dict(zip(columns, keys))))
    return pd.DataFrame(rows)


def json_clean(value):
    if isinstance(value, dict): return {k: json_clean(v) for k, v in value.items()}
    if isinstance(value, list): return [json_clean(v) for v in value]
    if isinstance(value, (float, np.floating)) and not math.isfinite(float(value)): return None
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.bool_): return bool(value)
    return value


def main():
    parts = [pd.read_csv(OUT / f"raw_trades_{w}.csv") for w in WINDOWS]
    trades = pd.concat(parts, ignore_index=True)
    trades["family"] = trades.signal_type.map(family)
    trades["risk"] = (trades.entry_price - trades.stop_price).abs()
    trades["risk_pct_entry"] = 100 * trades.risk / trades.entry_price
    trades["R_5bps"] = (trades.exit_price * (1 - 0.0005) - trades.entry_price * (1 + 0.0005)) / trades.risk
    trades["cost_R_5bps"] = trades.gross_R - trades.R_5bps
    entry_et = pd.to_datetime(trades.entry_timestamp, utc=True).dt.tz_convert("America/New_York")
    minutes = entry_et.dt.hour * 60 + entry_et.dt.minute
    trades["time_bucket"] = np.select([minutes < 630, minutes < 900], ["OPEN_0930_1030", "MID_1030_1500"], default="CLOSE_1500_ONWARD")
    holding_min = trades.holding_seconds / 60
    trades["holding_bucket"] = np.select([holding_min <= 15, holding_min <= 60], ["SHORT_LE_15M", "MEDIUM_15_60M"], default="LONG_GT_60M")
    trades.to_csv(OUT / "raw_trades_all.csv", index=False)

    relevant = trades[trades.family.isin(FAMILIES)].copy()
    family_summary = pd.DataFrame([metrics(relevant[relevant.family == f], {"family": f}) for f in FAMILIES])
    window = grouped(relevant, ["window", "family"])
    symbol = grouped(relevant, ["symbol", "family"])
    time_table = grouped(relevant, ["time_bucket", "family"])
    exit_table = grouped(relevant, ["exit_reason", "family"])
    holding_table = grouped(relevant, ["holding_bucket", "family"])
    for frame, name in [(family_summary,"family_economics.csv"),(window,"window_family_economics.csv"),(symbol,"symbol_family_economics.csv"),(time_table,"time_of_day_family_economics.csv"),(exit_table,"exit_path_family_economics.csv"),(holding_table,"holding_duration_family_economics.csv")]:
        frame.to_csv(OUT / name, index=False)

    family_symbols = {f: set(relevant.loc[relevant.family == f, "symbol"]) for f in FAMILIES}
    common_symbols = sorted(family_symbols["RSI"] & family_symbols["MACD"])
    common = relevant[relevant.symbol.isin(common_symbols)]
    common_table = pd.DataFrame([metrics(common[common.family == f], {"family": f, "common_symbol_count": len(common_symbols)}) for f in FAMILIES])
    common_table.to_csv(OUT / "common_symbol_support.csv", index=False)

    concentration_rows = []
    sensitivity_rows = []
    geometry_rows = []
    for fam in FAMILIES:
        group = relevant[relevant.family == fam].copy()
        counts = group.groupby("symbol").size().sort_values(ascending=False)
        abs_r = group.groupby("symbol").gross_R.sum().abs().sort_values(ascending=False)
        concentration_rows.append({
            "family": fam, "symbols": int(group.symbol.nunique()),
            "top1_trade_share": float(counts.head(1).sum()/len(group)) if len(group) else math.nan,
            "top3_trade_share": float(counts.head(3).sum()/len(group)) if len(group) else math.nan,
            "top5_trade_share": float(counts.head(5).sum()/len(group)) if len(group) else math.nan,
            "top1_abs_R_concentration": float(abs_r.head(1).sum()/abs_r.sum()) if abs_r.sum() else math.nan,
            "top3_abs_R_concentration": float(abs_r.head(3).sum()/abs_r.sum()) if abs_r.sum() else math.nan,
            "top5_abs_R_concentration": float(abs_r.head(5).sum()/abs_r.sum()) if abs_r.sum() else math.nan,
        })
        ordered_best = group.sort_values("gross_R", ascending=False)
        ordered_worst = group.sort_values("gross_R", ascending=True)
        row = {"family": fam, "base_gross_total_R": float(group.gross_R.sum()), "base_5bps_total_R": float(group.R_5bps.sum())}
        for n in (1,3,5):
            no_best = ordered_best.iloc[n:]; no_worst = ordered_worst.iloc[n:]
            row[f"gross_total_after_remove_top{n}"] = float(no_best.gross_R.sum())
            row[f"gross_expectancy_after_remove_top{n}"] = float(no_best.gross_R.mean()) if len(no_best) else math.nan
            row[f"5bps_total_after_remove_top{n}"] = float(no_best.R_5bps.sum())
            row[f"5bps_expectancy_after_remove_top{n}"] = float(no_best.R_5bps.mean()) if len(no_best) else math.nan
            row[f"gross_total_after_remove_worst{n}"] = float(no_worst.gross_R.sum())
            row[f"gross_expectancy_after_remove_worst{n}"] = float(no_worst.gross_R.mean()) if len(no_worst) else math.nan
            row[f"5bps_total_after_remove_worst{n}"] = float(no_worst.R_5bps.sum())
            row[f"5bps_expectancy_after_remove_worst{n}"] = float(no_worst.R_5bps.mean()) if len(no_worst) else math.nan
        sensitivity_rows.append(row)
        geometry_rows.append({
            "family": fam, "trades": len(group), "mean_cost_in_R_5bps": float(group.cost_R_5bps.mean()),
            "median_cost_in_R_5bps": float(group.cost_R_5bps.median()),
            "mean_stop_risk_pct": float(group.risk_pct_entry.mean()), "median_stop_risk_pct": float(group.risk_pct_entry.median()),
            "p25_stop_risk_pct": float(group.risk_pct_entry.quantile(.25)), "p75_stop_risk_pct": float(group.risk_pct_entry.quantile(.75)),
        })
    concentration = pd.DataFrame(concentration_rows); concentration.to_csv(OUT / "symbol_concentration.csv", index=False)
    sensitivity = pd.DataFrame(sensitivity_rows); sensitivity.to_csv(OUT / "winner_loser_sensitivity.csv", index=False)
    geometry = pd.DataFrame(geometry_rows); geometry.to_csv(OUT / "cost_and_stop_geometry.csv", index=False)
    grouped(relevant, ["geometry_path", "family"]).to_csv(OUT / "geometry_path_family_economics.csv", index=False)

    holding_stats = relevant.groupby("family").holding_seconds.agg(["count","mean","median"]).reset_index()
    holding_stats["mean_minutes"] = holding_stats["mean"]/60; holding_stats["median_minutes"] = holding_stats["median"]/60
    holding_stats.drop(columns=["mean","median"]).to_csv(OUT / "holding_duration_summary.csv", index=False)

    ma = trades[trades.family == "MA"]
    ma_summary = metrics(ma, {"family": "MA"})
    pd.DataFrame([ma_summary]).to_csv(OUT / "ma_trade_summary.csv", index=False)

    fs = {r["family"]: r for r in family_summary.to_dict("records")}
    per_window = {(r.window, r.family): r for r in window.itertuples()}
    floor_checks = {
        "combined_at_least_60": len(relevant) >= 60,
        "rsi_at_least_20": len(relevant[relevant.family=="RSI"]) >= 20,
        "macd_at_least_20": len(relevant[relevant.family=="MACD"]) >= 20,
        "rsi_at_least_2_windows": relevant.loc[relevant.family=="RSI","window"].nunique() >= 2,
        "macd_at_least_2_windows": relevant.loc[relevant.family=="MACD","window"].nunique() >= 2,
        "rsi_at_least_5_symbols": relevant.loc[relevant.family=="RSI","symbol"].nunique() >= 5,
        "macd_at_least_5_symbols": relevant.loc[relevant.family=="MACD","symbol"].nunique() >= 5,
    }
    floor_pass = all(floor_checks.values())
    gross_hypothesis = fs["RSI"]["gross_expectancy_R"] > fs["MACD"]["gross_expectancy_R"]
    cost_hypothesis = fs["RSI"]["expectancy_R_5bps"] > fs["MACD"]["expectancy_R_5bps"]
    gross_windows = sum(per_window[(w,"RSI")].gross_expectancy_R > per_window[(w,"MACD")].gross_expectancy_R for w in WINDOWS)
    cost_windows = sum(per_window[(w,"RSI")].expectancy_R_5bps > per_window[(w,"MACD")].expectancy_R_5bps for w in WINDOWS)
    common_map = {r["family"]: r for r in common_table.to_dict("records")}
    common_support = common_map["RSI"]["gross_expectancy_R"] > common_map["MACD"]["gross_expectancy_R"] and common_map["RSI"]["expectancy_R_5bps"] > common_map["MACD"]["expectancy_R_5bps"]
    sens = {r["family"]: r for r in sensitivity.to_dict("records")}
    top3_survival = sens["RSI"]["gross_expectancy_after_remove_top3"] > fs["MACD"]["gross_expectancy_R"] and sens["RSI"]["5bps_expectancy_after_remove_top3"] > fs["MACD"]["expectancy_R_5bps"]
    not_one_symbol = all(len(family_symbols[f]) >= 5 for f in FAMILIES)
    if not floor_pass:
        classification = "INCONCLUSIVE_TOO_THIN"
    elif gross_hypothesis and cost_hypothesis and gross_windows >= 2 and cost_windows >= 2 and common_support and top3_survival and not_one_symbol:
        classification = "FAMILY_EFFECT_REPLICATED"
    elif (not gross_hypothesis and not cost_hypothesis and gross_windows <= 1 and cost_windows <= 1):
        classification = "FAMILY_EFFECT_NOT_REPLICATED"
    else:
        classification = "FAMILY_EFFECT_WEAKENED"

    robustness = {
        "comparative_gross_hypothesis": gross_hypothesis, "comparative_5bps_hypothesis": cost_hypothesis,
        "windows_rsi_gt_macd_gross": gross_windows, "windows_rsi_gt_macd_5bps": cost_windows,
        "common_symbols": common_symbols, "common_symbol_support_pass": common_support,
        "rsi_top3_winner_removal_comparative_pass": top3_survival, "not_confined_to_one_symbol": not_one_symbol,
    }
    summary = {
        "task": "Task 56 - Independent Family Holdout Validation", "classification": classification,
        "deployment_state": "MONDAY_DECISION_SHADOW_ONLY", "family_summary": fs,
        "interpretability_floor": {"passed": floor_pass, "checks": floor_checks}, "robustness": robustness,
        "absolute_edge_questions": {
            "rsi_gross_positive": fs["RSI"]["gross_expectancy_R"] > 0,
            "rsi_5bps_positive": fs["RSI"]["expectancy_R_5bps"] > 0,
            "macd_gross_negative": fs["MACD"]["gross_expectancy_R"] < 0,
            "macd_5bps_negative": fs["MACD"]["expectancy_R_5bps"] < 0,
        },
        "ma_summary": ma_summary, "strategy_action_authorized": False, "capital_used": False,
    }
    summary = json_clean(summary)
    (OUT / "task56_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8", newline="\n")
    lines = [
        "# Task 56 — Independent Family Holdout Validation (resumed)", "", f"**Classification:** `{classification}`", "",
        "This completed run resumed the exact protocol frozen at `8de8d49` after the earlier infrastructure-only `VALIDATION_BLOCKED` attempt. The earlier blocker remains historical evidence and is not interpreted as a strategy result.", "",
        "## Family results", "", "| Family | Trades | W/L | Gross total R | Gross expectancy | Gross PF | 5bps total R | 5bps expectancy | 5bps PF |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for fam in FAMILIES:
        r=fs[fam]; lines.append(f"| {fam} | {r['trades']} | {r['wins']}/{r['losses']} | {r['gross_total_R']:.3f} | {r['gross_expectancy_R']:.3f} | {r['gross_profit_factor']:.3f} | {r['total_R_5bps']:.3f} | {r['expectancy_R_5bps']:.3f} | {r['profit_factor_5bps']:.3f} |")
    lines += ["", "## Comparative replication vs absolute edge", "", f"RSI exceeded MACD in {gross_windows}/3 windows gross and {cost_windows}/3 windows at 5bps. Common-symbol support: {common_support}. RSI top-three-winner removal comparative survival: {top3_survival}.", "", f"Absolute edge: RSI gross positive={summary['absolute_edge_questions']['rsi_gross_positive']}, RSI 5bps positive={summary['absolute_edge_questions']['rsi_5bps_positive']}; MACD gross negative={summary['absolute_edge_questions']['macd_gross_negative']}, MACD 5bps negative={summary['absolute_edge_questions']['macd_5bps_negative']}. Comparative replication does not make RSI production-ready.", "", "## Interpretability and deployment", "", f"Interpretability floor: {'PASS' if floor_pass else 'FAIL'}. MA trades: {ma_summary['trades']}. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; no capital or family enable/disable action is authorized."]
    (OUT / "task56_summary.md").write_text("\n".join(lines)+"\n", encoding="utf-8", newline="\n")
    (OUT / "task56_conclusion.md").write_text(f"# Task 56 Conclusion\n\n`{classification}`\n\nThe earlier `VALIDATION_BLOCKED` attempt was infrastructure-only. This resumed run used the unchanged frozen protocol and completed all gates, replays, and diagnostics. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; no capital or family action is authorized.\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
