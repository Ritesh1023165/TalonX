"""Research-review alert RESEARCH_REVIEW_EXPANDABLE_V3 (owner-approved 2026-10-17, presentation only): a short visible
summary plus the unchanged V2 text in a Telegram expandable quote (parse_mode=HTML). Fixtures and local renders only."""
from __future__ import annotations

import asyncio
import html
import re
import sqlite3
from types import SimpleNamespace

from talonx_opportunity import promotion as P
from tests.test_review_alert_compact_template import FEATS, NOW, Client, _setup, ctx, q, rich_seed

ALLOWED_TAGS = {"<b>", "</b>", "<blockquote expandable>", "</blockquote>"}


def tags(txt: str) -> list[str]:
    return re.findall(r"<[^>]*>", txt)


def visible(txt: str) -> str:
    """What Telegram counts against the 4096 limit: tags removed, entities decoded."""
    return html.unescape(re.sub(r"<[^>]*>", "", txt))


def test_summary_is_five_lines_with_the_same_values_and_every_warning_visible():
    txt = P.render_review_expandable(q(), NOW, "OPPORTUNITY_PROMOTION_V1", ctx())
    head, details = txt.split(P.HTML_DETAILS_OPEN)
    lines = head.rstrip("\n").split("\n")
    assert lines == [
        "🔎 <b>TWLO</b> · 🟢 ▲ UP +3.02% · UNVALIDATED",
        "💵 $284.08 at 11:48 ET · 15-min delayed, not live",
        "📊 0.5× ATR · vol 14.0% of 20d avg · 1.27% above prior-day high",
        "🧮 Score 65.9/100 · not a probability",
        "⚠️ Paper results negative after costs · review only · no order",
    ]
    assert details.endswith("</blockquote>")


def test_details_are_exactly_the_v2_text_without_its_header():
    c = ctx(cat="1 other SEC filing(s): 144", prior="2026-10-08")
    v2 = P.render_review_compact(q(), NOW, "P", c)
    txt = P.render_review_expandable(q(), NOW, "P", c)
    body = txt.split(P.HTML_DETAILS_OPEN, 1)[1].removesuffix("</blockquote>")
    assert html.unescape(body) == v2.split("\n", 1)[1]
    for kept in ("Previous close: $275.77", "Form 144 proposed-sale notice", "🔁 Earlier alert for TWLO delivered",
                 "negative after costs", "not a buy instruction", "🔖 Reference OPPORTUNITY_ENGINE:2026-10-09:TWLO"):
        assert kept in visible(txt)


def test_every_dynamic_value_is_escaped_and_only_allowed_tags_appear():
    nasty = q(symbol="BRK.B<b>&_*[x]</blockquote>")
    txt = P.render_review_expandable(nasty, NOW, "P<i>", ctx(cat="8-K <script>&amp;", universe="U&<>"))
    assert set(tags(txt)) <= ALLOWED_TAGS
    assert tags(txt).count("<blockquote expandable>") == 1 and tags(txt).count("</blockquote>") == 1
    assert txt.endswith("</blockquote>") and tags(txt)[:2] == ["<b>", "</b>"]
    assert "BRK.B&lt;b&gt;&amp;_*[x]&lt;/blockquote&gt;" in txt
    assert "BRK.B<b>&_*[x]</blockquote>" in visible(txt)


def test_sub_display_move_renders_escaped_less_than():
    txt = P.render_review_expandable(q(), NOW, "P", ctx(feats={**FEATS, "gap_pct": 0.004}))
    assert "UP &lt;0.01%" in txt and "UP <0.01%" not in txt.replace("&lt;", "")


def test_missing_evidence_renders_unknown_and_never_raises():
    txt = P.render_review_expandable({"promotion_id": None}, NOW, "P", None)
    assert txt.startswith("🔎 <b>UNKNOWN</b> · ❔ DIRECTION UNKNOWN · UNVALIDATED\n💵 UNKNOWN at UNKNOWN · delayed")
    assert "📊 Reasons UNKNOWN" in txt and "🧮 Score UNKNOWN" in txt and P.HTML_DETAILS_OPEN in txt
    part = P.render_review_expandable(q(), NOW, "P", ctx(feats={"gap_pct": 2.0}))
    assert "📊 ATR multiple UNKNOWN · volume UNKNOWN · prior-day range UNKNOWN" in part


