"""ERM nominee validation -- DESCRIPTIVE diagnostics (never gating). r9 §5-§6.

FROZEN definitions (reused, not re-implemented):
  * missing-exit bounds and the ex-suspect sensitivity: research/event_response_map_v1/metrics.cell_metrics
    (sha256 fd876a17...69dd), on the directional (SHORT) sector-relative GROSS return;
  * SUSPECT_ADJUSTMENT flag: research/event_response_map_v1/events.outcomes (sha256 701abda1...019c).
PROPOSED deterministic conventions (r9 §6; pending owner approval D6 -- never frozen before):
  unit book, cumulative unit P&L, maximum drawdown, concurrency, worst event, stock-leg MAE and break-even borrow,
  exactly as implemented below.
"""
from __future__ import annotations

from datetime import date

import numpy as np


def frozen_cell_diagnostics(obs) -> dict:
    """Frozen cell_metrics on the H10 rows (incl. missing-exit rows): bounds, ex-suspect, per-year, top-k (GROSS)."""
    from research.event_response_map_v1 import metrics as M
    m = M.cell_metrics(obs, "SHORT", "L1")
    keep = ("n", "n_missing_exit", "missing_exit_rate", "missing_exit_bounds", "suspect_adjustment_n",
            "sensitivity_mean_sector_relative_ex_suspect", "per_year", "mean_raw", "mean_spy_relative",
            "mean_sector_relative", "median_sector_relative", "hit_rate", "dispersion_sd")
    return {k: m.get(k) for k in keep}


def unit_book(events: list[dict], sessions: list[date], stock_cost: float, etf_cost: float) -> dict:
    """events: valid events only, each {'entry','exit' (dates), 'stock': {date: (open, high, close)},
    'etf': {date: (open, close)}} on ALL bars. Convention (PROPOSED):
      - leg notional 1 unit each at the entry OPEN; marks at each session close from entry to exit inclusive;
      - a session is marked only when BOTH legs have a close; the change since the last common mark is recognised then
        (first mark is relative to the entry opens);
      - pair change = -(S_t - S_prev)/S_entry_open + (E_t - E_prev)/E_entry_open  (units; sums to pair_gross);
      - the full round-trip cost (stock + ETF) is booked on the exit session;
      - missing-exit and dropped events are not in the book (they are counted elsewhere).
    Returns per-session P&L, cumulative P&L (from 0, not compounded), max drawdown (units), concurrency stats."""
    idx = {d: i for i, d in enumerate(sessions)}
    pnl = np.zeros(len(sessions))
    open_n = np.zeros(len(sessions), dtype=int)
    for ev in events:
        s_open, e_open = ev["stock"][ev["entry"]][0], ev["etf"][ev["entry"]][0]
        s_prev, e_prev = s_open, e_open
        i0, i1 = idx[ev["entry"]], idx[ev["exit"]]
        open_n[i0: i1 + 1] += 1
        for i in range(i0, i1 + 1):
            d = sessions[i]
            if d in ev["stock"] and d in ev["etf"]:
                s_c, e_c = ev["stock"][d][2], ev["etf"][d][1]
                pnl[i] += -(s_c - s_prev) / s_open + (e_c - e_prev) / e_open
                s_prev, e_prev = s_c, e_c
        pnl[i1] -= stock_cost + etf_cost
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    dd = float(np.max(peak - cum)) if len(cum) else 0.0
    active = [i for i in range(len(sessions)) if open_n[i] > 0]
    span = open_n[min(active): max(active) + 1] if active else np.array([], dtype=int)
    return {"unit": "1 unit = entry notional of one leg; P&L in units, not compounded, no capital base",
            "cumulative_pnl_units": float(cum[-1]) if len(cum) else 0.0, "max_drawdown_units": dd,
            "concurrency": {"mean": float(span.mean()) if len(span) else 0.0,
                            "median": float(np.median(span)) if len(span) else 0.0,
                            "max": int(span.max()) if len(span) else 0,
                            "sessions_counted": int(len(span))},
            "daily_pnl_units": pnl.tolist()}


def worst_and_mae(events: list[dict], pair_net: dict) -> dict:
    """Worst event = min pair_net (primary costs). Stock-leg MAE against the short, per event =
    max over sessions entry..exit with a stock bar of (high_t / open_entry - 1) (ALL bars). Percentiles: numpy
    'linear' interpolation (the numpy default) over valid events."""
    mae = []
    for ev in events:
        o = ev["stock"][ev["entry"]][0]
        hs = [v[1] for d, v in ev["stock"].items() if ev["entry"] <= d <= ev["exit"]]
        mae.append(max(h / o - 1 for h in hs))
    vals = list(pair_net.values())
    return {"worst_event_pair_net": float(min(vals)) if vals else None,
            "stock_leg_mae_p95": float(np.percentile(mae, 95, method="linear")) if mae else None,
            "stock_leg_mae_p99": float(np.percentile(mae, 99, method="linear")) if mae else None}


def break_even_borrow(pair_net: list[float], entry_exit: list[tuple[date, date]]) -> dict:
    """mean(pair_net) / mean(calendar_days_held / 360); calendar_days_held = (exit date - entry date).days per valid
    event (ACT/360). A value <= 0 means no borrow headroom. Annualised simple rate."""
    if not pair_net:
        return {"break_even_borrow_annual": None}
    days = np.array([(b - a).days for a, b in entry_exit], dtype=float)
    return {"break_even_borrow_annual": float(np.mean(pair_net) / np.mean(days / 360.0)),
            "mean_calendar_days_held": float(days.mean()), "day_count": "ACT/360"}
