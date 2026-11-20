"""Review alerts are AWARENESS ONLY (owner decision 2026-11-20): every message that can reach the Signal bot carries an
explicit awareness-only label and no trade-prompt wording (no buy/sell language, entry or exit timing, targets, stops,
"opportunity"/"setup"/"actionable" framing). Exempt: the two provenance lines that carry fingerprinted internal
identifiers (policy ``OPPORTUNITY_PROMOTION_V1``, reference ``OPPORTUNITY_ENGINE:...``), which cannot be renamed."""
from __future__ import annotations

import html
import re

import pytest

from talonx_opportunity import promotion as P
from tests.test_review_alert_compact_template import NOW, ctx, q

TRADE_WORDS = re.compile(r"\b(buy|buying|sell|selling|entry|entries|enter|exit|exits|target|targets|stop|stops|"
                         r"opportunit\w*|setup|setups|actionable|signal)\b", re.IGNORECASE)


def visible_lines(txt: str) -> list[str]:
    return html.unescape(re.sub(r"<[^>]*>", "", txt)).split("\n")


def renders():
    full = ctx(cat="1 other SEC filing(s): 144", prior="2026-10-08")
    return {"expandable": P.render_review_expandable(q(), NOW, "OPPORTUNITY_PROMOTION_V1", full),
            "expandable_no_evidence": P.render_review_expandable(q(), NOW, "OPPORTUNITY_PROMOTION_V1", None),
            "compact_body": P.render_review_compact(q(), NOW, "OPPORTUNITY_PROMOTION_V1", full),
            "minimal": P.render_review_minimal(q(), "OPPORTUNITY_PROMOTION_V1")}


@pytest.mark.parametrize("name", ["expandable", "expandable_no_evidence", "compact_body", "minimal"])
def test_no_trade_prompt_wording(name):
    lines = [ln for ln in visible_lines(renders()[name]) if not ln.startswith(("🔖 Reference", "🏷️ Policy"))]
    hits = [(ln, m.group(0)) for ln in lines for m in TRADE_WORDS.finditer(ln)]
    assert hits == []


@pytest.mark.parametrize("name", ["expandable", "expandable_no_evidence", "minimal"])
def test_awareness_only_label_is_visible_first(name):
    first = visible_lines(renders()[name])[0]
    assert "AWARENESS ONLY" in first


def test_collapsed_summary_states_awareness_only_and_tested_no_edge():
    head = renders()["expandable"].split(P.HTML_DETAILS_OPEN)[0]
    assert "not a trade prompt" in head and "no edge after costs" in head


def test_template_version_is_v4_awareness():
    assert P.REVIEW_TEMPLATE_VERSION == "RESEARCH_REVIEW_AWARENESS_V4"
