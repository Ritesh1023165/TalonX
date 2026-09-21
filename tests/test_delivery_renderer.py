"""
tests/test_delivery_renderer.py
-------------------------------
Task 96F -- rendering: compact / expanded / digest, band presentation,
event-type labels, 96C / 96D fact rendering, evidence, quality, disclaimer,
size policy, markup safety.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from talonx_ingest.intelligence.domain import EventType, SignificanceBand
from talonx_ingest.intelligence.delivery.claim_safety import scan_rendered
from talonx_ingest.intelligence.delivery.config import (
    BAND_LABEL,
    DISCLAIMER_SHORT,
    MESSAGE_BUDGET,
    ROUTE_DIGEST,
    ROUTE_IMMEDIATE,
)
from talonx_ingest.intelligence.delivery.renderer import (
    render_compact,
    render_digest,
    render_expanded,
    render_for_card,
)
from _delivery_helpers import NOW, make_card, mk_comparison, mk_event, mk_insider_activity


# ---------------------------------------------------------------------------
# structure + disclaimer + claim safety
# ---------------------------------------------------------------------------
def test_compact_has_identity_reasons_evidence_disclaimer():
    card, _ = make_card(on_watchlist=True)
    m = render_compact(card)
    assert m.tier == "COMPACT"
    assert BAND_LABEL[card.significance] in m.text
    assert card.symbol in m.text
    assert "Why surfaced:" in m.text
    assert DISCLAIMER_SHORT in m.text
    assert m.disclaimer_present
    assert scan_rendered(m.text) == []


def test_expanded_adds_form_items_and_more_reasons():
    card, wc = make_card(
        event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(),
        comparison=None, on_watchlist=True, pinned=True,
    )
    m = render_expanded(card)
    assert "Form 10-Q" in m.text
    # expanded shows up to 4 reasons; compact only 2
    assert m.text.count("• ") >= render_compact(card).text.count("• ")


def test_disclaimer_never_dropped_even_when_truncated():
    card, wc = make_card(
        event_type=EventType.ANNUAL_FILING, form_type="10-K", items=(),
        comparison=mk_comparison(
            event=mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=()),
            rf_diff=0.7, mdna_diff=0.5, liq_diff=0.4, whole_diff=0.5,
            revenue_rel_delta=0.6, eps_rel_delta=-0.9, neg_kw_delta=40,
        ),
        pinned=True, on_watchlist=True,
    )
    m = render_expanded(card)
    assert DISCLAIMER_SHORT in m.text
    assert len(m.text) <= MESSAGE_BUDGET + 40


# ---------------------------------------------------------------------------
# band presentation -- priority only, no direction
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "et,items,expect_band_word",
    [
        (EventType.SHAREHOLDER_VOTE_RESULT, ("5.07",), "LOW"),
        (EventType.EARNINGS_RESULTS, ("2.02",), None),  # band varies; just check label text form
    ],
)
def test_band_label_is_significance_not_conviction(et, items, expect_band_word):
    card, _ = make_card(event_type=et, items=items, age_hours=100)
    m = render_compact(card)
    assert "INFORMATION SIGNIFICANCE" in m.text
    for bad in ("CONVICTION", "STRONG SIGNAL", "BUY", "SELL", "BULLISH", "BEARISH"):
        assert bad not in m.text.upper().replace("INFORMATION SIGNIFICANCE", "")


def test_render_for_card_picks_tier_by_band():
    low, _ = make_card(event_type=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",), age_hours=100)
    assert render_for_card(low).tier == "COMPACT"
    hi_ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=())
    hi_card, _ = make_card(
        event_type=EventType.ANNUAL_FILING, form_type="10-K", items=(),
        comparison=mk_comparison(event=hi_ev, rf_diff=0.7, mdna_diff=0.4), pinned=True,
    )
    assert render_for_card(hi_card).tier == "EXPANDED"


# ---------------------------------------------------------------------------
# event types
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "et,items,form",
    [
        (EventType.EARNINGS_RESULTS, ("2.02",), "8-K"),
        (EventType.MATERIAL_AGREEMENT, ("1.01",), "8-K"),
        (EventType.ACQUISITION_DISPOSITION, ("2.01",), "8-K"),
        (EventType.DEBT_FINANCING, ("2.03",), "8-K"),
        (EventType.RESTRUCTURING, ("2.05",), "8-K"),
        (EventType.EXECUTIVE_CHANGE, ("5.02",), "8-K"),
        (EventType.REGULATION_FD, ("7.01",), "8-K"),
        (EventType.OTHER_MATERIAL_EVENT, ("8.01",), "8-K"),
        (EventType.QUARTERLY_FILING, (), "10-Q"),
        (EventType.ANNUAL_FILING, (), "10-K"),
        (EventType.INSIDER_TRANSACTION, (), "4"),
    ],
)
def test_every_taxonomy_type_renders_a_human_label(et, items, form):
    card, _ = make_card(event_type=et, items=items, form_type=form)
    m = render_compact(card)
    assert m.text  # renders
    assert scan_rendered(m.text) == []


# ---------------------------------------------------------------------------
# filing comparison rendering (Phase 6)
# ---------------------------------------------------------------------------
def test_filing_change_facts_rendered_as_facts_not_direction():
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=())
    card, wc = make_card(
        event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(),
        comparison=mk_comparison(
            event=ev, rf_diff=0.44, mdna_diff=0.2, revenue_rel_delta=0.24, neg_kw_delta=6
        ),
    )
    m = render_expanded(card, what_changed=wc)
    assert "Risk Factors changed above the material threshold" in m.text
    assert "Reported revenue YoY change +24%" in m.text
    assert "Risk-term lexicon count change +6" in m.text
    # no directional adjective on the debt/revenue fact
    assert "bearish" not in m.text.lower() and "bullish" not in m.text.lower()
    assert scan_rendered(m.text) == []


def test_negative_xbrl_delta_is_a_fact_not_a_warning():
    ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=())
    card, wc = make_card(
        event_type=EventType.ANNUAL_FILING, form_type="10-K", items=(),
        comparison=mk_comparison(event=ev, revenue_rel_delta=-0.35),
    )
    m = render_expanded(card, what_changed=wc)
    assert "Reported revenue YoY change -35%" in m.text
    assert scan_rendered(m.text) == []


# ---------------------------------------------------------------------------
# insider rendering (Phase 7)
# ---------------------------------------------------------------------------
def test_insider_cluster_and_value_rendered_descriptively():
    card, _ = make_card(
        event_type=EventType.INSIDER_TRANSACTION, form_type="4", items=(),
        insider_activity=mk_insider_activity(largest_value=2_300_000.0, cluster=True),
    )
    m = render_expanded(card, insider_activity=mk_insider_activity(largest_value=2_300_000.0, cluster=True))
    assert "distinct insiders reported open-market sales within 30 days" in m.text
    assert "Largest single open-market transaction: $2.30m" in m.text
    for bad in ("smart money", "insider signal", "bullish insider", "bearish insider"):
        assert bad not in m.text.lower()
    assert scan_rendered(m.text) == []


# ---------------------------------------------------------------------------
# significance reasons (Phase 8)
# ---------------------------------------------------------------------------
def test_reasons_capped_and_verbatim_from_card():
    card, _ = make_card(
        event_type=EventType.RESTRUCTURING, items=("2.05",), on_watchlist=True, pinned=True,
    )
    compact = render_compact(card)
    expanded = render_expanded(card)
    assert compact.text.count("• ") <= 2
    assert expanded.text.count("• ") <= 4
    # the reasons shown are a prefix of the card's own list (not recomputed)
    for r in card.significance_reasons[:2]:
        assert r in compact.text


# ---------------------------------------------------------------------------
# quality / freshness (Phase 10)
# ---------------------------------------------------------------------------
def test_quality_warning_shown_when_flags_present():
    card, _ = make_card(quality_flags=("missing_acceptance_timestamp",))
    m = render_compact(card)
    assert "Data limitations" in m.text


def test_clean_compact_has_no_data_status_clutter():
    card, _ = make_card()
    assert "Data status" not in render_compact(card).text
    assert "Data status: fresh" in render_expanded(card).text


# ---------------------------------------------------------------------------
# evidence (Phase 9)
# ---------------------------------------------------------------------------
def test_every_message_has_a_source_reference():
    card, _ = make_card()
    m = render_compact(card)
    assert ("sec.gov" in m.text) or ("Source ref:" in m.text) or ("ref " in m.text)
    assert m.evidence_urls and m.evidence_urls[0].startswith("https://")


# ---------------------------------------------------------------------------
# size policy (Phase 17)
# ---------------------------------------------------------------------------
def test_company_name_and_title_are_capped_defensively():
    card, _ = make_card(company="Z" * 5000)
    m = render_compact(card)
    assert len(m.text) < MESSAGE_BUDGET
    assert "…" in m.text  # the name was trimmed


def test_assemble_drops_low_priority_sections_first_keeps_identity_and_disclaimer():
    from talonx_ingest.intelligence.delivery.renderer import _assemble

    big = "\n".join(["fact line " + "y" * 60] * 40)
    sections = {
        "identity": ["ID LINE"],
        "event": ["EVENT LINE"],
        "reasons": ["Why surfaced:", "• r1", "• r2"],
        "facts": ["What changed:", big],
        "quality": ["⚠️ something"],
        "evidence": ["🔗 link"],
        "disclaimer": ["ℹ️ disclaimer stays"],
    }
    text, truncated, dropped = _assemble(sections, budget=400)
    assert truncated
    assert "ID LINE" in text and "ℹ️ disclaimer stays" in text
    # identity + disclaimer are never dropped
    assert "identity" not in dropped and "disclaimer" not in dropped
    # lowest-priority optional section goes first
    assert dropped[0] == "evidence"
    assert "facts" in dropped
    assert len(text) <= 400 + 40
    # deterministic
    assert _assemble(sections, budget=400)[0] == text


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------
def test_route_follows_band():
    low, _ = make_card(event_type=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",), age_hours=100)
    assert render_compact(low).route == ROUTE_DIGEST
    ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=())
    hi, wc = make_card(
        event_type=EventType.ANNUAL_FILING, form_type="10-K", items=(),
        comparison=mk_comparison(event=ev, rf_diff=0.7, mdna_diff=0.4), pinned=True,
    )
    assert render_expanded(hi, what_changed=wc).route == ROUTE_IMMEDIATE


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------
def test_digest_is_ranked_and_capped_with_disclaimer():
    cards = []
    for i, (et, it) in enumerate(
        [
            (EventType.SHAREHOLDER_VOTE_RESULT, ("5.07",)),
            (EventType.OTHER_MATERIAL_EVENT, ("8.01",)),
            (EventType.EXECUTIVE_CHANGE, ("5.02",)),
        ]
    ):
        c, _ = make_card(event_type=et, items=it, symbol=f"SYM{i}", age_hours=50)
        cards.append(c)
    d = render_digest(cards, now=NOW)
    assert d.tier == "DIGEST"
    assert "held event(s)" in d.text
    assert DISCLAIMER_SHORT in d.text
    assert scan_rendered(d.text) == []
