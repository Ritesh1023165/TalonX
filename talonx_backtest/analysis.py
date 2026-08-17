"""
talonx_backtest.analysis
-----------------------------
Descriptive breakdowns over a completed backtest's trades, plus two
research-scaffolding helpers (walk-forward date splitting, ablation
config generation) that are explicitly NOT auto-optimizers -- see each
function's own docstring. Nothing here changes talonx_quant.config
defaults; ablation/sensitivity configs are separate QuantConfig
instances a caller passes to a NEW BacktestEngine, never mutations of
the frozen production one.
"""
from __future__ import annotations

import dataclasses
from collections import defaultdict
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd

from talonx_backtest.metrics import PerformanceMetrics, compute_metrics
from talonx_backtest.portfolio import Trade

_ET = ZoneInfo("America/New_York")


def _group_and_score(trades: list[Trade], key_fn, r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    buckets: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        key = key_fn(t)
        if key is None:
            continue
        buckets[key].append(t)
    return {key: compute_metrics(group, r_field=r_field) for key, group in sorted(buckets.items())}


# ------------------------------------------------------------------
# Time-based analysis (spec section 12)
# ------------------------------------------------------------------

def by_date(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    return _group_and_score(trades, lambda t: None if t.exit_timestamp is None else str(t.exit_timestamp.date()), r_field)


def by_week(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    def key(t: Trade):
        if t.exit_timestamp is None:
            return None
        iso = t.exit_timestamp.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return _group_and_score(trades, key, r_field)


def by_month(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    return _group_and_score(
        trades, lambda t: None if t.exit_timestamp is None else f"{t.exit_timestamp.year}-{t.exit_timestamp.month:02d}", r_field,
    )


def by_year(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    return _group_and_score(trades, lambda t: None if t.exit_timestamp is None else str(t.exit_timestamp.year), r_field)


def by_session(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    return _group_and_score(trades, lambda t: t.session or "unknown", r_field)


def by_direction(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    return _group_and_score(trades, lambda t: t.direction, r_field)


def by_symbol(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    return _group_and_score(trades, lambda t: t.symbol, r_field)


# Entry-time-of-day buckets, ET wall-clock -- distinct from by_session
# (which only distinguishes pre_market vs regular per session.py) and
# from get_entry_blackout (which exists to GATE candidates, not bucket
# trades after the fact). These boundaries mirror session.py's own
# opening/closing-blackout windows (09:30-09:45 ET) plus a coarse
# midday split, purely for descriptive reporting.
_FIRST_30M_START = time(9, 30)
_FIRST_30M_END = time(10, 0)
_LAST_HOUR_START = time(15, 0)
_REGULAR_END = time(16, 0)


def _time_of_day_bucket(entry_timestamp) -> str | None:
    if entry_timestamp is None:
        return None
    local = entry_timestamp.astimezone(_ET).time()
    if local < _FIRST_30M_START:
        return "premarket"
    if local < _FIRST_30M_END:
        return "first_30m"
    if local < _LAST_HOUR_START:
        return "midday"
    if local < _REGULAR_END:
        return "last_hour"
    return "after_hours"


def by_time_of_day(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    """Buckets by ENTRY time (not signal/exit time) into premarket /
    first_30m (09:30-10:00 ET) / midday (10:00-15:00 ET) / last_hour
    (15:00-16:00 ET) / after_hours. Ordered dict-insertion-independent --
    callers wanting a fixed display order should iterate this fixed list
    rather than relying on dict order."""
    return _group_and_score(trades, lambda t: _time_of_day_bucket(t.entry_timestamp), r_field)


TIME_OF_DAY_ORDER = ("premarket", "first_30m", "midday", "last_hour", "after_hours")


# ------------------------------------------------------------------
# Signal-quality analysis (spec section 13)
# ------------------------------------------------------------------

def by_confluence(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    return _group_and_score(
        trades, lambda t: None if t.confluence_score is None else f"{t.confluence_score}/3", r_field,
    )


def _rr_bucket(rr: float | None) -> str | None:
    if rr is None:
        return None
    if rr < 2.0:
        return "1.5-2.0"
    if rr < 2.5:
        return "2.0-2.5"
    if rr < 3.0:
        return "2.5-3.0"
    return "3.0+"


def by_risk_reward(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    # screening_rr, not the legacy risk_reward_ratio alias (portfolio.Trade's
    # own docstring: identical by construction today, but screening_rr is
    # the canonical, explicitly-named field -- reading it here removes this
    # function's only remaining dependency on the "kept for backward
    # compatibility" field.
    return _group_and_score(trades, lambda t: _rr_bucket(t.screening_rr), r_field)


def _volume_bucket(surge: float | None) -> str | None:
    if surge is None:
        return None
    if surge < 3.0:
        return "2-3x"
    if surge < 5.0:
        return "3-5x"
    if surge < 10.0:
        return "5-10x"
    return "10x+"


def by_volume_surge(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    return _group_and_score(trades, lambda t: _volume_bucket(t.volume_surge_ratio), r_field)


def by_trend_alignment(trades: list[Trade], r_field: str = "net_R") -> dict[str, PerformanceMetrics]:
    def key(t: Trade):
        if t.trend_alignment is True:
            return "aligned"
        if t.trend_alignment is False:
            return "misaligned"
        return "neutral"
    return _group_and_score(trades, key, r_field)


# ------------------------------------------------------------------
# Exit analysis (spec section 14)
# ------------------------------------------------------------------

def exit_reason_counts(trades: list[Trade]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for t in trades:
        counts[t.exit_reason or "UNKNOWN"] += 1
    return dict(sorted(counts.items()))


# ------------------------------------------------------------------
# Walk-forward validation scaffolding (spec section 19) -- date splitting
# only. This does NOT run or optimize anything; it hands back the three
# date-bounded slices of a DataFrame so a caller can run three SEPARATE
# BacktestEngine passes (train/validation/out-of-sample) and compare
# their metric_set()s. No parameter search happens here or anywhere in
# this package.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class WalkForwardSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    out_of_sample: pd.DataFrame
    train_range: tuple[str, str]
    validation_range: tuple[str, str]
    out_of_sample_range: tuple[str, str]


def walk_forward_split(
    df: pd.DataFrame,
    train_end: str,
    validation_end: str,
    out_of_sample_end: str | None = None,
) -> WalkForwardSplit:
    """Splits a normalized OHLCV frame (talonx_backtest.data) into three
    chronological, non-overlapping slices by `timestamp`:
    [start, train_end) -> train, [train_end, validation_end) ->
    validation, [validation_end, out_of_sample_end or end) ->
    out-of-sample. Dates are UTC-parsed strings (e.g. "2025-01-01").
    Purely a data split -- see this section's own docstring above for
    why nothing here trains or optimizes anything."""
    train_end_ts = pd.Timestamp(train_end, tz="UTC")
    validation_end_ts = pd.Timestamp(validation_end, tz="UTC")
    out_end_ts = pd.Timestamp(out_of_sample_end, tz="UTC") if out_of_sample_end else df["timestamp"].max()

    train = df[df["timestamp"] < train_end_ts]
    validation = df[(df["timestamp"] >= train_end_ts) & (df["timestamp"] < validation_end_ts)]
    out_of_sample = df[(df["timestamp"] >= validation_end_ts) & (df["timestamp"] <= out_end_ts)]

    def _range(frame: pd.DataFrame) -> tuple[str, str]:
        if frame.empty:
            return ("n/a", "n/a")
        return (str(frame["timestamp"].min()), str(frame["timestamp"].max()))

    return WalkForwardSplit(
        train=train, validation=validation, out_of_sample=out_of_sample,
        train_range=_range(train), validation_range=_range(validation), out_of_sample_range=_range(out_of_sample),
    )


# ------------------------------------------------------------------
# Ablation scaffolding (spec section 20) -- generates EXPERIMENTAL
# QuantConfig variants for a caller to run through separate
# BacktestEngine instances and compare against the frozen baseline. This
# function only builds config objects; it never runs a backtest, never
# picks a "winner", and never writes back to the production QuantConfig.
# ------------------------------------------------------------------

# Each ablation disables ONE gate by relaxing its threshold to a
# pass-through value, rather than deleting the gate's code path --
# keeps every ablation config valid input to the SAME evaluate_signals/
# gate pipeline the baseline uses, so "Baseline - RSI" differs from
# baseline by exactly one threshold, nothing else.
_ABLATIONS: dict[str, dict[str, object]] = {
    "baseline": {},
    "baseline_minus_rsi": {"rsi_oversold": -1.0, "rsi_overbought": 101.0},
    "baseline_minus_volume": {"volume_surge_ratio_threshold": 0.0, "premarket_volume_surge_ratio_threshold": 0.0},
    "baseline_minus_trend_gate": {"trend_gate_enabled": False},
    "baseline_minus_atr_move_gate": {"atr_move_multiplier": 0.0},
    "baseline_minus_rr_gate": {"min_risk_reward_ratio": 0.0},
    "baseline_minus_confluence_gate": {"confluence_score_min": 0},
}


def ablation_configs(base_config) -> dict[str, object]:
    """Returns {label: QuantConfig} for the baseline plus each named
    single-factor ablation in _ABLATIONS, each a `dataclasses.replace`
    of `base_config` (the frozen production QuantConfig) with exactly
    one gate relaxed. Run each through its own BacktestEngine and
    compare metrics.metric_set() output -- this function does not do
    that itself."""
    return {label: dataclasses.replace(base_config, **overrides) for label, overrides in _ABLATIONS.items()}


# ------------------------------------------------------------------
# Cost-sensitivity analysis (spec section 10) -- runs the SAME frozen
# strategy over the SAME historical data once per execution-cost
# scenario, varying ONLY entry/exit slippage and spread. This is
# sensitivity analysis only: it never selects, ranks as "best", or
# recommends any one scenario -- see cost_sensitivity_scenarios' own
# docstring for the cost model and DEFAULT_COST_SCENARIOS_BPS below.
# ------------------------------------------------------------------

DEFAULT_COST_SCENARIOS_BPS: tuple[int, ...] = (0, 5, 10, 20)


def cost_sensitivity_scenarios(
    df: pd.DataFrame,
    quant_config,
    bps_scenarios: tuple[int, ...] = DEFAULT_COST_SCENARIOS_BPS,
    same_bar_resolution: str = "stop_first",
    eod_flatten_enabled: bool = True,
    progress_callback=None,
) -> list[dict]:
    """Runs a fresh BacktestEngine once per `bps_scenarios` entry, over
    the identical `df` and `quant_config` (the frozen strategy is
    untouched between scenarios) -- only execution cost changes.

    Cost model (deliberately simple and uniform, not calibrated to any
    specific venue -- documented here so a reader knows exactly what
    "N bps" means in this table): for a scenario of `bps` basis points,
    entry_slippage_bps = exit_slippage_bps = spread_bps = bps. This
    charges the SAME cost on both legs of the trade plus the same
    nominal spread, rather than trying to model a specific broker's fee
    schedule.

    Returns one dict per scenario (net-of-cost metrics only -- gross is
    cost-invariant by definition, so showing it here would be
    redundant): cost_bps, trades, win_rate, profit_factor, expectancy_r,
    total_r, max_drawdown_r. Never picks or highlights a "best" row --
    that judgment is left entirely to whoever reads the table.

    `progress_callback`, if given, is called as `callback(scenario_index,
    scenario_count, bps, bars_done, bars_total)` -- one full BacktestEngine
    pass runs per scenario, so this is the SAME per-bar progress
    BacktestEngine.run() reports, just labeled with which of the
    `len(bps_scenarios)` passes is currently running (this function is
    every bit as slow as a plain run, just repeated once per scenario --
    see engine.run()'s own docstring for why a bar-level progress signal
    matters here)."""
    from talonx_backtest.engine import BacktestConfig, BacktestEngine
    from talonx_backtest.execution import ExecutionConfig

    rows: list[dict] = []
    for i, bps in enumerate(bps_scenarios, start=1):
        config = BacktestConfig(
            quant_config=quant_config,
            execution=ExecutionConfig(
                entry_slippage_bps=float(bps), exit_slippage_bps=float(bps), spread_bps=float(bps),
                same_bar_resolution=same_bar_resolution,
            ),
            eod_flatten_enabled=eod_flatten_enabled,
        )
        engine_progress = None
        if progress_callback is not None:
            def engine_progress(bars_done, bars_total, _i=i, _bps=bps):
                progress_callback(_i, len(bps_scenarios), _bps, bars_done, bars_total)
        result = BacktestEngine(config).run(df, progress_callback=engine_progress)
        m = compute_metrics(result.trades, r_field="net_R")
        rows.append({
            "cost_bps": bps,
            "trades": m.total_trades,
            "win_rate": m.win_rate,
            "profit_factor": None if m.profit_factor in (None, float("inf")) else m.profit_factor,
            "expectancy_r": m.expectancy_r,
            "total_r": m.total_r,
            "max_drawdown_r": m.max_drawdown_r,
        })
    return rows
