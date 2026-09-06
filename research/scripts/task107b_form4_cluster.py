"""
task107b_form4_cluster.py  --  TASK 107B  Form 4 cluster offline falsification
=============================================================================
Evaluate whether causally observable episodes of >= 2 distinct insiders
making open-market (code P) purchases in the same issuer within 10 trading
days predict positive long-side returns at +5D / +10D / +15D.

FROZEN SPECIFICATION  (see results/task107b_form4_cluster/preregistration.md;
this docstring + the constants below ARE the pre-registration and are
committed before any return is computed).

  episode set      _build/episodes_w10_mo2.parquet   (w=10 trading days,
                   >=2 distinct owner_cik, code P, greedy non-overlapping)
  entry            OPEN of entry_session (first session strictly after the
                   knowable date = max FILING_DATE of the qualifying filings)
  exit             CLOSE at +5 / +10 / +15 sessions   (primary horizon +10D;
                   +5 and +15 co-reported; +20 diagnostic)
  price sources    task95g _daily (survivorship-correct S&P panel)  UNION
                   task107a _prices (Alpaca SIP adjustment=all, broad fetch)
  populations      P1 BROAD   = every episode priced on entry & +horizon
                   P2 IN-PANEL = issuer in the task95g survivorship panel
  returns          raw = close[+k]/open[entry] - 1
                   spy_excess = raw - SPY return over the same sessions
  costs            0 / 10 / 20(PRIMARY) / 30 / 50 bps round-trip, minus raw
  discovery/holdout  chronological, cutoff 2023-07-01 (frozen)
  dependence       episode = unit; issuer-block bootstrap 5000 +
                   calendar-week clustered-mean CI
  concentration    remove top 1/3/5 episodes by net contribution; remove
                   top issuer by count; contribution by year & issuer
  sensitivity      min_owners=3; agg_value >= 50k/250k/1m; any_officer;
                   any_director; any_ten_pct   (ALL cells reported;
                   a surprise subgroup is NEW_HYPOTHESIS_ONLY, not V2)

NO technical filter (AVWAP/RSI/breakout/RVOL/MA/gap) is in the primary
hypothesis.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
A_OUT = ROOT / "results" / "task107a_form4_feasibility"
BUILD = A_OUT / "_build"
PANEL = ROOT / "results" / "task95g_broad_cross_sectional" / "_daily"
PRICES = A_OUT / "_prices"
OUT = ROOT / "results" / "task107b_form4_cluster"
OUT.mkdir(parents=True, exist_ok=True)

HORIZONS = (5, 10, 15, 20)
PRIMARY_H = 10
COSTS_BPS = (0, 10, 20, 30, 50)
PRIMARY_COST = 20
HOLDOUT_CUTOFF = "2023-07-01"
N_BOOT = 5000
RNG_SEED = 107


# --------------------------------------------------------------------------
# frozen helper functions (unit-tested in tests/test_task107_form4_cluster.py)
# --------------------------------------------------------------------------
def apply_cost(gross: pd.Series, bps: int) -> pd.Series:
    """Round-trip cost in basis points, subtracted from a gross return."""
    return gross - bps / 10_000.0


def split_discovery_holdout(ep: pd.DataFrame, cutoff: str = HOLDOUT_CUTOFF):
    c = pd.Timestamp(cutoff)
    disc = ep[ep.entry_session < c].copy()
    hold = ep[ep.entry_session >= c].copy()
    return disc, hold


def remove_top_k(rets: pd.Series, k: int) -> pd.Series:
    if k <= 0 or k >= len(rets):
        return rets
    drop_idx = rets.reindex(rets.abs().sort_values(ascending=False).index).index[:k]
    return rets.drop(drop_idx)


def profit_factor(rets: pd.Series) -> float:
    w = rets[rets > 0].sum()
    l = -rets[rets < 0].sum()
    return float(w / l) if l > 0 else float("inf")


def max_drawdown_equalw(rets: pd.Series) -> dict:
    """Drawdown of the ADDITIVE equal-1-unit-per-episode cumulative-return
    curve (entry-time ordered).  Additive, not compounded: episodes are
    independent equal-notional paper positions, not one reinvested account.

    Returns peak-to-trough in *position-units* and as a multiple of the
    curve's final value (total P&L in the same units)."""
    if rets.empty:
        return {"units": 0.0, "vs_total_pnl": 0.0, "total_pnl_units": 0.0}
    eq = np.cumsum(rets.values)
    peak = np.maximum.accumulate(eq)
    trough = float((eq - peak).min())
    total = float(eq[-1])
    return {
        "units": trough,
        "total_pnl_units": total,
        "vs_total_pnl": float(trough / total) if total != 0 else float("nan"),
    }


# --------------------------------------------------------------------------
# price loading
# --------------------------------------------------------------------------
def _load_days(sym: str) -> pd.DataFrame | None:
    for base in (PANEL, PRICES):
        f = base / f"{sym}.csv"
        if f.exists() and f.stat().st_size > 20:
            try:
                d = pd.read_csv(f)
            except Exception:  # noqa: BLE001
                continue
            if "date" not in d.columns or d.empty:
                continue
            d["date"] = pd.to_datetime(d["date"]).dt.normalize()
            return d.sort_values("date").reset_index(drop=True)
    return None


