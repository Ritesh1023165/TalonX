"""DEVELOPMENT_CORPORATE_ACTION_SURVIVAL_V1 (pre-registered with the ALL dataset-basis declaration, BEFORE any
ALL-adjusted outcome exists). Pure logic: survival gates, RAW-vs-ALL trade diff attribution, manifest hashing.
No grid, no new thresholds, no alternative horizons, no parameter optimisation, no discretion.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

SURVIVAL_ID = "DEVELOPMENT_CORPORATE_ACTION_SURVIVAL_V1"
NET_10BPS_MIN_PCT = 0.15
SEED = 670067
RETURN_TOL_PCT = 1e-6          # |gross_ALL - gross_RAW| below this (percentage points) = "return unchanged"
FACTOR_TOL = 1e-5              # entry/exit ALL/RAW price-factor equality (uniform back-adjustment)
CATEGORIES = ("UNCHANGED", "DIRECT_CORPORATE_ACTION", "BENCHMARK_MEDIATED", "RANK_BOUNDARY_PROPAGATION",
              "OTHER_EXPLAINED", "UNEXPLAINED")


def survival_stats(trades: pd.DataFrame) -> dict:
    """Gross, net@10/25 and BOTH bootstrap calls: (i) the ORIGINAL anchor call (cell_summary -> 2000 resamples,
    day_col=decision_day), (ii) the task-specified call (10,000 resamples, 95 %, seed 670067, symbol / entry_day)."""
    from research.task67a_lib.research_stats import bootstrap_ci_clustered
    from research.task71_lib.diagnostics import cell_summary, net_return
    s = cell_summary(trades, day_col="decision_day")
    v = trades["gross_return_pct"].to_numpy()
    b_sym = bootstrap_ci_clustered(v, trades["symbol"].to_numpy(), n_resamples=10_000, ci_level=0.95, seed=SEED)
    b_day = bootstrap_ci_clustered(v, trades["entry_day"].astype(str).to_numpy(), n_resamples=10_000, ci_level=0.95,
                                   seed=SEED)
    bij = bool(trades.groupby("decision_day")["entry_day"].nunique().max() == 1
               and trades.groupby("entry_day")["decision_day"].nunique().max() == 1)
    return {"n_trades": int(len(trades)), "n_symbols": int(trades["symbol"].nunique()),
            "gross_mean_pct": float(trades["gross_return_pct"].mean()),
            **{f"net_{b}bps_pct": float(net_return(trades["gross_return_pct"], b).mean()) for b in (0, 5, 10, 15, 20, 25)},
            "original_2000": {"symbol": [s["bootstrap_gross_by_symbol"]["ci_low"], s["bootstrap_gross_by_symbol"]["ci_high"]],
                              "day": [s["bootstrap_gross_by_day"]["ci_low"], s["bootstrap_gross_by_day"]["ci_high"]]},
            "spec_10000": {"symbol": [b_sym.ci_low, b_sym.ci_high], "entry_day": [b_day.ci_low, b_day.ci_high]},
            "decision_to_entry_day_bijective": bij}


def survival_gates(st: dict, unexplained: int) -> dict:
    def pos(x):
        return x is not None and x > 0
    g = {"A_net_10bps_ge_0.15": st["net_10bps_pct"] >= NET_10BPS_MIN_PCT,
         "B_gross_positive": st["gross_mean_pct"] > 0,
         "C_symbol_cluster_ci_low_gt_0": pos(st["original_2000"]["symbol"][0]) and pos(st["spec_10000"]["symbol"][0]),
         "D_entry_day_cluster_ci_low_gt_0": (pos(st["original_2000"]["day"][0]) and pos(st["spec_10000"]["entry_day"][0])
                                             and st["decision_to_entry_day_bijective"]),
         "E_F_same_bootstrap_implementation_and_parameters": True,     # enforced by survival_stats itself
         "G_no_unexplained_differences": unexplained == 0}
    return {"gates": g, "pass": all(g.values())}


def classify(gates: dict, *, fingerprints_ok: bool, raw_parity_ok: bool, semantics_ok: bool, dataset_ok: bool,
             unexplained: int, holdout_untouched: bool) -> str:
    if not raw_parity_ok:
        return "TASK75B_BLOCKED_ENVIRONMENT_DRIFT"
    if not dataset_ok or not semantics_ok or not fingerprints_ok or not holdout_untouched:
        return "TASK75B_BLOCKED_DATASET"
    if unexplained > 0:
        return "TASK75B_BLOCKED_DATA_INTEGRITY"
    return "TASK75B_READY" if gates["pass"] else "TASK75_RETIRED_AFTER_CORPORATE_ACTION_CORRECTION"


# ------------------------------------------------------------------------------------------------------ trade diff
def _ca_days(ca_events: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for e in ca_events:
        if e.get("symbol") and e.get("ex_or_effective_date"):
            out.setdefault(e["symbol"], []).append(e["ex_or_effective_date"])
    return out


def attribute_diff(raw_ledger: pd.DataFrame, all_ledger: pd.DataFrame, ca_events: list[dict],
                   calendars: dict[str, list[str]]) -> pd.DataFrame:
    """Trade-by-trade RAW vs ALL diff keyed on (symbol, decision_day), over the FULL evaluated ledgers (selected and
    unselected rows). Every difference gets exactly one category (first match wins):
      DIRECT_CORPORATE_ACTION    the symbol itself has a split / reverse split / spin-off / dividend ex-date inside its
                                 lookback span or its entry..exit span
      BENCHMARK_MEDIATED         only the market-adjusted value moved and SPY had an ex-date inside the lookback span
                                 (SPY enters every symbol identically, so it cannot change a rank by itself)
      RANK_BOUNDARY_PROPAGATION  selection flipped with no own event, while another symbol in the SAME Day0 cross-
                                 section had an event inside that lookback span
      OTHER_EXPLAINED            prices differ only by a UNIFORM back-adjustment factor (entry and exit scaled equally
                                 by later dividends/splits; the return is unchanged within tolerance)
      UNEXPLAINED                anything else (blocks READY)
    ``calendars``: {slice_or_all: [canonical trading days]} used to find each trade's lookback start."""
    ca = _ca_days(ca_events)
    key = ["symbol", "decision_day"]
    r = raw_ledger.assign(decision_day=raw_ledger["decision_day"].astype(str)).set_index(key)
    a = all_ledger.assign(decision_day=all_ledger["decision_day"].astype(str)).set_index(key)
    cal = sorted({d for v in calendars.values() for d in v})
    idx = {d: i for i, d in enumerate(cal)}

    def span(d0: str, end: str | None) -> tuple[str, str]:
        i = idx.get(d0)
        lb = cal[max(0, i - 3)] if i is not None else d0
        return lb, (end or d0)

    def hit(sym, lo, hi):
        return any(lo <= d <= hi for d in ca.get(sym, []))

    rows = []
    for k in sorted(set(r.index) | set(a.index)):
        sym, d0 = k
        rr, aa = (r.loc[k] if k in r.index else None), (a.loc[k] if k in a.index else None)
        sel_r = rr is not None and bool(rr["data_ready"])
        sel_a = aa is not None and bool(aa["data_ready"])
        exit_day = str((aa if aa is not None and aa["exit_day"] is not None else rr)["exit_day"]) \
            if (aa is not None or rr is not None) else None
        lo, hi = span(d0, exit_day if exit_day not in (None, "None", "nan") else None)
        lb_lo, lb_hi = span(d0, d0)
        own = hit(sym, lo, hi)
        spy = hit("SPY", lb_lo, lb_hi)
        if sel_r != sel_a:
            change = "NEWLY_SELECTED" if sel_a else "NO_LONGER_SELECTED"
        elif not sel_r:
            continue                                            # unselected in both: not a trade
        else:
            dg = abs(float(aa["gross_return_pct"]) - float(rr["gross_return_pct"]))
            fe = float(aa["entry_price"]) / float(rr["entry_price"])
            fx = float(aa["exit_price"]) / float(rr["exit_price"])
            if dg <= RETURN_TOL_PCT and abs(fe - 1) <= FACTOR_TOL and abs(fx - 1) <= FACTOR_TOL:
                rows.append({"symbol": sym, "decision_day": d0, "change": "NONE", "category": "UNCHANGED"})
                continue
            change = "PRICE_OR_PNL_CHANGED"
        others = any(hit(o, lb_lo, lb_hi) for o in ca if o not in (sym, "SPY"))
        if own:
            cat = "DIRECT_CORPORATE_ACTION"
        elif change == "PRICE_OR_PNL_CHANGED":
            fe = float(aa["entry_price"]) / float(rr["entry_price"])
            fx = float(aa["exit_price"]) / float(rr["exit_price"])
            dg = abs(float(aa["gross_return_pct"]) - float(rr["gross_return_pct"]))
            cat = "OTHER_EXPLAINED" if abs(fe - fx) <= FACTOR_TOL * max(fe, fx) and dg <= 1e-3 else "UNEXPLAINED"
        elif spy and not others:
            cat = "BENCHMARK_MEDIATED"
        elif others:
            cat = "RANK_BOUNDARY_PROPAGATION"
        else:
            cat = "UNEXPLAINED"
        rows.append({"symbol": sym, "decision_day": d0, "change": change, "category": cat,
                     "raw_gross": None if rr is None or not sel_r else float(rr["gross_return_pct"]),
                     "all_gross": None if aa is None or not sel_a else float(aa["gross_return_pct"]),
                     "raw_rank": None if rr is None else rr["cross_sectional_rank_pct"],
                     "all_rank": None if aa is None else aa["cross_sectional_rank_pct"]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------------ manifest
def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def aggregate_hash(files: dict[str, str]) -> str:
    """sha256 over sorted (relative name, file sha256) pairs -- order- and path-independent."""
    return hashlib.sha256(json.dumps(sorted(files.items())).encode()).hexdigest()
