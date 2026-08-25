"""
research/scripts/task67a_family04_relative_strength.py
---------------------------------------------------------
Task 67B Step 2, Family 4: RELATIVE STRENGTH vs SPY / sector ETF.

Question: does stock-specific residual strength relative to market/sector
predict subsequent continuation? A naive `stock_return - SPY_return`
("raw RS") is contaminated by beta: a high-beta stock looks artificially
strong on raw RS during any market rally, which is not a stock-specific
phenomenon. This family separates the two via a causal, fail-closed beta
adjustment (section A below) and treats the BETA-ADJUSTED residual, not
raw RS, as the verdict-relevant effect (section B).

Exploratory, read-only, DEVELOPMENT-data-only phenomenon discovery -- NOT
a trading engine, NOT a backtest, NOT strategy freezing. Stock-universe
data access is exclusively via research.task67a_lib.data_guard's
STAGE1_DISCOVERY_GUARD (DEVELOPMENT role only). Benchmark (SPY / sector
ETF) OHLCV is read directly from data/historical_1m/task67a_benchmarks --
per the brief, that directory is NOT covered by DataSplitGuard (only the
DEVELOPMENT date range was ever downloaded for these benchmarks), so a
direct `pd.read_csv` there is not a data-discipline violation.

--------------------------------------------------------------------
A. BETA ESTIMATION (done ONCE, causally, fail-closed)
--------------------------------------------------------------------
The 62-trading-day DEVELOPMENT window is split in half BY CALENDAR DAY,
computed from the actual sorted unique trading days present in the
universe bars (not a hardcoded date guess): the first ~31 days are the
"calibration half", the last ~31 the "application half" (`
calibration_application_split`).

For each of the 35 symbols, USING ONLY calibration-half 1-minute bars,
`beta_spy` is estimated as Cov(stock 1-min return, SPY 1-min return) /
Var(SPY 1-min return) -- an OLS slope on paired same-timestamp 1-minute
returns (`_compute_beta`). Return definition: simple close-to-close pct
return between two CONSECUTIVE same-day bars whose gap is <= 5 minutes
(`_one_minute_returns`; the 5-minute tolerance absorbs the occasional
missing 1-min bar without silently computing a multi-hour-gap "return" as
if it were a 1-minute return). `beta_sector` is estimated the same way
against the symbol's mapped GICS sector ETF (from benchmark_inventory.
json's `sector_etfs.mapping`, reversed into a symbol->ETF lookup by
`load_sector_mapping`).

Fail-closed discipline: a symbol's calibration-half data must yield
`MIN_PAIRED_OBS_FOR_BETA` (2000) matched-timestamp return pairs before
its beta is trusted (this dataset runs ~900 bars/session, so 2000 pairs
is roughly 2 trading days of continuous 1-minute data -- a low, explicitly
documented bar, not tuned to flatter any symbol). Below that, `beta_spy`/
`beta_sector` is None and the symbol is EXCLUDED from the beta-adjusted
analysis (section B) -- never defaulted to beta=1 or beta=0.

ALL Family 4 candidate events (all 3 definitions) are restricted to the
APPLICATION HALF of the DEVELOPMENT window only (`build_rs_candidates`'s
`app_mask`), so beta is never estimated using data at or after the event
it is later applied to. See tests/test_task67a_family04_relative_strength.py
for the dedicated causality regression test.

--------------------------------------------------------------------
B. THREE RS DEFINITIONS + BETA-ADJUSTED RESIDUAL (Family-4-specific)
--------------------------------------------------------------------
Definitions vary only the trailing-return window used for the RS SIGNAL
itself (30m / 60m / 90m); the beta methodology above is one fixed
approach shared across all three. For each stock bar, RAW RS =
causal_trailing_return(stock, W) - causal_trailing_return(SPY, W), where
the SPY (and sector ETF) trailing return is looked up via the same
causal, same-day lookback logic `causal_price_at_offset` uses (see
`_causal_benchmark_lookup`, a cross-table generalization of that
algorithm since the price SOURCE here is a benchmark's own single-symbol
bar table, distinct from the QUERY frame of 35-symbol `bars_feat`).

Event condition: RAW RS falls in the top/bottom `RS_TAIL_QUANTILE` (10%)
of pooled application-half RAW RS values (a two-sided global-decile
extremity threshold, computed once per definition over the SAME
application-half candidate population the events are drawn from -- not
the whole dataset, and not leaking calibration-half values into the
threshold), at a bar at/after 14:00 UTC (excludes the first 30 minutes of
RTH, `POST_OPENING_RANGE_UTC_HOUR`, ORPB territory) with >=15 minutes of
same-day room before RTH close. Direction = sign(RAW RS) -- does strong
(or weak) relative strength continue.

This event set runs through the STANDARD `run_family_definition` pipeline
exactly like Families 1-3 (dedup / matched-control / clustered bootstrap
/ concentration / effect-surface / econ classification / verdict) --
those are the RAW RS matched-control numbers, reported in every standard
deliverable file and explicitly labeled "raw, before beta adjustment" in
summary.md. They are NOT the basis for the family's verdict.

ADDITIONALLY, for the same deduplicated event set restricted further to
symbols with a trustworthy `beta_spy` AND `beta_sector` (fail-closed
exclusion of the rest), `compute_beta_adjusted_metrics` computes, per
event and horizon (15/30/60/120m):
  - raw_forward_pct: the event's own direction-adjusted forward return
    (from the standard pipeline's horizon_metrics -- NOT matched-control
    excess, just the raw signed forward return for this trustworthy-beta
    subset).
  - spy_forward_pct / sector_forward_pct: SPY's / the sector ETF's own
    forward return over the same horizon window from the event's
    timestamp, direction-sign-adjusted the same way
    compute_event_horizon_and_mfe_mae direction-adjusts (multiplied by
    the event's own direction sign).
  - spy_adjusted_forward_pct = raw_forward_pct - beta_spy * spy_forward_pct
  - sector_adjusted_forward_pct = raw_forward_pct - beta_sector * sector_forward_pct
`bootstrap_ci_clustered` (grouped by symbol) is run separately on all
three series at every horizon (`bootstrap_beta_adjusted`), with distinct
seeds (see FAMILY_SEED_OFFSET / BETA_BOOTSTRAP_SEED_OFFSET below) so
resamples across the raw/spy-adjusted/sector-adjusted series are not
accidentally correlated with each other or with the standard pipeline's
own per-horizon excess bootstrap.

`classify_economic_magnitude` is applied to the SPY-adjusted mean at the
primary 60m horizon and the standard pipeline's `mfe_pct_median` (reused
as a documented proxy for a hypothetical perfect-exit upper bound -- it
describes the event distribution, not the specific beta-adjusted return
metric, but no better MFE/MAE reconstruction exists for the beta-adjusted
series without re-running MFE/MAE off a synthetic "beta-adjusted price
path", which is out of scope here). This becomes the family's REPORTED
economic classification and feeds the definition's actual VERDICT: a
`VerdictInputs` is constructed manually, reusing the standard pipeline's
concentration / effect-surface-instability / data-sufficiency /
temporal-breadth / symbol-breadth / matched-control-support / MFE-MAE-
asymmetry outputs as a documented simplification (those describe the
EVENT distribution, not the return metric), but with `excess_ci_
excludes_zero`, `nontrivial_economic_scale`, and `coherent_direction` all
computed from the BETA-ADJUSTED (SPY-adjusted) bootstrap/econ results,
not the raw ones. If raw RS looks strong but the SPY-adjusted CI includes
zero or the classification drops to ECONOMICALLY_TOO_SMALL, summary.md
states explicitly: "likely factor/beta exposure, not a stock-specific
phenomenon" for that definition.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from research.task67a_lib.data_guard import DataRole, get_stage1_guard
from research.task67a_lib.family_runner import (
    COHERENT_DIRECTION_MIN_AGREEMENT,
    run_family_definition,
)
from research.task67a_lib.research_stats import DEFAULT_SEED, bootstrap_ci_clustered
from research.task67a_lib.screening_framework import (
    DEFAULT_HORIZONS_MINUTES,
    ONE_WAY_FRICTION_BPS,
    POST_OPENING_RANGE_UTC_HOUR,
    ROUND_TRIP_FRICTION_BPS,
    VerdictInputs,
    add_bar_features,
    add_trading_day,
    causal_trailing_return,
    classify_economic_magnitude,
    determine_verdict,
    forward_return_horizons,
    session_close_timestamp_utc,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results/task67a_phenomenon_discovery/family_04_relative_strength"
FAMILY_ID = "family_04_relative_strength"
FAMILY_SEED_OFFSET = 400  # continues the 100/200/300 per-family pattern set by families 1-3.
#: Offset added on top of FAMILY_SEED_OFFSET + definition index for the Family-4-specific
#: raw/spy-adjusted/sector-adjusted bootstraps (section B), kept far away from the standard
#: pipeline's own per-horizon excess-bootstrap seeds (DEFAULT_SEED+FAMILY_SEED_OFFSET+i, +h)
#: so no two independent bootstraps in this script ever share a seed.
BETA_BOOTSTRAP_SEED_OFFSET = 40_000
BENCHMARK_DIR = ROOT / "data/historical_1m/task67a_benchmarks"
BENCHMARK_INVENTORY_PATH = ROOT / "results/task67a_phenomenon_discovery/benchmark_inventory.json"
BENCHMARK_TICKERS = ["SPY", "XLK", "XLY", "XLC", "XLP", "XLV", "XLI", "XLF"]

#: See module docstring section A: ~2 trading days of continuous 1-min data at this
#: dataset's ~900 bars/session pace. A symbol below this for either beta fails closed
#: (excluded from the beta-adjusted analysis) rather than falling back to beta=1/0.
MIN_PAIRED_OBS_FOR_BETA = 2000
#: A same-day 1-min return pair is only used if the two bars are <=5 minutes apart --
#: tolerates an occasional missing bar without conflating a multi-hour-gap "return"
#: with a genuine ~1-minute return.
MAX_RETURN_GAP_MINUTES = 5.0
#: Two-sided global-decile extremity threshold for the RAW RS event condition (top/
#: bottom 10% of pooled application-half RAW RS values) -- documented, not tuned.
RS_TAIL_QUANTILE = 0.10
RS_WINDOWS_MINUTES = [30, 60, 90]


# ---------------------------------------------------------------------
# Benchmark / sector-mapping loading
# ---------------------------------------------------------------------

def load_benchmarks() -> dict[str, pd.DataFrame]:
    """Loads SPY + the 7 sector ETFs' 1-min OHLCV directly from
    data/historical_1m/task67a_benchmarks (NOT via DataSplitGuard -- see
    module docstring for why that is not a data-discipline violation
    here), tz-localizes timestamps to UTC, and adds `trading_day` via
    `add_trading_day` so `_causal_benchmark_lookup` can do same-day-only
    lookups exactly like `causal_price_at_offset` does for the stock
    universe."""
    out: dict[str, pd.DataFrame] = {}
    for ticker in BENCHMARK_TICKERS:
        path = BENCHMARK_DIR / f"{ticker}.csv"
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["symbol"] = ticker
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = add_trading_day(df)
        out[ticker] = df
    return out


def load_sector_mapping() -> dict[str, str]:
    """Reverses benchmark_inventory.json's `sector_etfs.mapping` (ETF ->
    {sector, symbols:[...]}) into a symbol -> ETF ticker lookup, per the
    brief's instruction to use the exact mapping on file rather than
    re-deriving one."""
    inv = json.loads(BENCHMARK_INVENTORY_PATH.read_text(encoding="utf-8"))
    mapping = inv["sector_etfs"]["mapping"]
    symbol_to_etf: dict[str, str] = {}
    for etf, info in mapping.items():
        if not isinstance(info, dict) or "symbols" not in info:
            continue
        for sym in info["symbols"]:
            symbol_to_etf[sym] = etf
    return symbol_to_etf


# ---------------------------------------------------------------------
# Calendar split
# ---------------------------------------------------------------------

def calibration_application_split(bars_feat: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Splits the sorted unique `trading_day` values present in
    `bars_feat` in half: calibration = first floor(n/2) days, application
    = the remaining (>=) ceil(n/2) days (any odd leftover day goes to
    application, the larger/more-important half for event candidates).
    Computed from the ACTUAL data, never a hardcoded date guess, per the
    brief."""
    days = np.sort(bars_feat["trading_day"].unique())
    half = len(days) // 2
    return days[:half], days[half:]


