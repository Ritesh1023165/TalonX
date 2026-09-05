"""Replay one already-gated frozen Task 56 window (parallel-safe)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

os.environ["TALONX_QUANT_VOLATILITY_GATE_MODE"] = "MULTITIMEFRAME_EXPERIMENTAL"
os.environ["TALONX_QUANT_CONFLUENCE_CONTRACT"] = "INDEPENDENT_CONFIRMATION_EXPERIMENTAL"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from talonx_backtest.data import load_ohlcv_directory
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_backtest.reproducibility import config_hash, get_strategy_version

OUT = ROOT / "results" / "task56_independent_family_holdout"
ORIGINAL = ROOT / "data" / "historical_1m" / "task7b_alpaca_long_history"
DOWNLOADED = ROOT / "data" / "historical_1m" / "task56_holdout"
ORIGINAL_10 = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX"]
ADDITIONAL_25 = ["ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON", "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP", "QCOM", "REGN", "SBUX", "TXN", "VRTX"]
WINDOWS = {
    "H1_early": ("2025-12-11", "2025-12-24", "2025-12-26", "2026-01-26"),
    "H2_middle": ("2026-02-06", "2026-02-20", "2026-02-23", "2026-03-20"),
    "H3_late": ("2026-05-27", "2026-06-09", "2026-06-10", "2026-07-09"),
}
EXPECTED = {"strategy": "2ae6216bca70", "quant": "fdf4922d0728", "backtest": "0c7dd13d75c4"}


def date_slice(df, start, end):
    dates = df.timestamp.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    return df[(dates >= start) & (dates <= end)].copy().reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("window", choices=WINDOWS)
    args = parser.parse_args()
    gate = json.loads((OUT / "pre_replay_gates.json").read_text(encoding="utf-8"))
    config = BacktestConfig()
    actual = {"strategy": get_strategy_version(), "quant": config_hash(config.quant_config), "backtest": config_hash(config)}
    if not gate.get("all_mandatory_gates_passed") or actual != EXPECTED or not gate["windows"][args.window]["gate_passed"]:
        raise SystemExit("Frozen pre-replay gate/fingerprint check failed; refusing replay")
    warm_start, warm_end, eval_start, eval_end = WINDOWS[args.window]
    original = load_ohlcv_directory(ORIGINAL, symbols=ORIGINAL_10)
    extra = load_ohlcv_directory(DOWNLOADED / args.window, symbols=ADDITIONAL_25)
    whole = pd.concat([date_slice(original, warm_start, eval_end), date_slice(extra, warm_start, eval_end)], ignore_index=True)
    warmup = date_slice(whole, warm_start, warm_end)
    evaluation = date_slice(whole, eval_start, eval_end)
    engine = BacktestEngine(config=config, research_telemetry=True)
    last = [0.0]
    def progress(done, total):
        now = time.time()
        if done == total or now - last[0] >= 60:
            print(f"{args.window}: {done}/{total} ({100*done/total:.1f}%)", flush=True)
            last[0] = now
    started = time.time()
    result = engine.run(evaluation, warmup_df=warmup, progress_callback=progress, progress_interval_seconds=10)
    trades = []
    for trade in result.trades:
        row = trade.to_dict(); row["window"] = args.window; trades.append(row)
    pd.DataFrame(trades).to_csv(OUT / f"raw_trades_{args.window}.csv", index=False)
    pd.DataFrame(engine.signal_log).to_parquet(OUT / f"signal_log_{args.window}.parquet", index=False)
    pd.DataFrame(engine.candidate_telemetry).to_parquet(OUT / f"candidate_telemetry_{args.window}.parquet", index=False)
    pd.DataFrame([asdict(x) for x in result.rejections]).to_csv(OUT / f"rejections_{args.window}.csv", index=False)
    manifest = {
        "window": args.window, "elapsed_minutes": (time.time()-started)/60,
        "warmup_bars": result.warmup_bars_processed, "evaluation_bars": result.bars_processed,
        "signals_generated": result.signals_generated, "signals_published": result.signals_published,
        "trades": len(result.trades), "fingerprints": actual,
    }
    (OUT / f"replay_manifest_{args.window}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
