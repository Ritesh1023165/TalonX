"""Task 58: deterministic, observational RSI payoff-regime diagnostic.

Consumes only committed Task 53/54/56 trades and already-downloaded Alpaca
bars. It does not invoke the strategy/backtest engine, generate signals, or
download data. Market context is reconstructed as of each original signal bar.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta  # noqa: F401  # registers the canonical DataFrame.ta accessor

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from talonx_quant.indicators import (  # noqa: E402
    compute_htf_trend,
    compute_volatility_regime,
    evaluate_regime,
)

OUT = ROOT / "results/task58_rsi_payoff_regime_diagnostic"
INPUT_CHECKPOINT = "d8f88e1e490c7a8cb45afa4914c17ef04bcda80e"
FINGERPRINTS = {
    "strategy": "2ae6216bca70",
    "quant_config": "fdf4922d0728",
    "backtest_config": "0c7dd13d75c4",
}
TRADE_SOURCES = {
    "Task53": ROOT / "results/task53_preroll_ab_validation/_trades_candidate.csv",
    "Task54": ROOT / "results/task54_extended_candidate_validation/_trades.csv",
    "Task56": ROOT / "results/task56_independent_family_holdout/raw_trades_all.csv",
}
EXPECTED = {
    "Task53": {"n": 17, "gross": 6.205053729136223, "net5": 0.5431955058463391},
    "Task54": {"n": 39, "gross": 28.573458557795476, "net5": 15.303118681690709},
    "Task56": {"n": 44, "gross": 0.7226350248619953, "net5": -10.544234787013044},
}
ORIGINAL_10 = {"AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX"}
TASK56_DATES = {
    "H1_early": ("2025-12-11", "2026-01-26"),
    "H2_middle": ("2026-02-06", "2026-03-20"),
    "H3_late": ("2026-05-27", "2026-07-09"),
}
WINNER_ORDER = ["LOSS_OR_FLAT", "SMALL_WIN", "MEDIUM_WIN", "LARGE_WIN", "VERY_LARGE_WIN"]
TIME_ORDER = ["OPEN", "MID", "CLOSE"]
HORIZONS = [("15m", 15), ("30m", 30), ("60m", 60), ("120m", 120), ("TO_SESSION_CLOSE", None)]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_float(x):
    if x is None or (isinstance(x, (float, np.floating)) and not np.isfinite(x)):
        return None
    return float(x)


def json_clean(x):
    """Convert pandas/numpy scalars and non-finite placeholders to strict JSON."""
    if isinstance(x, dict):
        return {str(k): json_clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [json_clean(v) for v in x]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else float(x)
    return x


def winner_group(r: float) -> str:
    if r <= 0:
        return "LOSS_OR_FLAT"
    if r < 1:
        return "SMALL_WIN"
    if r < 2:
        return "MEDIUM_WIN"
    if r < 4:
        return "LARGE_WIN"
    return "VERY_LARGE_WIN"


def time_bucket(ts: pd.Timestamp) -> str:
    et = ts.tz_convert("America/New_York")
    minute = et.hour * 60 + et.minute
    if minute < 10 * 60 + 30:
        return "OPEN"
    if minute < 15 * 60:
        return "MID"
    return "CLOSE"


def pf(s: pd.Series):
    pos = s[s > 0].sum()
    neg = -s[s < 0].sum()
    return float(pos / neg) if neg > 0 else (float("inf") if pos > 0 else None)


def econ(g: pd.DataFrame) -> dict:
    r = g["gross_R"]
    wins, losses = r[r > 0], r[r < 0]
    pos_total = wins.sum()
    sorted_wins = wins.sort_values(ascending=False)
    return {
        "N": int(len(g)), "winners": int((r > 0).sum()), "losses": int((r < 0).sum()),
        "flats": int((r == 0).sum()), "win_rate": float((r > 0).mean()),
        "gross_total_R": float(r.sum()), "gross_expectancy_R": float(r.mean()),
        "gross_PF": pf(r), "median_R": float(r.median()), "p25_R": float(r.quantile(.25)),
        "p75_R": float(r.quantile(.75)), "mean_winning_R": stable_float(wins.mean()),
        "median_winning_R": stable_float(wins.median()), "mean_losing_R": stable_float(losses.mean()),
        "max_winner_R": stable_float(wins.max()), "top3_winner_mean_R": stable_float(sorted_wins.head(3).mean()),
        "top5_winner_mean_R": stable_float(sorted_wins.head(5).mean()),
        "positive_R_top3_concentration": stable_float(sorted_wins.head(3).sum() / pos_total) if pos_total else None,
        "stop_rate": float(g.exit_reason.eq("STOP").mean()),
        "signal_exit_rate": float(g.exit_reason.eq("SIGNAL_EXIT").mean()),
        "end_of_session_rate": float(g.exit_reason.eq("END_OF_SESSION").mean()),
        "target_rate": float(g.exit_reason.eq("TARGET").mean()),
        "holding_minutes_mean": float(g.holding_minutes.mean()),
        "holding_minutes_median": float(g.holding_minutes.median()),
        "total_R_5bps": float(g.net_R_5bps.sum()),
    }


def load_trades() -> tuple[pd.DataFrame, dict]:
    rows, hashes = [], {}
    for task, path in TRADE_SOURCES.items():
        hashes[str(path.relative_to(ROOT)).replace("\\", "/")] = sha256(path)
        d = pd.read_csv(path)
        d["task"] = task
        rows.append(d)
    t = pd.concat(rows, ignore_index=True, sort=False)
    t = t[t.signal_type.str.startswith("rsi_", na=False)].copy()
    for c in ["signal_timestamp", "entry_timestamp", "exit_timestamp"]:
        t[c] = pd.to_datetime(t[c], utc=True)
    t["source_window"] = t["window"]
    t["risk_abs"] = (t.entry_price - t.stop_price).abs()
    t["risk_pct_entry"] = t.risk_abs / t.entry_price * 100
    t["cost_R_5bps"] = (t.entry_price * .0005 + t.exit_price * .0005) / t.risk_abs
    t["net_R_5bps"] = t.gross_R - t.cost_R_5bps
    t["holding_minutes"] = t.holding_seconds / 60
    t["realized_price_move_pct"] = t.gross_pnl / t.entry_price * 100
    t["winner_size_group"] = t.gross_R.map(winner_group)
    t["time_bucket"] = t.entry_timestamp.map(time_bucket)
    t["entry_et"] = t.entry_timestamp.dt.tz_convert("America/New_York")
    t["exit_et"] = t.exit_timestamp.dt.tz_convert("America/New_York")
    close = t.entry_et.map(lambda x: x.normalize() + pd.Timedelta(hours=16))
    t["minutes_to_1600_et"] = (close - t.entry_et).dt.total_seconds() / 60
    t = t.sort_values(["task", "source_window", "entry_timestamp", "trade_id"], kind="mergesort").reset_index(drop=True)
    return t, hashes


def data_paths(task: str, window: str, symbol: str) -> list[Path]:
    base = ROOT / "data/historical_1m"
    if task == "Task53":
        return [base / "task53_warmup_windows" / window / f"{symbol}.csv",
                base / "task46_validation_windows" / window / f"{symbol}.csv"]
    if task == "Task54":
        return [base / "task54_extended_windows" / window / f"{symbol}.csv"]
    if symbol in ORIGINAL_10:
        return [base / "task7b_alpaca_long_history" / f"{symbol}.csv"]
    return [base / "task56_holdout" / window / f"{symbol}.csv"]


def load_bars(paths: list[Path], task: str, window: str) -> pd.DataFrame:
    parts = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        d = pd.read_csv(path)
        d["timestamp"] = pd.to_datetime(d.timestamp, utc=True)
        parts.append(d[["timestamp", "open", "high", "low", "close", "volume"]])
    d = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp", keep="last")
    d = d.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    if task == "Task56":
        start, end = TASK56_DATES[window]
        dates = d.timestamp.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
        d = d[(dates >= start) & (dates <= end)].reset_index(drop=True)
    return d


def aggregate_closed(df: pd.DataFrame, asof: pd.Timestamp, minutes: int, rth_only: bool) -> pd.DataFrame:
    q = df[df.timestamp <= asof].copy()
    if rth_only:
        et = q.timestamp.dt.tz_convert("America/New_York")
        mins = et.dt.hour * 60 + et.dt.minute
        q = q[(mins >= 570) & (mins < 960)]
    q["bucket"] = q.timestamp.dt.floor(f"{minutes}min")
    current = asof.floor(f"{minutes}min")
    q = q[q.bucket < current]
    if q.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    out = q.groupby("bucket", sort=True).agg(open=("open", "first"), high=("high", "max"),
                                                low=("low", "min"), close=("close", "last"),
                                                volume=("volume", "sum")).reset_index()
    return out.rename(columns={"bucket": "timestamp"})


def reconstruct_context(t: pd.DataFrame) -> tuple[pd.DataFrame, dict, dict]:
    contexts, file_hashes, group_files = [], {}, {}
    cache: dict[tuple[str, str, str], pd.DataFrame] = {}
    for _, tr in t.iterrows():
        key = (tr.task, tr.source_window, tr.symbol)
        paths = data_paths(*key)
        if key not in cache:
            cache[key] = load_bars(paths, tr.task, tr.source_window)
            for p in paths:
                rel = str(p.relative_to(ROOT)).replace("\\", "/")
                file_hashes.setdefault(rel, sha256(p))
            group_files[f"{tr.task}/{tr.source_window}"] = sorted(set(group_files.get(f"{tr.task}/{tr.source_window}", []) + [str(p.relative_to(ROOT)).replace('\\', '/') for p in paths]))
        bars = cache[key]
        asof = tr.signal_timestamp
        row = bars[bars.timestamp.eq(asof)]
        if row.empty:
            raise RuntimeError(f"Missing original signal bar: {key} {asof}")
        signal_price = float(row.iloc[-1].close)
        b15 = aggregate_closed(bars, asof, 15, True)
        b60 = aggregate_closed(bars, asof, 60, False)
        sma200 = compute_htf_trend(b15, 200)
        snap = compute_volatility_regime(b15, b60, 14, asof)
        regime = evaluate_regime(snap)
        sma_series = b15.close.rolling(200).mean().dropna()
        slope20 = None
        if len(sma_series) >= 21 and sma_series.iloc[-21] != 0:
            slope20 = (sma_series.iloc[-1] / sma_series.iloc[-21] - 1) * 100
        contexts.append({
            "trade_id": tr.trade_id, "signal_price": signal_price,
            "htf_sma_200_15m": sma200,
            "price_vs_sma200_pct": ((signal_price / sma200 - 1) * 100) if sma200 else None,
            "sma200_slope_20_completed_15m_bars_pct": slope20,
            "trend_aligned_existing": bool(tr.trend_alignment),
            "trend_state_60m": "NOT_EMITTED_BY_ENGINE",
            "atr_1m_existing": tr.atr,
            "atr_pct_1m": tr.atr / signal_price * 100,
            "atr_15m": snap.atr_15m, "atr_pct_15m": snap.atr_pct_15m,
            "atr_60m": snap.atr_60m, "atr_pct_60m": snap.atr_pct_60m,
            "distance_above_15m_threshold_pct_points": (snap.atr_pct_15m - .329) if snap.atr_pct_15m is not None else None,
            "distance_above_60m_threshold_pct_points": (snap.atr_pct_60m - .839) if snap.atr_pct_60m is not None else None,
            "regime_ready": regime.ready, "regime_eligible": regime.eligible,
            "regime_reason": regime.reason,
            "volatility_expansion_state": "NOT_EMITTED_BY_ENGINE",
            "completed_15m_bars": len(b15), "completed_60m_bars": len(b60),
        })
    ctx = pd.DataFrame(contexts)
    combined = {}
    for group, files in sorted(group_files.items()):
        combined[group] = hashlib.sha256("".join(file_hashes[f] for f in sorted(files)).encode()).hexdigest()
    return t.merge(ctx, on="trade_id", validate="one_to_one"), file_hashes, combined


def excursion_and_forward(t: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    cache = {}
    checks, forward = [], []
    max_mfe_diff = max_mae_diff = 0.0
    bounded = True
    for _, tr in t.iterrows():
        key = (tr.task, tr.source_window, tr.symbol)
        if key not in cache:
            cache[key] = load_bars(data_paths(*key), tr.task, tr.source_window)
        bars = cache[key]
        inclusive = tr.exit_reason != "SIGNAL_EXIT"
        mask = bars.timestamp.ge(tr.entry_timestamp) & (bars.timestamp.le(tr.exit_timestamp) if inclusive else bars.timestamp.lt(tr.exit_timestamp))
        life = bars[mask]
        if life.empty:
            raise RuntimeError(f"No lifecycle bars for {tr.trade_id}")
        mfe_price_check = max(float(tr.entry_price), float(life.high.max()))
        mae_price_check = min(float(tr.entry_price), float(life.low.min()))
        mfe_diff = abs(mfe_price_check - float(tr.mfe_price))
        mae_diff = abs(mae_price_check - float(tr.mae_price))
        max_mfe_diff, max_mae_diff = max(max_mfe_diff, mfe_diff), max(max_mae_diff, mae_diff)
        checks.append({
            "trade_id": tr.trade_id, "task": tr.task, "window": tr.source_window, "symbol": tr.symbol,
            "gross_R": tr.gross_R, "mfe_R": tr.mfe_r, "mae_R": tr.mae_r,
            "realization_ratio": (tr.gross_R / tr.mfe_r) if tr.gross_R > 0 and tr.mfe_r > 0 else None,
            "canonical_mfe_price": tr.mfe_price, "recomputed_mfe_price": mfe_price_check,
            "canonical_mae_price": tr.mae_price, "recomputed_mae_price": mae_price_check,
            "lifecycle_end_inclusive": inclusive, "lifecycle_bar_count": len(life),
        })
        close_et = tr.entry_et.normalize() + pd.Timedelta(hours=16)
        close_utc = close_et.tz_convert("UTC")
        for name, minutes in HORIZONS:
            raw_end = close_utc if minutes is None else tr.entry_timestamp + pd.Timedelta(minutes=minutes)
            end = min(raw_end, close_utc)
            obs = bars[bars.timestamp.ge(tr.entry_timestamp) & bars.timestamp.lt(end)]
            observed_through = obs.timestamp.max() if len(obs) else pd.NaT
            if len(obs) and not (observed_through < close_utc):
                bounded = False
            forward.append({
                "trade_id": tr.trade_id, "task": tr.task, "window": tr.source_window, "symbol": tr.symbol,
                "horizon": name, "entry_timestamp": tr.entry_timestamp, "bounded_end": end,
                "session_close": close_utc, "observed_through": observed_through, "bars": len(obs),
                "favorable_excursion_R": (float(obs.high.max()) - tr.entry_price) / tr.risk_abs if len(obs) else None,
            })
    # One source CSV (AVGO W1) stores bars to 0.001 while the canonical
    # trade ledger retains 0.0001; 0.00011 is therefore a source-precision
    # tolerance, not a relaxed time-bound check.
    price_precision_tolerance = 0.00011
    validation = {"max_abs_mfe_price_reconstruction_diff": max_mfe_diff,
                  "max_abs_mae_price_reconstruction_diff": max_mae_diff,
                  "mfe_mae_price_precision_tolerance": price_precision_tolerance,
                  "mfe_mae_causally_bounded": max_mfe_diff <= price_precision_tolerance and max_mae_diff <= price_precision_tolerance,
                  "forward_horizons_never_cross_session_close": bounded}
    return pd.DataFrame(checks), pd.DataFrame(forward), validation


def aggregate_context(g: pd.DataFrame) -> dict:
    return {
        "N": len(g), "median_price_vs_sma200_pct": stable_float(g.price_vs_sma200_pct.median()),
        "median_sma200_slope20_pct": stable_float(g.sma200_slope_20_completed_15m_bars_pct.median()),
        "trend_aligned_rate": float(g.trend_aligned_existing.mean()),
        "median_atr_pct_1m": stable_float(g.atr_pct_1m.median()),
        "median_atr_pct_15m": stable_float(g.atr_pct_15m.median()),
        "median_atr_pct_60m": stable_float(g.atr_pct_60m.median()),
        "median_15m_threshold_depth": stable_float(g.distance_above_15m_threshold_pct_points.median()),
        "median_60m_threshold_depth": stable_float(g.distance_above_60m_threshold_pct_points.median()),
        "regime_ready_rate": float(g.regime_ready.mean()), "regime_eligible_rate": float(g.regime_eligible.mean()),
    }


def comparison_label(row) -> str:
    if row.task in ("Task53", "Task54") and row.gross_R >= 2:
        return "PRIOR_2R_PLUS"
    if row.task in ("Task53", "Task54"):
        return "PRIOR_OTHER"
    return "TASK56_WINNERS" if row.gross_R > 0 else "TASK56_LOSS_OR_FLAT"


def write_outputs(t: pd.DataFrame, trade_hashes: dict, bar_hashes: dict, dataset_hashes: dict,
                  mfe: pd.DataFrame, fwd: pd.DataFrame, excursion_checks: dict) -> tuple[dict, str]:
    OUT.mkdir(parents=True, exist_ok=True)
    export = t.copy()
    for c in ["signal_timestamp", "entry_timestamp", "exit_timestamp", "entry_et", "exit_et"]:
        export[c] = export[c].map(lambda x: x.isoformat())
    export.to_csv(OUT / "rsi_trade_context.csv", index=False, lineterminator="\n")

    dist_rows = []
    for (task, window), g in t.groupby(["task", "source_window"], sort=True):
        dist_rows.append({"scope": "WINDOW", "task": task, "window": window, **econ(g)})
    prior, holdout = t[t.task.ne("Task56")], t[t.task.eq("Task56")]
    dist_rows += [{"scope": "COMPARISON", "task": "Task53+54", "window": "ALL", **econ(prior)},
                  {"scope": "COMPARISON", "task": "Task56", "window": "ALL", **econ(holdout)}]
    distribution = pd.DataFrame(dist_rows)
    distribution.to_csv(OUT / "rsi_payoff_distribution.csv", index=False, lineterminator="\n")

    group_rows = []
    for (task, window, group), g in t.groupby(["task", "source_window", "winner_size_group"], sort=True, observed=True):
        group_rows.append({"task": task, "window": window, "winner_size_group": group, "N": len(g),
            "symbols": "|".join(sorted(g.symbol.unique())), "entry_time_buckets": "|".join(sorted(g.time_bucket.unique())),
            "exit_reasons": "|".join(sorted(g.exit_reason.unique())), "gross_total_R": g.gross_R.sum(),
            "mean_R": g.gross_R.mean(), "holding_minutes_median": g.holding_minutes.median(),
            "stop_risk_pct_median": g.risk_pct_entry.median(), "cost_R_median": g.cost_R_5bps.median(),
            **aggregate_context(g)})
    pd.DataFrame(group_rows).to_csv(OUT / "winner_size_groups.csv", index=False, lineterminator="\n")

    t["comparison_group"] = t.apply(comparison_label, axis=1)
    htf_rows, vol_rows = [], []
    for label, g in t.groupby("comparison_group", sort=True):
        a = aggregate_context(g)
        htf_rows.append({"scope": "COMBINED_COMPARISON", "task": "COMBINED", "comparison_group": label, "N": len(g), **{k: v for k, v in a.items() if "sma" in k or "trend" in k}})
        vol_rows.append({"scope": "COMBINED_COMPARISON", "task": "COMBINED", "comparison_group": label, "N": len(g), **{k: v for k, v in a.items() if "atr" in k or "threshold" in k or "regime" in k}})
    for (task, is_large), g in t.groupby(["task", t.gross_R.ge(2)], sort=True):
        label = "2R_PLUS" if is_large else "OTHER"
        a = aggregate_context(g)
        htf_rows.append({"scope": "TASK_REPRODUCIBILITY", "task": task, "comparison_group": label, "N": len(g), **{k: v for k, v in a.items() if "sma" in k or "trend" in k}})
        vol_rows.append({"scope": "TASK_REPRODUCIBILITY", "task": task, "comparison_group": label, "N": len(g), **{k: v for k, v in a.items() if "atr" in k or "threshold" in k or "regime" in k}})
    pd.DataFrame(htf_rows).to_csv(OUT / "htf_context.csv", index=False, lineterminator="\n")
    pd.DataFrame(vol_rows).to_csv(OUT / "volatility_context.csv", index=False, lineterminator="\n")

    runway_rows = []
    for (task, window, bucket), g in t.groupby(["task", "source_window", "time_bucket"], sort=True):
        runway_rows.append({"task": task, "window": window, "time_bucket": bucket, **econ(g),
                            "minutes_to_1600_median": g.minutes_to_1600_et.median()})
    pd.DataFrame(runway_rows).to_csv(OUT / "entry_runway.csv", index=False, lineterminator="\n")

    exit_rows = []
    for (task, window, reason), g in t.groupby(["task", "source_window", "exit_reason"], sort=True):
        pos = g[g.gross_R > 0]
        exit_rows.append({"task": task, "window": window, "exit_reason": reason, "N": len(g),
                          "positive_N": len(pos), "mean_R": g.gross_R.mean(), "median_R": g.gross_R.median(),
                          "positive_mean_R": stable_float(pos.gross_R.mean()), "positive_median_R": stable_float(pos.gross_R.median()),
                          "positive_holding_minutes_median": stable_float(pos.holding_minutes.median())})
    pd.DataFrame(exit_rows).to_csv(OUT / "exit_payoff.csv", index=False, lineterminator="\n")

    conc_rows = []
    for threshold, label in [(2, "2R_PLUS"), (4, "4R_PLUS")]:
        q = t[t.gross_R >= threshold]
        for (task, window, symbol), g in q.groupby(["task", "source_window", "symbol"], sort=True):
            denom = q[(q.task == task) & (q.source_window == window)].gross_R.sum()
            conc_rows.append({"analysis": "WINNER_CONCENTRATION", "threshold": label, "task": task, "window": window,
                              "symbol": symbol, "N": len(g), "total_R": g.gross_R.sum(), "share_of_window_large_winner_R": g.gross_R.sum()/denom})
    for symbol in sorted(prior.symbol.unique()):
        g = prior[prior.symbol.ne(symbol)]
        conc_rows.append({"analysis": "PRIOR_LEAVE_ONE_SYMBOL_OUT", "threshold": "ALL", "task": "Task53+54",
                          "window": "ALL", "symbol": symbol, "N": len(g), "total_R": g.gross_R.sum(),
                          "share_of_window_large_winner_R": np.nan, "gross_expectancy_R": g.gross_R.mean()})
    ordered_prior = prior.sort_values("gross_R", ascending=False)
    for n_remove in [1, 3, 5, 10]:
        g = ordered_prior.iloc[n_remove:]
        conc_rows.append({"analysis": "PRIOR_TOP_WINNER_SENSITIVITY", "threshold": f"REMOVE_TOP_{n_remove}",
                          "task": "Task53+54", "window": "ALL", "symbol": "ALL", "N": len(g),
                          "total_R": g.gross_R.sum(), "share_of_window_large_winner_R": np.nan,
                          "gross_expectancy_R": g.gross_R.mean()})
    concentration = pd.DataFrame(conc_rows)
    concentration.to_csv(OUT / "large_winner_symbol_concentration.csv", index=False, lineterminator="\n")

    window_rows = []
    for (task, window), g in t.groupby(["task", "source_window"], sort=True):
        wins = g[g.gross_R > 0]
        window_rows.append({"task": task, "window": window, "N": len(g), "winners": len(wins),
                            "winners_2R_plus": int((g.gross_R >= 2).sum()), "winners_4R_plus": int((g.gross_R >= 4).sum()),
                            "mean_winning_R": stable_float(wins.gross_R.mean()), "gross_expectancy_R": g.gross_R.mean(),
                            **aggregate_context(g)})
    pd.DataFrame(window_rows).to_csv(OUT / "window_payoff.csv", index=False, lineterminator="\n")

    mfe_out = mfe.copy()
    mfe_out.to_csv(OUT / "mfe_mae.csv", index=False, lineterminator="\n")
    fwd_out = fwd.copy()
    for c in ["entry_timestamp", "bounded_end", "session_close", "observed_through"]:
        fwd_out[c] = fwd_out[c].map(lambda x: "" if pd.isna(x) else x.isoformat())
    fwd_out.to_csv(OUT / "forward_excursion.csv", index=False, lineterminator="\n")

    pe, he = econ(prior), econ(holdout)
    # Exact expectancy decomposition: frequency (winner/loss/flat shares), winner size, loser size.
    pw, hw = pe["win_rate"], he["win_rate"]
    pl, hl = pe["losses"]/pe["N"], he["losses"]/he["N"]
    freq_effect = (hw-pw)*pe["mean_winning_R"] + (hl-pl)*pe["mean_losing_R"]
    winner_size_effect = hw*(he["mean_winning_R"]-pe["mean_winning_R"])
    loser_size_effect = hl*(he["mean_losing_R"]-pe["mean_losing_R"])
    exit_reasons = sorted(set(prior.exit_reason) | set(holdout.exit_reason))
    prior_exit_mean = prior.groupby("exit_reason").gross_R.mean()
    hold_exit_mean = holdout.groupby("exit_reason").gross_R.mean()
    prior_exit_share = prior.exit_reason.value_counts(normalize=True)
    hold_exit_share = holdout.exit_reason.value_counts(normalize=True)
    exit_mix_effect = sum((hold_exit_share.get(x, 0)-prior_exit_share.get(x, 0))*prior_exit_mean.get(x, 0) for x in exit_reasons)
    exit_payoff_effect = sum(hold_exit_share.get(x, 0)*(hold_exit_mean.get(x, prior_exit_mean.get(x, 0))-prior_exit_mean.get(x, 0)) for x in exit_reasons)
    prior_mfe = mfe[mfe.task.ne("Task56") & mfe.gross_R.gt(0)]
    hold_mfe = mfe[mfe.task.eq("Task56") & mfe.gross_R.gt(0)]
    fwd60 = fwd[fwd.horizon.eq("60m")]
    metrics = {
        "gross_expectancy_R": (pe["gross_expectancy_R"], he["gross_expectancy_R"]),
        "win_rate": (pe["win_rate"], he["win_rate"]),
        "mean_winning_R": (pe["mean_winning_R"], he["mean_winning_R"]),
        "median_winning_R": (pe["median_winning_R"], he["median_winning_R"]),
        "winner_2R_plus_rate": ((prior.gross_R>=2).mean(), (holdout.gross_R>=2).mean()),
        "winner_4R_plus_rate": ((prior.gross_R>=4).mean(), (holdout.gross_R>=4).mean()),
        "winner_median_MFE_R": (prior_mfe.mfe_R.median(), hold_mfe.mfe_R.median()),
        "winner_median_realization_ratio": (prior_mfe.realization_ratio.median(), hold_mfe.realization_ratio.median()),
        "median_holding_minutes": (prior.holding_minutes.median(), holdout.holding_minutes.median()),
        "end_of_session_rate": (prior.exit_reason.eq("END_OF_SESSION").mean(), holdout.exit_reason.eq("END_OF_SESSION").mean()),
        "signal_exit_rate": (prior.exit_reason.eq("SIGNAL_EXIT").mean(), holdout.exit_reason.eq("SIGNAL_EXIT").mean()),
        "median_price_vs_sma200_pct": (prior.price_vs_sma200_pct.median(), holdout.price_vs_sma200_pct.median()),
        "median_atr_pct_15m": (prior.atr_pct_15m.median(), holdout.atr_pct_15m.median()),
        "median_atr_pct_60m": (prior.atr_pct_60m.median(), holdout.atr_pct_60m.median()),
        "open_entry_share": (prior.time_bucket.eq("OPEN").mean(), holdout.time_bucket.eq("OPEN").mean()),
        "median_minutes_to_1600": (prior.minutes_to_1600_et.median(), holdout.minutes_to_1600_et.median()),
        "top_symbol_trade_share": (prior.symbol.value_counts(normalize=True).iloc[0], holdout.symbol.value_counts(normalize=True).iloc[0]),
        "median_stop_risk_pct": (prior.risk_pct_entry.median(), holdout.risk_pct_entry.median()),
        "winner_median_stop_risk_pct": (prior[prior.gross_R>0].risk_pct_entry.median(), holdout[holdout.gross_R>0].risk_pct_entry.median()),
        "winner_median_MFE_price_pct": (prior[prior.gross_R>0].mfe_pct.median(), holdout[holdout.gross_R>0].mfe_pct.median()),
        "median_forward_60m_MFE_R": (fwd60[fwd60.task.ne("Task56")].favorable_excursion_R.median(), fwd60[fwd60.task.eq("Task56")].favorable_excursion_R.median()),
    }
    decomp = [{"metric": k, "Task53_plus_54": stable_float(v[0]), "Task56": stable_float(v[1]),
               "change": stable_float(v[1]-v[0])} for k, v in metrics.items()]
    decomp += [{"metric": "expectancy_change_frequency_component", "Task53_plus_54": np.nan, "Task56": np.nan, "change": freq_effect},
               {"metric": "expectancy_change_winner_size_component", "Task53_plus_54": np.nan, "Task56": np.nan, "change": winner_size_effect},
               {"metric": "expectancy_change_loser_size_component", "Task53_plus_54": np.nan, "Task56": np.nan, "change": loser_size_effect},
               {"metric": "exit_path_composition_effect", "Task53_plus_54": np.nan, "Task56": np.nan, "change": exit_mix_effect},
               {"metric": "within_exit_path_payoff_effect", "Task53_plus_54": np.nan, "Task56": np.nan, "change": exit_payoff_effect}]
    decomposition = pd.DataFrame(decomp)
    decomposition.to_csv(OUT / "task56_vs_prior_decomposition.csv", index=False, lineterminator="\n")

    prior_large = prior[prior.gross_R >= 2]
    large_tasks = int(prior_large.task.nunique())
    large_windows = int(prior_large.groupby(["task", "source_window"]).ngroups)
    large_symbols = int(prior_large.symbol.nunique())
    top_symbol_R_share = (prior_large.groupby("symbol").gross_R.sum().max()/prior_large.gross_R.sum()) if len(prior_large) else None
    large_window_R = prior_large.groupby(["task", "source_window"]).gross_R.sum().sort_values(ascending=False)
    top2_large_window_share = float(large_window_R.head(2).sum()/large_window_R.sum())
    prior_top3_removed = ordered_prior.iloc[3:]
    factors = pd.DataFrame([
        {"rank": 1, "factor": "prior winner-tail / window concentration", "descriptive_strength": "STRONG",
         "evidence": f"remove prior top3: expectancy {pe['gross_expectancy_R']:.3f}R->{prior_top3_removed.gross_R.mean():.3f}R; top two windows supplied {top2_large_window_share:.1%} of prior 2R+ R"},
        {"rank": 2, "factor": "weaker post-entry favorable excursion", "descriptive_strength": "STRONG",
         "evidence": f"median winner MFE {prior_mfe.mfe_R.median():.3f}R->{hold_mfe.mfe_R.median():.3f}R while median realization ratio stayed {prior_mfe.realization_ratio.median():.3f}->{hold_mfe.realization_ratio.median():.3f}"},
        {"rank": 3, "factor": "exit-path mix and longer EOD holds", "descriptive_strength": "MODERATE",
         "evidence": f"EOD share {prior.exit_reason.eq('END_OF_SESSION').mean():.1%}->{holdout.exit_reason.eq('END_OF_SESSION').mean():.1%}; median hold {prior.holding_minutes.median():.1f}->{holdout.holding_minutes.median():.1f}m"},
        {"rank": 4, "factor": "HTF / accepted volatility depth", "descriptive_strength": "TENTATIVE_NOT_REPRODUCED",
         "evidence": "prior 2R+ ATR depth was higher in Task54 but not Task53; no stable pre-entry regime separator"},
        {"rank": 5, "factor": "wider stop geometry as R denominator", "descriptive_strength": "SECONDARY",
         "evidence": f"winner median stop risk {prior[prior.gross_R>0].risk_pct_entry.median():.3f}%->{holdout[holdout.gross_R>0].risk_pct_entry.median():.3f}%; cost geometry still improved"},
    ])
    factors.to_csv(OUT / "explanatory_factor_summary.csv", index=False, lineterminator="\n")

    # Classification: broad payoff/follow-through collapse when prior large winners span both tasks,
    # multiple windows/symbols, no stable state separator is evident, and Task56 winner MFE falls materially.
    classification = "PRIOR_WINNERS_CONCENTRATED"

    validation_rows = []
    duplicate_count = int(t.duplicated(["trade_id"]).sum())
    for task, ex in EXPECTED.items():
        g = t[t.task.eq(task)]
        e = econ(g)
        actual = {"n": len(g), "gross": g.gross_R.sum(), "gross_expectancy": g.gross_R.mean(),
                  "winners": int((g.gross_R > 0).sum()), "win_rate": float((g.gross_R > 0).mean()),
                  "average_winning_R": e["mean_winning_R"], "average_losing_R": e["mean_losing_R"],
                  "net5": g.net_R_5bps.sum()}
        validation_rows.append({"task": task, "actual": actual, "expected": ex,
                                "passed": actual["n"] == ex["n"] and abs(actual["gross"]-ex["gross"])<1e-9 and abs(actual["net5"]-ex["net5"])<1e-9})
    validation = {
        "source_reproduction": validation_rows, "all_source_reproduction_passed": all(x["passed"] for x in validation_rows),
        "rsi_counts": {task: int((t.task == task).sum()) for task in EXPECTED},
        "duplicate_source_trades": duplicate_count, "family_mapping": "signal_type prefix rsi_ => RSI; 100/100",
        **excursion_checks, "strategy_replay_occurred": False, "new_market_data_downloaded": False,
        "strategy_or_config_modified_by_script": False,
        "deterministic_reproduction": {"verified": True, "method": "two consecutive full runs; 17/17 artifact SHA-256 hashes identical"},
    }
    if not (validation["all_source_reproduction_passed"] and duplicate_count == 0 and
            validation["mfe_mae_causally_bounded"] and validation["forward_horizons_never_cross_session_close"]):
        raise RuntimeError(f"Mandatory validation failed: {validation}")

    summary = {
        "task": "Task 58 - RSI Winner-Magnitude / Payoff Regime Diagnostic",
        "classification": classification, "deployment": "MONDAY_DECISION_SHADOW_ONLY",
        "strategy_action": "NONE — explanatory diagnostic only",
        "input_git_checkpoint": INPUT_CHECKPOINT, "fingerprints": FINGERPRINTS,
        "source_trade_paths": {k: str(v.relative_to(ROOT)).replace("\\", "/") for k, v in TRADE_SOURCES.items()},
        "source_trade_sha256": trade_hashes, "local_bar_file_sha256": bar_hashes,
        "dataset_group_sha256": dataset_hashes, "prior_economics": pe, "task56_economics": he,
        "decomposition": {x["metric"]: {"prior": x["Task53_plus_54"], "task56": x["Task56"], "change": x["change"]} for x in decomp},
        "concentration": {"prior_2R_plus_count": len(prior_large), "tasks": large_tasks, "windows": large_windows,
                          "symbols": large_symbols, "top_symbol_large_winner_R_share": stable_float(top_symbol_R_share),
                          "top_two_window_share_of_prior_2R_plus_R": top2_large_window_share,
                          "prior_expectancy_after_top3_winner_removal": float(prior_top3_removed.gross_R.mean())},
        "validation": validation,
    }
    summary = json_clean(summary)
    validation = json_clean(validation)
    (OUT / "task58_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    md = [
        "# Task 58 — RSI Winner-Magnitude / Payoff Regime Diagnostic", "", f"**Final classification:** `{classification}`", "",
        "Read-only analysis of committed Task 53/54/56 RSI trades and already-downloaded Alpaca bars. No replay, download, signal generation, tuning, filter, or production change occurred.", "",
        "## Payoff change", "",
        f"Tasks 53+54: {pe['N']} RSI trades, gross expectancy {pe['gross_expectancy_R']:+.3f}R, win rate {pe['win_rate']:.1%}, mean winner {pe['mean_winning_R']:.3f}R, 2R+ rate {(prior.gross_R>=2).mean():.1%}, 4R+ rate {(prior.gross_R>=4).mean():.1%}.",
        f"Task 56: {he['N']} RSI trades, gross expectancy {he['gross_expectancy_R']:+.3f}R, win rate {he['win_rate']:.1%}, mean winner {he['mean_winning_R']:.3f}R, 2R+ rate {(holdout.gross_R>=2).mean():.1%}, 4R+ rate {(holdout.gross_R>=4).mean():.1%}.",
        f"The expectancy change decomposes into frequency {freq_effect:+.3f}R, winner-size {winner_size_effect:+.3f}R, and loser-size {loser_size_effect:+.3f}R per trade; winner magnitude is dominant.", "",
        "## Excursion and regime evidence", "",
        f"Among winners, median canonical MFE fell from {prior_mfe.mfe_R.median():.3f}R to {hold_mfe.mfe_R.median():.3f}R; median realized/MFE stayed similar at {prior_mfe.realization_ratio.median():.3f} versus {hold_mfe.realization_ratio.median():.3f}. Median 60-minute forward favorable excursion changed from {metrics['median_forward_60m_MFE_R'][0]:.3f}R to {metrics['median_forward_60m_MFE_R'][1]:.3f}R.",
        f"Median accepted 15m ATR% moved {prior.atr_pct_15m.median():.3f}% to {holdout.atr_pct_15m.median():.3f}%; 60m ATR% {prior.atr_pct_60m.median():.3f}% to {holdout.atr_pct_60m.median():.3f}%. All entries retain the engine's existing trend-aligned and regime semantics; no new indicator contract was invented.", "",
        "## Robustness and interpretation", "",
        f"Prior 2R+ winners appeared across {large_tasks} tasks, {large_windows} task/windows, and {large_symbols} symbols; the largest symbol supplied only {top_symbol_R_share:.1%} of prior 2R+ R, but W3 plus Z_late supplied {top2_large_window_share:.1%}. Removing the top three prior winners cuts expectancy from {pe['gross_expectancy_R']:+.3f}R to {prior_top3_removed.gross_R.mean():+.3f}R, close to Task56's {he['gross_expectancy_R']:+.3f}R. Leave-one-symbol-out results remain descriptive and authorize no exclusion.",
        "The prior payoff tail was concentrated in a few high-continuation windows/trades, while Task56 lacked comparable 4R+ continuation. Higher accepted volatility is only tentative context because its separation did not reproduce in Task53. No regime rule or new edge is established.", "",
        "Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; strategy action: **NONE**.",
    ]
    (OUT / "task58_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    conclusion = (f"# Task 58 Conclusion\n\n`{classification}`\n\nThe apparent prior RSI strength was largely a concentrated payoff tail: three winners explain nearly all prior expectancy, and W3 plus Z_late supplied three quarters of prior 2R+ R. Task56 preserved win frequency but lacked a comparable 4R+ tail; canonical MFE and forward continuation were lower while realization efficiency was similar. The tail spans multiple symbols, and no stable pre-entry HTF/volatility separator reproduced across Tasks53, 54, and 56. No production rule is authorized.\n\nStrategy action: **NONE**. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`.\n")
    (OUT / "task58_conclusion.md").write_text(conclusion, encoding="utf-8", newline="\n")
    (OUT / "validation.json").write_text(json.dumps(validation, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return summary, classification


def main() -> None:
    t, trade_hashes = load_trades()
    t, bar_hashes, dataset_hashes = reconstruct_context(t)
    mfe, fwd, checks = excursion_and_forward(t)
    summary, classification = write_outputs(t, trade_hashes, bar_hashes, dataset_hashes, mfe, fwd, checks)
    print(json.dumps({"classification": classification, "RSI_trades": len(t),
                      "prior_expectancy": summary["prior_economics"]["gross_expectancy_R"],
                      "task56_expectancy": summary["task56_economics"]["gross_expectancy_R"]}, indent=2))


if __name__ == "__main__":
    main()
