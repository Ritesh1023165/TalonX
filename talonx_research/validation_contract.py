"""
Reusable validation contract (Task 115.B).

Given a per-trade / per-episode return frame with the frozen Task 107B
schema, produce the full metrics block: performance, cost sensitivity
(0/5/10/20/30/50 bps), discovery/holdout, robustness (top-1/3 removal,
issuer & time concentration), dependence-aware CIs, and a benchmark
(SPY-excess) block.

Reuses the FROZEN, unit-tested helpers in
research/scripts/task107b_form4_cluster.py -- it does not reimplement any
statistic.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_t107b(data_root: Path | None = None):
    """Load the frozen Task 107B eval helpers, optionally repointing its
    PANEL / PRICES / BUILD constants at another worktree's data dir."""
    spec = importlib.util.spec_from_file_location(
        "t107b_eval", _ROOT / "research" / "scripts" / "task107b_form4_cluster.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if data_root is not None:
        dr = Path(data_root)
        m.ROOT = dr
        m.A_OUT = dr / "results" / "task107a_form4_feasibility"
        m.BUILD = m.A_OUT / "_build"
        m.PANEL = dr / "results" / "task95g_broad_cross_sectional" / "_daily"
        m.PRICES = m.A_OUT / "_prices"
    return m


# 5-bps and 10-bps cells are added on top of the frozen 0/10/20/30/50 grid.
_COST_GRID = (0, 5, 10, 20, 30, 50)
_PRIMARY = 20


@dataclass
class ValidationMetrics:
    horizon: int
    primary_cost_bps: int
    n_trades: int
    raw: dict[str, Any] = field(default_factory=dict)         # full frozen evaluate() block
    cost_sensitivity: dict[int, dict] = field(default_factory=dict)
    discovery: dict = field(default_factory=dict)
    holdout: dict = field(default_factory=dict)
    concentration: dict = field(default_factory=dict)
    dependence: dict = field(default_factory=dict)
    benchmark: dict = field(default_factory=dict)
    monthly: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["cost_sensitivity"] = {str(k): v for k, v in self.cost_sensitivity.items()}
        return d


def evaluate_returns(df: pd.DataFrame, *, label: str, horizon: int = 10,
                     primary_cost_bps: int = _PRIMARY,
                     holdout_cutoff: str | None = None,
                     data_root: Path | None = None) -> ValidationMetrics:
    """df schema (frozen Task 107B): issuer_sym, entry_session, raw_<h>,
    spyx_<h>, n_distinct_owners, agg_value, any_officer/director/ten_pct.

    ``holdout_cutoff`` (ISO date): chronological discovery/holdout split
    within *this* frame.  When None, the frozen Task 107B 2023-07-01 cut
    is used (only meaningful when the frame spans it)."""
    t = _load_t107b(data_root)
    df = df.dropna(subset=[f"raw_{horizon}"]).sort_values("entry_session").reset_index(drop=True)
    full = t.evaluate(df, label)
    hblock = full.get(f"h{horizon}", {})

    cost_sens: dict[int, dict] = {}
    for c in _COST_GRID:
        net = t.apply_cost(df[f"raw_{horizon}"], c)
        cost_sens[c] = t.metrics(net)

    if holdout_cutoff:
        cut = pd.Timestamp(holdout_cutoff)
        e = pd.to_datetime(df["entry_session"])
        disc, hold = df[e < cut].copy(), df[e >= cut].copy()
    else:
        disc, hold = t.split_discovery_holdout(df)
    m = ValidationMetrics(
        horizon=horizon, primary_cost_bps=primary_cost_bps, n_trades=len(df),
        raw=hblock, cost_sensitivity=cost_sens,
        discovery=t.metrics(t.apply_cost(disc[f"raw_{horizon}"], primary_cost_bps)) if len(disc) else {},
        holdout=t.metrics(t.apply_cost(hold[f"raw_{horizon}"], primary_cost_bps)) if len(hold) else {},
        concentration=hblock.get("concentration", {}),
        dependence={"issuer_block_ci_net20": hblock.get("boot_ci_net20"),
                    "week_cluster_ci_net20": hblock.get("weekcluster_ci_net20")},
        benchmark=hblock.get("spy_excess", {}),
    )
    # monthly / quarterly / yearly on net@primary
    net = t.apply_cost(df[f"raw_{horizon}"], primary_cost_bps)
    tmp = df.assign(_net=net.values, _m=pd.to_datetime(df["entry_session"]))
    by_month = (tmp.groupby(tmp["_m"].dt.to_period("M"))["_net"]
                .agg(["count", "mean", "sum"]).reset_index())
    m.monthly = [{"period": str(r["_m"]), "trades": int(r["count"]),
                  "mean_net": float(r["mean"]), "sum_net": float(r["sum"])}
                 for _, r in by_month.iterrows()]
    return m


def yearly_quarterly(df: pd.DataFrame, *, horizon: int = 10, primary_cost_bps: int = _PRIMARY,
                     data_root: Path | None = None) -> dict[str, Any]:
    t = _load_t107b(data_root)
    df = df.dropna(subset=[f"raw_{horizon}"]).copy()
    net = t.apply_cost(df[f"raw_{horizon}"], primary_cost_bps)
    tmp = df.assign(_net=net.values, _e=pd.to_datetime(df["entry_session"]))
    out: dict[str, Any] = {}
    for name, key in (("yearly", tmp["_e"].dt.year),
                      ("quarterly", tmp["_e"].dt.to_period("Q").astype(str))):
        g = tmp.groupby(key)["_net"].agg(["count", "mean", "sum"])
        out[name] = {str(k): {"trades": int(v["count"]), "mean_net": float(v["mean"]),
                              "sum_net": float(v["sum"])} for k, v in g.iterrows()}
    return out
