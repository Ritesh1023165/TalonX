"""
TASK 122 Part 4 -- bounded feasibility check for the top-ranked candidate
(overnight/close-to-open return, conditioned on same-day abnormal volume
as a free "retail attention" proxy -- Berkman/Koch/Tuttle/Zhang 2012).

Uses ONLY already-downloaded, already-published free data
(results/task95g_broad_cross_sectional/_daily, Alpaca SIP daily bars,
adjustment=all, 2019-06-03..2026-08-14, no paid spend) -- no new
retrieval. Reports event/setup counts by month and ticker WITHOUT
choosing dates based on subsequent (overnight-return) outcomes -- this
script never reads or reports the outcome return, only the trigger
condition and coverage/data-quality facts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DAILY_DIR = Path("C:/workspace/TalonX/results/task95g_broad_cross_sectional/_daily")
OUT = Path(__file__).resolve().parents[2] / "results" / "task122_overnight_feasibility"
OUT.mkdir(parents=True, exist_ok=True)

CONFIGURED_48 = [
    "AAPL", "ABCL", "ABT", "ACHR", "ADC", "ADP", "AFL", "AGNC", "AMAT", "AMD", "ASML", "AVGO",
    "BABA", "BAC", "BLK", "BLSH", "C", "CSCO", "CVX", "DELL", "GOOGL", "IBM", "INTC", "JNJ",
    "JPM", "KO", "MA", "MCD", "MSFT", "MSTR", "NUE", "NVDA", "ORCL", "PATH", "PG", "PLTR",
    "PYPL", "RIG", "SHOP", "SKHY", "SMCI", "SPCX", "STX", "TSLA", "UNH", "V", "VRT", "WMT",
]

VOLUME_LOOKBACK_DAYS = 20   # trailing average window, causal (uses only prior days)
ABNORMAL_VOLUME_MULTIPLE = 2.0   # trigger: today's volume >= 2x its own trailing 20-day average


def main() -> int:
    available = {f.stem.upper() for f in DAILY_DIR.glob("*.csv")}
    covered = sorted(set(CONFIGURED_48) & available)
    missing = sorted(set(CONFIGURED_48) - available)
    print(f"configured=48  covered={len(covered)}  missing={len(missing)}: {missing}")

    per_symbol_quality = {}
    monthly_counts: dict[str, dict[str, int]] = {}   # symbol -> {YYYY-MM: n_triggers}
    total_rows = 0
    total_triggers = 0

    for sym in covered:
        df = pd.read_csv(DAILY_DIR / f"{sym}.csv", parse_dates=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        n_rows = len(df)
        total_rows += n_rows

        # data-quality: duplicate/out-of-order dates, non-positive prices/volume
        dupes = int(df["date"].duplicated().sum())
        out_of_order = int((df["date"].diff().dt.days < 0).sum())
        non_positive = int(((df[["open", "high", "low", "close"]] <= 0).any(axis=1)).sum())
        neg_volume = int((df["volume"] < 0).sum())
        per_symbol_quality[sym] = {
            "n_rows": n_rows, "first_date": str(df["date"].min().date()),
            "last_date": str(df["date"].max().date()),
            "duplicates": dupes, "out_of_order": out_of_order,
            "non_positive_prices": non_positive, "negative_volume": neg_volume,
        }

        # causal trailing-average volume (shift(1) so today's own volume never
        # leaks into its own baseline -- point-in-time correct)
        trailing_avg_vol = df["volume"].shift(1).rolling(VOLUME_LOOKBACK_DAYS, min_periods=VOLUME_LOOKBACK_DAYS).mean()
        is_trigger = df["volume"] >= (ABNORMAL_VOLUME_MULTIPLE * trailing_avg_vol)
        is_trigger = is_trigger.fillna(False)

        months = df["date"].dt.to_period("M").astype(str)
        by_month = df.loc[is_trigger].assign(month=months[is_trigger]).groupby("month").size()
        monthly_counts[sym] = {str(k): int(v) for k, v in by_month.items()}
        total_triggers += int(is_trigger.sum())

    # aggregate: triggers per calendar month across ALL covered symbols
    all_months: dict[str, int] = {}
    for sym, mc in monthly_counts.items():
        for m, c in mc.items():
            all_months[m] = all_months.get(m, 0) + c
    zero_trigger_months = sorted(m for m in all_months if all_months[m] == 0)

    n_months_spanned = len(all_months)
    avg_triggers_per_symbol_per_month = (total_triggers / len(covered) / n_months_spanned) if (covered and n_months_spanned) else None

    result = {
        "candidate": "overnight_close_to_open_return_conditioned_on_abnormal_volume",
        "data_source": "results/task95g_broad_cross_sectional/_daily (Alpaca SIP daily bars, "
                       "adjustment=all, free/entitled, no paid spend, 2019-06-03..2026-08-14)",
        "configured_universe_mapping": {
            "configured_n": len(CONFIGURED_48), "covered_n": len(covered),
            "covered": covered, "missing": missing,
        },
        "trigger_definition": {
            "rule": f"volume[t] >= {ABNORMAL_VOLUME_MULTIPLE}x trailing {VOLUME_LOOKBACK_DAYS}-day "
                    "average volume[t-1..t-20] (causal, shift(1), never includes day t's own volume)",
            "note": "This is the TRIGGER/setup count only -- NO subsequent (overnight) return was "
                    "read or used to select which dates are reported. Dates are not outcome-selected.",
        },
        "data_quality_by_symbol": per_symbol_quality,
        "total_rows": total_rows,
        "total_trigger_days_all_symbols": total_triggers,
        "n_calendar_months_spanned": n_months_spanned,
        "avg_triggers_per_symbol_per_month": avg_triggers_per_symbol_per_month,
        "zero_trigger_calendar_months_count": len(zero_trigger_months),
        "monthly_trigger_counts_by_symbol": monthly_counts,
    }
    out_path = OUT / "feasibility_summary.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"total_rows={total_rows}  total_triggers={total_triggers}  "
          f"avg/symbol/month={avg_triggers_per_symbol_per_month:.2f}" if avg_triggers_per_symbol_per_month else "no data")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
