"""Task75 closure A2 -- RAW-vs-ALL attribution ONLY, re-run on the EXISTING archived development data with two DATA
fixes (survival gates and thresholds are NOT re-run and NOT changed):
  1. corporate_action_audit_v2.json (ex-date selection) instead of the V1 audit;
  2. CENT-ROUNDING tolerance: Alpaca ALL prices are back-adjusted and then rounded to $0.01, so a trade whose price
     changed only through a uniform back-adjustment factor can show entry/exit factors that differ by up to the rounding
     bound. A PRICE_OR_PNL_CHANGED trade with no own event is OTHER_EXPLAINED_CENT_ROUNDING iff
         |fe / fx - 1| <= 0.005 / entry_all + 0.005 / exit_all + 1e-9
     (fe, fx = ALL/RAW entry and exit price factors). A selection flip with no own event, no event in the same Day0
     lookback, and a feature change within the same rounding bound on the lookback prices is RANK_FLIP_CENT_ROUNDING.
The registered survival.attribute_diff is reused unchanged; this module only re-labels its UNEXPLAINED rows.
Ledgers are recomputed with the unmodified evaluate() on the archived bytes (guard-checked at the LOAD layer).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.task75_v1 import contracts as C  # noqa: E402
from research.task75_v1.strategy import evaluate  # noqa: E402
from research.task75b_preflight import raw_parity as RP  # noqa: E402
from research.task75b_preflight import survival as S  # noqa: E402
from research.task75b_preflight.corrected_dev import ALL_DIR, regular_days  # noqa: E402
from research.task75b_preflight.holdout import HoldoutGuard, assert_research_path  # noqa: E402
from talonx_backtest.data import load_ohlcv_directory  # noqa: E402

RES = ROOT / "results" / "task75b_preflight"


def rounding_bound(entry_all: float, exit_all: float) -> float:
    return 0.005 / entry_all + 0.005 / exit_all + 1e-9


def relabel(diff: pd.DataFrame, raw_led: pd.DataFrame, all_led: pd.DataFrame) -> pd.DataFrame:
    key = ["symbol", "decision_day"]
    r = raw_led.assign(decision_day=raw_led["decision_day"].astype(str)).set_index(key)
    a = all_led.assign(decision_day=all_led["decision_day"].astype(str)).set_index(key)
    out = diff.copy()
    for i, row in out[out["category"] == "UNEXPLAINED"].iterrows():
        k = (row["symbol"], row["decision_day"])
        rr, aa = r.loc[k], a.loc[k]
        if row["change"] == "PRICE_OR_PNL_CHANGED":
            fe = float(aa["entry_price"]) / float(rr["entry_price"])
            fx = float(aa["exit_price"]) / float(rr["exit_price"])
            if abs(fe / fx - 1) <= rounding_bound(float(aa["entry_price"]), float(aa["exit_price"])):
                out.at[i, "category"] = "OTHER_EXPLAINED_CENT_ROUNDING"
        else:
            # selection flip: compare the market-adjusted feature; a flip driven purely by rounding moves it by
            # at most ~2 x (0.005 / price) x 100 pp -- use the symbol's own lookback-end price as scale
            fr, fa = rr["market_adjusted_return_pct"], aa["market_adjusted_return_pct"]
            if pd.notna(fr) and pd.notna(fa):
                px = float(aa["entry_price"]) if pd.notna(aa["entry_price"]) else float(rr["entry_price"]) \
                    if pd.notna(rr["entry_price"]) else None
                if px and abs(float(fa) - float(fr)) <= 100 * 4 * 0.005 / px + 1e-9:
                    out.at[i, "category"] = "RANK_FLIP_CENT_ROUNDING"
    return out


def main() -> dict:
    guard = HoldoutGuard.load()
    man = json.loads((RES / "dataset_manifest_all_v1.json").read_text())
    raw_man = json.loads(RP.MANIFEST.read_text())["slices"]
    A, R, cal = [], [], {}
    for label, sl in man["slices"].items():
        guard.check_range(*sl["window"], layer="LOAD")
        bars = load_ohlcv_directory(ALL_DIR / label, symbols=C.UNIVERSE + [C.MARKET_SYMBOL])
        guard.check_frame(bars, layer="LOAD")
        raw_bars = RP.load_slice(RP.ARCHIVE_DEFAULT, label, raw_man[label]["data_dir"].replace("\\", "/"))
        guard.check_frame(raw_bars, layer="LOAD")
        for f in (S.file_sha256(ALL_DIR / label / f"{s}.csv") == sl["files"][s]["sha256"] for s in sl["files"]):
            assert f, "archived ALL bytes changed"
        cal[label] = sorted(regular_days(bars).get("SPY", set()))
        A.append(evaluate(bars))
        R.append(evaluate(raw_bars))
    Aall, Rall = pd.concat(A, ignore_index=True), pd.concat(R, ignore_index=True)
    ca2 = json.loads((RES / "corporate_action_audit_v2.json").read_text())["events"]
    base = S.attribute_diff(Rall, Aall, ca2, cal)
    diff = relabel(base, Rall, Aall)
    rt = Rall[Rall["data_ready"] == True]  # noqa: E712
    at = Aall[Aall["data_ready"] == True]  # noqa: E712
    m = rt.assign(decision_day=rt.decision_day.astype(str)).merge(
        at.assign(decision_day=at.decision_day.astype(str)), on=["symbol", "decision_day"], how="outer", suffixes=("_r", "_a"))
    m["delta"] = m["gross_return_pct_a"].fillna(0) - m["gross_return_pct_r"].fillna(0)
    d = diff.merge(m[["symbol", "decision_day", "delta"]], on=["symbol", "decision_day"], how="left")
    by = d.groupby("category")["delta"].agg(["count", "sum"]).round(4)
    v1 = pd.read_csv(RES / "raw_vs_all_trade_diff.csv")
    v1_unexp = set(map(tuple, v1[v1.category == "UNEXPLAINED"][["symbol", "decision_day"]].astype(str).values))
    now = {tuple(x): c for x, c in zip(d[["symbol", "decision_day"]].astype(str).values, d["category"])}
    fate = pd.Series([now.get(k, "NOT_IN_V2_DIFF") for k in v1_unexp]).value_counts().to_dict()
    res = {"version": "ATTRIBUTION_V2 (ex-date audit + cent-rounding tolerance; survival NOT re-run)",
           "ledgers_reproduce_registered_selection": int(len(at)) == 1000 and abs(float(at.gross_return_pct.mean()) -
                                                                                 0.22962404880649456) < 1e-12,
           "by_category": {c: {"count": int(r["count"]), "gross_pp": float(r["sum"])} for c, r in by.iterrows()},
           "v1_unexplained_391_now": fate,
           "unexplained_now": int((d.category == "UNEXPLAINED").sum()),
           "residual_unexplained_gross_pp": float(d.loc[d.category == "UNEXPLAINED", "delta"].sum()),
           "total_change_pp": float(d["delta"].sum())}
    assert_research_path(RES / "attribution_v2.json")
    d.to_csv(RES / "raw_vs_all_trade_diff_v2.csv", index=False)
    (RES / "attribution_v2.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
