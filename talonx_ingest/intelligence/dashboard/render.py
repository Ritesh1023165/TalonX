"""
talonx_ingest.intelligence.dashboard.render
===========================================
Server-side HTML for the Event-Intelligence Dashboard. No JS framework, no
CDN, no build step — a self-contained page with a small inline stylesheet
(responsive card layout, readable contrast, band shown as **text + icon**,
never colour alone). Every dynamic value is HTML-escaped; every finished
page is claim-safety scanned by ``routes``.
"""
from __future__ import annotations

from html import escape as _h

from talonx_ingest.intelligence.dashboard import deeplink
from talonx_ingest.intelligence.dashboard.config import (
    CLAIM_POLICY_SHORT,
    DASHBOARD_VERSION,
    DATA_SOURCES,
    DISCLAIMER_SHORT,
    EVIDENCE_ARTIFACT_LINKS,
    EVIDENCE_PHILOSOPHY,
    EVIDENCE_STATEMENTS,
    NAV_PAGES,
    RULESET_VERSION,
    SIGNIFICANCE_HELP,
)
from talonx_ingest.intelligence.dashboard.viewmodel import (
    band_chip,
    evidence_links,
    event_type_label,
    fmt_ts,
    insider_facts,
    quality_notes,
    session_text,
    what_changed_facts,
)

_CSS = """
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
color:#1a1a1a;background:#f5f6f8}
a{color:#0b5cad}
main{max-width:960px;margin:0 auto;padding:16px}
header.top{background:#12233b;color:#fff;padding:10px 16px}
header.top .brand{font-weight:700;letter-spacing:.02em}
header.top .tag{opacity:.75;font-size:12px}
nav.pages{display:flex;flex-wrap:wrap;gap:4px;max-width:960px;margin:8px auto 0;padding:0 16px}
nav.pages a{padding:6px 12px;border-radius:6px 6px 0 0;background:#e7eaef;text-decoration:none;color:#12233b}
nav.pages a[aria-current=page]{background:#fff;font-weight:700}
h1{font-size:22px;margin:14px 0 4px}
h2{font-size:17px;margin:22px 0 8px;border-bottom:1px solid #dce0e6;padding-bottom:4px}
h3{font-size:15px;margin:12px 0 4px}
.card{background:#fff;border:1px solid #dce0e6;border-radius:8px;padding:12px 14px;margin:10px 0}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
.muted{color:#5b6472;font-size:13px}
.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:700;border:1px solid #bbb}
.band-critical{background:#fdecec;border-color:#e0b4b4;color:#7a1a1a}
.band-high{background:#fdf1e3;border-color:#e0c39a;color:#7a4a12}
.band-medium{background:#fbf7dd;border-color:#d8cf95;color:#6a5f12}
.band-low{background:#eef1f4;border-color:#c4ccd6;color:#3a4453}
.band-none{background:#eef1f4;border-color:#c4ccd6;color:#5b6472}
ul.tight{margin:6px 0;padding-left:20px}
ul.tight li{margin:2px 0}
table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}
th,td{border:1px solid #dce0e6;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f0f2f5}
.wrap-x{overflow-x:auto}
details>summary{cursor:pointer;font-weight:600;margin:4px 0}
.qflag{color:#7a4a12;background:#fdf1e3;border:1px solid #e0c39a;border-radius:4px;padding:1px 6px;font-size:12px;display:inline-block;margin:2px 4px 2px 0}
.empty{padding:24px;text-align:center;color:#5b6472;background:#fff;border:1px dashed #c4ccd6;border-radius:8px}
form.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:end;margin:8px 0}
form.filters label{font-size:12px;color:#5b6472;display:flex;flex-direction:column;gap:2px}
form.filters input,form.filters select{padding:5px 8px;border:1px solid #c4ccd6;border-radius:5px;font:inherit}
form.filters button{padding:6px 14px;border:0;border-radius:5px;background:#12233b;color:#fff;font:inherit;cursor:pointer}
footer.disc{max-width:960px;margin:24px auto 40px;padding:12px 16px;color:#5b6472;font-size:12px;border-top:1px solid #dce0e6}
.freshbar{font-size:13px;padding:8px 12px;border-radius:6px;margin:8px 0}
.fresh-FRESH{background:#e8f3ea;border:1px solid #a9cdb0}
.fresh-STALE,.fresh-UNKNOWN{background:#fdf6e3;border:1px solid #d8cf95}
.fresh-DOWN{background:#fdecec;border:1px solid #e0b4b4}
@media (max-width:640px){main{padding:10px}table{font-size:12px}}
"""


