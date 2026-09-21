"""
talonx_v2.pipeline -- the V2 lane orchestrator (Quant -> Brain -> paper)
====================================================================
I/O-agnostic: callers inject ``bars_lookup(symbol) -> list[{date,close,volume}]``
and ``price_lookup(symbol, session_date) -> {'open':float,'close':float} | None``.
The same pipeline drives offline replay, the Task 111 E2E fixture, and a
live poll loop.

Flow per episode:
  detect_episodes -> (idempotency check) -> liquidity gate -> V2QuantSignal
  -> V2Decision (Brain) -> BUY (Original paper engine math) at entry-session
  open -> persist. Separately, on each session tick, close any position due
  at its +10-trading-day exit at that session's close.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from talonx_v2 import brain_bridge, dispatch_bridge, paper, quant_bridge
from talonx_v2 import calendar as v2cal
from talonx_v2.cluster_engine import ClusterEpisode, PurchaseRecord, detect_episodes
from talonx_v2.config import V2_FROZEN_CONTRACT, V2Config
from talonx_v2.liquidity import evaluate_liquidity
from talonx_v2.schemas import V2Action
from talonx_v2.store import V2Store

BarsLookup = Callable[[str], list[dict]]
PriceLookup = Callable[[str, date], dict | None]


@dataclass
class ProcessResult:
    episodes_detected: int = 0
    signals_built: int = 0
    entries: list[dict] = field(default_factory=list)
    exits: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _field_provenance(px: dict, field: str) -> dict | None:
    """Copy adapter provenance and bind it to the exact consumed field.

    Legacy/injected lookups may not carry provenance; keep those rows NULL
    rather than inventing an adapter identity.
    """
    raw = px.get("_provenance") if isinstance(px, dict) else None
    if not isinstance(raw, dict):
        return None
    return {**raw, "field": field}


def process_episode(
    ep: ClusterEpisode,
    *,
    store: V2Store,
    bars_lookup: BarsLookup,
    price_lookup: PriceLookup,
    config: V2Config | None = None,
    router=None,
    result: ProcessResult | None = None,
) -> ProcessResult:
    cfg = config or V2Config()
    res = result or ProcessResult()

    # --- idempotency (restart / replay / duplicate filing safe) ---
    # A prior SKIPPED_ENTRY_STALE is terminal: a stale episode never becomes
    # un-stale, so it must not be re-processed into an entry on a later tick.
    disp = store.episode_disposition(ep.episode_id)
    if disp in ("ENTERED", "SKIPPED_ENTRY_STALE") \
            or store.position_for_episode(ep.episode_id) is not None:
        res.skipped.append({"episode_id": ep.episode_id, "reason": "ALREADY_PROCESSED"})
        return res

    # --- liquidity gate (causal: only bars strictly before entry session) ---
    bars = bars_lookup(ep.symbol) or []
    liq = evaluate_liquidity(bars, entry_session=ep.eligible_entry_session, config=cfg)

    sig = quant_bridge.build_signal(ep, liq, config=cfg)
    res.signals_built += 1

    decision = brain_bridge.contextualize(sig)

    if decision.action is not V2Action.BUY:
        store.record_disposition(
            episode_id=ep.episode_id, symbol=ep.symbol,
            disposition=f"SKIPPED_{liq.reason if not liq.ok else 'NON_BUY'}",
            issuer_cik=ep.issuer_cik,
            eligible_entry_session=ep.eligible_entry_session.isoformat(),
            detail=decision.rationale[:200],
        )
        res.skipped.append({"episode_id": ep.episode_id, "symbol": ep.symbol,
                            "reason": liq.reason if not liq.ok else "NON_BUY"})
        return res

    # --- entry at the eligible-entry-session OPEN ---
    px = price_lookup(ep.symbol, ep.eligible_entry_session)
    if not px or not px.get("open"):
        store.record_disposition(
            episode_id=ep.episode_id, symbol=ep.symbol, disposition="SKIPPED_NO_ENTRY_BAR",
            issuer_cik=ep.issuer_cik,
            eligible_entry_session=ep.eligible_entry_session.isoformat(),
        )
        res.skipped.append({"episode_id": ep.episode_id, "symbol": ep.symbol,
                            "reason": "NO_ENTRY_BAR"})
        return res

    liquidity_sources = []
    for bar in bars:
        p = bar.get("_provenance") if isinstance(bar, dict) else None
        if isinstance(p, dict) and p not in liquidity_sources:
            liquidity_sources.append(p)
    entry_provenance = _field_provenance(px, "open")
    outcome = paper.enter_position(
        store, decision, entry_price=float(px["open"]),
        entry_session=ep.eligible_entry_session, config=cfg,
        source_meta={"issuer_cik": ep.issuer_cik, "episode": ep.to_dict(),
                     "research_source": "Task107B", "frozen_contract": V2_FROZEN_CONTRACT,
                     "liquidity_price_provenance": liquidity_sources},
        price_provenance=entry_provenance,
    )
    if not outcome.entered:
        res.skipped.append({"episode_id": ep.episode_id, "symbol": ep.symbol,
                            "reason": outcome.reason})
        return res

    alert = dispatch_bridge.build_alert(
        decision, entry_session=ep.eligible_entry_session,
        target_exit_session=outcome.target_exit_session,
    )
    routing = None
    if router is not None:
        routing = dispatch_bridge.route(router, alert)
    res.entries.append({
        "episode_id": ep.episode_id, "symbol": ep.symbol,
        "entry_session": ep.eligible_entry_session.isoformat(),
        "entry_price": float(px["open"]), "shares": outcome.shares,
        "target_exit_session": outcome.target_exit_session.isoformat(),
    })
    res.alerts.append({"action": "BUY", "symbol": ep.symbol,
                       "telegram": dispatch_bridge.render_telegram(alert),
                       "routing": routing.to_dict() if routing else None})
    return res


def _basis_of(px: dict | None) -> date | None:
    """``basis_as_of`` of the price row actually consumed (None = unknown)."""
    raw = px.get("_provenance") if isinstance(px, dict) else None
    v = raw.get("basis_as_of") if isinstance(raw, dict) else None
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def sweep_corporate_actions(*, store: V2Store, as_of: date, guard) -> list[dict]:
    """PQ-2A: observe/apply explicit corporate-action evidence for every OPEN
    position (idempotent; original entry rows untouched).  This is NOT a
    settlement -- it only keeps the append-only trail current so marks,
    reconciliation and the operator view are correct DURING the hold.  A
    failure for one position never blocks another."""
    out: list[dict] = []
    if guard is None:
        return out
    for pos in store.open_positions():
        try:
            v = guard.assess_position(store, pos, as_of=as_of, settlement=False)
            out.append({"symbol": pos["symbol"], "episode_id": pos["episode_id"],
                        "status": v.status, "code": v.code, "detail": v.detail,
                        "applied": list(v.applied)})
        except Exception as exc:  # noqa: BLE001 -- never abort the tick
            out.append({"symbol": pos["symbol"], "episode_id": pos["episode_id"],
                        "status": "ERROR", "code": type(exc).__name__, "detail": str(exc)[:200],
                        "applied": []})
    return out


def settle_due_exits(
    *,
    store: V2Store,
    as_of_session: date,
    price_lookup: PriceLookup,
    config: V2Config | None = None,
    router=None,
    result: ProcessResult | None = None,
    corporate_actions=None,
) -> ProcessResult:
    """``corporate_actions``: a ``talonx_v2.corporate_actions.CorporateActionGuard``.
    ``None`` keeps the pre-PQ-2A behaviour and is for REPLAY/TEST callers only;
    the live companion always passes a guard (``run.py`` refuses to start live
    without one)."""
    cfg = config or V2Config()
    res = result or ProcessResult()
    ff_max = cfg.exit_fallforward_max_sessions
    for pos in paper.due_exits(store, as_of_session):
        target_session = _d(pos["target_exit_session"])
        as_of = _d(as_of_session)

        # FROZEN exit = close of the +10th trading session.  The ONLY
        # adjustment permitted is a DATA-AVAILABILITY fall-forward: if that
        # exact session's bar is missing, take the FIRST available close in
        # the next `ff_max` sessions.  Never backwards.  Never "best price".
        exit_session = target_session
        px = price_lookup(pos["symbol"], target_session)
        if not px or not px.get("close"):
            for k in range(1, ff_max + 1):
                nxt = v2cal.add_sessions(target_session, k)
                if nxt > as_of:
                    break                       # that session hasn't happened yet
                cand = price_lookup(pos["symbol"], nxt)
                if cand and cand.get("close"):
                    px, exit_session = cand, nxt
                    break

        if not px or not px.get("close"):
            last_ff = v2cal.add_sessions(target_session, ff_max)
            if as_of >= last_ff:
                # all `ff_max` fall-forward sessions have passed with no bar
                # -> EXPLICIT unresolved state.  Not a silent hold: the
                # position is flagged, surfaced, and no longer retried.
                store.mark_exit_unresolved(
                    pos["position_id"],
                    detail=f"no bar for {pos['symbol']} on {target_session.isoformat()} "
                           f"or the next {ff_max} sessions (through {last_ff.isoformat()})")
                res.skipped.append({"episode_id": pos["episode_id"], "symbol": pos["symbol"],
                                    "reason": "EXIT_UNRESOLVED"})
            else:
                # still inside the fall-forward window -> hold, retry next tick
                res.skipped.append({"episode_id": pos["episode_id"], "symbol": pos["symbol"],
                                    "reason": "EXIT_BAR_PENDING_FALLFORWARD"})
            continue
        exit_provenance = _field_provenance(px, "close")
        if corporate_actions is not None:
            # PQ-2A: authoritative corporate-action assessment IMMEDIATELY before
            # settlement (also applies any split not yet on the trail).  Never
            # fabricates shares/price/basis/P&L: HOLD retries inside the existing
            # +5 window; BLOCK / window exhaustion -> the existing EXIT_UNRESOLVED.
            verdict = corporate_actions.assess_position(
                store, pos, as_of=as_of, exit_basis_as_of=_basis_of(px), exit_session=exit_session,
                settlement=True)
            if not verdict.settle_ok:
                last_ff = v2cal.add_sessions(target_session, ff_max)
                if verdict.status == "BLOCK" or as_of >= last_ff:
                    store.mark_exit_unresolved(
                        pos["position_id"],
                        detail=f"CORPORATE_ACTION {verdict.text()} (target exit "
                               f"{target_session.isoformat()})")
                    res.skipped.append({"episode_id": pos["episode_id"], "symbol": pos["symbol"],
                                        "reason": "EXIT_UNRESOLVED", "corporate_action": verdict.code})
                else:
                    res.skipped.append({"episode_id": pos["episode_id"], "symbol": pos["symbol"],
                                        "reason": "EXIT_HOLD_CORPORATE_ACTION", "corporate_action": verdict.code})
                continue
        out = paper.close_position(store, pos, exit_price=float(px["close"]),
                                   exit_session=exit_session, config=cfg,
                                   price_provenance=exit_provenance)
        if not out.settled and out.blocked_reason:
            # defense in depth: a recorded corporate-action block refused settlement
            store.mark_exit_unresolved(pos["position_id"],
                                       detail=f"CORPORATE_ACTION {out.blocked_reason}")
            res.skipped.append({"episode_id": pos["episode_id"], "symbol": pos["symbol"],
                                "reason": "EXIT_UNRESOLVED", "corporate_action": "TRAIL_BLOCK"})
            continue
        if not out.settled:
            # Package 1 Settlement Integrity: the position was already
            # not OPEN by the time this call's own transaction ran (a
            # duplicate/stale-snapshot close attempt) -- no economic
            # mutation occurred, so no exit record and no notification
            # are generated for it either. `due_exits()` only lists
            # OPEN positions, so this is a defensive no-op under normal
            # single-threaded operation; it matters if this function is
            # ever invoked twice concurrently over an overlapping list.
            res.skipped.append({"episode_id": pos["episode_id"], "symbol": pos["symbol"],
                                "reason": "ALREADY_SETTLED"})
            continue
        from talonx_v2.schemas import V2Decision, V2Direction
        d = V2Decision(signal_id=f"v2sig-{pos['episode_id']}", episode_id=pos["episode_id"],
                       symbol=pos["symbol"], direction=V2Direction.BULLISH,
                       action=V2Action.SELL, official_eligible=True,
                       rationale="+10 trading-day exit", eligible_entry_session=_d(pos["entry_session"]))
        alert = dispatch_bridge.build_alert(d, realized={
            "entry_price": pos["entry_price"], "exit_price": float(px["close"]),
            "realized_pnl_pct": out.realized_pnl_pct, "trading_days_held": out.trading_days_held,
        })
        routing = dispatch_bridge.route(router, alert) if router is not None else None
        res.exits.append({
            "episode_id": pos["episode_id"], "symbol": pos["symbol"],
            "exit_session": exit_session.isoformat(), "exit_price": float(px["close"]),
            "realized_pnl_usd": out.realized_pnl_usd, "realized_pnl_pct": out.realized_pnl_pct,
            "trading_days_held": out.trading_days_held,
        })
        res.alerts.append({"action": "SELL", "symbol": pos["symbol"],
                           "telegram": dispatch_bridge.render_telegram(alert),
                           "routing": routing.to_dict() if routing else None})
    return res


def run_replay(
    records: list[PurchaseRecord],
    *,
    store: V2Store,
    bars_lookup: BarsLookup,
    price_lookup: PriceLookup,
    config: V2Config | None = None,
    router=None,
) -> ProcessResult:
    """Deterministic offline replay: detect all episodes, process each in
    entry-session order, settling due exits as the timeline advances."""
    cfg = config or V2Config()
    res = ProcessResult()
    episodes = detect_episodes(records, config=cfg)
    res.episodes_detected = len(episodes)
    timeline: list[tuple[date, str, ClusterEpisode | None]] = []
    for ep in episodes:
        timeline.append((ep.eligible_entry_session, "ENTRY", ep))
    # exit checks at each distinct entry session + each episode's target exit
    exit_days = sorted({e.eligible_entry_session for e in episodes} |
                       {v2cal.add_sessions(e.eligible_entry_session, cfg.hold_trading_days)
                        for e in episodes})
    for d0 in exit_days:
        timeline.append((d0, "SETTLE", None))
    timeline.sort(key=lambda t: (t[0], 0 if t[1] == "SETTLE" else 1))
    for d0, kind, ep in timeline:
        if kind == "SETTLE":
            settle_due_exits(store=store, as_of_session=d0, price_lookup=price_lookup,
                             config=cfg, router=router, result=res)
        else:
            process_episode(ep, store=store, bars_lookup=bars_lookup,
                            price_lookup=price_lookup, config=cfg, router=router, result=res)
    # final catch-all pass -- settle anything still open at the last modelled session
    if exit_days:
        last = v2cal.add_sessions(exit_days[-1], cfg.hold_trading_days + 6)
        settle_due_exits(store=store, as_of_session=last, price_lookup=price_lookup,
                         config=cfg, router=router, result=res)
    return res
