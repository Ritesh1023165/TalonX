"""
talonx_v2.paper -- V2 paper lifecycle (Phases 10-15)
==================================================
Reuses the Original paper engine's PURE math (``talonx_paper.engine``:
``calculate_buy`` / ``calculate_sell_pnl``).  No broker, no network, no
real capital.  Separate ledger (``v2_lane.db``) so V1 and V2 positions
are always attributable apart.

Lifecycle
---------
BUY   at the open of the eligible entry session (first NYSE session
      strictly after the cluster fired), IF: episode not already
      processed, symbol flat, < max concurrent, not in re-entry cooldown,
      cash available.
HOLD  across days -- persisted, restart-safe, NOT flattened at EOD.
SELL  at the close of the entry session + 10 trading days.
COOLDOWN  no new V2 position in that issuer until exit_session + 5
      trading days.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from talonx_paper.engine import calculate_buy, calculate_sell_pnl
from talonx_v2 import calendar as v2cal
from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Action, V2Decision
from talonx_v2.store import V2Store


@dataclass(frozen=True)
class EntryOutcome:
    entered: bool
    reason: str
    position_id: int | None = None
    shares: float | None = None
    target_exit_session: date | None = None


@dataclass(frozen=True)
class ExitOutcome:
    symbol: str
    episode_id: str
    exit_session: date
    exit_price: float
    realized_pnl_usd: float
    realized_pnl_pct: float
    trading_days_held: int


def _as_date(d) -> date:
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


def enter_position(
    store: V2Store,
    decision: V2Decision,
    *,
    entry_price: float,
    entry_session: date,
    config: V2Config | None = None,
    source_meta: dict | None = None,
) -> EntryOutcome:
    cfg = config or V2Config()
    cfg.validate_frozen()

    if decision.action is not V2Action.BUY:
        return EntryOutcome(False, f"DECISION_NOT_BUY:{decision.action.value}")

    # --- idempotency / restart safety: one logical cluster = one BUY ---
    if store.position_for_episode(decision.episode_id) is not None:
        return EntryOutcome(False, "EPISODE_ALREADY_HAS_POSITION")
    disp = store.episode_disposition(decision.episode_id)
    if disp == "ENTERED":
        return EntryOutcome(False, "EPISODE_ALREADY_ENTERED")

    sym = decision.symbol.upper()
    es = _as_date(entry_session)

    def _skip(reason: str) -> EntryOutcome:
        store.record_disposition(
            episode_id=decision.episode_id, symbol=sym, disposition=f"SKIPPED_{reason}",
            eligible_entry_session=es.isoformat(),
        )
        return EntryOutcome(False, reason)

    if store.position_for_symbol(sym) is not None:
        return _skip("SYMBOL_ALREADY_OPEN")

    cd = store.cooldown_until(sym)
    if cd is not None and es < cd:
        return _skip(f"IN_COOLDOWN_UNTIL_{cd.isoformat()}")

    if store.n_open() >= cfg.max_concurrent_positions:
        return _skip(f"MAX_CONCURRENT_{cfg.max_concurrent_positions}")

    if entry_price is None or entry_price <= 0:
        return _skip("BAD_ENTRY_PRICE")

    cash = store.cash()
    buy = calculate_buy(cash, cfg.per_position_allocation_usd, entry_price)
    if buy is None:
        return _skip("NO_CASH")
    shares, cost = buy

    target_exit = v2cal.add_sessions(es, cfg.hold_trading_days)

    pos_id = store.insert_open_position(
        episode_id=decision.episode_id, symbol=sym, issuer_cik=source_meta.get("issuer_cik", "") if source_meta else "",
        entry_session=es, target_exit_session=target_exit,
        entry_price=entry_price, shares=shares, position_cost=cost,
        source_meta=source_meta or {},
    )
    store.set_cash(cash - cost)
    store.append_trade(
        episode_id=decision.episode_id, symbol=sym, action="BUY",
        execution_price=entry_price, shares=shares, position_cost=cost,
        portfolio_cash_after=cash - cost,
    )
    store.record_disposition(
        episode_id=decision.episode_id, symbol=sym, disposition="ENTERED",
        issuer_cik=source_meta.get("issuer_cik", "") if source_meta else "",
        eligible_entry_session=es.isoformat(),
        detail=f"pos={pos_id} shares={shares:.4f} target_exit={target_exit.isoformat()}",
    )
    return EntryOutcome(True, "ENTERED", pos_id, shares, target_exit)


def due_exits(store: V2Store, as_of_session: date) -> list[dict]:
    """Open positions whose target exit session is <= as_of_session."""
    a = _as_date(as_of_session)
    return [p for p in store.open_positions()
            if _as_date(p["target_exit_session"]) <= a]


def close_position(
    store: V2Store,
    position: dict,
    *,
    exit_price: float,
    exit_session: date,
    config: V2Config | None = None,
) -> ExitOutcome:
    cfg = config or V2Config()
    es = _as_date(exit_session)
    entry_price = float(position["entry_price"])
    shares = float(position["shares"])
    pnl_usd, pnl_pct = calculate_sell_pnl(shares, entry_price, exit_price)
    held = v2cal.trading_days_elapsed(_as_date(position["entry_session"]), es)

    store.close_position(
        position_id=position["position_id"], exit_session=es, exit_price=exit_price,
        realized_pnl_usd=pnl_usd, realized_pnl_pct=pnl_pct, trading_days_held=held,
    )
    proceeds = shares * exit_price
    cash_after = store.cash() + proceeds
    store.set_cash(cash_after)
    store.append_trade(
        episode_id=position["episode_id"], symbol=position["symbol"], action="SELL",
        execution_price=exit_price, shares=shares, position_cost=float(position["position_cost"]),
        portfolio_cash_after=cash_after, entry_price=entry_price,
        realized_pnl_usd=pnl_usd, realized_pnl_pct=pnl_pct, trading_days_held=held,
    )
    cooldown_until = v2cal.add_sessions(es, cfg.reentry_cooldown_trading_days)
    store.set_cooldown(position["symbol"], cooldown_until)
    return ExitOutcome(position["symbol"], position["episode_id"], es, exit_price,
                       pnl_usd, pnl_pct, held)


def open_position_report(store: V2Store, as_of_session: date) -> list[dict]:
    """EOD / dashboard view: open V2 positions with days held / remaining
    (Phase 13/17).  Positions are NOT flattened here."""
    a = _as_date(as_of_session)
    out = []
    for p in store.open_positions():
        entry = _as_date(p["entry_session"])
        target = _as_date(p["target_exit_session"])
        held = v2cal.trading_days_elapsed(entry, a)
        remaining = max(0, v2cal.sessions_between(a, target))
        out.append({
            "symbol": p["symbol"], "episode_id": p["episode_id"],
            "entry_session": entry.isoformat(), "target_exit_session": target.isoformat(),
            "entry_price": p["entry_price"], "shares": p["shares"],
            "trading_days_held": held, "trading_days_remaining": remaining,
            "overdue": a > target,
        })
    return out


def recover(store: V2Store, as_of_session: date | None = None) -> dict:
    """Restart recovery (Phase 15): the DB is the source of truth; this
    just summarises what a restarted process picks back up."""
    opens = store.open_positions()
    summary = {
        "open_positions": len(opens),
        "symbols": [p["symbol"] for p in opens],
        "overdue_exits": [],
    }
    if as_of_session is not None:
        summary["overdue_exits"] = [
            p["symbol"] for p in due_exits(store, as_of_session)
        ]
    return summary