# ---------------------------------------------------------------------------
# shell + small components
# ---------------------------------------------------------------------------
def _nav(active: str) -> str:
    items = []
    for slug, label in NAV_PAGES:
        href = "/" if slug == "today" else f"/{slug}"
        cur = ' aria-current="page"' if slug == active else ""
        items.append(f'<a href="{href}"{cur}>{_h(label)}</a>')
    return '<nav class="pages" aria-label="Sections">' + "".join(items) + "</nav>"


def shell(title: str, active: str, body: str, *, refresh: int | None = None) -> str:
    meta_refresh = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{meta_refresh}<title>{_h(title)} · TalonX Intelligence</title>"
        f"<style>{_CSS}</style></head><body>"
        '<header class="top"><span class="brand">TalonX — Risk &amp; Event Intelligence</span> '
        '<span class="tag">Information, not advice. No predictive claim.</span></header>'
        f"{_nav(active)}"
        f"<main>{body}</main>"
        '<footer class="disc">'
        f"{_h(DISCLAIMER_SHORT)}<br>{_h(CLAIM_POLICY_SHORT)}<br>"
        f'<span class="muted">Ruleset {_h(RULESET_VERSION)} · {_h(DASHBOARD_VERSION)}</span>'
        "</footer></body></html>"
    )


def _band_badge(band: str | None) -> str:
    c = band_chip(band)
    return f'<span class="badge {c["css"]}" aria-label="{_h(c["label"])}">{c["icon"]} {_h(c["short"])}</span>'


def _freshbar(fresh: dict) -> str:
    overall = fresh.get("overall", "UNKNOWN")
    parts = []
    for s in fresh.get("sources", []):
        parts.append(f'{_h(s["source"])}: {_h(s["status"])}')
    counts = fresh.get("counts", {})
    return (
        f'<div class="freshbar fresh-{_h(overall)}">'
        f'<strong>Source freshness: {_h(overall)}</strong> — ' + " · ".join(parts)
        + f' · events {counts.get("events", 0)} · comparisons {counts.get("filing_comparisons", 0)}'
        f' · insider txns {counts.get("insider_transactions", 0)}</div>'
    )


def _qflags(flags) -> str:
    notes = quality_notes(flags)
    if not notes:
        return ""
    return "<div>" + "".join(f'<span class="qflag">{_h(n)}</span>' for n in notes) + "</div>"


def _reasons(row: dict) -> str:
    reasons = row.get("significance_reasons") or []
    if not reasons:
        return ""
    lis = "".join(f"<li>{_h(r)}</li>" for r in reasons)
    notes = row.get("significance_notes") or []
    note_html = ("<p class=\"muted\">" + _h("; ".join(notes)) + "</p>") if notes else ""
    return (
        "<details><summary>Why this is significant</summary>"
        f'<ul class="tight">{lis}</ul>{note_html}'
        f'<p class="muted">{_h(SIGNIFICANCE_HELP)}</p></details>'
    )


def _evlinks(links) -> str:
    if not links:
        return '<p class="muted">No source link available for this item.</p>'
    return "Evidence: " + " · ".join(
        f'<a href="{_h(l["url"])}" rel="noopener noreferrer">{_h(l["label"])}</a>' for l in links
    )


