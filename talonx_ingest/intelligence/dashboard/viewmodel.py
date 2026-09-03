"""
talonx_ingest.intelligence.dashboard.viewmodel
==============================================
Pure presentation transforms: read-API dicts -> render-ready dicts.
Timestamps (UTC + ET + relative), band chips (icon **and** text — never
colour alone), friendly data-quality notes, neutral fact lines from
``what_changed`` / insider activity, evidence-link lists.

No new intelligence. No direction. Every string here is scanned by
``claim_safety`` before it reaches a page.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from talonx_ingest.intelligence.dashboard.config import (
    BAND_ICON,
    BAND_LABEL,
    DISPLAY_TZ_LABEL,
    DISPLAY_TZ_NAME,
    EVENT_TYPE_LABEL,
    friendly_quality_flag,
)
from talonx_ingest.intelligence.domain import EventType, SignificanceBand

try:
    _ET = ZoneInfo(DISPLAY_TZ_NAME)
except Exception:  # noqa: BLE001 - tzdata missing -> fall back to UTC display
    _ET = timezone.utc

_BAND_CSS = {
    "CRITICAL": "band-critical",
    "HIGH": "band-high",
    "MEDIUM": "band-medium",
    "LOW": "band-low",
    None: "band-none",
}
_SESSION_TEXT = {
    "BMO": "before market open",
    "RTH": "regular hours",
    "AMC": "after market close",
    "NON_TRADING_DAY": "non-trading day",
    "UNKNOWN": "session unknown",
}
_SECTION_LABEL = {
    "risk_factors": "Risk Factors",
    "mdna": "MD&A",
    "liquidity": "Liquidity & Capital Resources",
    "whole_document": "whole document",
}


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def fmt_ts(iso: str | None, *, now: datetime | None = None) -> dict:
    d = _parse(iso)
    if d is None:
        return {"utc": "[time unavailable]", "et": "", "rel": "", "iso": None}
    now = now or datetime.now(timezone.utc)
    delta = now - d
    secs = delta.total_seconds()
    if secs < 0:
        rel = "in the future"
    elif secs < 3600:
        rel = f"{int(secs // 60)}m ago"
    elif secs < 86400:
        rel = f"{int(secs // 3600)}h ago"
    else:
        rel = f"{int(secs // 86400)}d ago"
    return {
        "utc": d.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "et": d.astimezone(_ET).strftime("%Y-%m-%d %H:%M ") + DISPLAY_TZ_LABEL,
        "rel": rel,
        "iso": d.astimezone(timezone.utc).isoformat(),
    }


def band_chip(band: str | None) -> dict:
    b = None
    if band:
        try:
            b = SignificanceBand(band)
        except ValueError:
            b = None
    return {
        "band": band or "NOT SCORED",
        "icon": BAND_ICON.get(b, "•"),
        "label": BAND_LABEL.get(b, "NOT YET SCORED"),
        "short": (band or "NOT SCORED"),
        "css": _BAND_CSS.get(band, "band-none"),
    }


def session_text(bucket: str | None) -> str:
    return _SESSION_TEXT.get(bucket or "UNKNOWN", "session unknown")


def event_type_label(value: str) -> str:
    try:
        return EVENT_TYPE_LABEL.get(EventType(value), value.replace("_", " ").title())
    except ValueError:
        return value.replace("_", " ").title()


def quality_notes(flags) -> list[str]:
    seen: list[str] = []
    for f in flags or ():
        note = friendly_quality_flag(f)
        if note not in seen:
            seen.append(note)
    return seen


def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:+.0f}%"


def _money(v) -> str:
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


def what_changed_facts(wc: dict | None) -> list[str]:
    """Neutral fact strings. The magnitude / sign of the FACT is shown;
    no market-direction interpretation, no colour semantics."""
    if not wc:
        return []
    out: list[str] = []
    sections = wc.get("sections") or {}
    for key in ("risk_factors", "mdna", "liquidity"):
        sc = sections.get(key)
        if not sc or sc.get("diff_ratio") is None or sc.get("status") != "FOUND":
            continue
        dr = float(sc["diff_ratio"])
        lbl = _SECTION_LABEL[key]
        if sc.get("exceeds_material_threshold"):
            out.append(f"{lbl}: changed above the frozen material threshold (change magnitude {dr * 100:.0f}%)")
        elif dr >= 0.05:
            out.append(f"{lbl}: change magnitude {dr * 100:.0f}%")
        if sc.get("pct_char_delta") is not None:
            out.append(f"{lbl}: section length change {float(sc['pct_char_delta']):+.0f}%")
    whole = wc.get("whole_document")
    if whole and whole.get("diff_ratio") is not None:
        out.append(
            f"Whole document: change magnitude {float(whole['diff_ratio']) * 100:.0f}%"
            + (" (above frozen threshold)" if whole.get("exceeds_material_threshold") else "")
        )
    for f in wc.get("notable_changes") or []:
        if f.get("kind") == "new_material_passages":
            out.append(f"{int(f.get('value', 0))} new multi-sentence passage(s) in Risk Factors / MD&A")
    by_cat = (wc.get("keywords") or {}).get("by_category") or {}
    for cat in ("negative_risk", "positive_business"):
        c = by_cat.get(cat)
        if c and c.get("total_delta"):
            terms = ", ".join(c.get("terms_increased", [])[:5])
            label = "Risk-term" if cat == "negative_risk" else "Business-term"
            out.append(
                f"{label} lexicon count change {int(c['total_delta']):+d} vs prior filing"
                + (f" (e.g. {terms})" if terms and c["total_delta"] > 0 else "")
            )
    for x in wc.get("xbrl") or []:
        if x.get("status") == "FOUND" and x.get("relative_delta") is not None:
            fld = str(x.get("field", "")).replace("_", " ")
            cmp = {"YOY": "YoY", "QOQ": "QoQ"}.get(str(x.get("comparison", "YoY")).upper(), "YoY")
            out.append(f"Reported {fld} {cmp} change {_pct(x['relative_delta'])}")
    return out


def insider_facts(activity: dict | None) -> list[str]:
    if not activity:
        return []
    out: list[str] = []
    a30 = next((a for a in activity["open_market_aggregates"] if a["window_calendar_days"] == 30), None)
    if a30 and a30["transaction_count"]:
        parts = []
        if a30["distinct_purchasers"]:
            parts.append(f"{a30['distinct_purchasers']} reported open-market purchase(s)")
        if a30["distinct_sellers"]:
            parts.append(f"{a30['distinct_sellers']} reported open-market sale(s)")
        if parts:
            out.append("Insiders (30 days): " + "; ".join(parts))
        if a30["largest_single_transaction_value"] is not None:
            out.append(f"Largest single open-market transaction: {_money(a30['largest_single_transaction_value'])}")
        if a30.get("value_coverage_note"):
            out.append(a30["value_coverage_note"])
    for c in activity["clusters"]:
        side = "purchases" if c["kind"] == "MULTIPLE_OPEN_MARKET_BUYERS" else "sales"
        out.append(
            f"{c['distinct_owners']} distinct insiders reported open-market {side} within {c['window_calendar_days']} days"
        )
    for r in activity["role_subsets"]:
        if r["subset"] in ("CEO", "CFO") and r["window_calendar_days"] == 30:
            act = []
            if r["purchase_count"]:
                act.append(f"{r['purchase_count']} purchase(s)")
            if r["sale_count"]:
                act.append(f"{r['sale_count']} sale(s)")
            if act:
                out.append(f"{r['subset']} reported open-market {', '.join(act)} (30 days)")
    return out


def evidence_links(row: dict) -> list[dict]:
    """(label, url) pairs for a row — deduped, http(s) only."""
    seen: list[str] = []
    out: list[dict] = []

    def _add(label, url):
        if url and str(url).lower().startswith(("http://", "https://")) and url not in seen:
            seen.append(url)
            out.append({"label": label, "url": url})

    _add("SEC filing index", row.get("filing_index_url"))
    _add("Primary document", row.get("primary_document_url"))
    for ev in row.get("evidence", []) or []:
        _add(f"source ({ev.get('transform', 'source')})", ev.get("source_url"))
    for x in row.get("exhibits", []) or []:
        _add(x.get("document_type") or x.get("filename") or "exhibit", x.get("source_url"))
    return out
