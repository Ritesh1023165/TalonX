"""
talonx_v2.dispatch_bridge -- V2 official alert rendering + routing (Phase 16)
=========================================================================
V2 uses the ONE official external path.  Experimental Telegram stays
structurally blocked (unchanged).  This module:

  * renders the alert card (Telegram legacy-Markdown, Task 99H escaping
    via ``talonx_dispatch.formatter.escape_markdown``)
  * asks ``talonx_ops.official_dispatch.OfficialExternalRouter`` whether
    the ``insider_buy_cluster_v2`` family may send + whether this
    episode was already delivered (dedup)

It does NOT itself open a network socket -- the actual send is the
existing official transport's job, and offline / replay runs never send.
Wording is factual: no "guaranteed profit", no "validated real-money
alpha", no "insider knows the stock will rise".
"""
from __future__ import annotations

from datetime import date

from talonx_dispatch.formatter import escape_markdown
from talonx_v2.config import V2_STATUS, V2_VERSION
from talonx_v2.schemas import V2Action, V2Alert, V2Decision

FAMILY = "insider_buy_cluster_v2"

_ACTION_EMOJI = {V2Action.BUY: "🟢", V2Action.SELL: "🔴", V2Action.HOLD: "⚪"}


def build_alert(
    decision: V2Decision,
    *,
    entry_session: date | None = None,
    target_exit_session: date | None = None,
    realized: dict | None = None,
) -> V2Alert:
    if decision.action is V2Action.BUY:
        headline = f"INSIDER BUY CLUSTER — BULLISH / BUY — {decision.symbol}"
        body = (
            f"{decision.rationale}\n"
            f"Planned exit: {target_exit_session.isoformat() if target_exit_session else 'entry + 10 trading days'}.\n"
            f"Paper only. Strategy {V2_VERSION} — status {V2_STATUS}."
        )
    elif decision.action is V2Action.SELL:
        r = realized or {}
        headline = f"INSIDER BUY CLUSTER — SELL / EXIT — {decision.symbol}"
        body = (
            f"Closing the {decision.symbol} paper long at the +10 trading-day exit.\n"
            f"Entry {r.get('entry_price')} → exit {r.get('exit_price')}  "
            f"({r.get('realized_pnl_pct', 0.0):+.2f}%, held {r.get('trading_days_held')} sessions).\n"
            f"Paper only. Strategy {V2_VERSION}."
        )
    else:
        headline = f"INSIDER BUY CLUSTER — informational — {decision.symbol}"
        body = decision.rationale

    return V2Alert(
        episode_id=decision.episode_id,
        symbol=decision.symbol,
        action=decision.action,
        direction=decision.direction,
        strategy_version=V2_VERSION,
        status=V2_STATUS,
        headline=headline,
        body=body,
        entry_session=entry_session,
        target_exit_session=target_exit_session,
        paper_only=True,
    )


def render_telegram(alert: V2Alert) -> str:
    """Legacy-Markdown card.  Every dynamic segment is escaped (Task 99H)."""
    emoji = _ACTION_EMOJI.get(alert.action, "⚪")
    lines = [
        f"{emoji} *{escape_markdown(alert.action.value)}* — "
        f"*{escape_markdown(alert.symbol)}*  ⚡ INSIDER BUY CLUSTER",
        "—" * 12,
        escape_markdown(alert.body),
        "",
        escape_markdown(f"[{alert.strategy_version} · {alert.status} · PAPER ONLY]"),
    ]
    return "\n".join(lines)


def route(router, alert: V2Alert):
    """``router`` = talonx_ops.official_dispatch.OfficialExternalRouter.
    Returns its RoutingDecision.  V2 is an OFFICIAL family; dedup key is
    the episode id + action so a BUY and its later SELL are distinct."""
    return router.decide(FAMILY, f"{alert.episode_id}:{alert.action.value}")