def _facts_ul(facts) -> str:
    if not facts:
        return ""
    return '<ul class="tight">' + "".join(f"<li>{_h(f)}</li>" for f in facts) + "</ul>"


def _event_card(row: dict, *, now=None, show_facts: bool = False) -> str:
    ts = fmt_ts(row.get("accepted_at_utc"), now=now)
    sym = _h(row["symbol"])
    comp = f' <span class="muted">{_h(row.get("company_name") or "")}</span>' if row.get("company_name") else ""
    et = _h(event_type_label(row["event_type"]))
    items = _h(", ".join(row.get("filing_items") or [])) or "—"
    body_facts = ""
    if show_facts:
        wc = row.get("comparison")
        facts = what_changed_facts(wc) if wc else []
        if row.get("insider_activity"):
            facts += insider_facts(row["insider_activity"])
        body_facts = ("<h3>What changed</h3>" + _facts_ul(facts)) if facts else ""
    return (
        '<article class="card">'
        f'<div class="row">{_band_badge(row.get("band"))} '
        f'<a href="{_h(deeplink.company_path(row["symbol"]))}"><strong>{sym}</strong></a>{comp}</div>'
        f'<div class="row"><strong>{et}</strong> <span class="muted">form {_h(row.get("form_type") or "?")} · items {items}</span></div>'
        f'<div class="muted">Accepted {_h(ts["utc"])} / {_h(ts["et"])} · {_h(ts["rel"])} · {_h(session_text(row.get("session_bucket")))}'
        + (f' · score {row["score"]}' if row.get("score") is not None else " · not yet scored")
        + "</div>"
        f"{_reasons(row)}"
        f"{body_facts}"
        f"{_qflags(row.get('data_quality_flags'))}"
        f'<div class="muted">{_evlinks(evidence_links(row))} · '
        f'<a href="{_h(deeplink.event_path(row["event_id"]))}">detail</a> · '
        f'<a href="{_h(deeplink.event_evidence_path(row["event_id"]))}">evidence trace</a></div>'
        "</article>"
    )


def _feed(rows, *, now=None, empty="No events for this view.") -> str:
    if not rows:
        return f'<div class="empty">{_h(empty)}</div>'
    return "".join(_event_card(r, now=now) for r in rows)


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------
def render_today(data: dict) -> str:
    now = None
    b = [f"<h1>Today</h1>", _freshbar(data["freshness"])]
    b.append(f'<p class="muted">Events accepted in the last {data.get("window_hours", 36)} hours, ranked by information significance.</p>')
    b.append("<h2>Attention feed</h2>")
    b.append(_feed(data["attention_feed"], now=now, empty="No material SEC events recorded in the current window."))
    b.append("<h2>Earnings / results</h2>")
    b.append(_feed(data["earnings"], now=now, empty="No earnings events in the current window."))
    b.append("<h2>Material filings</h2>")
    b.append(_feed(data["material_filings"], now=now, empty="No material 8-K / 10-Q / 10-K in the current window."))
    b.append("<h2>Insider activity</h2>")
    b.append(_feed(data["insider_activity"], now=now, empty="No insider ownership filings in the current window."))
    return shell("Today", "today", "".join(b))


