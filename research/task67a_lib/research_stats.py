"""
research/task67a_lib/research_stats.py
---------------------------------------
Shared, generic statistical/utility toolkit for Task 67A's broad
development-only alpha-phenomenon discovery screen (see
results/task65_piv/next_alpha_discovery_plan.md), and for any later task
that needs the same primitives.

This module deliberately generalizes patterns that were previously
hand-rolled per-script rather than reimplementing them from scratch:
  - percentile bootstrap CIs: research/scripts/task55_family_economics_diagnostic.py
    (`bootstrap_descriptive`, seeded `np.random.default_rng`, 95% quantile CI)
  - matched-control sampling / nearest-time pairing:
    research/scripts/task55_family_economics_diagnostic.py (`matched_control`)
  - MFE/MAE reconstruction and forward-horizon excursion:
    research/scripts/task58_rsi_payoff_regime_diagnostic.py
    (`excursion_and_forward`, `HORIZONS`)
  - winner-tail / symbol concentration:
    research/scripts/task58_rsi_payoff_regime_diagnostic.py (`econ`'s
    top3/top5 winner concentration) and task55's leave-one-symbol-out /
    top-winner-sensitivity checks.

Everything here is FAMILY-AGNOSTIC: no function knows about RSI, MACD,
FPRC_V1, ORPB_V1, or any of the 6 Task 67A candidate families. A later
Stage 1 script imports these and supplies its own event tables.

Determinism convention (used by every function that involves randomness):
  - every such function takes an explicit `seed: int` keyword argument
    with a documented default; it always builds a FRESH
    `numpy.random.default_rng(seed)` internally and never reads/mutates
    global numpy random state.
  - same seed + same input data + same parameters => bit-identical output,
    on any machine, any run order. This is verified by
    tests/test_task67a_research_stats.py's determinism tests (two
    independent calls with the same seed are asserted equal).

Small-N-honesty convention: any function that would normally summarize a
distribution (bootstrap, concentration) checks the sample size against a
documented minimum and returns `"insufficient_n": True` plus a plain-
language caveat instead of silently producing a falsely-precise number
from a handful of points. Callers must check this flag before trusting a
point estimate or CI.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------
# Seed convention
# ---------------------------------------------------------------------

#: Default seed used across this module's stochastic utilities whenever a
#: caller does not supply its own. Fixed, documented, never derived from
#: wall-clock time or any other non-reproducible source. Callers running
#: several independent bootstraps in the same script should pass distinct
#: explicit seeds (e.g. DEFAULT_SEED + an integer offset per family) so
#: their resamples are not accidentally correlated.
DEFAULT_SEED = 670067

#: Minimum sample size below which a bootstrap or concentration summary is
#: flagged `insufficient_n` rather than reported as if it were reliable.
MIN_N_FOR_SUMMARY = 5


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


# ---------------------------------------------------------------------
# 1. Bootstrap confidence intervals
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class BootstrapResult:
    """Result of a percentile bootstrap. `point_estimate` is the
    statistic computed on the ORIGINAL sample (not the mean of the
    resamples, which would be a slightly different, resampling-biased
    quantity)."""

    point_estimate: float | None
    ci_low: float | None
    ci_high: float | None
    n: int
    n_resamples: int
    ci_level: float
    seed: int
    method: str
    insufficient_n: bool
    caveat: str | None = None

    def as_dict(self) -> dict:
        return {
            "point_estimate": self.point_estimate,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "n": self.n,
            "n_resamples": self.n_resamples,
            "ci_level": self.ci_level,
            "seed": self.seed,
            "method": self.method,
            "insufficient_n": self.insufficient_n,
            "caveat": self.caveat,
        }


def bootstrap_ci(
    values: Sequence[float] | np.ndarray | pd.Series,
    statistic: Callable[[np.ndarray], float] = np.mean,
    *,
    n_resamples: int = 10_000,
    ci_level: float = 0.95,
    seed: int = DEFAULT_SEED,
    min_n: int = MIN_N_FOR_SUMMARY,
) -> BootstrapResult:
    """Percentile bootstrap CI for `statistic` applied to i.i.d. resamples
    of `values` (case resampling, with replacement, sample size == len(values)
    each draw). Method: draw `n_resamples` bootstrap samples, compute
    `statistic` on each, take the [(1-ci_level)/2, 1-(1-ci_level)/2]
    quantiles of that distribution as [ci_low, ci_high]. This is the same
    method Task 55's `bootstrap_descriptive` used (95% quantile CI over
    20,000 resamples of the trade-level series), generalized to any
    statistic and any CI level.

    NOT a formal proof of significance -- trades/events are frequently NOT
    independent (same-symbol clustering, overlapping holding periods), so
    this is a descriptive interval, matching Task 55's explicit caveat.
    Use `bootstrap_ci_clustered` when events should be resampled by group
    rather than individually, which is the more defensible choice whenever
    within-group dependence is plausible (e.g. multiple events from the
    same symbol/day).
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n < min_n:
        return BootstrapResult(
            point_estimate=float(statistic(arr)) if n else None,
            ci_low=None, ci_high=None, n=n, n_resamples=n_resamples,
            ci_level=ci_level, seed=seed, method="percentile_bootstrap",
            insufficient_n=True,
            caveat=f"n={n} < min_n={min_n}: CI withheld as unreliable, not reported.",
        )
    point_estimate = float(statistic(arr))
    rng = _rng(seed)
    idx = rng.integers(0, n, size=(n_resamples, n))
    resampled_stats = statistic(arr[idx], axis=1) if _is_vectorized_stat(statistic) else np.array(
        [statistic(arr[row]) for row in idx]
    )
    lo_q, hi_q = (1 - ci_level) / 2, 1 - (1 - ci_level) / 2
    ci_low, ci_high = (float(x) for x in np.quantile(resampled_stats, [lo_q, hi_q]))
    return BootstrapResult(
        point_estimate=point_estimate, ci_low=ci_low, ci_high=ci_high, n=n,
        n_resamples=n_resamples, ci_level=ci_level, seed=seed,
        method="percentile_bootstrap", insufficient_n=False,
        caveat="Descriptive only; independence across events is not verified.",
    )


