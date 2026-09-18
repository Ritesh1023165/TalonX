"""
talonx_v2.dashboard_read -- read model for the :8787 cockpit (Phase 17)
                            and EOD reconciliation (Phase 13)
====================================================================
Physically read-only.  Assembles a V2 section for the primary cockpit:
active profile, V1 availability, V2 status, new episodes, BULLISH/BUY,
open positions with days held / remaining, SELLs, realised paper P&L.

V2 is an ACTIVE ORIGINAL PAPER strategy, NOT Experimental -- it must not
be rendered under the Experimental/Validation section.
"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from talonx_ops.operator_read import operator_snapshot, read_tables

from talonx_v2 import paper
from talonx_v2.config import V2_STATUS, V2_VERSION, V2Config
from talonx_v2.profile import StrategyProfile, active_profile
from talonx_v2.store import V2Store


def _today() -> date:
    return datetime.now().astimezone().date()


def build_section(store: V2Store, *, as_of_session: date | None = None,
                  config: V2Config | None = None) -> dict:
    cfg = config or V2Config()
    as_of = as_of_session or _today()
    prof = active_profile()
    operator = operator_snapshot(store.path)
    tables = read_tables(store.path, ("trades", "processed_episodes"))
    trades = tables["trades"] or []
    closed = operator["positions"]["CLOSED"]
    realized = round(sum(float(p["realized_pnl_usd"] or 0.0) for p in closed), 2)
    wins = [p for p in closed if (p["realized_pnl_usd"] or 0) > 0]

    reader = SimpleNamespace(open_positions=lambda: operator["positions"]["OPEN"])
    open_report = paper.open_position_report(reader, as_of)
    return {
        "panel": "ACTIVE STRATEGY (Original flow)",
        "not_experimental": True,
        "active_profile": prof.value,
        "v1_baseline_available": True,
        "v1_selectable": True,
        "v2_selectable": True,
        "v2_strategy": V2_VERSION,
        "v2_status": V2_STATUS,
        "v2_is_active_profile": prof is StrategyProfile.INSIDER_BUY_CLUSTER_V2,
        "config": {
            "cluster_window_trading_days": cfg.cluster_window_trading_days,
            "min_distinct_owners": cfg.min_distinct_owners,
            "hold_trading_days": cfg.hold_trading_days,
            "max_concurrent_positions": cfg.max_concurrent_positions,
            "reentry_cooldown_trading_days": cfg.reentry_cooldown_trading_days,
            "liquidity_min_median_dollar_volume": cfg.liquidity_min_median_dollar_volume,
            "liquidity_min_close": cfg.liquidity_min_close,
        },
        "episodes_processed": sum(len(rows) for rows in operator["positions"].values()) + sum(
            r["disposition"].startswith("SKIPPED") for r in tables["processed_episodes"] or []),
        "open_positions": open_report,
        "n_open": len(open_report),
        "unresolved_positions": operator["positions"]["EXIT_UNRESOLVED"],
        "occupied_capacity": operator["account"]["capacity_used"],
        "operator": operator,
        "buys": [t for t in trades if t["action"] == "BUY"],
        "sells": [t for t in trades if t["action"] == "SELL"],
        "realized_pnl_usd": realized,
        "closed_positions": len(closed),
        "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        "cash": operator["account"]["settled_cash"],
        "paper_only": True,
        "real_capital": False,
    }


def eod_view(store: V2Store, *, as_of_session: date | None = None) -> dict:
    """EOD reconciliation (Phase 13): V2 positions are NOT flattened.
    Report every open position with expected exit / days held / remaining."""
    as_of = as_of_session or _today()
    operator = operator_snapshot(store.path)
    reader = SimpleNamespace(open_positions=lambda: operator["positions"]["OPEN"])
    rows = paper.open_position_report(reader, as_of)
    return {
        "as_of_session": as_of.isoformat(),
        "v2_positions_flattened_at_eod": False,
        "open_v2_positions": rows,
        "n_open": len(rows),
        "exit_unresolved": operator["positions"]["EXIT_UNRESOLVED"],
        "obligation_slots": operator["account"]["obligation_slots"],
        "overdue": [r for r in rows if r["overdue"]],
    }