def render_watchlist(rows: list[dict], *, symbols: list[str]) -> str:
    b = [f"<h1>Watchlist</h1>",
         '<p class="muted">Ordered by <strong>attention priority</strong> (information significance in the trailing window) — not by price movement and not by any prediction of future value.</p>']
    if not rows:
        b.append('<div class="empty">No watchlist symbols configured. Pass <code>?symbols=AAPL,MSFT</code>.</div>')
        return shell("Watchlist", "watchlist", "".join(b))
    for r in rows:
        chip = _band_badge(r["band"])
        pin = " 📌 pinned" if r.get("pinned") else ""
        quiet = ' <span class="muted">(quiet — no recent event)</span>' if r.get("is_quiet") else ""
        ins = r.get("insider_state") or {}
        ins_txt = (
            f'net open-market {ins.get("net_open_market_value", 0):+,.0f} (30d), '
            f'{ins.get("distinct_purchasers", 0)} buyer(s) / {ins.get("distinct_sellers", 0)} seller(s)'
            + (", cluster" if ins.get("has_cluster") else "")
        ) if ins else "no reported open-market insider activity"
        lmf = r.get("last_material_filing") or {}
        lmf_txt = (
            f'{_h(lmf.get("form_type", ""))} — {lmf.get("notable_change_count", 0)} notable change(s)'
            if lmf else "none recorded"
        )
        earn = fmt_ts(r.get("last_earnings_event_utc"))["utc"] if r.get("last_earnings_event_utc") else "none recorded"
        why = "; ".join(r.get("why") or [])
        b.append(
            '<article class="card">'
            f'<div class="row">{chip} <a href="{_h(deeplink.company_path(r["symbol"]))}"><strong>{_h(r["symbol"])}</strong></a>'
            f' <span class="muted">{_h(r.get("company_name") or "")}</span>{_h(pin)}{quiet}</div>'
            f'<div class="muted">{r.get("distinct_event_types", 0)} distinct event type(s) in window · latest '
            f'{_h(fmt_ts(r.get("latest_event_utc"))["rel"] if r.get("latest_event_utc") else "—")}</div>'
            + (f'<p>Why it\'s here: {_h(why)}</p>' if why else "")
            + f'<div class="muted">Last material filing: {lmf_txt} · Last earnings: {_h(earn)} · Insider: {_h(ins_txt)}</div>'
            "</article>"
        )
    return shell("Watchlist", "watchlist", "".join(b))


def render_company(data: dict) -> str:
    sym = _h(data["symbol"])
    b = [f"<h1>{sym}"
         + (f' <span class="muted">{_h(data.get("company_name") or "")}</span>' if data.get("company_name") else "")
         + "</h1>",
         _freshbar(data["freshness"])]
    if data.get("latest_band"):
        b.append(f'<p>Latest information significance: {_band_badge(data["latest_band"])} '
                 f'(<a href="{_h(deeplink.event_path(data["latest_band_event_id"]))}">latest scored event</a>)</p>')
    lc = data.get("latest_comparison")
    if lc:
        facts = what_changed_facts(lc)
        b.append("<h2>Latest filing comparison</h2>")
        b.append(f'<p class="muted">{_h(lc.get("form_type", ""))} {_h(lc.get("current_accession", ""))} vs prior '
                 f'{_h(lc.get("prior_accession") or "[no prior]")} · '
                 f'<a href="{_h(deeplink.filing_path(lc["comparison_id"]))}">full comparison</a></p>')
        b.append(_facts_ul(facts) or '<p class="muted">No section changes above threshold.</p>')
        b.append(_qflags(lc.get("quality_flags")))
    ia = data.get("insider_activity")
    if ia:
        b.append("<h2>Insider activity</h2>")
        b.append(_facts_ul(insider_facts(ia)) or '<p class="muted">No open-market insider activity in the rolling window.</p>')
        b.append(_insider_tables(ia))
    b.append("<h2>Event timeline</h2>")
    b.append(_feed(data["timeline"], empty="No SEC events recorded for this company."))
    return shell(data["symbol"], "", "".join(b))