def build_returns(ep: pd.DataFrame) -> pd.DataFrame:
    spy = _load_days("SPY")
    if spy is None:
        raise SystemExit("SPY bars missing -- fetch SPY first")
    spy = spy.set_index("date")
    spy_close = spy["close"]

    rows = []
    cache: dict[str, pd.DataFrame | None] = {}
    for r in ep.itertuples(index=False):
        sym = r.issuer_sym
        if sym not in cache:
            d0 = _load_days(sym)
            cache[sym] = d0.set_index("date") if d0 is not None else None
        di = cache[sym]
        if di is None:
            continue
        entry = pd.Timestamp(r.entry_session)
        if entry not in di.index:
            continue
        k0 = di.index.get_loc(entry)
        if not isinstance(k0, (int, np.integer)):
            continue
        k0 = int(k0)
        o = di.iloc[k0]["open"]
        if not (o > 0):
            continue
        rec = dict(issuer_sym=sym, entry_session=entry,
                   n_distinct_owners=r.n_distinct_owners, agg_value=r.agg_value,
                   any_officer=r.any_officer, any_director=r.any_director,
                   any_ten_pct=r.any_ten_pct)
        # spy index position
        spos = spy_close.index.searchsorted(entry)
        for h in HORIZONS:
            if k0 + h < len(di):
                c = di.iloc[k0 + h]["close"]
                rec[f"raw_{h}"] = c / o - 1.0
                # path metrics over the hold
                seg = di.iloc[k0:k0 + h + 1]
                rec[f"mfe_{h}"] = seg["high"].max() / o - 1.0
                rec[f"mae_{h}"] = seg["low"].min() / o - 1.0
                if spos + h < len(spy_close):
                    sr = spy_close.iloc[spos + h] / spy_close.iloc[spos] - 1.0
                    rec[f"spyx_{h}"] = rec[f"raw_{h}"] - sr
        rows.append(rec)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# metric block
# --------------------------------------------------------------------------
def metrics(rets: pd.Series) -> dict:
    rets = rets.dropna()
    n = len(rets)
    if n == 0:
        return {}
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    return dict(
        n=n,
        mean=float(rets.mean()),
        median=float(rets.median()),
        trimmed_mean=float(rets.sort_values().iloc[int(n * 0.1):n - int(n * 0.1)].mean()),
        win_rate=float((rets > 0).mean()),
        avg_winner=float(wins.mean()) if len(wins) else 0.0,
        avg_loser=float(losses.mean()) if len(losses) else 0.0,
        profit_factor=profit_factor(rets),
        expectancy=float(rets.mean()),
        max_drawdown=max_drawdown_equalw(rets),
        p05=float(rets.quantile(0.05)),
        p01=float(rets.quantile(0.01)),
        worst=float(rets.min()),
    )


def issuer_block_boot(df: pd.DataFrame, col: str, n_boot: int = N_BOOT) -> tuple[float, float]:
    rng = np.random.default_rng(RNG_SEED)
    g = df.groupby("issuer_sym")[col].apply(lambda s: s.dropna().values)
    issuers = list(g.index)
    pools = [g[i] for i in issuers]
    means = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, len(issuers), len(issuers))
        vals = np.concatenate([pools[p] for p in pick]) if len(pick) else np.array([])
        means[b] = vals.mean() if len(vals) else np.nan
    return float(np.nanpercentile(means, 2.5)), float(np.nanpercentile(means, 97.5))


def week_cluster_ci(entry_session: pd.Series, values: pd.Series) -> tuple[float, float]:
    d = pd.DataFrame({"e": pd.to_datetime(entry_session).values,
                      "v": pd.to_numeric(values, errors="coerce").values}).dropna()
    if d.empty:
        return float("nan"), float("nan")
    d["wk"] = d["e"].dt.to_period("W")
    wk = d.groupby("wk")["v"].mean()
    m = float(wk.mean())
    se = float(wk.std(ddof=1) / np.sqrt(len(wk))) if len(wk) > 1 else float("nan")
    return m - 1.96 * se, m + 1.96 * se


