"""
Research alert state machine, dedup and rendering.

Identity: ``<session_date>:<SYMBOL>:<family>`` with family GAP_UP | GAP_DOWN -- one candidate per
symbol + session + setup family. Transitions that produce an alert:

  (none)  -> WATCH | BULLISH_SETUP | BEARISH_SETUP     NEW (subject to the per-session new-alert cap)
  WATCH   -> BULLISH_SETUP | BEARISH_SETUP             upgrade
  same state, score/gap moved materially and >= 30 min since the last alert   MATERIAL_UPDATE
  active  -> INVALIDATED  (gap faded below 1%, flipped sign, or price went stale)

Everything else (an unchanged re-scan, a SETUP->WATCH downgrade) produces NO alert -- the same
unchanged alert is never sent twice. Every alert is a RESEARCH alert: it is never a V2
TRADE_EVENT and never starts paper execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig
from talonx_premarket.scoring import BEARISH_SETUP, BULLISH_SETUP, WATCH

INVALIDATED = "INVALIDATED"
MATERIAL_UPDATE = "MATERIAL_UPDATE"
ACTIVE_STATES = (WATCH, BULLISH_SETUP, BEARISH_SETUP)
RESEARCH_FOOTER = "Research alert only. Not a V2 trade event. Paper execution not started."


def family_of(gap_pct: float) -> str:
    return "GAP_UP" if gap_pct > 0 else "GAP_DOWN"


def candidate_id(session_date: str, symbol: str, family: str) -> str:
    return f"{session_date}:{symbol.upper()}:{family}"


@dataclass(frozen=True)
class Observation:
    """One scan's view of a symbol that is at least WATCH-classified, or an invalidation signal."""
    symbol: str
    classification: str          # WATCH | BULLISH_SETUP | BEARISH_SETUP | SCORED | REJECTED:<reason>
    gap_pct: float | None
    score: float | None
    last_price: float | None
    prev_close: float | None


@dataclass(frozen=True)
class AlertDecision:
    candidate_id: str
    symbol: str
    alert_type: str              # WATCH | BULLISH_SETUP | BEARISH_SETUP | MATERIAL_UPDATE | INVALIDATED
    new_state: str
    reason: str
    suppressed: str = ""         # "" or e.g. SESSION_NEW_ALERT_CAP


def decide(prev: dict | None, obs: Observation, *, session_date: str, now: datetime, new_alerts_so_far: int,
           cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> AlertDecision | None:
    """``prev`` is the stored candidate row for obs' identity (or None). Pure function."""
    cls = obs.classification
    if prev is None:
        if cls not in ACTIVE_STATES or obs.gap_pct is None:
            return None
        cid = candidate_id(session_date, obs.symbol, family_of(obs.gap_pct))
        if new_alerts_so_far >= cfg.max_new_alerts_per_session:
            return AlertDecision(cid, obs.symbol, cls, cls, "new candidate", suppressed="SESSION_NEW_ALERT_CAP")
        return AlertDecision(cid, obs.symbol, cls, cls, "new candidate")
    cid, state = prev["candidate_id"], prev["state"]
    if state == INVALIDATED:
        return None                                   # an invalidated identity stays closed for the session
    fam = prev["family"]
    faded = obs.gap_pct is None or abs(obs.gap_pct) < cfg.invalidate_abs_gap_below_pct
    flipped = obs.gap_pct is not None and family_of(obs.gap_pct) != fam and abs(obs.gap_pct) >= cfg.invalidate_abs_gap_below_pct
    stale = cls.startswith("REJECTED:STALE") or cls.startswith("REJECTED:NO_PREMARKET")
    if faded or flipped or stale:
        why = "gap faded below %.1f%%" % cfg.invalidate_abs_gap_below_pct if faded else (
            "gap flipped direction" if flipped else "price went stale")
        return AlertDecision(cid, obs.symbol, INVALIDATED, INVALIDATED, why)
    if cls in (BULLISH_SETUP, BEARISH_SETUP) and state == WATCH:
        return AlertDecision(cid, obs.symbol, cls, cls, "upgraded from WATCH")
    if cls in ACTIVE_STATES and obs.score is not None and prev.get("last_alert_utc"):
        since = (now - datetime.fromisoformat(prev["last_alert_utc"])).total_seconds()
        moved = (abs(obs.score - (prev["last_alert_score"] or 0)) >= cfg.material_update_score_delta
                 or abs(obs.gap_pct - (prev["last_alert_gap"] or 0)) >= cfg.material_update_gap_delta_pct)
        if moved and since >= cfg.material_update_min_interval_s:
            keep = state if cls == WATCH and state != WATCH else cls
            return AlertDecision(cid, obs.symbol, MATERIAL_UPDATE, keep, "score/gap moved materially")
    return None


def render(alert_type: str, *, symbol: str, name: str, feats: dict | None, score: dict | None, catalyst: str,
           phase: str, data_as_of_utc: str, reason: str, inside_v2_scope: bool) -> str:
    head = f"[PREMARKET RESEARCH] {symbol} — {alert_type}"
    lines = [head + (f" ({name[:40]})" if name else "")]
    if feats:
        lines += [
            f"Gap: {feats['gap_pct']:+.2f}% (pre-market last {feats['last_price']:.4g} vs previous close "
            f"{feats['prev_close']:.4g})",
            f"Premarket volume: {feats['pm_volume']:,.0f} sh (${feats['pm_dollars']:,.0f}), "
            f"{feats['activity_adv_fraction'] * 100:.1f}% of 20d ADV",
            f"Previous close: {feats['prev_close']:.4g} · prev range {feats['prev_low']:.4g}-{feats['prev_high']:.4g} · "
            f"{feats['range_position'].replace('_', ' ').lower()}",
        ]
    lines.append(f"Catalyst: {catalyst}")
    if score:
        lines.append(f"Score: {score['total']:.1f}/100 (gap {score['gap']:.1f}, activity {score['activity']:.1f}, "
                     f"liquidity {score['liquidity']:.1f}, catalyst {score['catalyst']:.1f}, "
                     f"structure {score['structure']:.1f}, data {score['data_confidence']:.1f})")
    lines.append(f"Why: {reason}")
    lines.append(f"Data: Alpaca SIP 1-min, 15-min delayed, as of {data_as_of_utc[11:16]} UTC · {phase}"
                 + (" · in V2 39-name scope" if inside_v2_scope else " · outside V2 scope"))
    lines.append(RESEARCH_FOOTER)
    return "\n".join(lines)