def _insider_tables(ia: dict) -> str:
    def _tbl(rows, title):
        if not rows:
            return f'<p class="muted">No {title.lower()} transactions.</p>'
        head = "<tr><th>Date</th><th>Owner</th><th>Role</th><th>Code / class</th><th>Shares</th><th>Price</th><th>Value</th><th>Ownership</th></tr>"
        body = "".join(
            "<tr>"
            f'<td>{_h(fmt_ts(t.get("transaction_date"))["utc"][:10] if t.get("transaction_date") else "—")}</td>'
            f'<td>{_h(t.get("owner_name") or "—")}</td><td>{_h(t.get("owner_role") or "—")}</td>'
            f'<td>{_h((t.get("transaction_code") or "?"))} / {_h(t.get("classification") or "")}</td>'
            f'<td>{"" if t.get("transaction_shares") is None else f"{t['transaction_shares']:,.0f}"}</td>'
            f'<td>{"" if t.get("price_per_share") is None else f"{t['price_per_share']:,.2f}"}</td>'
            f'<td>{"" if t.get("transaction_value") is None else f"{t['transaction_value']:,.0f}"}</td>'
            f'<td>{_h(t.get("ownership_nature") or "—")}</td></tr>'
            for t in rows
        )
        return f'<h3>{_h(title)}</h3><div class="wrap-x"><table>{head}{body}</table></div>'

    return (
        _tbl(ia.get("open_market_transactions", []), "OPEN-MARKET (discretionary P / S)")
        + _tbl(ia.get("other_transactions", []), "OTHER / ADMINISTRATIVE (grants, exercises, tax, gifts)")
    )


def render_filings(data: dict, *, filters: dict) -> str:
    b = ["<h1>Filings</h1>",
         '<p class="muted">Cross-company filing explorer. Significance and facts come from the intelligence stores — no recomputation here.</p>']
    b.append(_filter_form(filters))
    rows = data["items"]
    if not rows:
        b.append('<div class="empty">No material SEC events recorded for this filter.</div>')
        return shell("Filings", "filings", "".join(b))
    head = ("<tr><th>Sig</th><th>Symbol</th><th>Form</th><th>Items</th><th>Accepted (UTC)</th>"
            "<th>Session</th><th>What changed</th><th>Links</th></tr>")
    trs = []
    for r in rows:
        ts = fmt_ts(r.get("accepted_at_utc"))
        wc_link = (
            f'<a href="{_h(deeplink.filing_path(r["comparison_id"]))}">comparison</a>'
            if r.get("has_comparison") else '<span class="muted">n/a</span>'
        )
        trs.append(
            "<tr>"
            f'<td>{_band_badge(r.get("band"))}</td>'
            f'<td><a href="{_h(deeplink.company_path(r["symbol"]))}">{_h(r["symbol"])}</a></td>'
            f'<td>{_h(r.get("form_type") or "")}</td><td>{_h(", ".join(r.get("filing_items") or []))}</td>'
            f'<td>{_h(ts["utc"])}</td><td>{_h(r.get("session_bucket") or "")}</td>'
            f'<td>{wc_link}</td>'
            f'<td><a href="{_h(deeplink.event_path(r["event_id"]))}">detail</a></td>'
            "</tr>"
        )
    b.append(f'<div class="wrap-x"><table>{head}{"".join(trs)}</table></div>')
    if data.get("next_cursor"):
        b.append(f'<p><a href="?{_h(_qs(filters, cursor=data["next_cursor"]))}">Next page →</a></p>')
    return shell("Filings", "filings", "".join(b))


def _qs(filters: dict, **extra) -> str:
    from urllib.parse import urlencode

    q = {k: v for k, v in {**filters, **extra}.items() if v not in (None, "", False)}
    return urlencode(q)


def _filter_form(filters: dict) -> str:
    def _inp(name, label, value):
        return f'<label>{_h(label)}<input name="{name}" value="{_h(str(value or ""))}"></label>'

    bands = "".join(
        f'<option value="{b}"{" selected" if filters.get("band") == b else ""}>{b}</option>'
        for b in ("", "CRITICAL", "HIGH", "MEDIUM", "LOW")
    )
    return (
        '<form class="filters" method="get">'
        + _inp("symbol", "Symbol", filters.get("symbol"))
        + _inp("form", "Form (8-K / 10-Q / 10-K)", filters.get("form"))
        + _inp("item", "8-K item (e.g. 2.05)", filters.get("item"))
        + f'<label>Significance<select name="band">{bands}</select></label>'
        + _inp("since", "Since (YYYY-MM-DD)", filters.get("since"))
        + '<button type="submit">Filter</button>'
        "</form>"
    )