# --------------------------------------------------------------------------
def evaluate(df: pd.DataFrame, label: str) -> dict:
    df = df.sort_values("entry_session").reset_index(drop=True)
    res: dict = {"label": label, "n": len(df)}
    disc, hold = split_discovery_holdout(df)
    for h in HORIZONS:
        raw = df.get(f"raw_{h}")
        if raw is None:
            continue
        hd: dict = {}
        for c in COSTS_BPS:
            net = apply_cost(df[f"raw_{h}"], c)
            hd[f"net_{c}bps"] = metrics(net)
        hd["spy_excess"] = metrics(df[f"spyx_{h}"]) if f"spyx_{h}" in df else {}
        # discovery / holdout at primary cost
        hd["discovery_net20"] = metrics(apply_cost(disc[f"raw_{h}"], PRIMARY_COST)) if len(disc) else {}
        hd["holdout_net20"] = metrics(apply_cost(hold[f"raw_{h}"], PRIMARY_COST)) if len(hold) else {}
        # dependence-aware CI on net@20
        net20 = apply_cost(df[f"raw_{h}"], PRIMARY_COST)
        tmp = df.assign(_net=net20)
        hd["boot_ci_net20"] = issuer_block_boot(tmp, "_net")
        hd["weekcluster_ci_net20"] = week_cluster_ci(df["entry_session"], net20)
        # concentration
        conc = {}
        for k in (1, 3, 5):
            conc[f"drop_top{k}_mean_net20"] = float(remove_top_k(net20.dropna(), k).mean())
        by_iss = tmp.groupby("issuer_sym")["_net"].agg(["count", "sum"]).sort_values("sum", ascending=False)
        top_iss = by_iss.index[0]
        conc["top_issuer"] = str(top_iss)
        conc["drop_top_issuer_mean_net20"] = float(tmp.loc[tmp.issuer_sym != top_iss, "_net"].mean())
        conc["max_issuer_share_of_positive_sum"] = float(
            by_iss["sum"].clip(lower=0).iloc[0] / by_iss["sum"].clip(lower=0).sum()
        ) if by_iss["sum"].clip(lower=0).sum() > 0 else None
        conc["by_year_mean_net20"] = {
            int(y): float(v) for y, v in tmp.assign(y=tmp.entry_session.dt.year)
            .groupby("y")["_net"].mean().items()
        }
        hd["concentration"] = conc
        res[f"h{h}"] = hd
    return res


def sensitivity(df: pd.DataFrame) -> dict:
    out = {}
    cells = {
        "min_owners_ge3": df[df.n_distinct_owners >= 3],
        "value_ge_50k": df[df.agg_value >= 50_000],
        "value_ge_250k": df[df.agg_value >= 250_000],
        "value_ge_1m": df[df.agg_value >= 1_000_000],
        "any_officer": df[df.any_officer],
        "any_director": df[df.any_director],
        "any_ten_pct": df[df.any_ten_pct],
    }
    for name, sub in cells.items():
        if len(sub) < 30:
            out[name] = {"n": len(sub), "note": "n<30 -- not assessed"}
            continue
        d = {"n": len(sub)}
        for h in HORIZONS:
            if f"raw_{h}" in sub:
                net = apply_cost(sub[f"raw_{h}"], PRIMARY_COST)
                dd, hh = split_discovery_holdout(sub)
                d[f"h{h}"] = {
                    "mean_net20": float(net.mean()),
                    "pf": profit_factor(net.dropna()),
                    "win_rate": float((net > 0).mean()),
                    "discovery_mean_net20": float(apply_cost(dd[f"raw_{h}"], PRIMARY_COST).mean()) if len(dd) else None,
                    "holdout_mean_net20": float(apply_cost(hh[f"raw_{h}"], PRIMARY_COST).mean()) if len(hh) else None,
                }
        out[name] = d
    return out


def main():
    ep = pd.read_parquet(BUILD / "episodes_w10_mo2.parquet")
    ep["entry_session"] = pd.to_datetime(ep["entry_session"])
    ep = ep[ep.entry_session.notna()].copy()

    rr = build_returns(ep)
    rr.to_parquet(OUT / "episode_returns.parquet", index=False)
    n_priced = rr[f"raw_{PRIMARY_H}"].notna().sum() if f"raw_{PRIMARY_H}" in rr else 0
    print(f"episodes: {len(ep)}  priced @ entry: {len(rr)}  with +{PRIMARY_H}D close: {n_priced}")

    P1 = rr[rr[f"raw_{PRIMARY_H}"].notna()].copy()
    panel_syms = {f.stem.upper() for f in PANEL.glob("*.csv")}
    P2 = P1[P1.issuer_sym.isin(panel_syms)].copy()

    report = {
        "spec": {
            "episode_set": "episodes_w10_mo2", "entry": "entry_session open",
            "horizons": HORIZONS, "primary_h": PRIMARY_H, "costs_bps": COSTS_BPS,
            "primary_cost": PRIMARY_COST, "holdout_cutoff": HOLDOUT_CUTOFF,
            "n_boot": N_BOOT, "seed": RNG_SEED,
        },
        "coverage": {
            "episodes_total": int(len(ep)),
            "priced_at_entry": int(len(rr)),
            "P1_broad_n": int(len(P1)),
            "P2_in_panel_n": int(len(P2)),
        },
        "P1_broad": evaluate(P1, "P1_broad"),
        "P2_in_panel": evaluate(P2, "P2_in_panel"),
        "sensitivity_P1": sensitivity(P1),
        "sensitivity_P2": sensitivity(P2),
    }
    (OUT / "analysis.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report["P1_broad"].get(f"h{PRIMARY_H}", {}), indent=2, default=str)[:2000])
    print("\nwrote", OUT / "analysis.json")


if __name__ == "__main__":
    main()