# ---------------------------------------------------------------------
# Causal cross-table benchmark price lookup
# ---------------------------------------------------------------------

def _to_naive_utc_ns(values) -> np.ndarray:
    """Same normalization `screening_framework._naive_utc_ns` does
    (tz-aware Series -> naive UTC datetime64[ns] numpy array, since a
    tz-aware Series.to_numpy() returns a slow `object` array of
    Timestamps) -- reimplemented locally (a few lines) rather than
    importing that module-private helper, matching family03's own
    precedent of a small local re-implementation for cross-table lookups
    the shared module doesn't provide."""
    dt = pd.to_datetime(pd.Series(values).reset_index(drop=True))
    if getattr(dt.dt, "tz", None) is not None:
        dt = dt.dt.tz_convert("UTC").dt.tz_localize(None)
    return dt.to_numpy(dtype="datetime64[ns]")


def _causal_benchmark_lookup(
    benchmark_bars: pd.DataFrame, query_times, query_days, offset_minutes: float,
) -> np.ndarray:
    """Cross-table generalization of `causal_price_at_offset`: for each
    (query_times[i], query_days[i]) pair, returns the CLOSE of the most
    recent `benchmark_bars` row at or before (query_times[i] -
    offset_minutes) that shares query_days[i]'s trading day (never
    reaches into a prior session), NaN if no such row exists yet.
    `benchmark_bars` must be sorted by timestamp and carry a
    `trading_day` column (`add_trading_day`). Needed because
    `causal_price_at_offset` assumes the query rows and the price-source
    rows are the SAME frame (grouped by symbol); here the price source is
    a benchmark's own single-symbol table, distinct from the 35-symbol
    `bars_feat` query frame."""
    bench_times = _to_naive_utc_ns(benchmark_bars["timestamp"])
    bench_days = _to_naive_utc_ns(benchmark_bars["trading_day"])
    bench_close = benchmark_bars["close"].to_numpy(dtype=float)

    q_times = _to_naive_utc_ns(query_times)
    q_days = _to_naive_utc_ns(query_days)
    target = q_times - np.timedelta64(int(round(offset_minutes * 60)), "s")

    pos = np.searchsorted(bench_times, target, side="right") - 1
    valid = pos >= 0
    pos_clipped = np.clip(pos, 0, len(bench_times) - 1)
    same_day = np.zeros(len(q_times), dtype=bool)
    same_day[valid] = bench_days[pos_clipped[valid]] == q_days[valid]
    ok = valid & same_day
    out = np.full(len(q_times), np.nan, dtype=float)
    out[ok] = bench_close[pos_clipped[ok]]
    return out


