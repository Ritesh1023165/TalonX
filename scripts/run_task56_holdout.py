"""Frozen Task 56 pre-replay gates and candidate-only holdout replay."""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

os.environ["TALONX_QUANT_VOLATILITY_GATE_MODE"] = "MULTITIMEFRAME_EXPERIMENTAL"
os.environ["TALONX_QUANT_CONFLUENCE_CONTRACT"] = "INDEPENDENT_CONFIRMATION_EXPERIMENTAL"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from talonx_backtest.data import abort_on_critical_corruption, check_dataset_quality, load_ohlcv_directory
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_backtest.reproducibility import config_hash, get_strategy_version

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "task56_independent_family_holdout"
ORIGINAL = ROOT / "data" / "historical_1m" / "task7b_alpaca_long_history"
DOWNLOADED = ROOT / "data" / "historical_1m" / "task56_holdout"
ORIGINAL_10 = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX"]
ADDITIONAL_25 = ["ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON", "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP", "QCOM", "REGN", "SBUX", "TXN", "VRTX"]
UNIVERSE = ORIGINAL_10 + ADDITIONAL_25
WINDOWS = {
    "H1_early": ("2025-12-11", "2025-12-24", "2025-12-26", "2026-01-26"),
    "H2_middle": ("2026-02-06", "2026-02-20", "2026-02-23", "2026-03-20"),
    "H3_late": ("2026-05-27", "2026-06-09", "2026-06-10", "2026-07-09"),
}
EXPECTED = {"strategy": "2ae6216bca70", "quant": "fdf4922d0728", "backtest": "0c7dd13d75c4"}


