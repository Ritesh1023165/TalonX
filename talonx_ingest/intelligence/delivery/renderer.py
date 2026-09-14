"""
talonx_ingest.intelligence.delivery.renderer
============================================
Render a Task 96A ``AlertCard`` (already carrying the Task 96E band +
reasons) into a ``TelegramIntelligenceMessage``.

Deterministic. Consumes the canonical card plus, optionally, the Task 96C
``what_changed`` dict and the Task 96D ``InsiderActivity`` for the fact
lines. **Never** fetches market data, **never** recomputes significance,
**never** emits a direction or an outcome claim. Every message ends with
the standing disclaimer, which is never dropped.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_ingest.intelligence.delivery.config import (
    BAND_ICON,
    BAND_LABEL,
    COMPACT_TARGET,
    DISCLAIMER_SHORT,
    EVENT_TYPE_LABEL,
    EXPANDED_BANDS,
    MAX_DIGEST_ROWS,
    MAX_EVIDENCE_LINKS,
    MAX_FACTS_EXPANDED,
    MAX_REASONS_COMPACT,
    MAX_REASONS_EXPANDED,
    MESSAGE_BUDGET,
    ROUTE_DIGEST,
    ROUTE_IMMEDIATE,
    SECTION_PRIORITY,
    TIER_COMPACT,
    TIER_CONCISE,
    TIER_DIGEST,
    TIER_EXPANDED,
    is_immediate,
)
from talonx_ingest.intelligence.delivery.escape import bold, esc, italic, link
from talonx_ingest.intelligence.delivery.identity import content_hash
from talonx_ingest.intelligence.delivery.render_model import TelegramIntelligenceMessage
from talonx_ingest.intelligence.domain import FreshnessStatus, SessionBucket, SignificanceBand

_SESSION_LABEL = {
    SessionBucket.BMO: "before market open",
    SessionBucket.RTH: "regular hours",
    SessionBucket.AMC: "after market close",
    SessionBucket.NON_TRADING_DAY: "non-trading day",
    SessionBucket.UNKNOWN: "session unknown",
}
_SECTION_KEY_LABEL = {
    "risk_factors": "Risk Factors",
    "mdna": "MD&A",
    "liquidity": "Liquidity & Capital Resources",
    "whole_document": "whole document",
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _iso_min(dt: datetime | None) -> str:
    if dt is None:
        return "time unknown"
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _money(v: float | None) -> str:
    if v is None:
        return "n/a"
    a = abs(v)
    if a >= 1e9:
        return f"${a / 1e9:.2f}bn"
    if a >= 1e6:
        return f"${a / 1e6:.2f}m"
    if a >= 1e3:
        return f"${a / 1e3:.0f}k"
    return f"${a:.0f}"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:+.0f}%"


# ---------------------------------------------------------------------------
# section builders — each returns a list[str] of already-HTML lines
# ---------------------------------------------------------------------------
_COMPANY_MAX = 140
_TITLE_MAX = 300


def _trim(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _identity_lines(card) -> list[str]:
    band = card.significance
    icon = BAND_ICON.get(band, "⚪")
    label = BAND_LABEL.get(band, "SIGNIFICANCE NOT ASSIGNED")
    sess = _SESSION_LABEL.get(card.session_bucket, "session unknown")
    company = f" ({esc(_trim(card.company_name, _COMPANY_MAX))})" if card.company_name else ""
    return [f"{icon} {bold(label)}", f"{bold(card.symbol)}{company} · {esc(sess)}"]


def _event_lines(card, *, expanded: bool) -> list[str]:
    lines = [esc(EVENT_TYPE_LABEL.get(card.event_type, card.event_type.value))]
    if card.title:
        lines.append(esc(_trim(card.title, _TITLE_MAX)))
    lines.append(f"Accepted: {esc(_iso_min(card.timestamp_utc))}")
    if expanded:
        items = ", ".join(card.filing_items) if card.filing_items else "—"
        lines.append(f"Form {esc(card.form_type or '?')} · items {esc(items)}")
    return lines


def _reason_lines(card, *, limit: int) -> list[str]:
    reasons = list(card.significance_reasons)[:limit]
    if not reasons:
        return []
    out = ["Why surfaced:"]
    out.extend(f"• {esc(r)}" for r in reasons)
    return out


def _filing_change_facts(what_changed: dict | None) -> list[str]:
    if not what_changed:
        return []
    facts: list[str] = []
    sections = what_changed.get("sections") or {}
    for key in ("risk_factors", "mdna", "liquidity"):
        sc = sections.get(key)
        if not sc or sc.get("diff_ratio") is None or sc.get("status") != "FOUND":
            continue
        dr = float(sc["diff_ratio"])
        label = _SECTION_KEY_LABEL[key]
        if sc.get("exceeds_material_threshold"):
            facts.append(f"• {esc(label)} changed above the material threshold — change magnitude {dr * 100:.0f}%")
        elif dr >= 0.05:
            facts.append(f"• {esc(label)} change magnitude {dr * 100:.0f}%")
    whole = what_changed.get("whole_document")
    if whole and whole.get("diff_ratio") is not None and whole.get("exceeds_material_threshold"):
        facts.append(f"• Whole-document change magnitude {float(whole['diff_ratio']) * 100:.0f}%")
    passages = [
        f for f in (what_changed.get("notable_changes") or [])
        if f.get("kind") == "new_material_passages"
    ]
    if passages:
        facts.append(f"• {int(passages[0].get('value', 0))} new multi-sentence passage(s) in Risk Factors / MD&A")
    by_cat = (what_changed.get("keywords") or {}).get("by_category") or {}
    neg = by_cat.get("negative_risk")
    if neg and neg.get("total_delta"):
        d = int(neg["total_delta"])
        terms = ", ".join(neg.get("terms_increased", [])[:4])
        extra = f" (e.g. {esc(terms)})" if terms and d > 0 else ""
        facts.append(f"• Risk-term lexicon count change {d:+d} vs the prior filing{extra}")
    for x in (what_changed.get("xbrl") or []):
        if x.get("status") == "FOUND" and x.get("relative_delta") is not None:
            fld = str(x.get("field", "")).replace("_", " ")
            cmp = {"YOY": "YoY", "QOQ": "QoQ"}.get(str(x.get("comparison", "YoY")).upper(), "YoY")
            facts.append(f"• Reported {esc(fld)} {esc(cmp)} change {_pct(x['relative_delta'])}")
    return facts


def _insider_facts(activity) -> list[str]:
    if activity is None:
        return []
    facts: list[str] = []
    agg30 = next(
        (a for a in activity.open_market_aggregates if a.window_calendar_days == 30),
        None,
    )
    if agg30 and agg30.transaction_count:
        parts = []
        if agg30.distinct_purchasers:
            parts.append(f"{agg30.distinct_purchasers} reported open-market purchase(s)")
        if agg30.distinct_sellers:
            parts.append(f"{agg30.distinct_sellers} reported open-market sale(s)")
        if parts:
            facts.append(f"• Insiders (30d): {esc('; '.join(parts))}")
        if agg30.largest_single_transaction_value is not None:
            facts.append(
                f"• Largest single open-market transaction: {esc(_money(agg30.largest_single_transaction_value))}"
            )
    for c in activity.clusters:
        side = "purchases" if c.kind == "MULTIPLE_OPEN_MARKET_BUYERS" else "sales"
        facts.append(
            f"• {c.distinct_owners} distinct insiders reported open-market {esc(side)} within {c.window_calendar_days} days"
        )
    for rs in activity.role_subsets:
        if rs.window_calendar_days == 30 and (rs.purchase_count or rs.sale_count) and rs.subset in ("CEO", "CFO"):
            act = []
            if rs.purchase_count:
                act.append(f"{rs.purchase_count} purchase(s)")
            if rs.sale_count:
                act.append(f"{rs.sale_count} sale(s)")
            facts.append(f"• {esc(rs.subset)} reported open-market {esc(', '.join(act))} (30d)")
    return facts


def _facts_lines(card, what_changed, insider_activity, *, limit: int) -> list[str]:
    facts = _filing_change_facts(what_changed) + _insider_facts(insider_activity)
    # deterministic XBRL / key-number lines from the card's own summary_fields
    sf = card.summary_fields or {}
    for k in ("revenue_reported", "eps_diluted_reported"):
        if sf.get(k):
            facts.append(f"• {esc(k.replace('_', ' '))}: {esc(sf[k])}")
    if not facts:
        return []
    return ["What changed:"] + facts[:limit]


def _quality_lines(card, *, expanded: bool) -> list[str]:
    flags = list(card.data_quality_flags or ())
    fresh = card.freshness
    problem = fresh in (FreshnessStatus.STALE, FreshnessStatus.DOWN, FreshnessStatus.UNKNOWN) or flags
    if not problem:
        return ["Data status: fresh / complete"] if expanded else []
    out: list[str] = []
    if fresh in (FreshnessStatus.STALE, FreshnessStatus.DOWN):
        out.append(f"⚠️ Source feed was {esc(fresh.value.lower())} at emit time")
    elif fresh == FreshnessStatus.UNKNOWN:
        out.append("⚠️ Source freshness unknown at emit time")
    if flags:
        shown = ", ".join(flags[:6])
        out.append(f"⚠️ Data limitations: {esc(shown)}")
    return out


def _evidence_lines(card, *, limit: int) -> tuple[list[str], list[str]]:
    """Returns (rendered_lines, raw_urls)."""
    seen: list[str] = []
    rendered: list[str] = []
    sf = card.summary_fields or {}

    def _add(label: str, url: str | None):
        if url and url not in seen and len(seen) < limit:
            seen.append(url)
            rendered.append(link(label, url))

    _add("SEC filing", card.source_url)
    for ev in card.evidence or ():
        _add("source", getattr(ev, "source_url", None))
    acc = sf.get("accession")
    tail = f" · ref {esc(acc)}" if acc else ""
    if rendered:
        return ["\U0001f517 " + "  ·  ".join(rendered) + tail], seen
    if acc:
        return [f"Source ref: {esc(acc)}"], seen
    return [], seen


def _disclaimer_lines(card) -> list[str]:
    text = card.disclaimer or DISCLAIMER_SHORT
    return [italic("ℹ️ " + text)]


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
def _assemble(sections: dict[str, list[str]], *, budget: int) -> tuple[str, bool, list[str]]:
    """Join sections in priority order; if over budget, drop the
    lowest-priority optional section(s) first, then trim, keeping identity
    + disclaimer always. Returns (text, truncated, dropped)."""
    order = list(SECTION_PRIORITY)
    keep_always = {"identity", "disclaimer"}
    dropped: list[str] = []

    def _build(active: list[str]) -> str:
        blocks = []
        for name in order:
            if name in active and sections.get(name):
                blocks.append("\n".join(sections[name]))
        return "\n\n".join(b for b in blocks if b)

    active = [s for s in order if sections.get(s)]
    text = _build(active)
    if len(text) <= budget:
        return text, False, dropped

    # drop optional sections from lowest priority upward
    for name in reversed(order):
        if name in keep_always:
            continue
        if name in active:
            active.remove(name)
            dropped.append(name)
            text = _build(active)
            if len(text) <= budget:
                return text, True, dropped

    # still too long: hard-trim the body but re-append the disclaimer intact
    disc = "\n".join(sections.get("disclaimer", []))
    ident = "\n".join(sections.get("identity", []))
    room = budget - len(disc) - len(ident) - 20
    body = text
    if room > 0 and len(body) > room:
        body = body[:room].rsplit("\n", 1)[0] + "\n…"
    text = "\n\n".join(p for p in (ident, body, disc) if p)
    return text, True, dropped


def _render(
    card,
    *,
    tier: str,
    what_changed: dict | None,
    insider_activity,
    route_override: str | None = None,
) -> TelegramIntelligenceMessage:
    expanded = tier == TIER_EXPANDED
    reason_limit = MAX_REASONS_EXPANDED if expanded else MAX_REASONS_COMPACT
    fact_limit = MAX_FACTS_EXPANDED if expanded else 3
    ev_limit = MAX_EVIDENCE_LINKS if expanded else 1
    budget = MESSAGE_BUDGET if expanded else COMPACT_TARGET

    ev_lines, ev_urls = _evidence_lines(card, limit=ev_limit)
    sections: dict[str, list[str]] = {
        "identity": _identity_lines(card),
        "event": _event_lines(card, expanded=expanded),
        "reasons": _reason_lines(card, limit=reason_limit),
        "facts": _facts_lines(card, what_changed, insider_activity, limit=fact_limit),
        "quality": _quality_lines(card, expanded=expanded),
        "evidence": ev_lines,
        "disclaimer": _disclaimer_lines(card),
    }
    text, truncated, dropped = _assemble(sections, budget=budget)

    band = card.significance
    # Task 138: `route_override` (from notification_policy.classify_
    # disposition) is a NARROWING/re-routing of the band-derived route
    # only -- e.g. a HIGH-band card without a substantive trigger routes
    # DIGEST instead of the band-implied IMMEDIATE. Never widens a route
    # the band itself would not have allowed.
    route = ROUTE_IMMEDIATE if (band is not None and is_immediate(band)) else ROUTE_DIGEST
    if route_override in (ROUTE_IMMEDIATE, ROUTE_DIGEST):
        route = route_override
    return TelegramIntelligenceMessage(
        card_id=card.alert_id,
        event_id=card.event_id,
        symbol=card.symbol,
        band=band,
        tier=tier,
        route=route,
        text=text,
        content_hash=content_hash(text),
        char_len=len(text),
        truncated=truncated,
        dropped_sections=tuple(dropped),
        evidence_urls=tuple(ev_urls),
        disclaimer_present="ℹ️" in text,
    )


def render_concise(card, *, disposition_reason: str | None = None, now: datetime | None = None):
    """Task 138 Workstream 2: the compact IMMEDIATE-disposition shape --
    see docs/research/NOTIFICATION_POLICY.md §7. Target 3-5 short lines;
    always route=IMMEDIATE (this shape is only ever used for a card the
    notification policy already decided warrants interruption -- it does
    not itself re-derive eligibility). Full facts, aggregation windows,
    and the filing link move to the reply-for-details response (Workstream
    3), not this initial push. ``disposition_reason`` (the specific
    substantive trigger notification_policy.classify_disposition found)
    is preferred over the generic first significance reason when given,
    so the line always names the CONCRETE thing that qualified, never a
    vague "significant filing" placeholder.

    "Source" shows the event's own accepted_at_utc and its age computed
    at RENDER time (a real wall-clock read here, not a DB-read timestamp
    presented as fresh) -- kept explicitly labelled as source age only;
    it does not claim anything about the SEPARATE send-time freshness
    check (Task 136B), which runs independently right before delivery."""
    now = now or datetime.now(timezone.utc)
    reasons = list(card.significance_reasons)
    summary = (disposition_reason or (reasons[0] if reasons else None)
              or EVENT_TYPE_LABEL.get(card.event_type, card.event_type.value))
    summary = _trim(summary, 180)

    ts = card.timestamp_utc
    if ts is not None:
        ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        age_s = (now - ts).total_seconds()
        age_h = age_s / 3600.0
        age_txt = f"{age_h:.1f}h" if age_h >= 1 else f"{max(0, age_s) / 60:.0f}m"
        source_line = f"Source: {_iso_min(ts)} (source age: {age_txt})"
    else:
        source_line = "Source: time unknown"

    event_label = EVENT_TYPE_LABEL.get(card.event_type, card.event_type.value)
    disclaimer = card.disclaimer or DISCLAIMER_SHORT
    lines = [
        f"[INFO] {bold(esc(card.symbol))} — {esc(event_label)}",
        esc(summary),
        esc(source_line),
        italic('Reply "details" for facts and filing link.'),
        italic("ℹ️ " + esc(disclaimer)),
    ]
    text = "\n".join(lines)
    ev_urls = [card.source_url] if card.source_url else []
    return TelegramIntelligenceMessage(
        card_id=card.alert_id,
        event_id=card.event_id,
        symbol=card.symbol,
        band=card.significance,
        tier=TIER_CONCISE,
        route=ROUTE_IMMEDIATE,
        text=text,
        content_hash=content_hash(text),
        char_len=len(text),
        truncated=False,
        dropped_sections=(),
        evidence_urls=tuple(ev_urls),
        disclaimer_present=True,   # policy doc §7: boilerplate FACTS move
                                    # to the details reply; the standing
                                    # "information, not advice" safety
                                    # disclaimer itself is never dropped,
                                    # matching this module's own existing
                                    # invariant -- 5 lines total, still
                                    # within the compact target.
    )


def render_compact(card, *, what_changed: dict | None = None, insider_activity=None,
                   route_override: str | None = None):
    return _render(card, tier=TIER_COMPACT, what_changed=what_changed,
                   insider_activity=insider_activity, route_override=route_override)


def render_expanded(card, *, what_changed: dict | None = None, insider_activity=None,
                    route_override: str | None = None):
    return _render(card, tier=TIER_EXPANDED, what_changed=what_changed,
                   insider_activity=insider_activity, route_override=route_override)


def render_for_card(card, *, what_changed: dict | None = None, insider_activity=None,
                    route_override: str | None = None):
    """Pick the tier by band: HIGH / CRITICAL → expanded, else compact."""
    tier = TIER_EXPANDED if card.significance in EXPANDED_BANDS else TIER_COMPACT
    return _render(card, tier=tier, what_changed=what_changed,
                   insider_activity=insider_activity, route_override=route_override)


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------
def render_digest(cards, *, title: str = "TalonX Intelligence digest", now: datetime | None = None):
    """One message: a significance-ranked one-line list of held (LOW/MEDIUM)
    events. ``cards`` is an iterable of ``AlertCard``."""
    now = now or datetime.now(timezone.utc)
    rows = list(cards)
    rank = {
        SignificanceBand.CRITICAL: 0, SignificanceBand.HIGH: 1,
        SignificanceBand.MEDIUM: 2, SignificanceBand.LOW: 3, None: 4,
    }
    rows.sort(key=lambda c: (rank.get(c.significance, 4), c.symbol, c.event_id))
    shown = rows[:MAX_DIGEST_ROWS]

    lines = [f"{bold(title)} · {esc(_iso_min(now))}", f"{len(rows)} held event(s)"]
    for c in shown:
        icon = BAND_ICON.get(c.significance, "⚪")
        et = EVENT_TYPE_LABEL.get(c.event_type, c.event_type.value)
        lines.append(f"{icon} {bold(c.symbol)} — {esc(et)}")
    if len(rows) > len(shown):
        lines.append(esc(f"+ {len(rows) - len(shown)} more — open the dashboard"))
    lines.append("")
    lines.append(italic("ℹ️ " + DISCLAIMER_SHORT))
    text = "\n".join(lines)

    first = shown[0] if shown else None
    return TelegramIntelligenceMessage(
        card_id=f"digest:{_iso_min(now)}",
        event_id=f"digest:{_iso_min(now)}",
        symbol=(first.symbol if first else "DIGEST"),
        band=None,
        tier=TIER_DIGEST,
        route=ROUTE_DIGEST,
        text=text,
        content_hash=content_hash(text),
        char_len=len(text),
        truncated=len(rows) > len(shown),
        dropped_sections=(),
        evidence_urls=(),
        disclaimer_present=True,
    )