def _is_vectorized_stat(statistic: Callable) -> bool:
    """np.mean/np.median/np.std accept an `axis=` kwarg and can be applied
    to the whole (n_resamples, n) matrix at once (much faster than a
    Python-level loop per resample); anything else falls back to a
    per-row loop in bootstrap_ci."""
    return statistic in (np.mean, np.median, np.std, np.sum)


def bootstrap_ci_clustered(
    values: Sequence[float] | np.ndarray | pd.Series,
    group_ids: Sequence,
    statistic: Callable[[np.ndarray], float] = np.mean,
    *,
    n_resamples: int = 10_000,
    ci_level: float = 0.95,
    seed: int = DEFAULT_SEED,
    min_groups: int = MIN_N_FOR_SUMMARY,
) -> BootstrapResult:
    """Block/cluster bootstrap: resamples whole GROUPS (e.g. all events on
    one symbol, or one clustered occurrence -- see `dedup_events` below)
    with replacement, rather than individual events, so within-group
    dependence doesn't understate the true CI width. `values` and
    `group_ids` must be the same length and row-aligned.
    """
    values_arr = np.asarray(values, dtype=float)
    groups_arr = np.asarray(group_ids)
    unique_groups = np.unique(groups_arr)
    n_groups = len(unique_groups)
    if n_groups < min_groups:
        finite = values_arr[~np.isnan(values_arr)]
        return BootstrapResult(
            point_estimate=float(statistic(finite)) if len(finite) else None,
            ci_low=None, ci_high=None, n=n_groups, n_resamples=n_resamples,
            ci_level=ci_level, seed=seed, method="clustered_percentile_bootstrap",
            insufficient_n=True,
            caveat=f"n_groups={n_groups} < min_groups={min_groups}: CI withheld.",
        )
    by_group = {g: values_arr[groups_arr == g] for g in unique_groups}
    point_estimate = float(statistic(values_arr[~np.isnan(values_arr)]))
    rng = _rng(seed)
    stats_out = np.empty(n_resamples, dtype=float)
    for b in range(n_resamples):
        sampled_groups = rng.choice(unique_groups, size=n_groups, replace=True)
        pooled = np.concatenate([by_group[g] for g in sampled_groups])
        pooled = pooled[~np.isnan(pooled)]
        stats_out[b] = statistic(pooled) if len(pooled) else np.nan
    stats_out = stats_out[~np.isnan(stats_out)]
    lo_q, hi_q = (1 - ci_level) / 2, 1 - (1 - ci_level) / 2
    ci_low, ci_high = (float(x) for x in np.quantile(stats_out, [lo_q, hi_q]))
    return BootstrapResult(
        point_estimate=point_estimate, ci_low=ci_low, ci_high=ci_high, n=n_groups,
        n_resamples=n_resamples, ci_level=ci_level, seed=seed,
        method="clustered_percentile_bootstrap", insufficient_n=False,
        caveat="Resamples whole groups (e.g. symbol or event-cluster) to respect within-group dependence.",
    )