def test_worst_case_stays_under_the_telegram_limit():
    worst = ctx(cat="; ".join([f"8-K items 1.01, 2.03, 7.01, 8.01, 9.01 filed 2026-10-0{i}" for i in range(1, 9)]
                              + ["9 other SEC filing(s): 144, 3, 4, 5, 8-A12B, ARS, DEF 14A, DEFA14A, SC 13G"]),
                prior="2026-10-08")
    txt = P.render_review_expandable(q(symbol="BRK.B<b>&_*[x]"), NOW, "P", worst)
    assert len(visible(txt)) < 4096 and len(txt) < 4096
    assert len(visible(P.render_review_expandable(q(), NOW, "P", ctx()))) < 1500


# ------------------------------------------------------------------------------------------------- send adapter
class Inner:
    def __init__(self, configured=True):
        self.calls = []
        if configured is not None:
            self.is_configured = configured

    async def send(self, text, parse_mode=None, **kw):
        self.calls.append((text, parse_mode, kw))
        return "msg"


def test_adapter_uses_html_only_for_v3_payloads_and_passes_text_unchanged():
    inner = Inner()
    a = P.ExpandableHtmlClient(inner)
    v3 = P.render_review_expandable(q(), NOW, "P", ctx())
    v2 = P.render_review_compact(q(symbol="X<y>"), NOW, "P", ctx())         # e.g. a row enqueued before deployment
    minimal = P.render_review_minimal(q(), "P")
    for t in (v3, v2, minimal):
        assert asyncio.run(a.send(t, parse_mode=None)) == "msg"
    assert [(t, pm) for t, pm, _ in inner.calls] == [(v3, "HTML"), (v2, None), (minimal, None)]


def test_adapter_delegates_is_configured():
    assert P.ExpandableHtmlClient(Inner(True)).is_configured is True
    assert P.ExpandableHtmlClient(Inner(False)).is_configured is False
    assert P.ExpandableHtmlClient(Inner(None)).is_configured is True       # same default as the worker's getattr


def test_live_path_without_tracing_still_sends_html_once(tmp_path, monkeypatch):
    c = Client()
    pr, tt = _setup(tmp_path, monkeypatch, c)
    monkeypatch.setattr(pr, "_traced_client", lambda: None)               # tracing unavailable
    rich_seed(tmp_path, "BBB", tt(15))
    pr.tick()
    ob = sqlite3.connect(P.signal_outbox_path(tmp_path))
    payload, state, prov = ob.execute("SELECT payload_text, state, provenance_json FROM "
                                      "ops_notification_outbox").fetchone()
    assert state == "SENT" and c.sent == [(payload, "HTML")]
    assert '"template_version": "RESEARCH_REVIEW_EXPANDABLE_V3"' in prov


def test_presentation_fault_falls_back_to_plain_minimal_sent_without_html(tmp_path, monkeypatch):
    c = Client()
    pr, tt = _setup(tmp_path, monkeypatch, c)

    def boom(*a, **k):
        raise RuntimeError("render fault")
    monkeypatch.setattr(P, "render_review_expandable", boom)
    rich_seed(tmp_path, "CCC", tt(15))
    pr.tick()
    payload, state = sqlite3.connect(P.signal_outbox_path(tmp_path)).execute(
        "SELECT payload_text, state FROM ops_notification_outbox").fetchone()
    assert state == "SENT" and c.sent == [(payload, None)] and P.HTML_DETAILS_OPEN not in payload
    assert "negative after costs" in payload and "not a buy instruction" in payload


def test_promotion_decisions_do_not_depend_on_the_template(tmp_path, monkeypatch):
    """Same seed, V2 vs V3 renderer: identical promotion rows (state, reason, score, reference) -- presentation only."""
    rows = []
    for v3 in (False, True):
        root = tmp_path / ("v3" if v3 else "v2")
        root.mkdir()
        mp = monkeypatch
        c = Client()
        pr, tt = _setup(root, mp, c)
        if not v3:
            mp.setattr(P, "render_review_expandable", lambda p, n, pol, cx=None: P.render_review_compact(p, n, pol, cx))
        rich_seed(root, "DDD", tt(15))
        pr.tick()
        con = sqlite3.connect(root / "promotion.db")
        rows.append(con.execute("SELECT promotion_id, state, reason_code, score, reference_price, queue_rank "
                                "FROM promotions ORDER BY promotion_id").fetchall())
        mp.undo()
    assert rows[0] == rows[1] and rows[0]
    assert SimpleNamespace  # keep import used
