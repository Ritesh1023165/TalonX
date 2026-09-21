"""
talonx_v2.paper -- V2 paper lifecycle (Phases 10-15)
==================================================
No broker, no network, no real capital.  Separate ledger
(``v2_lane.db``) so V1 and V2 positions are always attributable apart.

Package 4: sizing/P&L math is V2's OWN (``talonx_v2.sizing`` --
whole-share, fee-inclusive), no longer Original's shared
``talonx_paper.engine.calculate_buy``/``calculate_sell_pnl`` (which
remain unmodified, still used by Original's own, separate,
fractional-share accounting).

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

from talonx_v2 import calendar as v2cal
from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Action, V2Decision
from talonx_v2.sizing import compute_exit_economics, size_whole_shares_fee_inclusive, zero_fee
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
    # Package 1 Settlement Integrity: True iff THIS call performed the
    # OPEN->CLOSED transition (state mutated, cash credited, trade
    # appended, cooldown set). False means the position was already not
    # OPEN (e.g. a duplicate/stale-snapshot close attempt) -- no
    # economic mutation occurred and the caller must not treat this as a
    # new exit (no alert, no res.exits entry).
    settled: bool = True
    # PQ-2A: non-None when settlement was REFUSED because a corporate-action
    # block is recorded for the position (no cash/trade/cooldown mutation).
    blocked_reason: str | None = None
    # PQ-2A: the quantity actually settled (post-corporate-action economic shares).
    exit_shares: float | None = None


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
    price_provenance: dict | None = None,
    fee_fn=None,
) -> EntryOutcome:
    """``fee_fn``: optional ``(quantity, price) -> float`` cost model,
    passed straight through to ``sizing.size_whole_shares_fee_inclusive``.
    Defaults to ``sizing.zero_fee`` -- the current, frozen, approved
    cost assumption (S10-22/OPS-014 remain unresolved; this default is
    NOT an invented realistic fee, and is deliberately NOT added as a
    ``V2Config`` field, to avoid any risk to the frozen-contract
    validation/release-fingerprint hash a config-schema change could
    create)."""
    cfg = config or V2Config()
    cfg.validate_frozen()

    if decision.action is not V2Action.BUY:
        return EntryOutcome(False, f"DECISION_NOT_BUY:{decision.action.value}")

    sym = decision.symbol.upper()
    es = _as_date(entry_session)

    def _skip(reason: str) -> EntryOutcome:
        store.record_disposition(
            episode_id=decision.episode_id, symbol=sym, disposition=f"SKIPPED_{reason}",
            eligible_entry_session=es.isoformat(),
        )
        return EntryOutcome(False, reason)

    # Targeted Remediation Directive 1 (concurrent admission fix): EVERY
    # admission read this function makes (idempotency, symbol-flat,
    # cooldown, capacity, cash) now runs INSIDE the SAME protected
    # transaction as the eventual write, not as separate, unprotected
    # reads beforehand. Called from V2Service._phase_open (the real
    # production/replay path), this nests transparently inside that
    # method's own OUTER store.transaction() (already holding the write
    # lock from before pipeline.process_episode even started -- see
    # service.py); called standalone (e.g. directly in a test), it
    # acquires its own BEGIN IMMEDIATE here instead. Either way, no
    # admission decision is ever made on a read taken before the write
    # lock was held.
    with store.transaction() as c:
        # --- Package 2 Durable Account Blocks: the FINAL, authoritative
        # admission gate -- evaluated against the active connection
        # inside this same protected transaction, so a block recorded by
        # a concurrent writer between an earlier in-memory check and this
        # point can never be raced past. A dashboard flag or an earlier
        # read is explicitly NOT sufficient (Package 2's own requirement)
        # -- this is the one check that actually blocks the mutation.
        from talonx_ops import account_blocks
        br = account_blocks.blocked_reason(c, store.account_id)
        if br is not None:
            return _skip(f"ACCOUNT_BLOCKED:{br}")

        # --- idempotency / restart safety: one logical cluster = one BUY ---
        if store.position_for_episode(decision.episode_id) is not None:
            return EntryOutcome(False, "EPISODE_ALREADY_HAS_POSITION")
        disp = store.episode_disposition(decision.episode_id)
        if disp == "ENTERED":
            return EntryOutcome(False, "EPISODE_ALREADY_ENTERED")

        if store.position_for_symbol(sym) is not None:
            return _skip("SYMBOL_ALREADY_OPEN")

        cd = store.cooldown_until(sym)
        if cd is not None and es < cd:
            return _skip(f"IN_COOLDOWN_UNTIL_{cd.isoformat()}")

        if store.n_open() >= cfg.max_concurrent_positions:
            return _skip(f"MAX_CONCURRENT_{cfg.max_concurrent_positions}")

        if entry_price is None or entry_price <= 0:
            return _skip("BAD_ENTRY_PRICE")

        # Package 4 P4-B: whole-share, fee-inclusive sizing against the
        # ALLOCATION cap, then a separate AVAILABLE-CASH check -- never
        # silently resized down to fit available cash (Session 10 §C's
        # own explicit distinction). AVAILABLE cash here excludes THIS
        # episode's own reservation (its intent is still 'PENDING' at
        # this exact moment, about to be consumed by this same fill)
        # but DOES exclude every OTHER still-PENDING intent's own
        # reserved allocation -- the same accounting
        # `_capacity_rejection_reason` already uses at admission time,
        # re-verified here as the final, authoritative, same-
        # transaction check (Package 2's own established principle).
        cash = store.cash()
        others_pending = [i for i in store.pending_entry_intents()
                          if i["episode_id"] != decision.episode_id]
        available_cash = cash - (cfg.per_position_allocation_usd * len(others_pending))
        sizing = size_whole_shares_fee_inclusive(
            price=entry_price, allocation_usd=cfg.per_position_allocation_usd,
            available_cash=available_cash, fee_fn=fee_fn or zero_fee,
        )
        if not sizing.ok or sizing.shares < 1:
            return _skip(f"NO_CASH:{sizing.reason}")
        shares = sizing.shares
        cost = sizing.entry_total

        target_exit = v2cal.add_sessions(es, cfg.hold_trading_days)

        # Task 131 Remediation Directive 4: the position insert, cash debit,
        # trade record, and disposition write commit TOGETHER, atomically --
        # a crash between any two of these can no longer leave a position
        # without its cash debit, a debit without a trade record, or an
        # ENTERED episode without a position row.
        pos_id = store.insert_open_position(
            episode_id=decision.episode_id, symbol=sym, issuer_cik=source_meta.get("issuer_cik", "") if source_meta else "",
            entry_session=es, target_exit_session=target_exit,
            entry_price=entry_price, shares=float(shares), position_cost=cost,
            source_meta=source_meta or {}, entry_fee=sizing.entry_fee,
            price_provenance=price_provenance,
        )
        store.set_cash(cash - cost)
        store.append_trade(
            episode_id=decision.episode_id, symbol=sym, action="BUY",
            execution_price=entry_price, shares=float(shares), position_cost=cost,
            portfolio_cash_after=cash - cost, fee=sizing.entry_fee,
            price_provenance=price_provenance,
        )
        store.record_disposition(
            episode_id=decision.episode_id, symbol=sym, disposition="ENTERED",
            issuer_cik=source_meta.get("issuer_cik", "") if source_meta else "",
            eligible_entry_session=es.isoformat(),
            detail=f"pos={pos_id} shares={shares} target_exit={target_exit.isoformat()}",
        )
    return EntryOutcome(True, "ENTERED", pos_id, float(shares), target_exit)


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
    fee_fn=None,
    price_provenance: dict | None = None,
    dividends=(),
) -> ExitOutcome:
    """``position`` supplies ONLY the lookup key (``position_id``) --
    Package 2 acceptance A5: every economic value used below (symbol,
    episode_id, entry_price, shares, position_cost, entry_session) is
    re-read fresh from the authoritative persisted row, INSIDE the same
    protected transaction as the close itself, never trusted from the
    caller-supplied dict. These fields happen to be write-once by this
    schema's own convention (never updated after ``insert_open_
    position()``), but settlement must not depend on that convention
    holding forever -- a caller passing a stale/inconsistent snapshot
    (a different overlapping caller's earlier read, a future admin
    correction tool that adjusts cost basis, a bug) must not be able to
    make settlement disagree with what is actually persisted."""
    cfg = config or V2Config()
    es = _as_date(exit_session)

    with store.transaction() as c:
        row = c.execute(
            "SELECT position_id, episode_id, symbol, entry_price, shares, position_cost, "
            "entry_session, status FROM positions WHERE position_id=?",
            (position["position_id"],),
        ).fetchone()
        if row is None:
            # the position row no longer exists at all -- structurally
            # unreachable via due_exits() (which only ever lists real
            # rows), but never fabricate an exit for a position that
            # isn't there.
            return ExitOutcome(position.get("symbol", ""), position.get("episode_id", ""), es,
                               exit_price, 0.0, 0.0, 0, settled=False)
        position_id = row["position_id"]
        episode_id = row["episode_id"]
        symbol = row["symbol"]
        entry_price = float(row["entry_price"])
        position_cost = float(row["position_cost"])
        entry_session = row["entry_session"]

        # PQ-2A: settlement quantity is the persisted ECONOMIC quantity --
        # entry shares x the exact product of APPLIED split ratios (append-only
        # trail); aggregate cost basis is unchanged by a pure split.  A recorded
        # corporate-action block (unsupported/conflicting/unknown-basis) REFUSES
        # settlement here, in the same transaction: no cash, no SELL, no P&L.
        blocked = store._blocked_action_rows_c(c, position_id)
        if blocked:
            return ExitOutcome(symbol, episode_id, es, exit_price, 0.0, 0.0, 0, settled=False,
                               blocked_reason=blocked[0]["status"] + ": " + str(blocked[0]["detail"]))
        qty_exact = store._effective_shares_exact_c(c, position_id)
        shares = float(qty_exact)
        from talonx_v2.corporate_actions import fraction_to_decimal
        qty_decimal = fraction_to_decimal(qty_exact)

        # Package 4 P4-E: exit economics derived from the AUTHORITATIVE
        # persisted `position_cost` (entry_total, fee-inclusive) --
        # never re-derived as `shares * entry_price` alone (that would
        # omit the entry fee, understating cost and overstating P&L
        # the moment a non-zero fee model is ever configured; dormant
        # today under the zero-fee default, wrong in general).
        exit_econ = compute_exit_economics(
            shares=qty_decimal, exit_price=exit_price, entry_total=position_cost,
            fee_fn=fee_fn or zero_fee,
        )
        pnl_usd, pnl_pct = exit_econ.realized_pnl_usd, exit_econ.realized_pnl_pct
        held = v2cal.trading_days_elapsed(_as_date(entry_session), es)

        # Task 131 Remediation Directive 4 + Package 1 Settlement Integrity:
        # close + cash credit + trade record + cooldown commit together,
        # atomically -- a crash mid-sequence can no longer leave a closed
        # position without its cash credit, or credited cash without a
        # trade record. store.close_position()'s own conditional UPDATE
        # (``WHERE status='OPEN'``) IS the authoritative eligibility check
        # for this transition; its return value MUST gate every subsequent
        # mutation below, or a second call against a stale snapshot (e.g.
        # two overlapping callers that both read the row while it was
        # still OPEN) would credit cash and append a SELL a second time
        # even though the state transition itself was correctly a no-op.
        transitioned = store.close_position(
            position_id=position_id, exit_session=es, exit_price=exit_price,
            realized_pnl_usd=pnl_usd, realized_pnl_pct=pnl_pct, trading_days_held=held,
            exit_fee=exit_econ.exit_fee, price_provenance=price_provenance,
        )
        if not transitioned:
            # Already CLOSED/EXIT_UNRESOLVED/otherwise not OPEN -- an
            # explicit, non-fabricating no-op. No cash, trade, or
            # cooldown mutation; the caller must not generate a second
            # exit notification from this outcome (see ``settled``).
            return ExitOutcome(symbol, episode_id, es, exit_price,
                               pnl_usd, pnl_pct, held, settled=False)
        cash_after = store.cash() + exit_econ.exit_net
        store.set_cash(cash_after)
        store.append_trade(
            episode_id=episode_id, symbol=symbol, action="SELL",
            execution_price=exit_price, shares=shares, position_cost=position_cost,
            portfolio_cash_after=cash_after, entry_price=entry_price,
            realized_pnl_usd=pnl_usd, realized_pnl_pct=pnl_pct, trading_days_held=held,
            fee=exit_econ.exit_fee, price_provenance=price_provenance,
        )
        cooldown_until = v2cal.add_sessions(es, cfg.reentry_cooldown_trading_days)
        store.set_cooldown(symbol, cooldown_until)
        # PQ-2A closure (total return): ELIGIBLE ordinary dividends are recorded as ACCRUED
        # receivables ATOMICALLY with this settlement (no cash yet -- credited later, after the
        # payable date, even though this trade is now CLOSED).  ``dividends`` were vetted by the
        # corporate-action guard; ``record_dividend_entitlement`` re-checks eligibility.
        for ev in dividends or ():
            store.record_dividend_entitlement(position_id=position_id, event=ev, exit_session=es)
    return ExitOutcome(symbol, episode_id, es, exit_price,
                       pnl_usd, pnl_pct, held, settled=True, exit_shares=shares)


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