def render_filing_detail(wc: dict) -> str:
    sym = _h(wc.get("symbol", ""))
    b = [f"<h1>Filing comparison — {sym}</h1>"]
    b.append(
        f'<p class="muted">{_h(wc.get("form_type", ""))} '
        f'{_h(wc.get("current_accession", ""))} '
        f'({_h(fmt_ts(wc.get("current_accepted_at_utc"))["utc"])}) vs prior '
        f'{_h(wc.get("prior_accession") or "[no prior comparable filing]")}</p>'
    )
    if not wc.get("has_prior"):
        b.append('<div class="empty">No prior comparable filing — change-vs-prior metrics are not available.</div>')
    whole = wc.get("whole_document")
    if whole:
        b.append("<h2>Whole-document change</h2>")
        b.append(
            f'<p>Change magnitude {float(whole["diff_ratio"]) * 100:.0f}% '
            f'(frozen threshold {float(whole["material_threshold"]) * 100:.0f}%) — '
            f'{"above" if whole.get("exceeds_material_threshold") else "below"} threshold. '
            f'Word count {whole.get("prior_word_count", 0):,} → {whole.get("current_word_count", 0):,} '
            f'({whole.get("word_count_delta", 0):+,}).</p>'
        )
    sections = wc.get("sections") or {}
    if sections:
        b.append("<h2>Section-level changes</h2>")
        head = "<tr><th>Section</th><th>Status</th><th>Change magnitude</th><th>Length change</th><th>Above threshold</th></tr>"
        trs = []
        for key, sc in sections.items():
            dr = sc.get("diff_ratio")
            trs.append(
                "<tr>"
                f"<td>{_h(key)}</td><td>{_h(sc.get('status', ''))}</td>"
                f'<td>{"n/a" if dr is None else f"{dr * 100:.0f}%"}</td>'
                f'<td>{"n/a" if sc.get("pct_char_delta") is None else f"{float(sc['pct_char_delta']):+.0f}%"}</td>'
                f'<td>{"yes" if sc.get("exceeds_material_threshold") else "no"}</td></tr>'
            )
        b.append(f'<div class="wrap-x"><table>{head}{"".join(trs)}</table></div>')
    xbrl = [x for x in (wc.get("xbrl") or []) if x.get("status") == "FOUND" and x.get("relative_delta") is not None]
    if xbrl:
        b.append("<h2>Reported financial changes (first-filed XBRL)</h2>")
        head = "<tr><th>Field</th><th>Comparison</th><th>Prior</th><th>Current</th><th>Change</th></tr>"
        trs = "".join(
            "<tr>"
            f'<td>{_h(str(x.get("field", "")).replace("_", " "))}</td><td>{_h(x.get("comparison", ""))}</td>'
            f'<td>{"" if x.get("prior_value") is None else f"{x['prior_value']:,.0f}"}</td>'
            f'<td>{"" if x.get("current_value") is None else f"{x['current_value']:,.0f}"}</td>'
            f'<td>{x["relative_delta"] * 100:+.0f}%</td></tr>'
            for x in xbrl
        )
        b.append(f'<div class="wrap-x"><table>{head}{trs}</table></div>')
        b.append('<p class="muted">Figures are the company\'s own reported values. Sign is the fact\'s own; it is not a market-direction indicator.</p>')
    kw = (wc.get("keywords") or {}).get("by_category") or {}
    kw_lines = [
        f'{"Risk-term" if c == "negative_risk" else "Business-term"} lexicon: '
        f'{kw[c]["prior_total"]} → {kw[c]["current_total"]} ({kw[c]["total_delta"]:+d})'
        for c in ("negative_risk", "positive_business")
        if kw.get(c)
    ]
    if kw_lines:
        b.append("<h2>Frozen-lexicon keyword counts</h2>")
        b.append(_facts_ul(kw_lines))
    for label, key in (("New passages", "new_passages"), ("Removed passages", "removed_passages")):
        ps = wc.get(key) or []
        if ps:
            b.append(f"<h2>{_h(label)} ({len(ps)})</h2>")
            b.append('<p class="muted">Excerpts below are verbatim text quoted from the SEC filing.</p>')
            b.append("".join(
                f'<details><summary>{_h(key)} #{p.get("index", i)} · {p.get("word_count", 0)} words</summary>'
                f'<blockquote class="filing-excerpt">{_h((p.get("text_excerpt") or "")[:600])}</blockquote></details>'
                for i, p in enumerate(ps[:20])
            ))
    b.append(_qflags(wc.get("quality_flags")))
    ev = wc.get("evidence") or []
    if wc.get("current_document_url") or wc.get("prior_document_url") or ev:
        links = []
        if wc.get("current_document_url"):
            links.append(f'<a href="{_h(wc["current_document_url"])}">current filing</a>')
        if wc.get("prior_document_url"):
            links.append(f'<a href="{_h(wc["prior_document_url"])}">prior filing</a>')
        b.append(f'<p class="muted">Evidence: {" · ".join(links)}</p>')
    return shell(f"Filing comparison — {wc.get('symbol', '')}", "filings", "".join(b))


