"""Task75B PREFLIGHT -- empirical proof of Alpaca adjustment=raw|split|all semantics, using corporate actions OUTSIDE both
reserved Task75 windows only (development-period / out-of-universe examples; no 2024 prices):
  KLAC 10:1 forward split, ex 2026-06-12 (development 2026 Q3, frozen universe)
  ORLY 15:1 forward split, ex 2025-06-10 (outside the universe)
  SPY  cash dividend 1.903516, ex 2026-06-18 (development 2026 Q3, the benchmark)
Daily SIP bars around each ex-date under all three adjustments; guard-checked at the DOWNLOAD layer.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.task75b_preflight.ca_audit import _headers, get  # noqa: E402,F401
from research.task75b_preflight.holdout import HoldoutGuard, assert_research_path  # noqa: E402

BARS = "https://data.alpaca.markets/v2/stocks/bars"
CASES = [("KLAC", "2026-06-08", "2026-06-17", "2026-06-12", "split 10:1"),
         ("ORLY", "2025-06-04", "2025-06-13", "2025-06-10", "split 15:1"),
         ("SPY", "2026-06-12", "2026-06-24", "2026-06-18", "dividend 1.903516")]


def bars(sym, start, end, adj, headers, guard):
    guard.check_range(start, end, layer="DOWNLOAD")
    import time
    time.sleep(2.0)
    q = urllib.parse.urlencode({"symbols": sym, "timeframe": "1Day", "start": start, "end": end, "feed": "sip",
                                "adjustment": adj, "limit": 100})
    with urllib.request.urlopen(urllib.request.Request(BARS + "?" + q, headers=headers), timeout=60) as r:
        return [(b["t"][:10], b["c"]) for b in json.loads(r.read())["bars"].get(sym, [])]


def main() -> dict:
    g, h = HoldoutGuard.load(), _headers()
    out = {}
    for sym, a, b, ex, what in CASES:
        series = {adj: dict(bars(sym, a, b, adj, h, g)) for adj in ("raw", "split", "all")}
        days = sorted(series["raw"])
        pre = max(d for d in days if d < ex)
        post = min(d for d in days if d >= ex)
        rows = [{"day": d, **{adj: series[adj].get(d) for adj in series}} for d in days]
        ratio = {adj: series[adj][post] / series[adj][pre] for adj in series}
        split_vs_raw_pre = series["split"][pre] / series["raw"][pre]
        all_vs_split_pre = series["all"][pre] / series["split"][pre]
        all_vs_split_post = series["all"][post] / series["split"][post]
        out[sym] = {"event": what, "ex_date": ex, "pre_day": pre, "post_day": post, "close_ratio_post_over_pre": ratio,
                    "split_over_raw_on_pre_day": split_vs_raw_pre, "all_over_split_on_pre_day": all_vs_split_pre,
                    "all_over_split_on_post_day": all_vs_split_post, "rows": rows}
    k, o, s = out["KLAC"], out["ORLY"], out["SPY"]
    verdict = {
        "RAW_contains_split_discontinuity": k["close_ratio_post_over_pre"]["raw"] < 0.2 and o["close_ratio_post_over_pre"]["raw"] < 0.2,
        "SPLIT_removes_split_discontinuity": 0.8 < k["close_ratio_post_over_pre"]["split"] < 1.25 and 0.8 < o["close_ratio_post_over_pre"]["split"] < 1.25,
        "SPLIT_does_not_neutralize_dividend": abs(s["all_over_split_on_pre_day"] - 1) > 1e-4 and abs(s["split_over_raw_on_pre_day"] - 1) < 1e-9,
        "ALL_split_adjusted": 0.8 < k["close_ratio_post_over_pre"]["all"] < 1.25,
        # ALL applies the CUMULATIVE factor of every LATER dividend up to the download date, so post-ex days also carry
        # a factor < 1 (from subsequent dividends); the dividend shows as the STEP in the all/split factor at ex-date.
        "ALL_dividend_adjusts_pre_ex_prices_down": s["all_over_split_on_pre_day"] < s["all_over_split_on_post_day"],
        "ALL_dividend_factor_step_matches_cash_amount": abs(
            (1 - s["all_over_split_on_pre_day"] / s["all_over_split_on_post_day"])
            * s["rows"][[r["day"] for r in s["rows"]].index(s["pre_day"])]["split"] - 1.903516) < 0.05,
        "ALL_is_download_date_dependent": s["all_over_split_on_post_day"] < 1 - 1e-6}
    res = {"cases": out, "verdict": verdict, "all_proven": all(verdict.values())}
    p = ROOT / "results" / "task75b_preflight" / "provider_semantics.json"
    assert_research_path(p)
    p.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = main()
    print(json.dumps({"verdict": r["verdict"], "all_proven": r["all_proven"]}, indent=1))
    for sym, c in r["cases"].items():
        print(sym, c["event"], "post/pre:", {k: round(v, 4) for k, v in c["close_ratio_post_over_pre"].items()},
              "split/raw pre:", round(c["split_over_raw_on_pre_day"], 6), "all/split pre:", round(c["all_over_split_on_pre_day"], 6),
              "all/split post:", round(c["all_over_split_on_post_day"], 6))