# ---------------------------------------------------------------------
# 2. Concentration metrics
# ---------------------------------------------------------------------

def concentration_metrics(
    df: pd.DataFrame,
    value_col: str,
    symbol_col: str = "symbol",
    day_col: str | None = None,
    period_col: str | None = None,
    *,
    min_n: int = MIN_N_FOR_SUMMARY,
) -> dict:
    """Generalizes Task 58's winner-tail concentration checks
    (`positive_R_top3_concentration`, top-N winner share) and Task 55's
    leave-one-symbol-out / top-winner-sensitivity checks into one
    reusable summary.

    Reports, for the POSITIVE-valued rows of `value_col` (i.e. "how
    concentrated is the total edge in a few winners/symbols/days", which
    is what prior tasks actually cared about -- a symbol/day dominating
    the LOSSES is a different, less alarming question):
      - top1_symbol_share / top3_symbol_share: fraction of total positive
        value_col attributable to the single/top-3 highest-total symbols.
      - best_day_share (if day_col given): fraction of total positive
        value_col attributable to the single best calendar day.
      - best_period_share (if period_col given): same, for an arbitrary
        caller-supplied period label (e.g. a task/window name, a month).
      - n_symbols, n_days, n_periods: cardinality, so a caller can judge
        e.g. "top3_symbol_share is high but there were only 4 symbols
        total" context.
    A concentration metric with fewer than `min_n` positive rows is
    flagged `insufficient_n` rather than reported.
    """
    positive = df[df[value_col] > 0]
    total_positive = float(positive[value_col].sum())
    out: dict = {
        "n_rows": int(len(df)), "n_positive_rows": int(len(positive)),
        "total_positive_value": total_positive,
    }
    if len(positive) < min_n or total_positive <= 0:
        out["insufficient_n"] = True
        out["caveat"] = f"n_positive_rows={len(positive)} < min_n={min_n} or total_positive<=0: shares withheld."
        return out
    out["insufficient_n"] = False

    by_symbol = positive.groupby(symbol_col)[value_col].sum().sort_values(ascending=False)
    out["n_symbols"] = int(by_symbol.shape[0])
    out["top1_symbol"] = str(by_symbol.index[0])
    out["top1_symbol_share"] = float(by_symbol.iloc[0] / total_positive)
    out["top3_symbol_share"] = float(by_symbol.iloc[:3].sum() / total_positive)
    out["top3_symbols"] = [str(s) for s in by_symbol.index[:3]]

    if day_col is not None:
        by_day = positive.groupby(day_col)[value_col].sum().sort_values(ascending=False)
        out["n_days"] = int(by_day.shape[0])
        out["best_day"] = str(by_day.index[0])
        out["best_day_share"] = float(by_day.iloc[0] / total_positive)

    if period_col is not None:
        by_period = positive.groupby(period_col)[value_col].sum().sort_values(ascending=False)
        out["n_periods"] = int(by_period.shape[0])
        out["best_period"] = str(by_period.index[0])
        out["best_period_share"] = float(by_period.iloc[0] / total_positive)

    return out


# ---------------------------------------------------------------------
# 3. Event de-duplication / clustering
# ---------------------------------------------------------------------