def render_event_detail(row: dict) -> str:
    ts = fmt_ts(row.get("accepted_at_utc"))
    b = [f'<h1>{_h(row["symbol"])} — {_h(event_type_label(row["event_type"]))}</h1>',
         f'<div class="row">{_band_badge(row.get("band"))} '
         f'<span class="muted">form {_h(row.get("form_type") or "?")} · items {_h(", ".join(row.get("filing_items") or [])) or "—"}</span></div>',
         f'<p class="muted">Accepted {_h(ts["utc"])} / {_h(ts["et"])} · {_h(session_text(row.get("session_bucket")))} · accession {_h(row.get("accession", ""))}'
         + (f' · significance score {row["score"]}' if row.get("score") is not None else " · not yet scored") + "</p>",
         _reasons(row)]
    wc = row.get("comparison")
    if wc:
        b.append("<h2>What changed</h2>")
        b.append(_facts_ul(what_changed_facts(wc)) or '<p class="muted">No section changes above threshold.</p>')
        b.append(f'<p><a href="{_h(deeplink.filing_path(wc["comparison_id"]))}">Full filing comparison →</a></p>')
    ia = row.get("insider_activity")
    if ia:
        b.append("<h2>Insider activity</h2>")
        b.append(_facts_ul(insider_facts(ia)))
        b.append(_insider_tables(ia))
    b.append("<h2>Evidence</h2>")
    b.append(f'<p>{_evlinks(evidence_links(row))}</p>')
    b.append(f'<p><a href="{_h(deeplink.event_evidence_path(row["event_id"]))}">Full evidence trace →</a> · '
             f'<a href="{_h(deeplink.company_path(row["symbol"]))}">{_h(row["symbol"])} company page →</a></p>')
    b.append(_qflags(row.get("data_quality_flags")))
    return shell(f'{row["symbol"]} event', "", "".join(b))


