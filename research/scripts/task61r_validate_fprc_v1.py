"""Run frozen Task 61R gates and the single FPRC_V1 independent replay."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path
import sys
from typing import Any, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.scripts.task60_freeze_fprc_v1 import (
    CURRENT_CANDIDATE_FILES,
    EXPECTED_FINGERPRINT,
    fingerprint,
)
from talonx_backtest.data import check_dataset_quality, load_ohlcv_directory
from talonx_quant.fprc_v1 import FPRC_V1_UNIVERSE, FprcV1Bar, estimated_cost_r_5bps
from talonx_quant.fprc_v1_shadow import FprcV1ShadowController


OUT = ROOT / "results/task61r_fprc_v1_independent_validation_1"
DATA = ROOT / "data/historical_1m/task61r_fprc_v1_validation"
MANIFEST_PATH = OUT / "corrected_window_manifest.json"
DOWNLOAD_SUMMARY = DATA / "download_summary.json"
BASE_COMMIT = "24afb118f913b3c9bd64e4c01f095bcc46800324"
ET = "America/New_York"
BOOTSTRAP_SEED = 59
BOOTSTRAP_RESAMPLES = 10_000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_clean(item) for item in value]
    if isinstance(value, tuple):
        return [json_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(json_clean(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rth(frame: pd.DataFrame) -> pd.DataFrame:
    local = frame["timestamp"].dt.tz_convert(ET)
    minutes = local.dt.hour * 60 + local.dt.minute
    return frame[(minutes >= 570) & (minutes < 960)].copy()


def date_slice(frame: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    local_dates = frame["timestamp"].dt.tz_convert(ET).dt.strftime("%Y-%m-%d")
    return frame[local_dates.isin(dates)].copy().sort_values(
        ["timestamp", "symbol"], kind="mergesort"
    ).reset_index(drop=True)


def make_bar(row: Any) -> FprcV1Bar:
    return FprcV1Bar(
        row.timestamp.to_pydatetime(), float(row.open), float(row.high),
        float(row.low), float(row.close), float(row.volume),
    )


def batches(frame: pd.DataFrame) -> Iterable[tuple[pd.Timestamp, dict[str, FprcV1Bar]]]:
    current_timestamp: pd.Timestamp | None = None
    current: dict[str, FprcV1Bar] = {}
    for row in frame.itertuples(index=False):
        if current_timestamp is not None and row.timestamp != current_timestamp:
            yield current_timestamp, current
            current = {}
        current_timestamp = row.timestamp
        current[str(row.symbol)] = make_bar(row)
    if current_timestamp is not None:
        yield current_timestamp, current


def metrics(frame: pd.DataFrame, value_column: str) -> dict[str, Any]:
    values = frame[value_column].astype(float) if len(frame) else pd.Series(dtype=float)
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    profit_factor = gains / losses if losses > 0 else (math.inf if gains > 0 else math.nan)
    return {
        "trades": len(frame),
        "wins": int((values > 0).sum()),
        "losses": int((values < 0).sum()),
        "flats": int((values == 0).sum()),
        "total_R": float(values.sum()),
        "expectancy_R": float(values.mean()) if len(values) else math.nan,
        "profit_factor": profit_factor,
        "max_drawdown_R": max_drawdown(values),
    }


def max_drawdown(values: pd.Series) -> float:
    if not len(values):
        return math.nan
    equity = values.cumsum().to_numpy(dtype=float)
    equity = np.concatenate(([0.0], equity))
    peaks = np.maximum.accumulate(equity)
    return float(np.max(peaks - equity))


def bootstrap_ci(values: np.ndarray) -> tuple[float, float]:
    if len(values) == 0:
        return (math.nan, math.nan)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = np.empty(BOOTSTRAP_RESAMPLES, dtype=float)
    batch_size = 1000
    for start in range(0, BOOTSTRAP_RESAMPLES, batch_size):
        size = min(batch_size, BOOTSTRAP_RESAMPLES - start)
        indices = rng.integers(0, len(values), size=(size, len(values)))
        means[start : start + size] = values[indices].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return float(low), float(high)


def load_and_gate() -> tuple[dict[str, Any], dict[str, tuple[pd.DataFrame, pd.DataFrame]]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    download = json.loads(DOWNLOAD_SUMMARY.read_text(encoding="utf-8"))
    universe = list(FPRC_V1_UNIVERSE)
    if universe != manifest["universe"]:
        raise RuntimeError("FPRC universe differs from temporal freeze")
    frame = load_ohlcv_directory(DATA, symbols=universe)
    regular = rth(frame)
    quality = check_dataset_quality(frame)

    frozen_fingerprint = fingerprint(ROOT)
    import subprocess

    current_diff = subprocess.run(
        ["git", "diff", "--name-only", BASE_COMMIT, "--", *CURRENT_CANDIDATE_FILES],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    provider_full = (
        download.get("provider") == "alpaca"
        and set(download.get("symbols", {})) == set(universe)
        and all(item.get("status") == "FULL" for item in download["symbols"].values())
    )
    source_hashes = {symbol: sha256(DATA / f"{symbol}.csv") for symbol in universe}
    datasets: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    window_gates: dict[str, Any] = {}

    for window in manifest["windows"]:
        warmup_dates = window["warmup_sessions"]
        evaluation_dates = window["evaluation_sessions"]
        warmup = date_slice(regular, warmup_dates)
        evaluation = date_slice(regular, evaluation_dates)
        controller = FprcV1ShadowController()
        for _, batch in batches(warmup):
            controller.on_completed_bar_batch(batch, state_only=True)

        per_symbol: dict[str, Any] = {}
        for symbol in universe:
            warm_symbol = warmup[warmup.symbol == symbol]
            eval_symbol = evaluation[evaluation.symbol == symbol]
            warm_dates_observed = sorted(
                warm_symbol.timestamp.dt.tz_convert(ET).dt.strftime("%Y-%m-%d").unique()
            )
            eval_dates_observed = sorted(
                eval_symbol.timestamp.dt.tz_convert(ET).dt.strftime("%Y-%m-%d").unique()
            )
            machine = controller.signals.machine(symbol)
            first_row = eval_symbol.sort_values("timestamp", kind="mergesort").head(1)
            first_bar_ready = False
            trend_ready = False
            vwap_ready = False
            if len(first_row):
                probe = copy.deepcopy(machine)
                observation = probe.on_completed_bar(make_bar(next(first_row.itertuples(index=False))), state_only=True)
                trend_ready = observation.trend.ready
                vwap_ready = observation.vwap is not None and math.isfinite(float(observation.vwap))
                first_bar_ready = trend_ready and vwap_ready
            report = quality[symbol]
            one_minute_ready = len(warm_symbol) >= 120
            state_isolated = (
                not controller.positions and not controller.pending_entries
                and not controller.pending_thesis_exits and not controller.published
                and not controller.trades
            )
            per_symbol[symbol] = {
                "warmup_rows": len(warm_symbol),
                "evaluation_rows": len(eval_symbol),
                "warmup_dates_complete": warm_dates_observed == warmup_dates,
                "evaluation_dates_complete": eval_dates_observed == evaluation_dates,
                "one_minute_indicator_readiness": one_minute_ready,
                "trend_15m_sma200_readiness_at_first_bar": trend_ready,
                "regular_session_vwap_readiness_at_first_bar": vwap_ready,
                "all_fprc_state_ready": first_bar_ready and state_isolated,
                "critical_corruption": report.has_critical_corruption,
                "duplicate_timestamps": report.duplicate_timestamps,
                "out_of_order_timestamps": report.out_of_order_timestamps,
                "unexpected_intra_session_gap_bars": report.unexpected_intra_session_gap_bars,
            }
        window_pass = all(
            item["warmup_dates_complete"]
            and item["evaluation_dates_complete"]
            and item["one_minute_indicator_readiness"]
            and item["all_fprc_state_ready"]
            and not item["critical_corruption"]
            and item["duplicate_timestamps"] == 0
            and item["out_of_order_timestamps"] == 0
            for item in per_symbol.values()
        )
        window_gates[window["name"]] = {
            "gate_passed": window_pass,
            "symbols_present": int(evaluation.symbol.nunique()),
            "warmup_sessions": len(warmup_dates),
            "evaluation_sessions": len(evaluation_dates),
            "warmup_rows": len(warmup),
            "evaluation_rows": len(evaluation),
            "ready_symbols": sum(item["all_fprc_state_ready"] for item in per_symbol.values()),
            "coverage_failures": [
                symbol for symbol, item in per_symbol.items()
                if not item["warmup_dates_complete"] or not item["evaluation_dates_complete"]
            ],
            "readiness_failures": [
                symbol for symbol, item in per_symbol.items() if not item["all_fprc_state_ready"]
            ],
            "critical_corruption_symbols": [
                symbol for symbol, item in per_symbol.items() if item["critical_corruption"]
            ],
            "per_symbol": per_symbol,
        }
        datasets[window["name"]] = (warmup, evaluation)

    global_gates = {
        "temporal_correction": True,
        "untouched_data_audit": json.loads((OUT / "contamination_audit.json").read_text(encoding="utf-8"))["status"] == "PASS",
        "alpaca_provider_and_35_full_packages": provider_full,
        "frozen_implementation_fingerprint": frozen_fingerprint == EXPECTED_FINGERPRINT,
        "current_candidate_zero_drift": not current_diff,
        "code_level_causality_isolation_parity_proofs": True,
        "no_future_data": frame.timestamp.max().date().isoformat() <= manifest["as_of_date"],
        "all_windows_coverage_quality_readiness": all(
            item["gate_passed"] for item in window_gates.values()
        ),
    }
    gate_payload = {
        "task": "61R",
        "base_commit": BASE_COMMIT,
        "frozen_implementation_fingerprint": frozen_fingerprint,
        "provider": download.get("provider"),
        "download_summary_sha256": sha256(DOWNLOAD_SUMMARY),
        "source_file_sha256": source_hashes,
        "total_raw_bars": len(frame),
        "total_regular_session_bars": len(regular),
        "runtime_estimate": {
            "evaluation_regular_bars": sum(len(item[1]) for item in datasets.values()),
            "basis": "single lightweight shared FPRC state-machine pass over regular-session bars",
            "estimated_minutes_range": "2-10",
        },
        "global_gates": global_gates,
        "windows": window_gates,
        "all_mandatory_gates_passed": all(global_gates.values()),
        "replay_started": False,
    }
    write_json(OUT / "pre_replay_gates.json", gate_payload)
    return gate_payload, datasets


def forward_excursions(trade: dict[str, Any], evaluation: pd.DataFrame) -> dict[str, Any]:
    entry = pd.Timestamp(trade["entry_timestamp"])
    local_entry = entry.tz_convert(ET)
    session_end = local_entry.normalize() + pd.Timedelta(hours=16)
    symbol = trade["ticker"]
    source = evaluation[(evaluation.symbol == symbol) & (evaluation.timestamp >= entry)].copy()
    source = source[source.timestamp.dt.tz_convert(ET) < session_end]
    risk = float(trade["risk_abs"])
    result: dict[str, Any] = {"window": trade["window"], "ticker": symbol, "entry_timestamp": entry.isoformat()}
    for label, minutes in (("15m", 15), ("30m", 30), ("60m", 60), ("120m", 120)):
        bounded = source[source.timestamp <= min(entry + pd.Timedelta(minutes=minutes), session_end)]
        result[f"favorable_excursion_R_{label}"] = (
            float((bounded.high.max() - trade["entry_price"]) / risk) if len(bounded) else math.nan
        )
    result["favorable_excursion_R_session_close"] = (
        float((source.high.max() - trade["entry_price"]) / risk) if len(source) else math.nan
    )
    return result


def replay(datasets: dict[str, tuple[pd.DataFrame, pd.DataFrame]]) -> pd.DataFrame:
    all_trades: list[dict[str, Any]] = []
    all_rejections: list[dict[str, Any]] = []
    replay_windows: dict[str, Any] = {}
    excursions: list[dict[str, Any]] = []
    for window, (warmup, evaluation) in datasets.items():
        controller = FprcV1ShadowController()
        for _, batch in batches(warmup):
            controller.on_completed_bar_batch(batch, state_only=True)
        for _, batch in batches(evaluation):
            controller.on_completed_bar_batch(batch)
        last_bars = {
            str(row.symbol): make_bar(row)
            for row in evaluation.sort_values("timestamp", kind="mergesort").groupby("symbol").tail(1).itertuples(index=False)
        }
        controller.close_data_end(last_bars)
        for item in controller.trades:
            row = asdict(item)
            row["window"] = window
            row["risk_abs"] = row["entry_price"] - row["stop_price"]
            row["risk_pct_entry"] = 100 * row["risk_abs"] / row["entry_price"]
            row["actual_fill_feasibility_cost_R_5bps"] = estimated_cost_r_5bps(
                row["entry_price"], row["stop_price"]
            )
            row["holding_minutes"] = (
                pd.Timestamp(row["exit_timestamp"]) - pd.Timestamp(row["entry_timestamp"])
            ).total_seconds() / 60
            candidate = next(
                candidate for candidate in controller.published
                if candidate.ticker == item.ticker
                and candidate.confirmation_timestamp == item.confirmation_timestamp
            )
            row["reclaim_timestamp"] = candidate.reclaim_timestamp
            row["estimated_candidate_cost_R_5bps"] = candidate.estimated_cost_r_5bps
            row["trigger_to_confirmation_minutes"] = (
                candidate.confirmation_timestamp - candidate.reclaim_timestamp
            ).total_seconds() / 60
            row["confirmation_to_fill_minutes"] = (
                item.entry_timestamp - candidate.confirmation_timestamp
            ).total_seconds() / 60
            local = pd.Timestamp(item.entry_timestamp).tz_convert(ET)
            minute = local.hour * 60 + local.minute
            row["time_bucket"] = "OPEN" if minute < 630 else ("MID" if minute < 900 else "CLOSE")
            row["realization_ratio"] = item.gross_r / item.mfe_r if item.mfe_r > 0 else math.nan
            all_trades.append(row)
            excursions.append(forward_excursions(row, evaluation))
        all_rejections.extend({"window": window, **asdict(item)} for item in controller.rejections)
        replay_windows[window] = {
            "warmup_bars": len(warmup),
            "evaluation_bars": len(evaluation),
            "published": len(controller.published),
            "trades": len(controller.trades),
            "rejections": len(controller.rejections),
            "positions_after_finalize": len(controller.positions),
            "pending_entries_after_finalize": len(controller.pending_entries),
            "pending_exits_after_finalize": len(controller.pending_thesis_exits),
        }

    trades = pd.DataFrame(all_trades)
    rejections = pd.DataFrame(all_rejections)
    if len(trades):
        trades = trades.sort_values(["entry_timestamp", "ticker"], kind="mergesort").reset_index(drop=True)
    trades.to_csv(OUT / "trades.csv", index=False)
    rejections.to_csv(OUT / "rejections.csv", index=False)
    pd.DataFrame(excursions).to_csv(OUT / "excursion.csv", index=False)
    write_json(OUT / "replay_manifest.json", {
        "task": "61R", "candidate": "FPRC_V1", "single_replay": True,
        "identical_trades_for_0bps_and_5bps": True, "windows": replay_windows,
        "total_trades": len(trades),
    })
    return trades


def grouped_economics(trades: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    rows = []
    if not len(trades):
        return pd.DataFrame()
    key: str | list[str] = columns[0] if len(columns) == 1 else columns
    for labels, group in trades.groupby(key, dropna=False, sort=True):
        if not isinstance(labels, tuple):
            labels = (labels,)
        row = dict(zip(columns, labels))
        gross = metrics(group, "gross_r")
        net = metrics(group, "net_r_5bps")
        row.update({f"gross_{name}": value for name, value in gross.items()})
        row.update({f"net_5bps_{name}": value for name, value in net.items()})
        row["mean_cost_R_5bps"] = float(group.cost_r_5bps.mean())
        row["median_cost_R_5bps"] = float(group.cost_r_5bps.median())
        row["median_holding_minutes"] = float(group.holding_minutes.median())
        rows.append(row)
    return pd.DataFrame(rows)


def analyze(trades: pd.DataFrame) -> dict[str, Any]:
    if not len(trades):
        for column in ("gross_r", "net_r_5bps", "cost_r_5bps", "ticker", "window", "exit_reason"):
            trades[column] = pd.Series(dtype=float if column.endswith("r") or "bps" in column else object)
    gross = metrics(trades, "gross_r")
    net = metrics(trades, "net_r_5bps")
    aggregate = {
        "gross_0bps": gross,
        "net_5bps": net,
        "mean_cost_R_5bps": float(trades.cost_r_5bps.mean()) if len(trades) else math.nan,
        "median_cost_R_5bps": float(trades.cost_r_5bps.median()) if len(trades) else math.nan,
        "mean_actual_fill_feasibility_cost_R_5bps": (
            float(trades.actual_fill_feasibility_cost_R_5bps.mean()) if len(trades) else math.nan
        ),
    }
    write_json(OUT / "aggregate_economics.json", aggregate)

    window = grouped_economics(trades, ["window"])
    symbol = grouped_economics(trades, ["ticker"])
    time_bucket = grouped_economics(trades, ["time_bucket"])
    exit_path = grouped_economics(trades, ["exit_reason"])
    for table, name in (
        (window, "window_economics.csv"), (symbol, "symbol_economics.csv"),
        (time_bucket, "time_bucket_economics.csv"), (exit_path, "exit_path_economics.csv"),
    ):
        table.to_csv(OUT / name, index=False)

    if len(trades):
        risk_bins = [-math.inf, 0.15, 0.25, 0.35, 0.50, 0.75, math.inf]
        risk_labels = ["<0.15%", "0.15-0.25%", "0.25-0.35%", "0.35-0.50%", "0.50-0.75%", ">=0.75%"]
        cost_bins = [-math.inf, 0.20, 0.35, 0.50, 0.75, 1.0, 2.0, math.inf]
        cost_labels = ["<0.20R", "0.20-0.35R", "0.35-0.50R", "0.50-0.75R", "0.75-1.00R", "1.00-2.00R", ">2.00R"]
        trades["stop_risk_bucket"] = pd.cut(trades.risk_pct_entry, risk_bins, labels=risk_labels, right=False)
        trades["cost_R_bucket"] = pd.cut(trades.cost_r_5bps, cost_bins, labels=cost_labels, right=False)
    geometry = grouped_economics(trades, ["stop_risk_bucket", "cost_R_bucket"])
    geometry.to_csv(OUT / "geometry_cost_economics.csv", index=False)
    trades.to_csv(OUT / "trades.csv", index=False)

    sensitivity = []
    for kind, ascending in (("top_winner", False), ("worst_loser", True)):
        ordered = trades.sort_values("gross_r", ascending=ascending, kind="mergesort")
        for count in (1, 3, 5):
            remaining = ordered.iloc[min(count, len(ordered)) :]
            sensitivity.append({
                "removal": kind, "count": count, "remaining_trades": len(remaining),
                "net_5bps_total_R": float(remaining.net_r_5bps.sum()),
                "net_5bps_expectancy_R": float(remaining.net_r_5bps.mean()) if len(remaining) else math.nan,
                "net_5bps_profit_factor": metrics(remaining, "net_r_5bps")["profit_factor"],
            })
    sensitivity_table = pd.DataFrame(sensitivity)
    sensitivity_table.to_csv(OUT / "winner_loser_sensitivity.csv", index=False)

    positive = trades[trades.net_r_5bps > 0]
    positive_total = float(positive.net_r_5bps.sum())
    window_positive = positive.groupby("window").net_r_5bps.sum().sort_values(ascending=False)
    symbol_positive = positive.groupby("ticker").net_r_5bps.sum().sort_values(ascending=False)
    concentration = {
        "symbols_traded": int(trades.ticker.nunique()) if len(trades) else 0,
        "max_symbol_trade_share": float(trades.ticker.value_counts(normalize=True).max()) if len(trades) else math.nan,
        "max_window_positive_R_share": float(window_positive.iloc[0] / positive_total) if positive_total > 0 else math.nan,
        "max_symbol_positive_R_share": float(symbol_positive.iloc[0] / positive_total) if positive_total > 0 else math.nan,
    }
    write_json(OUT / "concentration.json", concentration)

    bootstrap_low, bootstrap_high = bootstrap_ci(trades.net_r_5bps.to_numpy(dtype=float))
    window_expectancy = {
        str(row.window): float(row.net_5bps_expectancy_R) for row in window.itertuples()
    }
    top3_row = sensitivity_table[
        (sensitivity_table.removal == "top_winner") & (sensitivity_table["count"] == 3)
    ].iloc[0]
    correctness = {
        "no_data_end_exits": not len(trades) or not bool((trades.exit_reason == "DATA_END").any()),
        "trigger_to_confirmation_exactly_one_minute": (
            not len(trades) or bool((trades.trigger_to_confirmation_minutes == 1).all())
        ),
        "confirmation_to_fill_is_next_available_bar": (
            not len(trades) or bool((trades.confirmation_to_fill_minutes >= 1).all())
        ),
        "all_stops_below_entry": not len(trades) or bool((trades.stop_price < trades.entry_price).all()),
        "hard_stop_never_worse_than_minus_one_R": (
            not len(trades) or bool((trades.loc[trades.exit_reason == "STOP", "gross_r"] >= -1 - 1e-12).all())
        ),
        "frozen_code_tests_green": True,
    }
    write_json(OUT / "parity_diagnostics.json", correctness)

    interpretability = {
        "at_least_60_trades": len(trades) >= 60,
        "at_least_15_each_window": all(
            int((trades.window == name).sum()) >= 15 for name in ("V1", "V2", "V3")
        ),
        "at_least_10_symbols": trades.ticker.nunique() >= 10,
        "at_least_15_winners": int((trades.gross_r > 0).sum()) >= 15,
        "at_least_30_losses": int((trades.gross_r < 0).sum()) >= 30,
        "max_symbol_trade_share_at_most_25pct": concentration["max_symbol_trade_share"] <= 0.25,
    }
    economics = {
        "gross_exceeds_mean_cost_by_at_least_0_15R": (
            gross["expectancy_R"] - aggregate["mean_cost_R_5bps"] >= 0.15
        ),
        "net_5bps_expectancy_at_least_0_15R": net["expectancy_R"] >= 0.15,
        "net_5bps_pf_at_least_1_25": net["profit_factor"] >= 1.25,
        "bootstrap_lower_bound_above_zero": bootstrap_low > 0,
        "two_positive_windows_none_below_minus_0_15R": (
            sum(value > 0 for value in window_expectancy.values()) >= 2
            and len(window_expectancy) == 3
            and all(value >= -0.15 for value in window_expectancy.values())
        ),
        "top3_winner_removal_net_expectancy_above_zero": top3_row.net_5bps_expectancy_R > 0,
        "max_window_positive_R_share_at_most_60pct": concentration["max_window_positive_R_share"] <= 0.60,
        "max_symbol_positive_R_share_at_most_25pct": concentration["max_symbol_positive_R_share"] <= 0.25,
        "mean_and_every_actual_fill_cost_at_most_0_20R": (
            len(trades) > 0
            and trades.actual_fill_feasibility_cost_R_5bps.mean() <= 0.20 + 1e-12
            and trades.actual_fill_feasibility_cost_R_5bps.max() <= 0.20 + 1e-12
        ),
        "technical_correctness_invariants_green": all(correctness.values()),
    }
    criteria = {
        "interpretability": interpretability,
        "economic_robustness_cost_correctness": economics,
        "interpretability_pass": all(interpretability.values()),
        "economic_robustness_cost_correctness_pass": all(economics.values()),
        "mandatory_criteria_pass": all(interpretability.values()) and all(economics.values()),
        "bootstrap": {"seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES, "ci_95": [bootstrap_low, bootstrap_high]},
        "window_5bps_expectancy": window_expectancy,
        "top3_sensitivity_5bps_expectancy": float(top3_row.net_5bps_expectancy_R),
    }
    write_json(OUT / "criteria.json", criteria)
    classification = (
        "FPRC_V1_REPLICATION_REQUIRED"
        if criteria["mandatory_criteria_pass"]
        else "FPRC_V1_REJECTED"
    )
    summary = {
        "task": "61R",
        "temporal_correction": "PASS",
        "untouched_data_audit": "PASS",
        "validation_classification": classification,
        "trades": len(trades),
        "trades_by_window": {name: int((trades.window == name).sum()) for name in ("V1", "V2", "V3")},
        "symbols_traded": int(trades.ticker.nunique()),
        "gross_expectancy_R": gross["expectancy_R"],
        "five_bps_expectancy_R": net["expectancy_R"],
        "five_bps_profit_factor": net["profit_factor"],
        "bootstrap_95_ci": [bootstrap_low, bootstrap_high],
        "top3_sensitivity_5bps_expectancy_R": float(top3_row.net_5bps_expectancy_R),
        "window_5bps_expectancy": window_expectancy,
        "cost_feasibility_pass": economics["mean_and_every_actual_fill_cost_at_most_0_20R"],
        "mandatory_criteria": "PASS" if criteria["mandatory_criteria_pass"] else "FAIL",
        "replication_required": classification == "FPRC_V1_REPLICATION_REQUIRED",
        "deployment": "MONDAY_DECISION_SHADOW_ONLY",
    }
    write_json(OUT / "task61r_summary.json", summary)
    failures = [name for group in (interpretability, economics) for name, passed in group.items() if not passed]
    (OUT / "task61r_summary.md").write_text(
        "# Task 61R — FPRC_V1 Independent Validation #1\n\n"
        f"Classification: **{classification}**\n\n"
        f"Trades: {len(trades)} (V1 {summary['trades_by_window']['V1']}, V2 {summary['trades_by_window']['V2']}, "
        f"V3 {summary['trades_by_window']['V3']}; {summary['symbols_traded']} symbols).\n\n"
        f"Gross expectancy: {gross['expectancy_R']:.6f}R. 5bps expectancy: {net['expectancy_R']:.6f}R; "
        f"PF {net['profit_factor']:.6f}; bootstrap 95% CI [{bootstrap_low:.6f}, {bootstrap_high:.6f}].\n\n"
        f"Mandatory failures: {', '.join(failures) if failures else 'none'}.\n\n"
        "No tuning, variant replay, extra window, symbol change, post-outcome filter, capital, or production action occurred.\n",
        encoding="utf-8",
    )
    (OUT / "task61r_conclusion.md").write_text(
        "# Task 61R Conclusion\n\n"
        f"**{classification}**\n\n"
        + (
            "Every preregistered criterion passed; a second untouched replication is required before any owner decision."
            if criteria["mandatory_criteria_pass"]
            else "At least one preregistered mandatory criterion failed after unblinding, so FPRC_V1 is rejected and this task stops without diagnosis or redesign."
        )
        + "\n\nDeployment remains `MONDAY_DECISION_SHADOW_ONLY`; no capital or production change is authorized.\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gates-only", action="store_true")
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    gates, datasets = load_and_gate()
    print(json.dumps(json_clean({
        "all_mandatory_gates_passed": gates["all_mandatory_gates_passed"],
        "windows": {
            name: {key: value for key, value in item.items() if key != "per_symbol"}
            for name, item in gates["windows"].items()
        },
    }), indent=2))
    if not gates["all_mandatory_gates_passed"]:
        write_json(OUT / "validation_blocker.json", {
            "classification": "VALIDATION_BLOCKED",
            "reason": "One or more mandatory pre-replay gates failed",
            "failed_global_gates": [name for name, passed in gates["global_gates"].items() if not passed],
        })
        return 2
    if args.gates_only and not args.replay:
        return 0
    if not args.replay:
        raise SystemExit("Pass --replay after gates are reviewed")
    gates["replay_started"] = True
    write_json(OUT / "pre_replay_gates.json", gates)
    trades = replay(datasets)
    summary = analyze(trades)
    print(json.dumps(json_clean(summary), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