def et_dates(df: pd.DataFrame) -> pd.Series:
    return df["timestamp"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")


def date_slice(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    dates = et_dates(df)
    return df[(dates >= start) & (dates <= end)].copy().reset_index(drop=True)


def json_default(value):
    if isinstance(value, pd.Timestamp):
        return str(value)
    raise TypeError(type(value).__name__)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    config = BacktestConfig()
    fingerprints = {
        "strategy": get_strategy_version(),
        "quant": config_hash(config.quant_config),
        "backtest": config_hash(config),
    }
    gate = {
        "task": "Task 56 - Independent Family Holdout Validation",
        "frozen_protocol_commit": "8de8d4990c932830f09271bf45fa2326afc4e676",
        "fingerprints": fingerprints,
        "expected_fingerprints": EXPECTED,
        "fingerprints_match": fingerprints == EXPECTED,
        "runtime_estimate": {
            "basis": "Task 54 actual throughput over the same 35-symbol candidate-only workflow",
            "estimated_hours": 4.8,
            "practical_range_hours": "4.5-6",
        },
        "windows": {},
    }
    frames: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    original = load_ohlcv_directory(ORIGINAL, symbols=ORIGINAL_10)
    aapl_calendar = sorted(set(et_dates(original[original.symbol == "AAPL"])))

    all_pass = gate["fingerprints_match"]
    for window, (warm_start, warm_end, eval_start, eval_end) in WINDOWS.items():
        extra_dir = DOWNLOADED / window
        extra = load_ohlcv_directory(extra_dir, symbols=ADDITIONAL_25)
        whole = pd.concat([
            date_slice(original, warm_start, eval_end),
            date_slice(extra, warm_start, eval_end),
        ], ignore_index=True).sort_values(["symbol", "timestamp"], kind="mergesort").reset_index(drop=True)
        warmup = date_slice(whole, warm_start, warm_end)
        evaluation = date_slice(whole, eval_start, eval_end)
        expected_warm_dates = [d for d in aapl_calendar if warm_start <= d <= warm_end]
        expected_eval_dates = [d for d in aapl_calendar if eval_start <= d <= eval_end]
        quality = check_dataset_quality(whole)
        abort_on_critical_corruption(quality)
        per_symbol = {}
        readiness_engine = BacktestEngine(config=config)
        ordered = warmup.sort_values(["timestamp", "symbol"], kind="mergesort")
        for _, row in ordered.iterrows():
            readiness_engine._warmup_symbol_bar(row["symbol"], row["timestamp"], row)
        for symbol in UNIVERSE:
            w = warmup[warmup.symbol == symbol]
            e = evaluation[evaluation.symbol == symbol]
            w_dates = sorted(set(et_dates(w)))
            e_dates = sorted(set(et_dates(e)))
            q = quality[symbol]
            htf = len(readiness_engine.buffer_htf.get_bars(symbol))
            regime = len(readiness_engine.buffer_60m.get_bars(symbol))
            one = len(readiness_engine.buffer.get_bars(symbol))
            per_symbol[symbol] = {
                "warmup_rows": len(w), "evaluation_rows": len(e),
                "warmup_dates_complete": w_dates == expected_warm_dates,
                "evaluation_dates_complete": e_dates == expected_eval_dates,
                "duplicate_timestamps": q.duplicate_timestamps,
                "out_of_order_timestamps": q.out_of_order_timestamps,
                "critical_corruption": q.has_critical_corruption,
                "unexpected_intra_session_gap_bars": q.unexpected_intra_session_gap_bars,
                "htf_15m_bars": htf, "regime_60m_bars": regime, "indicator_1m_bars": one,
                "ready": htf >= config.quant_config.htf_sma_period and regime > config.quant_config.atr_period and one >= config.quant_config.min_bars_required,
            }
        window_pass = (
            set(whole.symbol.unique()) == set(UNIVERSE)
            and len(expected_warm_dates) == 10 and len(expected_eval_dates) == 20
            and all(x["warmup_dates_complete"] and x["evaluation_dates_complete"] for x in per_symbol.values())
            and all(not x["critical_corruption"] and x["duplicate_timestamps"] == 0 and x["out_of_order_timestamps"] == 0 for x in per_symbol.values())
            and all(x["ready"] for x in per_symbol.values())
        )
        gate["windows"][window] = {
            "symbols_present": len(set(whole.symbol)), "expected_symbols": 35,
            "warmup_trading_days": len(expected_warm_dates), "evaluation_trading_days": len(expected_eval_dates),
            "warmup_rows": len(warmup), "evaluation_rows": len(evaluation),
            "ready_symbols": sum(x["ready"] for x in per_symbol.values()),
            "critical_corruption_symbols": [s for s, x in per_symbol.items() if x["critical_corruption"]],
            "duplicate_or_out_of_order_symbols": [s for s, x in per_symbol.items() if x["duplicate_timestamps"] or x["out_of_order_timestamps"]],
            "coverage_failures": [s for s, x in per_symbol.items() if not x["warmup_dates_complete"] or not x["evaluation_dates_complete"]],
            "gate_passed": window_pass, "per_symbol": per_symbol,
        }
        all_pass = all_pass and window_pass
        frames[window] = (warmup, evaluation)

    gate["all_mandatory_gates_passed"] = all_pass
    (OUT / "pre_replay_gates.json").write_text(json.dumps(gate, indent=2, default=json_default), encoding="utf-8")
    print(json.dumps({"fingerprints": fingerprints, "windows": {k: {x: v for x, v in d.items() if x != "per_symbol"} for k, d in gate["windows"].items()}, "all_mandatory_gates_passed": all_pass}, indent=2), flush=True)
    if not all_pass:
        return 2

    started = time.time()
    all_trades = []
    replay_manifest = {"windows": {}, "started_utc": pd.Timestamp.now(tz="UTC").isoformat()}
    for window, (warmup, evaluation) in frames.items():
        engine = BacktestEngine(config=config, research_telemetry=True)
        last_print = [0.0]
        def progress(done, total, name=window):
            now = time.time()
            if done == total or now - last_print[0] >= 60:
                print(f"{name}: {done}/{total} evaluation bars ({100 * done / total:.1f}%)", flush=True)
                last_print[0] = now
        t0 = time.time()
        result = engine.run(evaluation, warmup_df=warmup, progress_callback=progress, progress_interval_seconds=10)
        trades = []
        for trade in result.trades:
            row = trade.to_dict()
            row["window"] = window
            trades.append(row)
            all_trades.append(row)
        pd.DataFrame(trades).to_csv(OUT / f"raw_trades_{window}.csv", index=False)
        pd.DataFrame(engine.signal_log).to_parquet(OUT / f"signal_log_{window}.parquet", index=False)
        pd.DataFrame(engine.candidate_telemetry).to_parquet(OUT / f"candidate_telemetry_{window}.parquet", index=False)
        pd.DataFrame([asdict(x) for x in result.rejections]).to_csv(OUT / f"rejections_{window}.csv", index=False)
        replay_manifest["windows"][window] = {
            "elapsed_minutes": (time.time() - t0) / 60, "warmup_bars": result.warmup_bars_processed,
            "evaluation_bars": result.bars_processed, "signals_generated": result.signals_generated,
            "signals_published": result.signals_published, "trades": len(result.trades),
        }
        (OUT / "replay_manifest.json").write_text(json.dumps(replay_manifest, indent=2), encoding="utf-8")
    pd.DataFrame(all_trades).to_csv(OUT / "raw_trades_all.csv", index=False)
    replay_manifest["elapsed_minutes"] = (time.time() - started) / 60
    replay_manifest["completed_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    replay_manifest["total_trades"] = len(all_trades)
    (OUT / "replay_manifest.json").write_text(json.dumps(replay_manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