def dedup_events(
    events: pd.DataFrame,
    *,
    group_keys: Sequence[str],
    time_col: str,
    min_gap_minutes: float,
    keep: str = "first",
) -> pd.DataFrame:
    """Generic clustering/de-duplication for event tables: within each
    `group_keys` group (typically ["symbol"], or ["symbol", trading-day]),
    sorts by `time_col` and merges any run of events whose consecutive gap
    is <= `min_gap_minutes` into one cluster -- a cheap, transparent stand-
    in for "this is really one signal re-firing on adjacent bars, not N
    independent occurrences" (the concern that motivated the 6-family
    discovery plan's "no single-name bar-by-bar retrigger inflating
    frequency" requirement).

    Returns a COPY of `events` with two new columns:
      - `_cluster_id`: an integer, unique within each `group_keys` group,
        shared by every event in the same cluster.
      - `_cluster_rank`: 0-based position of this event within its cluster
        in time order.
    and a boolean `_cluster_representative` column marking exactly one row
    per cluster as the representative (`keep="first"` marks the earliest
    event in the cluster; `keep="last"` the latest). Callers wanting a
    deduplicated table can filter to `_cluster_representative`; callers
    wanting the clustering itself (e.g. for `bootstrap_ci_clustered`'s
    `group_ids`) can use `_cluster_id` directly (combined with the
    group_keys, since cluster ids are only unique WITHIN a group).
    """
    if keep not in ("first", "last"):
        raise ValueError(f"keep must be 'first' or 'last', got {keep!r}")
    out = events.copy()
    out["_cluster_id"] = -1
    out["_cluster_rank"] = -1
    out["_cluster_representative"] = False

    for _, g in out.groupby(list(group_keys), sort=False):
        g = g.sort_values(time_col)
        times = pd.to_datetime(g[time_col])
        cluster_id = 0
        rank = 0
        prev_time = None
        cluster_ids = []
        ranks = []
        for t in times:
            if prev_time is not None and (t - prev_time).total_seconds() / 60.0 > min_gap_minutes:
                cluster_id += 1
                rank = 0
            cluster_ids.append(cluster_id)
            ranks.append(rank)
            rank += 1
            prev_time = t
        out.loc[g.index, "_cluster_id"] = cluster_ids
        out.loc[g.index, "_cluster_rank"] = ranks
        rep_rank = 0 if keep == "first" else -1
        for cid in set(cluster_ids):
            members = g.index[[c == cid for c in cluster_ids]]
            rep_idx = members[rep_rank]
            out.loc[rep_idx, "_cluster_representative"] = True

    return out


# ---------------------------------------------------------------------
# 4. Matched-control sampling
# ---------------------------------------------------------------------

