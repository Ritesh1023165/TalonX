"""
TASK 124 Part 2 -- inventory of ALL existing locally-available price data
relevant to the 48 configured tickers, before any new acquisition is
considered. No returns computed; no strategy logic touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

RELEASE_ROOT = Path("C:/workspace/TalonX")
RESEARCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RELEASE_ROOT))

OUT = RESEARCH_ROOT / "results" / "task124_intraday_feasibility"
OUT.mkdir(parents=True, exist_ok=True)

DAILY_DIR_1 = RELEASE_ROOT / "results/task95g_broad_cross_sectional/_daily"   # Alpaca SIP adjustment=all
DAILY_DIR_2 = RELEASE_ROOT / "results/task107a_form4_feasibility/_prices"     # Alpaca SIP adjustment=all
MINUTE_DIR = RELEASE_ROOT / "results/task93_alpha_foundation/_canonical_data"  # Alpaca UNADJUSTED 1-min


def main() -> int:
    from talonx_ops.watchlist_coverage import build_coverage_map

    cov = build_coverage_map()
    snapshot_note = "live watchlist.db read this task -- snapshot date recorded below"
    now = pd.Timestamp.now(tz="UTC").isoformat()

    d1_files = {f.stem.upper() for f in DAILY_DIR_1.glob("*.csv")}
    d2_files = {f.stem.upper() for f in DAILY_DIR_2.glob("*.csv")}
    d3_files = {f.stem.upper() for f in MINUTE_DIR.glob("*.csv")}
    overlap_d1_d2 = sorted(d1_files & d2_files)

    manifest = []
    for t in cov["tickers"]:
        sym = t["symbol"]
        entry = {
            "symbol": sym, "status": t["status"], "configured_horizon": t.get("configured_horizon"),
            "snapshot_taken_at_utc": now,
            "daily_coverage": None, "minute_coverage": None,
        }
        if sym in d1_files:
            df = pd.read_csv(DAILY_DIR_1 / f"{sym}.csv", usecols=["date"], parse_dates=["date"])
            entry["daily_coverage"] = {
                "source_dir": "task95g_broad_cross_sectional/_daily", "provider": "Alpaca SIP",
                "adjustment": "all (split+dividend back-adjusted -- total-return proxy)",
                "first_date": str(df["date"].min().date()), "last_date": str(df["date"].max().date()),
                "n_rows": len(df),
            }
        elif sym in d2_files:
            df = pd.read_csv(DAILY_DIR_2 / f"{sym}.csv", usecols=["date"], parse_dates=["date"])
            entry["daily_coverage"] = {
                "source_dir": "task107a_form4_feasibility/_prices", "provider": "Alpaca SIP",
                "adjustment": "all (split+dividend back-adjusted -- total-return proxy)",
                "first_date": str(df["date"].min().date()), "last_date": str(df["date"].max().date()),
                "n_rows": len(df),
            }
        else:
            entry["daily_coverage"] = {"status": "NO_LOCAL_DATA_LOCATED"}

        if sym in d3_files:
            df = pd.read_csv(MINUTE_DIR / f"{sym}.csv", usecols=["timestamp"], parse_dates=["timestamp"])
            entry["minute_coverage"] = {
                "source_dir": "task93_alpha_foundation/_canonical_data", "provider": "Alpaca (unspecified feed in manifest)",
                "adjustment": "UNADJUSTED (per canonical_dataset_manifest.json)",
                "first_ts": str(df["timestamp"].min()), "last_ts": str(df["timestamp"].max()),
                "n_rows": len(df),
                "note": "extended-hours bars present; regular-session subset must be filtered by "
                       "timestamp (09:30-16:00 ET), not assumed equal to all rows",
            }
        else:
            entry["minute_coverage"] = {"status": "NO_LOCAL_DATA_LOCATED"}
        manifest.append(entry)

    active = [e for e in manifest if e["status"] == "active"]
    paused = [e for e in manifest if e["status"] == "paused"]
    active_daily_covered = [e for e in active if e["daily_coverage"].get("n_rows")]
    active_minute_covered = [e for e in active if e["minute_coverage"].get("n_rows")]
    active_no_daily = [e["symbol"] for e in active if not e["daily_coverage"].get("n_rows")]
    active_no_minute = [e["symbol"] for e in active if not e["minute_coverage"].get("n_rows")]

    summary = {
        "snapshot_taken_at_utc": now,
        "note": "current watchlist membership is NOT treated as historical point-in-time membership -- "
               "this is a snapshot of TODAY's configured/active/paused status only, used to scope which "
               "symbols' historical price series are relevant to check, not a claim about what was "
               "configured/tradable at any past date.",
        "n_configured": len(manifest), "n_active": len(active), "n_paused": len(paused),
        "n_active_with_daily_coverage": len(active_daily_covered),
        "n_active_with_minute_coverage": len(active_minute_covered),
        "active_missing_daily": active_no_daily,
        "active_missing_minute": active_no_minute,
        "daily_source_precedence": "task95g_broad_cross_sectional/_daily checked first, "
                                   "task107a_form4_feasibility/_prices fallback",
        "daily_source_overlap": overlap_d1_d2,
        "prior_tasks_using_this_data": {
            "task95g_broad_cross_sectional/_daily": ["Task 95E", "Task 95G", "Task 121A/B (daily reconciliation only)",
                                                     "Task 122", "Task 123 Track A"],
            "task107a_form4_feasibility/_prices": ["Task 107A/B", "Task 116", "Task 120A-C", "Task 122", "Task 123 Track A"],
            "task93_alpha_foundation/_canonical_data": ["Task 93", "Task 121A/B (Experimental replay)", "Task 123 Track B"],
        },
        "outcomes_already_inspected": {
            "daily_close_to_close_returns": "YES -- Task 93/95E/95G (momentum/cross-sectional), "
                                            "Task 121A/B (Experimental trade returns)",
            "daily_close_to_next_open_overnight_returns": "YES -- Task 123 Track A (this exact "
                                                          "return definition, this exact universe)",
            "intraday_1min_returns": "YES -- Task 121A/B (Experimental), Task 123 Track B "
                                     "(this exact pre-close mechanism, 12 symbols, 2025-01-24..2025-08-14)",
            "unexamined_period": "any date range NOT already covered by an existing local file is, by "
                                 "definition, unexamined for THIS specific hypothesis -- see Part 3 probe "
                                 "evidence for what such an extension could look like",
        },
    }

    (OUT / "coverage_manifest.json").write_text(json.dumps({"summary": summary, "tickers": manifest}, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