def _benchmark_trailing_return_for_all(
    bars_feat: pd.DataFrame, bench_bars: pd.DataFrame, window_minutes: float,
) -> tuple[np.ndarray, np.ndarray]:
    """SPY (one shared benchmark for the whole universe) trailing return,
    aligned to every `bars_feat` row: no per-symbol grouping needed since
    all rows query the same benchmark series. Returns (trailing_return,
    price_now) -- `price_now` is also stored on candidate events so the
    beta-adjusted forward-return step (section B) has a causal SPY entry
    price without a second lookup."""
    now = _causal_benchmark_lookup(bench_bars, bars_feat["timestamp"], bars_feat["trading_day"], 0.0)
    lag = _causal_benchmark_lookup(bench_bars, bars_feat["timestamp"], bars_feat["trading_day"], window_minutes)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = (now - lag) / lag
    return ret, now


def _sector_trailing_return_for_all(
    bars_feat: pd.DataFrame, benchmarks: dict[str, pd.DataFrame], symbol_to_etf: dict[str, str],
    window_minutes: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Same as `_benchmark_trailing_return_for_all` but per-symbol, since
    each stock maps to a DIFFERENT sector ETF: loops the 35 symbol groups
    (cheap) and looks each group up against its own mapped ETF's bars.
    Returns (trailing_return, price_now, etf_ticker_per_row)."""
    n = len(bars_feat)
    ret = np.full(n, np.nan, dtype=float)
    now_price = np.full(n, np.nan, dtype=float)
    etf_col = np.array([""] * n, dtype=object)
    times_all = bars_feat["timestamp"].to_numpy()
    days_all = bars_feat["trading_day"].to_numpy()
    for sym, idx in bars_feat.groupby("symbol", sort=False).indices.items():
        idx = np.asarray(idx)
        etf = symbol_to_etf.get(sym)
        bench_bars = benchmarks.get(etf) if etf is not None else None
        if bench_bars is None:
            continue
        now = _causal_benchmark_lookup(bench_bars, times_all[idx], days_all[idx], 0.0)
        lag = _causal_benchmark_lookup(bench_bars, times_all[idx], days_all[idx], window_minutes)
        with np.errstate(divide="ignore", invalid="ignore"):
            r = (now - lag) / lag
        ret[idx] = r
        now_price[idx] = now
        etf_col[idx] = etf
    return ret, now_price, etf_col


# ---------------------------------------------------------------------
# Section A: beta estimation
# ---------------------------------------------------------------------

def _one_minute_returns(df: pd.DataFrame, max_gap_minutes: float = MAX_RETURN_GAP_MINUTES) -> pd.DataFrame:
    """Simple close-to-close pct return between CONSECUTIVE same-day bars
    whose gap is <= `max_gap_minutes` -- see module docstring section A
    for the return-definition rationale. `df` must have `timestamp`,
    `close`, `trading_day` columns; need not be pre-sorted."""
    d = df.sort_values("timestamp").reset_index(drop=True)
    prev_close = d["close"].shift(1)
    prev_day = d["trading_day"].shift(1)
    gap_minutes = d["timestamp"].diff().dt.total_seconds() / 60.0
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = (d["close"] - prev_close) / prev_close
    same_day = d["trading_day"] == prev_day
    valid = same_day & gap_minutes.notna() & (gap_minutes <= max_gap_minutes) & ret.notna()
    out = pd.DataFrame({"timestamp": d["timestamp"], "ret": ret})
    return out.loc[valid.to_numpy()].reset_index(drop=True)


def _compute_beta(stock_bars_calib: pd.DataFrame, bench_bars_calib: pd.DataFrame) -> tuple[float | None, int]:
    """OLS slope of stock 1-min return on benchmark 1-min return
    (Cov(stock,bench)/Var(bench)), computed on paired SAME-TIMESTAMP
    1-min returns (inner merge on timestamp). Returns (None, n) -- fail
    closed -- if n < MIN_PAIRED_OBS_FOR_BETA or the benchmark return
    series has zero variance in this sample."""
    stock_ret = _one_minute_returns(stock_bars_calib)
    bench_ret = _one_minute_returns(bench_bars_calib)
    merged = stock_ret.merge(bench_ret, on="timestamp", how="inner", suffixes=("_stock", "_bench"))
    n = len(merged)
    if n < MIN_PAIRED_OBS_FOR_BETA:
        return None, n
    x = merged["ret_bench"].to_numpy(dtype=float)
    y = merged["ret_stock"].to_numpy(dtype=float)
    var_x = float(np.var(x))
    if var_x <= 0:
        return None, n
    cov_xy = float(np.mean((x - x.mean()) * (y - y.mean())))
    return cov_xy / var_x, n


def compute_all_betas(
    bars_feat: pd.DataFrame, benchmarks: dict[str, pd.DataFrame], symbol_to_etf: dict[str, str],
    calibration_days: np.ndarray,
) -> pd.DataFrame:
    """Runs `_compute_beta` once per symbol against SPY and once against
    its mapped sector ETF, USING ONLY calibration-half bars for both the
    stock and the benchmark side. Returns one row per symbol with
    beta_spy/beta_sector, their paired-observation counts, and
    trustworthy_* flags (see MIN_PAIRED_OBS_FOR_BETA)."""
    spy_calib = benchmarks["SPY"][benchmarks["SPY"]["trading_day"].isin(calibration_days)]
    etf_calib_cache: dict[str, pd.DataFrame] = {}
    rows = []
    for sym, g in bars_feat.groupby("symbol", sort=False):
        stock_calib = g[g["trading_day"].isin(calibration_days)]
        beta_spy, n_spy = _compute_beta(stock_calib, spy_calib)
        etf = symbol_to_etf.get(sym)
        if etf not in etf_calib_cache and etf in benchmarks:
            etf_calib_cache[etf] = benchmarks[etf][benchmarks[etf]["trading_day"].isin(calibration_days)]
        beta_sector, n_sector = (
            _compute_beta(stock_calib, etf_calib_cache[etf]) if etf in etf_calib_cache else (None, 0)
        )
        rows.append({
            "symbol": sym, "sector_etf": etf,
            "beta_spy": beta_spy, "n_pairs_spy": n_spy, "trustworthy_spy": beta_spy is not None,
            "beta_sector": beta_sector, "n_pairs_sector": n_sector, "trustworthy_sector": beta_sector is not None,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------
# Section B: RS candidate events
# ---------------------------------------------------------------------

def build_rs_candidates(
    bars_feat: pd.DataFrame, benchmarks: dict[str, pd.DataFrame], symbol_to_etf: dict[str, str],
    application_days: np.ndarray, window_minutes: float,
) -> tuple[pd.DataFrame, dict]:
    """Builds the raw candidate-event table for one RS definition (see
    module docstring section B). Restricted to the APPLICATION HALF only
    (`app_mask`) -- this is what keeps beta estimation causally isolated
    from every event: beta never saw this half's data, and the event
    condition/RS threshold are computed only from it."""
    spy_ret, spy_now = _benchmark_trailing_return_for_all(bars_feat, benchmarks["SPY"], window_minutes)
    sector_ret, sector_now, sector_etf_col = _sector_trailing_return_for_all(
        bars_feat, benchmarks, symbol_to_etf, window_minutes
    )
    stock_ret = causal_trailing_return(bars_feat, window_minutes)
    raw_rs = stock_ret - spy_ret

    app_mask = bars_feat["trading_day"].isin(application_days).to_numpy()
    finite = np.isfinite(raw_rs)
    pool = raw_rs[app_mask & finite]
    if len(pool) == 0:
        tail_mask = np.zeros(len(bars_feat), dtype=bool)
        q_lo = q_hi = None
    else:
        q_lo, q_hi = (float(v) for v in np.quantile(pool, [RS_TAIL_QUANTILE, 1 - RS_TAIL_QUANTILE]))
        tail_mask = finite & ((raw_rs <= q_lo) | (raw_rs >= q_hi))

    t = pd.to_datetime(bars_feat["timestamp"])
    minutes_of_day = t.dt.hour * 60 + t.dt.minute
    post_open = (minutes_of_day >= POST_OPENING_RANGE_UTC_HOUR * 60).to_numpy()

    close_ts = bars_feat["trading_day"] + pd.Timedelta(hours=20)  # RTH_CLOSE_UTC_HOUR
    min_lead = ((close_ts - bars_feat["timestamp"]) >= pd.Timedelta(minutes=15)).to_numpy()

    mask = app_mask & tail_mask & post_open & min_lead & (raw_rs != 0)

    cand = bars_feat.loc[mask, [
        "symbol", "timestamp", "close", "trailing_vol_60m", "time_of_day_bucket", "vol_bucket", "trading_day",
    ]].rename(columns={"close": "entry_price"}).copy()
    cand["direction"] = np.where(raw_rs[mask] > 0, 1, -1)
    cand["raw_rs"] = raw_rs[mask]
    cand["spy_entry_price"] = spy_now[mask]
    cand["sector_entry_price"] = sector_now[mask]
    cand["sector_etf"] = sector_etf_col[mask]
    tail_info = {
        "rs_tail_quantile": RS_TAIL_QUANTILE, "q_lo": q_lo, "q_hi": q_hi, "n_pool": int(len(pool)),
    }
    return cand, tail_info


# ---------------------------------------------------------------------
# Section B: beta-adjusted forward-return metrics
# ---------------------------------------------------------------------

def compute_beta_adjusted_metrics(
    events_df: pd.DataFrame, horizon_metrics_df: pd.DataFrame, beta_df: pd.DataFrame,
    benchmarks: dict[str, pd.DataFrame], horizons_minutes=DEFAULT_HORIZONS_MINUTES,
) -> pd.DataFrame | None:
    """For the subset of `events_df` on symbols with a trustworthy
    beta_spy AND beta_sector (fail-closed exclusion of the rest), computes
    SPY's/the sector ETF's own direction-signed forward return at every
    horizon and the resulting spy_adjusted / sector_adjusted residuals
    (see module docstring section B). Returns None if no event survives
    the trustworthy-beta restriction."""
    trust = beta_df[beta_df["trustworthy_spy"] & beta_df["trustworthy_sector"]].set_index("symbol")
    ev = events_df[events_df["symbol"].isin(trust.index)].copy()
    if ev.empty:
        return None

    spy_bars = benchmarks["SPY"]
    rows = []
    for _, row in ev.iterrows():
        entry_ts = pd.Timestamp(row["timestamp"])
        close_ts = session_close_timestamp_utc(entry_ts)
        direction_raw = row["direction"]
        sign = -1.0 if direction_raw in (-1, "short", "SHORT") else 1.0
        sector_bars = benchmarks.get(row["sector_etf"])

        spy_fwd = forward_return_horizons(
            spy_bars, entry_timestamp=entry_ts, entry_price=float(row["spy_entry_price"]),
            horizons_minutes=list(horizons_minutes), session_close_timestamp=close_ts,
        )
        if sector_bars is not None:
            sector_fwd = forward_return_horizons(
                sector_bars, entry_timestamp=entry_ts, entry_price=float(row["sector_entry_price"]),
                horizons_minutes=list(horizons_minutes), session_close_timestamp=close_ts,
            )
        else:
            sector_fwd = [{"horizon_minutes": h, "forward_close_return_pct": None} for h in horizons_minutes]

        for h_spy, h_sector in zip(spy_fwd, sector_fwd):
            spy_pct = h_spy["forward_close_return_pct"]
            sector_pct = h_sector["forward_close_return_pct"]
            rows.append({
                "event_id": row["event_id"], "symbol": row["symbol"], "horizon_minutes": h_spy["horizon_minutes"],
                "spy_forward_pct": (spy_pct * sign) if spy_pct is not None else None,
                "sector_forward_pct": (sector_pct * sign) if sector_pct is not None else None,
            })

    fwd_df = pd.DataFrame(rows)
    merged = horizon_metrics_df.merge(fwd_df, on=["event_id", "symbol", "horizon_minutes"], how="inner")
    merged["beta_spy"] = merged["symbol"].map(trust["beta_spy"])
    merged["beta_sector"] = merged["symbol"].map(trust["beta_sector"])
    merged["raw_forward_pct"] = merged["forward_return_signed_pct"]
    merged["spy_adjusted_forward_pct"] = merged["raw_forward_pct"] - merged["beta_spy"] * merged["spy_forward_pct"]
    merged["sector_adjusted_forward_pct"] = (
        merged["raw_forward_pct"] - merged["beta_sector"] * merged["sector_forward_pct"]
    )
    return merged


def bootstrap_beta_adjusted(merged: pd.DataFrame, horizons_minutes, seed_base: int) -> dict:
    """Clustered (by symbol) bootstrap CI for raw_forward_pct,
    spy_adjusted_forward_pct, sector_adjusted_forward_pct, at every
    horizon. Distinct seeds per metric (+0 / +10_000 / +20_000) so the
    three resamples are independent of each other."""
    out: dict = {}
    for h in horizons_minutes:
        sub = merged[merged["horizon_minutes"] == h].dropna(
            subset=["raw_forward_pct", "spy_adjusted_forward_pct", "sector_adjusted_forward_pct"]
        )
        symbols = sub["symbol"].to_numpy()
        boot_raw = bootstrap_ci_clustered(sub["raw_forward_pct"].to_numpy(dtype=float), symbols, seed=seed_base + h)
        boot_spy = bootstrap_ci_clustered(
            sub["spy_adjusted_forward_pct"].to_numpy(dtype=float), symbols, seed=seed_base + 10_000 + h
        )
        boot_sector = bootstrap_ci_clustered(
            sub["sector_adjusted_forward_pct"].to_numpy(dtype=float), symbols, seed=seed_base + 20_000 + h
        )
        out[f"{h}m"] = {
            "n": int(len(sub)),
            "raw": boot_raw.as_dict(),
            "spy_adjusted": boot_spy.as_dict(),
            "sector_adjusted": boot_sector.as_dict(),
        }
    return out


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    guard = get_stage1_guard()
    bars = guard.load_ohlcv(DataRole.DEVELOPMENT, symbols=None)
    bars_feat = add_bar_features(bars)
    benchmarks = load_benchmarks()
    symbol_to_etf = load_sector_mapping()

    calibration_days, application_days = calibration_application_split(bars_feat)
    print(f"[family04] calibration days={len(calibration_days)}, application days={len(application_days)}")

    beta_df = compute_all_betas(bars_feat, benchmarks, symbol_to_etf, calibration_days)
    n_symbols_total = int(beta_df["symbol"].nunique())
    n_fail_spy = int((~beta_df["trustworthy_spy"]).sum())
    n_fail_sector = int((~beta_df["trustworthy_sector"]).sum())
    n_fail_either = int((~(beta_df["trustworthy_spy"] & beta_df["trustworthy_sector"])).sum())
    print(f"[family04] beta: {n_symbols_total} symbols, fail_spy={n_fail_spy}, "
          f"fail_sector={n_fail_sector}, fail_either={n_fail_either}")

    all_events, all_horizon_metrics, all_control_metrics, all_mfe_mae = [], [], [], []
    definitions_summary = {}
    definitions_json = []

    for i, window_minutes in enumerate(RS_WINDOWS_MINUTES):
        name = f"rs_trailing_{window_minutes}m"
        cand, tail_info = build_rs_candidates(
            bars_feat, benchmarks, symbol_to_etf, application_days, window_minutes
        )
        dedup_min_gap = max(10.0, window_minutes / 2.0)
        seed = DEFAULT_SEED + FAMILY_SEED_OFFSET + i
        result = run_family_definition(
            bars=bars, bars_feat=bars_feat, candidate_events=cand,
            definition_name=name, dedup_group_keys=["symbol"],
            dedup_min_gap_minutes=dedup_min_gap, seed=seed,
        )

        events = result["events_df"].copy()
        if len(events):
            events["definition"] = name
            all_events.append(events)
        hm = result["horizon_metrics_df"].copy()
        if len(hm):
            hm["definition"] = name
            all_horizon_metrics.append(hm)
        cm = result["control_metrics_df"].copy()
        if len(cm):
            cm["definition"] = name
            all_control_metrics.append(cm)
        mm = result["mfe_mae_df"].copy()
        if len(mm):
            mm["definition"] = name
            all_mfe_mae.append(mm)

        # --- Family-4-specific: beta-adjusted residual analysis ---
        merged = None
        if len(events):
            merged = compute_beta_adjusted_metrics(events, result["horizon_metrics_df"], beta_df, benchmarks)

        if merged is not None and len(merged):
            seed_base = DEFAULT_SEED + FAMILY_SEED_OFFSET + BETA_BOOTSTRAP_SEED_OFFSET + i * 1000
            boot_by_h = bootstrap_beta_adjusted(merged, DEFAULT_HORIZONS_MINUTES, seed_base)
            spy_adj_primary = boot_by_h.get("60m", {}).get("spy_adjusted", {})
            spy_adj_mean = spy_adj_primary.get("point_estimate")
            econ_class_adj = classify_economic_magnitude(
                spy_adj_mean, result.get("mfe_pct_median"), round_trip_friction_bps=ROUND_TRIP_FRICTION_BPS
            )

            valid_h_means = {
                h: boot_by_h[f"{h}m"]["spy_adjusted"]["point_estimate"] for h in DEFAULT_HORIZONS_MINUTES
                if boot_by_h[f"{h}m"]["spy_adjusted"]["point_estimate"] is not None
            }
            if spy_adj_mean is not None and spy_adj_mean != 0 and valid_h_means:
                primary_sign = np.sign(spy_adj_mean)
                agree_frac = float(np.mean([np.sign(v) == primary_sign for v in valid_h_means.values()]))
                coherent_direction_adj = agree_frac >= COHERENT_DIRECTION_MIN_AGREEMENT
            else:
                coherent_direction_adj = False

            if spy_adj_primary and not spy_adj_primary.get("insufficient_n") and spy_adj_primary.get("ci_low") is not None:
                lo, hi = spy_adj_primary["ci_low"], spy_adj_primary["ci_high"]
                excess_ci_excludes_zero_adj = (lo > 0 and hi > 0) or (lo < 0 and hi < 0)
            else:
                excess_ci_excludes_zero_adj = False

            vi_std = result["verdict_inputs"]
            vi_adj = VerdictInputs(
                coherent_direction=coherent_direction_adj,
                matched_control_support=vi_std["matched_control_support"],
                nontrivial_economic_scale=econ_class_adj in ("POTENTIALLY_TRADEABLE", "STRONG_EFFECT"),
                adequate_event_count=vi_std["adequate_event_count"],
                temporal_breadth=vi_std["temporal_breadth"],
                symbol_breadth=vi_std["symbol_breadth"],
                stable_effect_surface=vi_std["stable_effect_surface"],
                asymmetric_mfe_mae=vi_std["asymmetric_mfe_mae"],
                concentration_low=vi_std["concentration_low"],
                excess_ci_excludes_zero=excess_ci_excludes_zero_adj,
                data_sufficiency=vi_std["data_sufficiency"],
            )
            verdict_adj, reasoning_adj = determine_verdict(vi_adj)

            raw_strong = (
                result["economic_classification"] in ("POTENTIALLY_TRADEABLE", "STRONG_EFFECT")
                and vi_std["excess_ci_excludes_zero"]
            )
            adj_weak = (not excess_ci_excludes_zero_adj) or econ_class_adj == "ECONOMICALLY_TOO_SMALL"
            factor_note = None
            if raw_strong and adj_weak:
                factor_note = (
                    f"Raw RS excess for `{name}` looks economically meaningful with a matched-control CI "
                    "excluding zero, but the SPY-beta-adjusted residual's CI includes zero or its economic "
                    "classification drops to ECONOMICALLY_TOO_SMALL: likely factor/beta exposure, not a "
                    "stock-specific phenomenon."
                )

            beta_adjusted_section = {
                "n_trustworthy_events": int(merged["event_id"].nunique()),
                "n_symbols_trustworthy": int(merged["symbol"].nunique()),
                "per_horizon": boot_by_h,
                "economic_classification_beta_adjusted": econ_class_adj,
                "verdict_inputs_beta_adjusted": asdict(vi_adj),
                "verdict_beta_adjusted": verdict_adj,
                "verdict_reasoning_beta_adjusted": reasoning_adj,
                "raw_vs_adjusted_note": factor_note,
            }
        else:
            beta_adjusted_section = {
                "n_trustworthy_events": 0, "n_symbols_trustworthy": 0, "per_horizon": {},
                "economic_classification_beta_adjusted": "INSUFFICIENT_DATA",
                "verdict_inputs_beta_adjusted": None,
                "verdict_beta_adjusted": "INSUFFICIENT_DATA",
                "verdict_reasoning_beta_adjusted": (
                    "No deduplicated event survived restriction to symbols with a trustworthy (fail-closed) "
                    "beta estimate for this definition -- the beta-adjusted analysis (the verdict-relevant one "
                    "for Family 4) could not be computed."
                ),
                "raw_vs_adjusted_note": None,
            }

        definitions_summary[name] = {
            "description": (
                f"RAW RS = causal {window_minutes}m trailing stock return - causal {window_minutes}m trailing "
                f"SPY return, event fires when RAW RS is in the top/bottom {RS_TAIL_QUANTILE:.0%} of pooled "
                "application-half values. Direction = sign(RAW RS). Application-half-only, excludes first 30m "
                "of RTH, >=15min lead before close."
            ),
            "window_minutes": window_minutes,
            "dedup_group_keys": ["symbol"],
            "dedup_min_gap_minutes": dedup_min_gap,
            "seed": seed,
            "tail_info": tail_info,
            "n_raw_events": result["n_raw_events"],
            "n_dedup_events": result["n_dedup_events"],
            "n_symbols": result["n_symbols"],
            "n_days": result["n_days"],
            "per_horizon_raw_matched_control": result["per_horizon"],
            "mfe_pct_median": result.get("mfe_pct_median"),
            "mae_pct_median": result.get("mae_pct_median"),
            "concentration": result["concentration"],
            "effect_surface_instability": result["effect_surface_instability"],
            "effect_surface_instability_reason": result["effect_surface_instability_reason"],
            "economic_classification_raw": result["economic_classification"],
            "data_sufficiency": result["data_sufficiency"],
            "verdict_raw": result["verdict"],
            "verdict_reasoning_raw": result["verdict_reasoning"],
            "verdict_inputs_raw": result["verdict_inputs"],
            "main_weakness_raw": result["main_weakness"],
            "beta_adjusted": beta_adjusted_section,
            # THE definition's reported verdict is the beta-adjusted one, per the brief.
            "verdict": beta_adjusted_section["verdict_beta_adjusted"],
            "verdict_reasoning": beta_adjusted_section["verdict_reasoning_beta_adjusted"],
        }
        definitions_json.append({
            "name": name, "window_minutes": window_minutes, "dedup_group_keys": ["symbol"],
            "dedup_min_gap_minutes": dedup_min_gap, "seed": seed, "tail_info": tail_info,
        })
        print(f"[family04] {name}: raw={result['n_raw_events']} dedup={result['n_dedup_events']} "
              f"raw_verdict={result['verdict']} beta_adjusted_verdict={beta_adjusted_section['verdict_beta_adjusted']} "
              f"econ_adj={beta_adjusted_section['economic_classification_beta_adjusted']}")

    events_df = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()
    horizon_df = pd.concat(all_horizon_metrics, ignore_index=True) if all_horizon_metrics else pd.DataFrame()
    control_df = pd.concat(all_control_metrics, ignore_index=True) if all_control_metrics else pd.DataFrame()
    mfe_mae_df = pd.concat(all_mfe_mae, ignore_index=True) if all_mfe_mae else pd.DataFrame()

    events_df.to_csv(OUT_DIR / "events.csv", index=False)
    horizon_df.to_csv(OUT_DIR / "horizon_metrics.csv", index=False)
    control_df.to_csv(OUT_DIR / "matched_control_metrics.csv", index=False)
    mfe_mae_df.to_csv(OUT_DIR / "mfe_mae.csv", index=False)

    (OUT_DIR / "definitions.json").write_text(json.dumps(definitions_json, indent=2, default=str), encoding="utf-8")
    (OUT_DIR / "concentration.json").write_text(
        json.dumps({name: d["concentration"] for name, d in definitions_summary.items()}, indent=2, default=str),
        encoding="utf-8",
    )

    verdicts = [d["verdict"] for d in definitions_summary.values()]
    rollup_text = (
        f"{sum(v=='PHENOMENON_PRESENT' for v in verdicts)}/3 PHENOMENON_PRESENT, "
        f"{sum(v=='WEAK_SIGNAL' for v in verdicts)}/3 WEAK_SIGNAL, "
        f"{sum(v=='PHENOMENON_NOT_OBSERVED' for v in verdicts)}/3 PHENOMENON_NOT_OBSERVED, "
        f"{sum(v=='INSUFFICIENT_DATA' for v in verdicts)}/3 INSUFFICIENT_DATA -- "
        "definitions are NOT averaged into one number; each is reported independently, per the brief. "
        "Verdicts are the BETA-ADJUSTED (SPY-adjusted) ones, not raw RS."
    )

    beta_summary = beta_df.copy()
    beta_summary_records = json.loads(beta_summary.to_json(orient="records"))

    summary = {
        "family": FAMILY_ID,
        "question": (
            "Does stock-specific residual strength relative to market/sector (SPY-beta-ADJUSTED, not raw "
            "return-minus-SPY) predict subsequent continuation?"
        ),
        "data": {
            "role": "DEVELOPMENT", "n_symbols_universe": 35,
            "n_trading_days": int(len(calibration_days) + len(application_days)),
            "date_range": ["2026-05-15", "2026-08-14"],
            "note": (
                "The brief's nominal figure is ~62 trading days; the ACTUAL unique trading-day count observed "
                "in the loaded DEVELOPMENT bars is reported here (used directly by calibration_application_split "
                "-- the calibration/application split is computed from real data, not this nominal figure)."
            ),
        },
        "friction_assumption_bps": {"one_way": ONE_WAY_FRICTION_BPS, "round_trip": ROUND_TRIP_FRICTION_BPS},
        "calendar_split": {
            "n_calibration_days": int(len(calibration_days)),
            "n_application_days": int(len(application_days)),
            "calibration_days_first": str(pd.Timestamp(calibration_days[0]).date()) if len(calibration_days) else None,
            "calibration_days_last": str(pd.Timestamp(calibration_days[-1]).date()) if len(calibration_days) else None,
            "application_days_first": str(pd.Timestamp(application_days[0]).date()) if len(application_days) else None,
            "application_days_last": str(pd.Timestamp(application_days[-1]).date()) if len(application_days) else None,
        },
        "beta_fail_closed": {
            "min_paired_obs_for_beta": MIN_PAIRED_OBS_FOR_BETA,
            "n_symbols_total": n_symbols_total,
            "n_fail_closed_spy": n_fail_spy,
            "n_fail_closed_sector": n_fail_sector,
            "n_fail_closed_either": n_fail_either,
            "n_trustworthy_both": n_symbols_total - n_fail_either,
        },
        "beta_estimates": beta_summary_records,
        "definitions": definitions_summary,
        "family_rollup": rollup_text,
        "total_raw_events": int(sum(d["n_raw_events"] for d in definitions_summary.values())),
        "total_dedup_events": int(sum(d["n_dedup_events"] for d in definitions_summary.values())),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    beta_spy_vals = beta_df.loc[beta_df["trustworthy_spy"], "beta_spy"].astype(float)
    beta_sector_vals = beta_df.loc[beta_df["trustworthy_sector"], "beta_sector"].astype(float)

    md_lines = [
        "# Family 4 -- Relative Strength vs SPY / Sector ETF -- Stage 1 Screening Summary",
        "",
        "Question: does stock-specific residual strength relative to market/sector predict subsequent "
        "continuation? A naive `stock_return - SPY_return` (\"raw RS\") is contaminated by beta; this family "
        "separates the two via a causal, fail-closed beta adjustment and treats the SPY-beta-ADJUSTED residual, "
        "not raw RS, as the verdict-relevant effect.",
        "",
        f"Data: DEVELOPMENT role, 35 symbols, {len(calibration_days) + len(application_days)} trading days "
        f"(2026-05-15..2026-08-14; brief's nominal figure is ~62, actual observed unique days used throughout). "
        f"Friction assumption: {ONE_WAY_FRICTION_BPS}bps one-way / {ROUND_TRIP_FRICTION_BPS}bps round-trip.",
        "",
        f"**Family rollup:** {rollup_text}",
        "",
        "## Calibration / application calendar split",
        "",
        f"- Calibration half: {len(calibration_days)} days "
        f"({summary['calendar_split']['calibration_days_first']}..{summary['calendar_split']['calibration_days_last']})",
        f"- Application half: {len(application_days)} days "
        f"({summary['calendar_split']['application_days_first']}..{summary['calendar_split']['application_days_last']})",
        "- Beta (`beta_spy`, `beta_sector`) is estimated ONCE, using ONLY calibration-half 1-min bars. ALL "
        "Family 4 candidate events (all 3 definitions) are restricted to the application half only.",
        "",
        "## Beta estimation -- fail-closed summary",
        "",
        f"- Minimum paired 1-min return observations required: **{MIN_PAIRED_OBS_FOR_BETA}** "
        "(~2 trading days of continuous 1-min bars at this dataset's ~900 bars/session pace).",
        f"- {n_symbols_total} symbols total. Failed closed on beta_spy: **{n_fail_spy}**. "
        f"Failed closed on beta_sector: **{n_fail_sector}**. Failed closed on EITHER "
        f"(excluded from beta-adjusted analysis): **{n_fail_either}**.",
        f"- beta_spy (trustworthy symbols, n={len(beta_spy_vals)}): "
        f"median={beta_spy_vals.median():.3f}, range=[{beta_spy_vals.min():.3f}, {beta_spy_vals.max():.3f}]"
        if len(beta_spy_vals) else "- beta_spy: no trustworthy symbols.",
        f"- beta_sector (trustworthy symbols, n={len(beta_sector_vals)}): "
        f"median={beta_sector_vals.median():.3f}, range=[{beta_sector_vals.min():.3f}, {beta_sector_vals.max():.3f}]"
        if len(beta_sector_vals) else "- beta_sector: no trustworthy symbols.",
        "",
    ]

    for name, d in definitions_summary.items():
        ba = d["beta_adjusted"]
        md_lines += [
            f"## Definition: `{name}`",
            "",
            d["description"],
            "",
            f"- Dedup: group_keys={d['dedup_group_keys']}, min_gap_minutes={d['dedup_min_gap_minutes']}",
            f"- Raw events: {d['n_raw_events']} -> Deduplicated events: {d['n_dedup_events']} "
            f"(symbols={d['n_symbols']}, days={d['n_days']})",
            f"- RS tail thresholds (application-half pool, n={d['tail_info']['n_pool']}): "
            f"q_lo={d['tail_info']['q_lo']}, q_hi={d['tail_info']['q_hi']}",
            f"- Trustworthy-beta subset used for beta adjustment: {ba['n_trustworthy_events']} events, "
            f"{ba['n_symbols_trustworthy']} symbols",
            "",
            "### RAW RS (matched-control excess, before beta adjustment) -- reported, NOT the verdict basis",
            "",
            f"- Economic classification (raw): **{d['economic_classification_raw']}**",
            f"- Data sufficiency: **{d['data_sufficiency']}**",
            f"- Effect surface instability flagged: {d['effect_surface_instability']} "
            f"({d['effect_surface_instability_reason']})",
            f"- MFE median (%, at max horizon): {d['mfe_pct_median']}; MAE median (%): {d['mae_pct_median']}",
            "",
            "| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI |",
            "|---|---|---|---|---|---|---|",
        ]
        for h_label, h in d["per_horizon_raw_matched_control"].items():
            boot = h["excess_bootstrap_clustered"]
            ci = (
                f"[{boot['ci_low']:.4f}, {boot['ci_high']:.4f}]"
                if boot and not boot.get("insufficient_n") and boot.get("ci_low") is not None else "n/a"
            )
            md_lines.append(
                f"| {h_label} | {h['n_events']} | {h['n_matched_pairs']} | "
                f"{h['raw_mean_pct'] if h['raw_mean_pct'] is None else round(h['raw_mean_pct'], 4)} | "
                f"{h['matched_control_mean_pct'] if h['matched_control_mean_pct'] is None else round(h['matched_control_mean_pct'], 4)} | "
                f"{h['excess_mean_pct'] if h['excess_mean_pct'] is None else round(h['excess_mean_pct'], 4)} | {ci} |"
            )
        md_lines += [
            f"- Raw-RS verdict (informational only): **{d['verdict_raw']}** -- {d['verdict_reasoning_raw']}",
            "",
            "### BETA-ADJUSTED residual (RAW / SPY-adjusted / sector-adjusted side by side) -- THE verdict basis",
            "",
            "| Horizon | n | raw mean % [95% CI] | SPY-adjusted mean % [95% CI] | sector-adjusted mean % [95% CI] |",
            "|---|---|---|---|---|",
        ]
        for h_label, h in ba.get("per_horizon", {}).items():
            def _fmt(b):
                if not b or b.get("insufficient_n") or b.get("point_estimate") is None:
                    return "n/a"
                pe = round(b["point_estimate"], 4)
                if b.get("ci_low") is not None:
                    return f"{pe} [{round(b['ci_low'], 4)}, {round(b['ci_high'], 4)}]"
                return f"{pe}"
            md_lines.append(f"| {h_label} | {h['n']} | {_fmt(h['raw'])} | {_fmt(h['spy_adjusted'])} | {_fmt(h['sector_adjusted'])} |")
        md_lines += [
            "",
            f"- Economic classification (SPY-adjusted, 60m primary horizon): "
            f"**{ba['economic_classification_beta_adjusted']}**",
            "",
            f"### VERDICT (beta-adjusted basis): **{d['verdict']}**",
            "",
            d["verdict_reasoning"],
            "",
        ]
        if ba.get("raw_vs_adjusted_note"):
            md_lines += [f"**Note:** {ba['raw_vs_adjusted_note']}", ""]

    (OUT_DIR / "summary.md").write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[family04] wrote outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