def matched_control_sample(
    df: pd.DataFrame,
    treatment_col: str,
    treatment_label,
    control_label,
    *,
    match_keys: Sequence[str],
    time_col: str | None = None,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Generalizes Task 55's `matched_control`: splits `df` into a
    treatment group (`df[treatment_col] == treatment_label`) and a control
    group (`df[treatment_col] == control_label`), then produces:

      - `strata`: coarse-stratum common support -- for every distinct
        combination of `match_keys` present in BOTH groups, both groups'
        rows restricted to those combinations ("common_support" below).
      - `nearest_time_pairs` (only if `time_col` given): a DataFrame of
        greedy, bounded, one-to-one nearest-time-within-stratum pairs
        (same algorithm as Task 55's `matched_control`: sort all
        candidate cross pairs by |time delta|, assign greedily, no row
        reused twice), with an `abs_time_diff_minutes` column so a caller
        can judge match quality/reject pairs beyond a tolerance.
      - `common_support_counts`: how many treatment/control rows survive
        restriction to shared strata, as a sanity check the match isn't
        vacuous.

    Deterministic and seed-controlled even though this particular
    algorithm itself is not stochastic (greedy nearest-time assignment
    has no randomness) -- `seed` is accepted and stored in the output for
    interface consistency with the module's other utilities, and so a
    caller doing e.g. tie-breaking among exactly-equal time deltas via a
    supplied comparator can rely on a documented, reproducible order
    (ties are broken by original row order, which is itself deterministic
    given a deterministic input frame).
    """
    treat = df[df[treatment_col] == treatment_label]
    ctrl = df[df[treatment_col] == control_label]

    strata_rows = []
    common_support_idx_t, common_support_idx_c = [], []
    for key, group in df.groupby(list(match_keys)):
        t_rows = group[group[treatment_col] == treatment_label]
        c_rows = group[group[treatment_col] == control_label]
        if len(t_rows) and len(c_rows):
            key_tuple = key if isinstance(key, tuple) else (key,)
            strata_rows.append({
                **dict(zip(match_keys, key_tuple)),
                "treatment_n": len(t_rows), "control_n": len(c_rows),
            })
            common_support_idx_t.extend(t_rows.index.tolist())
            common_support_idx_c.extend(c_rows.index.tolist())

    strata = pd.DataFrame(strata_rows)
    common_support = {
        "treatment_rows": df.loc[common_support_idx_t] if common_support_idx_t else df.iloc[0:0],
        "control_rows": df.loc[common_support_idx_c] if common_support_idx_c else df.iloc[0:0],
    }

    pairs = pd.DataFrame()
    if time_col is not None and len(strata):
        pair_rows = []
        for key, group in df.groupby(list(match_keys)):
            t_rows = group[group[treatment_col] == treatment_label]
            c_rows = group[group[treatment_col] == control_label]
            if not len(t_rows) or not len(c_rows):
                continue
            candidates = []
            for ti, trow in t_rows.iterrows():
                for ci, crow in c_rows.iterrows():
                    dt = abs((pd.Timestamp(trow[time_col]) - pd.Timestamp(crow[time_col])).total_seconds())
                    candidates.append((dt, ti, ci))
            candidates.sort(key=lambda x: x[0])
            used_t, used_c = set(), set()
            for dt, ti, ci in candidates:
                if ti in used_t or ci in used_c:
                    continue
                used_t.add(ti)
                used_c.add(ci)
                key_tuple = key if isinstance(key, tuple) else (key,)
                pair_rows.append({
                    **dict(zip(match_keys, key_tuple)),
                    "treatment_index": ti, "control_index": ci,
                    "abs_time_diff_minutes": dt / 60.0,
                })
        pairs = pd.DataFrame(pair_rows)

    return {
        "strata": strata,
        "nearest_time_pairs": pairs,
        "common_support_counts": {
            "treatment_total": int(len(treat)), "control_total": int(len(ctrl)),
            "treatment_in_common_support": int(len(common_support_idx_t)),
            "control_in_common_support": int(len(common_support_idx_c)),
        },
        "common_support": common_support,
        "seed": seed,
    }


# ---------------------------------------------------------------------
# 5. Effect-surface analysis (broad bins, not fine grids)
# ---------------------------------------------------------------------

def effect_surface(
    df: pd.DataFrame,
    param_cols: Sequence[str],
    metric_col: str,
    *,
    n_bins: int = 3,
    min_n_per_cell: int = MIN_N_FOR_SUMMARY,
) -> pd.DataFrame:
    """Broad-binned parameter-stability surface: bins each numeric column
    in `param_cols` into `n_bins` (default 3 -- tertiles: LOW/MID/HIGH,
    deliberately coarse) quantile-based bins, then reports `metric_col`'s
    mean/median/n/std for every combination of bins actually populated.

    This exists specifically to answer the discovery plan's "stable
    parameter regions" question ("does a RANGE of reasonable parameter
    choices work, or only an isolated best-fit point... isolated optima
    are the single strongest overfitting tell") -- deliberately broad
    bins, not a fine grid search, because a fine grid invites exactly the
    isolated-optimum overfitting this check is meant to catch.

    A cell with fewer than `min_n_per_cell` rows is still reported (for
    completeness) but flagged `insufficient_n=True` in its row so a
    caller doesn't read a 2-observation cell's mean as equally reliable
    as a 200-observation cell's.
    """
    working = df.copy()
    bin_cols = []
    for col in param_cols:
        bin_col = f"_{col}_bin"
        try:
            working[bin_col] = pd.qcut(working[col], q=n_bins, duplicates="drop")
        except ValueError:
            # Too few distinct values to form n_bins quantile bins --
            # fall back to one bin per distinct value rather than raising.
            working[bin_col] = working[col].astype(str)
        bin_cols.append(bin_col)

    rows = []
    for key, group in working.groupby(bin_cols, observed=True):
        key_tuple = key if isinstance(key, tuple) else (key,)
        values = group[metric_col].dropna()
        n = len(values)
        rows.append({
            **{f"{col}_bin": str(k) for col, k in zip(param_cols, key_tuple)},
            "n": n,
            "mean": float(values.mean()) if n else None,
            "median": float(values.median()) if n else None,
            "std": float(values.std()) if n > 1 else None,
            "insufficient_n": n < min_n_per_cell,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------
# 6. Cross-family overlap
# ---------------------------------------------------------------------

def cross_family_overlap(
    events_a: pd.DataFrame,
    events_b: pd.DataFrame,
    *,
    symbol_col: str = "symbol",
    time_col: str = "timestamp",
    day_col: str | None = None,
    time_tolerance_minutes: float = 0.0,
) -> dict:
    """Compares two families' event sets (e.g. multi-hour-trend-
    continuation events vs. compression-expansion events on the same
    universe/window) for overlap, so a later comparison can tell whether
    two "structurally distinct" families are actually re-detecting the
    same underlying moves:

      - same_symbol_time_overlap: count/fraction of events_a whose
        (symbol, time) is within `time_tolerance_minutes` of some
        events_b event on the SAME symbol.
      - same_symbol_day_overlap (only if `day_col` given): count/fraction
        of events_a sharing (symbol, day) with some events_b event,
        regardless of exact time -- a coarser overlap signal for families
        whose entries are deliberately offset in time from each other
        (e.g. family 6's "later-session" entries vs. family 1's earlier
        multi-hour trigger).

    Overlap is reported directionionally from BOTH sides
    (a_covered_by_b and b_covered_by_a) since the two event sets are
    rarely the same size and "80% of A overlaps B" is a different claim
    than "80% of B overlaps A".
    """
    def _same_symbol_time(source: pd.DataFrame, other: pd.DataFrame) -> tuple[int, float]:
        if source.empty:
            return 0, 0.0
        other_by_symbol = {sym: pd.to_datetime(g[time_col]).sort_values().to_numpy() for sym, g in other.groupby(symbol_col)}
        hits = 0
        for _, row in source.iterrows():
            sym = row[symbol_col]
            if sym not in other_by_symbol:
                continue
            t = pd.Timestamp(row[time_col]).to_numpy()
            deltas_minutes = np.abs(other_by_symbol[sym] - t) / np.timedelta64(1, "m")
            if len(deltas_minutes) and deltas_minutes.min() <= time_tolerance_minutes:
                hits += 1
        return hits, (hits / len(source) if len(source) else 0.0)

    a_hits, a_frac = _same_symbol_time(events_a, events_b)
    b_hits, b_frac = _same_symbol_time(events_b, events_a)

    out = {
        "n_events_a": int(len(events_a)), "n_events_b": int(len(events_b)),
        "time_tolerance_minutes": time_tolerance_minutes,
        "a_covered_by_b_same_symbol_time": {"count": a_hits, "fraction": a_frac},
        "b_covered_by_a_same_symbol_time": {"count": b_hits, "fraction": b_frac},
    }

    if day_col is not None:
        def _same_symbol_day(source: pd.DataFrame, other: pd.DataFrame) -> tuple[int, float]:
            if source.empty:
                return 0, 0.0
            other_keys = set(zip(other[symbol_col], other[day_col]))
            hits = sum(1 for _, row in source.iterrows() if (row[symbol_col], row[day_col]) in other_keys)
            return hits, hits / len(source)

        ad_hits, ad_frac = _same_symbol_day(events_a, events_b)
        bd_hits, bd_frac = _same_symbol_day(events_b, events_a)
        out["a_covered_by_b_same_symbol_day"] = {"count": ad_hits, "fraction": ad_frac}
        out["b_covered_by_a_same_symbol_day"] = {"count": bd_hits, "fraction": bd_frac}

    return out


# ---------------------------------------------------------------------
# 7. MFE / MAE calculation
# ---------------------------------------------------------------------

def compute_mfe_mae(
    bars: pd.DataFrame,
    *,
    entry_timestamp,
    exit_timestamp,
    entry_price: float,
    risk_per_unit: float,
    direction: str = "long",
    time_col: str = "timestamp",
    high_col: str = "high",
    low_col: str = "low",
    inclusive_exit: bool = True,
) -> dict:
    """Reconstructs Maximum Favorable/Adverse Excursion from raw OHLC
    bars between entry and exit, same definition Task 58's
    `excursion_and_forward` used to cross-check its trade ledger's stored
    MFE/MAE (`mfe_price_check = max(entry_price, life.high.max())` for a
    long; MAE is the mirror using lows): the excursion boundary always
    INCLUDES the entry price itself (a trade that never moves favorably
    at all has MFE == entry, not undefined/NaN).

    `direction`: "long" or "short". For "short", favorable excursion uses
    LOWS (price moving down is favorable) and adverse uses HIGHS.

    `inclusive_exit`: whether the bar AT `exit_timestamp` itself is
    included in the excursion window (True by default; Task 58 excluded
    it only for SIGNAL_EXIT trades, on the theory the engine already
    exited on-signal before that bar's full range was tradeable -- a
    caller replicating that distinction should pass `inclusive_exit=False`
    for exactly that exit-reason case).

    Returns {mfe_price, mae_price, mfe_R, mae_R, bar_count}. `*_R` is
    None if `risk_per_unit` is 0 (unbounded/undefined R).
    """
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
    mask = (bars[time_col] >= entry_timestamp) & (
        bars[time_col] <= exit_timestamp if inclusive_exit else bars[time_col] < exit_timestamp
    )
    life = bars.loc[mask]
    if life.empty:
        raise ValueError("No bars found in [entry_timestamp, exit_timestamp] window -- cannot compute MFE/MAE.")

    if direction == "long":
        mfe_price = max(float(entry_price), float(life[high_col].max()))
        mae_price = min(float(entry_price), float(life[low_col].min()))
        mfe_move = mfe_price - entry_price
        mae_move = entry_price - mae_price
    else:
        mfe_price = min(float(entry_price), float(life[low_col].min()))
        mae_price = max(float(entry_price), float(life[high_col].max()))
        mfe_move = entry_price - mfe_price
        mae_move = mae_price - entry_price

    mfe_r = (mfe_move / risk_per_unit) if risk_per_unit else None
    mae_r = (mae_move / risk_per_unit) if risk_per_unit else None
    return {
        "mfe_price": mfe_price, "mae_price": mae_price,
        "mfe_R": mfe_r, "mae_R": mae_r, "bar_count": int(len(life)),
    }


# ---------------------------------------------------------------------
# 8. Forward-return horizon calculation
# ---------------------------------------------------------------------

def forward_return_horizons(
    bars: pd.DataFrame,
    *,
    entry_timestamp,
    entry_price: float,
    horizons_minutes: Iterable[int | None],
    session_close_timestamp=None,
    time_col: str = "timestamp",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> list[dict]:
    """Generalizes Task 58's `HORIZONS`/forward-excursion loop: for each
    horizon in `horizons_minutes` (an int number of minutes, or None
    meaning "through session close"), looks CAUSALLY forward from
    `entry_timestamp` (never past `session_close_timestamp` if supplied --
    matching Task 58's `forward_horizons_never_cross_session_close`
    invariant) and reports:
      - horizon_label: "{minutes}m" or "TO_SESSION_CLOSE"
      - bounded_end: the actual timestamp this horizon's window ends at
        (min(entry + horizon, session_close) when session_close is given)
      - bars_observed: how many bars fell in [entry, bounded_end)
      - favorable_excursion_high: max high observed (raw price, not R --
        callers wanting R should divide by their own risk_per_unit)
      - forward_close_return_pct: % return of the LAST observed bar's
        close vs. entry_price (None if zero bars observed)
      - bounded_by_session_close: True if bounded_end < entry + horizon
        (i.e. the nominal horizon was cut short by session close)
    """
    close_ts = pd.Timestamp(session_close_timestamp) if session_close_timestamp is not None else None
    entry_ts = pd.Timestamp(entry_timestamp)
    out = []
    for minutes in horizons_minutes:
        label = "TO_SESSION_CLOSE" if minutes is None else f"{minutes}m"
        raw_end = close_ts if minutes is None else entry_ts + pd.Timedelta(minutes=minutes)
        bounded_end = min(raw_end, close_ts) if close_ts is not None else raw_end
        bounded_by_close = close_ts is not None and bounded_end < raw_end
        mask = (bars[time_col] >= entry_ts) & (bars[time_col] < bounded_end)
        window = bars.loc[mask]
        n = len(window)
        forward_close_return_pct = (
            float((window[close_col].iloc[-1] - entry_price) / entry_price * 100.0) if n else None
        )
        out.append({
            "horizon_label": label,
            "horizon_minutes": minutes,
            "bounded_end": bounded_end,
            "bars_observed": int(n),
            "favorable_excursion_high": float(window[high_col].max()) if n else None,
            "adverse_excursion_low": float(window[low_col].min()) if n else None,
            "forward_close_return_pct": forward_close_return_pct,
            "bounded_by_session_close": bool(bounded_by_close),
        })
    return out
