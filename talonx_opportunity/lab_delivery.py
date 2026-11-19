"""
LAB DELIVERY POLICY -- Telegram presentation + delivery routing for the Lab (RESEARCH) bot (2026-09-28).

Sits strictly AFTER the unchanged ``LAB_NOTIFY_POLICY_V1*`` decision (budget, WATCH share, later-phase reserve,
surfaced parents -- all identical, so ``decision`` / ``counted_new`` / ``surfaced`` never change). It only decides HOW a
decided event reaches Telegram:

  IMMEDIATE  one individual Lab message (as before)
  DIGEST     no individual message; counted in the next periodic Lab digest (the decision row stays fully auditable)
  None       not delivered (every non-SELECTED V1 decision, exactly as before -- one exception below)

Routing (information value to the reader, not alpha):
  HIGH    NEW BULLISH/BEARISH setup; UPGRADE to BULLISH/BEARISH                                     -> IMMEDIATE
  HIGH    INVALIDATED of a setup previously sent to Lab                                               -> IMMEDIATE
  HIGH    INVALIDATED of a candidate promoted to Signal whose SAME_DAY horizon is still open
          (event before that window's regular close) -- also when V1 said NOT_SURFACED_PARENT         -> IMMEDIATE
  MEDIUM  MATERIAL_UPDATE of a setup previously sent to Lab that EXTENDS the move beyond the |gap| the
          reader last saw for it                                                                      -> IMMEDIATE
  LOW     MATERIAL_UPDATE that fades / re-tests the move (not beyond the last shown |gap|)            -> DIGEST
  LOW     new WATCH, WATCH MATERIAL_UPDATE, INVALIDATED of a candidate never sent as a setup          -> DIGEST
Nothing here reads or changes scores, thresholds, lifecycle or Signal eligibility.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

IMMEDIATE, DIGEST = "IMMEDIATE", "DIGEST"
HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"
SETUPS = ("BULLISH", "BEARISH")

# route reasons (closed list; persisted in notification.db decisions.route_reason)
R_NEW_SETUP = "NEW_SETUP"
R_UPGRADE = "UPGRADE_TO_SETUP"
R_SETUP_INVALIDATED = "SENT_SETUP_INVALIDATED"
R_SIGNAL_INVALIDATED = "OPEN_SIGNAL_INVALIDATED"
R_SETUP_EXTENDED = "SENT_SETUP_MOVE_EXTENDED"
R_SETUP_FADE = "SETUP_UPDATE_NOT_BEYOND_LAST_SHOWN"
R_SETUP_UPDATE_UNSENT = "SETUP_UPDATE_NEVER_SENT_AS_SETUP"
R_NEW_WATCH = "NEW_WATCH"
R_WATCH_UPDATE = "WATCH_UPDATE"
R_INVALIDATED_UNSENT = "INVALIDATED_NEVER_SENT_AS_SETUP"
R_OTHER = "OTHER_LOW_INFO"


@dataclass(frozen=True)
class LabDeliveryPolicy:
    version: str = "LAB_DELIVERY_POLICY_V1"
    digest_interval_s: int = 1800                  # digests are built only at 30-min UTC bucket boundaries
    digest_min_events: int = 5                     # ... and only once >= 5 held events are pending
    digest_max_hold_s: int = 7200                  # ... or the oldest pending one has waited >= 2 h
    digest_deliver_by_minutes: int = 30
    immediate_signal_invalidation: str = "PROMOTED_SIGNAL_AND_EVENT_BEFORE_WINDOW_REGULAR_CLOSE"
    material_update_immediate: str = "SENT_SETUP_AND_ABS_GAP_GT_LAST_SHOWN"

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


LAB_DELIVERY_POLICY_V1 = LabDeliveryPolicy()


def route(ev: dict, decision: str, *, setup_sent: bool, last_shown_abs_gap: float | None,
          signal_open: bool) -> tuple[str | None, str | None, str | None]:
    """(route, info_class, reason) for one V1-decided event. Pure."""
    typ, cls = ev["event_type"], ev.get("classification")
    if typ == "INVALIDATED" and signal_open and decision in ("SELECTED", "NOT_SURFACED_PARENT"):
        return IMMEDIATE, HIGH, R_SIGNAL_INVALIDATED
    if decision != "SELECTED":
        return None, None, None
    if typ in ("NEW", "UPGRADE") and cls in SETUPS:
        return IMMEDIATE, HIGH, R_NEW_SETUP if typ == "NEW" else R_UPGRADE
    if typ == "NEW":
        return DIGEST, LOW, R_NEW_WATCH
    if typ == "INVALIDATED":
        return (IMMEDIATE, HIGH, R_SETUP_INVALIDATED) if setup_sent else (DIGEST, LOW, R_INVALIDATED_UNSENT)
    if typ == "MATERIAL_UPDATE":
        if cls not in SETUPS:
            return DIGEST, LOW, R_WATCH_UPDATE
        if not setup_sent:
            return DIGEST, LOW, R_SETUP_UPDATE_UNSENT
        gap = ev.get("gap_pct")
        if gap is not None and (last_shown_abs_gap is None or abs(gap) > last_shown_abs_gap):
            return IMMEDIATE, MEDIUM, R_SETUP_EXTENDED
        return DIGEST, LOW, R_SETUP_FADE
    return DIGEST, LOW, R_OTHER


def digest_bucket(t: datetime, interval_s: int) -> datetime:
    e = int(t.timestamp())
    return datetime.fromtimestamp(e - e % interval_s, tz=timezone.utc)


# ------------------------------------------------------------------------------------------------------ presentation
FOOTER = "Research only · not a trade · no order"
_DOT = {"BULLISH": "🟢", "BEARISH": "🔴", "WATCH": "👀"}


def _money(x) -> str:
    x = float(x or 0)
    return f"${x / 1e9:.1f}B" if x >= 1e9 else f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}K"


def _direction(ev: dict, cand: dict | None) -> str:
    if ev.get("classification") in SETUPS or ev.get("classification") == "WATCH":
        return ev["classification"]
    fam = (cand or {}).get("family") or ("GAP_UP" if (ev.get("gap_pct") or 0) > 0 else "GAP_DOWN")
    return "BULLISH" if fam == "GAP_UP" else "BEARISH"


def render_lab(ev: dict, cand: dict | None, reason: str | None, *, last_shown_gap: float | None = None,
               signal_sent_utc: str | None = None) -> str:
    """Compact, mobile-first Lab message. Plain text (the worker sends parse_mode=None)."""
    f = _j(ev.get("features_json"))
    sc = _j(ev.get("score_json"))
    typ, cls = ev["event_type"], ev.get("classification")
    title = {"NEW": "NEW SETUP" if cls in SETUPS else "NEW WATCH", "UPGRADE": "SETUP UPGRADE",
             "MATERIAL_UPDATE": "SETUP UPDATE", "INVALIDATED": "SETUP INVALIDATED"}.get(typ, typ.replace("_", " "))
    d = _direction(ev, cand)
    lines = [f"🧪 TALONX LAB — {title}", "",
             f"{'⚫' if typ == 'INVALIDATED' else _DOT.get(d, '•')} {ev['symbol']} · "
             + (f"{d} → INVALIDATED" if typ == "INVALIDATED" else d)]
    total = sc.get("total") if sc else ev.get("score")
    if total is not None:
        lines.append(f"⭐ {float(total):.1f}")
    gap = f.get("gap_pct", ev.get("gap_pct"))
    if gap is not None:
        g = f"{'📈' if gap >= 0 else '📉'} {gap:+.2f}%"
        if typ == "MATERIAL_UPDATE" and last_shown_gap is not None:
            g += f" (was {last_shown_gap:+.2f}%)"
        lines.append(g)
    if f.get("pm_dollars"):
        lines.append(f"💵 {_money(f['pm_dollars'])} session volume")
    cat = ev.get("catalyst")
    if cat and cat != "none found":
        lines.append(f"📰 {cat[:60]}")
    if typ == "UPGRADE" and ev.get("from_state") == "WATCH":
        lines.append(f"⬆️ WATCH → {cls}")
    if typ == "INVALIDATED":
        lines.append(f"✖️ {ev.get('reason') or 'invalidated'}")
        if reason == R_SIGNAL_INVALIDATED:
            lines.append("⚠️ Was a Signal paper opportunity" + (f" ({signal_sent_utc[11:16]}Z)" if signal_sent_utc else ""))
    elif typ == "MATERIAL_UPDATE":
        lines.append("Move extended beyond last update")
    lines += ["", f"{ev['phase']} · data {(ev.get('data_as_of_utc') or '')[11:16]}Z", FOOTER]
    return "\n".join(lines)


DIGEST_LABELS = ((R_SETUP_FADE, "setup updates without a new extreme"),
                 (R_INVALIDATED_UNSENT, "invalidations of never-sent candidates"),
                 (R_NEW_WATCH, "new WATCH"), (R_WATCH_UPDATE, "WATCH updates"),
                 (R_SETUP_UPDATE_UNSENT, "updates of setups never sent"), (R_OTHER, "other"))


def render_digest(*, phase: str, start: datetime, end: datetime, counts: dict[str, int], active: dict[str, int],
                  immediate: dict[str, int], signal_affected: int) -> str:
    n = sum(counts.values())
    lines = [f"🧪 TALONX LAB — {phase} DIGEST", f"{start:%H:%M}–{end:%H:%M}Z", "",
             f"{n} low-information update{'s' if n != 1 else ''} held back"]
    lines += [f"• {counts[k]} {label}" for k, label in DIGEST_LABELS if counts.get(k)]
    lines += ["", f"Active setups: {active.get('BULLISH', 0)} bullish · {active.get('BEARISH', 0)} bearish",
              f"Sent individually: {immediate.get('BULLISH', 0)} new bullish · {immediate.get('BEARISH', 0)} "
              f"new bearish · {immediate.get('INVALIDATED', 0)} invalidated",
              "No open Signal opportunity affected" if not signal_affected
              else f"{signal_affected} Signal candidate(s) past their horizon", "", FOOTER]
    return "\n".join(lines)


def _j(s):
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s) if s else {}
    except ValueError:
        return {}


def to_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