def render_evidence_trace(tr: dict) -> str:
    b = [f'<h1>Evidence trace — {_h(tr["symbol"])}</h1>',
         f'<p class="muted">{_h(event_type_label(tr["event_type"]))} · accession {_h(tr["accession"])} · '
         f'accepted {_h(fmt_ts(tr.get("accepted_at_utc"))["utc"])} · source hash {_h((tr.get("source_hash") or "")[:16])}…</p>']

    def _ev_table(records, title):
        if not records:
            return ""
        head = "<tr><th>Transform</th><th>Provider</th><th>Record id</th><th>Exact timestamp</th><th>Retrieved</th><th>Input hash</th></tr>"
        body = "".join(
            "<tr>"
            f'<td>{_h(r.get("transform", ""))}</td><td>{_h(str(r.get("source_provider", "")))}</td>'
            f'<td>{_h(str(r.get("source_record_id", "")))}</td><td>{_h(str(r.get("exact_timestamp") or ""))}</td>'
            f'<td>{_h(str(r.get("retrieved_at") or ""))}</td><td>{_h((r.get("input_hash") or "")[:16])}</td></tr>'
            for r in records
        )
        return f"<h2>{_h(title)}</h2><div class=\"wrap-x\"><table>{head}{body}</table></div>"

    b.append(_ev_table(tr.get("event_evidence"), "Event provenance"))
    ce = tr.get("comparison_evidence")
    if ce:
        b.append(_ev_table(ce.get("records"), "Filing-comparison provenance"))
    b.append(_ev_table(tr.get("insider_filing_evidence"), "Insider-filing provenance"))
    sig = tr.get("significance")
    if sig:
        b.append("<h2>Significance derivation</h2>")
        b.append(f'<p>Band {_h(sig["band"])} · score {sig["score"]} · ruleset {_h(sig["ruleset_version"])} · '
                 f'input fingerprint {_h(sig["input_fingerprint"][:16])}…</p>')
        head = "<tr><th>+pts</th><th>Reason</th><th>Evidence ref</th></tr>"
        body = "".join(
            f'<tr><td>{r["points"]:+d}</td><td>{_h(r["description"])}</td><td>{_h(str(r.get("evidence_ref") or ""))}</td></tr>'
            for r in sig["reasons"]
        )
        b.append(f'<div class="wrap-x"><table>{head}{body}</table></div>')
    if tr.get("filing_index_url"):
        b.append(f'<p class="muted">SEC: <a href="{_h(tr["filing_index_url"])}">filing index</a>'
                 + (f' · <a href="{_h(tr["primary_document_url"])}">primary document</a>' if tr.get("primary_document_url") else "")
                 + "</p>")
    b.append(f'<p><a href="{_h(deeplink.event_path(tr["event_id"]))}">← back to event</a></p>')
    return shell(f'Evidence — {tr["symbol"]}', "evidence", "".join(b))


def render_evidence_page() -> str:
    b = ["<h1>Evidence &amp; Research</h1>",
         "<p>This page exists so you can trust the descriptive layer: the predictive claims were tested and dropped.</p>",
         "<h2>Research record</h2>", '<ul class="tight">']
    b += [f"<li>{_h(s)}</li>" for s in EVIDENCE_STATEMENTS]
    b.append("</ul>")
    b.append("<h2>What this product does NOT claim</h2>")
    b.append(f"<p>{_h(CLAIM_POLICY_SHORT)}</p>")
    b.append("<h2>Current configuration</h2>")
    b.append(f'<p>Information-significance ruleset: <strong>{_h(RULESET_VERSION)}</strong> (frozen; weights and banding '
             f'from the product design, never fitted to returns).</p>')
    b.append("<h3>Data sources</h3>")
    b.append('<ul class="tight">' + "".join(f"<li>{_h(s)}</li>" for s in DATA_SOURCES) + "</ul>")
    b.append("<h3>Evidence philosophy</h3>")
    b.append(f"<p>{_h(EVIDENCE_PHILOSOPHY)}</p>")
    b.append("<h3>Frozen research artifacts</h3>")
    b.append('<ul class="tight">' + "".join(
        f"<li>{_h(label)} — <code>{_h(path)}</code></li>" for label, path in EVIDENCE_ARTIFACT_LINKS
    ) + "</ul>")
    return shell("Evidence", "evidence", "".join(b))


def render_error(code: int, message: str) -> str:
    b = [f"<h1>{code}</h1>", f'<div class="empty">{_h(message)}</div>',
         '<p><a href="/">← Today</a></p>']
    return shell(str(code), "today", "".join(b))
