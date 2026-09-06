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
    disp = store.episode_disposition(ep.episode_id)
    if disp in ("ENTERED",) or store.position_for_episode(ep.episode_id) is not None:
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

    outcome = paper.enter_position(
        store, decision, entry_price=float(px["open"]),
        entry_session=ep.eligible_entry_session, config=cfg,
        source_meta={"issuer_cik": ep.issuer_cik, "episode": ep.to_dict(),
                     "research_source": "Task107B", "frozen_contract": V2_FROZEN_CONTRACT},
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


def settle_due_exits(
    *,
    store: V2Store,
    as_of_session: date,
    price_lookup: PriceLookup,
    config: V2Config | None = None,
    router=None,
    result: ProcessResult | None = None,
) -> ProcessResult:
    cfg = config or V2Config()
    res = result or ProcessResult()
    for pos in paper.due_exits(store, as_of_session):
        exit_session = _d(pos["target_exit_session"])
        px = price_lookup(pos["symbol"], exit_session)
        if not px or not px.get("close"):
            # target day missing data -> hold; retry next tick (Phase 12)
            res.skipped.append({"episode_id": pos["episode_id"], "symbol": pos["symbol"],
                                "reason": "EXIT_BAR_MISSING_HOLD"})
            continue
        out = paper.close_position(store, pos, exit_price=float(px["close"]),
                                   exit_session=exit_session, config=cfg)
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
    return res
